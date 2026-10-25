"""Prompt extension types for plugin-contributed prompt context."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

PromptExtensionMount = Literal[
    "system",
    "context",
    "input",
    "conversation",
    "memory",
    "capability",
]

PromptExtensionValueKind = Literal["text", "mapping", "sequence"]

PROMPT_EXTENSION_MOUNTS: tuple[PromptExtensionMount, ...] = (
    "system",
    "context",
    "input",
    "conversation",
    "memory",
    "capability",
)

PROMPT_EXTENSION_VALUE_KINDS: tuple[PromptExtensionValueKind, ...] = (
    "text",
    "mapping",
    "sequence",
)


def extension_visible_in_context_view(
    mount: str, meta: Mapping[str, Any], context_view: str | None,
) -> bool:
    """Apply the same context opt-in at collection and rendering boundaries."""
    if context_view is None or mount != "context":
        return True
    views = meta.get("context_views", ())
    return isinstance(views, (list, tuple, set, frozenset)) and context_view in views


@dataclass(slots=True)
class PromptExtension:
    """Structured prompt contribution produced by a plugin collector."""

    plugin_id: str
    mount: PromptExtensionMount
    title: str | None = None
    value: Any = None
    value_kind: PromptExtensionValueKind = "mapping"
    order: int = 100
    meta: dict[str, Any] = field(default_factory=dict)
