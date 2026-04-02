"""Tests for prompt context collection."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from astrbot.core import astr_main_agent as ama
from astrbot.core.astr_main_agent_resources import (
    CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT,
    LLM_SAFETY_MODE_SYSTEM_PROMPT,
    SANDBOX_MODE_PROMPT,
)
from astrbot.core.message.components import File, Image, Plain, Reply
from astrbot.core.prompt.collectors import (
    InputCollector,
    PolicyCollector,
    SessionCollector,
)
from astrbot.core.prompt.context_collect import (
    PROMPT_CONTEXT_PACK_EXTRA_KEY,
    collect_context_pack,
    log_context_pack,
)
from astrbot.core.prompt.context_types import ContextSlot
from astrbot.core.prompt.interfaces import ContextCollectorInterface
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


@pytest.mark.asyncio
async def test_log_context_pack_outputs_full_persona_payload():
    event, extras = _make_event()
    context = _make_context()
    req = ProviderRequest(prompt="hello")
    req.conversation = _make_conversation(persona_id="persona-a")
    extras["provider_request"] = req

    persona_prompt = """身份
- 你是 Alice，由 YakumoAki 设计。
稳定规则
- 始终以 Alice 身份回应。"""
    persona = {
        "name": "persona-a",
        "prompt": persona_prompt,
        "_begin_dialogs_processed": [
            {"role": "user", "content": "hi", "_no_save": True}
        ],
        "begin_dialogs": ["hi", "hello"],
        "tools": ["tool_a"],
        "skills": ["skill_a"],
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

    with patch("astrbot.core.prompt.context_collect.logger") as mock_logger:
        log_context_pack(pack, event=event)

    logged_messages = [
        call.args[0] % call.args[1:] if call.args else ""
        for call in mock_logger.info.call_args_list
    ]
    persona_logs = [
        message for message in logged_messages if "Prompt persona loaded:" in message
    ]

    assert len(persona_logs) == 1
    assert '"persona_id": "persona-a"' in persona_logs[0]
    assert (
        '"prompt": "身份\\n- 你是 Alice，由 YakumoAki 设计。\\n稳定规则\\n- 始终以 Alice 身份回应。"'
        in persona_logs[0]
    )
    assert '"segments"' in persona_logs[0]
    assert '"tools_whitelist": ["tool_a"]' in persona_logs[0]
    assert '"skills_whitelist": ["skill_a"]' in persona_logs[0]


@pytest.mark.asyncio
async def test_collect_context_pack_collects_effective_input_text_and_attachments():
    event, _ = _make_event()
    event.message_str = "/ask explain this"
    event.message_obj.message = [
        Plain(text="/ask explain this"),
        Image(file="https://example.com/image.png"),
        File(name="report.txt", file="C:/tmp/report.txt"),
    ]
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(
            tool_call_timeout=60,
            provider_wake_prefix="/ask ",
        ),
        collectors=[InputCollector()],
    )

    text_slot = pack.get_slot("input.text")
    assert text_slot is not None
    assert text_slot.value == "explain this"
    assert text_slot.meta["source_field"] == "event.message_str"

    images_slot = pack.get_slot("input.images")
    assert images_slot is not None
    assert images_slot.value == [
        {
            "ref": "https://example.com/image.png",
            "transport": "url",
            "source": "current",
        }
    ]

    files_slot = pack.get_slot("input.files")
    assert files_slot is not None
    assert files_slot.value == [
        {
            "name": "report.txt",
            "file": "C:/tmp/report.txt",
            "url": "",
            "source": "current",
            "reply_id": None,
        }
    ]


@pytest.mark.asyncio
async def test_collect_context_pack_collects_attachment_only_input_without_text():
    event, _ = _make_event()
    event.message_str = ""
    event.message_obj.message = [File(name="report.txt", file="C:/tmp/report.txt")]
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(tool_call_timeout=60),
        collectors=[InputCollector()],
    )

    assert pack.get_slot("input.text") is None
    files_slot = pack.get_slot("input.files")
    assert files_slot is not None
    assert files_slot.value[0]["source"] == "current"


@pytest.mark.asyncio
async def test_collect_context_pack_prefers_provider_request_prompt_for_input_text():
    event, _ = _make_event()
    event.message_str = "/ask raw message"
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )
    req = ProviderRequest(prompt="effective prompt")

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(
            tool_call_timeout=60,
            provider_wake_prefix="/ask ",
        ),
        provider_request=req,
        collectors=[InputCollector()],
    )

    text_slot = pack.get_slot("input.text")
    assert text_slot is not None
    assert text_slot.value == "effective prompt"
    assert text_slot.meta["source_field"] == "provider_request.prompt"


@pytest.mark.asyncio
async def test_collect_context_pack_collects_quoted_input_payloads():
    event, _ = _make_event()
    event.message_obj.message = [
        Reply(
            id="reply-1",
            message_str="quoted message",
            chain=[
                Image(file="file:///C:/tmp/quoted.png"),
                File(name="quoted.txt", file="C:/tmp/quoted.txt"),
            ],
        )
    ]
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    with (
        patch(
            "astrbot.core.prompt.collectors.input_collector.extract_quoted_message_text",
            new=AsyncMock(return_value="quoted message"),
        ),
        patch(
            "astrbot.core.prompt.collectors.input_collector.extract_quoted_message_images",
            new=AsyncMock(return_value=["https://example.com/fallback.png"]),
        ),
    ):
        pack = await collect_context_pack(
            event=event,
            plugin_context=context,
            config=ama.MainAgentBuildConfig(tool_call_timeout=60),
            collectors=[InputCollector()],
        )

    quoted_text_slot = pack.get_slot("input.quoted_text")
    assert quoted_text_slot is not None
    assert quoted_text_slot.value == "quoted message"
    assert "<Quoted Message>" not in quoted_text_slot.value

    quoted_images_slot = pack.get_slot("input.quoted_images")
    assert quoted_images_slot is not None
    assert quoted_images_slot.value == [
        {
            "ref": "file:///C:/tmp/quoted.png",
            "transport": "file",
            "source": "quoted",
            "resolution": "embedded",
            "reply_id": "reply-1",
        }
    ]

    files_slot = pack.get_slot("input.files")
    assert files_slot is not None
    assert files_slot.value == [
        {
            "name": "quoted.txt",
            "file": "C:/tmp/quoted.txt",
            "url": "",
            "source": "quoted",
            "reply_id": "reply-1",
        }
    ]


@pytest.mark.asyncio
async def test_collect_context_pack_collects_fallback_quoted_images_with_limit():
    event, _ = _make_event()
    event.message_obj.message = [Reply(id="reply-1", message_str="[Image]")]
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    with (
        patch(
            "astrbot.core.prompt.collectors.input_collector.extract_quoted_message_text",
            new=AsyncMock(return_value="quoted message"),
        ),
        patch(
            "astrbot.core.prompt.collectors.input_collector.extract_quoted_message_images",
            new=AsyncMock(
                return_value=[
                    "https://example.com/1.png",
                    "https://example.com/2.png",
                ]
            ),
        ),
    ):
        pack = await collect_context_pack(
            event=event,
            plugin_context=context,
            config=ama.MainAgentBuildConfig(
                tool_call_timeout=60,
                max_quoted_fallback_images=1,
            ),
            collectors=[InputCollector()],
        )

    quoted_images_slot = pack.get_slot("input.quoted_images")
    assert quoted_images_slot is not None
    assert quoted_images_slot.meta["fallback_count"] == 1
    assert quoted_images_slot.value == [
        {
            "ref": "https://example.com/1.png",
            "transport": "url",
            "source": "quoted",
            "resolution": "fallback",
            "reply_id": "reply-1",
        }
    ]


@pytest.mark.asyncio
async def test_collect_context_pack_collects_session_slots_for_private_chat():
    event, _ = _make_event()
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(
            tool_call_timeout=60,
            timezone="Asia/Shanghai",
        ),
        collectors=[SessionCollector()],
    )

    assert pack.meta["collectors"] == ["SessionCollector"]
    datetime_slot = pack.get_slot("session.datetime")
    assert datetime_slot is not None
    assert datetime_slot.value["timezone"] == "Asia/Shanghai"
    assert datetime_slot.value["source"] == "config.timezone"
    assert datetime_slot.meta["from_config"] is True
    assert "T" in datetime_slot.value["iso"]

    user_slot = pack.get_slot("session.user_info")
    assert user_slot is not None
    assert user_slot.value == {
        "user_id": "user123",
        "nickname": "Tester",
        "platform_name": "test_platform",
        "umo": "test_platform:private:test-session",
        "group_id": None,
        "group_name": None,
        "is_group": False,
    }


@pytest.mark.asyncio
async def test_collect_context_pack_collects_group_session_info():
    event, _ = _make_event()
    event.unified_msg_origin = "test_platform:group:test-session"
    event.message_obj.group_id = "group-1"
    event.message_obj.group = MagicMock(group_name="Test Group")
    event.get_group_id.return_value = "group-1"
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(tool_call_timeout=60),
        collectors=[SessionCollector()],
    )

    user_slot = pack.get_slot("session.user_info")
    assert user_slot is not None
    assert user_slot.value["group_id"] == "group-1"
    assert user_slot.value["group_name"] == "Test Group"
    assert user_slot.value["is_group"] is True


@pytest.mark.asyncio
async def test_collect_context_pack_session_timezone_falls_back_to_global_config():
    event, _ = _make_event()
    context = _make_context()
    context.get_config.return_value = {"timezone": "UTC"}
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(tool_call_timeout=60),
        collectors=[SessionCollector()],
    )

    datetime_slot = pack.get_slot("session.datetime")
    assert datetime_slot is not None
    assert datetime_slot.value["timezone"] == "UTC"
    assert datetime_slot.value["source"] == "plugin_context.get_config"
    assert datetime_slot.meta["from_config"] is True


@pytest.mark.asyncio
async def test_collect_context_pack_session_handles_missing_group_object():
    event, _ = _make_event()
    event.message_obj.group_id = "group-1"
    event.message_obj.group = None
    event.get_group_id.return_value = "group-1"
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(tool_call_timeout=60),
        collectors=[SessionCollector()],
    )

    user_slot = pack.get_slot("session.user_info")
    assert user_slot is not None
    assert user_slot.value["group_id"] == "group-1"
    assert user_slot.value["group_name"] is None
    assert user_slot.value["is_group"] is True


@pytest.mark.asyncio
async def test_collect_context_pack_session_fail_open_with_partial_event_data():
    event, _ = _make_event()
    event.message_obj.sender = None
    event.get_platform_name.side_effect = RuntimeError("missing platform")
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(tool_call_timeout=60),
        collectors=[SessionCollector()],
    )

    datetime_slot = pack.get_slot("session.datetime")
    assert datetime_slot is not None
    user_slot = pack.get_slot("session.user_info")
    assert user_slot is not None
    assert user_slot.value["user_id"] is None
    assert user_slot.value["nickname"] is None
    assert user_slot.value["platform_name"] is None
    assert user_slot.value["umo"] == "test_platform:private:test-session"


@pytest.mark.asyncio
async def test_collect_context_pack_default_collectors_include_session_collector():
    event, _ = _make_event()
    context = _make_context()
    req = ProviderRequest(prompt="hello")
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(tool_call_timeout=60),
        provider_request=req,
    )

    assert pack.meta["collectors"] == [
        "PersonaCollector",
        "InputCollector",
        "SessionCollector",
        "PolicyCollector",
    ]
    assert pack.get_slot("session.datetime") is not None
    assert pack.get_slot("session.user_info") is not None
    assert pack.get_slot("policy.safety_prompt") is not None


@pytest.mark.asyncio
async def test_collect_context_pack_collects_policy_safety_prompt_when_enabled():
    event, _ = _make_event()
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(
            tool_call_timeout=60,
            llm_safety_mode=True,
            safety_mode_strategy="system_prompt",
        ),
        collectors=[PolicyCollector()],
    )

    safety_slot = pack.get_slot("policy.safety_prompt")
    assert safety_slot is not None
    assert safety_slot.value == LLM_SAFETY_MODE_SYSTEM_PROMPT
    assert safety_slot.meta["enabled_by_config"] is True
    assert safety_slot.meta["strategy"] == "system_prompt"


@pytest.mark.asyncio
async def test_collect_context_pack_skips_policy_safety_prompt_when_disabled():
    event, _ = _make_event()
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(
            tool_call_timeout=60,
            llm_safety_mode=False,
        ),
        collectors=[PolicyCollector()],
    )

    assert pack.get_slot("policy.safety_prompt") is None


@pytest.mark.asyncio
async def test_collect_context_pack_collects_policy_sandbox_prompt_for_sandbox_runtime():
    event, _ = _make_event()
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(
            tool_call_timeout=60,
            computer_use_runtime="sandbox",
        ),
        collectors=[PolicyCollector()],
    )

    sandbox_slot = pack.get_slot("policy.sandbox_prompt")
    assert sandbox_slot is not None
    assert sandbox_slot.value == SANDBOX_MODE_PROMPT
    assert sandbox_slot.meta["enabled_by_config"] is True
    assert sandbox_slot.meta["runtime"] == "sandbox"


@pytest.mark.asyncio
async def test_collect_context_pack_skips_policy_sandbox_prompt_for_local_runtime():
    event, _ = _make_event()
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(
            tool_call_timeout=60,
            computer_use_runtime="local",
        ),
        collectors=[PolicyCollector()],
    )

    assert pack.get_slot("policy.sandbox_prompt") is None


class _BrokenCollector(ContextCollectorInterface):
    async def collect(self, event, plugin_context, config, provider_request=None):
        raise RuntimeError("boom")


class _StaticCollector(ContextCollectorInterface):
    async def collect(self, event, plugin_context, config, provider_request=None):
        return [
            ContextSlot(
                name="input.text",
                value="hello",
                category="input",
                source="test",
            )
        ]


@pytest.mark.asyncio
async def test_collect_context_pack_fail_open_when_a_collector_raises():
    event, _ = _make_event()
    context = _make_context()
    context.persona_manager.resolve_selected_persona = AsyncMock(
        return_value=(None, None, None, False)
    )

    pack = await collect_context_pack(
        event=event,
        plugin_context=context,
        config=ama.MainAgentBuildConfig(tool_call_timeout=60),
        collectors=[_BrokenCollector(), _StaticCollector()],
    )

    text_slot = pack.get_slot("input.text")
    assert text_slot is not None
    assert text_slot.value == "hello"
