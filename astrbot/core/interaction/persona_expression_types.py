"""Shared data types for Persona expression and stream protocols."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from astrbot import logger

from .effects import PersonaEffectCall
from .types import PersonalResponseAction

PersonaExpressionKind = Literal["reply", "proactive", "interjection"]
PersonaExpressionSource = Literal[
    "user_message",
    "core_result",
    "plugin_output",
    "runtime_observation",
    "stream_observation",
    "tool_observation",
    "direct",
]
PersonaExpressionPhase = Literal[
    "immediate",
    "final",
    "proactive",
    "interjection",
    "plugin",
    "standalone",
]
PersonaProgressStage = Literal["stream_text", "tool_running", "tool_completed"]
PERSONA_TENDENCY_DIMENSIONS: tuple[str, ...] = (
    "Joy",
    "Trust",
    "Fear",
    "Surprise",
    "Sadness",
    "Disgust",
    "Anger",
    "Anticipation",
)


def default_persona_tendency() -> dict[str, int]:
    return dict.fromkeys(PERSONA_TENDENCY_DIMENSIONS, 0)


def clamp_persona_tendency_value(value: int) -> int:
    return max(0, min(10, value))


@dataclass(frozen=True, slots=True)
class PersonaExpressionIntent:
    """Describe one invocation of the shared Persona expression surface."""

    kind: PersonaExpressionKind = "reply"
    source: PersonaExpressionSource = "direct"
    phase: PersonaExpressionPhase = "standalone"

    def as_metadata(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "source": self.source,
            "phase": self.phase,
        }


@dataclass(slots=True)
class PersonaExpressionRequest:
    source_text: str = ""
    progress_context: str = ""
    immediate_reply: str = ""
    observed_text: str = ""
    total_text: str = ""
    pending_text: str = ""
    progress_stage: PersonaProgressStage | None = None
    preserve_facts: bool = False
    short_reply: bool = False
    allow_empty: bool = False
    allow_action_only: bool = False
    intent: PersonaExpressionIntent = field(default_factory=PersonaExpressionIntent)
    avoid_previous_reply: bool = False
    require_turn_action: bool = False
    allow_silent: bool = False

    @classmethod
    def core_final(
        cls,
        source_text: str,
        *,
        immediate_reply: str | None = None,
    ) -> PersonaExpressionRequest:
        return cls(
            source_text=source_text,
            immediate_reply=immediate_reply or "",
            preserve_facts=True,
            short_reply=True,
            intent=PersonaExpressionIntent(
                source="core_result",
                phase="final",
            ),
        )


@dataclass(slots=True)
class PersonaExpressionSegment:
    speech: str = ""
    actions: list[str] = field(default_factory=list)
    tendency: dict[str, int] = field(default_factory=default_persona_tendency)

    def to_mapping(self) -> dict[str, Any]:
        """Return the stable public representation of one expression segment."""

        return {
            "speech": self.speech,
            "actions": list(self.actions),
            "tendency": dict(self.tendency),
        }


class InteractionExpressionError(RuntimeError):
    def __init__(
        self,
        reason: str,
        message: str | None = None,
        *,
        tool_execution_count: int = 0,
        side_effects_started: bool = False,
        prepared: Any | None = None,
    ) -> None:
        self.reason = reason
        self.tool_execution_count = tool_execution_count
        self.side_effects_started = side_effects_started
        self.prepared = prepared
        super().__init__(message or reason)

    @property
    def has_side_effects(self) -> bool:
        return self.side_effects_started or self.tool_execution_count > 0


@dataclass(slots=True, init=False)
class PersonaExpressionResult:
    segments: list[PersonaExpressionSegment]
    effect_calls: list[PersonaEffectCall]
    metadata: dict[str, Any]
    turn_action: PersonalResponseAction | None

    def __init__(
        self,
        *,
        segments: Sequence[PersonaExpressionSegment] | None = None,
        speech: str | None = None,
        actions: list[str] | None = None,
        tendency: dict[str, int] | None = None,
        effect_calls: list[PersonaEffectCall] | None = None,
        metadata: dict[str, Any] | None = None,
        turn_action: PersonalResponseAction | None = PersonalResponseAction.REPLY,
    ) -> None:
        if segments is None:
            if speech is None and actions is None and tendency is None:
                segments = []
            else:
                segments = [
                    PersonaExpressionSegment(
                        speech=speech or "",
                        actions=list(actions or []),
                        tendency=dict(tendency or default_persona_tendency()),
                    )
                ]
        self.segments = list(segments)
        self.effect_calls = list(effect_calls or [])
        self.metadata = dict(metadata or {})
        self.turn_action = turn_action

    @property
    def speech(self) -> str:
        return "".join(segment.speech for segment in self.segments)

    @property
    def speech_segments(self) -> tuple[str, ...]:
        """Return speech in model-provided segment order for TTS consumers."""

        return tuple(segment.speech for segment in self.segments)

    def speech_segments_for_text(
        self,
        value: str,
        *,
        segment_texts: Sequence[str] | None = None,
    ) -> tuple[str, ...]:
        """Resolve unchanged, truncated, or explicitly boundary-preserving text."""

        text = str(value or "")
        if not self.segments:
            return (text,) if text else ()
        if segment_texts is not None:
            resolved_segments = tuple(segment_texts)
            if (
                len(resolved_segments) != len(self.segments)
                or any(not isinstance(segment, str) for segment in resolved_segments)
                or "".join(resolved_segments) != text
            ):
                raise InteractionExpressionError("persona_segment_text_override_invalid")
            return resolved_segments
        if not text:
            return tuple("" for _ in self.segments)
        if self.speech.startswith(text):
            remaining = len(text)
            projected = []
            for segment in self.segments:
                segment_text = segment.speech[:remaining]
                projected.append(segment_text)
                remaining -= len(segment_text)
            return tuple(projected)
        raise InteractionExpressionError(
            "persona_text_rewrite_requires_segment_boundaries"
        )

    @property
    def actions(self) -> list[str]:
        return [action for segment in self.segments for action in segment.actions]

    @property
    def tendency(self) -> dict[str, int]:
        if not self.segments:
            return default_persona_tendency()
        return dict(self.segments[-1].tendency)

    @property
    def segment_mappings(self) -> tuple[dict[str, Any], ...]:
        return tuple(segment.to_mapping() for segment in self.segments)

    def to_mapping(self) -> dict[str, Any]:
        """Return the canonical structured output shape."""

        return {
            "turn_action": (
                self.turn_action.value if self.turn_action is not None else None
            ),
            "segments": [segment.to_mapping() for segment in self.segments],
            "effect_calls": [
                {
                    "name": call.name,
                    "arguments": copy.deepcopy(call.arguments),
                    **(
                        {"segment_index": call.segment_index}
                        if call.segment_index is not None
                        else {}
                    ),
                }
                for call in self.effect_calls
            ],
        }

    def replace_visible_speech(self, value: str) -> None:
        """Apply unchanged speech or prefix truncation without guessing boundaries."""

        text = str(value or "")
        if not self.segments:
            self.segments = [PersonaExpressionSegment(speech=text)] if text else []
            return
        if not text:
            for segment in self.segments:
                segment.speech = ""
            return
        for segment, projected in zip(
            self.segments,
            self.speech_segments_for_text(text),
        ):
            segment.speech = projected

    def truncate_speech(self, max_length: int) -> None:
        """Truncate the concatenated speech without discarding segment metadata."""

        if max_length < 0:
            max_length = 0
        self.replace_visible_speech(self.speech[:max_length])

    @speech.setter
    def speech(self, value: str) -> None:
        """Accept boundary-preserving mutations from legacy response hooks."""

        try:
            self.replace_visible_speech(str(value or ""))
        except InteractionExpressionError as exc:
            logger.warning(
                "Rejected Persona response-hook text rewrite; preserving original "
                "speech segments and action bindings: reason=%s",
                exc.reason,
            )

    @actions.setter
    def actions(self, value: Sequence[str]) -> None:
        if not self.segments:
            self.segments = [PersonaExpressionSegment()]
        self.segments[0].actions = list(value)

    @tendency.setter
    def tendency(self, value: dict[str, int]) -> None:
        if not self.segments:
            self.segments = [PersonaExpressionSegment()]
        self.segments[0].tendency = dict(value)


__all__ = [
    "InteractionExpressionError",
    "PERSONA_TENDENCY_DIMENSIONS",
    "PersonaExpressionIntent",
    "PersonaExpressionKind",
    "PersonaExpressionPhase",
    "PersonaExpressionRequest",
    "PersonaExpressionResult",
    "PersonaExpressionSegment",
    "PersonaExpressionSource",
    "PersonaProgressStage",
    "PersonalResponseAction",
    "clamp_persona_tendency_value",
    "default_persona_tendency",
]
