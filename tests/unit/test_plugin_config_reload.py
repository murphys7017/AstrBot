import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import astrbot.dashboard.services.config_service as module
from astrbot.dashboard.services.config_service import ConfigService


@pytest.mark.asyncio
async def test_plugin_config_save_reports_reload_failure(monkeypatch):
    request_json = asyncio.get_running_loop().create_future()
    request_json.set_result({"enabled": True})
    monkeypatch.setattr(
        module,
        "request",
        SimpleNamespace(
            json=request_json,
            args={"plugin_name": "demo"},
        ),
    )

    service = object.__new__(ConfigService)
    service._save_plugin_configs = AsyncMock()
    service.core_lifecycle = SimpleNamespace(
        plugin_manager=SimpleNamespace(
            reload=AsyncMock(return_value=(False, "import failed")),
        )
    )

    response = await service.post_plugin_configs()

    assert response["status"] == "error"
    assert "配置已保存，但重载失败" in response["message"]
    assert "import failed" in response["message"]
    service.core_lifecycle.plugin_manager.reload.assert_awaited_once_with("demo")
