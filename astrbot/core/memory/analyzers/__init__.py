from __future__ import annotations

from .base import (
    BaseMemoryAnalyzer,
    MemoryAnalyzerConfigurationError,
    MemoryAnalyzerError,
    MemoryAnalyzerExecutionError,
    MemoryAnalyzerPromptError,
    MemoryAnalyzerProviderError,
    MemoryAnalyzerRequest,
    MemoryAnalyzerResult,
)

__all__ = [
    "BaseMemoryAnalyzer",
    "MemoryAnalyzerConfigurationError",
    "MemoryAnalyzerError",
    "MemoryAnalyzerExecutionError",
    "MemoryAnalyzerPromptError",
    "MemoryAnalyzerProviderError",
    "MemoryAnalyzerRequest",
    "MemoryAnalyzerResult",
    "PromptJsonMemoryAnalyzer",
]


def __getattr__(name: str):
    if name == "PromptJsonMemoryAnalyzer":
        from .prompt_json import PromptJsonMemoryAnalyzer

        return PromptJsonMemoryAnalyzer
    raise AttributeError(name)
