import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.interaction import expression_agent as module
from astrbot.core.interaction.expression_agent import InteractionExpressionAgent
from astrbot.core.interaction.persona_expression_types import PersonaExpressionRequest
from astrbot.core.interaction.persona_stream_protocol import (
    build_persona_segment_stream_prompt,
)
from astrbot.core.interaction.types import InteractionAgentConfig
from astrbot.core.prompt.render.interfaces import RenderResult
from astrbot.core.provider.entities import LLMResponse, ProviderCompletionStatus


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stream", "nonstream_primary", "nonstream_fallback"])
async def test_fallback_keeps_persona_stream_protocol(monkeypatch, transport):
    protocol_prompt = build_persona_segment_stream_prompt(
        allowed_actions=["reply"], allow_action_only=False,
    )
    # Use the public protocol example so this transport check stays independent
    # of unrelated wire-format edits in the working tree.
    wire_records = [
        json.loads(line) for line in protocol_prompt.splitlines()
        if line.startswith("{")
    ]
    for record in wire_records:
        if record["record"] == "speech_delta":
            record["text"] = "hello"
    wire = "\n".join(json.dumps(record) for record in wire_records) + "\n"

    class Provider:
        def __init__(self, name, text):
            self.provider_config = {"id": name, "type": "test"}
            self.text = text

        def get_model(self):
            return "test"

        async def text_chat(self, **kwargs):
            raise AssertionError("streaming must not switch to text_chat")

        async def text_chat_stream(self, **kwargs):
            yield LLMResponse(role="assistant", completion_text=self.text, is_chunk=True)
            yield LLMResponse(
                role="assistant", completion_text=self.text,
                completion_status=ProviderCompletionStatus.COMPLETED,
            )

    class NonStreamingProvider:
        def __init__(self, name, text):
            self.provider_config = {"id": name, "type": "test"}
            self.text = text

        def get_model(self):
            return "test"

        async def text_chat(self, **kwargs):
            return LLMResponse(
                role="assistant", completion_text=self.text,
                completion_status=ProviderCompletionStatus.COMPLETED,
            )

    class Event:
        session_id = "session"
        unified_msg_origin = "webchat:FriendMessage:session"
        plugins_name = []

        def __init__(self):
            self.extras = {}

        def get_extra(self, key, default=None):
            return self.extras.get(key, default)

        def set_extra(self, key, value):
            self.extras[key] = value

        def get_platform_id(self):
            return "webchat"

        def get_platform_name(self):
            return "webchat"

        def is_stopped(self):
            return False

    primary = (
        NonStreamingProvider("primary", wire)
        if transport == "nonstream_primary"
        else Provider("primary", "plain text\n")
    )
    fallback = (
        NonStreamingProvider("fallback", wire)
        if transport == "nonstream_fallback"
        else Provider("fallback", wire)
    )
    monkeypatch.setattr(module, "Provider", (Provider, NonStreamingProvider))
    monkeypatch.setattr(module, "resolve_interaction_chat_provider", AsyncMock(
        return_value=(primary, "primary"),
    ))
    monkeypatch.setattr(module, "resolve_fallback_chat_providers", lambda *args: [fallback])
    monkeypatch.setattr(module.star_handlers_registry, "get_handlers_by_event_type", lambda *args, **kwargs: [])
    monkeypatch.setattr(module, "call_event_hook", AsyncMock(return_value=False))
    agent = InteractionExpressionAgent()
    agent._prepare_render_result = AsyncMock(return_value=RenderResult(
        system_prompt=protocol_prompt,
        request_prompt="hello",
        metadata={"persona_effect_specs": [], "expression_output_format": "segment_stream_v1"},
    ))
    records = []

    async def emit(record):
        records.append(record)

    result = await agent.generate_segment_stream_expression(
        Event(), SimpleNamespace(get_config=lambda **kwargs: {}, get_provider_by_id=lambda _: primary),
        InteractionAgentConfig(expression_output_format="json", expression_output_mode="prompt_only"),
        PersonaExpressionRequest(require_turn_action=True), emit_record=emit, message_id="message",
    )
    assert result.speech == "hello"
    assert [record["type"] for record in records] == [
        "header", "segment_start", "speech_delta", "segment_end", "finish",
    ]
