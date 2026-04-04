from __future__ import annotations

from typing import Any

from .analyzers.base import MemoryAnalyzerPromptError


def render_prompt_template(template: str, payload: dict[str, Any]) -> str:
    safe_template = template.replace("{", "{{").replace("}", "}}")
    for key in payload:
        if not isinstance(key, str) or not key:
            continue
        safe_template = safe_template.replace("{{" + key + "}}", "{" + key + "}")

    try:
        return safe_template.format(**payload)
    except Exception as exc:
        raise MemoryAnalyzerPromptError(
            "failed to render memory analyzer prompt"
        ) from exc
