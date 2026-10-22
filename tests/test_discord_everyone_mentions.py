from types import SimpleNamespace

import pytest

from astrbot.api.message_components import AtAll
from astrbot.core.platform.sources.discord.discord_platform_adapter import (
    DiscordPlatformAdapter,
)


@pytest.mark.parametrize("mention_everyone", [False, True])
def test_discord_everyone_mention_is_preserved(mention_everyone: bool) -> None:
    adapter = DiscordPlatformAdapter.__new__(DiscordPlatformAdapter)
    adapter.client = SimpleNamespace(user=None)
    adapter.bot_self_id = "999"
    message = SimpleNamespace(
        content="@everyone check this",
        channel=SimpleNamespace(id=123, guild=SimpleNamespace()),
        author=SimpleNamespace(id=456, display_name="member"),
        attachments=[],
        role_mentions=[],
        guild=None,
        mention_everyone=mention_everyone,
        id=789,
    )

    converted = adapter._convert_message_to_abm({"message": message})

    assert converted.message_str == "@everyone check this"
    assert sum(isinstance(item, AtAll) for item in converted.message) == int(
        mention_everyone
    )
