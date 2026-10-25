import pytest

from astrbot.core.execution import CoreExecutionSpec
from astrbot.core.execution_ledger import CoreExecutionLedger
from astrbot.core.prompt.context_types import ContextPack


class _Database:
    def __init__(self) -> None:
        self.records = []

    async def insert_core_execution_record(self, record, *, retain: int) -> bool:
        self.records.append((record, retain))
        return True

    async def get_recent_core_execution_records(self, conversation_id, *, limit):
        return [
            record
            for record, _ in self.records
            if record.conversation_id == conversation_id
        ][-limit:]


@pytest.mark.asyncio
async def test_append_execution_materializes_record_from_spec():
    spec = CoreExecutionSpec.from_context_pack(
        context_pack=ContextPack(),
        turn_id="turn-1",
        task_spec={"metadata": {"core_task_id": "task-1"}},
        parent_execution_id="parent-1",
    )
    database = _Database()
    ledger = CoreExecutionLedger(database, retain_per_conversation=7)

    assert await ledger.append_execution(
        execution_spec=spec,
        conversation_id="conversation-1",
        executor_id="native",
        status="completed",
        messages=[{"role": "tool", "content": "evidence"}],
        result="done",
        token_usage={"total": 12},
    )

    record, retain = database.records[0]
    assert retain == 7
    assert record.execution_id == spec.execution_id
    assert record.core_task_id == "task-1"
    assert record.conversation_id == "conversation-1"
    assert record.turn_id == "turn-1"
    assert record.parent_execution_id == "parent-1"
    assert record.executor_id == "native"
    assert record.status == "completed"
    assert record.task_spec == spec.task_spec
    assert record.messages == [{"role": "tool", "content": "evidence"}]
    assert record.result == "done"
    assert record.token_usage == {"total": 12}


@pytest.mark.asyncio
async def test_recent_execution_keeps_semantic_tool_pairing_without_tracking_ids():
    import json

    spec = CoreExecutionSpec.from_context_pack(
        context_pack=ContextPack(),
        turn_id="internal-turn",
        task_spec={
            "task_summary": "Compare results",
            "metadata": {"core_task_id": "internal-task"},
        },
    )
    database = _Database()
    ledger = CoreExecutionLedger(database)
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "internal-call-a",
                    "function": {"name": "search", "arguments": '{"query":"first"}'},
                },
                {
                    "id": "internal-call-b",
                    "function": {"name": "search", "arguments": '{"query":"second"}'},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "internal-call-b",
            "content": {"session_id": "business-session", "result": "second result"},
        },
        {"role": "tool", "tool_call_id": "internal-call-a", "content": "first result"},
    ]
    await ledger.append_execution(
        execution_spec=spec,
        conversation_id="internal-conversation",
        executor_id="internal-executor",
        status="completed",
        messages=messages,
        result="Compared results",
    )

    records = await ledger.recent("internal-conversation")

    serialized = json.dumps(records)
    assert "internal-" not in serialized
    assert "business-session" in serialized
    assert records[0]["tool_evidence"][1]["arguments"] == '{"query":"second"}'
    assert records[0]["tool_evidence"][2]["arguments"] == '{"query":"first"}'
    assert database.records[0][0].messages == messages
