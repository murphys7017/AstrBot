from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from astrbot import logger
from astrbot.core.agent.hooks import BaseAgentRunHooks
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import TOOL_TARGET_CORE, FunctionTool
from astrbot.core.agent_lifecycle_scope import (
    _MISSING as LIFECYCLE_MISSING,
)
from astrbot.core.agent_lifecycle_scope import (
    activate_agent_lifecycle,
    create_agent_lifecycle_overlay,
    get_active_agent_lifecycle,
)
from astrbot.core.pipeline.context_utils import call_event_hook
from astrbot.core.platform.astr_message_event import (
    INTERACTION_OUTPUT_CONTROLLER_EXTRA_KEY,
)
from astrbot.core.plugin_runtime import PLUGIN_RUNTIME_TARGET_PERSONAL_EXPRESSION
from astrbot.core.postprocess import dispatch_postprocess
from astrbot.core.postprocess.types import PostProcessTrigger
from astrbot.core.prompt.render import PROMPT_APPLY_RESULT_EXTRA_KEY
from astrbot.core.provider.entities import LLMResponse, ProviderRequest
from astrbot.core.star.star_handler import EventType
from astrbot.core.utils.runtime_diagnostics import measure_runtime_stage

_MISSING = object()
_LEGACY_PROMPT_MUTATION_CHAR_LIMIT = 16_000


@dataclass(slots=True)
class LegacyPromptMutation:
    source: str
    system_prompt_text: str = ""
    context_messages: list[dict[str, Any]] = field(default_factory=list)
    extra_user_content_parts: list[dict[str, Any]] = field(default_factory=list)
    prompt_text_operations: list[tuple[str, str]] = field(default_factory=list)
    fields: set[str] = field(default_factory=set)


def _append_only_string_delta(before: object, after: object) -> str:
    if (
        not isinstance(before, str)
        or not isinstance(after, str)
        or before == after
    ):
        return ""
    if after.startswith(before):
        return after[len(before) :]
    return ""


def _prompt_string_delta(before: object, after: object) -> str:
    suffix = _append_only_string_delta(before, after)
    if suffix:
        return suffix
    if (
        isinstance(before, str)
        and isinstance(after, str)
        and after != before
        and after.endswith(before)
    ):
        return after[: -len(before)]
    return ""


def _prompt_text_operation(before: object, after: object) -> tuple[str, str] | None:
    if not isinstance(before, str) or not isinstance(after, str) or before == after:
        return None
    if after.startswith(before):
        suffix = after[len(before) :]
        return ("suffix", suffix) if suffix.strip() else None
    if before and after.endswith(before):
        prefix = after[: -len(before)]
        return ("prefix", prefix) if prefix.strip() else None
    return None


def _appended_list_items(before: object, after: object) -> list[Any]:
    if not isinstance(before, list) or not isinstance(after, list):
        return []
    if len(after) < len(before):
        return []
    if any(current is not original for original, current in zip(before, after)):
        return []
    return deepcopy(after[len(before) :])


def _serialize_prompt_content_part(value: object) -> Any | None:
    if isinstance(value, str):
        return {"type": "text", "text": value}
    if isinstance(value, dict):
        return deepcopy(value)
    dump_for_context = getattr(value, "model_dump_for_context", None)
    if callable(dump_for_context):
        try:
            result = dump_for_context()
        except Exception:  # noqa: BLE001 - reject malformed legacy content.
            return None
        return deepcopy(result) if isinstance(result, dict) else None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            result = model_dump(exclude_none=True)
        except Exception:  # noqa: BLE001 - reject malformed legacy content.
            return None
        return deepcopy(result) if isinstance(result, dict) else None
    return None


def _normalize_prompt_message_content(value: object) -> str | list[Any] | None:
    if isinstance(value, str):
        return value if value else None
    if not isinstance(value, list):
        return None
    parts = [
        serialized
        for part in value
        if (serialized := _serialize_prompt_content_part(part)) is not None
    ]
    return parts or None


def _capture_legacy_prompt_mutation(
    handler: object,
    before: dict[str, Any],
    after: dict[str, Any],
) -> LegacyPromptMutation | None:
    source_module = str(getattr(handler, "handler_module_path", "") or "").strip()
    source_handler = str(getattr(handler, "handler_name", "") or "").strip()
    source = ":".join(value for value in (source_module, source_handler) if value)
    mutation = LegacyPromptMutation(source=source or "plugin")

    system_suffix = _prompt_string_delta(
        before.get("system_prompt"), after.get("system_prompt")
    )
    if system_suffix.strip():
        mutation.system_prompt_text = system_suffix
        mutation.fields.add("system_prompt")

    for field_name in ("contexts", "extra_user_content_parts"):
        additions = _appended_list_items(before.get(field_name), after.get(field_name))
        if not additions:
            continue
        message_count = len(mutation.context_messages)
        captured_extra_parts = False
        if field_name == "contexts":
            for item in additions:
                if not isinstance(item, dict):
                    continue
                if str(item.get("role", "")).strip().lower() != "user":
                    continue
                content = _normalize_prompt_message_content(item.get("content"))
                if content is not None:
                    mutation.context_messages.append(
                        {"role": "user", "content": content}
                    )
        else:
            content_parts = [
                serialized
                for part in additions
                if (serialized := _serialize_prompt_content_part(part)) is not None
            ]
            if content_parts:
                for part in content_parts:
                    part["_no_save"] = True
                mutation.extra_user_content_parts.extend(content_parts)
                captured_extra_parts = True
        if (
            len(mutation.context_messages) > message_count
            or captured_extra_parts
        ):
            mutation.fields.add(field_name)

    prompt_before = before.get("prompt")
    prompt_operation = _prompt_text_operation(
        prompt_before if isinstance(prompt_before, str) else "",
        after.get("prompt"),
    )
    if prompt_operation is not None:
        mutation.prompt_text_operations.append(prompt_operation)
        mutation.fields.add("prompt")

    return mutation if mutation.fields else None


def _legacy_prompt_mutation_size(mutation: LegacyPromptMutation) -> int:
    return _bounded_prompt_value_size(
        {
            "system_prompt_text": mutation.system_prompt_text,
            "context_messages": mutation.context_messages,
            "extra_user_content_parts": mutation.extra_user_content_parts,
            "prompt_text_operations": mutation.prompt_text_operations,
        },
        _LEGACY_PROMPT_MUTATION_CHAR_LIMIT,
    )


def _bounded_prompt_value_size(value: object, limit: int, *, depth: int = 0) -> int:
    if depth > 12:
        return limit + 1
    if isinstance(value, str):
        return min(len(value), limit + 1)
    if isinstance(value, dict):
        total = 2
        for key, item in value.items():
            total += len(str(key))
            if total > limit:
                return limit + 1
            total += _bounded_prompt_value_size(item, limit - total, depth=depth + 1)
            if total > limit:
                return limit + 1
        return total
    if isinstance(value, list | tuple):
        total = 2
        for item in value:
            total += _bounded_prompt_value_size(item, limit - total, depth=depth + 1)
            if total > limit:
                return limit + 1
        return total
    return 0


class AgentRequestLifecycle:
    """Owns one final request's public plugin lifecycle."""

    def __init__(
        self,
        event,
        *,
        execution_surface: str,
        provider_request: ProviderRequest | None = None,
        prompt_apply_result: object = _MISSING,
        hook_dispatcher: Callable[..., Any] = call_event_hook,
        record_reasoning: bool = False,
        dispatch_response_postprocess: bool = False,
        protected_request_fields: frozenset[str] = frozenset(),
    ) -> None:
        self.event = event
        self.execution_surface = execution_surface
        self.provider_request = provider_request
        self.prompt_apply_result = prompt_apply_result
        self.hook_dispatcher = hook_dispatcher
        self.record_reasoning = record_reasoning
        self.dispatch_response_postprocess = dispatch_response_postprocess
        self.protected_request_fields = protected_request_fields
        self.lifecycle_id = uuid.uuid4().hex
        self.tool_execution_count = 0
        self.legacy_prompt_mutations: list[LegacyPromptMutation] = []
        self._waiting_dispatched = False
        self._request_dispatched = False
        self._agent_begin_dispatched = False
        self._agent_done_dispatched = False
        self._waiting_stopped = False
        self._request_stopped = False
        self._agent_begin_stopped = False
        self._agent_done_stopped = False
        self._overlay = (
            create_agent_lifecycle_overlay(event)
            if execution_surface == PLUGIN_RUNTIME_TARGET_PERSONAL_EXPRESSION
            and getattr(event, "_supports_agent_lifecycle_overlay", False)
            else None
        )

    def bind_request(
        self,
        provider_request: ProviderRequest,
        *,
        prompt_apply_result: object = _MISSING,
    ) -> None:
        self.provider_request = provider_request
        if prompt_apply_result is not _MISSING:
            self.prompt_apply_result = prompt_apply_result

    @contextmanager
    def expose_request(self) -> Iterator[None]:
        with self._activate_scope():
            request = self.provider_request
            if request is None:
                yield
                return

            previous_request = self._capture_extra("provider_request")
            previous_apply_result = self._capture_extra(
                PROMPT_APPLY_RESULT_EXTRA_KEY,
            )
            self.event.set_extra("provider_request", request)
            if self.prompt_apply_result is not _MISSING:
                self.event.set_extra(
                    PROMPT_APPLY_RESULT_EXTRA_KEY,
                    self.prompt_apply_result,
                )
            try:
                yield
            finally:
                self._restore_extra("provider_request", previous_request)
                if self.prompt_apply_result is not _MISSING:
                    self._restore_extra(
                        PROMPT_APPLY_RESULT_EXTRA_KEY,
                        previous_apply_result,
                    )

    async def dispatch_waiting(self) -> bool:
        if self._waiting_dispatched:
            return self._waiting_stopped
        self._waiting_dispatched = True
        with measure_runtime_stage(self.event, "lifecycle.waiting_hook", lifecycle_id=self.lifecycle_id, target=self.execution_surface):
            with self.expose_request():
                self._waiting_stopped = bool(
                    await self.hook_dispatcher(
                        self.event,
                        EventType.OnWaitingLLMRequestEvent,
                        execution_surface=self.execution_surface,
                    )
                )
        return self._waiting_stopped

    async def dispatch_request(self) -> bool:
        if self._request_dispatched:
            return self._request_stopped
        if self.provider_request is None:
            raise RuntimeError("provider request is not bound")
        self._request_dispatched = True
        protected_fields = {
            field_name: deepcopy(getattr(self.provider_request, field_name))
            for field_name in self.protected_request_fields
            if hasattr(self.provider_request, field_name)
        }
        captured_mutations: list[LegacyPromptMutation] = []
        captured_prompt_chars = 0

        def observe_request_mutation(
            handler: object,
            before: dict[str, Any],
            after: dict[str, Any],
        ) -> None:
            nonlocal captured_prompt_chars
            mutation = _capture_legacy_prompt_mutation(handler, before, after)
            if mutation is not None and mutation.fields.intersection(
                self.protected_request_fields
            ):
                mutation_size = _legacy_prompt_mutation_size(mutation)
                if (
                    mutation_size
                    > _LEGACY_PROMPT_MUTATION_CHAR_LIMIT - captured_prompt_chars
                ):
                    logger.warning(
                        "Skipping legacy plugin prompt injection over the request "
                        "limit: source=%s size=%s remaining=%s",
                        mutation.source,
                        mutation_size,
                        max(
                            0,
                            _LEGACY_PROMPT_MUTATION_CHAR_LIMIT
                            - captured_prompt_chars,
                        ),
                    )
                    return
                captured_prompt_chars += mutation_size
                captured_mutations.append(mutation)

        dispatch_kwargs: dict[str, Any] = {
            "execution_surface": self.execution_surface,
        }
        if self.hook_dispatcher is call_event_hook and self.protected_request_fields:
            dispatch_kwargs["_request_mutation_observer"] = observe_request_mutation
        with self.expose_request():
            self._request_stopped = bool(
                await self.hook_dispatcher(
                    self.event,
                    EventType.OnLLMRequestEvent,
                    self.provider_request,
                    **dispatch_kwargs,
                )
            )
        for field_name, value in protected_fields.items():
            if getattr(self.provider_request, field_name) != value:
                if not self._request_stopped and any(
                    field_name in mutation.fields for mutation in captured_mutations
                ):
                    logger.debug(
                        "Adapting append-only OnLLMRequestEvent mutation of protected "
                        "%s field on %s",
                        field_name,
                        self.execution_surface,
                    )
                else:
                    logger.warning(
                        "Ignoring unsupported or oversized OnLLMRequestEvent mutation "
                        "of protected "
                        "%s field on %s",
                        field_name,
                        self.execution_surface,
                    )
                setattr(self.provider_request, field_name, value)
        if not self._request_stopped:
            self.legacy_prompt_mutations.extend(captured_mutations)
            for mutation in captured_mutations:
                logger.info(
                    "DIAG prompt.legacy_plugin_injection_adapted: "
                    "source=%s fields=%s context_message_count=%s",
                    mutation.source,
                    sorted(mutation.fields),
                    len(mutation.context_messages),
                )
        return self._request_stopped

    async def dispatch_agent_begin(self, run_context: ContextWrapper) -> bool:
        if self._agent_begin_dispatched:
            return self._agent_begin_stopped
        self._agent_begin_dispatched = True
        with self.expose_request():
            self._agent_begin_stopped = bool(
                await self.hook_dispatcher(
                    self.event,
                    EventType.OnAgentBeginEvent,
                    run_context,
                    execution_surface=self.execution_surface,
                )
            )
        return self._agent_begin_stopped

    async def dispatch_agent_done(
        self,
        run_context: ContextWrapper,
        llm_response: LLMResponse,
    ) -> bool:
        if self._agent_done_dispatched:
            return self._agent_done_stopped
        self._agent_done_dispatched = True

        with self.expose_request():
            if self.record_reasoning and llm_response.reasoning_content:
                self.event.set_extra(
                    "_llm_reasoning_content",
                    llm_response.reasoning_content,
                )
            response_stopped = bool(
                await self.hook_dispatcher(
                    self.event,
                    EventType.OnLLMResponseEvent,
                    llm_response,
                    execution_surface=self.execution_surface,
                )
            )
            done_stopped = bool(
                await self.hook_dispatcher(
                    self.event,
                    EventType.OnAgentDoneEvent,
                    run_context,
                    llm_response,
                    execution_surface=self.execution_surface,
                )
            )
        self._agent_done_stopped = response_stopped or done_stopped

        if (
            self.dispatch_response_postprocess
            and not self._agent_done_stopped
            and not self.is_stopped()
        ):
            await dispatch_postprocess(
                event=self.event,
                trigger=PostProcessTrigger.ON_LLM_RESPONSE,
                llm_response=llm_response,
                plugin_context=run_context.context.context,
            )
        return self._agent_done_stopped

    async def dispatch_tool_start(
        self,
        tool: FunctionTool,
        tool_args: dict | None,
        *,
        run_context: ContextWrapper | None = None,
    ) -> None:
        self.tool_execution_count += 1
        with self.expose_request():
            await self.hook_dispatcher(
                self.event,
                EventType.OnUsingLLMToolEvent,
                tool,
                tool_args,
                execution_surface=self.execution_surface,
            )
        await self._notify_interaction_tool_stage(
            "start",
            tool,
            tool_args,
            batch_context=self._tool_batch_context(run_context)
            if run_context is not None
            else None,
        )

    async def dispatch_tool_end(
        self,
        tool: FunctionTool,
        tool_args: dict | None,
        tool_result,
        *,
        run_context: ContextWrapper | None = None,
    ) -> None:
        with self.expose_request():
            self.event.clear_result()
            await self.hook_dispatcher(
                self.event,
                EventType.OnLLMToolRespondEvent,
                tool,
                tool_args,
                tool_result,
                execution_surface=self.execution_surface,
            )
        await self._notify_interaction_tool_stage(
            "end",
            tool,
            tool_args,
            tool_result,
            batch_context=self._tool_batch_context(run_context)
            if run_context is not None
            else None,
        )

    @staticmethod
    def _tool_batch_context(run_context: ContextWrapper) -> dict[str, object]:
        return {
            "batch_index": getattr(run_context, "tool_call_batch_index", None),
            "batch_size": getattr(run_context, "tool_call_batch_size", None),
        }

    async def _notify_interaction_tool_stage(
        self,
        phase: str,
        tool: FunctionTool,
        tool_args: dict | None,
        tool_result=None,
        *,
        batch_context: dict[str, object] | None = None,
    ) -> None:
        """Bridge Core tool lifecycle into Interaction without runner coupling."""
        if self.execution_surface != TOOL_TARGET_CORE:
            return
        controller = self.event.get_extra(INTERACTION_OUTPUT_CONTROLLER_EXTRA_KEY)
        callback = getattr(controller, f"observe_core_tool_{phase}", None)
        if not callable(callback):
            return
        batch_context = batch_context or {}
        context_keys = {
            "_interaction_tool_batch_index": batch_context.get("batch_index"),
            "_interaction_tool_batch_size": batch_context.get("batch_size"),
        }
        previous_values = {
            key: self.event.get_extra(key, _MISSING) for key in context_keys
        }
        for key, value in context_keys.items():
            self.event.set_extra(key, value)
        try:
            await callback(self.event, tool, tool_args, tool_result)
        except Exception:  # Progress feedback must never affect tool execution.
            logger.warning(
                "Interaction tool-stage observer failed: phase=%s tool=%s",
                phase,
                getattr(tool, "name", "<unknown>"),
                exc_info=True,
            )
        finally:
            for key, previous in previous_values.items():
                self._restore_extra(key, previous)

    def _restore_extra(self, key: str, previous: object) -> None:
        overlay = get_active_agent_lifecycle(self.event)
        if overlay is not None:
            overlay.restore_extra(key, previous)
            return
        if previous is not _MISSING:
            self.event.set_extra(key, previous)
            return
        extras = getattr(self.event, "_extras", None)
        if isinstance(extras, dict):
            extras.pop(key, None)
        else:
            self.event.set_extra(key, None)

    def _capture_extra(self, key: str) -> object:
        overlay = get_active_agent_lifecycle(self.event)
        if overlay is not None:
            return overlay.capture_extra(key)
        return self.event.get_extra(key, _MISSING)

    @contextmanager
    def _activate_scope(self) -> Iterator[None]:
        if self._overlay is None:
            yield
            return
        with activate_agent_lifecycle(self._overlay):
            yield

    def is_stopped(self) -> bool:
        """Return this lifecycle's stop state without reading a sibling scope."""

        if self._overlay is not None:
            if self._overlay.force_stopped:
                return True
            result = (
                self._overlay.result
                if self._overlay.result is not LIFECYCLE_MISSING
                else self._overlay.initial_result
            )
            if result is None:
                return self._overlay.initial_stopped
            return result.is_stopped()
        return self.event.is_stopped()


class AgentRequestLifecycleHooks(BaseAgentRunHooks):
    """Adapt one request lifecycle to the shared Agent runner hooks."""

    def __init__(
        self,
        lifecycle: AgentRequestLifecycle,
        *,
        dispatch_agent_stages: bool = True,
        before_llm_request: Callable[[ContextWrapper], Awaitable[None]] | None = None,
    ) -> None:
        self.lifecycle = lifecycle
        self.dispatch_agent_stages = dispatch_agent_stages
        self.before_llm_request = before_llm_request

    async def on_agent_begin(self, run_context: ContextWrapper) -> None:
        if self.dispatch_agent_stages:
            await self.lifecycle.dispatch_agent_begin(run_context)

    async def on_before_llm_request(self, run_context: ContextWrapper) -> None:
        if self.before_llm_request is not None:
            await self.before_llm_request(run_context)

    async def on_agent_done(
        self,
        run_context: ContextWrapper,
        llm_response: LLMResponse,
    ) -> None:
        if self.dispatch_agent_stages:
            await self.lifecycle.dispatch_agent_done(run_context, llm_response)

    async def on_tool_start(
        self,
        run_context: ContextWrapper,
        tool: FunctionTool,
        tool_args: dict | None,
    ) -> None:
        await self.lifecycle.dispatch_tool_start(
            tool,
            tool_args,
            run_context=run_context,
        )

    async def on_tool_end(
        self,
        run_context: ContextWrapper,
        tool: FunctionTool,
        tool_args: dict | None,
        tool_result,
    ) -> None:
        await self.lifecycle.dispatch_tool_end(
            tool,
            tool_args,
            tool_result,
            run_context=run_context,
        )


__all__ = ["AgentRequestLifecycle", "AgentRequestLifecycleHooks"]
