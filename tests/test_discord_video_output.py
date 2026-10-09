from io import BufferedReader
from unittest.mock import AsyncMock

import pytest

from astrbot.api.message_components import Video
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.sources.discord.discord_platform_event import (
    DiscordPlatformEvent,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected_name"),
    [
        ("https://example.com/clips/demo.mp4", "demo.mp4"),
        ("https://example.com/demo.mp4?token=test#preview", "demo.mp4"),
        ("https://example.com/%E6%B5%8B%E8%AF%95%20video.mp4", "测试 video.mp4"),
        ("https://example.com", "media_video_test.mp4"),
    ],
)
async def test_discord_sends_video_as_attachment(
    tmp_path, monkeypatch, url, expected_name
):
    video_path = tmp_path / "media_video_test.mp4"
    video_bytes = b"video attachment payload"
    video_path.write_bytes(video_bytes)
    monkeypatch.setattr(
        Video,
        "convert_to_file_path",
        AsyncMock(return_value=str(video_path)),
    )
    event = DiscordPlatformEvent.__new__(DiscordPlatformEvent)

    _, files, _, _, _ = await event._parse_to_discord(
        MessageChain(chain=[Video.fromURL(url)])
    )

    assert len(files) == 1
    try:
        assert files[0].filename == expected_name
        assert isinstance(files[0].fp, BufferedReader)
        assert files[0].fp.tell() == 0
        assert files[0].fp.read() == video_bytes
    finally:
        files[0].close()


@pytest.mark.asyncio
async def test_discord_sends_local_video_as_attachment(tmp_path):
    video_path = tmp_path / "local.mp4"
    video_path.write_bytes(b"local video payload")
    event = DiscordPlatformEvent.__new__(DiscordPlatformEvent)

    _, files, _, _, _ = await event._parse_to_discord(
        MessageChain(chain=[Video.fromFileSystem(str(video_path))])
    )

    assert len(files) == 1
    try:
        assert files[0].filename == "local.mp4"
        assert isinstance(files[0].fp, BufferedReader)
        assert files[0].fp.read() == b"local video payload"
    finally:
        files[0].close()
