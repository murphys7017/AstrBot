from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from astrbot.core.utils.astrbot_path import get_astrbot_root


@dataclass(slots=True)
class MemoryStorageConfig:
    sqlite_path: Path
    docs_root: Path
    projections_root: Path


@dataclass(slots=True)
class MemoryShortTermConfig:
    enabled: bool = True
    recent_turns_window: int = 8


@dataclass(slots=True)
class MemoryConsolidationConfig:
    enabled: bool = True
    min_short_term_updates: int = 12
    batch_window_hours: int = 6


@dataclass(slots=True)
class MemoryLongTermConfig:
    enabled: bool = True
    docs_dir: Path | None = None
    min_experience_importance: float = 0.7


@dataclass(slots=True)
class MemoryVectorIndexConfig:
    enabled: bool = True
    provider: str = "simple"
    experience_top_k: int = 5
    long_term_top_k: int = 5


@dataclass(slots=True)
class MemoryPersonaConfig:
    enabled: bool = False
    reflection_interval_hours: int = 24


@dataclass(slots=True)
class MemoryJobsConfig:
    consolidation_enabled: bool = True
    long_term_enabled: bool = True
    persona_reflection_enabled: bool = False


def resolve_memory_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (Path(get_astrbot_root()) / candidate).resolve()


@dataclass(slots=True)
class MemoryConfig:
    enabled: bool = True
    storage: MemoryStorageConfig = field(
        default_factory=lambda: MemoryStorageConfig(
            sqlite_path=resolve_memory_path("data/memory/memory.db"),
            docs_root=resolve_memory_path("data/memory/long_term"),
            projections_root=resolve_memory_path("data/memory/projections"),
        )
    )
    short_term: MemoryShortTermConfig = field(default_factory=MemoryShortTermConfig)
    consolidation: MemoryConsolidationConfig = field(
        default_factory=MemoryConsolidationConfig
    )
    long_term: MemoryLongTermConfig = field(
        default_factory=lambda: MemoryLongTermConfig(
            docs_dir=resolve_memory_path("data/memory/long_term")
        )
    )
    vector_index: MemoryVectorIndexConfig = field(
        default_factory=MemoryVectorIndexConfig
    )
    persona: MemoryPersonaConfig = field(default_factory=MemoryPersonaConfig)
    jobs: MemoryJobsConfig = field(default_factory=MemoryJobsConfig)


def get_default_memory_config_path() -> Path:
    return resolve_memory_path("data/memory/config.yaml")


def build_default_memory_config_payload() -> dict:
    return {
        "enabled": True,
        "storage": {
            "sqlite_path": "data/memory/memory.db",
            "docs_root": "data/memory/long_term",
            "projections_root": "data/memory/projections",
        },
        "short_term": {
            "enabled": True,
            "recent_turns_window": 8,
        },
        "consolidation": {
            "enabled": True,
            "min_short_term_updates": 12,
            "batch_window_hours": 6,
        },
        "long_term": {
            "enabled": True,
            "docs_dir": "data/memory/long_term",
            "min_experience_importance": 0.7,
        },
        "vector_index": {
            "enabled": True,
            "provider": "simple",
            "experience_top_k": 5,
            "long_term_top_k": 5,
        },
        "persona": {
            "enabled": False,
            "reflection_interval_hours": 24,
        },
        "jobs": {
            "consolidation_enabled": True,
            "long_term_enabled": True,
            "persona_reflection_enabled": False,
        },
    }


def ensure_memory_config_file(
    path: Path | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    config_path = path or get_default_memory_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists() and not overwrite:
        return config_path

    payload = build_default_memory_config_payload()
    config_path.write_text(
        yaml.safe_dump(
            payload,
            allow_unicode=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    return default


def _as_str(value: object, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def load_memory_config(path: Path | None = None) -> MemoryConfig:
    config_path = path or get_default_memory_config_path()
    if not config_path.exists():
        ensure_memory_config_file(config_path)

    payload: dict = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            payload = loaded

    storage_payload = payload.get("storage", {}) if isinstance(payload, dict) else {}
    short_term_payload = (
        payload.get("short_term", {}) if isinstance(payload, dict) else {}
    )
    consolidation_payload = (
        payload.get("consolidation", {}) if isinstance(payload, dict) else {}
    )
    long_term_payload = (
        payload.get("long_term", {}) if isinstance(payload, dict) else {}
    )
    vector_index_payload = (
        payload.get("vector_index", {}) if isinstance(payload, dict) else {}
    )
    persona_payload = payload.get("persona", {}) if isinstance(payload, dict) else {}
    jobs_payload = payload.get("jobs", {}) if isinstance(payload, dict) else {}

    config = MemoryConfig(
        enabled=_as_bool(payload.get("enabled"), True),
        storage=MemoryStorageConfig(
            sqlite_path=resolve_memory_path(
                _as_str(storage_payload.get("sqlite_path"), "data/memory/memory.db")
            ),
            docs_root=resolve_memory_path(
                _as_str(storage_payload.get("docs_root"), "data/memory/long_term")
            ),
            projections_root=resolve_memory_path(
                _as_str(
                    storage_payload.get("projections_root"),
                    "data/memory/projections",
                )
            ),
        ),
        short_term=MemoryShortTermConfig(
            enabled=_as_bool(short_term_payload.get("enabled"), True),
            recent_turns_window=_as_int(
                short_term_payload.get("recent_turns_window"),
                8,
            ),
        ),
        consolidation=MemoryConsolidationConfig(
            enabled=_as_bool(consolidation_payload.get("enabled"), True),
            min_short_term_updates=_as_int(
                consolidation_payload.get("min_short_term_updates"),
                12,
            ),
            batch_window_hours=_as_int(
                consolidation_payload.get("batch_window_hours"),
                6,
            ),
        ),
        long_term=MemoryLongTermConfig(
            enabled=_as_bool(long_term_payload.get("enabled"), True),
            docs_dir=resolve_memory_path(
                _as_str(long_term_payload.get("docs_dir"), "data/memory/long_term")
            ),
            min_experience_importance=_as_float(
                long_term_payload.get("min_experience_importance"),
                0.7,
            ),
        ),
        vector_index=MemoryVectorIndexConfig(
            enabled=_as_bool(vector_index_payload.get("enabled"), True),
            provider=_as_str(vector_index_payload.get("provider"), "simple"),
            experience_top_k=_as_int(
                vector_index_payload.get("experience_top_k"),
                5,
            ),
            long_term_top_k=_as_int(
                vector_index_payload.get("long_term_top_k"),
                5,
            ),
        ),
        persona=MemoryPersonaConfig(
            enabled=_as_bool(persona_payload.get("enabled"), False),
            reflection_interval_hours=_as_int(
                persona_payload.get("reflection_interval_hours"),
                24,
            ),
        ),
        jobs=MemoryJobsConfig(
            consolidation_enabled=_as_bool(
                jobs_payload.get("consolidation_enabled"),
                True,
            ),
            long_term_enabled=_as_bool(
                jobs_payload.get("long_term_enabled"),
                True,
            ),
            persona_reflection_enabled=_as_bool(
                jobs_payload.get("persona_reflection_enabled"),
                False,
            ),
        ),
    )
    ensure_memory_runtime_dirs(config)
    return config


def ensure_memory_runtime_dirs(config: MemoryConfig) -> None:
    config.storage.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    config.storage.docs_root.mkdir(parents=True, exist_ok=True)
    config.storage.projections_root.mkdir(parents=True, exist_ok=True)
    if config.long_term.docs_dir is not None:
        config.long_term.docs_dir.mkdir(parents=True, exist_ok=True)


_MEMORY_CONFIG: MemoryConfig | None = None


def get_memory_config() -> MemoryConfig:
    global _MEMORY_CONFIG
    if _MEMORY_CONFIG is None:
        _MEMORY_CONFIG = load_memory_config()
    return _MEMORY_CONFIG
