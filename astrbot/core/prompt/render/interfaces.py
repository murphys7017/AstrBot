"""Prompt render-layer interfaces."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context

from ..context_types import ContextPack, ContextSlot

if TYPE_CHECKING:
    from astrbot.core.astr_main_agent import MainAgentBuildConfig

    from .prompt_tree import PromptBuilder


@dataclass
class RenderResult:
    """Unified render output for the prompt pipeline."""

    prompt_tree: PromptBuilder | None = None
    system_prompt: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_schema: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SerializedRenderValue:
    """Structured intermediate value produced by a renderer serializer."""

    slot_name: str
    group: str
    tag: str
    kind: str
    value: Any
    meta: dict[str, Any] = field(default_factory=dict)


class PromptSelectorInterface(ABC):
    """Abstract selector interface for prompt context packs."""

    @abstractmethod
    def select(
        self,
        pack: ContextPack,
        *,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> ContextPack:
        """Select the context pack to pass into the render layer."""
        raise NotImplementedError


class BasePromptRenderer:
    """Base rule provider for prompt rendering."""

    ALL_SLOT_GROUPS: tuple[str, ...] = (
        "system",
        "persona",
        "policy",
        "input",
        "session",
        "conversation",
        "knowledge",
        "capability",
        "memory",
    )

    def get_name(self) -> str:
        """Return the stable renderer name."""
        return "base"

    def get_root_tag(self) -> str:
        """Return the prompt-tree root tag."""
        return "prompt"

    def get_enabled_slot_groups(self) -> tuple[str, ...]:
        """Return enabled logical data groups for this renderer."""
        return self.ALL_SLOT_GROUPS

    def get_node_structure(self) -> dict[str, str]:
        """Return the top-level node structure for logical groups."""
        return {
            "system": "system",
            "persona": "persona",
            "policy": "policy",
            "input": "input",
            "session": "session",
            "conversation": "conversation",
            "knowledge": "knowledge",
            "capability": "capability",
            "memory": "memory",
        }

    def render_prompt_tree(
        self,
        prompt_tree: PromptBuilder,
        *,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> RenderResult:
        """Render the built prompt tree into the final context payload."""
        rendered_groups = prompt_tree._root_node.meta.get("rendered_groups", [])
        rendered_slots = prompt_tree._root_node.meta.get("rendered_slots", [])
        return RenderResult(
            prompt_tree=prompt_tree,
            system_prompt=prompt_tree.build(),
            metadata=self._build_render_metadata(
                prompt_tree=prompt_tree,
                rendered_groups=rendered_groups,
                rendered_slots=rendered_slots,
            ),
        )

    def render_system_context(
        self,
        target,
        slots: list[ContextSlot],
        *,
        pack: ContextPack,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> list[str]:
        return self._render_slots_as_children("system", target, slots)

    def render_persona_context(
        self,
        target,
        slots: list[ContextSlot],
        *,
        pack: ContextPack,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> list[str]:
        return self._render_slots_as_children("persona", target, slots)

    def render_policy_context(
        self,
        target,
        slots: list[ContextSlot],
        *,
        pack: ContextPack,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> list[str]:
        return self._render_slots_as_children("policy", target, slots)

    def render_input_context(
        self,
        target,
        slots: list[ContextSlot],
        *,
        pack: ContextPack,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> list[str]:
        return self._render_slots_as_children("input", target, slots)

    def render_session_context(
        self,
        target,
        slots: list[ContextSlot],
        *,
        pack: ContextPack,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> list[str]:
        return self._render_slots_as_children("session", target, slots)

    def render_conversation_context(
        self,
        target,
        slots: list[ContextSlot],
        *,
        pack: ContextPack,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> list[str]:
        return self._render_slots_as_children("conversation", target, slots)

    def render_knowledge_context(
        self,
        target,
        slots: list[ContextSlot],
        *,
        pack: ContextPack,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> list[str]:
        return self._render_slots_as_children("knowledge", target, slots)

    def render_capability_context(
        self,
        target,
        slots: list[ContextSlot],
        *,
        pack: ContextPack,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> list[str]:
        return self._render_slots_as_children("capability", target, slots)

    def render_memory_context(
        self,
        target,
        slots: list[ContextSlot],
        *,
        pack: ContextPack,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config: MainAgentBuildConfig | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> list[str]:
        return self._render_slots_as_children("memory", target, slots)

    def _render_slots_as_children(
        self,
        group: str,
        target,
        slots: list[ContextSlot],
    ) -> list[str]:
        """Render a logical group into child tags under the target node."""
        rendered_slot_names: list[str] = []
        for serialized in self.serialize_group_slots(group, slots):
            content = self.render_serialized_value(serialized)
            if content is None:
                continue

            target.tag(
                serialized.tag,
                meta={
                    "slot_name": serialized.slot_name,
                    "group": serialized.group,
                    "value_kind": serialized.kind,
                    **serialized.meta,
                },
            ).add(content)
            rendered_slot_names.append(serialized.slot_name)
        return rendered_slot_names

    def serialize_group_slots(
        self,
        group: str,
        slots: list[ContextSlot],
    ) -> list[SerializedRenderValue]:
        """Serialize all slots in a logical group into structured values."""
        serialized_values: list[SerializedRenderValue] = []
        for slot in sorted(slots, key=lambda item: item.name):
            serialized = self.serialize_slot_value(slot, group=group)
            if serialized is not None:
                serialized_values.append(serialized)
        return serialized_values

    def serialize_slot_value(
        self,
        slot: ContextSlot,
        *,
        group: str,
    ) -> SerializedRenderValue | None:
        """Serialize a single slot into a structured intermediate value."""
        tag = self._slot_to_child_tag(slot.name, group)
        value = slot.value

        if group == "knowledge" and isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str):
                resolved = text.strip()
                if resolved:
                    return SerializedRenderValue(
                        slot_name=slot.name,
                        group=group,
                        tag=tag,
                        kind="text",
                        value=resolved,
                    )

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            return SerializedRenderValue(
                slot_name=slot.name,
                group=group,
                tag=tag,
                kind="text",
                value=text,
            )

        if value is None:
            return None

        if isinstance(value, dict):
            return SerializedRenderValue(
                slot_name=slot.name,
                group=group,
                tag=tag,
                kind="mapping",
                value=value,
            )

        if isinstance(value, list):
            return SerializedRenderValue(
                slot_name=slot.name,
                group=group,
                tag=tag,
                kind="sequence",
                value=value,
            )

        if isinstance(value, (bool, int, float)):
            return SerializedRenderValue(
                slot_name=slot.name,
                group=group,
                tag=tag,
                kind="scalar",
                value=value,
            )

        return SerializedRenderValue(
            slot_name=slot.name,
            group=group,
            tag=tag,
            kind="scalar",
            value=str(value),
        )

    def render_serialized_value(self, serialized: SerializedRenderValue) -> str | None:
        """Render a structured intermediate value into node text."""
        if serialized.kind == "text":
            value = serialized.value
            if not isinstance(value, str):
                return None
            return value

        return json.dumps(
            serialized.value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    @staticmethod
    def _slot_to_child_tag(slot_name: str, group: str) -> str:
        """Convert a slot name into a child tag name for a logical group."""
        child_tag = (
            slot_name[len(group) + 1 :]
            if slot_name.startswith(f"{group}.")
            else slot_name
        )
        return child_tag.replace(".", "_") or group

    @staticmethod
    def _stringify_slot_value(slot: ContextSlot) -> str | None:
        """Convert a slot value into a minimal text form."""
        value = slot.value
        if isinstance(value, str):
            text = value.strip()
            return text or None
        if value is None:
            return None
        return str(value)

    def _build_render_metadata(
        self,
        *,
        prompt_tree: PromptBuilder,
        rendered_groups: list[str],
        rendered_slots: list[str],
    ) -> dict[str, Any]:
        """Build shared renderer metadata for render results."""
        return {
            "renderer": self.get_name(),
            "rendered_groups": list(rendered_groups),
            "rendered_slots": list(rendered_slots),
            "tree_root": prompt_tree._root_node.meta.get("tag", self.get_root_tag()),
        }
