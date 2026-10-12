"""Text projections for diagnostics; provider media payloads stay unchanged."""

from __future__ import annotations

import re
from typing import Any

from astrbot.core.utils.error_redaction import redact_sensitive_text

_DATA_URI = re.compile(r"data:([\w.+-]+/[\w.+-]+);base64,([A-Za-z0-9+/=]+)")
_MEDIA_TYPES = frozenset(
    {"image", "image_url", "input_image", "input_audio", "audio", "video_url"}
)
_SECRET_KEYS = frozenset(
    {
        "key",
        "api_key",
        "apikey",
        "password",
        "secret",
        "authorization",
        "access_token",
        "auth_token",
        "refresh_token",
    }
)


def project_prompt_diagnostics(value: Any) -> tuple[Any, dict[str, int]]:
    """Remove media bytes/references and redact credentials in a detached copy."""
    media = {"parts": 0, "base64_chars": 0}

    def strip_data_uri(match: re.Match[str]) -> str:
        media["parts"] += 1
        media["base64_chars"] += len(match.group(2))
        return f"[media:{match.group(1)}]"

    def visit(item: Any) -> Any:
        if hasattr(item, "model_dump"):
            item = item.model_dump(mode="json")
        if isinstance(item, dict):
            kind = item.get("type")
            if isinstance(kind, str) and kind in _MEDIA_TYPES:
                media["parts"] += 1

                # Collect transport size without retaining private URLs or bytes.
                def count_encoded(part: Any) -> None:
                    if isinstance(part, str):
                        media["base64_chars"] += sum(
                            len(match.group(2)) for match in _DATA_URI.finditer(part)
                        )
                    elif isinstance(part, dict):
                        if part.get("type") == "base64":
                            media["base64_chars"] += len(str(part.get("data") or ""))
                        else:
                            for child in part.values():
                                count_encoded(child)
                    elif isinstance(part, (list, tuple)):
                        for child in part:
                            count_encoded(child)

                count_encoded(item)
                return {"type": kind, "media": "[omitted]"}
            return {
                key: "[REDACTED]" if str(key).lower() in _SECRET_KEYS else visit(child)
                for key, child in item.items()
            }
        if isinstance(item, (list, tuple)):
            return [visit(child) for child in item]
        if isinstance(item, str):
            return redact_sensitive_text(_DATA_URI.sub(strip_data_uri, item))
        return item

    return visit(value), media
