from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from astrbot.core.json_parsing import coerce_json_value, extract_json_object
from astrbot.core.output_contract import CompiledOutputContract, OutputContract

from .effects import (
    PersonaEffectCall,
    PersonaEffectSpec,
    parse_persona_effect_calls_with_issues,
)
from .persona_expression_contract import PERSONA_EFFECT_BATCH_TOOL_NAME
from .persona_expression_schema import build_persona_expression_tool_parameters
from .persona_expression_types import (
    InteractionExpressionError,
    PersonaExpressionResult,
    PersonaExpressionSegment,
)
from .persona_expression_validation import validated_persona_segments
from .structured_output import parse_persona_text, restore_native_optional_fields
from .types import PersonalResponseAction


def coerce_tool_call_payload(tool_arg: object) -> dict[str, Any] | None:
    payload = coerce_json_value(tool_arg)
    return payload if isinstance(payload, dict) else None


def build_persona_expression_result_from_payload(
    payload: dict[str, Any],
) -> PersonaExpressionResult:
    expected_fields = {"turn_action", "segments"}
    if set(payload) != expected_fields:
        raise InteractionExpressionError("invalid_persona_expression_fields")
    segments = validated_persona_segments(payload)
    metadata: dict[str, Any] = {}
    raw_action = payload.get("turn_action")
    try:
        turn_action = (
            PersonalResponseAction(str(raw_action))
            if raw_action is not None
            else None
        )
    except ValueError:
        turn_action = None
        metadata["personal_response_action_parse_issue"] = str(raw_action)
    return PersonaExpressionResult(
        segments=segments,
        metadata=metadata,
        turn_action=turn_action,
    )


def extract_persona_expression_result(
    text: object,
    *,
    llm_response=None,
    output_contract: OutputContract | None = None,
    compiled_output_contract: CompiledOutputContract | None = None,
    output_format: str = "legacy",
) -> PersonaExpressionResult:
    """Parse the configured Persona expression protocol into a canonical result."""
    preferred = (
        output_contract.preferred_tool_name
        if isinstance(output_contract, OutputContract)
        else None
    )
    strict_tool_call = (
        isinstance(output_contract, OutputContract)
        and output_contract.mode == "tool_call"
        and not output_contract.allow_text_fallback
    )
    strict_json_object = (
        isinstance(output_contract, OutputContract)
        and output_contract.mode == "json_object"
        and output_contract.strict
    )
    # 1. Protocol tool call. Expression is exactly one terminal payload.
    if strict_tool_call and llm_response is not None:
        names = list(getattr(llm_response, "tools_call_name", []) or [])
        args = list(getattr(llm_response, "tools_call_args", []) or [])
        indexes = [index for index, name in enumerate(names) if name == preferred]
        if len(indexes) > 1:
            raise InteractionExpressionError(
                "duplicate_persona_expression_tool_call",
                "persona_expression tool call must occur exactly once",
            )
        if indexes:
            index = indexes[0]
            payload = coerce_tool_call_payload(args[index]) if index < len(args) else None
            if payload is not None:
                return build_persona_expression_result_from_payload(payload)
    if strict_tool_call:
        raise InteractionExpressionError(
            "missing_persona_expression_tool_call",
            "persona_expression tool call missing",
        )
    # 2. Configured text format fallback
    if output_format in {"json", "xml", "markdown"}:
        try:
            payload = parse_persona_text(
                text,
                output_format,
                schema=(
                    output_contract.schema
                    if isinstance(output_contract, OutputContract)
                    else build_persona_expression_tool_parameters()
                ),
            )
        except ValueError as exc:
            raise InteractionExpressionError(
                "invalid_persona_expression_format",
                f"invalid {output_format} persona expression: {exc}",
            ) from exc
        if (
            output_format == "json"
            and isinstance(output_contract, OutputContract)
            and output_contract.schema is not None
            and output_contract.schema
        ):
            payload = restore_native_optional_fields(payload, output_contract.schema)
    else:
        payload = extract_json_object(text)
    if isinstance(payload, dict):
        return build_persona_expression_result_from_payload(payload)
    if strict_tool_call or strict_json_object or output_format in {"xml", "markdown"}:
        raise InteractionExpressionError(
            "invalid_persona_expression_json",
            "persona expression must be a single JSON object",
        )
    # 3. 纯文本兼容
    return PersonaExpressionResult(
        segments=[
            PersonaExpressionSegment(
                speech=(str(text or "")).strip(),
            )
        ],
        turn_action=PersonalResponseAction.REPLY,
    )


def extract_persona_effect_calls(
    llm_response,
    effects: Sequence[PersonaEffectSpec],
    *,
    segment_count: int | None,
) -> tuple[list[PersonaEffectCall], dict[str, Any]]:
    enabled_effects = [
        effect
        for effect in effects
        if isinstance(effect, PersonaEffectSpec) and effect.enabled
    ]
    if llm_response is None:
        if not enabled_effects:
            return [], {}
        raise InteractionExpressionError("missing_persona_effect_batch_tool_call")

    names = list(getattr(llm_response, "tools_call_name", []) or [])
    args = list(getattr(llm_response, "tools_call_args", []) or [])
    indexes = [
        index
        for index, name in enumerate(names)
        if name == PERSONA_EFFECT_BATCH_TOOL_NAME
    ]
    if not enabled_effects:
        if indexes:
            raise InteractionExpressionError(
                "unexpected_persona_effect_batch_tool_call",
                "persona_effect_batch was not registered for this turn",
            )
        return [], {}
    if not indexes:
        raise InteractionExpressionError(
            "missing_persona_effect_batch_tool_call",
            "persona_effect_batch tool call missing",
        )
    if len(indexes) != 1:
        raise InteractionExpressionError(
            "duplicate_persona_effect_batch_tool_call",
            "persona_effect_batch tool call must occur exactly once",
        )
    index = indexes[0]
    payload = coerce_tool_call_payload(args[index]) if index < len(args) else None
    if payload is None or set(payload) != {"effect_calls"}:
        raise InteractionExpressionError("invalid_persona_effect_batch")
    raw_effect_calls = coerce_json_value(payload.get("effect_calls"))
    if not isinstance(raw_effect_calls, list):
        raise InteractionExpressionError("invalid_persona_effect_batch")
    calls, issues = parse_persona_effect_calls_with_issues(
        raw_effect_calls,
        enabled_effects,
        segment_count=segment_count,
    )
    metadata = (
        {"effect_parse_issues": [issue.to_dict() for issue in issues]}
        if issues
        else {}
    )
    return calls, metadata


__all__ = [
    "PERSONA_EFFECT_BATCH_TOOL_NAME",
    "build_persona_expression_result_from_payload",
    "coerce_tool_call_payload",
    "extract_persona_effect_calls",
    "extract_persona_expression_result",
]
