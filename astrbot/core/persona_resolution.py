"""Event-local selected-persona resolution shared by prompt and execution paths."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from astrbot.core.persona_context import PersonaContextSeed

PERSONA_RESOLUTION_CACHE_EXTRA_KEY = "_persona_resolution_cache"
PERSONA_RESOLUTION_INFLIGHT_EXTRA_KEY = "_persona_resolution_inflight"
PersonaResolutionCacheKey = tuple[str, str, str, str, int]


@dataclass(frozen=True, slots=True)
class PersonaResolution:
    """One selected-persona result, stable for the lifetime of an event."""

    persona_id: str | None
    persona: dict[str, Any] | None
    force_applied_persona_id: str | None
    use_webchat_special_default: bool


def build_event_persona_resolution_key(
    *,
    event: Any,
    persona_manager: object,
    conversation_persona_id: str | None,
    provider_settings: Mapping[str, Any] | None,
) -> PersonaResolutionCacheKey:
    """Build a key from every current PersonaManager resolution input."""
    default_personality = ""
    if isinstance(provider_settings, Mapping):
        default_personality = str(
            provider_settings.get("default_personality", "") or ""
        )
    return (
        str(getattr(event, "unified_msg_origin", "") or ""),
        str(event.get_platform_name() or ""),
        str(conversation_persona_id or ""),
        default_personality,
        id(persona_manager),
    )


async def resolve_event_persona(
    *,
    event: Any,
    persona_manager: Any,
    conversation_persona_id: str | None,
    provider_settings: Mapping[str, Any] | None,
) -> PersonaResolution:
    """Resolve selected persona once per event, sharing concurrent callers."""
    key = build_event_persona_resolution_key(
        event=event,
        persona_manager=persona_manager,
        conversation_persona_id=conversation_persona_id,
        provider_settings=provider_settings,
    )
    cache = _get_event_cache(event, PERSONA_RESOLUTION_CACHE_EXTRA_KEY)
    cached = cache.get(key)
    if isinstance(cached, PersonaResolution):
        return cached

    inflight = _get_event_cache(event, PERSONA_RESOLUTION_INFLIGHT_EXTRA_KEY)
    task = inflight.get(key)
    if not isinstance(task, asyncio.Task):
        task = asyncio.create_task(
            resolve_persona_selection(
                unified_msg_origin=event.unified_msg_origin,
                platform_name=event.get_platform_name(),
                persona_manager=persona_manager,
                conversation_persona_id=conversation_persona_id,
                provider_settings=provider_settings,
            )
        )
        task.add_done_callback(_consume_background_resolution_exception)
        inflight[key] = task
        _set_event_cache(event, PERSONA_RESOLUTION_INFLIGHT_EXTRA_KEY, inflight)

    try:
        resolution = await asyncio.shield(task)
    except BaseException:
        if task.done():
            inflight.pop(key, None)
            _set_event_cache(event, PERSONA_RESOLUTION_INFLIGHT_EXTRA_KEY, inflight)
        raise

    cache[key] = resolution
    _set_event_cache(event, PERSONA_RESOLUTION_CACHE_EXTRA_KEY, cache)
    inflight.pop(key, None)
    _set_event_cache(event, PERSONA_RESOLUTION_INFLIGHT_EXTRA_KEY, inflight)
    return resolution


async def resolve_persona_selection(
    *,
    unified_msg_origin: str,
    platform_name: str,
    persona_manager: Any,
    conversation_persona_id: str | None,
    provider_settings: Mapping[str, Any] | None,
) -> PersonaResolution:
    """Resolve one selected-persona snapshot without requiring an Event."""
    (
        persona_id,
        persona,
        force_applied_persona_id,
        use_webchat_special_default,
    ) = await persona_manager.resolve_selected_persona(
        umo=unified_msg_origin,
        conversation_persona_id=conversation_persona_id,
        platform_name=platform_name,
        provider_settings=dict(provider_settings or {}),
    )
    return PersonaResolution(
        persona_id=persona_id,
        persona=persona if isinstance(persona, dict) else None,
        force_applied_persona_id=force_applied_persona_id,
        use_webchat_special_default=bool(use_webchat_special_default),
    )


def _get_event_cache(event: Any, key: str) -> dict[PersonaResolutionCacheKey, Any]:
    try:
        cache = event.get_extra(key, {})
    except Exception:  # noqa: BLE001
        return {}
    return cache if isinstance(cache, dict) else {}


def _set_event_cache(
    event: Any,
    key: str,
    cache: dict[PersonaResolutionCacheKey, Any],
) -> None:
    try:
        event.set_extra(key, cache)
    except Exception:  # noqa: BLE001
        pass


def _consume_background_resolution_exception(
    task: asyncio.Task[PersonaResolution],
) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except asyncio.CancelledError:
        return


__all__ = [
    "PERSONA_RESOLUTION_CACHE_EXTRA_KEY",
    "PERSONA_RESOLUTION_INFLIGHT_EXTRA_KEY",
    "PersonaContextSeed",
    "PersonaResolution",
    "build_event_persona_resolution_key",
    "resolve_event_persona",
    "resolve_persona_selection",
]
