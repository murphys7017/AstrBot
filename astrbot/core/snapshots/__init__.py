"""Shared in-memory snapshot contracts for Core and plugins."""

from .attachments import (
    SnapshotAttachment,
    SnapshotAttachmentRef,
    SnapshotAttachmentStore,
)
from .desktop import (
    DesktopFrameReference,
    DesktopStateSnapshot,
    resolve_desktop_frame_attachment,
)
from .hub import SnapshotHub
from .types import (
    SnapshotCallback,
    SnapshotComposer,
    SnapshotEnvelope,
    SnapshotFreshness,
    SnapshotProvenance,
    SnapshotPublisher,
    SnapshotReader,
    SnapshotScope,
    SnapshotSubscription,
)

__all__ = [
    "SnapshotAttachment",
    "SnapshotAttachmentRef",
    "SnapshotAttachmentStore",
    "SnapshotCallback",
    "DesktopFrameReference",
    "DesktopStateSnapshot",
    "resolve_desktop_frame_attachment",
    "SnapshotComposer",
    "SnapshotEnvelope",
    "SnapshotFreshness",
    "SnapshotHub",
    "SnapshotPublisher",
    "SnapshotProvenance",
    "SnapshotReader",
    "SnapshotScope",
    "SnapshotSubscription",
]
