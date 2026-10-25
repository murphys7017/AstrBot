"""Resolve executable tool capabilities for one runtime target."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.core import logger
from astrbot.core.agent.handoff import HandoffTool
from astrbot.core.agent.tool import (
    TOOL_TARGET_PERSONAL_EXPRESSION,
    FunctionTool,
    ToolSet,
    normalize_action_semantic_capabilities,
    normalize_semantic_capabilities,
    normalize_tool_targets,
    tool_description_for_model,
)
from astrbot.core.persona_resolution import resolve_event_persona
from astrbot.core.plugin_runtime import (
    tool_plugin_is_selected,
    tool_supports_runtime_target,
)
from astrbot.core.utils.runtime_diagnostics import measure_runtime_stage

if TYPE_CHECKING:
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.provider.entities import ProviderRequest
    from astrbot.core.star.context import Context


CAPABILITY_REASON_INCLUDED = "included"
CAPABILITY_REASON_INACTIVE = "inactive"
CAPABILITY_REASON_TARGET_MISMATCH = "target_mismatch"
CAPABILITY_REASON_PLUGIN_NOT_SELECTED = "plugin_not_selected"
CAPABILITY_REASON_PERSONA_NOT_SELECTED = "persona_not_selected"
CAPABILITY_REASON_SUBAGENT_CORE_ONLY = "subagent_core_only"
CAPABILITY_REASON_SUBAGENT_OWNED = "subagent_owned"
CAPABILITY_REASON_EXECUTION_POLICY = "execution_policy"
CAPABILITY_REASON_UNKNOWN_TOOL = "unknown_tool"


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    """Stable admission result for one named tool candidate."""

    tool_name: str
    included: bool
    reason: str


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    """Immutable capability selection for one turn and execution target.

    Tool objects remain live execution handles. The surrounding tuple and
    serialized records are detached from mutable manager inventories.
    Admission-only readers may omit schemas; such a snapshot explicitly rejects
    inventory serialization rather than pretending to contain an empty inventory.
    """

    target: str
    persona_id: str | None
    selection_mode: str
    tools: tuple[FunctionTool, ...] = ()
    decisions: tuple[CapabilityDecision, ...] = ()
    include_tool_schema: bool = field(default=True, repr=False, compare=False)
    _serialized_tools: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        normalize_tool_targets((self.target,))
        tools = tuple(self.tools)
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "decisions", tuple(self.decisions))
        serialized_tools = (
            sorted(
                (_serialize_tool(tool) for tool in tools),
                key=lambda item: str(item.get("name", "")),
            )
            if self.include_tool_schema
            else ()
        )
        object.__setattr__(self, "_serialized_tools", tuple(serialized_tools))

    @classmethod
    def empty(
        cls,
        *,
        target: str,
        persona_id: str | None = None,
        selection_mode: str = "none",
        decisions: tuple[CapabilityDecision, ...] = (),
    ) -> CapabilitySnapshot:
        return cls(
            target=target,
            persona_id=persona_id,
            selection_mode=selection_mode,
            decisions=decisions,
        )

    def is_empty(self) -> bool:
        return not self.tools

    def names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    def to_toolset(self) -> ToolSet:
        """Return a detached ToolSet that retains the selected live handlers."""
        return ToolSet(list(self.tools))

    def serialized_tools(self) -> list[dict[str, Any]]:
        if not self.include_tool_schema:
            raise ValueError("capability_snapshot_admission_only")
        return deepcopy(list(self._serialized_tools))

    def serialized_inventory(self) -> dict[str, Any]:
        tools = self.serialized_tools()
        return {
            "format": "tool_inventory_v1",
            "tool_count": len(tools),
            "tools": tools,
        }

    def semantic_capability_bindings(self) -> dict[str, tuple[Any, ...]]:
        """Project semantic capabilities without changing tool admission."""
        from astrbot.core.execution_capabilities import (
            collect_semantic_capability_bindings,
        )

        return collect_semantic_capability_bindings(self.tools)

    def inventory_metadata(self) -> dict[str, Any]:
        return {
            "format": "tool_inventory_v1",
            "tool_count": len(self.tools),
            "persona_id": self.persona_id,
            "selection_mode": self.selection_mode,
            "tool_target": self.target,
            "decision_count": len(self.decisions),
            "excluded_reasons": self.excluded_reason_counts(),
        }

    def excluded_reason_counts(self) -> dict[str, int]:
        return dict(
            Counter(
                decision.reason for decision in self.decisions if not decision.included
            )
        )


class CapabilityResolver:
    """Single owner for persona selection and runtime tool admission."""

    async def resolve(
        self,
        *,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: object,
        target: str,
        provider_request: ProviderRequest | None = None,
        persona_selection: tuple[str | None, dict[str, Any] | None] | None = None,
        include_registered_tools: bool = False,
        excluded_tool_names: frozenset[str] = frozenset(),
        exclude_handoff_tools: bool = False,
        include_tool_schema: bool = True,
    ) -> CapabilitySnapshot:
        request_toolset = (
            provider_request.func_tool if provider_request is not None else None
        )
        if isinstance(request_toolset, ToolSet) and not include_registered_tools:
            return self.resolve_explicit_toolset(
                event=event,
                target=target,
                toolset=request_toolset,
                persona_id=self._request_persona_id(provider_request),
                excluded_tool_names=excluded_tool_names,
                exclude_handoff_tools=exclude_handoff_tools,
                include_tool_schema=include_tool_schema,
            )

        with measure_runtime_stage(event, "capability.persona", target=target):
            if persona_selection is None:
                persona_id, persona = await self._resolve_persona(
                    event=event,
                    plugin_context=plugin_context,
                    config=config,
                    provider_request=provider_request,
                )
            else:
                persona_id, persona = persona_selection
        with measure_runtime_stage(event, "capability.inventory", target=target):
            tool_manager = plugin_context.get_llm_tool_manager()
            if tool_manager is None:
                registered_candidates: list[FunctionTool] = []
                selection_mode = "none"
                pre_decisions: list[CapabilityDecision] = []
            else:
                (
                    registered_candidates,
                    selection_mode,
                    pre_decisions,
                ) = self._select_registered_tools(
                    tool_manager=tool_manager,
                    persona=persona,
                )

        candidate_groups: list[list[FunctionTool]] = []
        if not isinstance(request_toolset, ToolSet) or include_registered_tools:
            candidate_groups.append(registered_candidates)
        if isinstance(request_toolset, ToolSet):
            candidate_groups.append(list(request_toolset))
        if isinstance(request_toolset, ToolSet):
            selection_mode = (
                f"provider_request+{selection_mode}"
                if include_registered_tools
                else "provider_request"
            )

        with measure_runtime_stage(
            event,
            "capability.candidates",
            target=target,
            registered_count=len(registered_candidates),
            request_count=len(request_toolset) if isinstance(request_toolset, ToolSet) else 0,
        ):
            candidates = self._merge_candidate_groups(*candidate_groups)

        return self._resolve_candidates(
            event=event,
            target=target,
            persona_id=persona_id,
            selection_mode=selection_mode,
            candidates=candidates,
            pre_decisions=pre_decisions,
            excluded_tool_names=excluded_tool_names,
            exclude_handoff_tools=exclude_handoff_tools,
            include_tool_schema=include_tool_schema,
        )

    @staticmethod
    def _merge_candidate_groups(
        *groups: list[FunctionTool],
    ) -> list[FunctionTool]:
        """Merge tools in order while preserving ToolSet.add_tool conflict rules."""
        candidates: list[FunctionTool] = []
        positions: dict[str, int] = {}
        for group in groups:
            for tool in group:
                position = positions.get(tool.name)
                if position is None:
                    positions[tool.name] = len(candidates)
                    candidates.append(tool)
                    continue
                existing = candidates[position]
                existing_active = bool(getattr(existing, "active", True))
                new_active = bool(getattr(tool, "active", True))
                if new_active or not existing_active:
                    candidates[position] = tool
        return candidates

    def resolve_explicit_toolset(
        self,
        *,
        event: AstrMessageEvent,
        target: str,
        toolset: ToolSet,
        persona_id: str | None = None,
        selection_mode: str = "provider_request",
        excluded_tool_names: frozenset[str] = frozenset(),
        exclude_handoff_tools: bool = False,
        include_tool_schema: bool = True,
    ) -> CapabilitySnapshot:
        """Resolve a request-owned candidate set without consulting globals."""
        return self._resolve_candidates(
            event=event,
            target=target,
            persona_id=persona_id,
            selection_mode=selection_mode,
            candidates=list(toolset),
            pre_decisions=[],
            excluded_tool_names=excluded_tool_names,
            exclude_handoff_tools=exclude_handoff_tools,
            include_tool_schema=include_tool_schema,
        )

    @staticmethod
    def _select_registered_tools(
        *,
        tool_manager,
        persona: dict[str, Any] | None,
    ) -> tuple[list[FunctionTool], str, list[CapabilityDecision]]:
        registered_tools = list(tool_manager.func_list)
        allowed_names = persona.get("tools") if isinstance(persona, dict) else None
        if not persona or allowed_names is None:
            return registered_tools, "all", []
        if not isinstance(allowed_names, list) or not allowed_names:
            return (
                [],
                "none",
                [
                    CapabilityDecision(
                        tool_name=str(getattr(tool, "name", "") or ""),
                        included=False,
                        reason=CAPABILITY_REASON_PERSONA_NOT_SELECTED,
                    )
                    for tool in registered_tools
                ],
            )

        selected_names = []
        for raw_name in allowed_names:
            name = str(raw_name).strip()
            if name and name not in selected_names:
                selected_names.append(name)
        candidates = []
        for name in selected_names:
            tool = tool_manager.get_func(name)
            if tool is not None:
                candidates.append(tool)
        found_names = {tool.name for tool in candidates}
        decisions = [
            CapabilityDecision(
                tool_name=tool.name,
                included=False,
                reason=CAPABILITY_REASON_PERSONA_NOT_SELECTED,
            )
            for tool in registered_tools
            if tool.name not in selected_names
        ]
        decisions.extend(
            CapabilityDecision(
                tool_name=name,
                included=False,
                reason=CAPABILITY_REASON_UNKNOWN_TOOL,
            )
            for name in selected_names
            if name not in found_names
        )
        return candidates, "whitelist", decisions

    def _resolve_candidates(
        self,
        *,
        event: AstrMessageEvent,
        target: str,
        persona_id: str | None,
        selection_mode: str,
        candidates: list[FunctionTool],
        pre_decisions: list[CapabilityDecision],
        excluded_tool_names: frozenset[str],
        exclude_handoff_tools: bool,
        include_tool_schema: bool,
    ) -> CapabilitySnapshot:
        selected = ToolSet()
        decisions = list(pre_decisions)
        with measure_runtime_stage(event, "capability.admission", target=target, candidate_count=len(candidates)):
            for tool in candidates:
                reason = self._exclusion_reason(
                    event,
                    tool,
                    target,
                    excluded_tool_names,
                    exclude_handoff_tools,
                )
                included = reason is None
                decisions.append(
                    CapabilityDecision(
                        tool_name=str(getattr(tool, "name", "") or ""),
                        included=included,
                        reason=reason or CAPABILITY_REASON_INCLUDED,
                    )
                )
                if included:
                    selected.add_tool(tool)

        with measure_runtime_stage(event, "capability.schema", target=target, selected_count=len(selected)):
            return self._build_snapshot(
                target=target,
                persona_id=persona_id,
                selection_mode=selection_mode,
                tools=list(selected),
                decisions=decisions,
                include_tool_schema=include_tool_schema,
            )

    def _build_snapshot(
        self,
        *,
        target: str,
        persona_id: str | None,
        selection_mode: str,
        tools: list[FunctionTool],
        decisions: list[CapabilityDecision],
        include_tool_schema: bool,
    ) -> CapabilitySnapshot:
        snapshot = CapabilitySnapshot(
            target=target,
            persona_id=persona_id,
            selection_mode=selection_mode,
            tools=tuple(tools),
            decisions=tuple(decisions),
            include_tool_schema=include_tool_schema,
        )
        logger.debug(
            "Capability snapshot resolved: target=%s persona_id=%s "
            "selection_mode=%s tool_count=%s tool_names=%s excluded_reasons=%s",
            target,
            persona_id,
            selection_mode,
            len(snapshot.tools),
            snapshot.names(),
            snapshot.excluded_reason_counts(),
        )
        return snapshot

    @staticmethod
    async def _resolve_persona(
        *,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: object,
        provider_request: ProviderRequest | None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        request = provider_request or event.get_extra("provider_request")
        conversation_persona_id = CapabilityResolver._request_persona_id(request)
        persona_manager = getattr(plugin_context, "persona_manager", None)
        if persona_manager is None:
            return conversation_persona_id, None

        resolution = await resolve_event_persona(
            event=event,
            persona_manager=persona_manager,
            conversation_persona_id=conversation_persona_id,
            provider_settings=getattr(config, "provider_settings", {}) or {},
        )
        return resolution.persona_id, resolution.persona

    @staticmethod
    def _request_persona_id(provider_request: object | None) -> str | None:
        conversation = getattr(provider_request, "conversation", None)
        persona_id = getattr(conversation, "persona_id", None)
        return persona_id if isinstance(persona_id, str) else None

    @staticmethod
    def _exclusion_reason(
        event,
        tool: FunctionTool,
        target: str,
        excluded_tool_names: frozenset[str],
        exclude_handoff_tools: bool,
    ) -> str | None:
        if exclude_handoff_tools and isinstance(tool, HandoffTool):
            return CAPABILITY_REASON_EXECUTION_POLICY
        if target == TOOL_TARGET_PERSONAL_EXPRESSION and isinstance(tool, HandoffTool):
            return CAPABILITY_REASON_SUBAGENT_CORE_ONLY
        if tool.name in excluded_tool_names:
            return CAPABILITY_REASON_SUBAGENT_OWNED
        if not bool(getattr(tool, "active", True)):
            return CAPABILITY_REASON_INACTIVE
        if not tool_supports_runtime_target(event, tool, target):
            return CAPABILITY_REASON_TARGET_MISMATCH
        if not tool_plugin_is_selected(event, tool):
            return CAPABILITY_REASON_PLUGIN_NOT_SELECTED
        return None


def _serialize_tool(tool: FunctionTool) -> dict[str, Any]:
    schema = ToolSet([tool]).openai_schema()
    return {
        "name": tool.name,
        "description": tool_description_for_model(tool),
        "parameters": deepcopy(tool.parameters),
        "active": bool(getattr(tool, "active", True)),
        "handler_module_path": getattr(tool, "handler_module_path", None),
        "execution_targets": sorted(
            normalize_tool_targets(getattr(tool, "execution_targets", None))
        ),
        "semantic_capabilities": sorted(
            normalize_semantic_capabilities(
                getattr(tool, "semantic_capabilities", None)
            )
        ),
        "action_semantic_capabilities": {
            str(action): sorted(capabilities)
            for action, capabilities in normalize_action_semantic_capabilities(
                getattr(tool, "action_semantic_capabilities", None)
            ).items()
        },
        "schema": deepcopy(schema[0]) if schema else None,
    }


__all__ = [
    "CAPABILITY_REASON_INACTIVE",
    "CAPABILITY_REASON_EXECUTION_POLICY",
    "CAPABILITY_REASON_INCLUDED",
    "CAPABILITY_REASON_PERSONA_NOT_SELECTED",
    "CAPABILITY_REASON_PLUGIN_NOT_SELECTED",
    "CAPABILITY_REASON_SUBAGENT_CORE_ONLY",
    "CAPABILITY_REASON_SUBAGENT_OWNED",
    "CAPABILITY_REASON_TARGET_MISMATCH",
    "CAPABILITY_REASON_UNKNOWN_TOOL",
    "CapabilityDecision",
    "CapabilityResolver",
    "CapabilitySnapshot",
]
