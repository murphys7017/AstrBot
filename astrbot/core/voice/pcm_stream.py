"""Turn-scoped incremental text-to-PCM boundary for platform stream delivery."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, Literal

from .service import VoiceServiceError, resolve_tts_provider


@dataclass(frozen=True, slots=True)
class PCMTextPart:
    """A prepared speech delta; text=None closes this Persona segment."""

    segment_index: int
    text: str | None


@dataclass(frozen=True, slots=True)
class PCMStreamFrame:
    kind: Literal["start", "audio", "end"]
    segment_index: int
    sample_offset: int
    audio: bytes = b""
    encoding: str = "pcm16le"
    sample_rate: int = 32000
    channels: int = 1


async def synthesize_pcm_stream(
    plugin_context: Any,
    event: Any,
    text_source: AsyncIterator[PCMTextPart],
    *,
    provider: Any | None = None,
) -> AsyncIterator[PCMStreamFrame]:
    """Publish tagged PCM frames without files or complete-segment aggregation.

    The caller supplies already decoded, prepared text and closes this iterator
    on interruption. Exactly one Provider session consumes all ordered segments.
    start precedes the first chunk, end follows the acknowledged segment flush;
    sample offsets count frames per channel and do not require a final duration.
    """
    stage = "interaction.outbound_tts_stream"
    tts = provider or resolve_tts_provider(plugin_context, event, stage=stage)
    supports = getattr(tts, "support_pcm_stream", None)
    if not callable(supports) or supports() is not True:
        raise VoiceServiceError(
            "incremental_pcm_stream_unsupported",
            "The selected TTS Provider does not accept incremental PCM streaming",
            stage=stage,
        )
    current_index: int | None = None
    next_index = 0
    segment_open = False

    async def inputs() -> AsyncIterator[str | None]:
        nonlocal current_index, next_index, segment_open
        async for part in text_source:
            if (
                not isinstance(part, PCMTextPart)
                or type(part.segment_index) is not int
                or part.segment_index != next_index
            ):
                raise VoiceServiceError(
                    "pcm_stream_segment_order_invalid",
                    "PCM text segments must arrive once in increasing order",
                    stage=stage,
                )
            if part.text is not None and (
                not isinstance(part.text, str) or not part.text
            ):
                raise VoiceServiceError(
                    "pcm_stream_text_delta_invalid",
                    "PCM text deltas must be nonempty strings",
                    stage=stage,
                )
            current_index = part.segment_index
            segment_open = True
            yield part.text
            if part.text is None:
                # The Provider resumes this generator only after its flush marker
                # has been accepted by our output consumer.
                segment_open = False
                next_index += 1
        if segment_open:
            raise VoiceServiceError(
                "pcm_stream_segment_boundary_missing",
                "PCM input ended without closing its final segment",
                stage=stage,
            )

    output_index: int | None = None
    next_output_index = 0
    offset = 0
    try:
        async with aclosing(tts.get_pcm_stream(inputs())) as frames:
            async for audio in frames:
                if current_index is None:
                    raise RuntimeError("pcm_stream_audio_before_text")
                if output_index is None:
                    if current_index != next_output_index:
                        raise RuntimeError("pcm_stream_duplicate_or_missing_boundary")
                    output_index = current_index
                    offset = 0
                    yield PCMStreamFrame("start", output_index, offset)
                if output_index != current_index:
                    raise RuntimeError("pcm_stream_audio_crossed_segment_boundary")
                if audio is None:
                    yield PCMStreamFrame("end", output_index, offset)
                    output_index = None
                    next_output_index += 1
                else:
                    if not isinstance(audio, bytes) or not audio or len(audio) % 2:
                        raise RuntimeError("pcm_stream_audio_invalid")
                    yield PCMStreamFrame("audio", output_index, offset, audio)
                    offset += len(audio) // 2
        if output_index is not None:
            raise RuntimeError("pcm_stream_missing_flush_ack")
    except VoiceServiceError:
        raise
    except Exception as exc:
        raise VoiceServiceError(
            "pcm_stream_provider_failed",
            "Incremental PCM synthesis failed",
            stage=stage,
        ) from exc
    finally:
        close_input = getattr(text_source, "aclose", None)
        if callable(close_input):
            async with asyncio.timeout(0.5):
                await close_input()
