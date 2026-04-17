"""Per-event caches shared by prompt collect and legacy request decoration."""

from __future__ import annotations

import json
from typing import Any

_IMAGE_CAPTION_CACHE_EXTRA_KEY = "prompt_image_caption_cache"
_FILE_EXTRACT_CACHE_EXTRA_KEY = "prompt_file_extract_cache"

_MISSING = object()


def _get_event_cache(event: object | None, key: str) -> dict[str, Any] | None:
    if event is None:
        return None

    getter = getattr(event, "get_extra", None)
    if not callable(getter):
        return None

    try:
        cache = getter(key)
    except Exception:  # noqa: BLE001
        return None

    if isinstance(cache, dict):
        return cache

    setter = getattr(event, "set_extra", None)
    if not callable(setter):
        return None

    cache = {}
    try:
        setter(key, cache)
    except Exception:  # noqa: BLE001
        return None
    return cache


def build_image_caption_cache_key(
    *,
    provider_id: str | None,
    prompt: str,
    image_refs: list[str],
) -> str:
    return json.dumps(
        {
            "provider_id": provider_id or "",
            "prompt": prompt,
            "image_refs": list(image_refs),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def get_cached_image_caption(
    event: object | None,
    *,
    provider_id: str | None,
    prompt: str,
    image_refs: list[str],
) -> tuple[bool, str | None]:
    cache = _get_event_cache(event, _IMAGE_CAPTION_CACHE_EXTRA_KEY)
    if cache is None:
        return False, None

    key = build_image_caption_cache_key(
        provider_id=provider_id,
        prompt=prompt,
        image_refs=image_refs,
    )
    if key not in cache:
        return False, None
    return True, cache[key]


def set_cached_image_caption(
    event: object | None,
    *,
    provider_id: str | None,
    prompt: str,
    image_refs: list[str],
    result: str | None,
) -> None:
    cache = _get_event_cache(event, _IMAGE_CAPTION_CACHE_EXTRA_KEY)
    if cache is None:
        return

    key = build_image_caption_cache_key(
        provider_id=provider_id,
        prompt=prompt,
        image_refs=image_refs,
    )
    cache[key] = result


def build_file_extract_cache_key(
    *,
    provider: str,
    file_path: str,
) -> str:
    return json.dumps(
        {
            "provider": provider,
            "file_path": file_path,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def get_cached_file_extract(
    event: object | None,
    *,
    provider: str,
    file_path: str,
) -> tuple[bool, str | None]:
    cache = _get_event_cache(event, _FILE_EXTRACT_CACHE_EXTRA_KEY)
    if cache is None:
        return False, None

    key = build_file_extract_cache_key(provider=provider, file_path=file_path)
    if key not in cache:
        return False, None
    return True, cache[key]


def set_cached_file_extract(
    event: object | None,
    *,
    provider: str,
    file_path: str,
    result: str | None,
) -> None:
    cache = _get_event_cache(event, _FILE_EXTRACT_CACHE_EXTRA_KEY)
    if cache is None:
        return

    key = build_file_extract_cache_key(provider=provider, file_path=file_path)
    cache[key] = result


__all__ = [
    "build_file_extract_cache_key",
    "build_image_caption_cache_key",
    "get_cached_file_extract",
    "get_cached_image_caption",
    "set_cached_file_extract",
    "set_cached_image_caption",
]
