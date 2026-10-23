import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.interaction.core_router import (
    CoreRouterAgent,
    CoreRouterError,
    build_core_router_output_contract,
    build_core_router_system_prompt,
    extract_core_router_decision,
)
from astrbot.core.interaction.types import (
    CoreRouterAction,
    CoreRouterDecision,
    CoreRouterReason,
    InteractionAgentConfig,
)
from astrbot.core.output_contract import CompiledOutputContract


def test_core_router_output_is_typed_and_action_reason_pairs_are_consistent():
    contract = build_core_router_output_contract()

    assert contract.mode == "json_object"
    assert contract.strict is True
    assert len(contract.schema["anyOf"]) == 2
    assert all(
        branch["additionalProperties"] is False for branch in contract.schema["anyOf"]
    )
    assert extract_core_router_decision(
        '{"action":"route_to_core","reason_code":"visual_understanding"}'
    ) == CoreRouterDecision(
        CoreRouterAction.ROUTE_TO_CORE,
        CoreRouterReason.VISUAL_UNDERSTANDING,
    )
    assert extract_core_router_decision(
        '{"action":"personal_only","reason_code":"conversation"}'
    ).should_route_to_core is False

    with pytest.raises(CoreRouterError, match="invalid structured decision"):
        extract_core_router_decision(
            '{"action":"personal_only","reason_code":"external_action"}'
        )
    with pytest.raises(CoreRouterError, match="invalid structured decision"):
        extract_core_router_decision(
            '{"action":"route_to_core","reason_code":"external_action",'
            '"task_spec":"must not be returned"}'
        )


def test_core_router_prompt_is_independent_of_persona_and_executor_selection():
    prompt = build_core_router_system_prompt()

    assert "Personal 正在并行生成" in prompt
    assert "不决定 Personal 是否回复" in prompt
    assert "Core executor 已由当前 Profile 固定选择" in prompt
    assert "不选择执行器、工具、能力参数或任务步骤" in prompt
    assert "persona.prompt" not in prompt
    assert "人格记忆" not in prompt


@pytest.mark.asyncio
async def test_core_router_calls_selected_provider_with_structured_json_contract(monkeypatch):
    contract = build_core_router_output_contract()

    class Provider:
        provider_config = {"id": "router", "type": "test"}

        def __init__(self):
            self.calls = []

        async def text_chat(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                completion_text=json.dumps(
                    {
                        "action": "route_to_core",
                        "reason_code": "external_information",
                    }
                )
            )

    class Event:
        session_id = "session-1"

        def get_extra(self, _key, default=None):
            return default

        def get_platform_id(self):
            return "webchat"

    provider = Provider()
    agent = CoreRouterAgent()
    agent._prepare_render_result = AsyncMock(
        return_value=SimpleNamespace(
            output_contract=contract,
            compiled_output_contract=CompiledOutputContract(
                contract=contract,
                strategy="protocol_native_json",
            ),
            request_prompt="route this request",
            system_prompt="router policy",
            messages=[{"role": "user", "content": "latest weather"}],
        )
    )
    monkeypatch.setattr("astrbot.core.interaction.core_router.Provider", Provider)
    monkeypatch.setattr(
        "astrbot.core.interaction.core_router.resolve_interaction_chat_provider",
        AsyncMock(return_value=(provider, "router")),
    )

    decision = await agent.route(
        Event(),
        object(),
        InteractionAgentConfig(
            planner_provider_id="router",
            planner_timeout=2.0,
        ),
    )

    assert decision.should_route_to_core is True
    assert provider.calls[0]["output_contract"].mode == "json_object"
    assert provider.calls[0]["system_prompt"] == "router policy"
    agent._prepare_render_result.assert_awaited_once()
