"""Prompt render engine."""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from html import escape
from time import perf_counter

from astrbot import logger
from astrbot.core.agent.message import Message, TextPart
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.plugin_runtime import resolve_plugin_prompt_extension_target
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.provider.register import provider_cls_map
from astrbot.core.runtime_config_projection import resolve_event_runtime_configuration
from astrbot.core.star.context import Context
from astrbot.core.utils.trace import prompt_trace_enabled, record_prompt_trace

from ..context_types import ContextPack, ContextSlot
from ..context_views import (
    PromptContextView,
    project_prompt_context_view,
    resolve_prompt_context_view,
)
from ..diagnostics import measure_prompt_stage, record_prompt_timings
from ..targets import (
    PromptTarget,
    project_context_pack,
)
from .anthropic_renderer import AnthropicPromptRenderer
from .base_renderer import BasePromptRenderer
from .deepseek_renderer import DeepSeekPromptRenderer
from .interfaces import PromptRenderProfile, RenderResult
from .layout import DefaultPromptLayout, PromptLayoutInterface
from .minimax_renderer import MiniMaxPromptRenderer
from .openai_renderer import OpenAIPromptRenderer
from .request_adapter import (
    PROMPT_TRANSIENT_MESSAGE_INDICES_KEY,
    PROMPT_TRANSIENT_SYSTEM_PROMPT_BASE_KEY,
    PROMPT_TRANSIENT_SYSTEM_PROMPT_DROPPED_KEY,
    PROMPT_TRANSIENT_SYSTEM_PROMPT_EXTENSION_KEY,
)
from .tree_builder import PromptTreeBuilder

_PROMPT_RENDERER_FAMILIES = {
    "base",
    "openai",
    "anthropic",
    "minimax",
    "deepseek",
}
_PLUGIN_TRANSIENT_PROMPT_TARGETS = frozenset({"persona", "core"})
_TRANSIENT_PROMPT_MESSAGE_WARN_SECONDS = 0.05


class PromptRenderEngine:
    """Project a context target, build its semantic tree, and serialize it."""

    def __init__(
        self,
        *,
        default_renderer: BasePromptRenderer | None = None,
        default_layout: PromptLayoutInterface | None = None,
        tree_builder: PromptTreeBuilder | None = None,
    ) -> None:
        self.default_renderer = default_renderer or BasePromptRenderer()
        self.default_layout = default_layout or DefaultPromptLayout()
        self.tree_builder = tree_builder or PromptTreeBuilder()

    def render(
        self,
        pack: ContextPack,
        *,
        target: PromptTarget | str | None = None,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config=None,
        provider_request: ProviderRequest | None = None,
        profile: PromptRenderProfile | None = None,
        context_view: PromptContextView | str | None = None,
    ) -> RenderResult:
        resolved_target = (
            PromptTarget(target) if target is not None else PromptTarget.CORE
        )
        view_spec = resolve_prompt_context_view(context_view)
        if view_spec is not None and view_spec.target is not resolved_target:
            raise ValueError(
                f"context view {view_spec.name.value} requires target "
                f"{view_spec.target.value}, got {resolved_target.value}"
            )
        timings = []
        with measure_prompt_stage(timings, "context_view"):
            view_pack = project_prompt_context_view(pack, context_view)
        history_turns = profile.history_turns if profile is not None else None
        history_limit_reason = None
        history_max_estimated_tokens = None
        if view_spec is not None and view_spec.history_turns is not None:
            history_turns = view_spec.history_turns
        if view_spec is not None:
            history_limit_reason = view_spec.history_limit_reason
            history_max_estimated_tokens = view_spec.history_max_estimated_tokens
        with measure_prompt_stage(timings, "target_projection"):
            target_pack = project_context_pack(
                view_pack, resolved_target, history_turns=history_turns,
                history_limit_reason=history_limit_reason,
                history_max_estimated_tokens=history_max_estimated_tokens, config=config,
            )
        with measure_prompt_stage(timings, "render_profile"):
            selected_pack = self._apply_render_profile(target_pack, profile)
        renderer = self._resolve_renderer(
            event=event,
            plugin_context=plugin_context,
            config=config,
            provider_request=provider_request,
        )
        with measure_prompt_stage(timings, "tree_build"):
            prompt_tree = self.tree_builder.build(
                selected_pack, layout=self.default_layout, event=event,
                plugin_context=plugin_context, config=config,
                provider_request=provider_request,
            )
        with measure_prompt_stage(timings, "provider_render"):
            result = renderer.render_prompt_tree(
                prompt_tree, event=event, plugin_context=plugin_context,
                config=config, provider_request=provider_request,
            )
        if profile is not None:
            result.request_prompt = profile.request_prompt
        result = self._attach_engine_metadata(
            result,
            selected_pack=selected_pack,
            renderer=renderer,
            layout=self.default_layout,
        )
        result.metadata["prompt_target"] = resolved_target.value
        result.metadata["render_timings"] = timings
        self._inject_transient_prompt_messages(
            result,
            event=event,
            plugin_context=plugin_context,
            target=resolved_target.value,
            context_view=view_spec.name.value if view_spec is not None else None,
            provider_request=provider_request,
        )
        record_prompt_timings(event, f"render:{resolved_target.value}", timings)
        self._log_render_result(
            result,
            selected_pack=selected_pack,
            renderer=renderer,
            event=event,
            provider_request=provider_request,
        )
        return result

    def recompile_for_provider(
        self,
        source: RenderResult,
        *,
        provider_request: ProviderRequest,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
    ) -> RenderResult:
        """Serialize an already-projected prompt tree for another provider."""
        if source.prompt_tree is None:
            raise ValueError("Cannot recompile a render result without a prompt tree")
        renderer = self._resolve_renderer(provider_request=provider_request)
        timings = []
        with measure_prompt_stage(timings, "provider_recompile"):
            result = renderer.render_prompt_tree(
                deepcopy(source.prompt_tree), provider_request=provider_request,
            )
        result.request_prompt = source.request_prompt
        result.metadata = {
            **source.metadata,
            **result.metadata,
            "renderer_name": renderer.get_name(),
            "render_timings": timings,
        }
        if plugin_context is not None:
            self._inject_transient_prompt_messages(
                result,
                event=event,
                plugin_context=plugin_context,
                target=str(source.metadata.get("prompt_target", "core")),
                context_view=(
                    str(source.metadata["context_view"])
                    if source.metadata.get("context_view")
                    else None
                ),
                provider_request=provider_request,
            )
        record_prompt_timings(None, "provider_recompile", timings)
        return result

    def _inject_transient_prompt_messages(
        self,
        result: RenderResult,
        *,
        event: AstrMessageEvent | None,
        plugin_context: Context | None,
        target: str,
        context_view: str | None,
        provider_request: ProviderRequest | None,
        legacy_prompt_mutations: Sequence[object] = (),
    ) -> None:
        """Add request-local messages after ContextPack projection.

        These messages intentionally live in the rendered request rather than
        the canonical ContextPack. A plugin can therefore expose fast-changing
        state without poisoning the per-turn context-pack cache.
        """
        collector_iter = ()
        list_collectors = (
            getattr(plugin_context, "list_prompt_extension_collectors", None)
            if plugin_context is not None
            else None
        )
        if callable(list_collectors):
            try:
                try:
                    collectors = list_collectors(event=event)
                except TypeError:
                    collectors = list_collectors()
            except Exception:
                logger.exception("Failed to list transient prompt message providers")
            else:
                try:
                    collector_iter = iter(collectors or ())
                except TypeError:
                    logger.warning(
                        "Transient prompt message provider registry returned "
                        "invalid value: type=%s",
                        type(collectors).__name__,
                    )

        transient_messages: list[dict[str, object]] = []
        transient_timings: list[dict[str, object]] = []
        transient_sources: set[str] = set()
        runtime_config = (
            resolve_event_runtime_configuration(event)[0] if event is not None else None
        )
        get_owner_name = getattr(
            plugin_context, "get_prompt_extension_collector_owner_name", None
        )
        for collector in collector_iter:
            collect_messages = getattr(collector, "collect_prompt_messages", None)
            if not callable(collect_messages):
                continue
            plugin_id = str(getattr(collector, "plugin_id", "") or "").strip()
            if not plugin_id:
                continue
            raw_targets = getattr(collector, "prompt_message_targets", frozenset())
            if not isinstance(raw_targets, (list, tuple, set, frozenset)):
                continue
            declared_targets = {
                str(value).strip() for value in raw_targets if str(value).strip()
            }
            allowed_targets = declared_targets & _PLUGIN_TRANSIENT_PROMPT_TARGETS
            owner_name = get_owner_name(collector) if callable(get_owner_name) else None
            target_override = resolve_plugin_prompt_extension_target(
                runtime_config, owner_name
            )
            if target_override is not None:
                allowed_targets.intersection_update({target_override})
            if target not in allowed_targets:
                continue
            started_at = perf_counter()
            try:
                messages = collect_messages(
                    event,
                    plugin_context,
                    target=target,
                    context_view=context_view,
                    provider_request=provider_request,
                )
            except Exception:
                elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
                transient_timings.append(
                    {
                        "plugin_id": plugin_id,
                        "duration_ms": elapsed_ms,
                        "status": "failed",
                    }
                )
                logger.exception(
                    "Transient prompt message provider failed: plugin_id=%s",
                    plugin_id,
                )
                continue
            elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
            transient_timings.append(
                {
                    "plugin_id": plugin_id,
                    "duration_ms": elapsed_ms,
                    "status": "completed",
                }
            )
            if elapsed_ms >= _TRANSIENT_PROMPT_MESSAGE_WARN_SECONDS * 1000:
                logger.warning(
                    "Transient prompt message provider is slow: plugin_id=%s "
                    "target=%s duration_ms=%.3f",
                    plugin_id,
                    target,
                    elapsed_ms,
                )
            if not isinstance(messages, list):
                logger.warning(
                    "Transient prompt message provider returned invalid value: "
                    "plugin_id=%s type=%s",
                    plugin_id,
                    type(messages).__name__,
                )
                continue
            for message in messages:
                normalized = self._normalize_transient_prompt_message(message)
                if normalized is not None:
                    transient_messages.append(normalized)
                    transient_sources.add(plugin_id)

        for mutation in legacy_prompt_mutations:
            source = str(getattr(mutation, "source", "plugin") or "plugin")
            for message in getattr(mutation, "context_messages", ()) or ():
                normalized = self._normalize_transient_prompt_message(message)
                if normalized is not None:
                    transient_messages.append(normalized)
                    transient_sources.add(source)

        if transient_timings:
            result.metadata["transient_prompt_message_timings"] = transient_timings
        if not transient_messages:
            return

        existing_messages = list(result.messages)
        insertion_index = len(existing_messages)
        if existing_messages and existing_messages[-1].get("role") == "user":
            insertion_index -= 1
        result.messages = (
            existing_messages[:insertion_index]
            + transient_messages
            + existing_messages[insertion_index:]
        )
        result.metadata["transient_prompt_message_count"] = len(transient_messages)
        result.metadata["transient_prompt_message_providers"] = sorted(
            transient_sources
        )

    def refresh_transient_prompt_messages(
        self,
        *,
        provider_request: ProviderRequest,
        run_context_messages: list[Message],
        event: AstrMessageEvent | None,
        plugin_context: Context | None,
        target: str,
        context_view: str | None = None,
        legacy_prompt_mutations: Sequence[object] = (),
        base_system_prompt: str | None = None,
    ) -> None:
        """Refresh request-local messages immediately before a provider call."""
        scratch = RenderResult()
        self._inject_transient_prompt_messages(
            scratch,
            event=event,
            plugin_context=plugin_context,
            target=target,
            context_view=context_view,
            provider_request=provider_request,
            legacy_prompt_mutations=legacy_prompt_mutations,
        )
        system_prompt_updated = self._refresh_legacy_system_prompt(
            provider_request,
            base_system_prompt=base_system_prompt,
            legacy_prompt_mutations=legacy_prompt_mutations,
        )
        if system_prompt_updated:
            system_message = next(
                (
                    message
                    for message in run_context_messages
                    if message.role == "system"
                ),
                None,
            )
            if system_message is None:
                run_context_messages.insert(
                    0,
                    Message(role="system", content=provider_request.system_prompt),
                )
            else:
                system_message.content = provider_request.system_prompt

        retained_messages = [
            message
            for message in run_context_messages
            if not getattr(message, "_prompt_transient", False)
        ]
        for message in retained_messages:
            if not isinstance(message.content, list):
                continue
            message.content = [
                part
                for part in message.content
                if not getattr(part, "_prompt_transient", False)
            ]

        fresh_messages: list[dict[str, object]] = []
        fresh_models: list[Message] = []
        for message in scratch.messages:
            normalized = self._normalize_transient_prompt_message(message)
            if normalized is None:
                continue
            normalized.pop("_prompt_transient", None)
            model = Message.model_validate(normalized)
            model._no_save = True
            model._prompt_transient = True
            fresh_messages.append(normalized)
            fresh_models.append(model)

        legacy_extra_parts = [
            deepcopy(part)
            for mutation in legacy_prompt_mutations
            for part in getattr(mutation, "extra_user_content_parts", ()) or ()
            if isinstance(part, dict)
        ]
        self._refresh_legacy_extra_user_content_parts(
            retained_messages,
            legacy_extra_parts,
        )
        prompt_prefix = ""
        prompt_suffix = ""
        for mutation in legacy_prompt_mutations:
            for placement, text in getattr(
                mutation, "prompt_text_operations", ()
            ) or ():
                if placement == "prefix":
                    prompt_prefix = text + prompt_prefix
                elif placement == "suffix":
                    prompt_suffix += text
        self._refresh_legacy_prompt_text_parts(
            retained_messages,
            base_prompt=provider_request.prompt,
            prefix=prompt_prefix,
            suffix=prompt_suffix,
        )

        request_metadata = dict(provider_request.metadata or {})
        old_indices = {
            int(index)
            for index in request_metadata.get(
                PROMPT_TRANSIENT_MESSAGE_INDICES_KEY,
                [],
            )
            if isinstance(index, int) and index >= 0
        }
        existing_contexts = list(provider_request.contexts or [])
        insertion_index = min(old_indices) if old_indices else len(existing_contexts)
        retained_contexts = [
            message
            for index, message in enumerate(existing_contexts)
            if index not in old_indices
        ]
        insertion_index = min(insertion_index, len(retained_contexts))
        provider_request.contexts = (
            retained_contexts[:insertion_index]
            + fresh_messages
            + retained_contexts[insertion_index:]
        )
        if fresh_messages:
            request_metadata[PROMPT_TRANSIENT_MESSAGE_INDICES_KEY] = list(
                range(insertion_index, insertion_index + len(fresh_messages))
            )
        else:
            request_metadata.pop(PROMPT_TRANSIENT_MESSAGE_INDICES_KEY, None)
        provider_request.metadata = request_metadata

        last_user_index = next(
            (
                index
                for index in range(len(retained_messages) - 1, -1, -1)
                if retained_messages[index].role == "user"
            ),
            None,
        )
        has_follow_up = last_user_index is not None and any(
            message.role in {"assistant", "tool"}
            for message in retained_messages[last_user_index + 1 :]
        )
        if last_user_index is not None and not has_follow_up:
            retained_messages[last_user_index:last_user_index] = fresh_models
        else:
            retained_messages.extend(fresh_models)
        run_context_messages[:] = retained_messages

    @staticmethod
    def _refresh_legacy_extra_user_content_parts(
        run_context_messages: list[Message],
        serialized_parts: list[dict[str, object]],
    ) -> None:
        if not serialized_parts:
            return
        last_user = next(
            (
                message
                for message in reversed(run_context_messages)
                if message.role == "user"
            ),
            None,
        )
        if last_user is None:
            return
        try:
            parsed = Message.model_validate(
                {"role": "user", "content": serialized_parts}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Legacy plugin extra user content rejected (%s): %s",
                type(exc).__name__,
                exc,
            )
            return
        if not isinstance(parsed.content, list):
            return
        for part in parsed.content:
            part._no_save = True
            part._prompt_transient = True

        if isinstance(last_user.content, str):
            existing_content = (
                [TextPart(text=last_user.content)] if last_user.content else []
            )
            last_user.content = [*existing_content, *parsed.content]
        elif isinstance(last_user.content, list):
            last_user.content.extend(parsed.content)
        else:
            last_user.content = list(parsed.content)

    @staticmethod
    def _refresh_legacy_prompt_text_parts(
        run_context_messages: list[Message],
        *,
        base_prompt: str | None,
        prefix: str,
        suffix: str,
    ) -> None:
        if not prefix and not suffix:
            return
        last_user = next(
            (
                message
                for message in reversed(run_context_messages)
                if message.role == "user"
            ),
            None,
        )
        if last_user is None:
            return

        prefix_part = TextPart(text=prefix) if prefix else None
        suffix_part = TextPart(text=suffix) if suffix else None
        for part in (prefix_part, suffix_part):
            if part is not None:
                part._no_save = True
                part._prompt_transient = True

        if isinstance(last_user.content, str):
            content = [TextPart(text=last_user.content)] if last_user.content else []
            last_user.content = [
                *([prefix_part] if prefix_part is not None else []),
                *content,
                *([suffix_part] if suffix_part is not None else []),
            ]
            return

        if not isinstance(last_user.content, list):
            last_user.content = []
        prompt_part_index = next(
            (
                index
                for index, part in enumerate(last_user.content)
                if getattr(part, "type", None) == "text"
            ),
            None,
        )
        if prompt_part_index is None or not base_prompt:
            last_user.content[0:0] = [
                part
                for part in (prefix_part, suffix_part)
                if part is not None
            ]
            return
        if prefix_part is not None:
            last_user.content.insert(prompt_part_index, prefix_part)
            prompt_part_index += 1
        if suffix_part is not None:
            last_user.content.insert(prompt_part_index + 1, suffix_part)

    @staticmethod
    def _refresh_legacy_system_prompt(
        provider_request: ProviderRequest,
        *,
        base_system_prompt: str | None,
        legacy_prompt_mutations: Sequence[object],
    ) -> bool:
        request_metadata = dict(provider_request.metadata or {})
        stored_base = request_metadata.get(PROMPT_TRANSIENT_SYSTEM_PROMPT_BASE_KEY)
        if isinstance(base_system_prompt, str):
            base = base_system_prompt
        elif isinstance(stored_base, str):
            base = stored_base
        else:
            base = str(provider_request.system_prompt or "")
        if request_metadata.get(PROMPT_TRANSIENT_SYSTEM_PROMPT_DROPPED_KEY) is True:
            provider_request.system_prompt = base
            return True

        extensions = []
        for mutation in legacy_prompt_mutations:
            content = str(getattr(mutation, "system_prompt_text", "") or "")
            if not content.strip():
                continue
            source = escape(str(getattr(mutation, "source", "plugin") or "plugin"))
            extensions.append(
                f'<extension source="{source}">{escape(content, quote=False)}</extension>'
            )
        if not extensions:
            return False

        extension_block = (
            "<legacy_plugin_system_extensions>\n"
            + "\n".join(extensions)
            + "\n</legacy_plugin_system_extensions>"
        )
        if not base or base.endswith("\n\n"):
            separator = ""
        elif base.endswith("\n"):
            separator = "\n"
        else:
            separator = "\n\n"
        request_metadata[PROMPT_TRANSIENT_SYSTEM_PROMPT_BASE_KEY] = base
        request_metadata[PROMPT_TRANSIENT_SYSTEM_PROMPT_EXTENSION_KEY] = extension_block
        provider_request.metadata = request_metadata
        provider_request.system_prompt = base + separator + extension_block
        return True

    @staticmethod
    def _normalize_transient_prompt_message(
        message: object,
    ) -> dict[str, object] | None:
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        content = message.get("content")
        if (
            not isinstance(role, str)
            or role.strip().lower() != "user"
            or not isinstance(content, (str, list))
        ):
            return None
        normalized = {
            "role": "user",
            "content": deepcopy(content),
            "_no_save": True,
            "_prompt_transient": True,
        }
        try:
            Message.model_validate(normalized)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Transient prompt message rejected: invalid message payload (%s): %s",
                type(exc).__name__,
                exc,
            )
            return None
        return normalized

    @staticmethod
    def _apply_render_profile(
        pack: ContextPack,
        profile: PromptRenderProfile | None,
    ) -> ContextPack:
        if profile is None:
            return pack

        selected = ContextPack(
            slots=deepcopy(pack.slots),
            provider_request_ref=pack.provider_request_ref,
            meta=deepcopy(pack.meta),
        )
        for slot_name in profile.hidden_slot_names:
            selected.slots.pop(slot_name, None)

        if profile.system_prompt is not None:
            selected.add_slot(
                ContextSlot(
                    name="system.base",
                    value=profile.system_prompt,
                    category="system",
                    source=f"prompt_render_profile:{profile.name}",
                    render_mode="text",
                    meta={
                        "scope": "render_profile",
                        "node_type": f"{profile.name}_system_prompt",
                    },
                )
            )

        suffix = profile.input_text_suffix
        if suffix:
            input_slot = selected.get_slot("input.text")
            if input_slot is not None and isinstance(input_slot.value, str):
                input_slot.value = f"{input_slot.value.rstrip()}{suffix}"

        if profile.output_contract is not None:
            selected.meta["output_contract"] = profile.output_contract.to_dict()
        if profile.output_contract_strategy is not None:
            selected.meta["output_contract_strategy"] = profile.output_contract_strategy
        selected.meta["render_profile"] = profile.name
        selected.meta["slot_count"] = len(selected.slots)
        return selected

    def _resolve_renderer(
        self,
        *,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config=None,
        provider_request: ProviderRequest | None = None,
    ) -> BasePromptRenderer:
        provider = self._resolve_provider_from_request(provider_request)
        if provider is None:
            provider = self._resolve_provider_from_event(event)
        if provider is None:
            provider = self._resolve_request_provider(plugin_context, config)
        renderer_family = self._resolve_prompt_renderer_family(provider)
        if renderer_family == "anthropic":
            return AnthropicPromptRenderer()
        if renderer_family == "openai":
            return OpenAIPromptRenderer()
        if renderer_family == "deepseek":
            return DeepSeekPromptRenderer()
        if renderer_family == "minimax":
            return MiniMaxPromptRenderer(
                enable_tool_call=self._resolve_minimax_tool_call_enabled(provider)
            )
        return self.default_renderer

    @staticmethod
    def _resolve_prompt_renderer_family(provider) -> str:
        provider_config = getattr(provider, "provider_config", None)
        if not isinstance(provider_config, dict):
            return "base"
        configured_family = str(
            provider_config.get("prompt_renderer_family", "") or ""
        ).strip()
        if configured_family:
            return (
                configured_family
                if configured_family in _PROMPT_RENDERER_FAMILIES
                else "base"
            )
        provider_type = str(provider_config.get("type", "") or "").strip()
        if not provider_type:
            return "base"
        metadata = provider_cls_map.get(provider_type)
        if metadata is None:
            return "base"
        metadata_family = str(
            getattr(metadata, "prompt_renderer_family", "base") or "base"
        )
        return metadata_family if metadata_family in _PROMPT_RENDERER_FAMILIES else "base"

    @staticmethod
    def _resolve_minimax_tool_call_enabled(provider) -> bool:
        provider_config = getattr(provider, "provider_config", None)
        if not isinstance(provider_config, dict):
            return False
        supports_strategy = getattr(
            provider,
            "supports_output_contract_strategy",
            None,
        )
        if not (
            callable(supports_strategy)
            and supports_strategy("protocol_tool_call")
        ):
            return False
        value = provider_config.get("minimax_enable_tool_call")
        if value is None:
            return True
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    @staticmethod
    def _resolve_provider_from_request(provider_request: ProviderRequest | None):
        if provider_request is None:
            return None
        provider = getattr(provider_request, "provider", None)
        if provider is not None:
            return provider
        provider_type = getattr(provider_request, "provider_type", None)
        if provider_type:
            return _PromptRenderProviderProxy(str(provider_type))
        return None

    @staticmethod
    def _resolve_provider_from_event(event: AstrMessageEvent | None):
        if event is None:
            return None
        provider = event.get_extra("provider")
        if provider is not None:
            return provider
        provider_type = event.get_extra("provider_type")
        if provider_type:
            return _PromptRenderProviderProxy(str(provider_type))
        return None

    @staticmethod
    def _resolve_request_provider(
        plugin_context: Context | None,
        config,
    ):
        if plugin_context is None:
            return None
        provider_id = str(getattr(config, "provider_id", "") or "").strip()
        if not provider_id:
            provider_settings = getattr(config, "provider_settings", None)
            if isinstance(provider_settings, dict):
                provider_id = str(
                    provider_settings.get("default_provider_id")
                    or provider_settings.get("provider_id")
                    or ""
                ).strip()
        if provider_id:
            get_provider_by_id = getattr(plugin_context, "get_provider_by_id", None)
            if callable(get_provider_by_id):
                provider = get_provider_by_id(provider_id)
                if provider is not None:
                    return provider
        get_using_provider = getattr(plugin_context, "get_using_provider", None)
        if callable(get_using_provider):
            try:
                return get_using_provider()
            except TypeError:
                try:
                    return get_using_provider(umo=None)
                except TypeError:
                    return None
        return None

    def _attach_engine_metadata(
        self,
        result: RenderResult,
        *,
        selected_pack: ContextPack,
        renderer: BasePromptRenderer,
        layout: PromptLayoutInterface,
    ) -> RenderResult:
        result.metadata.update(
            {
                "engine": "PromptRenderEngine",
                "renderer_name": renderer.get_name(),
                "layout_name": layout.get_name(),
                "slot_count": len(selected_pack.slots),
                "selected_slot_names": sorted(selected_pack.slots),
                "enabled_slot_groups": list(layout.get_enabled_slot_groups()),
                "prompt_slot_sizes": {
                    name: self._serialized_size(slot.value)
                    for name, slot in selected_pack.slots.items()
                },
            }
        )
        context_budgets = selected_pack.meta.get("context_budgets")
        if isinstance(context_budgets, dict):
            result.metadata["context_budgets"] = deepcopy(context_budgets)
        render_profile = selected_pack.meta.get("render_profile")
        if isinstance(render_profile, str) and render_profile:
            result.metadata["render_profile"] = render_profile
        context_view = selected_pack.meta.get("context_view")
        if isinstance(context_view, str) and context_view:
            result.metadata["context_view"] = context_view
            result.metadata["context_view_source_requirement"] = (
                selected_pack.meta.get("context_view_source_requirement")
            )
            result.metadata["context_view_source_slot_names"] = deepcopy(
                selected_pack.meta.get("context_view_source_slot_names", [])
            )
        return result

    @staticmethod
    def _serialized_size(value: object) -> int:
        try:
            return len(json.dumps(value, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            return len(str(value or ""))

    def _log_render_result(
        self,
        result: RenderResult,
        *,
        selected_pack: ContextPack,
        renderer: BasePromptRenderer,
        event: AstrMessageEvent | None = None,
        provider_request: ProviderRequest | None = None,
    ) -> None:
        if not prompt_trace_enabled():
            return

        payload = {
            "umo": getattr(event, "unified_msg_origin", None) if event else None,
            "session_id": (
                getattr(provider_request, "session_id", None)
                if provider_request is not None
                else None
            ),
            "renderer": renderer.get_name(),
            "slot_count": len(selected_pack.slots),
            "selected_slot_names": sorted(selected_pack.slots),
            "system_prompt_preview": self._preview_text(result.system_prompt),
            "request_prompt_preview": self._preview_text(result.request_prompt),
            "message_count": len(result.messages),
            "message_previews": self._preview_messages(result.messages),
            "tool_schema_count": len(result.tool_schema or []),
            "tool_names": self._extract_tool_names(result.tool_schema),
            "metadata": result.metadata,
        }
        record_prompt_trace(
            event,
            "prompt.render_result",
            **payload,
        )

    @staticmethod
    def _preview_text(text: object, *, limit: int = 240) -> str | None:
        if not isinstance(text, str):
            return None
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 3]}..."

    def _preview_messages(
        self,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        previews: list[dict[str, object]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            preview: dict[str, object] = {
                "role": message.get("role"),
            }
            if isinstance(content, str):
                preview["content_preview"] = self._preview_text(content)
            elif isinstance(content, list):
                preview["part_count"] = len(content)
                preview["content_types"] = [
                    part.get("type")
                    for part in content
                    if isinstance(part, dict) and part.get("type") is not None
                ]
                text_previews = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") != "text":
                        continue
                    text = part.get("text")
                    text_preview = self._preview_text(text, limit=160)
                    if text_preview:
                        text_previews.append(text_preview)
                if text_previews:
                    preview["text_previews"] = text_previews[:2]
            previews.append(preview)
        return previews

    @staticmethod
    def _extract_tool_names(
        tool_schema: list[dict[str, object]] | None,
    ) -> list[str]:
        names: list[str] = []
        for schema in tool_schema or []:
            if not isinstance(schema, dict):
                continue
            function_payload = schema.get("function")
            if isinstance(function_payload, dict):
                name = function_payload.get("name")
            else:
                name = schema.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        return names


class _PromptRenderProviderProxy:
    def __init__(self, provider_type: str) -> None:
        metadata = provider_cls_map.get(provider_type)
        renderer_family = (
            getattr(metadata, "prompt_renderer_family", "base")
            if metadata is not None
            else "base"
        )
        self.provider_config = {
            "type": provider_type,
            "prompt_renderer_family": renderer_family,
        }
