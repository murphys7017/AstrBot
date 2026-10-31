from __future__ import annotations

from collections.abc import Sequence

from astrbot.core.agent.tool import ToolSet
from astrbot.core.output_contract import OutputContract
from astrbot.core.provider.output_contract_tools import (
    build_single_tool_set_from_contract,
)

from .effects import PersonaEffectSpec
from .persona_expression_schema import (
    build_persona_effect_batch_tool_parameters,
    build_persona_expression_tool_parameters,
)
from .types import PersonalResponseAction

PERSONA_EXPRESSION_TOOL_NAME = "persona_expression"
PERSONA_EFFECT_BATCH_TOOL_NAME = "persona_effect_batch"


def build_persona_expression_output_contract(
    *,
    allowed_turn_actions: Sequence[PersonalResponseAction] | None = None,
) -> OutputContract:
    return OutputContract(
        mode="tool_call",
        strict=True,
        schema=build_persona_expression_tool_parameters(
            allowed_turn_actions=allowed_turn_actions,
        ),
        preferred_tool_name=PERSONA_EXPRESSION_TOOL_NAME,
        allow_text_fallback=False,
    )


def build_persona_effect_batch_output_contract(
    effects: Sequence[PersonaEffectSpec],
    *,
    allow_silent: bool = False,
) -> OutputContract:
    return OutputContract(
        mode="tool_call",
        strict=True,
        schema=build_persona_effect_batch_tool_parameters(
            effects,
            allow_silent=allow_silent,
        ),
        preferred_tool_name=PERSONA_EFFECT_BATCH_TOOL_NAME,
        allow_text_fallback=False,
    )


def _enabled_persona_effects(
    effects: Sequence[PersonaEffectSpec],
) -> list[PersonaEffectSpec]:
    return [
        effect
        for effect in effects
        if isinstance(effect, PersonaEffectSpec) and effect.enabled
    ]


def _build_persona_effect_terminal_tools(
    effects: Sequence[PersonaEffectSpec],
    *,
    allow_silent: bool = False,
) -> ToolSet | None:
    if not _enabled_persona_effects(effects):
        return None
    contract = build_persona_effect_batch_output_contract(
        effects,
        allow_silent=allow_silent,
    )
    return build_single_tool_set_from_contract(
        contract,
        description="Return registered Persona Effect calls for this turn.",
    )


def _build_persona_expression_output_contract(
    output_format: str,
    *,
    allowed_turn_actions: Sequence[PersonalResponseAction] | None = None,
) -> OutputContract:
    """Build the output contract for the Persona expression channel only."""
    schema = build_persona_expression_tool_parameters(
        allowed_turn_actions=allowed_turn_actions,
    )
    if output_format == "tool_call":
        return OutputContract(
            mode="tool_call",
            strict=True,
            schema=schema,
            preferred_tool_name=PERSONA_EXPRESSION_TOOL_NAME,
            allow_text_fallback=False,
        )
    if output_format == "json":
        return OutputContract(
            mode="json_object",
            strict=True,
            schema=schema,
            allow_text_fallback=False,
        )
    return OutputContract(
        mode="text",
        strict=True,
        schema=schema,
        allow_text_fallback=False,
    )


__all__ = [
    "PERSONA_EFFECT_BATCH_TOOL_NAME",
    "PERSONA_EXPRESSION_TOOL_NAME",
    "build_persona_effect_batch_output_contract",
    "build_persona_expression_output_contract",
]
