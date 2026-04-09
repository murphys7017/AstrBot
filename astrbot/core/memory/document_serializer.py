from __future__ import annotations

from .types import LongTermMemoryDocument, LongTermMemoryIndex, ScopeType


class DocumentSerializer:
    def build_search_text(
        self,
        index: LongTermMemoryIndex,
        document: LongTermMemoryDocument | None = None,
    ) -> str:
        detail = document.detail_summary if document is not None else None
        recent_updates = ""
        if document is not None and document.updates:
            recent_updates = "\n".join(
                str(item.get("summary", "")).strip()
                for item in document.updates[-3:]
                if isinstance(item, dict) and str(item.get("summary", "")).strip()
            )
        return (
            f"Title: {index.title}\n"
            f"Category: {self._enum_value(index.category)}\n"
            f"Status: {self._enum_value(index.status)}\n"
            f"Summary: {index.summary}\n"
            f"Detail: {detail or ''}\n"
            f"Tags: {', '.join(index.tags)}\n"
            f"Recent Updates: {recent_updates}"
        ).strip()

    @staticmethod
    def _enum_value(value: ScopeType | str) -> str:
        return value.value if hasattr(value, "value") else str(value)
