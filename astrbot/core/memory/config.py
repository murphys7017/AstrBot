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
    "session_insight_v1.md": """You are a memory consolidation analyzer.

Task:
- Read the recent batch of turns and the short-term state.
- Produce a session-level insight.
- Return JSON only.

Requirements:
- topic_summary: concise topic-level summary
- progress_summary: concise progress summary
- summary_text: overall session insight text

Short-term topic:
{topic_state_current_topic}

Short-term topic summary:
{topic_state_summary}

Short-term summary:
{short_term_summary}

Active focus:
{short_term_active_focus}

Recent dialogue:
{recent_dialogue_text}
""",
    "experience_extract_v1.md": """You are a memory experience extractor.

Task:
- Read the session insight and supporting turns.
- Extract timeline experiences worth keeping.
- Return JSON only.

Requirements:
- experiences: list of objects
- each object must contain:
  - category
  - summary
  - detail_summary
  - importance
  - confidence

Allowed categories:
- user_fact
- user_preference
- project_progress
- interaction_pattern
- relationship_signal
- episodic_event

Session topic summary:
{insight_topic_summary}

Session progress summary:
{insight_progress_summary}

Session overall summary:
{insight_summary_text}

Recent dialogue:
{recent_dialogue_text}
""",
    "long_term_promote_v1.md": """You are a long-term memory promotion planner.

Task:
- Read the pending experiences and existing long-term memories for the same scope.
- Decide which pending experiences should create a new long-term memory, update an existing one, or be ignored.
- Return JSON only.

Requirements:
- actions: list of objects
- each object must contain:
  - action
  - target_memory_id
  - category
  - reason
  - experience_ids

Allowed actions:
- create
- update
- ignore

Allowed categories:
- user_fact
- user_preference
- project_progress
- interaction_pattern
- relationship_signal
- episodic_event

Pending experiences JSON:
{pending_experiences_json}

Existing long-term memories JSON:
{existing_memories_json}
""",
    "long_term_compose_v1.md": """You are a long-term memory composer.

Task:
- Read the selected action, the supporting experiences, and the current long-term memory state if one exists.
- Produce the final long-term memory content.
- Return JSON only.

Requirements:
- title
- summary
- detail_summary
- tags
- importance
- confidence
- status

Allowed status values:
- active
- archived
- contradicted

Action:
{promotion_action}

Category:
{promotion_category}

Promotion reason:
{promotion_reason}

Existing memory JSON:
{existing_memory_json}

Supporting experiences JSON:
{supporting_experiences_json}
""",
}

DEFAULT_MEMORY_ANALYZER_PROVIDER_ID = "ollama"
DEFAULT_MEMORY_ANALYZER_MODEL = "qwen3:1.7b"
DEFAULT_MEMORY_ANALYZER_SPECS: dict[str, tuple[str, str]] = {
    "topic_v1": ("topic_v1.md", "TopicStateResult"),
    "focus_v1": ("focus_v1.md", "ShortTermFocusResult"),
    "summary_v1": ("summary_v1.md", "ShortTermSummaryResult"),
    "session_insight_v1": ("session_insight_v1.md", "SessionInsightResult"),
    "experience_extract_v1": ("experience_extract_v1.md", "ExperienceExtractResult"),
    "long_term_promote_v1": ("long_term_promote_v1.md", "LongTermPromoteResult"),
    "long_term_compose_v1": ("long_term_compose_v1.md", "LongTermComposeResult"),
}
DEFAULT_MEMORY_ANALYSIS_STAGES: dict[str, list[str]] = {
    "short_term_update": ["topic_v1", "focus_v1", "summary_v1"],
    "session_insight_update": ["session_insight_v1"],
    "experience_extract": ["experience_extract_v1"],
    "long_term_promote": ["long_term_promote_v1"],
    "long_term_compose": ["long_term_compose_v1"],
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
    min_pending_experiences: int = 3


@dataclass(slots=True)
class MemoryVectorIndexConfig:
    enabled: bool = False
    provider: str = "faiss"
    provider_id: str = ""
    model: str = ""
    root_dir: Path = field(
        default_factory=lambda: resolve_memory_path("data/memory/vector_index")
    )
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
    provider_id: str = DEFAULT_MEMORY_ANALYZER_PROVIDER_ID
    model: str = DEFAULT_MEMORY_ANALYZER_MODEL
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


def _build_default_analysis_analyzers() -> dict[str, MemoryAnalyzerConfig]:
    analyzers: dict[str, MemoryAnalyzerConfig] = {}
    for analyzer_name, (
        prompt_file,
        output_schema,
    ) in DEFAULT_MEMORY_ANALYZER_SPECS.items():
        analyzers[analyzer_name] = MemoryAnalyzerConfig(
            enabled=True,
            implementation="prompt_json",
            provider_id=DEFAULT_MEMORY_ANALYZER_PROVIDER_ID,
            model=DEFAULT_MEMORY_ANALYZER_MODEL,
            prompt_file=prompt_file,
            output_schema=output_schema,
            timeout_seconds=20,
            temperature=0.0,
        )
    return analyzers


def _build_default_analysis_stages() -> dict[str, MemoryAnalysisStageConfig]:
    return {
        stage_name: MemoryAnalysisStageConfig(analyzers=list(analyzer_names))
        for stage_name, analyzer_names in DEFAULT_MEMORY_ANALYSIS_STAGES.items()
    }


def _build_default_memory_config() -> MemoryConfig:
    config = MemoryConfig()
    config.analysis.analyzers = _build_default_analysis_analyzers()
    config.analysis.stages = _build_default_analysis_stages()
    return config


def _serialize_path_for_payload(path: Path | None) -> str | None:
    if path is None:
        return None

    astrbot_root = Path(get_astrbot_root()).resolve()
    try:
        return path.resolve().relative_to(astrbot_root).as_posix()
    except ValueError:
        return path.as_posix()


def build_default_memory_config_payload() -> dict:
    default_config = _build_default_memory_config()
    return {
        "enabled": default_config.enabled,
        "storage": {
            "sqlite_path": _serialize_path_for_payload(
                default_config.storage.sqlite_path
            ),
            "docs_root": _serialize_path_for_payload(default_config.storage.docs_root),
            "projections_root": _serialize_path_for_payload(
                default_config.storage.projections_root
            ),
        },
        "short_term": {
            "enabled": default_config.short_term.enabled,
            "recent_turns_window": default_config.short_term.recent_turns_window,
        },
        "consolidation": {
            "enabled": default_config.consolidation.enabled,
            "min_short_term_updates": default_config.consolidation.min_short_term_updates,
            "batch_window_hours": default_config.consolidation.batch_window_hours,
        },
        "long_term": {
            "enabled": default_config.long_term.enabled,
            "docs_dir": _serialize_path_for_payload(default_config.long_term.docs_dir),
            "min_experience_importance": default_config.long_term.min_experience_importance,
            "min_pending_experiences": default_config.long_term.min_pending_experiences,
        },
        "vector_index": {
            "enabled": default_config.vector_index.enabled,
            "provider": default_config.vector_index.provider,
            "provider_id": default_config.vector_index.provider_id,
            "model": default_config.vector_index.model,
            "root_dir": _serialize_path_for_payload(
                default_config.vector_index.root_dir
            ),
            "experience_top_k": default_config.vector_index.experience_top_k,
            "long_term_top_k": default_config.vector_index.long_term_top_k,
        },
        "persona": {
            "enabled": default_config.persona.enabled,
            "reflection_interval_hours": default_config.persona.reflection_interval_hours,
        },
        "jobs": {
            "consolidation_enabled": default_config.jobs.consolidation_enabled,
            "long_term_enabled": default_config.jobs.long_term_enabled,
            "persona_reflection_enabled": default_config.jobs.persona_reflection_enabled,
        },
        "analysis": {
            "enabled": default_config.analysis.enabled,
            "strict": default_config.analysis.strict,
            "prompts_root": _serialize_path_for_payload(
                default_config.analysis.prompts_root
            ),
            "analyzers": {
                analyzer_name: {
                    "enabled": analyzer_config.enabled,
                    "implementation": analyzer_config.implementation,
                    "provider_id": analyzer_config.provider_id,
                    "model": analyzer_config.model,
                    "prompt_file": analyzer_config.prompt_file,
                    "output_schema": analyzer_config.output_schema,
                    "timeout_seconds": analyzer_config.timeout_seconds,
                    "temperature": analyzer_config.temperature,
                }
                for analyzer_name, analyzer_config in default_config.analysis.analyzers.items()
            },
            "stages": {
                stage_name: {
                    "analyzers": list(stage_config.analyzers),
                }
                for stage_name, stage_config in default_config.analysis.stages.items()
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
            provider_id=_as_str(
                config_payload.get("provider_id"),
                DEFAULT_MEMORY_ANALYZER_PROVIDER_ID,
            ),
            model=_as_str(
                config_payload.get("model"),
                DEFAULT_MEMORY_ANALYZER_MODEL,
            ),
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
            min_pending_experiences=_as_int(
                long_term_payload.get("min_pending_experiences"),
                3,
            ),
        ),
        vector_index=MemoryVectorIndexConfig(
            enabled=_as_bool(vector_index_payload.get("enabled"), False),
            provider=_as_str(vector_index_payload.get("provider"), "faiss"),
            provider_id=_as_str(vector_index_payload.get("provider_id"), ""),
            model=_as_str(vector_index_payload.get("model"), ""),
            root_dir=resolve_memory_path(
                _as_str(
                    vector_index_payload.get("root_dir"), "data/memory/vector_index"
                )
            ),
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
    config.vector_index.root_dir.mkdir(parents=True, exist_ok=True)
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
