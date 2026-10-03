from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import astrbot.dashboard.services.chat_service as chat_service_module
from astrbot.core.db.po import PlatformSession
from astrbot.core.db.sqlite import SQLiteDatabase
from astrbot.dashboard.services.chat_service import ChatService


def _make_session(session_id="session-1"):
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    return SimpleNamespace(
        session_id=session_id,
        platform_id="webchat",
        creator="alice",
        display_name="Session title",
        is_group=0,
        created_at=timestamp,
        updated_at=timestamp,
    )


class _SessionsDatabase:
    def __init__(self):
        self.calls = []

    async def get_platform_sessions_by_creator_paginated(self, **kwargs):
        self.calls.append(kwargs)
        return [{"session": _make_session()}], 65


@pytest.mark.asyncio
async def test_chat_session_listing_paginates_without_changing_legacy_response(
    monkeypatch: pytest.MonkeyPatch,
):
    db = _SessionsDatabase()
    service = object.__new__(ChatService)
    service.db = db
    monkeypatch.setattr(
        chat_service_module,
        "g",
        SimpleNamespace(
            get=lambda key, default=None: "alice" if key == "username" else default
        ),
    )

    monkeypatch.setattr(
        chat_service_module,
        "request",
        SimpleNamespace(
            args={"page": "2", "page_size": "30", "platform_id": "webchat"}
        ),
    )
    paginated = await service.get_sessions()

    assert paginated["status"] == "ok"
    assert paginated["data"]["page"] == 2
    assert paginated["data"]["page_size"] == 30
    assert paginated["data"]["total"] == 65
    assert len(paginated["data"]["sessions"]) == 1
    assert db.calls[-1] == {
        "creator": "alice",
        "platform_id": "webchat",
        "page": 2,
        "page_size": 30,
        "exclude_project_sessions": True,
    }

    monkeypatch.setattr(chat_service_module, "request", SimpleNamespace(args={}))
    legacy = await service.get_sessions()

    assert legacy["status"] == "ok"
    assert isinstance(legacy["data"], list)
    assert db.calls[-1]["page"] == 1
    assert db.calls[-1]["page_size"] == 100

    monkeypatch.setattr(
        chat_service_module,
        "request",
        SimpleNamespace(args={"page": "invalid"}),
    )
    invalid = await service.get_sessions()

    assert invalid["status"] == "error"
    assert "integers" in invalid["message"]


@pytest.mark.asyncio
async def test_get_session_includes_metadata_for_deep_linked_sidebar_item(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _make_session("older-session")

    class Database:
        async def get_platform_session_by_id(self, _session_id):
            return session

        async def get_project_by_session(self, **_kwargs):
            return None

        async def get_webchat_threads_by_parent_session(self, **_kwargs):
            return []

    class HistoryManager:
        async def get(self, **_kwargs):
            return []

    service = object.__new__(ChatService)
    service.db = Database()
    service.platform_history_mgr = HistoryManager()
    service.running_convs = {}
    monkeypatch.setattr(
        chat_service_module,
        "g",
        SimpleNamespace(
            get=lambda key, default=None: "alice" if key == "username" else default
        ),
    )
    monkeypatch.setattr(
        chat_service_module,
        "request",
        SimpleNamespace(args={"session_id": "older-session"}),
    )
    response = await service.get_session()

    assert response["status"] == "ok"
    assert response["data"]["session"]["session_id"] == "older-session"
    assert response["data"]["session"]["display_name"] == "Session title"


@pytest.mark.asyncio
async def test_paginated_session_order_is_stable_for_equal_timestamps(tmp_path):
    db = SQLiteDatabase(str(tmp_path / "sessions.db"))
    await db.initialize()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        async with db.get_db() as session:
            async with session.begin():
                session.add_all(
                    [
                        PlatformSession(
                            session_id=f"session-{index}",
                            creator="alice",
                            platform_id="webchat",
                            created_at=timestamp,
                            updated_at=timestamp,
                        )
                        for index in range(5)
                    ]
                )

        first_page, total = await db.get_platform_sessions_by_creator_paginated(
            creator="alice", page=1, page_size=2
        )
        second_page, _ = await db.get_platform_sessions_by_creator_paginated(
            creator="alice", page=2, page_size=2
        )
        third_page, _ = await db.get_platform_sessions_by_creator_paginated(
            creator="alice", page=3, page_size=2
        )

        session_ids = [
            item["session"].session_id
            for page in (first_page, second_page, third_page)
            for item in page
        ]
        assert total == 5
        assert session_ids == [f"session-{index}" for index in reversed(range(5))]
    finally:
        await db.engine.dispose()
