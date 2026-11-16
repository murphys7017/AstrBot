"""Invocation-local context views applied before PromptTarget projection."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .context_types import ContextPack
from .extensions.types import extension_visible_in_context_view
from .targets import PromptTarget


class PromptContextSourceRequirement(str, Enum):
    """Which Interaction context source an invocation is allowed to consume."""

    CONFIGURED_PERSONA = "configured_persona"
    BASE_ONLY = "base_only"


class PromptContextView(str, Enum):
    """A bounded fact surface for one model invocation within a PromptTarget."""

    TURN_PLAN = "turn_plan"
    OLV_STREAM = "olv_stream"
    PROGRESS = "progress"
    FINAL_RESULT = "final_result"
    PROACTIVE = "proactive"


# Optional event-extra contract used by OLV/AG99live. The Adapter marks a
# turn before prompt rendering; older integrations omit the marker and keep
# their existing image behavior.
DESKTOP_CONTEXT_ALLOWED_EXTRA_KEY = "interaction.desktop_context_allowed"

_DESKTOP_IMAGE_SLOT_NAMES = frozenset(
    {
        "input.images",
        "input.quoted_images",
        "input.image_captions",
        "input.quoted_image_captions",
    }
)


@dataclass(frozen=True, slots=True)
class PromptContextViewSpec:
    """Declarative visibility and acquisition policy for an invocation view."""

    name: PromptContextView
    target: PromptTarget
    source_requirement: PromptContextSourceRequirement
    allowed_slot_names: frozenset[str] | None = None
    allowed_slot_prefixes: frozenset[str] = frozenset()
    history_turns: int | None = None
    history_limit_reason: str | None = None
    history_max_estimated_tokens: int | None = None
    requires_media_context: bool = True

    def allows_slot(self, slot_name: str) -> bool:
        if self.allowed_slot_names is None:
            return True
        return slot_name in self.allowed_slot_names or any(
            slot_name.startswith(prefix) for prefix in self.allowed_slot_prefixes
        )


_PERSONA_BASE_CONTEXT_SLOTS = frozenset(
    {
        "system.global",
        "system.base",
        "extension.system",
        "extension.context",
        "persona.prompt",
        "persona.segments",
        "persona.summary",
        "persona.begin_dialogs",
        "input.text",
        "input.quoted_text",
        "input.visible_reply_material",
        "conversation.history",
        "conversation.group_recent",
        "memory.persona_state",
        "session.datetime",
        "session.user_info",
    }
)

_PERSONA_MEDIA_CONTEXT_SLOTS = frozenset(
    {
        "input.images",
        "input.image_captions",
        "input.quoted_images",
        "input.quoted_image_captions",
        "input.media_content_parts",
        "input.explicit_content_parts",
        "input.attachment_summary",
    }
)


_PERSONA_CONTEXT_VIEWS: dict[PromptContextView, PromptContextViewSpec] = {
    PromptContextView.TURN_PLAN: PromptContextViewSpec(
        name=PromptContextView.TURN_PLAN,
        target=PromptTarget.PERSONA,
        source_requirement=PromptContextSourceRequirement.BASE_ONLY,
        allowed_slot_names=_PERSONA_BASE_CONTEXT_SLOTS | _PERSONA_MEDIA_CONTEXT_SLOTS,
        # Direct Persona views inherit the configured candidate window from
        # the render profile. Token budgets still bound the selected history.
        history_max_estimated_tokens=3000,
    ),
    PromptContextView.OLV_STREAM: PromptContextViewSpec(
        name=PromptContextView.OLV_STREAM,
        target=PromptTarget.PERSONA,
        source_requirement=PromptContextSourceRequirement.BASE_ONLY,
        allowed_slot_names=_PERSONA_BASE_CONTEXT_SLOTS | _PERSONA_MEDIA_CONTEXT_SLOTS,
        history_max_estimated_tokens=1800,
    ),
    PromptContextView.FINAL_RESULT: PromptContextViewSpec(
        name=PromptContextView.FINAL_RESULT,
        target=PromptTarget.PERSONA,
        source_requirement=PromptContextSourceRequirement.CONFIGURED_PERSONA,
        allowed_slot_names=(
            _PERSONA_BASE_CONTEXT_SLOTS
            | {"memory.topic_state", "memory.short_term"}
        ),
        history_max_estimated_tokens=3000,
        requires_media_context=False,
    ),
    PromptContextView.PROGRESS: PromptContextViewSpec(
        name=PromptContextView.PROGRESS,
        target=PromptTarget.PERSONA,
        source_requirement=PromptContextSourceRequirement.BASE_ONLY,
        allowed_slot_names=frozenset(
            {
                "system.global",
                "extension.system",
                "extension.context",
                "persona.summary",
                "input.visible_reply_material",
                "input.previous_persona_acknowledgement",
            }
        ),
        requires_media_context=False,
    ),
    PromptContextView.PROACTIVE: PromptContextViewSpec(
        name=PromptContextView.PROACTIVE,
        target=PromptTarget.PERSONA,
        source_requirement=PromptContextSourceRequirement.BASE_ONLY,
        allowed_slot_names=frozenset(
            {
                "system.global",
                "extension.system",
                "extension.context",
                "persona.summary",
                "input.visible_reply_material",
                "conversation.history",
                "memory.topic_state",
                "memory.short_term",
                "memory.persona_state",
            }
        ),
        history_turns=2,
        history_limit_reason="context_view_history_limit",
        history_max_estimated_tokens=1200,
        requires_media_context=False,
    ),
}


def resolve_prompt_context_view(
    view: PromptContextView | str | None,
) -> PromptContextViewSpec | None:
    if view is None:
        return None
    resolved = PromptContextView(view)
    return _PERSONA_CONTEXT_VIEWS[resolved]


def desktop_context_allowed_for_event(event: Any | None) -> bool:
    """Return whether Adapter-provided desktop frames may reach this prompt."""

    get_platform_name = getattr(event, "get_platform_name", None)
    if not callable(get_platform_name):
        return True
    try:
        platform_name = str(get_platform_name() or "").strip().lower()
    except Exception:  # noqa: BLE001
        return True
    if platform_name != "olv_pet_adapter":
        return True

    get_extra = getattr(event, "get_extra", None)
    if not callable(get_extra):
        return True
    try:
        marker = get_extra(DESKTOP_CONTEXT_ALLOWED_EXTRA_KEY, None)
    except TypeError:
        marker = get_extra(DESKTOP_CONTEXT_ALLOWED_EXTRA_KEY)
    # Missing marker keeps compatibility with older Adapter deployments.
    return marker is not False


def _is_desktop_snapshot_record(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    source = str(record.get("source") or "").strip().lower()
    semantic_type = str(record.get("semantic_type") or "").strip().lower()
    return source == "screen" or semantic_type == "desktop_snapshot"


def project_desktop_context(
    pack: ContextPack,
    *,
    include_desktop_context: bool,
) -> ContextPack:
    """Remove only Adapter desktop snapshots from a branch-local ContextPack."""

    if include_desktop_context or pack.meta.get("desktop_context_filtered") is True:
        return pack

    projected = ContextPack(
        provider_request_ref=pack.provider_request_ref,
        meta=deepcopy(pack.meta),
    )
    removed_count = 0
    removed_attachment_counts = {
        "input.images": 0,
        "input.quoted_images": 0,
    }
    attachment_summary_slot = None
    for slot in pack.slots.values():
        if slot.name == "input.attachment_summary" and isinstance(
            slot.value, dict
        ):
            attachment_summary_slot = slot
            continue
        if slot.name not in _DESKTOP_IMAGE_SLOT_NAMES or not isinstance(
            slot.value, list
        ):
            projected.add_slot(deepcopy(slot))
            continue

        retained = []
        for record in slot.value:
            if _is_desktop_snapshot_record(record):
                removed_count += 1
                if slot.name in removed_attachment_counts:
                    removed_attachment_counts[slot.name] += 1
                continue
            retained.append(deepcopy(record))
        if not retained:
            continue
        selected = deepcopy(slot)
        selected.value = retained
        projected.add_slot(selected)

    if attachment_summary_slot is not None:
        summary = deepcopy(attachment_summary_slot.value)
        for slot_name, summary_key in (
            ("input.images", "images"),
            ("input.quoted_images", "quoted_images"),
        ):
            removed = removed_attachment_counts[slot_name]
            if removed <= 0:
                continue
            remaining = int(summary.get(summary_key, 0) or 0) - removed
            if remaining > 0:
                summary[summary_key] = remaining
            else:
                summary.pop(summary_key, None)
        if summary:
            selected = deepcopy(attachment_summary_slot)
            selected.value = summary
            projected.add_slot(selected)

    projected.meta["desktop_context_filtered"] = True
    projected.meta["desktop_context_removed_records"] = removed_count
    return projected


def project_prompt_context_view(
    pack: ContextPack,
    view: PromptContextView | str | None,
) -> ContextPack:
    """Create a view-local Pack without weakening later target projection."""

    spec = resolve_prompt_context_view(view)
    if spec is None:
        return pack
    # Attached images are current input. View visibility, rather than words in
    # the user's message, determines which invocation receives them.
    projected = ContextPack(
        provider_request_ref=pack.provider_request_ref,
        meta=deepcopy(pack.meta),
    )
    for slot in pack.slots.values():
        if spec.allows_slot(slot.name):
            selected = slot
            if slot.name == "extension.context":
                selected = deepcopy(slot)
                if not isinstance(selected.value, dict):
                    continue
                items = selected.value.get("items")
                if not isinstance(items, list):
                    continue
                selected.value["items"] = [
                    item for item in items
                    if isinstance(item, dict)
                    and extension_visible_in_context_view(
                        "context",
                        item.get("meta") if isinstance(item.get("meta"), dict) else {},
                        spec.name.value,
                    )
                ]
                if not selected.value["items"]:
                    continue
                selected.meta["item_count"] = len(selected.value["items"])
            projected.add_slot(selected)

    projected.meta["context_view"] = spec.name.value
    projected.meta["context_view_source_requirement"] = spec.source_requirement.value
    projected.meta["context_view_source_slot_names"] = sorted(pack.slots)
    projected.meta["context_view_selected_slot_names"] = sorted(projected.slots)
    return projected


__all__ = [
    "DESKTOP_CONTEXT_ALLOWED_EXTRA_KEY",
    "PromptContextSourceRequirement",
    "PromptContextView",
    "PromptContextViewSpec",
    "desktop_context_allowed_for_event",
    "project_desktop_context",
    "project_prompt_context_view",
    "resolve_prompt_context_view",
]
