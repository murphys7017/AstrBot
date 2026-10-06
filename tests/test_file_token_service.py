import pytest

from astrbot.core.file_token_service import FileTokenService


@pytest.mark.asyncio
async def test_reusable_tokens_preserve_single_use_and_expiration(tmp_path):
    path = tmp_path / "logo.png"
    path.write_bytes(b"logo")
    service = FileTokenService()

    reusable = await service.register_file(str(path), single_use=False)
    assert await service.handle_file(reusable) == str(path)
    assert await service.handle_file(reusable) == str(path)
    assert not await service.check_token_expired(reusable)

    single_use = await service.register_file(str(path))
    assert await service.handle_file(single_use) == str(path)
    with pytest.raises(KeyError):
        await service.handle_file(single_use)

    expired = await service.register_file(str(path), timeout=-1, single_use=False)
    with pytest.raises(KeyError):
        await service.handle_file(expired)

    path.unlink()
    with pytest.raises(FileNotFoundError):
        await service.handle_file(reusable)
    assert await service.check_token_expired(reusable)
