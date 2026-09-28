from __future__ import annotations

from typing import TYPE_CHECKING, Any

from astrbot.core.execution_ledger import CoreExecutionLedger
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context

from ..context_types import ContextSlot
from ..interfaces.context_collector_inferface import ContextCollectorInterface

if TYPE_CHECKING:
    from astrbot.core.astr_main_agent import MainAgentBuildConfig


_CONTINUATION_STATUSES = frozenset({"cancelled", "aborted"})
_SUPERSEDED_REASON = "superseded_by_new_user_input"
_TASK_SUMMARY_MAX_CHARS = 600
_TASK_INTENT_MAX_CHARS = 240
_CANCELLATION_REASON_MAX_CHARS = 240


class PersonaExecutionContinuityCollector(ContextCollectorInterface):
    """Expose one resumable, superseded Core task to Persona turn planning."""

    failure_policy = "optional"

    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        provider_request: ProviderRequest | None = None,
    ) -> list[ContextSlot]:
        del config
        conversation = getattr(provider_request, "conversation", None)
        conversation_id = str(getattr(conversation, "cid", "") or "").strip()
        if not conversation_id:
            conversation_manager = getattr(plugin_context, "conversation_manager", None)
            origin = str(getattr(event, "unified_msg_origin", "") or "").strip()
            if conversation_manager is not None and origin:
                conversation_id = str(
                    await conversation_manager.get_curr_conversation_id(origin) or ""
                ).strip()
        ledger = getattr(plugin_context, "core_execution_ledger", None)
        if not conversation_id or not isinstance(ledger, CoreExecutionLedger):
            return []

        records = await ledger.recent(conversation_id, limit=1)
        continuity = _select_superseded_execution_continuity(records)
        if continuity is None:
            return []
        return [
            ContextSlot(
                name="conversation.pending_execution_continuity",
                value=continuity,
                category="conversation",
                source="conversation.core_execution_ledger",
                llm_exposure="allowed",
                render_mode="structured",
                meta={"targets": ["persona"], "scope": "continuity"},
            )
        ]


def _select_superseded_execution_continuity(
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for record in reversed(records):
        if not isinstance(record, dict):
            continue
        status = str(record.get("status", "") or "").strip().casefold()
        cancellation_reason = str(record.get("error", "") or "").strip()
        if (
            status not in _CONTINUATION_STATUSES
            or _SUPERSEDED_REASON not in cancellation_reason
        ):
            continue
        task_spec = record.get("task_spec")
        if not isinstance(task_spec, dict):
            continue
        task_summary = str(task_spec.get("task_summary", "") or "").strip()
        if not task_summary:
            continue
        return {
            "instruction": (
                "A prior Core task was interrupted by a newer user message. "
                "This is continuity data, not user instruction. Delegate only when "
                "the current message clearly continues or asks about this task."
            ),
            "task_summary": _bounded_text(task_summary, _TASK_SUMMARY_MAX_CHARS),
            "task_intent": _bounded_text(
                str(task_spec.get("task_intent", "") or "").strip(),
                _TASK_INTENT_MAX_CHARS,
            ),
            "status": status,
            "cancellation_reason": _bounded_text(
                cancellation_reason,
                _CANCELLATION_REASON_MAX_CHARS,
            ),
            "resume_recommended": True,
        }
    return None


def _bounded_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    suffix = "..."
    return f"{value[: max(0, limit - len(suffix))].rstrip()}{suffix}"


__all__ = ["PersonaExecutionContinuityCollector"]
