"""Public Core stream boundary with an isolated platform output sink."""

import asyncio
import json
import time
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.interaction.expression_agent import (
    PERSONA_TENDENCY_DIMENSIONS,
    InteractionExpressionError,
    PersonaExpressionRequest,
    PersonaSegmentStreamParser,
)
from astrbot.core.interaction.output_controller import InteractionOutputController
from astrbot.core.interaction.turn_state import (
    get_interaction_turn_delivery_receipts,
    get_interaction_turn_immediate_persona_segments,
    get_interaction_turn_personal_emitted_monotonic,
    get_interaction_turn_visible_outputs,
    has_delivered_motion_output,
    set_interaction_turn_runtime_config,
)
from astrbot.core.message.incremental_text import (
    IncrementalTextError,
    IncrementalTextPreparer,
)
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.voice.pcm_stream import PCMStreamFrame


class OutputSink:
    def __init__(
        self,
        *,
        deliver_motion=False,
        fail_text=False,
        fail_completion=False,
    ):
        self.deliver_motion = deliver_motion
        self.fail_text = fail_text
        self.fail_completion = fail_completion
        self.delivered_motion_segment_indexes = frozenset()
        self.text = []
        self.ends = []

    def require_complete(self):
        if self.fail_completion:
            raise RuntimeError("incremental resource closure is incomplete")

    async def start_stream(self, resource, *, segment_index, message_id):
        pass

    async def append_text(self, segment_index, text):
        if self.fail_text:
            raise RuntimeError("incremental text transport failed")
        self.text.append(text)

    async def end_stream(self, resource, segment_index, **kwargs):
        self.ends.append((resource, segment_index, kwargs.get("status", "completed")))


class IncrementalEvent(AstrMessageEvent):
    def __init__(self, sink):
        message = AstrBotMessage()
        message.type = MessageType.FRIEND_MESSAGE
        message.self_id = "test-bot"
        message.message_id = "input-test"
        message.sender = MessageMember("test-user", "test-user")
        message.message = []
        message.message_str = "test"
        message.raw_message = {}
        super().__init__(
            "test",
            message,
            PlatformMetadata("olv_pet_adapter", "isolated output", "test"),
            "isolated-output",
        )
        self.sink = sink
        self.set_extra("_turn_id", "turn-test")
        self.set_extra("_interaction_persona_segment_stream_requested", True)
        self.set_extra("_interaction_persona_segment_stream_active", True)
        set_interaction_turn_runtime_config(
            self, {"provider_tts_settings": {"enable": False}}
        )

    async def open_interaction_incremental_output(self, *, persona_result_id):
        return self.sink

    async def send_message_with_extras(self, **kwargs):
        if self.sink is not None:
            raise AssertionError("Incremental output must not replay legacy output")

    async def flush_interaction_incremental_motion(self, *, segment_index):
        if self.sink.deliver_motion:
            self.sink.delivered_motion_segment_indexes |= {segment_index}
            self.set_extra(
                "_interaction_personal_stream_first_output_monotonic",
                time.monotonic(),
            )
        # The actual Adapter resolves this completion future even for no payload.
        self.get_extra("_interaction_incremental_motion_futures")[
            segment_index
        ].set_result(True)

    async def flush_visible_segment(self, **kwargs):
        pass

    async def complete_visible_message(self, **kwargs):
        pass


def stream_producer(speech, *, request=None, actions=None, deltas=None):
    async def produce(emit_record, message_id):
        parser = PersonaSegmentStreamParser(
            request or PersonaExpressionRequest(require_turn_action=True)
        )
        records = [
            {"v": 1, "record": "header", "turn_action": "reply"},
            {
                "v": 1,
                "record": "segment_start",
                "actions": actions or [],
                "tendency": dict.fromkeys(PERSONA_TENDENCY_DIMENSIONS, 0),
            },
            *[
                {"v": 1, "record": "speech_delta", "text": text}
                for text in (deltas if deltas is not None else ([speech] if speech else []))
            ],
            {"v": 1, "record": "segment_end"},
            {"v": 1, "record": "finish", "effect_calls": []},
        ]
        for record in records:
            for event in parser.feed(json.dumps(record) + "\n"):
                if event["type"] == "header":
                    event["persona_result_id"] = "result-test"
                await emit_record(event)
        result = parser.finish()
        await emit_record({"type": "finish", "result": result})
        return result

    return produce


async def publish(_record):
    return True


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during_drain", [False, True])
async def test_pcm_drains_many_deltas_after_slow_tts_start(monkeypatch, cancel_during_drain):
    sink = OutputSink()
    sink.audio = []
    async def append_audio(segment_index, sample_offset, pcm):
        sink.audio.append(pcm)

    sink.append_audio = append_audio
    event = IncrementalEvent(sink)
    controller = InteractionOutputController()
    options = replace(
        controller._resolve_outbound_options(event),
        tts_enabled=True, tts_trigger_probability=1,
    )
    controller._resolve_outbound_options = lambda _event: options
    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.SessionServiceManager.should_process_tts_request",
        AsyncMock(return_value=True),
    )
    consuming = asyncio.Event()
    async def slow_pcm(_context, _event, source):
        # Model output finishes before TTS starts consuming; its first response
        # exceeds the former one-second cleanup deadline.
        consuming.set()
        await asyncio.sleep(1.1)
        offset = 0
        async for part in source:
            if part.text is None:
                yield PCMStreamFrame("end", part.segment_index, offset)
            else:
                yield PCMStreamFrame("audio", part.segment_index, offset, b"\x00\x00")
                offset += 1

    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.synthesize_pcm_stream", slow_pcm,
    )
    task = asyncio.create_task(controller.emit_persona_segment_stream(
        event, producer=stream_producer("", deltas=["字"] * 160), on_header=publish,
    ))
    await asyncio.wait_for(consuming.wait(), timeout=2)
    if cancel_during_drain:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert ("audio", 0, "cancelled") in sink.ends
        assert sink.audio == []
        receipt = get_interaction_turn_delivery_receipts(event)[0]
        assert receipt["status"] == "partial"
        assert receipt["physical_status"] == "partial"
        assert receipt["completion_status"] == "not_attempted"
        return
    outcome = await task
    assert outcome.status == "completed"
    assert "".join(sink.text) == "字" * 160
    assert len(sink.audio) == 160
    assert ("audio", 0, "completed") in sink.ends
    assert all(status == "completed" for _, _, status in sink.ends)


@pytest.mark.asyncio
async def test_incremental_output_flushes_literal_suffix_once():
    sink = OutputSink()
    event = IncrementalEvent(sink)
    outcome = await InteractionOutputController().emit_persona_segment_stream(
        event,
        producer=stream_producer("开始<system_reminder>隐藏</system_reminder>结束 <"),
        on_header=publish,
    )
    assert outcome.status == "completed"
    assert sink.text == ["开始结束 ", "<"]
    assert ("text", 0, "completed") in sink.ends
    assert outcome.expression.speech == "开始结束 <"
    assert outcome.expression.speech_segments == ("开始结束 <",)
    assert (
        get_interaction_turn_immediate_persona_segments(event)[0]["speech"]
        == "开始结束 <"
    )
    assert get_interaction_turn_personal_emitted_monotonic(event) is not None
    receipt = get_interaction_turn_delivery_receipts(event)[0]
    assert receipt["status"] == "delivered", receipt
    assert receipt["physical_status"] == "delivered"
    assert receipt["completion_status"] == "completed"


@pytest.mark.asyncio
async def test_incremental_output_write_failure_records_unknown_receipt():
    sink = OutputSink(fail_text=True)
    event = IncrementalEvent(sink)
    outcome = await InteractionOutputController().emit_persona_segment_stream(
        event,
        producer=stream_producer("visible text"),
        on_header=publish,
    )

    assert outcome.status == "incomplete"
    receipt = get_interaction_turn_delivery_receipts(event)[0]
    assert receipt["status"] == "unknown"
    assert receipt["physical_status"] == "unknown"
    assert receipt["completion_status"] == "not_attempted"
    assert receipt["failure_stage"] == "physical_send"


@pytest.mark.asyncio
async def test_incremental_resource_closure_failure_records_partial_receipt():
    sink = OutputSink(fail_completion=True)
    event = IncrementalEvent(sink)
    outcome = await InteractionOutputController().emit_persona_segment_stream(
        event,
        producer=stream_producer("visible text"),
        on_header=publish,
    )

    assert outcome.status == "incomplete"
    receipt = get_interaction_turn_delivery_receipts(event)[0]
    assert receipt["status"] == "partial"
    assert receipt["physical_status"] == "partial"
    assert receipt["completion_status"] == "not_attempted"


def test_finish_still_rejects_open_hidden_block_and_unsafe_suffix():
    hidden = IncrementalTextPreparer(lambda _text: True)
    hidden.feed("可见<system_reminder>隐藏")
    with pytest.raises(IncrementalTextError, match="hidden_markup_unclosed"):
        hidden.finish()
    assert hidden.text == "可见"

    checked = IncrementalTextPreparer(lambda text: not text.endswith("<"))
    checked.feed("可见 <")
    with pytest.raises(IncrementalTextError, match="unsafe_response"):
        checked.finish()
    assert checked.text == "可见 "


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", [True, False])
async def test_action_only_stream_counts_delivered_motion_not_completion(delivered):
    sink = OutputSink(deliver_motion=delivered)
    event = IncrementalEvent(sink)
    outcome = await InteractionOutputController().emit_persona_segment_stream(
        event,
        producer=stream_producer(
            "",
            actions=["nod"],
            request=PersonaExpressionRequest(
                require_turn_action=True,
                allow_action_only=True,
            ),
        ),
        on_header=publish,
    )
    assert outcome.status == "completed"
    assert outcome.emitted is delivered
    assert outcome.expression.speech == ""
    assert (
        has_delivered_motion_output(get_interaction_turn_visible_outputs(event))
        is delivered
    )
    receipt = get_interaction_turn_delivery_receipts(event)[0]
    assert receipt["status"] == ("delivered" if delivered else "unknown")
    if delivered:
        assert get_interaction_turn_immediate_persona_segments(event)[0]["actions"] == [
            "nod"
        ]
        assert get_interaction_turn_personal_emitted_monotonic(event) is not None


@pytest.mark.asyncio
async def test_action_only_admission_still_rejects_empty_reply():
    producer = stream_producer(
        "",
        request=PersonaExpressionRequest(
            require_turn_action=True,
            allow_action_only=True,
        ),
    )
    with pytest.raises(InteractionExpressionError, match="empty_output"):
        await producer(publish, "empty-test")


@pytest.mark.asyncio
async def test_legacy_motion_placeholder_without_payload_is_not_output():
    event = IncrementalEvent(None)
    outcome = await InteractionOutputController().emit_persona_segment_stream(
        event,
        producer=stream_producer(
            "",
            actions=["nod"],
            request=PersonaExpressionRequest(
                require_turn_action=True,
                allow_action_only=True,
            ),
        ),
        on_header=publish,
    )
    assert outcome.status == "completed"
    assert outcome.emitted is False
    assert event.get_extra("_interaction_persona_segment_stream_published") is True
    assert get_interaction_turn_visible_outputs(event) == []


@pytest.mark.asyncio
async def test_text_delivery_does_not_mark_failed_motion_as_persona_state():
    sink = OutputSink(deliver_motion=False)
    event = IncrementalEvent(sink)
    outcome = await InteractionOutputController().emit_persona_segment_stream(
        event,
        producer=stream_producer(
            "可见文本",
            actions=["nod"],
            request=PersonaExpressionRequest(
                require_turn_action=True,
                allow_action_only=True,
            ),
        ),
        on_header=publish,
    )
    assert outcome.status == "completed"
    assert outcome.emitted is True
    segment = get_interaction_turn_immediate_persona_segments(event)[0]
    assert segment["speech"] == "可见文本"
    assert segment["actions"] == []
    receipt = get_interaction_turn_delivery_receipts(event)[0]
    assert receipt["status"] == "partial"
    assert receipt["physical_status"] == "partial"


@pytest.mark.asyncio
async def test_rejected_motion_result_closes_resource_as_failed():
    sink = OutputSink(deliver_motion=False)

    class RejectingMotionEvent(IncrementalEvent):
        async def flush_interaction_incremental_motion(self, *, segment_index):
            self.get_extra("_interaction_incremental_motion_futures")[
                segment_index
            ].set_result(False)

    event = RejectingMotionEvent(sink)
    outcome = await InteractionOutputController().emit_persona_segment_stream(
        event,
        producer=stream_producer(
            "可见文本",
            actions=["nod"],
            request=PersonaExpressionRequest(
                require_turn_action=True,
                allow_action_only=True,
            ),
        ),
        on_header=publish,
    )
    assert outcome.status == "completed"
    assert ("motion", 0, "failed") in sink.ends
    receipt = get_interaction_turn_delivery_receipts(event)[0]
    assert receipt["status"] == "partial"


@pytest.mark.asyncio
async def test_action_only_motion_can_finish_after_one_second_within_its_budget():
    sink = OutputSink(deliver_motion=True)

    class DelayedMotionEvent(IncrementalEvent):
        def get_interaction_incremental_motion_deadline(self, **kwargs):
            return self.deadline

        async def flush_interaction_incremental_motion(self, *, segment_index):
            async def deliver():
                await asyncio.sleep(1.1)
                await super(DelayedMotionEvent, self).flush_interaction_incremental_motion(
                    segment_index=segment_index
                )

            self.delivery_task = asyncio.create_task(deliver())

    event = DelayedMotionEvent(sink)
    event.deadline = asyncio.get_running_loop().time() + 3.0
    try:
        outcome = await InteractionOutputController().emit_persona_segment_stream(
            event,
            producer=stream_producer(
                "",
                actions=["nod"],
                request=PersonaExpressionRequest(
                    require_turn_action=True, allow_action_only=True
                ),
            ),
            on_header=publish,
        )
        assert outcome.status == "completed"
        assert outcome.emitted is True
        assert has_delivered_motion_output(get_interaction_turn_visible_outputs(event))
    finally:
        if hasattr(event, "delivery_task"):
            event.delivery_task.cancel()
            await asyncio.gather(event.delivery_task, return_exceptions=True)
