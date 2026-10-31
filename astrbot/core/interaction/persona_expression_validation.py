"""Validation contract shared by Persona expression and stream protocols."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from astrbot import logger
from astrbot.core.plugin_admission import is_hard_contribution

from .effects import PersonaEffectSpec
from .persona_expression_types import (
    PERSONA_TENDENCY_DIMENSIONS,
    InteractionExpressionError,
    PersonaExpressionRequest,
    PersonaExpressionResult,
    PersonaExpressionSegment,
    clamp_persona_tendency_value,
)
from .types import PersonalResponseAction


def allowed_persona_turn_actions(
    req: PersonaExpressionRequest,
) -> tuple[PersonalResponseAction, ...]:
    if not req.require_turn_action:
        return (PersonalResponseAction.REPLY,)
    if req.allow_silent:
        return (
            PersonalResponseAction.REPLY,
            PersonalResponseAction.SILENT,
        )
    return (PersonalResponseAction.REPLY,)


def validated_persona_tendency(payload: dict[str, Any]) -> dict[str, int]:
    tendency = payload.get("tendency")
    if not isinstance(tendency, dict) or set(tendency) != set(
        PERSONA_TENDENCY_DIMENSIONS
    ):
        raise InteractionExpressionError("invalid_persona_tendency")
    normalized: dict[str, int] = {}
    for dimension in PERSONA_TENDENCY_DIMENSIONS:
        value = tendency[dimension]
        if isinstance(value, bool) or not isinstance(value, int):
            raise InteractionExpressionError("invalid_persona_tendency")
        normalized[dimension] = clamp_persona_tendency_value(value)
    return normalized


def validated_persona_segment(
    payload: object,
    *,
    discard_invalid_actions: bool = False,
) -> PersonaExpressionSegment:
    if not isinstance(payload, dict):
        raise InteractionExpressionError("invalid_persona_segment")
    if set(payload) != {"speech", "actions", "tendency"}:
        raise InteractionExpressionError("invalid_persona_segment_fields")
    speech = payload.get("speech")
    if not isinstance(speech, str):
        raise InteractionExpressionError("invalid_persona_speech")
    actions = payload.get("actions")
    if not isinstance(actions, list) or any(
        not isinstance(action, str) or not action.strip()
        for action in actions
    ):
        if not discard_invalid_actions:
            raise InteractionExpressionError("invalid_persona_actions")
        logger.warning(
            "Persona segment action hints rejected; ignoring malformed actions"
        )
        actions = []
    return PersonaExpressionSegment(
        speech=speech,
        actions=[action.strip() for action in actions],
        tendency=validated_persona_tendency(payload),
    )


def validated_persona_segments(
    payload: dict[str, Any],
) -> list[PersonaExpressionSegment]:
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise InteractionExpressionError("invalid_persona_segments")
    return [validated_persona_segment(segment) for segment in segments]


def validate_persona_expression_result(
    req: PersonaExpressionRequest,
    result: PersonaExpressionResult,
    *,
    effects: Sequence[PersonaEffectSpec] = (),
) -> None:
    if not isinstance(result.segments, list):
        raise InteractionExpressionError("invalid_persona_segments")
    for segment in result.segments:
        if not isinstance(segment, PersonaExpressionSegment):
            raise InteractionExpressionError("invalid_persona_segment")
        if not isinstance(segment.speech, str):
            raise InteractionExpressionError("invalid_persona_speech")
        if not isinstance(segment.actions, list) or any(
            not isinstance(action, str) or not action.strip()
            for action in segment.actions
        ):
            raise InteractionExpressionError("invalid_persona_actions")
        if not isinstance(segment.tendency, dict):
            raise InteractionExpressionError("invalid_persona_tendency")
        if set(segment.tendency) != set(PERSONA_TENDENCY_DIMENSIONS):
            raise InteractionExpressionError("invalid_persona_tendency")
        for dimension, value in segment.tendency.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise InteractionExpressionError("invalid_persona_tendency")
            segment.tendency[dimension] = clamp_persona_tendency_value(value)

    action = result.turn_action
    if not isinstance(action, PersonalResponseAction):
        raise InteractionExpressionError("missing_personal_response_action")
    if not req.require_turn_action and action is not PersonalResponseAction.REPLY:
        raise InteractionExpressionError("disallowed_personal_response_action")
    if action is PersonalResponseAction.SILENT:
        if not req.allow_silent:
            raise InteractionExpressionError("disallowed_personal_response_action")
        if (
            result.segments
            or result.effect_calls
            or result.metadata.get("effect_parse_issues")
        ):
            raise InteractionExpressionError("invalid_silent_personal_response")
        return
    if not result.speech.strip() and not (
        req.allow_empty
        or (req.allow_action_only and any(segment.actions for segment in result.segments))
    ):
        raise InteractionExpressionError("empty_output")
    required_effects = [
        effect
        for effect in effects
        if isinstance(effect, PersonaEffectSpec)
        and effect.enabled
        and is_hard_contribution(effect.metadata)
    ]
    if not required_effects:
        return

    calls_by_name: dict[str, int] = {}
    calls_by_segment: dict[tuple[str, int], int] = {}
    for call in result.effect_calls:
        calls_by_name[call.name] = calls_by_name.get(call.name, 0) + 1
        if call.segment_index is not None:
            key = (call.name, call.segment_index)
            calls_by_segment[key] = calls_by_segment.get(key, 0) + 1
    parse_issue_names = {
        str(issue.get("name", "") or "").strip()
        for issue in (result.metadata.get("effect_parse_issues", []) or [])
        if isinstance(issue, dict)
    }
    for effect in required_effects:
        if effect.metadata.get("required_per_segment") is True:
            for segment_index in range(len(result.segments)):
                call_count = calls_by_segment.get((effect.name, segment_index), 0)
                if call_count == 0:
                    reason = (
                        "invalid_required_persona_effect"
                        if effect.name in parse_issue_names
                        else "missing_required_persona_effect"
                    )
                    raise InteractionExpressionError(
                        reason,
                        f"required persona effect is not valid: {effect.name} "
                        f"for segment {segment_index}",
                    )
                if (
                    effect.metadata.get("exactly_one_per_segment") is True
                    and call_count != 1
                ):
                    raise InteractionExpressionError(
                        "required_persona_effect_count",
                        f"required persona effect must occur exactly once "
                        f"for segment {segment_index}: {effect.name}",
                    )
            continue
        call_count = calls_by_name.get(effect.name, 0)
        if call_count == 0:
            reason = (
                "invalid_required_persona_effect"
                if effect.name in parse_issue_names
                else "missing_required_persona_effect"
            )
            raise InteractionExpressionError(
                reason,
                f"required persona effect is not valid: {effect.name}",
            )
        if effect.metadata.get("exactly_one_per_segment") is True and call_count != 1:
            raise InteractionExpressionError(
                "required_persona_effect_count",
                f"required persona effect must occur exactly once: {effect.name}",
            )


@dataclass(frozen=True, slots=True)
class PersonaStreamValidationContract:
    """Callbacks required by the stream parser without importing the agent."""

    allowed_turn_actions: Callable[[
        PersonaExpressionRequest,
    ], tuple[PersonalResponseAction, ...]] = allowed_persona_turn_actions
    validate_segment: Callable[..., PersonaExpressionSegment] = validated_persona_segment
    validate_result: Callable[..., None] = validate_persona_expression_result


__all__ = [
    "PersonaStreamValidationContract",
    "allowed_persona_turn_actions",
    "validate_persona_expression_result",
    "validated_persona_segment",
    "validated_persona_segments",
    "validated_persona_tendency",
]
