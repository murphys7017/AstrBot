"""Prompt render engine."""

from __future__ import annotations

from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context

from ..context_types import ContextPack, ContextSlot
from .base_renderer import BasePromptRenderer
from .interfaces import RenderResult
from .prompt_tree import NodeRef, PromptBuilder
from .selector import PassthroughPromptSelector, select_context_pack


class PromptRenderEngine:
    """Drive prompt rendering from selector through tree output."""

    def __init__(
        self,
        *,
        selector=None,
        default_renderer: BasePromptRenderer | None = None,
    ) -> None:
        self.selector = selector or PassthroughPromptSelector()
        self.default_renderer = default_renderer or BasePromptRenderer()

    def render(
        self,
        pack: ContextPack,
        *,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config=None,
        provider_request: ProviderRequest | None = None,
    ) -> RenderResult:
        selected_pack = self._select_context_pack(
            pack,
            event=event,
            plugin_context=plugin_context,
            config=config,
            provider_request=provider_request,
        )
        renderer = self._resolve_renderer(
            selected_pack,
            event=event,
            plugin_context=plugin_context,
            config=config,
            provider_request=provider_request,
        )
        prompt_tree = self._build_prompt_tree(
            selected_pack,
            renderer=renderer,
            event=event,
            plugin_context=plugin_context,
            config=config,
            provider_request=provider_request,
        )
        result = renderer.render_prompt_tree(
            prompt_tree,
            event=event,
            plugin_context=plugin_context,
            config=config,
            provider_request=provider_request,
        )
        return self._attach_engine_metadata(
            result,
            selected_pack=selected_pack,
            renderer=renderer,
        )

    def _select_context_pack(
        self,
        pack: ContextPack,
        *,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config=None,
        provider_request: ProviderRequest | None = None,
    ) -> ContextPack:
        return select_context_pack(
            pack,
            selector=self.selector,
            event=event,
            plugin_context=plugin_context,
            config=config,
            provider_request=provider_request,
        )

    def _resolve_renderer(
        self,
        pack: ContextPack,
        *,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config=None,
        provider_request: ProviderRequest | None = None,
    ) -> BasePromptRenderer:
        return self.default_renderer

    def _build_prompt_tree(
        self,
        pack: ContextPack,
        *,
        renderer: BasePromptRenderer,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config=None,
        provider_request: ProviderRequest | None = None,
    ) -> PromptBuilder:
        root_tag = renderer.get_root_tag()
        prompt_tree = PromptBuilder(root_tag)
        path_refs: dict[str, NodeRef] = {root_tag: prompt_tree.ref()}
        grouped_slots = self._group_slots(pack)
        enabled_groups = [
            group
            for group in renderer.get_enabled_slot_groups()
            if group in grouped_slots
        ]
        node_structure = renderer.get_node_structure()
        rendered_slots: list[str] = []
        rendered_groups: list[str] = []

        for group in enabled_groups:
            node_path = node_structure.get(group)
            if not node_path:
                continue

            target_ref = self._ensure_node_path(
                prompt_tree,
                path_refs=path_refs,
                root_tag=root_tag,
                node_path=node_path,
            )
            slots = grouped_slots[group]
            rendered = self._render_group_context(
                renderer,
                group=group,
                target=target_ref,
                resolve_node=lambda path: self._ensure_node_path(
                    prompt_tree,
                    path_refs=path_refs,
                    root_tag=root_tag,
                    node_path=path,
                ),
                slots=slots,
                pack=pack,
                event=event,
                plugin_context=plugin_context,
                config=config,
                provider_request=provider_request,
            )
            if rendered:
                rendered_groups.append(group)
                rendered_slots.extend(rendered)

        prompt_tree._root_node.meta["rendered_slots"] = rendered_slots
        prompt_tree._root_node.meta["rendered_groups"] = rendered_groups
        prompt_tree._root_node.meta["renderer"] = renderer.get_name()
        prompt_tree._root_node.meta["enabled_slot_groups"] = list(enabled_groups)
        return prompt_tree

    def _render_group_context(
        self,
        renderer: BasePromptRenderer,
        *,
        group: str,
        target: NodeRef,
        resolve_node,
        slots: list[ContextSlot],
        pack: ContextPack,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config=None,
        provider_request: ProviderRequest | None = None,
    ) -> list[str]:
        render_method = getattr(renderer, f"render_{group}_context")
        return render_method(
            target,
            slots,
            pack=pack,
            resolve_node=resolve_node,
            event=event,
            plugin_context=plugin_context,
            config=config,
            provider_request=provider_request,
        )

    def _ensure_node_path(
        self,
        prompt_tree: PromptBuilder,
        *,
        path_refs: dict[str, NodeRef],
        root_tag: str,
        node_path: str,
    ) -> NodeRef:
        normalized_path = node_path.strip("/")
        if not normalized_path:
            return prompt_tree.ref()

        parts = normalized_path.split("/")
        if parts[0] == root_tag:
            parts = parts[1:]

        current_path = root_tag
        current_ref = path_refs[root_tag]
        for part in parts:
            current_path = f"{current_path}/{part}"
            if current_path not in path_refs:
                path_refs[current_path] = current_ref.tag(
                    part,
                    meta={"node_path": current_path},
                )
            current_ref = path_refs[current_path]
        return current_ref

    @staticmethod
    def _group_slots(pack: ContextPack) -> dict[str, list[ContextSlot]]:
        grouped_slots: dict[str, list[ContextSlot]] = {}
        for slot in pack.slots.values():
            group = slot.name.split(".", 1)[0]
            grouped_slots.setdefault(group, []).append(slot)
        return grouped_slots

    def _attach_engine_metadata(
        self,
        result: RenderResult,
        *,
        selected_pack: ContextPack,
        renderer: BasePromptRenderer,
    ) -> RenderResult:
        result.metadata.update(
            {
                "engine": "PromptRenderEngine",
                "selector": self.selector.__class__.__name__,
                "renderer_name": renderer.get_name(),
                "slot_count": len(selected_pack.slots),
                "selected_slot_names": sorted(selected_pack.slots),
                "enabled_slot_groups": list(renderer.get_enabled_slot_groups()),
            }
        )
        return result
