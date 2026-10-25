import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from anthropic.types import Message

from astrbot.core.interaction.core_planner import (
    CorePlannerAgent,
    CorePlannerError,
    build_core_planner_output_contract,
    build_core_planner_prompt,
    build_core_planner_system_prompt,
    extract_core_planning_decision,
)
from astrbot.core.interaction.types import (
    CorePlanningAction,
    CoreTaskSpec,
    InteractionAgentConfig,
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
from astrbot.core.tools.web_search_tools import is_web_search_tool_name


def _execute_payload() -> dict:
    return {
        "decision": "execute",
        "core_task_spec": {
            "task_intent": "lookup",
            "task_summary": "查询当前时间",
            "execution_prompt": "查询当前时间并返回时区明确的结果。",
            "suggested_capabilities": ["time"],
            "requires_visual_understanding": False,
        },
    }


def test_core_planner_prompt_has_no_prior_decision_surface():
    prompt = build_core_planner_system_prompt()

    assert "hybrid" not in prompt
    assert "silent" not in prompt
    assert "Router" in prompt
    assert "不要重新做路由判断" in prompt
    assert "Personal 的统一结构化回复计划" not in prompt
    assert "插件目录" not in prompt
    assert "web_research" in prompt


def test_core_task_spec_marks_web_research_as_direct_execution():
    assert CoreTaskSpec(
        suggested_capabilities=["web_research"]
    ).requires_direct_web_research()
    assert CoreTaskSpec(
        task_intent="查询模型评价",
        task_summary="联网搜索公开测评和用户反馈",
        execution_prompt="请联网检索并汇总网上资料。",
        suggested_capabilities=["知识检索"],
    ).requires_direct_web_research()
    assert (
        CoreTaskSpec(
            suggested_capabilities=["workspace_io"]
        ).requires_direct_web_research()
        is False
    )


def test_web_search_capability_detection_includes_namespaced_tools():
    assert is_web_search_tool_name("web__search") is True
    assert is_web_search_tool_name("web__open") is False
    assert is_web_search_tool_name("weather__lookup") is False


def test_core_task_spec_keeps_visual_requirement_out_of_workspace_io():
    payload = _execute_payload()["core_task_spec"]
    payload["requires_visual_understanding"] = True

    task_spec = CoreTaskSpec.from_mapping(payload)

    assert task_spec is not None
    assert task_spec.requires_visual_understanding is True
    assert task_spec.suggested_capabilities == ["time"]

    payload["suggested_capabilities"] = ["workspace_io"]
    task_spec = CoreTaskSpec.from_mapping(payload)
    assert task_spec is not None
    assert task_spec.suggested_capabilities == []


def test_core_planner_accepts_json_text():
    decision = extract_core_planning_decision(
        LLMResponse(role="assistant", completion_text=json.dumps(_execute_payload()))
    )
    assert decision.action is CorePlanningAction.EXECUTE
    assert decision.task_spec is not None
    assert decision.task_spec.execution_prompt.startswith("查询当前时间")


def test_core_planner_rejects_not_required_for_delegated_task():

    with pytest.raises(CorePlannerError, match="invalid structured result"):
        extract_core_planning_decision(
            LLMResponse(
                role="assistant",
                completion_text='{"decision":"not_required","core_task_spec":null}',
            )
        )


def test_core_planner_rejects_unexpected_tool_call():
    response = LLMResponse(
        role="assistant",
        tools_call_name=["core_execution_plan"],
        tools_call_args=[_execute_payload()],
    )
    with pytest.raises(CorePlannerError, match="unexpected_core_planner_tool_call"):
        extract_core_planning_decision(response)


def test_core_planner_rejects_execute_without_task_spec():

    with pytest.raises(CorePlannerError, match="invalid structured result"):
        extract_core_planning_decision(
            LLMResponse(
                role="assistant",
                completion_text='{"decision":"execute","core_task_spec":null}',
            )
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"decision": "not_required"},
        {"decision": "not_required", "core_task_spec": {}},
        {
            "decision": "execute",
            "core_task_spec": {
                key: value
                for key, value in _execute_payload()["core_task_spec"].items()
                if key != "requires_visual_understanding"
            },
        },
        {
            "decision": "execute",
            "core_task_spec": {
                "task_summary": "查询当前时间",
                "execution_prompt": "查询当前时间。",
                "suggested_capabilities": [],
            },
        },
        {
            "decision": "execute",
            "core_task_spec": {
                "task_intent": "lookup",
                "task_summary": "查询当前时间",
                "execution_prompt": "查询当前时间。",
                "suggested_capabilities": "time",
            },
        },
        {
            "decision": "execute",
            "core_task_spec": {
                "task_intent": "lookup",
                "task_summary": "查询当前时间",
                "execution_prompt": "查询当前时间。",
                "suggested_capabilities": [1],
            },
        },
    ],
)
def test_core_planner_rejects_payloads_that_violate_declared_schema(payload):

    with pytest.raises(CorePlannerError, match="invalid structured result"):
        extract_core_planning_decision(
            LLMResponse(role="assistant", completion_text=json.dumps(payload))
        )


@pytest.mark.parametrize(
    "empty_field", ["task_intent", "task_summary", "execution_prompt"]
)
def test_core_planner_rejects_execute_with_empty_required_task_field(empty_field):
    payload = _execute_payload()
    payload["core_task_spec"][empty_field] = "  "

    with pytest.raises(CorePlannerError, match="invalid structured result"):
        extract_core_planning_decision(
            LLMResponse(role="assistant", completion_text=json.dumps(payload))
        )


def test_core_planner_contract_requires_nonempty_task_fields():
    task_schema = build_core_planner_output_contract().schema["properties"][
        "core_task_spec"
    ]

    assert task_schema["properties"]["task_intent"]["minLength"] == 1
    assert task_schema["properties"]["task_summary"]["minLength"] == 1
    assert task_schema["properties"]["execution_prompt"]["minLength"] == 1


@pytest.mark.asyncio
async def test_core_planner_json_text_crosses_minimax_boundary_without_tools():
    provider = ProviderMiniMaxTokenPlan(
        {
            "id": "planner",
            "type": "minimax_token_plan",
            "key": ["test-key"],
            "model": "MiniMax-M3.1-Flash",
        },
        {},
    )
    create = AsyncMock(
        return_value=Message(
            id="planner-response",
            type="message",
            role="assistant",
            model=provider.get_model(),
            content=[{"type": "text", "text": json.dumps(_execute_payload())}],
            stop_reason="end_turn",
            usage={"input_tokens": 100, "output_tokens": 30},
        )
    )
    client = provider.client
    provider.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    try:
        selected = await CorePlannerAgent().ensure_available(
            SimpleNamespace(),
            SimpleNamespace(get_provider_by_id=lambda _id: provider),
            InteractionAgentConfig(planner_provider_id="planner"),
        )
        assert selected == "planner"
        request = ProviderRequest()
        request.provider = provider
        rendered = PromptRenderEngine().render(
            ContextPack(),
            target=PromptTarget.CORE_PLANNER,
            provider_request=request,
            profile=PromptRenderProfile(
                name="interaction_core_planner",
                system_prompt=build_core_planner_system_prompt(),
                request_prompt=build_core_planner_prompt(),
                output_contract=build_core_planner_output_contract(),
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
    assert extract_core_planning_decision(response).action is CorePlanningAction.EXECUTE
