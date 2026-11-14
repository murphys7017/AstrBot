"""Public desktop snapshot payloads published by desktop body adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .attachments import SnapshotAttachment, SnapshotAttachmentRef
from .types import SnapshotScope


@dataclass(frozen=True, slots=True)
class DesktopFrameReference:
    attachment_ref: SnapshotAttachmentRef
    revision: int
    captured_at: float
    generation: int
    client_uid: str


@dataclass(frozen=True, slots=True)
class DesktopStateSnapshot:
    state_revision: int
    generation: int
    client_uid: str
    connected: bool
    observation_supported: bool
    presence_supported: bool
    latest_frame: DesktopFrameReference | None
    presence: dict[str, Any] | None


def resolve_desktop_frame_attachment(
    snapshot_hub: Any,
    *,
    snapshot_kind: str,
    source_id: str,
    scope: SnapshotScope,
    attachment_id: str,
    revision: int | None = None,
    generation: int | None = None,
) -> SnapshotAttachment | None:
    """Resolve one current frame while validating its state identity."""

    if not snapshot_hub or not str(attachment_id).strip():
        return None
    envelope = snapshot_hub.get_snapshot(
        kind=snapshot_kind,
        source_id=source_id,
        scope=scope,
    )
    projection = getattr(envelope, "payload", None)
    if not isinstance(projection, DesktopStateSnapshot):
        return None
    frame = projection.latest_frame
    if frame is None:
        return None
    if (
        frame.attachment_ref.scope != scope
        or frame.attachment_ref.source_id != source_id
        or frame.attachment_ref.kind != "desktop_frame"
    ):
        return None
    if frame.attachment_ref.attachment_id != str(attachment_id).strip():
        return None
    if revision is not None and frame.revision != int(revision):
        return None
    if generation is not None and frame.generation != int(generation):
        return None
    return snapshot_hub.get_attachment(frame.attachment_ref)


__all__ = [
    "DesktopFrameReference",
    "DesktopStateSnapshot",
    "resolve_desktop_frame_attachment",
]
