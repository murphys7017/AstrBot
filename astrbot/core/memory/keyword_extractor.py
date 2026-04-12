from __future__ import annotations

import re
from abc import ABC, abstractmethod

import jieba.analyse

from .config import (
    DEFAULT_MEMORY_KEYWORD_EXTRACTOR_IMPLEMENTATION,
    MemoryKeywordExtractionConfig,
)


class MemoryKeywordExtractor(ABC):
    kind: str

    @abstractmethod
    def extract(self, text: str, *, top_k: int) -> list[str]:
        raise NotImplementedError


class JiebaTfidfKeywordExtractor(MemoryKeywordExtractor):
    kind = DEFAULT_MEMORY_KEYWORD_EXTRACTOR_IMPLEMENTATION
    _ENGLISH_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")

    def extract(self, text: str, *, top_k: int) -> list[str]:
        normalized = text.strip()
        if not normalized or top_k <= 0:
            return []

        keywords = [
            keyword.strip()
            for keyword in jieba.analyse.extract_tags(
                normalized,
                topK=max(top_k, 1),
                withWeight=False,
            )
            if keyword.strip()
        ]
        english_keywords = self._extract_english_keywords(normalized, top_k=top_k)
        return _merge_keywords(keywords, english_keywords, limit=top_k)

    def _extract_english_keywords(self, text: str, *, top_k: int) -> list[str]:
        counts: dict[str, int] = {}
        order: dict[str, int] = {}
        for index, match in enumerate(self._ENGLISH_TOKEN_PATTERN.finditer(text)):
            token = match.group(0).lower()
            counts[token] = counts.get(token, 0) + 1
            order.setdefault(token, index)
        ranked = sorted(
            counts.items(),
            key=lambda item: (-item[1], order[item[0]], item[0]),
        )
        return [token for token, _ in ranked[:top_k]]


class MemoryKeywordExtractorRegistry:
    def __init__(self) -> None:
        self._implementations: dict[str, MemoryKeywordExtractor] = {}
        self.register(JiebaTfidfKeywordExtractor())

    def register(self, extractor: MemoryKeywordExtractor) -> None:
        self._implementations[extractor.kind] = extractor

    def build(
        self,
        config: MemoryKeywordExtractionConfig,
    ) -> ConfiguredMemoryKeywordExtractor:
        implementation = self._implementations.get(config.implementation)
        if implementation is None:
            available = ", ".join(sorted(self._implementations))
            raise ValueError(
                "unsupported memory keyword extractor implementation "
                f"`{config.implementation}`; available: {available}"
            )
        return ConfiguredMemoryKeywordExtractor(
            implementation=implementation,
            enabled=config.enabled,
            top_k=max(0, int(config.top_k)),
        )


class ConfiguredMemoryKeywordExtractor:
    def __init__(
        self,
        *,
        implementation: MemoryKeywordExtractor,
        enabled: bool,
        top_k: int,
    ) -> None:
        self.implementation = implementation
        self.enabled = enabled
        self.top_k = top_k

    def extract(self, text: str) -> list[str]:
        if not self.enabled or self.top_k <= 0:
            return []
        return self.implementation.extract(text, top_k=self.top_k)


def build_keyword_extractor(
    config: MemoryKeywordExtractionConfig,
) -> ConfiguredMemoryKeywordExtractor:
    registry = MemoryKeywordExtractorRegistry()
    return registry.build(config)


def _merge_keywords(*groups: list[str], limit: int) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for keyword in group:
            normalized = keyword.strip()
            if not normalized:
                continue
            lowered = normalized.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            merged.append(normalized)
            if len(merged) >= limit:
                return merged
    return merged
