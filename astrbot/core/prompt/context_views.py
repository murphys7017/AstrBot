"""Invocation-local context views applied before PromptTarget projection."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum

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
    "PromptContextSourceRequirement",
    "PromptContextView",
    "PromptContextViewSpec",
    "project_prompt_context_view",
    "resolve_prompt_context_view",
]
