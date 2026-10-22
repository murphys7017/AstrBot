"""Codex SDK Executor Body adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any, Protocol

from .codex_session import CodexSdkSession
from .contracts import (
    ExecutionFinalUpdate,
    ExecutionOutputMaterial,
    ExecutionProgressUpdate,
    ExecutionResult,
    ExecutionUpdate,
    ExecutorRun,
)


class _CodexSession(Protocol):
    async def iter_turn(self, prompt: str) -> AsyncIterator[Any]: ...


class CodexExecutorRun:
    """Translate one SDK turn into the executor-neutral run contract."""

    executor_id = "codex_cli"

    def __init__(
        self,
        *,
        session: _CodexSession | CodexSdkSession,
        prompt: str,
    ) -> None:
        self._session = session
        self._prompt = prompt
        self._stop_requested = False
        self._turn_task: asyncio.Task[None] | None = None
        self._closed = False
        self._turn_terminal_seen = False

    def request_stop(self) -> None:
        if self._turn_terminal_seen:
            return
        self._stop_requested = True
        task = self._turn_task
        if task is None or task.done():
            return
        if task is asyncio.current_task():
            stop_owned_turn = getattr(self._session, "request_stop_for_task", None)
            if callable(stop_owned_turn):
                stop_owned_turn(task)
        else:
            task.cancel()

    def request_follow_up(self, message_text: str) -> None:
        del message_text
        return None

    def cancel_follow_up(self, ticket: Any) -> bool:
        del ticket
        return False

    def invalidate(self) -> None:
        invalidate = getattr(self._session, "invalidate", None)
        if callable(invalidate):
            invalidate()

    async def aclose(self) -> None:
        self._closed = True
        task = self._turn_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            self.request_stop()
            done, pending = await asyncio.wait({task}, timeout=10.0)
            if pending:
                self.invalidate()

    async def stream(self) -> AsyncIterator[ExecutionUpdate]:
        if self._closed:
            raise RuntimeError("Codex executor run is closed")
        if self._stop_requested:
            raise asyncio.CancelledError("Codex run was stopped before start")
        self._turn_task = asyncio.current_task()
        completed_items: list[Any] = []
        final_result: ExecutionResult | None = None
        terminal_error: RuntimeError | None = None
        turn_cancelled = False
        self._turn_terminal_seen = False
        try:
            async with aclosing(self._session.iter_turn(self._prompt)) as notifications:
                async for notification in notifications:
                    if self._stop_requested and not self._turn_terminal_seen:
                        raise asyncio.CancelledError("Codex run was stopped")
                    method = str(getattr(notification, "method", "") or "")
                    payload = getattr(notification, "payload", None)

                    if self._turn_terminal_seen:
                        continue

                    if method == "turn/started":
                        yield ExecutionProgressUpdate(summary="accepted")
                        continue
                    if method == "item/started":
                        yield ExecutionProgressUpdate(summary="working")
                        continue
                    if method == "item/completed":
                        item = getattr(payload, "item", None)
                        if item is not None:
                            completed_items.append(item)
                        continue
                    if method == "turn/completed":
                        self._turn_terminal_seen = True
                        turn = getattr(payload, "turn", None)
                        status = _enum_value(getattr(turn, "status", None))
                        if status == "interrupted":
                            turn_cancelled = True
                            continue
                        if status != "completed":
                            terminal_error = RuntimeError("Codex turn failed")
                            continue

                        turn_items = list(getattr(turn, "items", ()) or ())
                        final_text = _extract_final_text(
                            [*completed_items, *turn_items]
                        )
                        if not final_text:
                            terminal_error = RuntimeError(
                                "Codex turn completed without a final assistant answer"
                            )
                        else:
                            final_result = ExecutionResult(
                                output=ExecutionOutputMaterial(text=final_text)
                            )
                        continue
                    if method in {"turn/failed", "turn/cancelled"}:
                        self._turn_terminal_seen = True
                        if method == "turn/cancelled":
                            turn_cancelled = True
                        else:
                            terminal_error = RuntimeError("Codex turn failed")
                        continue
                    # Ignore deltas and unknown notifications; they may contain reasoning or tool data.

            if turn_cancelled:
                if self._stop_requested:
                    raise asyncio.CancelledError("Codex turn was cancelled")
                raise RuntimeError("Codex turn was interrupted")
            if terminal_error is not None:
                raise terminal_error
            if final_result is None:
                raise RuntimeError("Codex turn ended without a completed turn")
            yield ExecutionFinalUpdate(result=final_result)
        finally:
            self._turn_task = None


def build_codex_executor_run(
    *,
    session: _CodexSession | CodexSdkSession,
    prompt: str,
) -> ExecutorRun:
    return CodexExecutorRun(session=session, prompt=prompt)


def _enum_value(value: object) -> str | None:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else None


def _extract_final_text(items: list[Any]) -> str:
    final_answers: list[str] = []
    unphased_messages: list[str] = []
    seen_ids: set[str] = set()

    for item in items:
        normalized = getattr(item, "root", item)
        if getattr(normalized, "type", None) != "agentMessage":
            continue
        text = getattr(normalized, "text", None)
        if not isinstance(text, str) or not text.strip():
            continue
        item_id = getattr(normalized, "id", None)
        if isinstance(item_id, str) and item_id in seen_ids:
            continue
        if isinstance(item_id, str):
            seen_ids.add(item_id)

        phase = _enum_value(getattr(normalized, "phase", None))
        if phase == "final_answer":
            final_answers.append(text.strip())
        elif phase is None:
            unphased_messages.append(text.strip())

    candidates = final_answers or unphased_messages
    return candidates[-1] if candidates else ""


__all__ = ["CodexExecutorRun", "build_codex_executor_run"]
