from __future__ import annotations

import asyncio
import json

from astrbot import logger
from astrbot.core.deadline import TurnDeadlineExceeded
from astrbot.core.output_contract import CompiledOutputContract, OutputContract
from astrbot.core.prompt.render import (
    PromptRenderEngine,
    PromptRenderProfile,
    PromptTarget,
)
from astrbot.core.provider import Provider
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.star.context import Context

from .context_builder import (
    build_prompt_render_provider_request,
    get_or_build_interaction_context_material,
    get_or_build_interaction_media_context_pack,
    provider_supports_modality,
)
from .prompt_support import (
    build_interaction_prompt_build_config,
    build_model_context_messages,
)
from .provider_resolution import resolve_interaction_chat_provider
from .turn_state import (
    get_interaction_turn_deadline,
    get_interaction_turn_state,
)
from .types import CorePlanningAction, CorePlanningDecision, InteractionAgentConfig


class CorePlannerError(RuntimeError):
    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


def build_core_planner_system_prompt() -> str:
    return (
        "你是 Core Planner，负责把已经委派给 Core 的当前任务整理为执行规格。\n"
        "Router 已完成对话与任务的分流，Planner 输出固定为 execute。\n"
        "以当前请求为任务来源，使用历史和 memory 完成必要消歧，并在当前请求续接时恢复已开始的 Core 任务。\n"
        "把当前请求整理为简洁、完整、可执行的 CoreTaskSpec；"
        "suggested_capabilities 只使用与任务直接相关的能力意图：需要当前轮联网检索时必须填 web_research，"
        "需要文件处理时填 workspace_io，需要计算时填 computation。"
        "当前消息或引用图片的视觉理解使用 requires_visual_understanding 表达，工作区读写使用 workspace_io 表达。"
        "web_research 表示在当前 Core 回合完成联网检索。"
        "CoreTaskSpec 只描述用户要完成的工作目标、执行提示和能力意图，采用当前 Core 工具快照。\n"
        "输出结构化决策对象，decision 为 execute。"
    )


def build_core_planner_prompt() -> str:
    return "为 Router 已路由的当前请求生成 CoreTaskSpec，仅输出符合决策结构的 JSON 对象，decision 必须为 execute。"


def build_core_planner_output_contract() -> OutputContract:
    task_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "task_intent": {"type": "string", "minLength": 1},
            "task_summary": {"type": "string", "minLength": 1},
            "execution_prompt": {"type": "string", "minLength": 1},
            "suggested_capabilities": {
                "type": "array",
                "items": {"type": "string"},
            },
            "requires_visual_understanding": {"type": "boolean"},
        },
        "required": [
            "task_intent",
            "task_summary",
            "execution_prompt",
            "suggested_capabilities",
            "requires_visual_understanding",
        ],
    }
    return OutputContract(
        mode="json_object",
        strict=True,
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "decision": {
                    "type": "string",
                    "const": "execute",
                },
                "core_task_spec": task_schema,
            },
            "required": ["decision", "core_task_spec"],
        },
    )


def extract_core_planning_decision(llm_response: LLMResponse) -> CorePlanningDecision:
    if llm_response.tools_call_name or llm_response.tools_call_args:
        raise CorePlannerError("unexpected_core_planner_tool_call")
    try:
        payload = json.loads(llm_response.completion_text)
    except (TypeError, ValueError) as exc:
        raise CorePlannerError("invalid_core_planner_payload") from exc
    decision = CorePlanningDecision.from_mapping(payload)
    if (
        decision is None
        or "requires_visual_understanding" not in payload["core_task_spec"]
    ):
        raise CorePlannerError(
            "invalid_core_planner_payload",
            "Core Planner returned an invalid structured result",
        )
    return decision


class CorePlannerAgent:
    async def ensure_available(
        self,
        event,
        plugin_context: Context,
        interaction_config: InteractionAgentConfig,
    ) -> str:
        """Validate the configured Planner before Router can delegate a turn."""

        try:
            provider, provider_id = await resolve_interaction_chat_provider(
                event,
                plugin_context,
                interaction_config.planner_provider_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise CorePlannerError("provider_resolution_error", str(exc)) from exc
        self._validate_provider(provider, provider_id)
        return provider_id

    @staticmethod
    def _validate_provider(provider: object, provider_id: str) -> None:
        if not isinstance(provider, Provider):
            raise CorePlannerError(
                "provider_unavailable",
                f"provider unavailable: provider_id={provider_id}",
            )
        if not provider.supports_output_contract_strategy("prompt_only"):
            raise CorePlannerError(
                "unsupported_output_contract",
                "Core Planner requires a provider with prompt_only support",
            )

    async def plan(
        self,
        event,
        plugin_context: Context,
        interaction_config: InteractionAgentConfig,
    ) -> CorePlanningDecision:
        provider, provider_id = await resolve_interaction_chat_provider(
            event,
            plugin_context,
            interaction_config.planner_provider_id,
        )
        self._validate_provider(provider, provider_id)
        render_result = await self._prepare_render_result(
            event,
            plugin_context,
            interaction_config,
            provider,
        )
        contract = render_result.output_contract
        compiled = render_result.compiled_output_contract
        if not isinstance(contract, OutputContract) or not isinstance(
            compiled,
            CompiledOutputContract,
        ):
            raise CorePlannerError("unsupported_output_contract")
        if contract.mode != "json_object" or compiled.strategy != "prompt_only":
            raise CorePlannerError(
                "unsupported_output_contract",
                "Core Planner requires a prompt-only JSON output contract",
            )
        deadline = get_interaction_turn_deadline(event)
        try:
            timeout_context = (
                deadline.enforce(
                    "core_planner",
                    interaction_config.planner_timeout,
                )
                if deadline is not None
                else asyncio.timeout(interaction_config.planner_timeout)
            )
            async with timeout_context:
                response = await provider.text_chat(
                    prompt=render_result.request_prompt or "",
                    contexts=build_model_context_messages(
                        render_result.messages,
                        provider=provider,
                    ),
                    system_prompt=render_result.system_prompt or "",
                    temperature=interaction_config.planner_temperature,
                    output_contract=contract,
                    compiled_output_contract=compiled,
                )
        except TurnDeadlineExceeded:
            raise
        except TimeoutError:
            raise CorePlannerError("timeout") from None
        except Exception as exc:
            raise CorePlannerError("model_error", str(exc)) from exc
        decision = extract_core_planning_decision(response)
        if (
            decision.action is not CorePlanningAction.EXECUTE
            or decision.task_spec is None
        ):
            raise CorePlannerError(
                "delegated_task_not_executable",
                "Core Planner must return execute for a Router-routed task",
            )
        logger.info(
            "Core Planner parsed: turn_id=%s target=core_planner platform_id=%s "
            "session_id=%s decision=%s task_intent=%s suggested_capabilities=%s "
            "requires_visual_understanding=%s execution_prompt_length=%s "
            "direct_web_research=%s",
            str(event.get_extra("_turn_id", "") or ""),
            event.get_platform_id(),
            event.session_id,
            decision.action.value,
            decision.task_spec.task_intent if decision.task_spec else "",
            decision.task_spec.suggested_capabilities if decision.task_spec else [],
            decision.task_spec.requires_visual_understanding
            if decision.task_spec
            else False,
            len(decision.task_spec.execution_prompt) if decision.task_spec else 0,
            decision.task_spec.requires_direct_web_research()
            if decision.task_spec
            else False,
        )
        return decision

    async def _prepare_render_result(
        self,
        event,
        plugin_context: Context,
        interaction_config: InteractionAgentConfig,
        provider: Provider,
    ):
        build_config = build_interaction_prompt_build_config(plugin_context, event)
        turn_state = get_interaction_turn_state(event)
        if turn_state is not None:
            async with turn_state.lock:
                material = await get_or_build_interaction_context_material(
                    event=event,
                    plugin_context=plugin_context,
                    interaction_config=interaction_config,
                    build_config=build_config,
                )
        else:
            material = await get_or_build_interaction_context_material(
                event=event,
                plugin_context=plugin_context,
                interaction_config=interaction_config,
                build_config=build_config,
            )
        planner_pack = await get_or_build_interaction_media_context_pack(
            event=event,
            plugin_context=plugin_context,
            build_config=build_config,
            material=material,
            base_context_pack=material.prompt_context_pack,
            provider=provider,
            cache_key="core_planner",
        )
        hidden_slot_names = (
            frozenset({"input.images", "input.quoted_images"})
            if not provider_supports_modality(provider, "image")
            else frozenset()
        )
        render_result = PromptRenderEngine().render(
            planner_pack,
            target=PromptTarget.CORE_PLANNER,
            event=event,
            plugin_context=plugin_context,
            config=build_config,
            provider_request=build_prompt_render_provider_request(event, provider),
            profile=PromptRenderProfile(
                name="interaction_core_planner",
                system_prompt=build_core_planner_system_prompt(),
                request_prompt=build_core_planner_prompt(),
                output_contract=build_core_planner_output_contract(),
                hidden_slot_names=hidden_slot_names,
            ),
        )
        return render_result


__all__ = [
    "CorePlannerAgent",
    "CorePlannerError",
    "build_core_planner_output_contract",
    "build_core_planner_system_prompt",
    "extract_core_planning_decision",
]
