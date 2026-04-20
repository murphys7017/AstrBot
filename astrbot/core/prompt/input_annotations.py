"""Optional sidecar annotations for platform-provided input semantics."""

from __future__ import annotations

INPUT_ITEM_ANNOTATIONS_EXTRA_KEY = "prompt_input_item_annotations"
INPUT_TEXT_ANNOTATION_KEY = "input.text"
INPUT_QUOTED_TEXT_ANNOTATION_KEY = "input.quoted_text"

SUPPORTED_INPUT_ANNOTATION_FIELDS: tuple[str, ...] = (
    "semantic_type",
    "explanation",
    "explanation_source",
    "context_role",
)


def build_message_annotation_key(index: int) -> str:
    """Build the sidecar key for a top-level message component."""
    return f"message[{index}]"


def build_reply_chain_annotation_key(message_index: int, chain_index: int) -> str:
    """Build the sidecar key for a component inside a reply chain."""
    return f"message[{message_index}].reply.chain[{chain_index}]"


def normalize_input_annotations(raw: object) -> dict[str, dict[str, str]]:
    """Normalize a loose event-extra payload into a safe annotation mapping."""
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            continue
        annotation = extract_input_annotation_fields(value)
        if annotation:
            normalized[key] = annotation
    return normalized


def extract_input_annotation_fields(raw: object) -> dict[str, str]:
    """Keep only supported string fields from a raw annotation payload."""
    if not isinstance(raw, dict):
        return {}

    annotation: dict[str, str] = {}
    for field in SUPPORTED_INPUT_ANNOTATION_FIELDS:
        value = raw.get(field)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                annotation[field] = normalized
    return annotation


def copy_input_annotation_fields(raw: object) -> dict[str, str]:
    """Return a shallow copy of supported annotation fields."""
    return dict(extract_input_annotation_fields(raw))


__all__ = [
    "INPUT_ITEM_ANNOTATIONS_EXTRA_KEY",
    "INPUT_QUOTED_TEXT_ANNOTATION_KEY",
    "INPUT_TEXT_ANNOTATION_KEY",
    "SUPPORTED_INPUT_ANNOTATION_FIELDS",
    "build_message_annotation_key",
    "build_reply_chain_annotation_key",
    "copy_input_annotation_fields",
    "extract_input_annotation_fields",
    "normalize_input_annotations",
]
