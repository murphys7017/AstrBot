import asyncio
from types import SimpleNamespace

import pytest

from astrbot.core.executors.codex_cli import CodexExecutorRun
from astrbot.core.executors.contracts import (
    ExecutionFinalUpdate,
    ExecutionProgressUpdate,
)


class _Session:
    def __init__(self, events):
        self.events = events
        self.interrupted = False

    async def iter_turn(self, prompt):
        assert prompt == "inspect"
        for event in self.events:
            yield event

    async def interrupt(self, turn_id=None):
        self.interrupted = True


class _DrainAfterCompletionSession(_Session):
    def __init__(self):
        super().__init__([])
        self.terminal_consumed = asyncio.Event()
        self.allow_end = asyncio.Event()
        self.ended = False

    async def iter_turn(self, prompt):
        assert prompt == "inspect"
        yield SimpleNamespace(
            method="turn/completed",
            payload=SimpleNamespace(
                turn=SimpleNamespace(
                    status="completed",
                    items=[
                        SimpleNamespace(
                            type="agentMessage",
                            id="final-1",
                            phase="final_answer",
                            text="done",
                        )
                    ],
                )
            ),
        )
        self.terminal_consumed.set()
        await self.allow_end.wait()
        self.ended = True


@pytest.mark.asyncio
async def test_codex_run_emits_progress_and_one_final_text():
    turn = SimpleNamespace(
        status="completed",
        items=[
            SimpleNamespace(
                type="agentMessage",
                id="final-1",
                phase="final_answer",
                text="done",
            )
        ],
    )
    run = CodexExecutorRun(
        session=_Session(
            [
                SimpleNamespace(method="turn/started", payload=None),
                SimpleNamespace(
                    method="item/agentMessage/delta",
                    payload=SimpleNamespace(delta="hidden intermediate"),
                ),
                SimpleNamespace(
                    method="turn/completed",
                    payload=SimpleNamespace(turn=turn),
                ),
            ]
        ),
        prompt="inspect",
    )

    updates = [update async for update in run.stream()]

    assert len(updates) == 2
    assert isinstance(updates[0], ExecutionProgressUpdate)
    assert isinstance(updates[1], ExecutionFinalUpdate)
    assert updates[1].result.output.text == "done"
    await run.aclose()


@pytest.mark.asyncio
async def test_codex_run_rejects_failed_turn():
    run = CodexExecutorRun(
        session=_Session(
            [
                SimpleNamespace(
                    method="turn/completed",
                    payload=SimpleNamespace(
                        turn=SimpleNamespace(status="failed", items=[])
                    ),
                )
            ]
        ),
        prompt="inspect",
    )

    with pytest.raises(RuntimeError, match="Codex turn failed"):
        _ = [update async for update in run.stream()]


@pytest.mark.asyncio
async def test_codex_run_drains_completed_turn_before_final_and_ignores_late_stop():
    session = _DrainAfterCompletionSession()
    run = CodexExecutorRun(session=session, prompt="inspect")
    updates_task = asyncio.create_task(_collect_updates(run))

    await asyncio.wait_for(session.terminal_consumed.wait(), timeout=1)
    assert not updates_task.done()

    run.request_stop()
    await asyncio.sleep(0)
    assert session.interrupted is False
    assert not updates_task.done()

    session.allow_end.set()
    updates = await asyncio.wait_for(updates_task, timeout=1)

    assert session.ended is True
    assert len(updates) == 1
    assert isinstance(updates[0], ExecutionFinalUpdate)
    assert updates[0].result.output.text == "done"
    await run.aclose()


async def _collect_updates(run):
    return [update async for update in run.stream()]
