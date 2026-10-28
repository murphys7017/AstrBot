import pytest

from astrbot.core.utils import migra_helper


@pytest.mark.asyncio
async def test_required_migration_failure_propagates_to_startup(monkeypatch):
    async def fail_migration(*_args):
        raise RuntimeError("migration failed")

    monkeypatch.setattr(
        migra_helper,
        "migrate_45_to_46",
        fail_migration,
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        await migra_helper.migra(None, None, None, None)
