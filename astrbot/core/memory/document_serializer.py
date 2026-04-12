from __future__ import annotations

import jieba.analyse

from .types import LongTermMemoryDocument, LongTermMemoryIndex, ScopeType


class DocumentSerializer:
    KEYWORD_TOP_K = 12

    def build_search_text(
        self,
        index: LongTermMemoryIndex,
        document: LongTermMemoryDocument | None = None,
    ) -> str:
        detail = document.detail_summary if document is not None else None
        updates = self._format_updates(document)
        keyword_source = self._build_keyword_source_text(index, document, updates)
        keywords = self._extract_keywords(keyword_source)
        sections = [
            f"Title: {index.title}",
            f"Category: {self._enum_value(index.category)}",
            f"Status: {self._enum_value(index.status)}",
            f"Summary: {index.summary}",
            f"Detail: {detail or ''}",
            f"Tags: {', '.join(index.tags)}",
            f"First Event At: {self._format_datetime(index.first_event_at)}",
            f"Last Event At: {self._format_datetime(index.last_event_at)}",
            "Updates:",
            self._render_bullets(updates),
            f"Keywords: {', '.join(keywords)}",
        ]
        return "\n".join(section for section in sections if section).strip()

    def _build_keyword_source_text(
        self,
        index: LongTermMemoryIndex,
        document: LongTermMemoryDocument | None,
        updates: list[str],
    ) -> str:
        detail = document.detail_summary if document is not None else ""
        sections = [
            index.title,
            index.summary,
            detail,
            " ".join(index.tags),
            "\n".join(updates),
        ]
        return "\n".join(section for section in sections if section).strip()

    def _format_updates(
        self,
        document: LongTermMemoryDocument | None,
    ) -> list[str]:
        if document is None:
            return []
        rendered_updates: list[str] = []
        for item in document.updates:
            if not isinstance(item, dict):
                continue
            parts = []
            timestamp = str(item.get("timestamp", "")).strip()
            action = str(item.get("action", "")).strip()
            summary = str(item.get("summary", "")).strip()
            if timestamp:
                parts.append(timestamp)
            if action:
                parts.append(action)
            if summary:
                parts.append(summary)
            if parts:
                rendered_updates.append(" | ".join(parts))
        return rendered_updates

    def _extract_keywords(self, text: str) -> list[str]:
        if not text.strip():
            return []
        return [
            keyword.strip()
            for keyword in jieba.analyse.extract_tags(
                text,
                topK=self.KEYWORD_TOP_K,
                withWeight=False,
            )
            if keyword.strip()
        ]

    @staticmethod
    def _render_bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items if item.strip())

    @staticmethod
    def _format_datetime(value) -> str:
        return value.isoformat() if value is not None else ""

    @staticmethod
    def _enum_value(value: ScopeType | str) -> str:
        return value.value if hasattr(value, "value") else str(value)
