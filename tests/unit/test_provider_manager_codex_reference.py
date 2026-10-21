import asyncio
from types import SimpleNamespace

import pytest

import astrbot.api  # noqa: F401
from astrbot.core.provider.manager import ProviderManager


class _Config(dict):
    def save_config(self):
        pass


@pytest.mark.parametrize(
    (
        "active_executor_id",
        "profile_executor_id",
        "delete_by_source",
        "change_type",
    ),
    [
        ("codex_cli", "native", False, False),
        ("codex_cli", "native", True, False),
        ("native", "codex_cli", False, False),
        ("codex_cli", "native", False, True),
    ],
)
@pytest.mark.asyncio
async def test_mutating_referenced_codex_provider_is_rejected(
    active_executor_id,
    profile_executor_id,
    delete_by_source,
    change_type,
):
    provider = {
        "id": "codex-main",
        "type": "codex_cli",
        "provider_source_id": "codex-source",
    }
    default_config = _Config(
        core_executor={"active_executor_id": active_executor_id},
        provider=[provider],
    )
    manager = object.__new__(ProviderManager)
    manager.acm = SimpleNamespace(
        default_conf=default_config,
        confs={
            "default": {
                "core_execution": {
                    "executor_id": profile_executor_id,
                    "codex_cli": {"provider_id": "codex-main"},
                }
            }
        },
    )
    manager.resource_lock = asyncio.Lock()
    manager.providers_config = [provider]
    manager.get_provider_config_by_id = lambda _provider_id, merged=False: provider

    with pytest.raises(ValueError, match="Codex CLI Core executor is referenced"):
        if change_type:
            await manager.update_provider(
                "codex-main",
                {**provider, "type": "chat_completion", "enable": True},
            )
        elif delete_by_source:
            await manager.delete_provider(provider_source_id="codex-source")
        else:
            await manager.delete_provider(provider_id="codex-main")

    assert default_config["provider"] == [provider]
