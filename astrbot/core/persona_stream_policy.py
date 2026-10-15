"""Keep optional plugin capabilities from blocking an active OLV Persona stream."""

from __future__ import annotations

from typing import Any

from astrbot.core import logger

SKIPPED_CAPABILITIES_EXTRA_KEY = "_interaction_persona_stream_skipped_capabilities"


def is_olv_persona_stream(event: Any) -> bool:
    get_platform_name = getattr(event, "get_platform_name", None)
    return (
        callable(get_platform_name)
        and str(get_platform_name() or "").lower() == "olv_pet_adapter"
        and event.get_extra("_interaction_persona_segment_stream_active", False) is True
    )


def skip_incompatible_stream_capability(
    event: Any, *, kind: str, name: str, compatible: bool = False
) -> bool:
    if not is_olv_persona_stream(event) or compatible:
        return False
    skipped = event.get_extra(SKIPPED_CAPABILITIES_EXTRA_KEY)
    if skipped is None:
        skipped = set()
        event.set_extra(SKIPPED_CAPABILITIES_EXTRA_KEY, skipped)
    identity = (kind, name)
    if identity not in skipped:
        skipped.add(identity)
        logger.warning(
            "DIAG persona_stream.plugin_skipped: turn_id=%s kind=%s name=%s "
            "reason=stream_incompatible action=continue_core_dialogue",
            event.get_extra("_turn_id", ""),
            kind,
            name,
        )
    return True


def persona_stream_hook_allowed(event: Any, handler: Any) -> bool:
    if not is_olv_persona_stream(event):
        return True
    # Import at dispatch time: Star Context also consumes this policy.
    from astrbot.core.star.star_handler import (
        PERSONA_SEGMENT_STREAM_SAFE_KEY,
        EventType,
    )

    if handler.event_type not in (
        EventType.OnWaitingLLMRequestEvent,
        EventType.OnLLMRequestEvent,
        EventType.OnLLMResponseEvent,
        EventType.OnAgentBeginEvent,
        EventType.OnAgentDoneEvent,
        EventType.OnPersonaExpressionResultEvent,
        EventType.OnDecoratingResultEvent,
    ):
        return True
    return not skip_incompatible_stream_capability(
        event,
        kind=handler.event_type.name,
        name=handler.handler_full_name,
        compatible=handler.extras_configs.get(PERSONA_SEGMENT_STREAM_SAFE_KEY) is True,
    )
