from __future__ import annotations

from pathlib import Path

from astrbot.core.memory.config import (
    DEFAULT_MEMORY_ANALYZER_MODEL,
    DEFAULT_MEMORY_ANALYZER_PROMPTS,
    DEFAULT_MEMORY_ANALYZER_PROVIDER_ID,
    _build_default_memory_config,
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
    assert "analysis:" in content
    assert "prompts_root: data/memory/prompts" in content
    assert "topic_v1:" in content
    assert "focus_v1:" in content
    assert "summary_v1:" in content
    assert "session_insight_v1:" in content
    assert "experience_extract_v1:" in content
    assert "long_term_promote_v1:" in content
    assert "long_term_compose_v1:" in content
    assert f"provider_id: {DEFAULT_MEMORY_ANALYZER_PROVIDER_ID}" in content
    assert f"model: {DEFAULT_MEMORY_ANALYZER_MODEL}" in content


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
    assert config.vector_index.root_dir == (
        temp_dir / "runtime-root" / "data/memory/vector_index"
    )
    assert config.storage.docs_root.exists()
    assert config.storage.projections_root.exists()
    assert config.analysis.prompts_root == (
        temp_dir / "runtime-root" / "data/memory/prompts"
    )
    assert config.analysis.prompts_root.exists()
    for prompt_name in DEFAULT_MEMORY_ANALYZER_PROMPTS:
        assert (config.analysis.prompts_root / prompt_name).exists()
    assert config.vector_index.enabled is False
    assert (
        config.analysis.analyzers["topic_v1"].provider_id
        == DEFAULT_MEMORY_ANALYZER_PROVIDER_ID
    )
    assert config.analysis.analyzers["topic_v1"].model == DEFAULT_MEMORY_ANALYZER_MODEL


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
                '  provider_id: "embed-lite"',
                '  model: "embedding-model"',
                '  root_dir: "custom/vector_index"',
                "  experience_top_k: 9",
                "analysis:",
                "  enabled: true",
                "  strict: true",
                '  prompts_root: "custom/prompts"',
                "  analyzers:",
                "    emotion_v1:",
                '      implementation: "prompt_json"',
                '      provider_id: "memory-lite"',
                '      prompt_file: "emotion_v1.md"',
                '      output_schema: "EmotionResult"',
                "      timeout_seconds: 11",
                "      temperature: 0.3",
                "  stages:",
                "    short_term_update:",
                '      analyzers: ["emotion_v1"]',
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
    assert config.vector_index.provider_id == "embed-lite"
    assert config.vector_index.model == "embedding-model"
    assert config.vector_index.root_dir == (
        temp_dir / "astrbot-root" / "custom/vector_index"
    )
    assert config.vector_index.experience_top_k == 9
    assert config.analysis.enabled is True
    assert config.analysis.strict is True
    assert config.analysis.prompts_root == (
        temp_dir / "astrbot-root" / "custom/prompts"
    )
    assert "emotion_v1" in config.analysis.analyzers
    assert config.analysis.analyzers["emotion_v1"].provider_id == "memory-lite"
    assert config.analysis.analyzers["emotion_v1"].prompt_file == "emotion_v1.md"
    assert config.analysis.stages["short_term_update"].analyzers == ["emotion_v1"]


def test_build_default_memory_config_payload_contains_expected_sections():
    payload = build_default_memory_config_payload()
    default_config = _build_default_memory_config()

    assert set(payload) == {
        "enabled",
        "identity",
        "storage",
        "short_term",
        "consolidation",
        "long_term",
        "vector_index",
        "persona",
        "jobs",
        "analysis",
    }
    assert payload["enabled"] is default_config.enabled
    assert payload["storage"]["sqlite_path"] == "data/memory/memory.db"
    assert payload["storage"]["docs_root"] == "data/memory/long_term"
    assert payload["storage"]["projections_root"] == "data/memory/projections"
    assert payload["identity"]["mappings_path"] == "data/memory/identity_mappings.yaml"
    assert payload["vector_index"]["root_dir"] == "data/memory/vector_index"
    assert payload["analysis"]["prompts_root"] == "data/memory/prompts"
    assert (
        payload["short_term"]["recent_turns_window"]
        == default_config.short_term.recent_turns_window
    )
    assert (
        payload["consolidation"]["min_short_term_updates"]
        == default_config.consolidation.min_short_term_updates
    )
    assert (
        payload["long_term"]["min_pending_experiences"]
        == default_config.long_term.min_pending_experiences
    )
    assert (
        payload["vector_index"]["experience_top_k"]
        == default_config.vector_index.experience_top_k
    )
    assert payload["analysis"]["analyzers"]["topic_v1"]["prompt_file"] == "topic_v1.md"
    assert (
        payload["analysis"]["analyzers"]["topic_v1"]["provider_id"]
        == DEFAULT_MEMORY_ANALYZER_PROVIDER_ID
    )
    assert (
        payload["analysis"]["analyzers"]["topic_v1"]["model"]
        == DEFAULT_MEMORY_ANALYZER_MODEL
    )
    assert payload["analysis"]["analyzers"]["focus_v1"]["prompt_file"] == "focus_v1.md"
    assert (
        payload["analysis"]["analyzers"]["summary_v1"]["prompt_file"] == "summary_v1.md"
    )
    assert (
        payload["analysis"]["analyzers"]["session_insight_v1"]["prompt_file"]
        == "session_insight_v1.md"
    )
    assert (
        payload["analysis"]["analyzers"]["experience_extract_v1"]["prompt_file"]
        == "experience_extract_v1.md"
    )
    assert (
        payload["analysis"]["analyzers"]["long_term_promote_v1"]["prompt_file"]
        == "long_term_promote_v1.md"
    )
    assert (
        payload["analysis"]["analyzers"]["long_term_compose_v1"]["prompt_file"]
        == "long_term_compose_v1.md"
    )
    assert payload["vector_index"]["enabled"] is False
    assert payload["vector_index"]["provider"] == "faiss"
    assert payload["vector_index"]["provider_id"] == ""
    assert payload["analysis"]["stages"]["short_term_update"]["analyzers"] == [
        "topic_v1",
        "focus_v1",
        "summary_v1",
    ]
    assert payload["analysis"]["stages"]["session_insight_update"]["analyzers"] == [
        "session_insight_v1",
    ]
    assert payload["analysis"]["stages"]["experience_extract"]["analyzers"] == [
        "experience_extract_v1",
    ]
    assert payload["analysis"]["stages"]["long_term_promote"]["analyzers"] == [
        "long_term_promote_v1",
    ]
    assert payload["analysis"]["stages"]["long_term_compose"]["analyzers"] == [
        "long_term_compose_v1",
    ]
