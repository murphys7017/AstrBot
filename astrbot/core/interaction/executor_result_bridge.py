"""Bridge executor-neutral final results into the existing Interaction output path."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from astrbot.core import logger
from astrbot.core.deadline import TurnDeadlineBudget
from astrbot.core.execution import CoreExecutionEventKind, CoreExecutionHead
from astrbot.core.executors.contracts import (
    ExecutionFinalUpdate,
    ExecutionOutputUpdate,
    ExecutionProgressUpdate,
    ExecutionResult,
    ExecutionUpdate,
)
from astrbot.core.executors.runtime import drive_executor_run
from astrbot.core.message.message_event_result import MessageChain

from .output_controller import InteractionOutputController
from .turn_state import get_interaction_turn_state

_VISIBLE_PROGRESS_STAGES = frozenset({"accepted", "working"})


@dataclass(slots=True)
class ExecutionResultOutputBridge:
    """Accept visible executor result text without exposing platform delivery.

    ``AssetRef`` deliberately contains safe identity metadata rather than a
    sendable local path or URL. Assets therefore remain Core evidence until a
    concrete Body supplies an explicit safe attachment-delivery contract.
    """

    event: object
    output_controller: InteractionOutputController
    head: CoreExecutionHead
    _final_delivery_started: bool = field(default=False, init=False)
    _last_progress_stage: str | None = field(default=None, init=False)
    _incremental_stream_queue: asyncio.Queue[MessageChain | None] | None = field(
        default=None,
        init=False,
    )
    _incremental_stream_task: asyncio.Task[None] | None = field(
        default=None,
        init=False,
    )
    _incremental_text: str = field(default="", init=False)
    _incremental_stream_failed: bool = field(default=False, init=False)

    async def accept(self, update: ExecutionUpdate) -> None:
        """Handle result-bearing updates while the execution is still current."""

        if not self._can_accept_result():
            logger.debug(
                "Discarding executor result after Core termination: execution_id=%s",
                self.head.spec.execution_id,
            )
            return
        if isinstance(update, ExecutionOutputUpdate):
            await self._accept_incremental_output(update)
            return
        if isinstance(update, ExecutionProgressUpdate):
            stage = str(update.summary or "").strip().lower()
            if stage not in _VISIBLE_PROGRESS_STAGES or stage == self._last_progress_stage:
                return
            self._last_progress_stage = stage
            try:
                await self.output_controller.deliver_core_execution_progress(
                    stage,
                    self.event,
                )
            except Exception:
                logger.warning(
                    "Core executor progress delivery failed; continuing run: "
                    "execution_id=%s stage=%s",
                    self.head.spec.execution_id,
                    stage,
                    exc_info=True,
                )
            return
        if isinstance(update, ExecutionFinalUpdate):
            await self.deliver_final(update.result)

    async def deliver_final(self, result: ExecutionResult) -> bool:
        """Deliver final text via Personal's existing Core-final expression path."""

        if not self._can_accept_result():
            return False
        output = result.output
        text = str(output.text or "").strip() if output is not None else ""
        if not text and self._incremental_text:
            text = self._incremental_text.strip()
        if not text or self._final_delivery_started:
            return False
        if self._incremental_stream_queue is not None:
            suffix = self._incremental_suffix(text)
            if suffix:
                await self._publish_incremental_text(suffix)
            await self._close_incremental_stream()
            if not self._incremental_stream_failed:
                self._final_delivery_started = True
                return True
        self._final_delivery_started = True
        if output is not None and output.assets:
            logger.info(
                "Executor result contains deferred asset references: "
                "execution_id=%s asset_count=%s",
                self.head.spec.execution_id,
                len(output.assets),
            )
        await self.output_controller.deliver_core_execution_result(
            MessageChain().message(text),
            self.event,
        )
        return True

    async def _accept_incremental_output(
        self,
        update: ExecutionOutputUpdate,
    ) -> None:
        output = update.output
        text = str(output.text or "") if output is not None else ""
        if not text:
            return
        self._incremental_text += text
        if output.assets:
            logger.info(
                "Executor incremental output contains deferred asset references: "
                "execution_id=%s asset_count=%s",
                self.head.spec.execution_id,
                len(output.assets),
            )
        if not self._supports_incremental_streaming():
            return
        await self._ensure_incremental_stream()
        await self._publish_incremental_text(text)

    def _supports_incremental_streaming(self) -> bool:
        enabled = self.event.get_extra("enable_streaming")
        if enabled is False:
            return False
        metadata = getattr(self.event, "platform_meta", None)
        return bool(getattr(metadata, "support_streaming_message", False))

    async def _ensure_incremental_stream(self) -> None:
        if self._incremental_stream_queue is not None:
            return
        queue = asyncio.Queue()
        self._incremental_stream_queue = queue

        async def source():
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item

        self._incremental_stream_task = asyncio.create_task(
            self.output_controller.capture_streaming(source(), self.event),
            name=f"core-executor-stream:{self.head.spec.execution_id}",
        )

    async def _publish_incremental_text(self, text: str) -> None:
        queue = self._incremental_stream_queue
        if queue is None or self._incremental_stream_failed:
            return
        try:
            await queue.put(MessageChain().message(text))
        except Exception:
            self._incremental_stream_failed = True
            logger.warning(
                "Core executor incremental output enqueue failed: execution_id=%s",
                self.head.spec.execution_id,
                exc_info=True,
            )

    def _incremental_suffix(self, final_text: str) -> str:
        if final_text.startswith(self._incremental_text):
            return final_text[len(self._incremental_text) :]
        if self._incremental_text.startswith(final_text):
            return ""
        logger.warning(
            "Core executor incremental output diverged from final result: "
            "execution_id=%s incremental_chars=%s final_chars=%s",
            self.head.spec.execution_id,
            len(self._incremental_text),
            len(final_text),
        )
        return final_text

    async def _close_incremental_stream(self) -> None:
        queue = self._incremental_stream_queue
        task = self._incremental_stream_task
        self._incremental_stream_queue = None
        self._incremental_stream_task = None
        if queue is None or task is None:
            return
        await queue.put(None)
        try:
            await task
        except asyncio.CancelledError:
            raise
        except Exception:
            self._incremental_stream_failed = True
            logger.warning(
                "Core executor incremental stream failed: execution_id=%s",
                self.head.spec.execution_id,
                exc_info=True,
            )

    async def close(self) -> None:
        """Close an unfinished incremental stream during cancellation or failure."""

        if self._incremental_stream_queue is not None:
            await self._close_incremental_stream()

    def _can_accept_result(self) -> bool:
        """Allow a just-completed result, but reject replaced executions."""

        terminal = self.head.terminal_event
        if terminal is None:
            return True
        return getattr(terminal, "kind", None) is CoreExecutionEventKind.COMPLETED


async def drive_executor_to_personal_output(
    *,
    event: object,
    output_controller: InteractionOutputController,
    head: CoreExecutionHead,
    body,
    run,
    deadline: TurnDeadlineBudget | None = None,
    submission_metadata: dict | None = None,
    executor_lease: object | None = None,
):
    """Drive any Executor Body and route its final material through Personal.

    This is the shared C5 boundary: executor updates remain executor-neutral,
    while only ``ExecutionResultOutputBridge`` can create visible Core output.
    """

    bridge = ExecutionResultOutputBridge(
        event=event,
        output_controller=output_controller,
        head=head,
    )
    state = (
        get_interaction_turn_state(event)
        if callable(getattr(event, "get_extra", None))
        else None
    )
    try:
        return await drive_executor_run(
            head=head,
            body=body,
            run=run,
            deadline=deadline,
            submission_metadata=submission_metadata,
            output_sink=bridge.accept,
            executor_lease=executor_lease,
            cleanup_scope=state.execution_scope if state is not None else None,
        )
    finally:
        await bridge.close()


__all__ = ["ExecutionResultOutputBridge", "drive_executor_to_personal_output"]
