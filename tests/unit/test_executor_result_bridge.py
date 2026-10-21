from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.execution import CoreExecutionEventKind, CoreExecutionSpec
from astrbot.core.executors.contracts import (
    ExecutionFinalUpdate,
    ExecutionOutputMaterial,
    ExecutionProgressUpdate,
    ExecutionResult,
)
from astrbot.core.interaction.executor_result_bridge import ExecutionResultOutputBridge
from astrbot.core.prompt.context_types import ContextPack


@pytest.mark.asyncio
async def test_execution_result_bridge_uses_existing_core_final_output_boundary():
    deliver = AsyncMock()
    controller = SimpleNamespace(deliver_core_execution_result=deliver)
    head = SimpleNamespace(
        terminal_event=None,
        spec=CoreExecutionSpec.from_context_pack(
            context_pack=ContextPack(),
            turn_id="turn-1",
        ),
    )
    event = object()
    bridge = ExecutionResultOutputBridge(
        event=event,
        output_controller=controller,
        head=head,
    )

    await bridge.accept(
        ExecutionFinalUpdate(
            ExecutionResult(output=ExecutionOutputMaterial(text="final answer"))
        )
    )

    deliver.assert_awaited_once()
    message, delivered_event = deliver.await_args.args
    assert message.get_plain_text() == "final answer"
    assert delivered_event is event


@pytest.mark.asyncio
async def test_execution_result_bridge_discards_late_final_result():
    deliver = AsyncMock()
    controller = SimpleNamespace(deliver_core_execution_result=deliver)
    head = SimpleNamespace(
        terminal_event=SimpleNamespace(kind=CoreExecutionEventKind.CANCELLED),
        spec=CoreExecutionSpec.from_context_pack(
            context_pack=ContextPack(),
            turn_id="turn-1",
        ),
    )
    bridge = ExecutionResultOutputBridge(
        event=object(),
        output_controller=controller,
        head=head,
    )

    await bridge.accept(
        ExecutionFinalUpdate(
            ExecutionResult(output=ExecutionOutputMaterial(text="late answer"))
        )
    )

    deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_execution_result_bridge_allows_final_delivery_after_completion():
    deliver = AsyncMock()
    controller = SimpleNamespace(deliver_core_execution_result=deliver)
    head = SimpleNamespace(
        terminal_event=SimpleNamespace(kind=CoreExecutionEventKind.COMPLETED),
        spec=CoreExecutionSpec.from_context_pack(
            context_pack=ContextPack(),
            turn_id="turn-1",
        ),
    )
    bridge = ExecutionResultOutputBridge(
        event=object(),
        output_controller=controller,
        head=head,
    )

    await bridge.accept(
        ExecutionFinalUpdate(
            ExecutionResult(output=ExecutionOutputMaterial(text="final answer"))
        )
    )

    deliver.assert_awaited_once()

    await bridge.accept(
        ExecutionFinalUpdate(
            ExecutionResult(output=ExecutionOutputMaterial(text="duplicate answer"))
        )
    )

    deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_execution_progress_bridge_allowlists_stages_and_deduplicates():
    deliver_progress = AsyncMock(return_value=True)
    controller = SimpleNamespace(
        deliver_core_execution_progress=deliver_progress,
        deliver_core_execution_result=AsyncMock(),
    )
    head = SimpleNamespace(
        terminal_event=None,
        spec=CoreExecutionSpec.from_context_pack(
            context_pack=ContextPack(),
            turn_id="turn-1",
        ),
    )
    event = object()
    bridge = ExecutionResultOutputBridge(
        event=event,
        output_controller=controller,
        head=head,
    )

    await bridge.accept(ExecutionProgressUpdate(summary="accepted"))
    await bridge.accept(ExecutionProgressUpdate(summary="accepted"))
    await bridge.accept(ExecutionProgressUpdate(summary="run rm -rf"))
    await bridge.accept(ExecutionProgressUpdate(summary="working"))

    assert [call.args[0] for call in deliver_progress.await_args_list] == [
        "accepted",
        "working",
    ]
    assert all(call.args[1] is event for call in deliver_progress.await_args_list)


@pytest.mark.asyncio
async def test_execution_progress_bridge_discards_updates_after_cancellation():
    deliver_progress = AsyncMock()
    controller = SimpleNamespace(
        deliver_core_execution_progress=deliver_progress,
        deliver_core_execution_result=AsyncMock(),
    )
    head = SimpleNamespace(
        terminal_event=SimpleNamespace(kind=CoreExecutionEventKind.CANCELLED),
        spec=CoreExecutionSpec.from_context_pack(
            context_pack=ContextPack(),
            turn_id="turn-1",
        ),
    )
    bridge = ExecutionResultOutputBridge(
        event=object(),
        output_controller=controller,
        head=head,
    )

    await bridge.accept(ExecutionProgressUpdate(summary="working"))

    deliver_progress.assert_not_awaited()


@pytest.mark.asyncio
async def test_execution_progress_delivery_failure_does_not_escape_bridge():
    deliver_progress = AsyncMock(side_effect=RuntimeError("progress transport failed"))
    controller = SimpleNamespace(
        deliver_core_execution_progress=deliver_progress,
        deliver_core_execution_result=AsyncMock(),
    )
    head = SimpleNamespace(
        terminal_event=None,
        spec=CoreExecutionSpec.from_context_pack(
            context_pack=ContextPack(),
            turn_id="turn-1",
        ),
    )
    bridge = ExecutionResultOutputBridge(
        event=object(),
        output_controller=controller,
        head=head,
    )

    await bridge.accept(ExecutionProgressUpdate(summary="working"))

    deliver_progress.assert_awaited_once_with("working", bridge.event)
