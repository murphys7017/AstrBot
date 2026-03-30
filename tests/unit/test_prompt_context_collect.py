"""Tests for prompt context collection."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from astrbot.core import astr_main_agent as ama
from astrbot.core.astr_main_agent_resources import (
    CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT,
)
from astrbot.core.message.components import Plain
from astrbot.core.prompt.context_collect import (
    PROMPT_CONTEXT_PACK_EXTRA_KEY,
    collect_context_pack,
)
from astrbot.core.provider.entities import ProviderRequest


def _make_event():
    extras: dict[str, object] = {}

    event = MagicMock()
    event.unified_msg_origin = "test_platform:private:test-session"
    event.message_str = "hello"
    event.message_obj = MagicMock()
    event.message_obj.message = [Plain(text="hello")]
    event.message_obj.sender = MagicMock(user_id="user123", nickname="Tester")
    event.message_obj.group_id = None
    event.message_obj.group = None
    event.get_platform_name.return_value = "test_platform"
    event.get_platform_id.return_value = "test_platform"
    event.get_group_id.return_value = None
    event.get_sender_name.return_value = "Tester"
    event.plugins_name = None
    event.trace = MagicMock()

    def _get_extra(key):
        return extras.get(key)

    def _set_extra(key, value):
        extras[key] = value

    event.get_extra.side_effect = _get_extra
    event.set_extra.side_effect = _set_extra
    return event, extras


def _make_context():
    ctx = MagicMock()
    ctx.get_config.return_value = {}
    ctx.get_provider_by_id.return_value = None
    ctx.subagent_orchestrator = None
    ctx.get_llm_tool_manager.return_value = MagicMock()
    ctx.persona_manager = MagicMock()
    ctx.persona_manager.get_persona_v3_by_id = MagicMock(return_value=None)
    ctx.conversation_manager = MagicMock()
    return ctx


def _make_conversation(persona_id=None):
    conversation = MagicMock()
    conversation.cid = "conv-id"
    conversation.persona_id = persona_id
    conversation.history = "[]"
    return conversation


@pytest.mark.asyncio
async def test_collect_context_pack_collects_persona_prompt():
    event, extras = _make_event()
    context = _make_context()
    req = ProviderRequest(prompt="hello")
    req.conversation = _make_conversation(persona_id="persona-a")
    extras["provider_request"] = req

    persona = {
        "name": "persona-a",
        "prompt": "You are a helpful assistant.",
        "_begin_dialogs_processed": [],
        "tools": None,
        "skills": None,
    }
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=("persona-a", persona, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(tool_call_timeout=60),
        provider_request=req,
    )

    slot = pack.get_slot("persona.prompt")
    assert slot is not None
    assert slot.value == "You are a helpful assistant."
    assert pack.provider_request_ref is req
    segments_slot = pack.get_slot("persona.segments")
    assert segments_slot is not None
    assert segments_slot.value["unparsed_sections"] == ["You are a helpful assistant."]


@pytest.mark.asyncio
async def test_collect_context_pack_collects_webchat_default_persona_prompt():
    event, extras = _make_event()
    event.get_platform_name.return_value = "webchat"
    context = _make_context()
    req = ProviderRequest(prompt="hello")
    req.conversation = _make_conversation(persona_id=None)
    extras["provider_request"] = req

    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=("_chatui_default_", None, None, True)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(tool_call_timeout=60),
        provider_request=req,
    )

    slot = pack.get_slot("persona.prompt")
    assert slot is not None
    assert slot.value == CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT
    assert slot.meta["use_webchat_special_default"] is True
    assert pack.get_slot("persona.segments") is not None


@pytest.mark.asyncio
async def test_build_main_agent_stores_prompt_context_pack_in_event_extra():
    event, extras = _make_event()
    context = _make_context()
    provider = MagicMock()
    provider.provider_config = {"id": "test-provider", "modalities": ["tool_use"]}
    provider.get_model.return_value = "gpt-4"
    context.get_using_provider.return_value = provider

    conversation = _make_conversation(persona_id="persona-a")
    context.conversation_manager.get_curr_conversation_id = AsyncMock(return_value=None)
    context.conversation_manager.new_conversation = AsyncMock(return_value="conv-id")
    context.conversation_manager.get_conversation = AsyncMock(return_value=conversation)

    persona = {
        "name": "persona-a",
        "prompt": "You are a helpful assistant.",
        "_begin_dialogs_processed": [],
        "tools": None,
        "skills": None,
    }
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=("persona-a", persona, None, False)
    )

    with (
        patch("astrbot.core.astr_main_agent.AgentRunner") as mock_runner_cls,
        patch("astrbot.core.astr_main_agent.AstrAgentContext"),
    ):
        mock_runner = MagicMock()
        mock_runner.reset = AsyncMock()
        mock_runner_cls.return_value = mock_runner

        result = await ama.build_main_agent(
            event=event,
            plugin_context=context,
            config=ama.MainAgentBuildConfig(tool_call_timeout=60),
        )

    assert result is not None
    assert PROMPT_CONTEXT_PACK_EXTRA_KEY in extras
    pack = extras[PROMPT_CONTEXT_PACK_EXTRA_KEY]
    slot = pack.get_slot("persona.prompt")
    assert slot is not None
    assert slot.value == "You are a helpful assistant."
    assert pack.get_slot("persona.segments") is not None
