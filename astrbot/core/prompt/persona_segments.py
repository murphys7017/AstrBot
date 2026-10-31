"""Compatibility exports for the canonical persona segment parser."""

from astrbot.core.persona_segments import (
    PERSONA_MOTION_FIELDS,
    PERSONA_SUMMARY_FIELDS,
    build_persona_motion_prompt,
    build_persona_prompt_projection,
    finalize_persona_segments,
    normalize_section_name,
    parse_legacy_persona_prompt,
)

__all__ = [
    "PERSONA_MOTION_FIELDS",
    "PERSONA_SUMMARY_FIELDS",
    "build_persona_motion_prompt",
    "build_persona_prompt_projection",
    "finalize_persona_segments",
    "normalize_section_name",
    "parse_legacy_persona_prompt",
]
