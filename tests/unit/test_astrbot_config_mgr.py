import json

import astrbot.core.astrbot_config_mgr as config_manager_module
from astrbot.core.astrbot_config_mgr import AstrBotConfigManager
from astrbot.core.config.default import DEFAULT_CONFIG
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType


class _RecordingConfigRouter:
    def __init__(self) -> None:
        self.origins: list[str] = []

    def get_conf_id_for_umop(self, umo: str) -> str | None:
        self.origins.append(umo)
        if umo == "alice:FriendMessage:815049548":
            return "alice-config"
        return None


def test_message_session_uses_canonical_umo_for_config_routing() -> None:
    default_config = object()
    alice_config = object()
    router = _RecordingConfigRouter()
    manager = AstrBotConfigManager.__new__(AstrBotConfigManager)
    manager.ucr = router
    manager.abconf_data = {
        "alice-config": {
            "path": "alice.json",
            "name": "Alice",
        }
    }
    manager.confs = {
        "default": default_config,
        "alice-config": alice_config,
    }
    session = MessageSession(
        "alice",
        MessageType.FRIEND_MESSAGE,
        "815049548",
    )

    assert manager.get_conf(session) is alice_config
    assert manager.get_conf_info(session)["id"] == "alice-config"
    assert router.origins == [
        "alice:FriendMessage:815049548",
        "alice:FriendMessage:815049548",
    ]


def test_create_profile_does_not_copy_system_executor_setting(tmp_path, monkeypatch):
    class _Preferences:
        def get(self, _key, default=None, **_kwargs):
            return default

        def put(self, _key, _value, **_kwargs):
            return None

    manager = AstrBotConfigManager.__new__(AstrBotConfigManager)
    manager.sp = _Preferences()
    manager.confs = {"default": object()}
    manager.abconf_data = {}
    monkeypatch.setattr(
        config_manager_module, "get_astrbot_config_path", lambda: str(tmp_path)
    )

    profile_id = manager.create_conf()

    profile = manager.confs[profile_id]
    profile_path = tmp_path / f"abconf_{profile_id}.json"
    persisted = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    assert "core_executor" not in profile
    assert "core_executor" not in persisted
    assert "core_executor" in DEFAULT_CONFIG


def test_load_profile_removes_stale_system_executor_copy(tmp_path, monkeypatch):
    profile_id = "profile-codex"
    profile_path = tmp_path / "profile-codex.json"
    profile_path.write_text(
        json.dumps(
            {
                "core_executor": {"active_executor_id": "native"},
                "core_execution": {
                    "executor_id": "codex_cli",
                    "codex_cli": {"provider_id": "codex-main"},
                },
            }
        ),
        encoding="utf-8",
    )

    class _Preferences:
        def get(self, _key, default=None, **_kwargs):
            return {
                profile_id: {"path": profile_path.name, "name": "Codex profile"}
            }

    monkeypatch.setattr(
        AstrBotConfigManager,
        "_migrate_profile_resources_to_global_owner",
        lambda _self: None,
    )
    monkeypatch.setattr(
        config_manager_module, "get_astrbot_config_path", lambda: str(tmp_path)
    )
    manager = AstrBotConfigManager(
        default_config=object(),
        ucr=object(),
        sp=_Preferences(),
    )

    profile = manager.confs[profile_id]
    persisted = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    assert "core_executor" not in profile
    assert "core_executor" not in persisted
    assert profile["core_execution"]["executor_id"] == "codex_cli"
    assert persisted["core_execution"]["executor_id"] == "codex_cli"
