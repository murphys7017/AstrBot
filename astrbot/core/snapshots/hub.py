"""In-memory process snapshot hub shared by Core and plugins."""

from __future__ import annotations

import asyncio
import inspect
import logging
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass, replace
from time import time
from typing import Any
from uuid import uuid4

from .attachments import (
    SnapshotAttachment,
    SnapshotAttachmentRef,
    SnapshotAttachmentStore,
)
from .types import (
    SnapshotCallback,
    SnapshotEnvelope,
    SnapshotProvenance,
    SnapshotScope,
    SnapshotSubscription,
)

logger = logging.getLogger("astrbot.snapshot_hub")


@dataclass(slots=True)
class _SubscriptionState:
    kind: str | None
    source_id: str | None
    scope: SnapshotScope
    callback: SnapshotCallback
    pending: SnapshotEnvelope[Any] | None = None
    task: asyncio.Task[None] | None = None


class _SnapshotSubscription:
    def __init__(self, hub: SnapshotHub, token: str) -> None:
        self._hub = hub
        self._token = token
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._hub._remove_subscription(self._token)


class SnapshotHub:
    """Route bounded, current state between independently owned components.

    The hub is deliberately ephemeral.  Producers own collection and domain
    payloads; the hub only indexes the latest value for each
    ``source/kind/scope`` address.  Durable memory remains owned by the memory
    service and high-frequency desktop frames are never persisted to durable
    storage here. Reads require an explicit scope so a plugin cannot enumerate
    other contexts.
    """

    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str, SnapshotScope], SnapshotEnvelope[Any]] = {}
        self._revisions: dict[tuple[str, str, SnapshotScope], int] = {}
        self._attachments = SnapshotAttachmentStore()
        self._subscriptions: dict[str, _SubscriptionState] = {}

    def put_attachment(
        self,
        *,
        kind: str,
        source_id: str,
        scope: SnapshotScope,
        payload: Any,
        ttl: float | None = None,
        content_type: str = "application/octet-stream",
    ) -> SnapshotAttachmentRef:
        self._refresh_attachment_protection()
        ref = self._attachments.put(
            kind=kind,
            source_id=source_id,
            scope=scope,
            payload=payload,
            ttl=ttl,
            content_type=content_type,
            protected=True,
        )
        # The caller normally publishes a snapshot immediately after putting
        # the attachment. Recompute protection now as well so a failed or
        # delayed publish cannot retain this temporary protection forever.
        self._refresh_attachment_protection()
        return ref

    def get_attachment(
        self,
        ref: SnapshotAttachmentRef,
        *,
        include_expired: bool = False,
    ) -> SnapshotAttachment | None:
        return self._attachments.get(ref, include_expired=include_expired)

    def delete_attachment(self, ref: SnapshotAttachmentRef) -> bool:
        return self._attachments.delete(ref)

    def subscribe(
        self,
        *,
        scope: SnapshotScope,
        callback: SnapshotCallback,
        kind: str | None = None,
        source_id: str | None = None,
        replay_latest: bool = True,
    ) -> SnapshotSubscription:
        if not isinstance(scope, SnapshotScope):
            raise ValueError("snapshot subscriptions require an explicit SnapshotScope")
        token = uuid4().hex
        state = _SubscriptionState(
            kind=(self._normalize_identifier(kind, "kind") if kind else None),
            source_id=(
                self._normalize_identifier(source_id, "source_id")
                if source_id
                else None
            ),
            scope=scope,
            callback=callback,
        )
        self._subscriptions[token] = state
        if replay_latest:
            for envelope in self.list_snapshots(
                kind=state.kind,
                source_id=state.source_id,
                scope=state.scope,
            ):
                self._queue_subscription(state, envelope)
        return _SnapshotSubscription(self, token)

    def publish_snapshot(
        self,
        *,
        kind: str,
        source_id: str,
        scope: SnapshotScope,
        payload: Any,
        ttl: float | None = None,
        provenance: SnapshotProvenance | tuple[str, ...] | None = None,
    ) -> SnapshotEnvelope[Any]:
        self._prune_expired()
        normalized_kind = self._normalize_identifier(kind, "kind")
        normalized_source = self._normalize_identifier(source_id, "source_id")
        if not isinstance(scope, SnapshotScope):
            raise TypeError("scope must be a SnapshotScope")
        if ttl is not None and float(ttl) < 0:
            raise ValueError("snapshot ttl must be non-negative")
        key = (normalized_source, normalized_kind, scope)
        revision = self._revisions.get(key, 0) + 1
        generated_at = time()
        if provenance is None:
            resolved_provenance = SnapshotProvenance(
                source_id=normalized_source,
                observed_at=generated_at,
            )
        elif isinstance(provenance, SnapshotProvenance):
            if provenance.source_id != normalized_source:
                raise ValueError(
                    "snapshot provenance source_id must match source_id"
                )
            resolved_provenance = provenance
        else:
            resolved_provenance = SnapshotProvenance(
                source_id=normalized_source,
                observed_at=generated_at,
                chain=tuple(
                    str(item) for item in provenance if str(item).strip()
                ),
            )
        envelope = SnapshotEnvelope(
            snapshot_id=uuid4().hex,
            kind=normalized_kind,
            source_id=normalized_source,
            scope=scope,
            revision=revision,
            generated_at=generated_at,
            expires_at=(generated_at + float(ttl)) if ttl is not None else None,
            provenance=resolved_provenance,
            payload=deepcopy(payload),
        )
        self._revisions[key] = revision
        self._snapshots[key] = envelope
        self._refresh_attachment_protection()
        self._notify_subscribers(envelope)
        return replace(envelope, payload=deepcopy(envelope.payload))

    def get_snapshot(
        self,
        *,
        kind: str | None = None,
        scope: SnapshotScope,
        source_id: str | None = None,
        include_expired: bool = False,
    ) -> SnapshotEnvelope[Any] | None:
        candidates = self.list_snapshots(
            kind=kind,
            scope=scope,
            source_id=source_id,
            include_expired=include_expired,
        )
        if not candidates:
            return None
        return candidates[0]

    def list_snapshots(
        self,
        *,
        kind: str | None = None,
        scope: SnapshotScope,
        source_id: str | None = None,
        include_expired: bool = False,
    ) -> tuple[SnapshotEnvelope[Any], ...]:
        if not isinstance(scope, SnapshotScope):
            raise ValueError("snapshot reads require an explicit SnapshotScope")
        if not include_expired:
            self._prune_expired()
        normalized_kind = (
            self._normalize_identifier(kind, "kind") if kind is not None else None
        )
        normalized_source = (
            self._normalize_identifier(source_id, "source_id")
            if source_id is not None
            else None
        )
        snapshots = []
        for envelope in self._snapshots.values():
            if normalized_kind is not None and envelope.kind != normalized_kind:
                continue
            if normalized_source is not None and envelope.source_id != normalized_source:
                continue
            if envelope.scope != scope:
                continue
            if not include_expired and envelope.is_expired:
                continue
            snapshots.append(envelope)
        snapshots.sort(key=lambda item: item.generated_at, reverse=True)
        return tuple(
            replace(item, payload=deepcopy(item.payload)) for item in snapshots
        )

    def clear_snapshots(
        self,
        *,
        kind: str | None = None,
        scope: SnapshotScope,
        source_id: str,
    ) -> int:
        """Remove matching values while preserving source revision monotonicity."""

        if not isinstance(scope, SnapshotScope):
            raise ValueError("snapshot clears require an explicit SnapshotScope")

        normalized_source = self._normalize_identifier(source_id, "source_id")
        normalized_kind = (
            self._normalize_identifier(kind, "kind") if kind is not None else None
        )
        keys = []
        for key, envelope in self._snapshots.items():
            if normalized_kind is not None and envelope.kind != normalized_kind:
                continue
            if normalized_source is not None and envelope.source_id != normalized_source:
                continue
            if envelope.scope != scope:
                continue
            keys.append(key)
        for key in keys:
            del self._snapshots[key]
        self._refresh_attachment_protection()
        return len(keys)

    def compose_snapshots(
        self,
        *,
        scope: SnapshotScope,
        kinds: tuple[str, ...] | None = None,
        include_expired: bool = False,
    ) -> tuple[SnapshotEnvelope[Any], ...]:
        """Return a deterministic current view for a consumer or prompt builder."""

        normalized_kinds = (
            {self._normalize_identifier(kind, "kind") for kind in kinds}
            if kinds is not None
            else None
        )
        snapshots = self.list_snapshots(
            scope=scope,
            include_expired=include_expired,
        )
        if normalized_kinds is not None:
            snapshots = tuple(item for item in snapshots if item.kind in normalized_kinds)
        return tuple(
            sorted(
                snapshots,
                key=lambda item: (item.kind, item.source_id, item.generated_at),
            )
        )

    @staticmethod
    def _normalize_identifier(value: str, field_name: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"snapshot {field_name} must not be empty")
        return normalized

    def _prune_expired(self, *, now: float | None = None) -> None:
        observed_at = time() if now is None else float(now)
        expired_keys = [
            key
            for key, envelope in self._snapshots.items()
            if envelope.expires_at is not None and envelope.expires_at <= observed_at
        ]
        for key in expired_keys:
            del self._snapshots[key]
        if expired_keys:
            self._refresh_attachment_protection()

    def _refresh_attachment_protection(self) -> None:
        protected: set[str] = set()
        for envelope in self._snapshots.values():
            _collect_attachment_ids(envelope.payload, protected)
        self._attachments.set_protected_ids(protected)

    def _notify_subscribers(self, envelope: SnapshotEnvelope[Any]) -> None:
        for state in tuple(self._subscriptions.values()):
            if state.scope != envelope.scope:
                continue
            if state.kind is not None and state.kind != envelope.kind:
                continue
            if state.source_id is not None and state.source_id != envelope.source_id:
                continue
            self._queue_subscription(state, envelope)

    def _queue_subscription(
        self,
        state: _SubscriptionState,
        envelope: SnapshotEnvelope[Any],
    ) -> None:
        callback_envelope = replace(
            envelope,
            payload=deepcopy(envelope.payload),
        )
        if inspect.iscoroutinefunction(state.callback):
            state.pending = callback_envelope
            self._ensure_subscription_task(state)
            return
        try:
            result = state.callback(callback_envelope)
            if inspect.isawaitable(result):
                self._schedule_awaitable(result)
        except Exception:  # noqa: BLE001
            logger.exception("snapshot subscription callback failed")

    def _ensure_subscription_task(self, state: _SubscriptionState) -> None:
        if state.task is not None and not state.task.done():
            return
        try:
            state.task = asyncio.create_task(
                self._drain_subscription(state),
                name="astrbot.snapshot_subscription",
            )
        except RuntimeError:
            state.task = None

    async def _drain_subscription(self, state: _SubscriptionState) -> None:
        while state.pending is not None:
            envelope = state.pending
            state.pending = None
            try:
                result = state.callback(envelope)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("snapshot subscription callback failed")
        state.task = None

    @staticmethod
    def _schedule_awaitable(awaitable: Any) -> None:
        try:
            task = asyncio.create_task(awaitable)
        except RuntimeError:
            return
        task.add_done_callback(SnapshotHub._log_subscription_task_failure)

    @staticmethod
    def _log_subscription_task_failure(task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:  # noqa: BLE001
            logger.exception("snapshot subscription callback failed")

    def _remove_subscription(self, token: str) -> None:
        state = self._subscriptions.pop(token, None)
        if state is None:
            return
        state.pending = None
        if state.task is not None and not state.task.done():
            state.task.cancel()

def _collect_attachment_ids(value: Any, result: set[str]) -> None:
    if isinstance(value, SnapshotAttachmentRef):
        result.add(value.attachment_id)
        return
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            _collect_attachment_ids(getattr(value, field.name), result)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_attachment_ids(item, result)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect_attachment_ids(item, result)


__all__ = ["SnapshotHub"]
