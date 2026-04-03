from __future__ import annotations

from pathlib import Path

from astrbot.core.memory.config import (
    build_default_memory_config_payload,
    ensure_memory_config_file,
    load_memory_config,
)


def test_ensure_memory_config_file_creates_default_yaml(temp_dir: Path):
    config_path = temp_dir / "memory" / "config.yaml"

    written_path = ensure_memory_config_file(config_path)

    assert written_path == config_path
    assert config_path.exists()
    content = config_path.read_text(encoding="utf-8")
    assert "storage:" in content
    assert "sqlite_path: data/memory/memory.db" in content
    assert "vector_index:" in content


def test_load_memory_config_creates_missing_file_and_uses_defaults(
    temp_dir: Path,
    monkeypatch,
):
    monkeypatch.setenv("ASTRBOT_ROOT", str(temp_dir / "runtime-root"))
    config_path = temp_dir / "runtime" / "config.yaml"

    config = load_memory_config(config_path)

    assert config_path.exists()
    assert config.enabled is True
    assert config.storage.sqlite_path == (
        temp_dir / "runtime-root" / "data/memory/memory.db"
    )
    assert config.storage.docs_root == (
        temp_dir / "runtime-root" / "data/memory/long_term"
    )
    assert config.storage.projections_root == (
        temp_dir / "runtime-root" / "data/memory/projections"
    )
    assert config.storage.docs_root.exists()
    assert config.storage.projections_root.exists()


def test_load_memory_config_reads_explicit_values(temp_dir: Path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(temp_dir / "astrbot-root"))
    config_path = temp_dir / "memory-config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "enabled: false",
                "storage:",
                '  sqlite_path: "custom/memory.sqlite3"',
                '  docs_root: "custom/long_term"',
                '  projections_root: "custom/projections"',
                "short_term:",
                "  enabled: false",
                "  recent_turns_window: 16",
                "consolidation:",
                "  min_short_term_updates: 20",
                "vector_index:",
                "  enabled: false",
                "  experience_top_k: 9",
            ]
        ),
        encoding="utf-8",
    )

    config = load_memory_config(config_path)

    assert config.enabled is False
    assert config.storage.sqlite_path == (
        temp_dir / "astrbot-root" / "custom/memory.sqlite3"
    )
    assert config.storage.docs_root == (temp_dir / "astrbot-root" / "custom/long_term")
    assert config.storage.projections_root == (
        temp_dir / "astrbot-root" / "custom/projections"
    )
    assert config.short_term.enabled is False
    assert config.short_term.recent_turns_window == 16
    assert config.consolidation.min_short_term_updates == 20
    assert config.vector_index.enabled is False
    assert config.vector_index.experience_top_k == 9


def test_build_default_memory_config_payload_contains_expected_sections():
    payload = build_default_memory_config_payload()

    assert set(payload) == {
        "enabled",
        "storage",
        "short_term",
        "consolidation",
        "long_term",
        "vector_index",
        "persona",
        "jobs",
    }
