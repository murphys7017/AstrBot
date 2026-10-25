from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import astrbot.dashboard.services.config_service as config_service_module
from astrbot.dashboard.services.config_service import ConfigService

PROFILE_ID = "profile-to-delete"
PROFILE_ROUTE = "test:FriendMessage:123"


class _AwaitableJsonRequest:
    def __init__(self, profile_id=PROFILE_ID):
        self.profile_id = profile_id

    @property
    async def json(self):
        return {"id": self.profile_id}


class _Router:
    def __init__(self, routing):
        self.umop_to_conf_id = dict(routing)
        self.updates = []

    async def update_routing_data(self, routing):
        self.updates.append(dict(routing))
        self.umop_to_conf_id = dict(routing)


class _FailingRouter(_Router):
    async def update_routing_data(self, routing):
        self.updates.append(dict(routing))
        raise RuntimeError("route persistence unavailable")


class _ConfigManager:
    def __init__(self, *, delete_result):
        self.confs = {PROFILE_ID: object()}
        self.abconf_data = {PROFILE_ID: {"path": "profile.json"}}
        self.delete_result = delete_result

    def delete_conf(self, conf_id):
        if not self.delete_result:
            return False
        self.confs.pop(conf_id, None)
        self.abconf_data.pop(conf_id, None)
        return True


def _service(*, router, config_manager):
    service = ConfigService.__new__(ConfigService)
    service.ucr = router
    service.acm = config_manager
    service.core_lifecycle = SimpleNamespace(
        pipeline_scheduler_mapping={PROFILE_ID: object()},
        reload_subagent_orchestrator_profile=AsyncMock(),
    )
    return service


@pytest.mark.asyncio
async def test_delete_failure_does_not_remove_profile_routes(monkeypatch):
    router = _Router({PROFILE_ROUTE: PROFILE_ID})
    service = _service(
        router=router,
        config_manager=_ConfigManager(delete_result=False),
    )
    monkeypatch.setattr(
        config_service_module,
        "request",
        _AwaitableJsonRequest(),
    )

    result = await service.delete_abconf()

    assert result["status"] == "error"
    assert "路由未修改" in result["message"]
    assert router.umop_to_conf_id == {PROFILE_ROUTE: PROFILE_ID}
    assert router.updates == []


@pytest.mark.asyncio
async def test_delete_success_removes_routes_after_profile(monkeypatch):
    router = _Router({PROFILE_ROUTE: PROFILE_ID, "other:FriendMessage:456": "other"})
    config_manager = _ConfigManager(delete_result=True)
    service = _service(router=router, config_manager=config_manager)
    monkeypatch.setattr(
        config_service_module,
        "request",
        _AwaitableJsonRequest(),
    )

    result = await service.delete_abconf()

    assert result["status"] == "ok"
    assert PROFILE_ID not in config_manager.confs
    assert router.updates == [{"other:FriendMessage:456": "other"}]
    assert router.umop_to_conf_id == {"other:FriendMessage:456": "other"}
    service.core_lifecycle.reload_subagent_orchestrator_profile.assert_awaited_once_with(
        PROFILE_ID
    )


@pytest.mark.asyncio
async def test_delete_missing_profile_cleans_orphaned_routes(monkeypatch):
    router = _Router({PROFILE_ROUTE: PROFILE_ID})
    config_manager = _ConfigManager(delete_result=False)
    config_manager.confs.clear()
    config_manager.abconf_data.clear()
    service = _service(router=router, config_manager=config_manager)
    monkeypatch.setattr(
        config_service_module,
        "request",
        _AwaitableJsonRequest(),
    )

    result = await service.delete_abconf()

    assert result["status"] == "ok"
    assert router.umop_to_conf_id == {}
    assert router.updates == [{}]


@pytest.mark.asyncio
async def test_delete_success_reports_unfinished_route_cleanup(monkeypatch):
    router = _FailingRouter({PROFILE_ROUTE: PROFILE_ID})
    config_manager = _ConfigManager(delete_result=True)
    service = _service(router=router, config_manager=config_manager)
    monkeypatch.setattr(
        config_service_module,
        "request",
        _AwaitableJsonRequest(),
    )

    result = await service.delete_abconf()

    assert result["status"] == "ok"
    assert PROFILE_ID not in config_manager.confs
    assert "路由清理未完成" in result["message"]
    assert result["data"]["partial"] is True
    assert router.umop_to_conf_id == {PROFILE_ROUTE: PROFILE_ID}


@pytest.mark.asyncio
async def test_delete_normalizes_profile_id_before_deleting(monkeypatch):
    router = _Router({PROFILE_ROUTE: PROFILE_ID})
    config_manager = _ConfigManager(delete_result=True)
    service = _service(router=router, config_manager=config_manager)
    monkeypatch.setattr(
        config_service_module,
        "request",
        _AwaitableJsonRequest(" profile-to-delete "),
    )

    result = await service.delete_abconf()

    assert result["status"] == "ok"
    assert PROFILE_ID not in config_manager.confs
    assert router.umop_to_conf_id == {}
