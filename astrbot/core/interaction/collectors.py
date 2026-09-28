from __future__ import annotations

from typing import TYPE_CHECKING

from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.prompt.context_types import ContextSlot
from astrbot.core.prompt.interfaces.context_collector_inferface import (
    ContextCollectorInterface,
)
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context

from .turn_state import get_interaction_turn_immediate_reply

if TYPE_CHECKING:
    from astrbot.core.astr_main_agent import MainAgentBuildConfig


_PERSONA_PROGRESS_TEXT_MAX_CHARS = 480
_PERSONA_PROGRESS_ACKNOWLEDGEMENT_MAX_CHARS = 240
_PERSONA_PROACTIVE_TEXT_MAX_CHARS = 1000


def _truncate_phase_local_text(value: object, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


class PersonaVisibleReplyCollector(ContextCollectorInterface):
    """Collect phase-local material consumed by the Persona render target."""

    def __init__(self, request: object) -> None:
        self.request = request

    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        provider_request: ProviderRequest | None = None,
    ) -> list[ContextSlot]:
        del plugin_context, config, provider_request
        request = self.request
        intent = getattr(request, "intent", None)
        intent_kind = str(getattr(intent, "kind", "") or "")
        payload = {
            "phase": str(getattr(intent, "phase", "standalone") or "standalone"),
            "source": str(getattr(intent, "source", "direct") or "direct"),
            "source_text": str(getattr(request, "source_text", "") or "").strip(),
            "immediate_reply": str(
                getattr(request, "immediate_reply", "") or ""
            ).strip(),
            "observed_text": str(
                getattr(request, "observed_text", "") or ""
            ).strip(),
            "total_text": str(getattr(request, "total_text", "") or "").strip(),
            "pending_text": str(
                getattr(request, "pending_text", "") or ""
            ).strip(),
            "progress_stage": str(
                getattr(request, "progress_stage", "") or ""
            ).strip(),
            "preserve_facts": bool(getattr(request, "preserve_facts", False)),
            "short_reply": bool(getattr(request, "short_reply", False)),
            "allow_empty": bool(getattr(request, "allow_empty", False)),
        }
        if intent_kind == "interjection":
            payload = {
                "phase": payload["phase"],
                "source": payload["source"],
                "progress_stage": payload["progress_stage"],
                "observed_text": _truncate_phase_local_text(
                    payload["observed_text"],
                    max_chars=_PERSONA_PROGRESS_TEXT_MAX_CHARS,
                ),
                "pending_text": _truncate_phase_local_text(
                    payload["pending_text"],
                    max_chars=_PERSONA_PROGRESS_TEXT_MAX_CHARS,
                ),
                "short_reply": payload["short_reply"],
                "allow_empty": payload["allow_empty"],
            }
        elif intent_kind == "proactive":
            for field in (
                "source_text",
                "immediate_reply",
                "observed_text",
                "total_text",
                "pending_text",
            ):
                payload[field] = _truncate_phase_local_text(
                    payload[field],
                    max_chars=_PERSONA_PROACTIVE_TEXT_MAX_CHARS,
                )
        payload = {
            key: value for key, value in payload.items() if value not in {"", False}
        }
        if not payload:
            return []
        slots = [
            ContextSlot(
                name="input.visible_reply_material",
                value=payload,
                category="input",
                source="interaction_visible_reply_material",
                render_mode="structured",
                meta={
                    "scope": "dynamic",
                    "node_type": "interaction_visible_reply_material",
                },
            )
        ]
        if intent_kind == "interjection":
            acknowledgement = get_interaction_turn_immediate_reply(event)
            if acknowledgement:
                slots.append(
                    ContextSlot(
                        name="input.previous_persona_acknowledgement",
                        value={
                            "text": _truncate_phase_local_text(
                                acknowledgement,
                                max_chars=_PERSONA_PROGRESS_ACKNOWLEDGEMENT_MAX_CHARS,
                            )
                        },
                        category="input",
                        source="interaction_turn_state",
                        render_mode="structured",
                        meta={
                            "scope": "dynamic",
                            "node_type": "previous_persona_acknowledgement",
                        },
                    )
                )
        return slots
