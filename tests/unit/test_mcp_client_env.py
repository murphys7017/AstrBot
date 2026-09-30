from astrbot.core.agent import mcp_client


def test_prepare_stdio_env_uses_astrbot_cache_for_uvx(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_client, "get_astrbot_data_path", lambda: str(tmp_path))
    monkeypatch.setattr(mcp_client.sys, "platform", "win32")
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)

    prepared = mcp_client._prepare_stdio_env({"command": "uvx", "args": []})

    assert prepared["env"]["UV_CACHE_DIR"] == str(tmp_path / "uv-cache")
    assert prepared["env"]["UV_TOOL_DIR"] == str(tmp_path / "uv-tools")
    assert (tmp_path / "uv-cache").is_dir()
    assert (tmp_path / "uv-tools").is_dir()


def test_prepare_stdio_env_preserves_explicit_uv_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_client, "get_astrbot_data_path", lambda: str(tmp_path))
    monkeypatch.setattr(mcp_client.sys, "platform", "win32")

    prepared = mcp_client._prepare_stdio_env(
        {
            "command": "uvx",
            "args": [],
            "env": {"uv_cache_dir": "C:/custom/uv-cache"},
        }
    )

    assert prepared["env"]["uv_cache_dir"] == "C:/custom/uv-cache"
    assert "UV_CACHE_DIR" not in prepared["env"]
    assert prepared["env"]["UV_TOOL_DIR"] == str(tmp_path / "uv-tools")


def test_prepare_stdio_env_preserves_explicit_uv_tool_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_client, "get_astrbot_data_path", lambda: str(tmp_path))
    monkeypatch.setattr(mcp_client.sys, "platform", "win32")

    prepared = mcp_client._prepare_stdio_env(
        {
            "command": "uvx",
            "args": [],
            "env": {"uv_tool_dir": "C:/custom/uv-tools"},
        }
    )

    assert prepared["env"]["uv_tool_dir"] == "C:/custom/uv-tools"
    assert "UV_TOOL_DIR" not in prepared["env"]


def test_prepare_stdio_env_does_not_add_uv_cache_for_other_commands(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(mcp_client, "get_astrbot_data_path", lambda: str(tmp_path))
    monkeypatch.setattr(mcp_client.sys, "platform", "win32")
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)

    prepared = mcp_client._prepare_stdio_env({"command": "python", "args": []})

    assert "UV_CACHE_DIR" not in prepared["env"]
    assert "UV_TOOL_DIR" not in prepared["env"]
    assert not (tmp_path / "uv-cache").exists()
    assert not (tmp_path / "uv-tools").exists()
