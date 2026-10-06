import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

import astrbot.core.core_lifecycle  # noqa: F401
from astrbot.core.message.components import File
from astrbot.core.platform.sources.slack.slack_event import SlackMessageEvent


@pytest.mark.asyncio
@pytest.mark.parametrize("source_type", ["path", "uri", "http", "uppercase_http"])
async def test_slack_file_upload_resolves_source_and_preserves_local_files(
    tmp_path, source_type
):
    payload = b"slack attachment"
    local = tmp_path / "attachment.txt"
    local.write_bytes(payload)
    app = web.Application()
    app.router.add_get("/attachment", lambda _: web.Response(body=payload))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    source = {
        "path": str(local),
        "uri": local.as_uri(),
        "http": f"http://127.0.0.1:{port}/attachment",
        "uppercase_http": f"HTTP://127.0.0.1:{port}/attachment",
    }[source_type]
    uploaded_paths = []

    async def upload(*, file, filename):
        path = Path(file)
        assert await asyncio.to_thread(path.read_bytes) == payload
        assert filename == "attachment.txt"
        uploaded_paths.append(path)
        return {"ok": True, "files": [{"permalink": "https://slack.test/file"}]}

    try:
        block = await SlackMessageEvent._from_segment_to_slack_block(
            File(name="attachment.txt", url=source),
            AsyncMock(files_upload_v2=AsyncMock(side_effect=upload)),
        )
        assert "https://slack.test/file" in block["text"]["text"]
        assert local.read_bytes() == payload
        assert uploaded_paths[0].exists() == (source_type in {"path", "uri"})
    finally:
        await runner.cleanup()
