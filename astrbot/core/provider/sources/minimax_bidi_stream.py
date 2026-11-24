"""MiniMax bidirectional PCM streaming with acknowledged text boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp


async def stream_minimax_pcm(
    text_source: AsyncIterator[str | None],
    *,
    session: aiohttp.ClientSession,
    api_base: str,
    api_key: str,
    model: str,
    voice_setting: dict[str, Any],
    language_boost: str,
    timber_weights: list[dict[str, Any]] | None = None,
    proxy: str | None = None,
    timeout_seconds: float = 60,
) -> AsyncIterator[bytes | None]:
    """Yield PCM16LE/32000Hz/mono; None acknowledges an input flush marker.

    Text deltas are coalesced per input segment before submission. Input None
    flushes the current segment without ending synthesis; exhausting the input
    finishes the session. No next-segment text is sent until the consumer
    accepts the flush boundary.
    Cancellation closes this synthesis WebSocket and never replays submitted
    text. The caller owns the HTTP session/pool and closes it at Provider exit;
    neither the WebSocket nor a synthesis task is reused across Turns.
    """
    endpoint = urlsplit(api_base)
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        raise ValueError("minimax_bidi_invalid_api_base")
    ws_url = urlunsplit(
        (
            "wss" if endpoint.scheme == "https" else "ws",
            endpoint.netloc,
            "/ws/v1/t2a_v2_bidi",
            "",
            "",
        )
    )
    if not api_key or not model or timeout_seconds <= 0:
        raise ValueError("minimax_bidi_configuration_missing")

    # A yielded frame is consumed on this same task, possibly waiting for
    # desktop audio credit. Only time network operations owned by the provider.
    async with asyncio.timeout(timeout_seconds):
        ws = await session.ws_connect(
            ws_url,
            headers={"Authorization": f"Bearer {api_key}"},
            proxy=proxy or None,
            heartbeat=20,
            max_msg_size=1_048_576,
        )
    async with ws:

        async def send(event: dict[str, Any]) -> None:
            async with asyncio.timeout(timeout_seconds):
                await ws.send_json(event)

        async def receive() -> dict[str, Any]:
            # Heartbeats keep the socket alive but do not constitute a synthesis response.
            async with asyncio.timeout(timeout_seconds):
                message = await ws.receive()
            if message.type != aiohttp.WSMsgType.TEXT:
                raise RuntimeError("minimax_bidi_closed_before_finished")
            data = message.json()
            if not isinstance(data, dict):
                raise RuntimeError("minimax_bidi_invalid_event")
            code = (data.get("base_resp") or {}).get("status_code", 0)
            if code not in {0, 2205} or data.get("event") == "task_failed":
                # Do not put Provider response bodies or credentials in errors.
                raise RuntimeError(f"minimax_bidi_provider_error:{code}")
            return data

        if (await receive()).get("event") != "connected_success":
            raise RuntimeError("minimax_bidi_connection_not_ready")
        start: dict[str, Any] = {
            "event": "task_start",
            "model": model,
            "voice_setting": voice_setting,
            "language_boost": language_boost,
            "audio_setting": {
                "format": "pcm",
                "sample_rate": 32000,
                "channel": 1,
            },
        }
        if timber_weights:
            start["timber_weights"] = timber_weights
        await send(start)
        if (await receive()).get("event") != "task_started":
            raise RuntimeError("minimax_bidi_task_not_ready")

        max_task_continue_chars = 9000
        boundary_ack = asyncio.Event()
        continue_ack = asyncio.Event()
        retry_requested = asyncio.Event()
        retry_signal = asyncio.Event()
        input_finished = False

        async def send_segment(text: str) -> None:
            chunks = [
                text[start : start + max_task_continue_chars]
                for start in range(0, len(text), max_task_continue_chars)
            ] or [""]
            for chunk_index, chunk in enumerate(chunks):
                is_last_chunk = chunk_index == len(chunks) - 1
                retry_count = 0
                while True:
                    retry_signal.clear()
                    continue_ack.clear()
                    boundary_ack.clear()
                    if chunk:
                        await send({"event": "task_continue", "text": chunk})
                    if is_last_chunk:
                        await send({"event": "task_flush"})
                    ack = boundary_ack if is_last_chunk else continue_ack
                    boundary_wait = asyncio.create_task(ack.wait())
                    retry_wait = asyncio.create_task(retry_signal.wait())
                    try:
                        await asyncio.wait(
                            {boundary_wait, retry_wait},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    finally:
                        for task in (boundary_wait, retry_wait):
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(
                            boundary_wait, retry_wait, return_exceptions=True
                        )
                    if retry_signal.is_set():
                        retry_count += 1
                        if retry_count > 8:
                            raise RuntimeError("minimax_bidi_queue_retry_exhausted")
                        await asyncio.sleep(min(0.05 * (2 ** (retry_count - 1)), 1.0))
                        continue
                    break

        async def send_text() -> None:
            nonlocal input_finished
            segment_parts: list[str] = []
            async for text in text_source:
                if text is None:
                    await send_segment("".join(segment_parts))
                    segment_parts.clear()
                elif not isinstance(text, str) or not text:
                    raise ValueError("minimax_bidi_invalid_text_delta")
                else:
                    segment_parts.append(text)
            if segment_parts:
                await send_segment("".join(segment_parts))
            input_finished = True
            await send({"event": "task_finish"})

        sender = asyncio.create_task(send_text(), name="minimax-bidi-text")
        receiver: asyncio.Task[dict[str, Any]] | None = None
        try:
            while True:
                receiver = asyncio.create_task(receive(), name="minimax-bidi-audio")
                await asyncio.wait(
                    {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
                )
                if sender.done():
                    # Propagate upstream errors even while the server waits for
                    # text, instead of turning them into a receive timeout.
                    await sender
                data = await receiver
                code = (data.get("base_resp") or {}).get("status_code", 0)
                if code == 2205:
                    # MiniMax keeps the session open and asks the client to
                    # resend the rejected task_continue after a short delay.
                    retry_requested.set()
                    retry_signal.set()
                    continue
                audio = (data.get("data") or {}).get("audio")
                if audio:
                    if not isinstance(audio, str):
                        raise RuntimeError("minimax_bidi_invalid_audio")
                    try:
                        pcm = bytes.fromhex(audio)
                    except ValueError as exc:
                        raise RuntimeError("minimax_bidi_invalid_audio_hex") from exc
                    if len(pcm) % 2:
                        raise RuntimeError("minimax_bidi_unaligned_pcm")
                    if pcm:
                        yield pcm
                event = data.get("event")
                if event == "task_continued" and data.get("is_final", True):
                    # A successful continuation retires the retry guard so a
                    # stale flush from the rejected attempt cannot close it.
                    retry_requested.clear()
                    continue_ack.set()
                elif event == "task_flushed":
                    if retry_requested.is_set():
                        continue
                    # The consumer must receive and process this boundary
                    # before the sender can submit the next segment. The
                    # segment index and audio ownership live in that consumer.
                    yield None
                    boundary_ack.set()
                elif event == "task_finished":
                    if not input_finished:
                        raise RuntimeError("minimax_bidi_finished_before_input")
                    await sender
                    break
                elif event == "task_canceled":
                    raise RuntimeError("minimax_bidi_unexpected_cancel")
        finally:
            owned_tasks = [sender, *([receiver] if receiver is not None else [])]
            for task in owned_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*owned_tasks, return_exceptions=True)
            try:
                close_input = getattr(text_source, "aclose", None)
                if callable(close_input):
                    async with asyncio.timeout(0.5):
                        await close_input()
            finally:
                with suppress(TimeoutError):
                    async with asyncio.timeout(0.5):
                        await ws.close()
