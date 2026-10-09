from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from astrbot.core.interaction.expression_agent import (
    PersonaExpressionResult,
    PersonaExpressionSegment,
)
from astrbot.core.interaction.output_controller import (
    InteractionOutputController,
    OutboundMaterializationOptions,
)
from astrbot.core.message.components import Image, Plain, Record
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.voice.service import TextToSpeechResult, TTSState


def _options(
    *, dual_output: bool, show_reasoning: bool = False
) -> OutboundMaterializationOptions:
    return OutboundMaterializationOptions(
        reply_prefix="",
        show_reasoning=show_reasoning,
        tts_enabled=True,
        tts_trigger_probability=1.0,
        tts_dual_output=dual_output,
        tts_use_file_service=False,
        callback_api_base="",
        t2i_enabled=False,
        t2i_word_threshold=150,
        t2i_use_network=False,
        t2i_active_template="base",
    )


@pytest.mark.asyncio
async def test_persona_tts_consumes_speech_segments_in_order():
    controller = object.__new__(InteractionOutputController)
    controller.plugin_context = object()
    controller._resolve_outbound_options = lambda _event: _options(dual_output=True)
    next_id = iter(("tts-1", "tts-2"))
    controller._next_output_segment_id = lambda _event, _kind: next(next_id)
    event = SimpleNamespace(
        get_extra=lambda key, default=None: {
            "_turn_id": "turn-1",
        }.get(key, default),
    )
    requested_texts = []
    persona_result = PersonaExpressionResult(
        segments=[
            PersonaExpressionSegment(speech="第一句"),
            PersonaExpressionSegment(speech=""),
            PersonaExpressionSegment(speech="第二句"),
        ],
    )

    async def fake_synthesize(_context, _event, text, **kwargs):
        requested_texts.append((text, kwargs["message_id"]))
        state = TTSState(
            turn_id="turn-1",
            message_id=kwargs["message_id"],
            tts_request_id=f"request-{len(requested_texts)}",
            stage="interaction.outbound_tts",
            status="succeeded",
            provider_id="fake-tts",
            audio_path=f"{len(requested_texts)}.wav",
        )
        return TextToSpeechResult(
            text=text,
            audio_path=state.audio_path or "",
            audio_url=None,
            provider_id="fake-tts",
            metadata={},
            state=state,
        )

    message = MessageChain(
        [Plain("第一句第二句"), Image("attachment.png")],
    )
    with (
        patch(
            "astrbot.core.interaction.output_controller.SessionServiceManager"
            ".should_process_tts_request",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "astrbot.core.interaction.output_controller.random.random",
            return_value=0.0,
        ),
        patch(
            "astrbot.core.interaction.output_controller.synthesize_text",
            new=fake_synthesize,
        ),
    ):
        materialized, metadata = await controller.materialize_interaction_outbound_message(
            event,
            message,
            message_kind="core_reply",
            result_is_model_result=True,
            message_id="message-1",
            tts_segments=persona_result.speech_segments,
        )

    assert requested_texts == [
        ("第一句", "message-1"),
        ("第二句", "tts-1"),
    ]
    assert [type(component) for component in materialized.chain] == [
        Record,
        Record,
        Plain,
        Image,
    ]
    assert materialized.chain[2].text == "第一句第二句"
    assert materialized.get_plain_text() == "第一句第二句"
    assert sum(isinstance(component, Plain) for component in materialized.chain) == 1
    assert [item["tts_source_text"] for item in metadata["tts"]] == [
        "第一句",
        "第二句",
    ]
    assert [
        item["persona_segment_index"] for item in metadata["tts"]
    ] == [0, 2]
    assert [
        item["persona_segment_count"] for item in metadata["tts"]
    ] == [3, 3]


@pytest.mark.asyncio
async def test_persona_tts_keeps_reasoning_text_outside_speech_segments():
    controller = object.__new__(InteractionOutputController)
    controller.plugin_context = object()
    controller._resolve_outbound_options = lambda _event: _options(
        dual_output=False,
        show_reasoning=True,
    )
    controller._next_output_segment_id = lambda _event, _kind: "tts-1"
    event = SimpleNamespace(
        get_extra=lambda key, default=None: {
            "_turn_id": "turn-1",
            "_llm_reasoning_content": "internal reasoning",
        }.get(key, default),
        get_platform_name=lambda: "webchat",
    )
    requested_texts = []
    persona_result = PersonaExpressionResult(
        segments=[
            PersonaExpressionSegment(speech="第一句"),
            PersonaExpressionSegment(speech="第二句"),
        ],
    )

    async def fake_synthesize(_context, _event, text, **kwargs):
        requested_texts.append(text)
        state = TTSState(
            turn_id="turn-1",
            message_id=kwargs["message_id"],
            tts_request_id="request-1",
            stage="interaction.outbound_tts",
            status="succeeded",
            provider_id="fake-tts",
            audio_path="speech.wav",
        )
        return TextToSpeechResult(
            text=text,
            audio_path="speech.wav",
            audio_url=None,
            provider_id="fake-tts",
            metadata={},
            state=state,
        )

    message = MessageChain([Plain("第一句第二句")])
    with (
        patch(
            "astrbot.core.interaction.output_controller.SessionServiceManager"
            ".should_process_tts_request",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "astrbot.core.interaction.output_controller.random.random",
            return_value=0.0,
        ),
        patch(
            "astrbot.core.interaction.output_controller.synthesize_text",
            new=fake_synthesize,
        ),
    ):
        materialized, _ = await controller.materialize_interaction_outbound_message(
            event,
            message,
            message_kind="core_reply",
            result_is_model_result=True,
            message_id="message-1",
            tts_segments=persona_result.speech_segments,
        )

    assert requested_texts == ["第一句", "第二句"]
    assert [type(component) for component in materialized.chain] == [
        Plain,
        Record,
        Record,
    ]
    assert materialized.chain[0].text == "思考: internal reasoning\n"
