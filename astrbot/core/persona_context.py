"""Runtime-owned static persona context projection.

This module is the neutral boundary between persona resolution, Runtime, and
Prompt collection.  It contains only core-owned projection types so importing
Runtime does not initialize the ``astrbot.core.prompt`` package.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from astrbot.core import logger
from astrbot.core.persona_resources import CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT
from astrbot.core.persona_segments import (
    build_persona_prompt_projection,
    parse_legacy_persona_prompt,
)

if TYPE_CHECKING:
    from astrbot.core.persona_resolution import PersonaResolution
else:
    PersonaResolution = Any


class PersonaContextSlotLike(Protocol):
    """Structural view shared by core and Prompt persona slot adapters."""

    name: str
    value: Any
    meta: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PersonaContextSlot:
    """Prompt-independent projection of one static persona context slot."""

    name: str
    value: Any
    category: str
    source: str
    llm_exposure: str = "allowed"
    placement: str = "middle"
    render_mode: str = "raw"
    priority: int = 50
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "meta", deepcopy(self.meta))


@dataclass(frozen=True, slots=True)
class PersonaContextSeed:
    """Immutable static Persona slots shared by one Runtime scope."""

    slots: tuple[PersonaContextSlot, ...]
    scope_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.slots, tuple):
            raise TypeError("slots must be a tuple")
        if any(not isinstance(slot, PersonaContextSlot) for slot in self.slots):
            raise TypeError("slots must contain PersonaContextSlot values")
        object.__setattr__(
            self,
            "slots",
            tuple(deepcopy(slot) for slot in self.slots),
        )
        normalized_scope_key = str(self.scope_key or "").strip()
        if not normalized_scope_key:
            raise ValueError("scope_key is required")
        object.__setattr__(self, "scope_key", normalized_scope_key)

    def materialize_slots(self) -> list[PersonaContextSlot]:
        """Return an isolated projection for one Prompt context build."""
        return deepcopy(list(self.slots))


def build_persona_slots_from_resolution(
    resolution: PersonaResolution,
) -> list[PersonaContextSlot]:
    """Project one resolved persona into the canonical static slots."""
    slots: list[PersonaContextSlot] = []
    persona_id = resolution.persona_id
    persona = resolution.persona
    force_applied_persona_id = resolution.force_applied_persona_id
    use_webchat_special_default = resolution.use_webchat_special_default

    if not persona and not use_webchat_special_default:
        logger.debug("No persona resolved (persona_id=%s)", persona_id)
        return slots

    if use_webchat_special_default:
        slots.append(
            PersonaContextSlot(
                name="persona.prompt",
                value=CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT,
                category="persona",
                source="persona_mgr",
                meta={
                    "persona_id": persona_id,
                    "force_applied": force_applied_persona_id is not None,
                    "use_webchat_special_default": True,
                },
            )
        )
    elif persona and "prompt" in persona and persona["prompt"]:
        slots.append(
            PersonaContextSlot(
                name="persona.prompt",
                value=persona["prompt"],
                category="persona",
                source="persona_mgr",
                meta={
                    "persona_id": persona_id,
                    "force_applied": force_applied_persona_id is not None,
                },
            )
        )

    prompt_slot = next(
        (slot for slot in slots if slot.name == "persona.prompt"), None
    )
    if (
        prompt_slot
        and isinstance(prompt_slot.value, str)
        and prompt_slot.value.strip()
    ):
        persona_segments = parse_legacy_persona_prompt(prompt_slot.value)
        slots.extend(
            (
                PersonaContextSlot(
                    name="persona.segments",
                    value=persona_segments,
                    category="persona",
                    source="persona_parser",
                    meta={
                        "persona_id": persona_id,
                        "source_slot": "persona.prompt",
                        "parser": "legacy_prompt_v1",
                    },
                ),
                PersonaContextSlot(
                    name="persona.summary",
                    value=build_persona_prompt_projection(persona_segments),
                    category="persona",
                    source="persona_parser",
                    meta={
                        "persona_id": persona_id,
                        "source_slot": "persona.segments",
                        "format": "persona_summary_v1",
                    },
                ),
            )
        )

    if (
        persona
        and "_begin_dialogs_processed" in persona
        and persona["_begin_dialogs_processed"]
    ):
        slots.append(
            PersonaContextSlot(
                name="persona.begin_dialogs",
                value=persona["_begin_dialogs_processed"],
                category="persona",
                source="persona_mgr",
                meta={
                    "persona_id": persona_id,
                    "raw_begin_dialogs": persona.get("begin_dialogs", []),
                },
            )
        )

    for slot_name in ("tools", "skills"):
        if persona and slot_name in persona:
            slots.append(
                PersonaContextSlot(
                    name=f"persona.{slot_name}_whitelist",
                    value=persona[slot_name],
                    category="persona",
                    source="persona_mgr",
                    meta={
                        "persona_id": persona_id,
                        "semantics": "None=all, []=none, [...]=specific",
                    },
                )
            )

    if use_webchat_special_default:
        for slot in slots:
            slot.meta["use_webchat_special_default"] = True
    return slots


def build_persona_context_seed(
    resolution: PersonaResolution,
    *,
    scope_key: str,
) -> PersonaContextSeed | None:
    """Build a Runtime-owned immutable static Persona seed."""
    slots = build_persona_slots_from_resolution(resolution)
    if not any(slot.name.startswith("persona.") for slot in slots):
        return None
    return PersonaContextSeed(
        slots=tuple(slots),
        scope_key=scope_key,
    )


__all__ = [
    "PersonaContextSlotLike",
    "PersonaContextSlot",
    "PersonaContextSeed",
    "build_persona_context_seed",
    "build_persona_slots_from_resolution",
]
