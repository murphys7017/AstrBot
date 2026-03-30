"""
Prompt context collection helpers.

This module wires collectors into a single fail-open collection flow.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from astrbot.core import logger
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.star.context import Context

from .collectors.persona_collector import PersonaCollector
from .context_catalog import get_catalog
from .context_types import ContextPack, ContextSlot
from .interfaces.context_collector_inferface import ContextCollectorInterface

PROMPT_CONTEXT_PACK_EXTRA_KEY = "prompt_context_pack"


def _default_collectors() -> list[ContextCollectorInterface]:
    """Return the collectors enabled for the current phase."""
    return [PersonaCollector()]


def _stringify_value_preview(value: object, *, max_len: int = 400) -> str:
    """Create a compact preview string for logs."""
    if isinstance(value, str):
        preview = " ".join(value.split())
    else:
        try:
            preview = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            preview = repr(value)

    if len(preview) <= max_len:
        return preview
    return f"{preview[: max_len - 3]}..."


async def collect_context_pack(
    *,
    event: AstrMessageEvent,
    plugin_context: Context,
    config,
    provider_request=None,
    collectors: Iterable[ContextCollectorInterface] | None = None,
) -> ContextPack:
    """
    Collect prompt context into a single pack.

    This stage is intentionally fail-open and does not mutate ProviderRequest.
    """
    catalog = get_catalog()
    collector_list = (
        list(collectors) if collectors is not None else _default_collectors()
    )

    pack = ContextPack(
        provider_request_ref=provider_request,
        meta={
            "catalog_version": catalog.version,
            "collectors": [],
        },
    )

    for collector in collector_list:
        collector_name = collector.__class__.__name__
        pack.meta["collectors"].append(collector_name)

        try:
            slots = await collector.collect(event, plugin_context, config)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Prompt context collector failed: collector=%s error=%s",
                collector_name,
                exc,
                exc_info=True,
            )
            continue

        for slot in slots:
            if not catalog.has(slot.name):
                logger.warning(
                    "Prompt context slot is not declared in catalog: slot=%s collector=%s",
                    slot.name,
                    collector_name,
                )

            if pack.has_slot(slot.name):
                logger.warning(
                    "Prompt context slot overwritten: slot=%s collector=%s",
                    slot.name,
                    collector_name,
                )

            pack.add_slot(slot)

    pack.meta["slot_count"] = len(pack.slots)
    return pack


def log_context_pack(
    pack: ContextPack, *, event: AstrMessageEvent | None = None
) -> None:
    """Log a compact summary of the collected context pack."""
    umo = getattr(event, "unified_msg_origin", None) if event else None
    logger.info(
        "Prompt context pack collected: umo=%s catalog=%s collectors=%s slot_count=%s",
        umo,
        pack.meta.get("catalog_version"),
        pack.meta.get("collectors"),
        pack.meta.get("slot_count", len(pack.slots)),
    )

    if not pack.slots:
        return

    for slot_name in sorted(pack.slots):
        slot: ContextSlot = pack.slots[slot_name]
        logger.info(
            "Prompt context slot: name=%s category=%s source=%s meta=%s value=%s",
            slot.name,
            slot.category,
            slot.source,
            slot.meta,
            _stringify_value_preview(slot.value),
        )
