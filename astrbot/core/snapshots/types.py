"""Common contracts for short-lived runtime snapshots.

Snapshots are immutable views of a domain-owned state source.  The envelope
provides the metadata that lets consumers reason about scope, freshness and
provenance without coupling them to the source's domain model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

if TYPE_CHECKING:
    from .attachments import SnapshotAttachment, SnapshotAttachmentRef


class SnapshotFreshness(StrEnum):
    """The freshness state derived from an envelope's expiration time."""

    FRESH = "fresh"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class SnapshotProvenance:
    """Source trail attached to a snapshot without exposing source internals."""

    source_id: str
    observed_at: float
    chain: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotScope:
    """Stable address of the context a snapshot describes."""

    scope_type: str
    scope_id: str
    parent_id: str | None = None

    def __post_init__(self) -> None:
        if not str(self.scope_type).strip():
            raise ValueError("snapshot scope_type must not be empty")
        if not str(self.scope_id).strip():
            raise ValueError("snapshot scope_id must not be empty")


PayloadT = TypeVar("PayloadT")
SnapshotCallback = Callable[
    ["SnapshotEnvelope[Any]"], Awaitable[None] | None
]


@dataclass(frozen=True, slots=True)
class SnapshotEnvelope(Generic[PayloadT]):
    """Metadata plus one domain-owned snapshot payload."""

    snapshot_id: str
    kind: str
    source_id: str
    scope: SnapshotScope
    revision: int
    generated_at: float
    expires_at: float | None
    provenance: SnapshotProvenance
    payload: PayloadT

    def freshness(self, *, now: float | None = None) -> SnapshotFreshness:
        if self.expires_at is None:
            return SnapshotFreshness.FRESH
        import time

        observed_at = time.time() if now is None else float(now)
        return (
            SnapshotFreshness.FRESH
            if observed_at < self.expires_at
            else SnapshotFreshness.EXPIRED
        )

    @property
    def is_expired(self) -> bool:
        return self.freshness() is SnapshotFreshness.EXPIRED


class SnapshotReader(Protocol):
    """Public read boundary; every read is scoped to one context."""

    def get_snapshot(
        self,
        *,
        kind: str | None = None,
        scope: SnapshotScope,
        source_id: str | None = None,
        include_expired: bool = False,
    ) -> SnapshotEnvelope[Any] | None: ...

    def list_snapshots(
        self,
        *,
        kind: str | None = None,
        scope: SnapshotScope,
        source_id: str | None = None,
        include_expired: bool = False,
    ) -> tuple[SnapshotEnvelope[Any], ...]: ...

    def get_attachment(
        self,
        ref: SnapshotAttachmentRef,
        *,
        include_expired: bool = False,
    ) -> SnapshotAttachment | None: ...

    def subscribe(
        self,
        *,
        scope: SnapshotScope,
        callback: SnapshotCallback,
        kind: str | None = None,
        source_id: str | None = None,
        replay_latest: bool = True,
    ) -> SnapshotSubscription: ...


class SnapshotPublisher(Protocol):
    """Public write boundary implemented by state-producing plugins."""

    def publish_snapshot(
        self,
        *,
        kind: str,
        source_id: str,
        scope: SnapshotScope,
        payload: Any,
        ttl: float | None = None,
        provenance: SnapshotProvenance | tuple[str, ...] | None = None,
    ) -> SnapshotEnvelope[Any]: ...

    def put_attachment(
        self,
        *,
        kind: str,
        source_id: str,
        scope: SnapshotScope,
        payload: Any,
        ttl: float | None = None,
        content_type: str = "application/octet-stream",
    ) -> SnapshotAttachmentRef: ...


class SnapshotComposer(Protocol):
    """Read boundary for composing several current domain snapshots."""

    def compose_snapshots(
        self,
        *,
        scope: SnapshotScope,
        kinds: tuple[str, ...] | None = None,
        include_expired: bool = False,
    ) -> tuple[SnapshotEnvelope[Any], ...]: ...


class SnapshotSubscription(Protocol):
    """Handle used to stop one scoped snapshot subscription."""

    def close(self) -> None: ...


__all__ = [
    "SnapshotEnvelope",
    "SnapshotFreshness",
    "SnapshotProvenance",
    "SnapshotComposer",
    "SnapshotPublisher",
    "SnapshotReader",
    "SnapshotScope",
    "SnapshotCallback",
    "SnapshotSubscription",
]
