"""Publish MemorySnapshot payloads through the shared Core snapshot hub."""

from __future__ import annotations

import hashlib
from typing import Any

from astrbot.core.snapshots import SnapshotScope

from .types import MemorySnapshot

MEMORY_SNAPSHOT_KIND = "memory"
MEMORY_SNAPSHOT_SOURCE = "astrbot.memory"
MEMORY_SNAPSHOT_TTL_SECONDS = 120.0


def build_memory_snapshot_scope(
    *,
    config_id: str,
    umo: str,
    conversation_id: str | None,
) -> SnapshotScope:
    """Build a stable, non-sensitive scope key for one prompt memory view."""

    raw_scope = "|".join(
        (
            str(config_id or "default").strip() or "default",
            str(umo or "").strip(),
            str(conversation_id or "__default__").strip() or "__default__",
        )
    )
    scope_id = hashlib.sha256(raw_scope.encode("utf-8")).hexdigest()
    return SnapshotScope(scope_type="conversation", scope_id=scope_id)


def publish_memory_snapshot(
    hub: Any,
    snapshot: MemorySnapshot,
    *,
    config_id: str,
) -> None:
    """Publish one bounded prompt snapshot when the public hub is available."""

    if not isinstance(snapshot, MemorySnapshot):
        raise TypeError("snapshot must be a MemorySnapshot")
    hub.publish_snapshot(
        kind=MEMORY_SNAPSHOT_KIND,
        source_id=MEMORY_SNAPSHOT_SOURCE,
        scope=build_memory_snapshot_scope(
            config_id=config_id,
            umo=snapshot.umo,
            conversation_id=snapshot.conversation_id,
        ),
        payload=snapshot,
        ttl=MEMORY_SNAPSHOT_TTL_SECONDS,
        provenance=("memory_service", "prompt_snapshot"),
    )


def read_memory_snapshot(
    hub: Any,
    *,
    scope: SnapshotScope,
    include_expired: bool = False,
) -> MemorySnapshot | None:
    """Read a typed MemorySnapshot from the shared hub."""

    envelope = hub.get_snapshot(
        kind=MEMORY_SNAPSHOT_KIND,
        source_id=MEMORY_SNAPSHOT_SOURCE,
        scope=scope,
        include_expired=include_expired,
    )
    payload = getattr(envelope, "payload", None)
    return payload if isinstance(payload, MemorySnapshot) else None


__all__ = [
    "MEMORY_SNAPSHOT_KIND",
    "MEMORY_SNAPSHOT_SOURCE",
    "MEMORY_SNAPSHOT_TTL_SECONDS",
    "build_memory_snapshot_scope",
    "publish_memory_snapshot",
    "read_memory_snapshot",
]
