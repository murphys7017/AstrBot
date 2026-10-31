from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

from astrbot.core.plugin_admission import is_hard_contribution

from .effects import PersonaEffectSpec, normalize_persona_effect_parameters_schema
from .persona_expression_types import PERSONA_TENDENCY_DIMENSIONS
from .types import PersonalResponseAction

_PERSONA_SEGMENT_GUIDANCE = "按说话时动作或情绪变化分段；没有状态变化时不必拆段，不为凑段数重复文本或添加动作。"
_PERSONA_ACTION_GUIDANCE = (
    "actions 是同段同时发生的简单动作意图数组，可含自然方向；先后配合话语的动作须拆段。"
    "不写角度、坐标、速度、时长或插件 effect 数据。"
)
_PERSONA_TENDENCY_GUIDANCE = "tendency 只评估这一段内容引起的情绪强度，不计入之前积累的情绪，不照抄参考状态数值。"


def build_persona_expression_tool_parameters(
    *,
    allowed_turn_actions: Sequence[PersonalResponseAction] | None = None,
) -> dict[str, Any]:
    segment_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "speech": {
                "type": "string",
                "description": "本段用户可见表达文本；按动作或状态变化进行分段。",
            },
            "actions": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": _PERSONA_ACTION_GUIDANCE,
            },
            "tendency": {
                "type": "object",
                "description": _PERSONA_TENDENCY_GUIDANCE,
                "additionalProperties": False,
                "properties": {
                    dimension: {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 10,
                    }
                    for dimension in PERSONA_TENDENCY_DIMENSIONS
                },
                "required": list(PERSONA_TENDENCY_DIMENSIONS),
            },
        },
        "required": ["speech", "actions", "tendency"],
    }
    properties: dict[str, Any] = {
        "segments": {
            "type": "array",
            "items": segment_schema,
            "minItems": 0,
            "description": _PERSONA_SEGMENT_GUIDANCE,
        },
    }
    actions = [
        action.value
        for action in (
            allowed_turn_actions
            if allowed_turn_actions is not None
            else (PersonalResponseAction.REPLY,)
        )
    ]
    properties["turn_action"] = {
        "type": "string",
        "enum": actions,
        "description": "Allowed turn_action values: "
        + "; ".join(
            {
                "reply": "complete the visible response in Personal",
                "silent": "emit no visible response; segments must be empty",
            }[action]
            for action in actions
        ),
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": copy.deepcopy(properties),
        "required": ["turn_action", "segments"],
    }


def build_persona_effect_batch_tool_parameters(
    effects: Sequence[PersonaEffectSpec] = (),
    *,
    allow_silent: bool = False,
) -> dict[str, Any]:
    enabled_effects = sorted(
        (
            effect
            for effect in effects
            if isinstance(effect, PersonaEffectSpec) and effect.enabled
        ),
        key=lambda effect: effect.name,
    )
    properties: dict[str, Any] = {
        "effect_calls": {
            "type": "array",
            "items": False,
            "description": "只包含本轮注册 effect 的调用；可以为空数组。",
        },
    }
    effect_schemas = []
    for effect in enabled_effects:
        per_segment = effect.metadata.get("required_per_segment") is True
        effect_schemas.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {
                        "const": effect.name,
                        "description": effect.description,
                    },
                    "arguments": normalize_persona_effect_parameters_schema(
                        effect.parameters
                    ),
                    "segment_index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "0-based index into segments for this effect call.",
                    },
                },
                "required": [
                    "name",
                    "arguments",
                    *(["segment_index"] if per_segment else []),
                ],
            }
        )
    if effect_schemas:
        properties["effect_calls"] = {
            "type": "array",
            "items": {"oneOf": copy.deepcopy(effect_schemas)},
            "description": "只包含本轮注册 effect 的调用；可以为空数组。",
        }
        required_effect_count = sum(
            1 for effect in enabled_effects if is_hard_contribution(effect.metadata)
        )
        if required_effect_count and not allow_silent:
            required_names = [
                effect.name
                for effect in enabled_effects
                if is_hard_contribution(effect.metadata)
            ]
            if required_names:
                properties["effect_calls"]["description"] = (
                    "Required Persona Effects: "
                    + ", ".join(required_names)
                    + ". For required_per_segment effects, provide one call for each "
                    "segments entry with its 0-based segment_index. Always provide schema-valid "
                    "and complete arguments. Semantic labels or annotations do not "
                    "replace an execution shape or other required fields defined by "
                    "the effect schema; do not invent default values."
                )
        elif required_effect_count:
            properties["effect_calls"]["description"] = (
                "Required Persona Effects apply to non-silent replies. For silent, "
                "return an empty effect_calls array."
            )
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": copy.deepcopy(properties),
        "required": ["effect_calls"],
    }


__all__ = [
    "build_persona_effect_batch_tool_parameters",
    "build_persona_expression_tool_parameters",
]
