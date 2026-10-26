"""Keep optional plugin capabilities from blocking an active OLV Persona stream."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from astrbot.core import logger
from astrbot.core.plugin_admission import resolve_owner_metadata
from astrbot.core.runtime_config_projection import resolve_event_runtime_configuration

SKIPPED_CAPABILITIES_EXTRA_KEY = "_interaction_persona_stream_skipped_capabilities"
PERSONA_STREAM_SAFE_PLUGINS_CONFIG_KEY = "persona_stream_safe_plugins"
DEFAULT_PERSONA_STREAM_SAFE_PLUGINS = frozenset(
    {
        "astrbot_plugin_livingmemory",
        "astrbot_plugin_self_learning",
    }
)


def is_olv_persona_stream(event: Any, *, include_finished: bool = False) -> bool:
    get_platform_name = getattr(event, "get_platform_name", None)
    return (
        callable(get_platform_name)
        and str(get_platform_name() or "").lower() == "olv_pet_adapter"
        and (
            event.get_extra("_interaction_persona_segment_stream_active", False) is True
            or (
                include_finished
                and event.get_extra("_interaction_persona_segment_stream_status")
                in {"completed", "incomplete", "failed", "cancelled"}
            )
        )
    )


def is_olv_persona_stream_scope(event: Any) -> bool:
    """Return whether this turn requested the OLV stream hook isolation scope."""
    get_platform_name = getattr(event, "get_platform_name", None)
    return (
        callable(get_platform_name)
        and str(get_platform_name() or "").lower() == "olv_pet_adapter"
        and event.get_extra(
            "_interaction_persona_segment_stream_requested", False
        ) is True
    )


def skip_incompatible_stream_capability(
    event: Any,
    *,
    kind: str,
    name: str,
    compatible: bool = False,
    include_finished: bool = False,
    include_requested: bool = False,
) -> bool:
    if include_requested:
        in_scope = is_olv_persona_stream_scope(event) or is_olv_persona_stream(
            event, include_finished=include_finished
        )
    else:
        in_scope = is_olv_persona_stream(
            event, include_finished=include_finished
        )
    if not in_scope or compatible:
        return False
    skipped = event.get_extra(SKIPPED_CAPABILITIES_EXTRA_KEY)
    if skipped is None:
        skipped = set()
        event.set_extra(SKIPPED_CAPABILITIES_EXTRA_KEY, skipped)
    identity = (kind, name)
    if identity not in skipped:
        skipped.add(identity)
        logger.debug(
            "DIAG persona_stream.plugin_skipped: turn_id=%s kind=%s name=%s "
            "reason=stream_incompatible action=continue_core_dialogue",
            event.get_extra("_turn_id", ""),
            kind,
            name,
        )
    return True


def _configured_persona_stream_safe_plugins(event: Any) -> set[str]:
    """Resolve plugin names explicitly allowed to run during Persona streaming."""
    config, _ = resolve_event_runtime_configuration(event)
    if not isinstance(config, Mapping):
        return set(DEFAULT_PERSONA_STREAM_SAFE_PLUGINS)
    interaction_config = config.get("interaction_middleware", {})
    if not isinstance(interaction_config, Mapping):
        return set(DEFAULT_PERSONA_STREAM_SAFE_PLUGINS)

    configured = interaction_config.get(PERSONA_STREAM_SAFE_PLUGINS_CONFIG_KEY)
    if configured is None:
        return set(DEFAULT_PERSONA_STREAM_SAFE_PLUGINS)
    if isinstance(configured, str):
        configured = configured.replace(";", ",").replace("\n", ",").split(",")
    if not isinstance(configured, (list, tuple, set, frozenset)):
        return set()
    return {str(name).strip().casefold() for name in configured if str(name).strip()}


def _handler_plugin_name(handler: Any) -> str:
    metadata = resolve_owner_metadata(getattr(handler, "handler_module_path", None))
    return str(getattr(metadata, "name", "") or "").strip().casefold()


def persona_stream_hook_allowed(event: Any, handler: Any) -> bool:
    # Import at dispatch time: Star Context also consumes this policy.
    from astrbot.core.star.star_handler import (
        PERSONA_SEGMENT_STREAM_SAFE_KEY,
        EventType,
    )

    # Requested OLV scope covers interjections and delegated Core-final output
    # after middleware clears the invocation-local active flag. The finished
    # status remains a fallback for terminal callbacks after request cleanup.
    event_type = getattr(handler, "event_type", None)
    if event_type is None:
        return True
    include_finished = event_type is EventType.OnAfterMessageSentEvent
    if not is_olv_persona_stream_scope(event) and not is_olv_persona_stream(
        event, include_finished=include_finished
    ):
        return True
    if event_type not in (
        EventType.OnWaitingLLMRequestEvent,
        EventType.OnLLMRequestEvent,
        EventType.OnLLMResponseEvent,
        EventType.OnAgentBeginEvent,
        EventType.OnAgentDoneEvent,
        EventType.OnPersonaExpressionResultEvent,
        EventType.OnPersonaExpressionSegmentIntentReadyEvent,
        EventType.OnPersonaExpressionSegmentReadyEvent,
        EventType.OnPersonaExpressionStreamFinishedEvent,
        EventType.OnDecoratingResultEvent,
        EventType.OnAfterMessageSentEvent,
    ):
        return True
    extras_configs = getattr(handler, "extras_configs", {})
    if not isinstance(extras_configs, Mapping):
        extras_configs = {}
    compatible = extras_configs.get(PERSONA_SEGMENT_STREAM_SAFE_KEY) is True
    if not compatible:
        compatible = _handler_plugin_name(
            handler
        ) in _configured_persona_stream_safe_plugins(event)
    return not skip_incompatible_stream_capability(
        event,
        kind=getattr(event_type, "name", str(event_type)),
        name=getattr(handler, "handler_full_name", getattr(handler, "handler_name", "<unknown>")),
        compatible=compatible,
        include_finished=include_finished,
        include_requested=True,
    )
