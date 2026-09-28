from types import SimpleNamespace

import pytest

from astrbot.core.execution_ledger import CoreExecutionLedger
from astrbot.core.prompt.collectors import PersonaExecutionContinuityCollector
from astrbot.core.provider.entities import ProviderRequest


class _Ledger(CoreExecutionLedger):
    def __init__(self, records):
        self.records = records
        self.calls = []

    async def recent(self, conversation_id: str, *, limit: int = 8):
        self.calls.append((conversation_id, limit))
        return self.records[-limit:]


@pytest.mark.asyncio
async def test_persona_execution_continuity_collector_projects_only_latest_superseded_task():
    ledger = _Ledger(
        [
            {
                "status": "completed",
                "task_spec": {"task_summary": "completed task"},
                "result": "do not expose",
            },
            {
                "status": "cancelled",
                "error": "deadline_exceeded",
                "task_spec": {"task_summary": "expired task"},
            },
            {
                "status": "cancelled",
                "error": "superseded_by_new_user_input: old task",
                "task_spec": {"task_summary": "older resumable task"},
            },
            {
                "status": "aborted",
                "error": "superseded_by_new_user_input: " + "x" * 300,
                "task_spec": {
                    "task_summary": "latest task " + "y" * 700,
                    "task_intent": "weather " + "z" * 300,
                },
                "tool_evidence": [{"content": "do not expose"}],
                "result": "do not expose",
            },
        ]
    )
    collector = PersonaExecutionContinuityCollector()
    slots = await collector.collect(
        event=SimpleNamespace(),
        plugin_context=SimpleNamespace(core_execution_ledger=ledger),
        config=SimpleNamespace(),
        provider_request=ProviderRequest(
            conversation=SimpleNamespace(cid="conversation-1")
        ),
    )

    assert ledger.calls == [("conversation-1", 1)]
    assert len(slots) == 1
    continuity = slots[0].value
    assert continuity["status"] == "aborted"
    assert continuity["resume_recommended"] is True
    assert continuity["task_summary"].startswith("latest task")
    assert len(continuity["task_summary"]) == 600
    assert continuity["task_intent"].startswith("weather")
    assert len(continuity["task_intent"]) == 240
    assert len(continuity["cancellation_reason"]) == 240
    assert "tool_evidence" not in continuity
    assert "result" not in continuity


@pytest.mark.asyncio
async def test_persona_execution_continuity_ignores_superseded_task_after_completion():
    ledger = _Ledger(
        [
            {
                "status": "cancelled",
                "error": "superseded_by_new_user_input",
                "task_spec": {"task_summary": "old interrupted task"},
            },
            {
                "status": "completed",
                "task_spec": {"task_summary": "new completed task"},
            },
        ]
    )
    slots = await PersonaExecutionContinuityCollector().collect(
        event=SimpleNamespace(),
        plugin_context=SimpleNamespace(core_execution_ledger=ledger),
        config=SimpleNamespace(),
        provider_request=ProviderRequest(
            conversation=SimpleNamespace(cid="conversation-1")
        ),
    )

    assert ledger.calls == [("conversation-1", 1)]
    assert slots == []
