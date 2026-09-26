from unittest.mock import AsyncMock

import pytest

import astrbot.core.conversation_mgr as conversation_mgr
from astrbot.core.conversation_mgr import ConversationManager


@pytest.mark.asyncio
async def test_delete_current_conversation_reads_persisted_selection(monkeypatch):
    db = AsyncMock()
    manager = ConversationManager(db)
    session_get = AsyncMock(return_value="persisted-conversation")
    session_remove = AsyncMock()
    monkeypatch.setattr(conversation_mgr.sp, "session_get", session_get)
    monkeypatch.setattr(conversation_mgr.sp, "session_remove", session_remove)

    await manager.delete_conversation("qq:GroupMessage:1000")

    db.delete_conversation.assert_awaited_once_with(cid="persisted-conversation")
    session_remove.assert_awaited_once_with(
        "qq:GroupMessage:1000",
        "sel_conv_id",
    )
    assert "qq:GroupMessage:1000" not in manager.session_conversations
