from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.interaction.personal_policy import (
    PersonalPolicyAction,
    PersonalPolicyAgent,
    PersonalPolicyError,
    PersonalPolicyEvaluationStatus,
    build_personal_policy_output_contract,
    build_personal_policy_system_prompt,
    extract_personal_policy_decision,
)
from astrbot.core.interaction.types import InteractionAgentConfig
from astrbot.core.output_contract import CompiledOutputContract


def test_policy_prompt_requires_novel_facts_before_reexpressing():
    prompt = build_personal_policy_system_prompt()

    assert "最近 assistant 已表达相同意图" in prompt
    assert "Heartbeat 只表示到了评估时点" in prompt


def _compiled_contract():
    contract = build_personal_policy_output_contract()
    return contract, CompiledOutputContract(
        contract=contract,
        strategy="protocol_tool_call",
        tool_name=contract.preferred_tool_name,
        tool_schema=contract.schema,
    )


def _prompt_only_contract():
    contract = build_personal_policy_output_contract()
    return contract, CompiledOutputContract(
        contract=contract,
        strategy="prompt_only",
        degraded=True,
        degrade_reason="renderer_has_no_protocol_support",
    )


def test_policy_extraction_reports_invalid_matching_tool_call():
    contract, compiled = _compiled_contract()
    response = SimpleNamespace(
        tools_call_name=["personal_policy_decision"],
        tools_call_args=[
            {
                "action": "ignore",
                "reason_code": "insufficient_value",
                "reply_intent": "Only a heartbeat was observed.",
                "importance": 0.0,
                "defer_seconds": 0,
            }
        ],
    )

    with pytest.raises(PersonalPolicyError) as exc_info:
        extract_personal_policy_decision(response, contract, compiled)

    assert exc_info.value.reason == "invalid_policy_tool_call"


def test_policy_extraction_accepts_valid_matching_tool_call():
    contract, compiled = _compiled_contract()
    response = SimpleNamespace(
        tools_call_name=["personal_policy_decision"],
        tools_call_args=[
            {
                "action": "ignore",
                "reason_code": "insufficient_value",
                "reply_intent": "",
                "importance": 0.0,
                "defer_seconds": 0,
            }
        ],
    )

    decision = extract_personal_policy_decision(response, contract, compiled)

    assert decision.action is PersonalPolicyAction.IGNORE


def test_policy_extraction_rejects_prompt_only_json():
    contract, compiled = _prompt_only_contract()
    response = SimpleNamespace(
        completion_text=(
            '{"action":"ignore","reason_code":"insufficient_value",'
            '"reply_intent":"","importance":0.0,"defer_seconds":0}'
        ),
        tools_call_name=[],
        tools_call_args=[],
    )

    with pytest.raises(PersonalPolicyError) as exc_info:
        extract_personal_policy_decision(response, contract, compiled)

    assert exc_info.value.reason == "unsupported_policy_tool_call"


@pytest.mark.asyncio
async def test_policy_rejects_incompatible_provider_before_render_or_model_call(monkeypatch):
    class Provider:
        provider_config = {"id": "policy", "type": "test"}

        def supports_output_contract_strategy(self, strategy):
            return strategy == "prompt_only"

        async def text_chat(self, **_kwargs):
            raise AssertionError("incompatible policy provider must not be called")

    provider = Provider()
    agent = PersonalPolicyAgent()
    agent._prepare_render_result = AsyncMock(
        side_effect=AssertionError("incompatible policy provider must not be rendered")
    )
    on_provider_call_started = AsyncMock()
    monkeypatch.setattr("astrbot.core.interaction.personal_policy.Provider", Provider)

    result = await agent.evaluate(
        runtime_key=object(),
        batch=SimpleNamespace(batch_id="batch-1"),
        gate_result=SimpleNamespace(evaluated_at=1.0),
        state=object(),
        gate_settings=object(),
        plugin_context=SimpleNamespace(get_provider_by_id=lambda _provider_id: provider),
        runtime_config={},
        interaction_config=InteractionAgentConfig(
            personal_policy_enabled=True,
            personal_policy_provider_id="policy",
        ),
        on_provider_call_started=on_provider_call_started,
    )

    assert result is not None
    assert result.status is PersonalPolicyEvaluationStatus.FAIL_CLOSED
    assert result.failure_code == "unsupported_policy_tool_call"
    assert result.provider_call_started is False
    agent._prepare_render_result.assert_not_awaited()
    on_provider_call_started.assert_not_awaited()
