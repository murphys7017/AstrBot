import asyncio
from types import SimpleNamespace

import pytest

from astrbot.dashboard.services.base import DashboardService
from astrbot.dashboard.services.chunked_upload_service import (
    ChunkedUploadError,
    ChunkedUploadService,
)


@pytest.mark.asyncio
async def test_dashboard_service_shutdown_cancels_housekeeping_and_drains_work():
    service = DashboardService(SimpleNamespace(app=None, config=None))
    housekeeping_started = asyncio.Event()
    housekeeping_cancelled = asyncio.Event()
    work_started = asyncio.Event()
    work_finished = asyncio.Event()

    async def housekeeping():
        housekeeping_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            housekeeping_cancelled.set()
            raise

    async def work():
        work_started.set()
        await asyncio.sleep(0)
        work_finished.set()

    service.create_background_task(
        housekeeping(),
        name="test-housekeeping",
    )
    service.create_background_task(
        work(),
        name="test-work",
        cancel_on_shutdown=False,
    )
    await asyncio.gather(housekeeping_started.wait(), work_started.wait())

    await service.shutdown()

    assert housekeeping_cancelled.is_set()
    assert work_finished.is_set()


@pytest.mark.asyncio
async def test_dashboard_service_rejects_new_work_during_shutdown():
    service = DashboardService(SimpleNamespace(app=None, config=None))
    await service.shutdown()

    async def work():
        return None

    with pytest.raises(RuntimeError, match="shutting down"):
        service.create_background_task(work(), name="late-work")


@pytest.mark.asyncio
async def test_chunked_upload_service_rejects_new_sessions_after_shutdown(tmp_path):
    service = ChunkedUploadService(tmp_path)
    await service.shutdown()

    with pytest.raises(ChunkedUploadError, match="shutting down"):
        service.init_session(
            owner="test",
            purpose="chat",
            filename="upload.bin",
            original_filename="upload.bin",
            total_size=1,
        )

    assert not list(tmp_path.iterdir())
