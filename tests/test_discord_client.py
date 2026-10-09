from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.platform.sources.discord.client import DiscordBotClient


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_bot_messages", [False, True])
@pytest.mark.parametrize(("author_id", "is_bot"), [(1, True), (2, True), (3, False)])
async def test_discord_filters_own_messages_but_keeps_other_bot_policy(
    allow_bot_messages,
    author_id,
    is_bot,
):
    client = DiscordBotClient(token="test", allow_bot_messages=allow_bot_messages)
    client._connection.user = SimpleNamespace(id=1)
    client.on_message_received = AsyncMock()
    message = SimpleNamespace(
        id=42,
        author=SimpleNamespace(
            id=author_id,
            bot=is_bot,
            name="tester",
            display_name="tester",
        ),
        content="hello",
        clean_content="hello",
        channel=SimpleNamespace(id=123),
        guild=None,
        mentions=[],
    )

    await client.on_message(message)

    if author_id == 1 or (is_bot and not allow_bot_messages):
        client.on_message_received.assert_not_awaited()
    else:
        client.on_message_received.assert_awaited_once()
        assert client.on_message_received.call_args.args[0]["message"] is message
