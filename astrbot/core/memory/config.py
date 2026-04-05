from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from astrbot.core.utils.astrbot_path import get_astrbot_root

DEFAULT_MEMORY_ANALYZER_PROMPTS: dict[str, str] = {
    "topic_v1.md": """You are a memory topic analyzer.

Task:
- Read the latest conversation window.
- Identify the current main topic.
- Summarize that topic briefly.
- Return JSON only.

Requirements:
- current_topic: short label or title
- topic_summary: concise summary of the active topic
- topic_confidence: float between 0 and 1

Conversation window:
{recent_dialogue_text}

Latest user:
{latest_user_text}

Latest assistant:
{latest_assistant_text}
""",
    "focus_v1.md": """You are a memory focus analyzer.

Task:
- Read the recent dialogue.
- Identify what should remain active for the next turn.
- Return JSON only.

Requirements:
- active_focus: the main unresolved focus, request, or task point

Conversation window:
{recent_dialogue_text}

Latest user:
{latest_user_text}
""",
    "summary_v1.md": """You are a short-term memory summarizer.

Task:
- Compress the recent conversation into a short-term memory summary.
- Keep only information that is useful for the next turn.
- Return JSON only.

Requirements:
- short_summary: concise multi-turn summary

Recent turns JSON:
{recent_turns_json}
""",
}


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


@dataclass(slots=True)
class MemoryAnalyzerConfig:
    enabled: bool = True
    implementation: str = "prompt_json"
    provider_id: str = ""
    model: str = ""
    prompt_file: str = ""
    output_schema: str = ""
    timeout_seconds: int = 20
    temperature: float = 0.0


@dataclass(slots=True)
class MemoryAnalysisStageConfig:
    analyzers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MemoryAnalysisConfig:
    enabled: bool = False
    strict: bool = True
    prompts_root: Path = field(
        default_factory=lambda: resolve_memory_path("data/memory/prompts")
    )
    analyzers: dict[str, MemoryAnalyzerConfig] = field(default_factory=dict)
    stages: dict[str, MemoryAnalysisStageConfig] = field(default_factory=dict)


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
    analysis: MemoryAnalysisConfig = field(default_factory=MemoryAnalysisConfig)


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
        "analysis": {
            "enabled": False,
            "strict": True,
            "prompts_root": "data/memory/prompts",
            "analyzers": {
                "topic_v1": {
                    "enabled": True,
                    "implementation": "prompt_json",
                    "provider_id": "",
                    "model": "",
                    "prompt_file": "topic_v1.md",
                    "output_schema": "TopicStateResult",
                    "timeout_seconds": 20,
                    "temperature": 0.0,
                },
                "focus_v1": {
                    "enabled": True,
                    "implementation": "prompt_json",
                    "provider_id": "",
                    "model": "",
                    "prompt_file": "focus_v1.md",
                    "output_schema": "ShortTermFocusResult",
                    "timeout_seconds": 20,
                    "temperature": 0.0,
                },
                "summary_v1": {
                    "enabled": True,
                    "implementation": "prompt_json",
                    "provider_id": "",
                    "model": "",
                    "prompt_file": "summary_v1.md",
                    "output_schema": "ShortTermSummaryResult",
                    "timeout_seconds": 20,
                    "temperature": 0.0,
                },
            },
            "stages": {
                "short_term_update": {
                    "analyzers": ["topic_v1", "focus_v1", "summary_v1"],
                }
            },
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


def _as_list_of_str(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _as_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    return {}


def _load_analyzer_configs(payload: object) -> dict[str, MemoryAnalyzerConfig]:
    analyzer_payload = _as_dict(payload)
    analyzers: dict[str, MemoryAnalyzerConfig] = {}
    for name, raw_config in analyzer_payload.items():
        analyzer_name = str(name).strip()
        if not analyzer_name:
            continue

        config_payload = _as_dict(raw_config)
        analyzers[analyzer_name] = MemoryAnalyzerConfig(
            enabled=_as_bool(config_payload.get("enabled"), True),
            implementation=_as_str(
                config_payload.get("implementation"),
                "prompt_json",
            ),
            provider_id=_as_str(config_payload.get("provider_id"), ""),
            model=_as_str(config_payload.get("model"), ""),
            prompt_file=_as_str(config_payload.get("prompt_file"), ""),
            output_schema=_as_str(config_payload.get("output_schema"), ""),
            timeout_seconds=_as_int(config_payload.get("timeout_seconds"), 20),
            temperature=_as_float(config_payload.get("temperature"), 0.0),
        )
    return analyzers


def _load_stage_configs(payload: object) -> dict[str, MemoryAnalysisStageConfig]:
    stage_payload = _as_dict(payload)
    stages: dict[str, MemoryAnalysisStageConfig] = {}
    for name, raw_config in stage_payload.items():
        stage_name = str(name).strip()
        if not stage_name:
            continue

        config_payload = _as_dict(raw_config)
        stages[stage_name] = MemoryAnalysisStageConfig(
            analyzers=_as_list_of_str(config_payload.get("analyzers")),
        )
    return stages


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
    analysis_payload = payload.get("analysis", {}) if isinstance(payload, dict) else {}

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
        analysis=MemoryAnalysisConfig(
            enabled=_as_bool(analysis_payload.get("enabled"), False),
            strict=_as_bool(analysis_payload.get("strict"), True),
            prompts_root=resolve_memory_path(
                _as_str(analysis_payload.get("prompts_root"), "data/memory/prompts")
            ),
            analyzers=_load_analyzer_configs(analysis_payload.get("analyzers")),
            stages=_load_stage_configs(analysis_payload.get("stages")),
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
    config.analysis.prompts_root.mkdir(parents=True, exist_ok=True)
    ensure_default_memory_prompt_files(config.analysis.prompts_root)


def ensure_default_memory_prompt_files(
    prompts_root: Path,
    *,
    overwrite: bool = False,
) -> None:
    prompts_root.mkdir(parents=True, exist_ok=True)
    for filename, content in DEFAULT_MEMORY_ANALYZER_PROMPTS.items():
        prompt_path = prompts_root / filename
        if prompt_path.exists() and not overwrite:
            continue
        prompt_path.write_text(content, encoding="utf-8")


_MEMORY_CONFIG: MemoryConfig | None = None


def get_memory_config() -> MemoryConfig:
    global _MEMORY_CONFIG
    if _MEMORY_CONFIG is None:
        _MEMORY_CONFIG = load_memory_config()
    return _MEMORY_CONFIG
