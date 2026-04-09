from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml

from .config import MemoryConfig, get_memory_config
from .types import LongTermMemoryDocument, ScopeType


class DocumentLoader:
    def __init__(self, config: MemoryConfig | None = None) -> None:
        self.config = config or get_memory_config()

    def load_long_term_document(
        self,
        doc_path: Path | str,
    ) -> LongTermMemoryDocument:
        resolved_path = self._resolve_doc_path(doc_path)
        raw_text = self._normalize_text(resolved_path.read_text(encoding="utf-8"))
        front_matter, body = self._split_front_matter(raw_text)
        updates = front_matter.get("updates")
        supporting_experiences = front_matter.get("supporting_experiences")
        source_refs = front_matter.get("source_refs")
        tags = front_matter.get("tags")
        return LongTermMemoryDocument(
            memory_id=str(front_matter["memory_id"]),
            umo=str(front_matter["umo"]),
            scope_type=str(front_matter["scope_type"]),
            scope_id=str(front_matter["scope_id"]),
            category=str(front_matter["category"]),
            status=str(front_matter["status"]),
            title=str(front_matter["title"]),
            summary=self._extract_section(body, "Summary") or "",
            detail_summary=self._extract_section(body, "Detail"),
            importance=float(front_matter["importance"]),
            confidence=float(front_matter["confidence"]),
            supporting_experiences=[
                str(item)
                for item in supporting_experiences
                if isinstance(item, str) and item.strip()
            ]
            if isinstance(supporting_experiences, list)
            else [],
            updates=[item for item in updates if isinstance(item, dict)]
            if isinstance(updates, list)
            else [],
            source_refs=[
                str(item)
                for item in source_refs
                if isinstance(item, str) and item.strip()
            ]
            if isinstance(source_refs, list)
            else [],
            tags=[str(item) for item in tags if isinstance(item, str) and item.strip()]
            if isinstance(tags, list)
            else [],
            first_event_at=self._parse_datetime(front_matter.get("first_event_at")),
            last_event_at=self._parse_datetime(front_matter.get("last_event_at")),
            created_at=self._parse_datetime(front_matter.get("created_at")),
            updated_at=self._parse_datetime(front_matter.get("updated_at")),
            raw_text=raw_text,
        )

    def save_long_term_document(
        self,
        document: LongTermMemoryDocument,
        doc_path: Path | str | None = None,
    ) -> Path:
        resolved_path = self._resolve_doc_path(
            doc_path or self._build_default_doc_path(document)
        )
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(
            self._render_markdown(document),
            encoding="utf-8",
        )
        return resolved_path

    def extract_body_text(self, document: LongTermMemoryDocument) -> str:
        if isinstance(document.raw_text, str) and document.raw_text.strip():
            _, body = self._split_front_matter(document.raw_text)
            return body.strip()
        return self._render_markdown(document).strip()

    def build_long_term_doc_path(self, document: LongTermMemoryDocument) -> Path:
        return self._build_default_doc_path(document)

    def _build_default_doc_path(self, document: LongTermMemoryDocument) -> Path:
        return (
            self.config.storage.docs_root
            / self._safe_path_component(document.umo)
            / self._safe_path_component(self._enum_value(document.scope_type))
            / f"{self._safe_path_component(document.memory_id)}.md"
        )

    def _resolve_doc_path(self, doc_path: Path | str) -> Path:
        path = Path(doc_path)
        if path.is_absolute():
            return path
        return (self.config.storage.docs_root / path).resolve()

    def _render_markdown(self, document: LongTermMemoryDocument) -> str:
        front_matter = yaml.safe_dump(
            {
                "memory_id": document.memory_id,
                "umo": document.umo,
                "scope_type": self._enum_value(document.scope_type),
                "scope_id": document.scope_id,
                "category": self._enum_value(document.category),
                "status": self._enum_value(document.status),
                "title": document.title,
                "importance": document.importance,
                "confidence": document.confidence,
                "tags": list(document.tags),
                "source_refs": list(document.source_refs),
                "supporting_experiences": list(document.supporting_experiences),
                "updates": list(document.updates),
                "first_event_at": self._format_datetime(document.first_event_at),
                "last_event_at": self._format_datetime(document.last_event_at),
                "created_at": self._format_datetime(document.created_at),
                "updated_at": self._format_datetime(document.updated_at),
            },
            allow_unicode=True,
            sort_keys=False,
        ).strip()
        lines = [
            "---",
            front_matter,
            "---",
            "",
            f"# {document.title}",
            "",
            "## Summary",
            self._render_text_block(document.summary),
            "",
            "## Detail",
            self._render_text_block(document.detail_summary or ""),
            "",
            "## Supporting Experiences",
            self._render_text_block("\n".join(document.supporting_experiences)),
            "",
            "## Updates",
            self._render_text_block(self._render_updates(document.updates)),
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _split_front_matter(raw_text: str) -> tuple[dict, str]:
        if not raw_text.startswith("---\n"):
            raise ValueError("long-term document is missing YAML front matter")
        parts = raw_text.split("\n---\n", 1)
        if len(parts) != 2:
            raise ValueError("long-term document front matter is malformed")
        front_matter_text = parts[0][4:]
        body = parts[1]
        front_matter = yaml.safe_load(front_matter_text) or {}
        if not isinstance(front_matter, dict):
            raise ValueError("long-term document front matter is invalid")
        required_fields = (
            "memory_id",
            "umo",
            "scope_type",
            "scope_id",
            "category",
            "status",
            "title",
            "importance",
            "confidence",
        )
        for field_name in required_fields:
            if field_name not in front_matter:
                raise ValueError(
                    f"long-term document missing required field `{field_name}`"
                )
        return front_matter, body

    @staticmethod
    def _normalize_text(raw_text: str) -> str:
        return raw_text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _extract_section(body: str, title: str) -> str | None:
        marker = f"## {title}\n"
        start = body.find(marker)
        if start < 0:
            return None
        next_marker = body.find("\n## ", start + len(marker))
        section = (
            body[start + len(marker) : next_marker]
            if next_marker >= 0
            else body[start + len(marker) :]
        ).strip()
        if section.startswith("```"):
            lines = section.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
        return section or None

    @staticmethod
    def _render_updates(updates: list[dict]) -> str:
        if not updates:
            return ""
        return "\n".join(
            json.dumps(update, ensure_ascii=False, sort_keys=True) for update in updates
        )

    @staticmethod
    def _render_text_block(value: str) -> str:
        fence = DocumentLoader._fence_for_text(value)
        return f"{fence}text\n{value}\n{fence}"

    @staticmethod
    def _fence_for_text(value: str) -> str:
        max_backticks = 0
        current = 0
        for char in value:
            if char == "`":
                current += 1
                max_backticks = max(max_backticks, current)
            else:
                current = 0
        return "`" * max(3, max_backticks + 1)

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return datetime.fromisoformat(value)

    @staticmethod
    def _format_datetime(value: datetime | None) -> str | None:
        return value.isoformat() if isinstance(value, datetime) else None

    @staticmethod
    def _safe_path_component(value: str) -> str:
        sanitized = "".join(
            char if char.isalnum() or char in "._-" else "_" for char in value
        ).strip("._")
        return sanitized or "unknown"

    @staticmethod
    def _enum_value(value: ScopeType | str) -> str:
        return value.value if hasattr(value, "value") else str(value)
