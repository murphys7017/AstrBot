import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from anthropic.types import Message

from astrbot.core.interaction.personal_policy import (
    PersonalPolicyAction,
    PersonalPolicyError,
    build_personal_policy_output_contract,
    build_personal_policy_prompt,
    build_personal_policy_system_prompt,
    extract_personal_policy_decision,
)
from astrbot.core.prompt.context_types import ContextPack
from astrbot.core.prompt.render import (
    PromptRenderEngine,
    PromptRenderProfile,
    PromptTarget,
)
from astrbot.core.provider.entities import LLMResponse, ProviderRequest
from astrbot.core.provider.sources.minimax_token_plan_source import (
    ProviderMiniMaxTokenPlan,
)


def test_policy_prompt_requires_novel_facts_before_reexpressing():
    prompt = build_personal_policy_system_prompt()

    assert "最近 assistant 已表达相同意图" in prompt
    assert "Heartbeat 只表示到了评估时点" in prompt


@pytest.mark.parametrize(
    "text",
    [
        '{"action":"ignore","reason_code":"insufficient_value",'
        '"reply_intent":"Only a heartbeat was observed.",'
        '"importance":0.0,"defer_seconds":0}',
        '{"action":"express","reason_code":"social_opportunity",'
        '"reply_intent":"hello","importance":0.5,"defer_seconds":0',
        '```json\n{"action":"ignore"}\n```',
    ],
)
def test_policy_extraction_rejects_invalid_text(text):
    with pytest.raises(PersonalPolicyError) as exc_info:
        extract_personal_policy_decision(
            LLMResponse(role="assistant", completion_text=text)
        )

    assert exc_info.value.reason == "invalid_policy_payload"


def test_policy_extraction_rejects_unexpected_tools():
    response = LLMResponse(
        role="assistant",
        tools_call_name=["personal_policy_decision"],
        tools_call_args=[{}],
    )

    with pytest.raises(PersonalPolicyError) as exc_info:
        extract_personal_policy_decision(response)

    assert exc_info.value.reason == "unexpected_policy_tool_call"


@pytest.mark.asyncio
async def test_policy_json_text_crosses_minimax_provider_boundary_without_tools():
    provider = ProviderMiniMaxTokenPlan(
        {
            "id": "policy",
            "type": "minimax_token_plan",
            "key": ["test-key"],
            "model": "MiniMax-M3.1-Flash",
        },
        {},
    )
    payload = {
        "action": "express",
        "reason_code": "social_opportunity",
        "reply_intent": "自然承接近期话题",
        "importance": 0.5,
        "defer_seconds": 0,
    }
    create = AsyncMock(
        return_value=Message(
            id="policy-response",
            type="message",
            role="assistant",
            model=provider.get_model(),
            content=[{"type": "text", "text": json.dumps(payload)}],
            stop_reason="end_turn",
            usage={"input_tokens": 100, "output_tokens": 30},
        )
    )
    client = provider.client
    provider.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    try:
        request = ProviderRequest()
        request.provider = provider
        rendered = PromptRenderEngine().render(
            ContextPack(),
            target=PromptTarget.PERSONAL_POLICY,
            provider_request=request,
            profile=PromptRenderProfile(
                name="personal_policy",
                system_prompt=build_personal_policy_system_prompt(),
                request_prompt=build_personal_policy_prompt(),
                output_contract=build_personal_policy_output_contract(),
            ),
        )
        response = await provider.text_chat(
            prompt=rendered.request_prompt,
            contexts=rendered.messages,
            system_prompt=rendered.system_prompt,
            output_contract=rendered.output_contract,
            compiled_output_contract=rendered.compiled_output_contract,
        )
    finally:
        await client.close()

    wire_payload = create.call_args.kwargs
    assert "tools" not in wire_payload
    assert "tool_choice" not in wire_payload
    assert not (wire_payload.get("extra_body") or {}).get("tools")
    assert rendered.compiled_output_contract.strategy == "prompt_only"
    assert not rendered.compiled_output_contract.degraded
    assert "只输出一个 JSON object" in str(wire_payload["system"])
    decision = extract_personal_policy_decision(response)
    assert decision.action is PersonalPolicyAction.EXPRESS
    assert decision.reply_intent == payload["reply_intent"]
