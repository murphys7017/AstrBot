from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import astrbot.dashboard.services.chat_service as chat_service_module
from astrbot.dashboard.services.chat_service import ChatService


def _service_with_db(db):
    service = object.__new__(ChatService)
    service.db = db
    service._build_user_message_parts = AsyncMock()
    return service


def _authenticated_user(monkeypatch, username):
    monkeypatch.setattr(
        chat_service_module,
        "g",
        SimpleNamespace(
            get=lambda key, default=None: username if key == "username" else default
        ),
    )


@pytest.mark.asyncio
async def test_chat_rejects_session_owned_by_another_user(monkeypatch):
    db = SimpleNamespace(
        get_platform_session_by_id=AsyncMock(
            return_value=SimpleNamespace(session_id="alice-session", creator="alice")
        ),
        create_platform_session=AsyncMock(),
    )
    service = _service_with_db(db)
    _authenticated_user(monkeypatch, "bob")

    response = await service.chat({"message": "canary", "session_id": "alice-session"})

    assert response["status"] == "error"
    assert response["message"] == "Permission denied"
    db.create_platform_session.assert_not_awaited()
    service._build_user_message_parts.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_session_lookup_failure_does_not_continue(monkeypatch):
    db = SimpleNamespace(
        get_platform_session_by_id=AsyncMock(side_effect=RuntimeError("database down")),
        create_platform_session=AsyncMock(),
    )
    service = _service_with_db(db)
    _authenticated_user(monkeypatch, "alice")

    with pytest.raises(RuntimeError, match="database down"):
        await service.chat({"message": "canary", "session_id": "alice-session"})

    db.create_platform_session.assert_not_awaited()
    service._build_user_message_parts.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_does_not_create_session_for_empty_message(monkeypatch):
    db = SimpleNamespace(
        get_platform_session_by_id=AsyncMock(return_value=None),
        create_platform_session=AsyncMock(),
    )
    service = _service_with_db(db)
    service._build_user_message_parts.return_value = []
    _authenticated_user(monkeypatch, "alice")

    response = await service.chat({"message": "", "session_id": "empty-session"})

    assert response["status"] == "error"
    db.create_platform_session.assert_not_awaited()
