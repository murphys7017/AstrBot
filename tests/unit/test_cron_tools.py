"""Tests for cron tool metadata."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.platform.message_type import MessageType
from astrbot.core.tools.cron_tools import FutureTaskTool


def test_future_task_schema_has_action_and_create_cron_guidance():
    """The merged tool should expose action routing and unambiguous cron guidance."""
    tool = FutureTaskTool()

    assert tool.name == "future_task"
    assert tool.parameters["required"] == ["action"]
    assert tool.parameters["properties"]["action"]["enum"] == [
        "create",
        "edit",
        "delete",
        "list",
    ]

    description = tool.parameters["properties"]["cron_expression"]["description"]

    assert "mon-fri" in description
    assert "sat,sun" in description
    assert "1-5" in description
    assert "Prefer named weekdays" in description


def test_future_task_schema_has_no_job_type_and_delete_job_id():
    """The merged tool should remove job_type and document delete requirements."""
    tool = FutureTaskTool()

    assert "job_type" not in tool.parameters["properties"]
    action_description = tool.parameters["properties"]["action"]["description"]
    job_id_description = tool.parameters["properties"]["job_id"]["description"]

    assert "'edit' requires 'job_id'" in action_description
    assert "Required for 'delete' and 'edit'" in job_id_description


@pytest.mark.asyncio
async def test_future_task_edit_requires_job_id():
    """Edit mode should require job_id."""
    tool = FutureTaskTool()
    cron_mgr = SimpleNamespace()
    context = SimpleNamespace(
        context=SimpleNamespace(
            context=SimpleNamespace(cron_manager=cron_mgr),
            event=SimpleNamespace(
                unified_msg_origin="test:private:session",
                get_sender_id=lambda: "user-1",
            ),
        )
    )

    result = await tool.call(context, action="edit")

    assert result == "error: job_id is required when action=edit."


@pytest.mark.asyncio
async def test_future_task_edit_updates_existing_job():
    """Edit mode should update note and one-time scheduling fields."""
    tool = FutureTaskTool()
    existing_job = SimpleNamespace(
        job_id="job-1",
        name="old name",
        job_type="active_agent",
        run_once=False,
        cron_expression="0 8 * * *",
        payload={
            "session": "test:private:session",
            "sender_id": "user-1",
            "note": "old note",
            "origin": "tool",
        },
    )
    updated_job = SimpleNamespace(
        job_id="job-1",
        name="new name",
        run_once=True,
        cron_expression=None,
        next_run_time=None,
    )
    cron_mgr = SimpleNamespace(
        db=SimpleNamespace(get_cron_job=AsyncMock(return_value=existing_job)),
        update_job=AsyncMock(return_value=updated_job),
    )
    context = SimpleNamespace(
        context=SimpleNamespace(
            context=SimpleNamespace(cron_manager=cron_mgr),
            event=SimpleNamespace(
                unified_msg_origin="test:private:session",
                get_sender_id=lambda: "user-1",
            ),
        )
    )

    result = await tool.call(
        context,
        action="edit",
        job_id="job-1",
        name="new name",
        note="new note",
        run_once=True,
        run_at="2026-02-02T08:00:00+08:00",
    )

    cron_mgr.update_job.assert_awaited_once_with(
        "job-1",
        name="new name",
        description="new note",
        run_once=True,
        cron_expression=None,
        payload={
            "session": "test:private:session",
            "sender_id": "user-1",
            "note": "new note",
            "origin": "tool",
            "run_at": "2026-02-02T08:00:00+08:00",
        },
    )
    assert result == "Updated future task job-1 (new name)."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "extra", "expected_action"),
    [
        ("edit", {"name": "changed"}, "edit"),
        ("delete", {}, "delete"),
    ],
)
async def test_future_task_rejects_another_group_member(
    action, extra, expected_action
):
    tool = FutureTaskTool()
    job = SimpleNamespace(
        job_id="job-other",
        payload={"session": "test:group:room", "sender_id": "user-2"},
    )
    cron_mgr = SimpleNamespace(
        db=SimpleNamespace(get_cron_job=AsyncMock(return_value=job)),
        update_job=AsyncMock(),
        delete_job=AsyncMock(),
    )
    context = SimpleNamespace(
        context=SimpleNamespace(
            context=SimpleNamespace(cron_manager=cron_mgr),
            event=SimpleNamespace(
                unified_msg_origin="test:group:room",
                get_sender_id=lambda: "user-1",
                get_message_type=lambda: MessageType.GROUP_MESSAGE,
            ),
        )
    )

    result = await tool.call(
        context,
        action=action,
        job_id="job-other",
        **extra,
    )

    assert "created by another member of this group chat" in result
    assert (
        f"only the member who created it can {expected_action} it" in result.lower()
    )
    cron_mgr.update_job.assert_not_awaited()
    cron_mgr.delete_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_future_task_explains_creatorless_legacy_job():
    tool = FutureTaskTool()
    job = SimpleNamespace(
        job_id="job-legacy",
        payload={"session": "test:group:room", "origin": "api"},
    )
    cron_mgr = SimpleNamespace(
        db=SimpleNamespace(get_cron_job=AsyncMock(return_value=job)),
        delete_job=AsyncMock(),
    )
    context = SimpleNamespace(
        context=SimpleNamespace(
            context=SimpleNamespace(cron_manager=cron_mgr),
            event=SimpleNamespace(
                unified_msg_origin="test:group:room",
                get_sender_id=lambda: "user-1",
                get_message_type=lambda: MessageType.GROUP_MESSAGE,
            ),
        )
    )

    result = await tool.call(context, action="delete", job_id="job-legacy")

    assert "has no chat member as its creator" in result
    assert "created outside this chat" in result
    assert "another member" not in result
    cron_mgr.delete_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_future_task_list_only_shows_current_sender_jobs():
    tool = FutureTaskTool()
    own_job = SimpleNamespace(
        job_id="job-own",
        name="my task",
        job_type="active_agent",
        run_once=True,
        enabled=True,
        next_run_time=None,
        payload={"session": "test:group:room", "sender_id": "user-1"},
    )
    other_job = SimpleNamespace(
        job_id="job-other",
        name="private task name",
        job_type="active_agent",
        run_once=True,
        enabled=True,
        next_run_time=None,
        payload={"session": "test:group:room", "sender_id": "user-2"},
    )
    cron_mgr = SimpleNamespace(list_jobs=AsyncMock(return_value=[own_job, other_job]))
    context = SimpleNamespace(
        context=SimpleNamespace(
            context=SimpleNamespace(cron_manager=cron_mgr),
            event=SimpleNamespace(
                unified_msg_origin="test:group:room",
                get_sender_id=lambda: "user-1",
            ),
        )
    )

    result = await tool.call(context, action="list")

    assert "job-own | my task" in result
    assert "job-other" not in result
    assert "private task name" not in result
    assert "not created by you are not listed" in result


@pytest.mark.asyncio
async def test_future_task_empty_list_explains_hidden_same_session_tasks():
    tool = FutureTaskTool()
    other_job = SimpleNamespace(
        job_id="job-other",
        name="private task name",
        payload={"session": "test:group:room", "sender_id": "user-2"},
    )
    cron_mgr = SimpleNamespace(list_jobs=AsyncMock(return_value=[other_job]))
    context = SimpleNamespace(
        context=SimpleNamespace(
            context=SimpleNamespace(cron_manager=cron_mgr),
            event=SimpleNamespace(
                unified_msg_origin="test:group:room",
                get_sender_id=lambda: "user-1",
            ),
        )
    )

    result = await tool.call(context, action="list")

    assert result.startswith("No future tasks found for this session.")
    assert "not created by you are not listed" in result
    assert "job-other" not in result
    assert "private task name" not in result
