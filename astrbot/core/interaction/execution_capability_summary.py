"""Read-only Core capability projection used by independent Core routing."""

from __future__ import annotations

from dataclasses import dataclass

from astrbot import logger
from astrbot.core.agent.tool import TOOL_TARGET_CORE
from astrbot.core.capabilities import CapabilityResolver
from astrbot.core.execution_capabilities import WEB_RESEARCH_CAPABILITY
from astrbot.core.star.context import Context

from .turn_state import (
    get_interaction_turn_state,
    resolve_interaction_turn_runtime_configuration,
)
from .types import InteractionPromptBuildConfig

_WEB_PROVIDER_TOOL_NAMES = {
    "tavily": "web_search_tavily",
    "bocha": "web_search_bocha",
    "brave": "web_search_brave",
    "firecrawl": "web_search_firecrawl",
    "baidu_ai_search": "web_search_baidu",
    "exa": "web_search_exa",
}


@dataclass(frozen=True, slots=True)
class ExecutionCapability:
    capability_id: str
    state: str
    executor: str = "core"
    bindings: tuple[str, ...] = ()
    personal_can_call: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.capability_id,
            "state": self.state,
            "executor": self.executor,
            "bindings": list(self.bindings),
            "personal_can_call": self.personal_can_call,
        }


@dataclass(frozen=True, slots=True)
class ExecutionCapabilitySummary:
    config_id: str
    capabilities: tuple[ExecutionCapability, ...]
    format: str = "execution_capability_summary_v1"
    target: str = "core"

    def get(self, capability_id: str) -> ExecutionCapability | None:
        return next(
            (
                capability
                for capability in self.capabilities
                if capability.capability_id == capability_id
            ),
            None,
        )

    def admitted_ids(self) -> tuple[str, ...]:
        return tuple(
            capability.capability_id
            for capability in self.capabilities
            if capability.state == "admitted"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "format": self.format,
            "target": self.target,
            "config_id": self.config_id,
            "capabilities": [
                capability.to_dict() for capability in self.capabilities
            ],
        }

def get_core_execution_capability_summary(
    event,
) -> ExecutionCapabilitySummary | None:
    state = get_interaction_turn_state(event)
    summary = (
        state.core_execution_capability_summary if state is not None else None
    )
    return summary if isinstance(summary, ExecutionCapabilitySummary) else None


async def resolve_core_execution_capability_summary(
    *,
    event,
    plugin_context: Context,
    config: InteractionPromptBuildConfig,
    persona_selection: tuple[str | None, dict[str, object] | None] | None = None,
) -> ExecutionCapabilitySummary:
    state = get_interaction_turn_state(event)
    existing = get_core_execution_capability_summary(event)
    if existing is not None:
        return existing

    _, config_id = resolve_interaction_turn_runtime_configuration(event)
    tool_names: set[str] = set()
    capability_state = "unavailable"
    try:
        snapshot = await CapabilityResolver().resolve(
            event=event,
            plugin_context=plugin_context,
            config=config,
            target=TOOL_TARGET_CORE,
            provider_request=None,
            persona_selection=persona_selection,
            include_tool_schema=False,
        )
        bindings = snapshot.semantic_capability_bindings().get(
            WEB_RESEARCH_CAPABILITY,
            (),
        )
        tool_names.update(
            binding.tool_name
            for binding in bindings
            if getattr(binding, "tool_name", "")
        )
        provider_settings = config.provider_settings
        if provider_settings.get("web_search", False) is True:
            provider = str(
                provider_settings.get("websearch_provider", "tavily") or "tavily"
            ).strip()
            configured_tool = _WEB_PROVIDER_TOOL_NAMES.get(provider)
            if configured_tool:
                tool_names.add(configured_tool)
        if tool_names:
            capability_state = "admitted"
    except Exception as exc:  # noqa: BLE001
        capability_state = "unknown"
        logger.warning(
            "Core capability summary resolution failed: turn_id=%s config_id=%s error=%s",
            str(event.get_extra("_turn_id", "") or ""),
            config_id,
            exc,
        )

    summary = ExecutionCapabilitySummary(
        config_id=config_id,
        capabilities=(
            ExecutionCapability(
                capability_id=WEB_RESEARCH_CAPABILITY,
                state=capability_state,
                bindings=tuple(sorted(tool_names)),
            ),
        ),
    )
    if state is not None and state.core_execution_capability_summary is None:
        state.core_execution_capability_summary = summary
        summary = state.core_execution_capability_summary
    logger.debug(
        "DIAG interaction.core_capability_summary: turn_id=%s config_id=%s "
        "capability_ids=%s web_research_state=%s bindings=%s",
        str(event.get_extra("_turn_id", "") or ""),
        config_id,
        list(summary.admitted_ids()),
        summary.get(WEB_RESEARCH_CAPABILITY).state,
        list(summary.get(WEB_RESEARCH_CAPABILITY).bindings),
    )
    return summary


__all__ = [
    "ExecutionCapability",
    "ExecutionCapabilitySummary",
    "get_core_execution_capability_summary",
    "resolve_core_execution_capability_summary",
]
