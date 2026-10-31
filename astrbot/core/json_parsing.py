"""Provider-independent JSON text normalization and tolerant parsing."""

from __future__ import annotations

import ast
import json
import re
from copy import deepcopy
from typing import Any

from json_repair import repair_json

from astrbot.core import logger

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_MISSING = object()


def strip_json_code_fence(text: str) -> str:
    """Remove surrounding whitespace and a complete JSON code fence."""
    cleaned = text.strip()
    fenced = _JSON_FENCE.fullmatch(cleaned)
    return fenced.group(1).strip() if fenced is not None else cleaned


def _clean_json_candidate(text: str) -> str:
    without_thinking = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return strip_json_code_fence(without_thinking)


def _parse_jsonish_value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return _MISSING


def _balance_json_delimiters(text: str) -> str:
    closers: list[str] = []
    in_string = False
    escape = False
    quote_char = '"'
    for char in text:
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == quote_char:
                in_string = False
            continue
        if char in {'"', "'"}:
            in_string = True
            quote_char = char
        elif char == "{":
            closers.append("}")
        elif char == "[":
            closers.append("]")
        elif char in {"}", "]"} and closers and char == closers[-1]:
            closers.pop()
    if in_string:
        text += quote_char
    return text + "".join(reversed(closers))


def _extract_json_value(text: str) -> Any:
    cleaned = _clean_json_candidate(text)
    parsed = _parse_jsonish_value(cleaned)
    if parsed is not _MISSING:
        return parsed

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        parsed = _parse_jsonish_value(cleaned[start : end + 1])
        if parsed is not _MISSING:
            return parsed
    if start >= 0:
        parsed = _parse_jsonish_value(_balance_json_delimiters(cleaned[start:]))
        if parsed is not _MISSING:
            return parsed

    try:
        return repair_json(cleaned, return_objects=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("JSON repair failed: %s", exc)
        return _MISSING


def extract_json_object(text: object) -> dict[str, Any] | None:
    """Extract one tolerant JSON object from model-produced text."""
    if not isinstance(text, str):
        return None
    value = _extract_json_value(text)
    return value if isinstance(value, dict) else None


def coerce_json_value(value: object) -> Any:
    """Coerce an already-decoded or model-produced JSON value once."""
    if isinstance(value, dict | list):
        return deepcopy(value)
    if not isinstance(value, str) or not value.strip():
        return value
    parsed = _extract_json_value(value)
    return value if parsed is _MISSING else parsed


__all__ = [
    "coerce_json_value",
    "extract_json_object",
    "strip_json_code_fence",
]
