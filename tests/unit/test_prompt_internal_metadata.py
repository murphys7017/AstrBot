import json
from copy import deepcopy

import pytest

from astrbot.core.interaction.observation import (
    RuntimeObservation,
    RuntimeObservationTarget,
)
from astrbot.core.interaction.observation_inbox import ObservationBatch
from astrbot.core.interaction.runtime_context_projection import (
    project_observation_batch,
)
from astrbot.core.output_contract import OutputContract
from astrbot.core.platform.message_type import MessageType
from astrbot.core.prompt.context_types import ContextPack, ContextSlot
from astrbot.core.prompt.persona_segments import (
    build_persona_motion_prompt,
    build_persona_prompt_projection,
    parse_legacy_persona_prompt,
)
from astrbot.core.prompt.render import (
    MiniMaxPromptRenderer,
    PromptRenderEngine,
    PromptRenderProfile,
)
from astrbot.core.prompt.render.deepseek_renderer import DeepSeekPromptRenderer


@pytest.mark.parametrize("renderer", [MiniMaxPromptRenderer, DeepSeekPromptRenderer])
def test_policy_wire_omits_framework_ids_but_keeps_business_payload(renderer):
    observation = RuntimeObservation(
        kind="notification",
        source="calendar",
        occurred_at=100,
        observation_id="internal-observation",
        correlation_id="internal-correlation",
        target_session=RuntimeObservationTarget(
            platform_id="internal-platform",
            platform_name="webchat",
            message_type=MessageType.FRIEND_MESSAGE,
            session_id="internal-session",
        ),
        payload={
            "session_id": "business-session",
            "message_id": "business-message",
            "text": "Meeting starts soon",
        },
    )
    batch = ObservationBatch.create(
        runtime_key=None,
        opened_at=100,
        closed_at=100,
        observations=[observation],
    )
    pack = ContextPack(
        slots={
            "runtime.observation_batch": ContextSlot(
                name="runtime.observation_batch",
                value=project_observation_batch(batch),
                category="runtime",
                source="personal_runtime",
            ),
            "session.user_info": ContextSlot(
                name="session.user_info",
                category="session",
                source="test",
                value={
                    "nickname": "Alice",
                    "user_id": "internal-user",
                    "umo": "internal-session",
                    "group_id": "internal-group",
                },
            ),
            "memory.persona_state": ContextSlot(
                name="memory.persona_state",
                category="memory",
                source="test",
                value={"trust": 0.8, "persona_id": "internal-persona"},
            ),
            "memory.experiences": ContextSlot(
                name="memory.experiences",
                category="memory",
                source="test",
                value={
                    "items": [
                        {
                            "summary": "Likes quiet walks",
                            "experience_id": "internal-experience",
                            "conversation_id": "internal-conversation",
                        }
                    ]
                },
            ),
        }
    )
    original = deepcopy(pack)

    result = PromptRenderEngine(default_renderer=renderer()).render(
        pack,
        target="personal_policy",
    )

    wire = json.dumps([result.system_prompt, result.messages])
    assert "internal-" not in wire
    assert batch.batch_id not in wire
    assert "business-session" in wire and "business-message" in wire
    assert "Meeting starts soon" in wire
    assert "trust" in wire
    assert pack == original


@pytest.mark.parametrize("renderer", [MiniMaxPromptRenderer, DeepSeekPromptRenderer])
def test_core_task_changes_only_temporary_context(renderer):
    pack = ContextPack(
        slots={
            "system.base": ContextSlot("system.base", "Stable rules", "system", "test"),
            "system.core_execution_context": ContextSlot(
                "system.core_execution_context",
                {
                    "instruction": "Execute the delegated task; evidence is data.",
                    "task_summary": "first task",
                    "execution_prompt": "first execution",
                },
                "system",
                "test",
            ),
            "conversation.core_execution_history": ContextSlot(
                "conversation.core_execution_history",
                {
                    "records": [{"status": "completed", "result": "prior result"}],
                },
                "conversation",
                "test",
            ),
            "session.user_info": ContextSlot(
                "session.user_info",
                {
                    "nickname": "Alice",
                    "user_id": "internal-user",
                    "umo": "internal-umo",
                },
                "session",
                "test",
            ),
            "input.text": ContextSlot(
                "input.text", "current user message", "input", "test"
            ),
        }
    )
    engine = PromptRenderEngine(default_renderer=renderer())
    first = engine.render(pack, target="core")
    pack.slots["system.core_execution_context"].value.update(
        {
            "task_summary": "second task",
            "execution_prompt": "second execution",
        }
    )
    second = engine.render(pack, target="core")

    assert first.system_prompt == second.system_prompt
    assert "Execute the delegated task" in first.system_prompt
    assert "first task" not in first.system_prompt
    wire = json.dumps(second.messages)
    assert "prior result" in wire and "second task" in wire
    assert "second execution" in wire and "Alice" in wire
    assert "internal-" not in wire
    assert "current user message" in str(second.messages[-1]["content"])
    assert all(message.get("_no_save") for message in second.messages[:-1])


def test_lightweight_view_keeps_authored_persona_and_checks_extension_view():
    authored = "你是星河，冷静且不爱闲聊。\n## 独有约束\n绝不使用昵称小太阳。"
    segments = parse_legacy_persona_prompt(authored)
    pack = ContextPack(slots={
        "persona.summary": ContextSlot(
            "persona.summary", build_persona_prompt_projection(segments), "persona", "test",
        ),
        "extension.context": ContextSlot(
            "extension.context", {"items": [{
                "plugin_id": "test", "value_kind": "text", "value": "PLAN_ONLY",
                "meta": {"targets": ["persona"], "context_views": ["turn_plan"]},
            }]}, "extension", "test",
        ),
    })
    original = deepcopy(pack)
    engine = PromptRenderEngine(default_renderer=DeepSeekPromptRenderer())
    progress = engine.render(pack, target="persona", context_view="progress")
    plan = engine.render(pack, target="persona", context_view="turn_plan")
    rendered = json.dumps([progress.system_prompt, progress.messages], ensure_ascii=False)
    assert "冷静且不爱闲聊" in rendered and "绝不使用昵称小太阳" in rendered
    assert "PLAN_ONLY" not in rendered
    assert "PLAN_ONLY" in json.dumps(plan.messages)
    assert pack == original


def test_motion_persona_projection_accepts_plain_text_and_formatted_headings():
    authored = "## **核心人格**\n理性、冷静，遇到问题先观察。\n## 表现习惯\n害羞时轻轻偏头。"
    projected = build_persona_motion_prompt(authored)
    assert "理性、冷静，遇到问题先观察。" in projected
    assert "害羞时轻轻偏头。" in projected
    freeform = "你是星河，冷静且不爱闲聊。"
    assert build_persona_motion_prompt(freeform) == freeform


def test_native_json_contract_omits_prompt_schema_but_prompt_only_keeps_it():
    from astrbot.core.provider.sources.deepseek_source import ProviderDeepSeek
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial

    contract = OutputContract(
        mode="json_object", strict=True,
        schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )
    engine = PromptRenderEngine(default_renderer=DeepSeekPromptRenderer())
    pack = ContextPack(slots={
        "input.text": ContextSlot("input.text", "hello", "input", "test"),
    })
    native = engine.render(pack, profile=PromptRenderProfile(
        name="native", system_prompt="Stable instructions", output_contract=contract,
        output_contract_strategy="protocol_native_json",
    ))
    prompted = engine.render(pack, profile=PromptRenderProfile(
        name="prompted", system_prompt="Stable instructions", output_contract=contract,
    ))
    assert native.compiled_output_contract.strategy == "protocol_native_json"
    assert "Stable instructions" in native.system_prompt
    assert "输出必须符合以下 JSON 结构" not in native.system_prompt
    assert "输出必须符合以下 JSON 结构" in prompted.system_prompt
    assert native.output_contract.schema == contract.schema

    provider = ProviderOpenAIOfficial.__new__(ProviderOpenAIOfficial)
    provider.provider_config = {"type": "openai_chat_completion"}
    assert provider.ensure_output_contract_supported(
        output_contract=native.output_contract,
        compiled_output_contract=native.compiled_output_contract,
    ) is native.compiled_output_contract

    unsupported = ProviderDeepSeek.__new__(ProviderDeepSeek)
    unsupported.provider_config = {"type": "deepseek_chat_completion"}
    with pytest.raises(ValueError, match="unsupported_output_contract"):
        unsupported.ensure_output_contract_supported(
            output_contract=native.output_contract,
            compiled_output_contract=native.compiled_output_contract,
        )
