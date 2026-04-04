from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.core.provider.provider import Provider


class MemoryAnalyzerError(RuntimeError):
    """Base error for memory analyzer failures."""


class MemoryAnalyzerConfigurationError(MemoryAnalyzerError):
    """Raised when analyzer configuration is invalid."""


class MemoryAnalyzerProviderError(MemoryAnalyzerError):
    """Raised when the configured provider cannot be used."""


class MemoryAnalyzerPromptError(MemoryAnalyzerError):
    """Raised when prompt loading or rendering fails."""


class MemoryAnalyzerExecutionError(MemoryAnalyzerError):
    """Raised when analyzer execution fails."""


@dataclass(slots=True)
class MemoryAnalyzerRequest:
    analyzer_name: str
    stage: str | None
    payload: dict[str, Any]
    prompt_template: str
    prompt_path: Path
    provider: Provider
    provider_id: str
    model: str | None
    output_schema: str
    timeout_seconds: int
    temperature: float
    umo: str | None = None
    conversation_id: str | None = None


@dataclass(slots=True)
class MemoryAnalyzerResult:
    analyzer_name: str
    stage: str | None
    data: dict[str, Any]
    raw_text: str
    provider_id: str
    model: str | None


class BaseMemoryAnalyzer(abc.ABC):
    kind: str

    @abc.abstractmethod
    async def analyze(self, request: MemoryAnalyzerRequest) -> MemoryAnalyzerResult:
        """Run analyzer and return structured result."""
