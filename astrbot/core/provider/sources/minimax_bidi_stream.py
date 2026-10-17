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

    Each input string is appended once. Input None flushes the current segment
    without ending synthesis; exhausting the input finishes the session. No
    next-segment text is sent until the consumer accepts the flush boundary.
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

    async with asyncio.timeout(timeout_seconds):
        async with session.ws_connect(
            ws_url,
            headers={"Authorization": f"Bearer {api_key}"},
            proxy=proxy or None,
            heartbeat=20,
            max_msg_size=1_048_576,
        ) as ws:

            async def receive() -> dict[str, Any]:
                message = await ws.receive()
                if message.type != aiohttp.WSMsgType.TEXT:
                    raise RuntimeError("minimax_bidi_closed_before_finished")
                data = message.json()
                if not isinstance(data, dict):
                    raise RuntimeError("minimax_bidi_invalid_event")
                code = data.get("base_resp", {}).get("status_code", 0)
                if code or data.get("event") == "task_failed":
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
            await ws.send_json(start)
            if (await receive()).get("event") != "task_started":
                raise RuntimeError("minimax_bidi_task_not_ready")

            boundary_ack = asyncio.Event()
            input_finished = False

            async def send_text() -> None:
                nonlocal input_finished
                async for text in text_source:
                    if text is None:
                        boundary_ack.clear()
                        await ws.send_json({"event": "task_flush"})
                        await boundary_ack.wait()
                    elif not isinstance(text, str) or not text:
                        raise ValueError("minimax_bidi_invalid_text_delta")
                    else:
                        await ws.send_json({"event": "task_continue", "text": text})
                input_finished = True
                await ws.send_json({"event": "task_finish"})

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
                    audio = data.get("data", {}).get("audio")
                    if audio:
                        if not isinstance(audio, str):
                            raise RuntimeError("minimax_bidi_invalid_audio")
                        try:
                            pcm = bytes.fromhex(audio)
                        except ValueError as exc:
                            raise RuntimeError(
                                "minimax_bidi_invalid_audio_hex"
                            ) from exc
                        if len(pcm) % 2:
                            raise RuntimeError("minimax_bidi_unaligned_pcm")
                        if pcm:
                            yield pcm
                    event = data.get("event")
                    if event == "task_flushed":
                        # The caller processes the boundary before new text enters
                        # the session, so following audio has unambiguous ownership.
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
