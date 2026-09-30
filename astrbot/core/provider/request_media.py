"""ProviderRequest media normalization at mutable plugin boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from astrbot import logger
from astrbot.core.agent.message import ImageURLPart, TextPart
from astrbot.core.utils.image_materializer import (
    ImageMaterializationError,
    MaterializedImage,
    materialize_image_ref,
)

if TYPE_CHECKING:
    from astrbot.core.provider.entities import ProviderRequest


@dataclass(frozen=True, slots=True)
class ProviderRequestImageStats:
    discovered: int = 0
    normalized: int = 0
    dropped: int = 0
    optimized: int = 0
    original_bytes: int = 0
    normalized_bytes: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.normalized or self.dropped)


async def normalize_provider_request_images(
    request: ProviderRequest,
    *,
    max_images: int | None = None,
    max_total_bytes: int | None = None,
    max_dimension: int | None = None,
) -> ProviderRequestImageStats:
    """Validate request images and replace them with bounded data URLs.

    The limits are optional so existing provider behavior remains unchanged.
    Persona passes them explicitly because its prompt is latency-sensitive and
    must not carry unbounded base64 material from the canonical context.
    """
    if max_images is not None and max_images <= 0:
        raise ValueError("max_images must be positive")
    if max_total_bytes is not None and max_total_bytes <= 0:
        raise ValueError("max_total_bytes must be positive")
    if max_dimension is not None and max_dimension <= 0:
        raise ValueError("max_dimension must be positive")

    references = _collect_image_references(request)
    if not references:
        return ProviderRequestImageStats()

    unique_references = list(dict.fromkeys(references))
    semaphore = asyncio.Semaphore(4)

    async def materialize(
        reference: str,
    ) -> tuple[str, MaterializedImage | None, bool, int]:
        try:
            async with semaphore:
                image = await materialize_image_ref(reference)
            original_bytes = len(image.data)
            optimized = False
            if max_dimension is not None:
                prepared = image.prepare_for_provider(max_dimension=max_dimension)
                optimized = prepared.data != image.data
                image = prepared
            return reference, image, optimized, original_bytes
        except ImageMaterializationError as exc:
            logger.warning(
                "ProviderRequest image rejected after plugin mutation: ref=%s error=%s",
                _reference_preview(reference),
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ProviderRequest image normalization failed: ref=%s error=%s",
                _reference_preview(reference),
                exc,
                exc_info=True,
            )
        return reference, None, False, 0

    materialized_results = await asyncio.gather(
        *(materialize(ref) for ref in unique_references)
    )
    resolved = {
        reference: (image, optimized, original_bytes)
        for reference, image, optimized, original_bytes in materialized_results
    }
    kept_bytes = 0
    kept_images = 0
    selected: dict[str, str | None] = {}
    optimized_count = 0
    original_bytes = 0
    normalized_bytes = 0
    for reference in unique_references:
        image, optimized, image_original_bytes = resolved[reference]
        if image is None:
            selected[reference] = None
            continue
        image_bytes = len(image.data)
        original_bytes += image_original_bytes
        if max_images is not None and kept_images >= max_images:
            selected[reference] = None
            continue
        if (
            max_total_bytes is not None
            and kept_bytes + image_bytes > max_total_bytes
        ):
            selected[reference] = None
            continue
        selected[reference] = image.to_data_url()
        kept_images += 1
        kept_bytes += image_bytes
        normalized_bytes += image_bytes
        optimized_count += int(optimized)

    request.image_urls = [
        normalized
        for reference in _string_items(request.image_urls)
        if (normalized := selected.get(reference)) is not None
    ]
    request.extra_user_content_parts = _normalize_extra_content_parts(
        request.extra_user_content_parts,
        selected,
    )
    request.contexts = _normalize_context_images(request.contexts, selected)

    normalized_count = sum(value is not None for value in selected.values())
    return ProviderRequestImageStats(
        discovered=len(unique_references),
        normalized=normalized_count,
        dropped=len(unique_references) - normalized_count,
        optimized=optimized_count,
        original_bytes=original_bytes,
        normalized_bytes=normalized_bytes,
    )


def _collect_image_references(request: ProviderRequest) -> list[str]:
    references = _string_items(request.image_urls)
    for part in _list_items(request.extra_user_content_parts):
        reference = _content_part_image_reference(part)
        if reference:
            references.append(reference)
    for message in _list_items(request.contexts):
        if not isinstance(message, dict):
            continue
        for part in _list_items(message.get("content")):
            reference = _content_part_image_reference(part)
            if reference:
                references.append(reference)
    return references


def _normalize_extra_content_parts(
    parts: object,
    resolved: dict[str, str | None],
) -> list[Any]:
    normalized_parts: list[Any] = []
    for part in _list_items(parts):
        reference = _content_part_image_reference(part)
        if not reference:
            normalized_parts.append(part)
            continue
        normalized = resolved.get(reference)
        if normalized is None:
            normalized_parts.append(TextPart(text="[Image]"))
            continue
        if isinstance(part, ImageURLPart):
            copied = part.model_copy(deep=True)
            copied.image_url.url = normalized
            normalized_parts.append(copied)
            continue
        if isinstance(part, dict):
            copied = dict(part)
            image_url = copied.get("image_url")
            if isinstance(image_url, dict):
                copied["image_url"] = {**image_url, "url": normalized}
            else:
                copied["image_url"] = normalized
            normalized_parts.append(copied)
    return normalized_parts


def _normalize_context_images(
    contexts: object,
    resolved: dict[str, str | None],
) -> list[Any]:
    normalized_contexts: list[Any] = []
    for message in _list_items(contexts):
        if not isinstance(message, dict):
            normalized_contexts.append(message)
            continue
        content = message.get("content")
        if not isinstance(content, list):
            normalized_contexts.append(message)
            continue
        copied_message = dict(message)
        copied_parts: list[Any] = []
        for part in content:
            reference = _content_part_image_reference(part)
            if not reference:
                copied_parts.append(part)
                continue
            normalized = resolved.get(reference)
            if normalized is None:
                copied_parts.append({"type": "text", "text": "[Image]"})
                continue
            copied_part = dict(part)
            image_url = copied_part.get("image_url")
            if isinstance(image_url, dict):
                copied_part["image_url"] = {**image_url, "url": normalized}
            else:
                copied_part["image_url"] = normalized
            copied_parts.append(copied_part)
        copied_message["content"] = copied_parts
        normalized_contexts.append(copied_message)
    return normalized_contexts


def _content_part_image_reference(part: object) -> str | None:
    if isinstance(part, ImageURLPart):
        return _normalize_reference(part.image_url.url)
    if not isinstance(part, dict) or part.get("type") != "image_url":
        return None
    image_url = part.get("image_url")
    if isinstance(image_url, dict):
        return _normalize_reference(image_url.get("url"))
    return _normalize_reference(image_url)


def _string_items(value: object) -> list[str]:
    return [
        normalized
        for item in _list_items(value)
        if (normalized := _normalize_reference(item)) is not None
    ]


def _list_items(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _normalize_reference(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _reference_preview(reference: str, *, max_length: int = 160) -> str:
    if len(reference) <= max_length:
        return reference
    return f"{reference[: max_length - 3]}..."


__all__ = ["ProviderRequestImageStats", "normalize_provider_request_images"]
