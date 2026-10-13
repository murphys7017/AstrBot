import pytest

from astrbot.core.interaction.expression_agent import (
    InteractionExpressionError,
    PersonaExpressionResult,
    PersonaExpressionSegment,
)


def test_persona_speech_rewrite_does_not_rebind_actions_by_length():
    result = PersonaExpressionResult(segments=[
        PersonaExpressionSegment(speech="左……", actions=["turn_head_left"]),
        PersonaExpressionSegment(speech="右……", actions=["turn_head_right"]),
    ])
    original = result.segment_mappings
    result.speech = "右……左……"
    assert result.segment_mappings == original
    result.truncate_speech(3)
    assert result.speech_segments == ("左……", "")
    assert result.segments[0].actions == ["turn_head_left"]


def test_persona_text_override_requires_explicit_matching_segment_boundaries():
    result = PersonaExpressionResult(segments=[
        PersonaExpressionSegment(speech="左……", actions=["turn_head_left"]),
        PersonaExpressionSegment(speech="右……", actions=["turn_head_right"]),
    ])
    assert result.speech_segments_for_text(
        "向左看。向右看。",
        segment_texts=("向左看。", "向右看。"),
    ) == ("向左看。", "向右看。")
    with pytest.raises(
        InteractionExpressionError,
        match="persona_segment_text_override_invalid",
    ):
        result.speech_segments_for_text(
            "向左看。",
            segment_texts=("向左看。", "向右看。"),
        )
