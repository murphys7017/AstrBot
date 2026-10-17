"""Invocation-local context views applied before PromptTarget projection."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum

from .context_types import ContextPack
from .targets import PromptTarget

_AMBIENT_VISUAL_SLOT_NAMES = frozenset(
    {
        "input.images",
        "input.image_captions",
        "input.quoted_images",
        "input.quoted_image_captions",
    }
)
_EXPLICIT_VISUAL_REQUEST = re.compile(
    r"屏幕|桌面|截图|画面|窗口|界面|弹窗|报错|错误提示|图片|照片|图像|图里|图中|图上|"
    r"屏幕上|屏幕里|屏幕内容|当前页面|这个页面|当前窗口|窗口里|图片里|截图里|"
    r"识别文字|提取文字|读一下图|帮我看看|帮我看一下|你看一下|你看看|看一下这个|看看这个|"
    r"\b(?:screen|desktop|screenshot|window|interface|ui|image|picture|photo)\b",
    re.IGNORECASE,
)


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


_PERSONA_CONTEXT_VIEWS: dict[PromptContextView, PromptContextViewSpec] = {
    PromptContextView.TURN_PLAN: PromptContextViewSpec(
        name=PromptContextView.TURN_PLAN,
        target=PromptTarget.PERSONA,
        source_requirement=PromptContextSourceRequirement.BASE_ONLY,
        allowed_slot_names=frozenset(
            {
                "system.global",
                "system.base",
                "extension.system",
                "persona.prompt",
                "persona.segments",
                "persona.summary",
                "persona.begin_dialogs",
                "input.text",
                "input.images",
                "input.image_captions",
                "input.quoted_text",
                "input.quoted_images",
                "input.quoted_image_captions",
                "input.media_content_parts",
                "input.explicit_content_parts",
                "input.attachment_summary",
                "input.visible_reply_material",
                "conversation.history",
                "conversation.group_recent",
                "conversation.pending_execution_continuity",
                "memory.topic_state",
                "memory.short_term",
                "memory.persona_state",
                "session.datetime",
                "session.user_info",
            }
        ),
        history_turns=6,
        history_limit_reason="context_view_history_limit",
        history_max_estimated_tokens=3000,
    ),
    PromptContextView.OLV_STREAM: PromptContextViewSpec(
        name=PromptContextView.OLV_STREAM,
        target=PromptTarget.PERSONA,
        source_requirement=PromptContextSourceRequirement.BASE_ONLY,
        allowed_slot_names=frozenset(
            {
                "system.global",
                "system.base",
                "extension.system",
                "persona.prompt",
                "persona.segments",
                "persona.summary",
                "persona.begin_dialogs",
                "input.text",
                "input.images",
                "input.image_captions",
                "input.quoted_text",
                "input.quoted_images",
                "input.quoted_image_captions",
                "input.media_content_parts",
                "input.explicit_content_parts",
                "input.attachment_summary",
                "input.visible_reply_material",
                "conversation.history",
                "conversation.group_recent",
                "conversation.pending_execution_continuity",
                "memory.topic_state",
                "memory.short_term",
                "memory.persona_state",
                "session.datetime",
                "session.user_info",
            }
        ),
        history_turns=3,
        history_limit_reason="olv_stream_history_limit",
        history_max_estimated_tokens=1800,
    ),
    PromptContextView.FINAL_RESULT: PromptContextViewSpec(
        name=PromptContextView.FINAL_RESULT,
        target=PromptTarget.PERSONA,
        source_requirement=PromptContextSourceRequirement.CONFIGURED_PERSONA,
        allowed_slot_names=frozenset(
            {
                "system.global",
                "system.base",
                "extension.system",
                "persona.prompt",
                "persona.segments",
                "persona.summary",
                "persona.begin_dialogs",
                "input.text",
                "input.quoted_text",
                "input.visible_reply_material",
                "conversation.history",
                "conversation.group_recent",
                "conversation.pending_execution_continuity",
                "memory.topic_state",
                "memory.short_term",
                "memory.persona_state",
                "session.datetime",
                "session.user_info",
            }
        ),
        history_turns=6,
        history_limit_reason="final_result_history_limit",
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


def explicitly_requests_visual_context(pack: ContextPack) -> bool:
    """Return whether the current user text asks to inspect visual material."""

    text_slot = pack.get_slot("input.text")
    meta = text_slot.meta if text_slot is not None else {}
    text = meta.get("raw_text") if isinstance(meta, dict) else None
    if not isinstance(text, str):
        text = text_slot.value if text_slot is not None else ""
    return isinstance(text, str) and bool(_EXPLICIT_VISUAL_REQUEST.search(text))


def exclude_unrequested_ambient_visual_context(
    pack: ContextPack,
    *,
    include: bool,
) -> ContextPack:
    """Remove adapter-marked desktop snapshots before media enrichment/rendering."""

    if include or not any(
        slot.name in _AMBIENT_VISUAL_SLOT_NAMES
        and isinstance(slot.value, list)
        and any(_is_ambient_visual_record(record) for record in slot.value)
        for slot in pack.slots.values()
    ):
        return pack

    projected = ContextPack(
        slots=deepcopy(pack.slots),
        provider_request_ref=pack.provider_request_ref,
        meta=deepcopy(pack.meta),
    )
    ambient_refs = _ambient_visual_refs(projected)
    for slot_name in _AMBIENT_VISUAL_SLOT_NAMES:
        slot = projected.get_slot(slot_name)
        if slot is None or not isinstance(slot.value, list):
            continue
        retained = [
            record for record in slot.value if not _is_ambient_visual_record(record)
        ]
        if retained:
            slot.value = retained
            if "count" in slot.meta:
                slot.meta["count"] = len(retained)
        else:
            projected.slots.pop(slot_name, None)

    for slot_name in ("input.explicit_content_parts", "input.media_content_parts"):
        explicit_parts = projected.get_slot(slot_name)
        if explicit_parts is None or not isinstance(explicit_parts.value, list):
            continue
        retained = [
            part
            for part in explicit_parts.value
            if _content_part_image_ref(part) not in ambient_refs
        ]
        if retained:
            explicit_parts.value = retained
            if "part_count" in explicit_parts.meta:
                explicit_parts.meta["part_count"] = len(retained)
        else:
            projected.slots.pop(explicit_parts.name, None)

    projected.meta["ambient_visual_context"] = "excluded_unrequested"
    return projected


def _is_ambient_visual_record(record: object) -> bool:
    return (
        isinstance(record, dict)
        and str(record.get("semantic_type", "")).strip().lower()
        == "desktop_snapshot"
    )


def _ambient_visual_refs(pack: ContextPack) -> set[str]:
    return {
        ref
        for name in _AMBIENT_VISUAL_SLOT_NAMES
        if (slot := pack.get_slot(name)) is not None and isinstance(slot.value, list)
        for record in slot.value
        if _is_ambient_visual_record(record)
        and isinstance((ref := record.get("ref")), str)
        and ref
    }


def _content_part_image_ref(part: object) -> str | None:
    if isinstance(part, dict):
        part_type = str(part.get("type", "")).strip().lower()
        if part_type == "image_url":
            image_url = part.get("image_url")
            ref = (
                image_url.get("url")
                if isinstance(image_url, dict)
                else image_url
            )
        elif part_type == "image":
            source = part.get("source")
            ref = (
                source.get("url") or source.get("data")
                if isinstance(source, dict)
                else None
            )
        else:
            return None
        return ref if isinstance(ref, str) else None

    image_url = getattr(part, "image_url", None)
    ref = getattr(image_url, "url", None)
    if isinstance(ref, str):
        return ref
    source = getattr(part, "source", None)
    ref = getattr(source, "url", None) or getattr(source, "data", None)
    return ref if isinstance(ref, str) else None


def project_prompt_context_view(
    pack: ContextPack,
    view: PromptContextView | str | None,
) -> ContextPack:
    """Create a view-local Pack without weakening later target projection."""

    spec = resolve_prompt_context_view(view)
    if spec is None:
        return pack
    ambient_visual_allowed = (
        spec.name not in {PromptContextView.TURN_PLAN, PromptContextView.OLV_STREAM}
        or explicitly_requests_visual_context(pack)
    )
    source_pack = exclude_unrequested_ambient_visual_context(
        pack,
        include=ambient_visual_allowed,
    )

    projected = ContextPack(
        provider_request_ref=source_pack.provider_request_ref,
        meta=deepcopy(source_pack.meta),
    )
    for slot in source_pack.slots.values():
        if spec.allows_slot(slot.name):
            projected.add_slot(slot)

    projected.meta["context_view"] = spec.name.value
    projected.meta["context_view_source_requirement"] = spec.source_requirement.value
    projected.meta["context_view_source_slot_names"] = sorted(source_pack.slots)
    projected.meta["context_view_selected_slot_names"] = sorted(projected.slots)
    return projected


__all__ = [
    "PromptContextSourceRequirement",
    "PromptContextView",
    "PromptContextViewSpec",
    "explicitly_requests_visual_context",
    "exclude_unrequested_ambient_visual_context",
    "project_prompt_context_view",
    "resolve_prompt_context_view",
]
