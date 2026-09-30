from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.core.initial_loader import InitialLoader


@pytest.mark.asyncio
async def test_runtime_failure_propagates_after_lifecycle_cleanup(monkeypatch):
    lifecycle = MagicMock()
    lifecycle.dashboard_shutdown_event = object()
    lifecycle.initialize = AsyncMock()
    lifecycle.start = AsyncMock(side_effect=RuntimeError("runtime failed"))
    lifecycle.stop = AsyncMock()

    dashboard = MagicMock()
    dashboard.run.return_value = None

    monkeypatch.setattr(
        "astrbot.core.initial_loader.AstrBotCoreLifecycle",
        MagicMock(return_value=lifecycle),
    )
    monkeypatch.setattr(
        "astrbot.core.initial_loader.AstrBotDashboard",
        MagicMock(return_value=dashboard),
    )

    loader = InitialLoader(MagicMock(), MagicMock())
    with pytest.raises(RuntimeError, match="runtime failed"):
        await loader.start()

    lifecycle.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_initialization_failure_still_cleans_up(monkeypatch):
    lifecycle = MagicMock()
    lifecycle.initialize = AsyncMock(side_effect=RuntimeError("init failed"))
    lifecycle.start = AsyncMock()
    lifecycle.stop = AsyncMock()

    monkeypatch.setattr(
        "astrbot.core.initial_loader.AstrBotCoreLifecycle",
        MagicMock(return_value=lifecycle),
    )

    loader = InitialLoader(MagicMock(), MagicMock())
    with monkeypatch.context() as patch_context:
        patch_context.setattr("astrbot.core.initial_loader.logger", MagicMock())
        await loader.start()

    lifecycle.start.assert_not_awaited()
    lifecycle.stop.assert_awaited_once()
