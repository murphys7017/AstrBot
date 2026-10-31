"""
Persona prompt parsing helpers.

This module parses the legacy free-form persona prompt into structured segments.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

PERSONA_MOTION_FIELDS: tuple[str, ...] = (
    "core_persona",
    "expression_habits",
    "emotional_continuity",
    "interaction_reactions",
    "personality_state_machine",
    "stable_rules",
    "unparsed_sections",
)

_SECTION_ALIASES = {
    "身份": "identity",
    "身份与关系": "identity",
    "核心人格": "core_persona",
    "核心性格": "core_persona",
    "性格": "core_persona",
    "性格特征": "core_persona",
    "性格倾向": "core_persona",
    "personality": "core_persona",
    "personalitytraits": "core_persona",
    "表现习惯": "expression_habits",
    "动作偏好": "expression_habits",
    "肢体表现": "expression_habits",
    "expressionhabits": "expression_habits",
    "情绪表达": "emotional_continuity",
    "情绪与连续性": "emotional_continuity",
    "示例语气": "tone_examples",
    "对话风格": "dialogue_style",
    "表达方式": "dialogue_style",
    "互动反应": "interaction_reactions",
    "渐进式理解": "progressive_understanding",
    "认知偏差(rationalbias)": "rational_bias",
    "memoryhooks(持续兴趣)": "memory_hooks",
    "personalitydrives": "personality_drives",
    "personalitystatemachine": "personality_state_machine",
    "状态模式": "personality_state_machine",
    "relationshiplayer": "relationship_layer",
    "与用户的关系": "relationship_layer",
    "interactionmemory": "interaction_memory",
    "稳定规则": "stable_rules",
}

_INTERACTION_REACTION_ALIASES = {
    "被夸": "praised",
    "被取外号": "nickname",
    "暧昧/关心": "affection_or_care",
    "被关心": "affection_or_care",
}

_STATE_MACHINE_ALIASES = {
    "normal": "normal",
    "teaching": "teaching",
    "mocking": "mocking",
    "curious": "curious",
    "tsundere": "tsundere",
    "guarded": "guarded",
    "affectionate": "affectionate",
    "reflective": "reflective",
}


def _empty_persona_segments() -> dict[str, object]:
    return {
        "identity": [],
        "core_persona": [],
        "expression_habits": [],
        "emotional_continuity": [],
        "tone_examples": [],
        "dialogue_style": [],
        "interaction_reactions": {
            "praised": [],
            "nickname": [],
            "affection_or_care": [],
            "other": [],
        },
        "progressive_understanding": [],
        "rational_bias": [],
        "memory_hooks": [],
        "personality_drives": [],
        "personality_state_machine": {
            "normal": "",
            "teaching": "",
            "mocking": "",
            "curious": "",
            "tsundere": "",
            "guarded": "",
            "affectionate": "",
            "reflective": "",
        },
        "relationship_layer": {
            "current_affinity": None,
            "traits": [],
        },
        "interaction_memory": [],
        "stable_rules": [],
        "unparsed_sections": [],
    }


PERSONA_SUMMARY_FIELDS: tuple[str, ...] = tuple(_empty_persona_segments())


def _canonicalize_title(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^#{1,6}\s+", "", value).rstrip("#").strip()
    if value.startswith("**") and value.endswith("**"):
        value = value[2:-2].strip()
    value = value.replace("（", "(").replace("）", ")")
    value = value.rstrip("：:")
    value = value.replace(" ", "")
    return value.lower()


def normalize_section_name(title: str) -> str | None:
    """Map a raw section title to a stable internal key."""
    return _SECTION_ALIASES.get(_canonicalize_title(title))


def _normalize_interaction_reaction_name(title: str) -> str | None:
    title = _parse_content_line(title)
    label = re.split(r"[：:]", title, maxsplit=1)[0]
    return _INTERACTION_REACTION_ALIASES.get(label.strip())


def _parse_content_line(line: str) -> str:
    value = line.strip()
    if value.startswith(("- ", "* ", "+ ")):
        value = value[2:].strip()

    if value.startswith("「") and value.endswith("」") and len(value) >= 2:
        value = value[1:-1].strip()

    return value


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _parse_state_machine_line(line: str) -> tuple[str, str] | None:
    raw = _parse_content_line(line)
    if "：" in raw:
        key, value = raw.split("：", 1)
    elif ":" in raw:
        key, value = raw.split(":", 1)
    else:
        return None

    normalized_key = _STATE_MACHINE_ALIASES.get(key.strip().lower())
    if not normalized_key:
        return None

    return normalized_key, value.strip()


def _parse_relationship_affinity(line: str) -> int | None:
    raw = _parse_content_line(line)
    if not raw.startswith("当前关系值"):
        return None

    match = re.search(r"(\d+)", raw)
    if not match:
        return None

    return int(match.group(1))


def parse_legacy_persona_prompt(prompt: str) -> dict[str, object]:
    """Parse the legacy free-form persona prompt into normalized segments."""
    segments = _empty_persona_segments()
    if not prompt or not prompt.strip():
        return segments

    current_section: str | None = None
    current_subsection: str | None = None

    for raw_line in prompt.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        section_name = normalize_section_name(line)
        if section_name:
            current_section = section_name
            current_subsection = None
            continue

        # An explicit unknown heading starts a new section. Preserve it without
        # assigning its contents to the previously recognized persona field.
        if re.match(r"^#{1,6}\s+", line):
            current_section = None
            current_subsection = None
            _append_unique(segments["unparsed_sections"], line)
            continue

        if current_section == "interaction_reactions":
            reaction_line = _parse_content_line(line)
            subsection = _normalize_interaction_reaction_name(reaction_line)
            if subsection:
                current_subsection = subsection
                parts = re.split(r"[：:]", reaction_line, maxsplit=1)
                value = parts[1] if len(parts) == 2 else ""
                parsed_value = _parse_content_line(value)
                if parsed_value:
                    _append_unique(
                        segments["interaction_reactions"][current_subsection],
                        parsed_value,
                    )
                continue
            # Other reaction rules are independent of the last named reaction.
            # A list item or label begins its own rule; unlabelled continuation
            # lines can still belong to the legacy named subsection.
            if line.startswith(("- ", "* ", "+ ")) or re.match(
                r"^[^：:「“\"]{1,32}[：:]", reaction_line
            ):
                current_subsection = None
            if current_subsection is None:
                _append_unique(segments["interaction_reactions"]["other"], reaction_line)
                continue

        if current_section == "personality_state_machine":
            state_pair = _parse_state_machine_line(line)
            if state_pair:
                state_key, state_value = state_pair
                segments["personality_state_machine"][state_key] = state_value
            else:
                _append_unique(segments["unparsed_sections"], line)
            continue

        if current_section == "relationship_layer":
            affinity = _parse_relationship_affinity(line)
            if affinity is not None:
                segments["relationship_layer"]["current_affinity"] = affinity
                continue

            if line in {"行为特征：", "行为特征:"}:
                current_subsection = "traits"
                continue

            value = _parse_content_line(line)
            if value:
                _append_unique(segments["relationship_layer"]["traits"], value)
            continue

        if current_section == "interaction_reactions" and current_subsection:
            value = _parse_content_line(line)
            if value:
                _append_unique(
                    segments["interaction_reactions"][current_subsection],
                    value,
                )
            continue

        if current_section is None:
            _append_unique(segments["unparsed_sections"], line)
            continue

        if current_section in {
            "identity",
            "core_persona",
            "expression_habits",
            "emotional_continuity",
            "tone_examples",
            "dialogue_style",
            "progressive_understanding",
            "rational_bias",
            "memory_hooks",
            "personality_drives",
            "interaction_memory",
            "stable_rules",
        }:
            value = _parse_content_line(line)
            if value:
                _append_unique(segments[current_section], value)
            continue

        _append_unique(segments["unparsed_sections"], line)

    return finalize_persona_segments(segments)


def finalize_persona_segments(parsed: dict[str, object]) -> dict[str, object]:
    """Return a stable, isolated persona segments structure."""
    base = _empty_persona_segments()
    merged = deepcopy(base)

    for key, value in parsed.items():
        if key not in merged:
            continue
        if isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key].update(value)
        else:
            merged[key] = value

    return merged


def build_persona_prompt_projection(segments: Mapping[str, Any]) -> dict[str, Any]:
    """Keep authored persona rules intact, removing only empty structure.

    Lightweight calls save context through their history/material views. A fixed
    line limit or a heading whitelist must not silently change their persona.
    """
    def compact(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: cleaned for key, item in value.items()
                if (cleaned := compact(item)) not in (None, "", [], {})
            }
        if isinstance(value, (list, tuple)):
            return [
                cleaned for item in value
                if (cleaned := compact(item)) not in (None, "", [], {})
            ]
        return deepcopy(value)

    return compact(segments)


def build_persona_motion_prompt(prompt: str) -> str:
    """Project authored personality and performance rules with the shared parser.

    Free-form personas have no separately identifiable core; keep their original
    text instead of inventing a personality or silently disabling reactions.
    """
    segments = parse_legacy_persona_prompt(prompt)
    if not segments["core_persona"]:
        return prompt.strip()
    selected = build_persona_prompt_projection({
        key: segments[key]
        for key in PERSONA_MOTION_FIELDS
    })

    def lines(value: Any):
        if isinstance(value, dict):
            for key, item in value.items():
                yield f"{key}:"
                yield from lines(item)
        elif isinstance(value, list):
            for item in value:
                yield from lines(item)
        else:
            yield str(value)

    return "\n".join(lines(selected))
