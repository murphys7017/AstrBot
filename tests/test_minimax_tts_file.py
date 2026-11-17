"""File output must consume the aggregate, not concatenate it with deltas."""

import asyncio
import io
import json
import wave
from pathlib import Path

import pytest
from aiohttp import web

from astrbot.core.provider.sources import minimax_tts_api_source as source


@pytest.mark.parametrize("has_final", [True, False])
def test_minimax_file_output(tmp_path, monkeypatch, has_final):
    monkeypatch.setattr(source, "get_astrbot_temp_path", lambda: str(tmp_path))
    pcm = b"\x00\x00\x00\x10\x00\xf0\x00\x00" * 160
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 32000, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)
    complete = output.getvalue()

    async def run():
        async def handle(request):
            body = await request.json()
            assert body["stream_options"]["exclude_aggregated_audio"] is False
            frames = [(1, complete[:128]), (1, complete[128:])]
            if has_final:
                frames.append((2, complete))
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            for status, audio in frames:
                payload = json.dumps(
                    {
                        "data": {"status": status, "audio": audio.hex()},
                        "base_resp": {"status_code": 0},
                    }
                )
                await response.write(f"data: {payload}\n\n".encode())
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_post("/v1/t2a_v2", handle)
        runner = web.AppRunner(app)
        await runner.setup()
        server = await asyncio.get_running_loop().create_server(
            runner.server, "127.0.0.1", 0
        )
        port = server.sockets[0].getsockname()[1]
        provider = source.ProviderMiniMaxTTSAPI(
            {
                "id": "minimax-file-test",
                "type": "minimax_tts_api",
                "api_key": "test",
                "model": "speech-02-hd",
                "api_base": f"http://127.0.0.1:{port}/v1/t2a_v2",
            },
            {},
        )
        try:
            if has_final:
                path = Path(await provider.get_audio("hello"))
                assert path.read_bytes() == complete
                with wave.open(str(path)) as wav:
                    assert wav.readframes(wav.getnframes()) == pcm
            else:
                with pytest.raises(RuntimeError, match="without_final_audio"):
                    await provider.get_audio("hello")
                assert not list(tmp_path.glob("*.wav"))
        finally:
            await provider.terminate()
            server.close()
            await server.wait_closed()
            await runner.cleanup()

    asyncio.run(run())
