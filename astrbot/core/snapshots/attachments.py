"""Short-lived opaque payloads referenced by snapshot envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any
from uuid import uuid4

from .types import SnapshotScope


@dataclass(frozen=True, slots=True)
class SnapshotAttachmentRef:
    attachment_id: str
    kind: str
    source_id: str
    scope: SnapshotScope
    created_at: float
    expires_at: float | None
    content_type: str
    size: int | None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and time() >= self.expires_at


@dataclass(frozen=True, slots=True)
class SnapshotAttachment:
    ref: SnapshotAttachmentRef
    payload: Any


class SnapshotAttachmentStore:
    """Own opaque, short-lived payloads referenced by current snapshots."""

    def __init__(self, *, max_entries: int = 25) -> None:
        self._max_entries = max(1, int(max_entries))
        self._entries: dict[str, SnapshotAttachment] = {}
        self._protected_ids: set[str] = set()

    def set_protected_ids(self, attachment_ids: set[str]) -> None:
        """Keep attachments referenced by current snapshots during eviction."""

        self._protected_ids = set(attachment_ids)
        self._trim_to_limit()

    def put(
        self,
        *,
        kind: str,
        source_id: str,
        scope: SnapshotScope,
        payload: Any,
        ttl: float | None = None,
        content_type: str = "application/octet-stream",
        protected: bool = False,
    ) -> SnapshotAttachmentRef:
        if ttl is not None and float(ttl) < 0:
            raise ValueError("snapshot attachment ttl must be non-negative")
        self._prune_expired()
        created_at = time()
        ref = SnapshotAttachmentRef(
            attachment_id=uuid4().hex,
            kind=str(kind or "").strip(),
            source_id=str(source_id or "").strip(),
            scope=scope,
            created_at=created_at,
            expires_at=(created_at + float(ttl)) if ttl is not None else None,
            content_type=str(content_type or "application/octet-stream").strip(),
            size=_payload_size(payload),
        )
        if not ref.kind or not ref.source_id:
            raise ValueError("snapshot attachment kind and source_id are required")
        if not isinstance(scope, SnapshotScope):
            raise TypeError("scope must be a SnapshotScope")
        self._entries[ref.attachment_id] = SnapshotAttachment(ref, payload)
        if protected:
            self._protected_ids.add(ref.attachment_id)
        self._trim_to_limit()
        return ref

    def get(
        self,
        ref: SnapshotAttachmentRef,
        *,
        include_expired: bool = False,
    ) -> SnapshotAttachment | None:
        if not isinstance(ref, SnapshotAttachmentRef):
            raise TypeError("attachment ref must be a SnapshotAttachmentRef")
        if not include_expired:
            self._prune_expired()
        entry = self._entries.get(ref.attachment_id)
        if entry is None:
            return None
        if entry.ref != ref:
            return None
        if not include_expired and entry.ref.is_expired:
            return None
        return entry

    def delete(self, ref: SnapshotAttachmentRef) -> bool:
        if not isinstance(ref, SnapshotAttachmentRef):
            raise TypeError("attachment ref must be a SnapshotAttachmentRef")
        self._protected_ids.discard(ref.attachment_id)
        return self._entries.pop(ref.attachment_id, None) is not None

    def _prune_expired(self) -> None:
        for attachment_id, entry in tuple(self._entries.items()):
            if entry.ref.is_expired:
                self._entries.pop(attachment_id, None)

    def _trim_to_limit(self) -> None:
        if len(self._entries) <= self._max_entries:
            return
        ordered = sorted(
            (
                entry
                for entry in self._entries.values()
                if entry.ref.attachment_id not in self._protected_ids
            ),
            key=lambda entry: entry.ref.created_at,
        )
        removable = max(0, len(self._entries) - self._max_entries)
        for entry in ordered[:removable]:
            self._entries.pop(entry.ref.attachment_id, None)


def _payload_size(payload: Any) -> int | None:
    try:
        return len(payload)
    except TypeError:
        return None


__all__ = [
    "SnapshotAttachment",
    "SnapshotAttachmentRef",
    "SnapshotAttachmentStore",
]
