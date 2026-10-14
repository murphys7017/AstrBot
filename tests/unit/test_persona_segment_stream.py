import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.interaction.expression_agent import (
    InteractionExpressionError,
    PersonaExpressionResult,
)
from astrbot.core.interaction.output_controller import InteractionOutputController
from astrbot.core.interaction.turn_state import (
    get_interaction_turn_immediate_persona_state,
    get_interaction_turn_immediate_reply,
    get_interaction_turn_visible_outputs,
)
from astrbot.core.interaction.types import PersonalResponseAction
from astrbot.core.star.star_handler import (
    PERSONA_SEGMENT_STREAM_SAFE_KEY,
    EventType,
)
from astrbot.core.voice import TTSState


class StreamEvent:
    def __init__(self):
        self._extras = {"_turn_id": "turn-1"}
        self.sender_started = asyncio.Event()
        self.sender_finished = asyncio.Event()
        self.delivered_text_parts = []

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def set_extra(self, key, value):
        self._extras[key] = value

    def get_platform_name(self):
        return "webchat"

    async def send_interaction_streaming(
        self,
        generator,
        *,
        platform_extras=None,
        use_fallback=False,
    ):
        self.sender_started.set()
        try:
            async for message in generator:
                if message.type == "persona_speech_delta":
                    self.delivered_text_parts.append(message.get_plain_text())
        finally:
            self.sender_finished.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("header_first", [False, True])
async def test_persona_stream_cancellation_drains_tasks(header_first):
    controller = InteractionOutputController()
    controller._ensure_persona_segment_stream_compatible = lambda _event: None
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=False
    )
    controller._next_output_segment_id = lambda _event, _kind: "stream-1"
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()

    event = StreamEvent()
    producer_started = asyncio.Event()
    producer_cancelled = asyncio.Event()
    wait_forever = asyncio.Event()

    async def producer(emit_record, _message_id):
        producer_started.set()
        try:
            if header_first:
                await emit_record(
                    {
                        "type": "header",
                        "turn_action": "reply",
                        "persona_result_id": "result-1",
                    }
                )
            await wait_forever.wait()
        finally:
            producer_cancelled.set()

    async def on_header(_record):
        return None

    task = asyncio.create_task(
        controller.emit_persona_segment_stream(
            event,
            producer=producer,
            on_header=on_header,
        )
    )
    await asyncio.wait_for(producer_started.wait(), timeout=1)
    if header_first:
        await asyncio.wait_for(event.sender_started.wait(), timeout=1)

    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)

    assert isinstance(result[0], asyncio.CancelledError)
    assert producer_cancelled.is_set()
    assert event.sender_finished.is_set() is header_first


@pytest.mark.asyncio
async def test_silent_persona_stream_does_not_start_webchat_delivery():
    controller = InteractionOutputController()
    controller._ensure_persona_segment_stream_compatible = lambda _event: None
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=False
    )
    controller._next_output_segment_id = lambda _event, _kind: "stream-1"
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()

    event = StreamEvent()

    async def producer(emit_record, message_id):
        assert message_id == "stream-1"
        result = PersonaExpressionResult(
            speech="",
            turn_action=PersonalResponseAction.SILENT,
        )
        await emit_record({"type": "header", "turn_action": "silent"})
        await emit_record({"type": "finish", "result": result})
        return result

    outcome = await controller.emit_persona_segment_stream(
        event,
        producer=producer,
        on_header=AsyncMock(return_value=False),
    )

    assert outcome.expression.turn_action is PersonalResponseAction.SILENT
    assert outcome.status == "completed"
    assert outcome.emitted is False
    assert event.sender_started.is_set() is False
    controller._notify_lifecycle.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_stream_preserves_empty_segment_persona_state(monkeypatch):
    controller = InteractionOutputController()
    controller._ensure_persona_segment_stream_compatible = lambda _event: None
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=False
    )
    controller._next_output_segment_id = lambda _event, _kind: "stream-1"
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()
    event = StreamEvent()
    finish_events = []

    def registered_handlers(event_type, **_kwargs):
        if event_type is EventType.OnPersonaExpressionStreamFinishedEvent:
            return [object()]
        return []

    async def capture_finish(_event, event_type, **kwargs):
        assert event_type is EventType.OnPersonaExpressionStreamFinishedEvent
        finish_events.append(kwargs)
        return False

    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.star_handlers_registry.get_handlers_by_event_type",
        registered_handlers,
    )
    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.call_event_hook",
        capture_finish,
    )

    async def producer(emit_record, _message_id):
        await emit_record(
            {
                "type": "header",
                "turn_action": "reply",
                "persona_result_id": "result-1",
            }
        )
        await emit_record({"type": "segment_start", "segment_index": 0})
        await emit_record(
            {
                "type": "speech_delta",
                "segment_index": 0,
                "delta_index": 0,
                "text": "hello",
            }
        )
        await emit_record(
            {
                "type": "segment_end",
                "segment_index": 0,
                "segment": {
                    "speech": "hello",
                    "actions": [],
                    "thought": "",
                    "tendency": {},
                },
            }
        )
        await emit_record({"type": "segment_start", "segment_index": 1})
        await emit_record(
            {
                "type": "segment_end",
                "segment_index": 1,
                "segment": {
                    "speech": "",
                    "actions": ["blink"],
                    "thought": "",
                    "tendency": {},
                },
            }
        )
        result = PersonaExpressionResult(speech="hello")
        await emit_record({"type": "finish", "result": result})
        return result

    await controller.emit_persona_segment_stream(
        event,
        producer=producer,
        on_header=AsyncMock(),
    )

    assert get_interaction_turn_immediate_persona_state(event)[0] == ("blink",)
    assert finish_events == [
        {
            "turn_id": "turn-1",
            "persona_result_id": "result-1",
            "message_id": "stream-1",
            "segment_count": 2,
            "status": "completed",
            "failure_reason": None,
            "execution_surface": "personal_expression",
        }
    ]


@pytest.mark.asyncio
async def test_incomplete_stream_reports_accepted_segment_prefix(monkeypatch):
    controller = InteractionOutputController()
    controller._ensure_persona_segment_stream_compatible = lambda _event: None
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=False
    )
    controller._next_output_segment_id = lambda _event, _kind: "stream-1"
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()
    event = StreamEvent()
    finish_events = []

    def registered_handlers(event_type, **_kwargs):
        if event_type is EventType.OnPersonaExpressionStreamFinishedEvent:
            return [object()]
        return []

    async def capture_finish(_event, event_type, **kwargs):
        assert event_type is EventType.OnPersonaExpressionStreamFinishedEvent
        finish_events.append(kwargs)
        return False

    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.star_handlers_registry.get_handlers_by_event_type",
        registered_handlers,
    )
    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.call_event_hook",
        capture_finish,
    )

    async def producer(emit_record, _message_id):
        await emit_record(
            {
                "type": "header",
                "turn_action": "reply",
                "persona_result_id": "result-1",
            }
        )
        await emit_record({"type": "segment_start", "segment_index": 0})
        await emit_record(
            {
                "type": "speech_delta",
                "segment_index": 0,
                "delta_index": 0,
                "text": "accepted",
            }
        )
        await emit_record(
            {
                "type": "segment_end",
                "segment_index": 0,
                "segment": {
                    "speech": "accepted",
                    "actions": [],
                    "thought": "",
                    "tendency": {},
                },
            }
        )
        raise InteractionExpressionError("provider_failed")

    outcome = await controller.emit_persona_segment_stream(
        event,
        producer=producer,
        on_header=AsyncMock(return_value=True),
    )

    assert outcome.status == "incomplete"
    assert outcome.failure_reason == "provider_failed"
    assert event.delivered_text_parts == ["accepted"]
    assert finish_events[0]["status"] == "incomplete"
    assert finish_events[0]["segment_count"] == 1
    assert finish_events[0]["failure_reason"] == "provider_failed"


@pytest.mark.asyncio
async def test_olv_stream_delivers_complete_tts_segment_before_provider_finish(
    monkeypatch,
):
    controller = InteractionOutputController()
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=True,
        tts_trigger_probability=1.0,
        tts_use_file_service=False,
        callback_api_base=None,
        reply_prefix="",
        show_reasoning=False,
        t2i_enabled=False,
    )
    controller._next_output_segment_id = lambda _event, kind: {
        "persona_stream": "stream-1",
        "persona_tts": "tts-1",
    }[kind]
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()
    controller._get_runtime_config = lambda _event: {}
    prepared_segments = []

    async def prepare_segment(_event, message, **_kwargs):
        prepared_segments.append(message.get_plain_text())
        return message

    controller._prepare_model_expression = prepare_segment

    class OLVStreamEvent(StreamEvent):
        def __init__(self):
            super().__init__()
            self._extras["_interaction_persona_segment_stream_requested"] = True

        def get_platform_name(self):
            return "olv_pet_adapter"

        async def send_message_with_extras(self, *_args, **_kwargs):
            raise AssertionError("the streaming adapter path should not send here")

        async def flush_visible_segment(self, **_kwargs):
            return None

        async def complete_visible_message(self, **_kwargs):
            return None

    event = OLVStreamEvent()
    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.star_handlers_registry.get_handlers_by_event_type",
        lambda event_type, **_kwargs: (
            [
                SimpleNamespace(
                    extras_configs={PERSONA_SEGMENT_STREAM_SAFE_KEY: True}
                )
            ]
            if event_type is EventType.OnDecoratingResultEvent
            else []
        ),
    )
    controller._get_runtime_config = lambda _event: {}
    segment_delivered = asyncio.Event()
    provider_finished = asyncio.Event()
    deliveries = []

    async def deliver_visible(_event, _message, *, message_parts, **_kwargs):
        async for message, extras, message_id in message_parts:
            deliveries.append(
                (message, extras, message_id, provider_finished.is_set())
            )
            segment_delivered.set()
        return ["visible-1"]

    controller._deliver_visible_message = deliver_visible
    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.star_handlers_registry.get_handlers_by_event_type",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.SessionServiceManager.should_process_tts_request",
        AsyncMock(return_value=True),
    )

    async def synthesize(_context, _event, text, **kwargs):
        assert text == "hello"
        assert kwargs["persona_result_id"] == "result-1"
        state = TTSState(
            turn_id="turn-1",
            message_id=kwargs["message_id"],
            tts_request_id="tts-request-1",
            stage="interaction.outbound_tts",
            status="succeeded",
            provider_id="test",
            audio_path="C:/audio.wav",
            audio_url="https://local/audio.wav",
            parent_message_id="stream-1",
            persona_result_id="result-1",
            persona_segment_index=0,
        )
        return SimpleNamespace(
            state=state,
            delivered_file="https://local/audio.wav",
            text=text,
            audio_path=state.audio_path,
            audio_url=state.audio_url,
            provider_id="test",
        )

    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.synthesize_text",
        synthesize,
    )

    tendency = {
        "Joy": 0,
        "Trust": 0,
        "Fear": 0,
        "Surprise": 0,
        "Sadness": 0,
        "Disgust": 0,
        "Anger": 0,
        "Anticipation": 0,
    }

    async def producer(emit_record, message_id):
        assert message_id == "stream-1"
        await emit_record(
            {
                "type": "header",
                "turn_action": "reply",
                "persona_result_id": "result-1",
            }
        )
        await emit_record({"type": "segment_start", "segment_index": 0})
        await emit_record(
            {
                "type": "speech_delta",
                "segment_index": 0,
                "delta_index": 0,
                "text": "hello",
            }
        )
        await emit_record(
            {
                "type": "segment_end",
                "segment_index": 0,
                "segment": {
                    "speech": "hello",
                    "actions": [],
                    "thought": "",
                    "tendency": tendency,
                },
            }
        )
        await asyncio.wait_for(segment_delivered.wait(), timeout=1)
        result = PersonaExpressionResult(speech="hello")
        await emit_record({"type": "finish", "result": result})
        provider_finished.set()
        return result

    outcome = await controller.emit_persona_segment_stream(
        event,
        producer=producer,
        on_header=AsyncMock(return_value=True),
    )

    assert outcome.status == "completed"
    assert outcome.emitted is True
    assert prepared_segments == ["hello"]
    assert event.sender_started.is_set() is False
    assert len(deliveries) == 1
    message, extras, message_id, finished_before_delivery = deliveries[0]
    assert message.type == "persona_stream_tts"
    assert message.chain[0].file == "https://local/audio.wav"
    assert "persona_segment_count" not in message.chain[0].delivery_metadata[
        "output_segment"
    ]["tts"]
    assert message_id == "tts-1"
    assert extras["persona_result_id"] == "result-1"
    assert extras["persona_segment_index"] == 0
    assert extras["persona_streaming"] is True
    assert "persona_segment_count" not in extras
    assert finished_before_delivery is False


@pytest.mark.asyncio
async def test_persona_stream_cancellation_cancels_stalled_tts(monkeypatch):
    controller = InteractionOutputController()
    controller._ensure_persona_segment_stream_compatible = lambda _event: None
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=True,
        tts_trigger_probability=1.0,
        tts_use_file_service=False,
        callback_api_base=None,
    )
    controller._next_output_segment_id = lambda _event, _kind: "stream-1"
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()
    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.SessionServiceManager.should_process_tts_request",
        AsyncMock(return_value=True),
    )

    event = StreamEvent()
    tts_started = asyncio.Event()
    tts_cancelled = asyncio.Event()
    producer_finished = asyncio.Event()
    wait_forever = asyncio.Event()

    async def stalled_synthesis(*_args, **_kwargs):
        tts_started.set()
        try:
            await wait_forever.wait()
        finally:
            tts_cancelled.set()

    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.synthesize_text",
        stalled_synthesis,
    )

    async def producer(emit_record, _message_id):
        await emit_record({"type": "header", "turn_action": "reply"})
        for segment_index, segment_text in enumerate(("hello", " world")):
            segment = {
                "speech": segment_text,
                "actions": [],
                "thought": "",
                "tendency": {},
            }
            await emit_record(
                {"type": "segment_start", "segment_index": segment_index}
            )
            await emit_record(
                {
                    "type": "speech_delta",
                    "segment_index": segment_index,
                    "delta_index": 0,
                    "text": segment_text,
                }
            )
            await emit_record(
                {
                    "type": "segment_end",
                    "segment_index": segment_index,
                    "segment": segment,
                }
            )
        await emit_record({"type": "segment_start", "segment_index": 2})
        await emit_record(
            {
                "type": "segment_end",
                "segment_index": 2,
                "segment": {
                    "speech": "",
                    "actions": ["blink"],
                    "thought": "",
                    "tendency": {},
                },
            }
        )
        result = PersonaExpressionResult(speech="hello world")
        await emit_record({"type": "finish", "result": result})
        producer_finished.set()
        return result

    task = asyncio.create_task(
        controller.emit_persona_segment_stream(
            event,
            producer=producer,
            on_header=AsyncMock(),
        )
    )
    await asyncio.wait_for(tts_started.wait(), timeout=1)
    await asyncio.wait_for(producer_finished.wait(), timeout=1)
    task.cancel()
    result = await asyncio.wait_for(
        asyncio.gather(task, return_exceptions=True),
        timeout=1,
    )

    assert isinstance(result[0], asyncio.CancelledError)
    assert tts_cancelled.is_set()
    assert event.sender_finished.is_set()
    assert event.delivered_text_parts == ["hello"]
    assert event.get_extra("_interaction_persona_segment_stream_status") == (
        "cancelled"
    )
    assert get_interaction_turn_immediate_reply(event) == "hello"
    assert get_interaction_turn_immediate_persona_state(event)[0] == ()
    visible_outputs = get_interaction_turn_visible_outputs(event)
    assert visible_outputs[-1]["text"] == "hello"
