from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import OperationalError

from astrbot.core.db import BaseDatabase
from astrbot.core.db.po import CoreExecutionRecord

if TYPE_CHECKING:
    from astrbot.core.execution import CoreExecutionSpec


class CoreExecutionLedger:
    """Own persistence and retrieval of Core executor attempts."""

    def __init__(self, db: BaseDatabase, *, retain_per_conversation: int = 32) -> None:
        self._db = db
        self._retain = max(1, int(retain_per_conversation))

    @property
    def retain_per_conversation(self) -> int:
        """Return the canonical retained history horizon for one conversation."""
        return self._retain

    async def append(self, record: CoreExecutionRecord) -> bool:
        last_error: OperationalError | None = None
        for attempt in range(3):
            try:
                return await self._db.insert_core_execution_record(
                    record,
                    retain=self._retain,
                )
            except OperationalError as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.05 * (2**attempt))
        if last_error is not None:
            raise last_error
        return False

    async def append_execution(
        self,
        *,
        execution_spec: CoreExecutionSpec,
        conversation_id: str,
        executor_id: str,
        status: str,
        messages: list[dict[str, Any]] | None = None,
        result: str | None = None,
        error: str | None = None,
        token_usage: dict[str, Any] | None = None,
    ) -> bool:
        """Materialize and persist one executor attempt from Core facts."""

        record = CoreExecutionRecord(
            execution_id=execution_spec.execution_id,
            conversation_id=conversation_id,
            turn_id=execution_spec.turn_id,
            core_task_id=execution_spec.core_task_id,
            parent_execution_id=execution_spec.parent_execution_id,
            attempt=execution_spec.attempt,
            executor_id=executor_id,
            status=status,
            task_spec=execution_spec.task_spec,
            messages=messages,
            result=result,
            error=error,
            token_usage=token_usage,
        )
        return await self.append(record)

    async def recent(
        self,
        conversation_id: str,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        records = await self._db.get_recent_core_execution_records(
            conversation_id,
            limit=limit,
        )
        return [_record_to_prompt_payload(record) for record in records]


def _record_to_prompt_payload(record: CoreExecutionRecord) -> dict[str, Any]:
    return {
        "status": record.status,
        "task_spec": {
            key: record.task_spec[key]
            for key in (
                "task_intent",
                "task_summary",
                "execution_prompt",
                "suggested_capabilities",
                "requires_visual_understanding",
            )
            if key in (record.task_spec or {})
        },
        "tool_evidence": _summarize_execution_messages(record.messages or []),
        "result": _bounded_text(record.result, limit=4000),
        "error": _bounded_text(record.error, limit=2000),
    }


def _summarize_execution_messages(messages: list) -> list[dict[str, Any]]:
    # Resolve identities before trimming history; a result can outlive its call.
    tool_calls_by_id = {
        str(call["id"]): _summarize_tool_call(call)
        for message in messages
        if isinstance(message, dict)
        if isinstance(message.get("tool_calls"), list)
        for call in message["tool_calls"]
        if isinstance(call, dict)
        and call.get("id")
        and isinstance(call.get("function"), dict)
    }
    evidence: list[dict[str, Any]] = []
    for message in messages[-8:]:
        if not isinstance(message, dict):
            continue
        item: dict[str, Any] = {"role": str(message.get("role", ""))}
        content = message.get("content")
        if content is not None:
            serialized = (
                content
                if isinstance(content, str)
                else json.dumps(content, ensure_ascii=False, default=str)
            )
            item["content"] = _bounded_text(serialized, limit=1200)
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            item["tool_calls"] = [
                _summarize_tool_call(call)
                for call in tool_calls[:8]
                if isinstance(call, dict)
            ]
        tool_call_id = message.get("tool_call_id")
        tool_call = tool_calls_by_id.get(str(tool_call_id))
        if tool_call is not None:
            # Include arguments as well: parallel calls to the same tool can
            # return in any order, so a tool name alone loses result ownership.
            item.update(tool_call)
        elif message.get("name"):
            item["name"] = str(message["name"])
        evidence.append(item)
    return evidence


def _summarize_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function")
    if not isinstance(function, dict):
        return {"type": call.get("type")}
    arguments = function.get("arguments")
    serialized_arguments = (
        arguments
        if isinstance(arguments, str)
        else json.dumps(arguments, ensure_ascii=False, default=str)
    )
    return {
        "name": function.get("name"),
        "arguments": _bounded_text(serialized_arguments, limit=1000),
    }


def _bounded_text(value: str | None, *, limit: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text if len(text) <= limit else f"{text[:limit]}..."


__all__ = ["CoreExecutionLedger"]
