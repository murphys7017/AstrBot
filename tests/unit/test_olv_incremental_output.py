"""Public Core stream boundary with an isolated platform output sink."""

import json
import time

import pytest

from astrbot.core.interaction.expression_agent import (
    PERSONA_TENDENCY_DIMENSIONS,
    InteractionExpressionError,
    PersonaExpressionRequest,
    PersonaSegmentStreamParser,
)
from astrbot.core.interaction.output_controller import InteractionOutputController
from astrbot.core.interaction.turn_state import (
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


class OutputSink:
    def __init__(self, *, deliver_motion=False):
        self.deliver_motion = deliver_motion
        self.delivered_motion_segment_indexes = frozenset()
        self.text = []
        self.ends = []

    async def start_stream(self, resource, *, segment_index, message_id):
        pass

    async def append_text(self, segment_index, text):
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


def stream_producer(speech, *, request=None, actions=None):
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
            *([{"v": 1, "record": "speech_delta", "text": speech}] if speech else []),
            {"v": 1, "record": "segment_end", "thought": ""},
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
