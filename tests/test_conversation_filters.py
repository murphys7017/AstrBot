from datetime import datetime, timezone

import pytest

from astrbot.core.db.po import ConversationV2


@pytest.mark.asyncio
async def test_exclude_ids_match_umo_boundary_without_like_wildcards(temp_db):
    conversations = [
        ConversationV2(
            conversation_id="astrbot-group",
            platform_id="astrbot",
            user_id="astrbot:GroupMessage:1",
            content=[],
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        ConversationV2(
            conversation_id="astrbotweb-group",
            platform_id="astrbotweb",
            user_id="astrbotweb:GroupMessage:2",
            content=[],
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
        ConversationV2(
            conversation_id="literal-percent",
            platform_id="100%",
            user_id="100%:GroupMessage:3",
            content=[],
            created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        ),
    ]

    async with temp_db.get_db() as session:
        async with session.begin():
            session.add_all(conversations)

    result, total = await temp_db.get_filtered_conversations(
        page=1,
        page_size=10,
        exclude_ids=["astrbot"],
    )
    assert total == 2
    assert {conversation.conversation_id for conversation in result} == {
        "astrbotweb-group",
        "literal-percent",
    }

    _, wildcard_total = await temp_db.get_filtered_conversations(
        page=1,
        page_size=10,
        exclude_ids=["100%"],
    )
    assert wildcard_total == 2
