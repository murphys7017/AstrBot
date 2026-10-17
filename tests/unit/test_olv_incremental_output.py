"""Public Core stream boundary with an isolated platform output sink."""

import json

import pytest

from astrbot.core.interaction.expression_agent import (
    PERSONA_TENDENCY_DIMENSIONS,
    PersonaExpressionRequest,
    PersonaSegmentStreamParser,
)
from astrbot.core.interaction.output_controller import InteractionOutputController
from astrbot.core.interaction.turn_state import set_interaction_turn_runtime_config
from astrbot.core.message.incremental_text import (
    IncrementalTextError,
    IncrementalTextPreparer,
)
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata


class OutputSink:
    def __init__(self):
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
            "test", message,
            PlatformMetadata("olv_pet_adapter", "isolated output", "test"),
            "isolated-output",
        )
        self.sink = sink
        self.set_extra("_turn_id", "turn-test")
        self.set_extra("_interaction_persona_segment_stream_requested", True)
        self.set_extra("_interaction_persona_segment_stream_active", True)
        set_interaction_turn_runtime_config(self, {"provider_tts_settings": {"enable": False}})

    async def open_interaction_incremental_output(self, *, persona_result_id):
        return self.sink

    async def send_message_with_extras(self, **kwargs):
        raise AssertionError("Incremental output must not replay legacy output")

    async def flush_visible_segment(self, **kwargs):
        pass

    async def complete_visible_message(self, **kwargs):
        pass


def stream_producer(speech, *, request=None, actions=None):
    async def produce(emit_record, message_id):
        parser = PersonaSegmentStreamParser(request or PersonaExpressionRequest(require_turn_action=True))
        records = [
            {"v": 1, "record": "header", "turn_action": "reply"},
            {"v": 1, "record": "segment_start", "actions": actions or [],
             "tendency": dict.fromkeys(PERSONA_TENDENCY_DIMENSIONS, 0)},
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
        event, producer=stream_producer("开始<system_reminder>隐藏</system_reminder>结束 <"),
        on_header=publish,
    )
    assert outcome.status == "completed"
    assert sink.text == ["开始结束 ", "<"]
    assert ("text", 0, "completed") in sink.ends


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
