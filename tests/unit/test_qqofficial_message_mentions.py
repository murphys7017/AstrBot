import pytest

from astrbot.api.event import MessageChain
from astrbot.api.message_components import At, Plain
from astrbot.core.platform.sources.qqofficial.qqofficial_message_event import (
    QQOfficialMessageEvent,
)


@pytest.mark.asyncio
async def test_qqofficial_message_serializes_user_mentions_in_order():
    message = MessageChain(
        chain=[
            Plain("hello "),
            At(qq="member-1"),
            Plain(" there"),
            At(qq="all"),
        ],
    )

    parsed = await QQOfficialMessageEvent._parse_to_qqofficial(message)

    assert parsed[0] == 'hello <qqbot-at-user id="member-1" /> there'
