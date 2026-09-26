from datetime import datetime, timezone

import pytest

from astrbot.core.db.po import ConversationV2, PlatformSession


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


@pytest.mark.asyncio
async def test_webchat_session_title_is_searchable(temp_db):
    session_id = "webchat-session-title"
    async with temp_db.get_db() as session:
        async with session.begin():
            session.add_all(
                [
                    ConversationV2(
                        conversation_id="webchat-title-search",
                        platform_id="webchat",
                        user_id=(
                            "webchat:FriendMessage:"
                            f"webchat!astrbot!{session_id}"
                        ),
                        content=[],
                        created_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
                        updated_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
                    ),
                    PlatformSession(
                        session_id=session_id,
                        platform_id="webchat",
                        creator="astrbot",
                        display_name="中文食谱笔记",
                    ),
                ]
            )

    conversations, total = await temp_db.get_filtered_conversations(
        page=1,
        page_size=10,
        search_query="食谱",
    )

    assert total == 1
    assert [conversation.conversation_id for conversation in conversations] == [
        "webchat-title-search"
    ]
