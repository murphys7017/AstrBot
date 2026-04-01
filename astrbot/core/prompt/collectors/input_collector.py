"""
Input context collector for prompt context packing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.core import logger
from astrbot.core.message.components import File, Image, Reply
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context
from astrbot.core.utils.quoted_message.settings import (
    SETTINGS as DEFAULT_QUOTED_MESSAGE_SETTINGS,
)
from astrbot.core.utils.quoted_message_parser import (
    extract_quoted_message_images,
    extract_quoted_message_text,
)
from astrbot.core.utils.string_utils import normalize_and_dedupe_strings

from ..context_types import ContextSlot
from ..interfaces.context_collector_inferface import ContextCollectorInterface

if TYPE_CHECKING:
    from astrbot.core.astr_main_agent import MainAgentBuildConfig
    from astrbot.core.utils.quoted_message.settings import QuotedMessageParserSettings


@dataclass
class _ReplyPayload:
    texts: list[str] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    fallback_image_count: int = 0


class InputCollector(ContextCollectorInterface):
    """Collect the current user input into prompt context slots."""

    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        provider_request: ProviderRequest | None = None,
    ) -> list[ContextSlot]:
        slots: list[ContextSlot] = []

        try:
            effective_text, text_source = self._resolve_effective_text(
                event=event,
                config=config,
                provider_request=provider_request,
            )
            if effective_text:
                slots.append(
                    ContextSlot(
                        name="input.text",
                        value=effective_text,
                        category="input",
                        source="event_input",
                        meta={"source_field": text_source},
                    )
                )

            current_images = await self._collect_current_images(event)
            if current_images:
                slots.append(
                    ContextSlot(
                        name="input.images",
                        value=current_images,
                        category="input",
                        source="event_input",
                        meta={"count": len(current_images), "source": "current"},
                    )
                )

            current_files = self._collect_files_from_components(
                event.message_obj.message,
                source="current",
            )
            reply_payload = await self._collect_reply_payloads(event, config)

            if reply_payload.texts:
                slots.append(
                    ContextSlot(
                        name="input.quoted_text",
                        value="\n\n".join(reply_payload.texts),
                        category="input",
                        source="quoted_message",
                        meta={"reply_count": len(reply_payload.texts)},
                    )
                )

            if reply_payload.images:
                slots.append(
                    ContextSlot(
                        name="input.quoted_images",
                        value=reply_payload.images,
                        category="input",
                        source="quoted_message",
                        meta={
                            "count": len(reply_payload.images),
                            "fallback_count": reply_payload.fallback_image_count,
                        },
                    )
                )

            all_files = [*current_files, *reply_payload.files]
            if all_files:
                slots.append(
                    ContextSlot(
                        name="input.files",
                        value=all_files,
                        category="input",
                        source="event_input",
                        meta={"count": len(all_files)},
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to collect input context: %s", exc, exc_info=True)

        return slots

    def _resolve_effective_text(
        self,
        *,
        event: AstrMessageEvent,
        config: MainAgentBuildConfig,
        provider_request: ProviderRequest | None,
    ) -> tuple[str, str]:
        if provider_request and isinstance(provider_request.prompt, str):
            return provider_request.prompt, "provider_request.prompt"

        message_text = event.message_str or ""
        wake_prefix = config.provider_wake_prefix or ""
        if wake_prefix and message_text.startswith(wake_prefix):
            return message_text[len(wake_prefix) :], "event.message_str"
        return message_text, "event.message_str"

    async def _collect_current_images(
        self,
        event: AstrMessageEvent,
    ) -> list[dict[str, Any]]:
        images: list[dict[str, Any]] = []
        seen_refs: set[str] = set()

        for comp in event.message_obj.message:
            if not isinstance(comp, Image):
                continue
            image_record = await self._build_image_record(comp, source="current")
            if not image_record:
                continue
            ref = image_record["ref"]
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            images.append(image_record)

        return images

    def _collect_files_from_components(
        self,
        components: list[object],
        *,
        source: str,
        reply_id: str | int | None = None,
    ) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []

        for comp in components:
            if not isinstance(comp, File):
                continue
            file_record = self._build_file_record(
                comp,
                source=source,
                reply_id=reply_id,
            )
            if file_record is not None:
                files.append(file_record)

        return files

    async def _collect_reply_payloads(
        self,
        event: AstrMessageEvent,
        config: MainAgentBuildConfig,
    ) -> _ReplyPayload:
        payload = _ReplyPayload()
        reply_components = [
            comp for comp in event.message_obj.message if isinstance(comp, Reply)
        ]
        if not reply_components:
            return payload

        settings = self._get_quoted_message_parser_settings(config)
        seen_texts: set[str] = set()
        seen_image_refs: set[str] = set()

        for reply_component in reply_components:
            reply_id = getattr(reply_component, "id", None)

            try:
                quoted_text = await extract_quoted_message_text(
                    event,
                    reply_component,
                    settings=settings,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to collect quoted text: umo=%s reply_id=%s error=%s",
                    event.unified_msg_origin,
                    reply_id,
                    exc,
                    exc_info=True,
                )
                quoted_text = None

            if quoted_text:
                normalized_text = quoted_text.strip()
                if normalized_text and normalized_text not in seen_texts:
                    seen_texts.add(normalized_text)
                    payload.texts.append(normalized_text)

            has_embedded_image = False
            if reply_component.chain:
                for reply_item in reply_component.chain:
                    if isinstance(reply_item, Image):
                        has_embedded_image = True
                        image_record = await self._build_image_record(
                            reply_item,
                            source="quoted",
                            resolution="embedded",
                            reply_id=reply_id,
                        )
                        if not image_record:
                            continue
                        ref = image_record["ref"]
                        if ref in seen_image_refs:
                            continue
                        seen_image_refs.add(ref)
                        payload.images.append(image_record)

                payload.files.extend(
                    self._collect_files_from_components(
                        reply_component.chain,
                        source="quoted",
                        reply_id=reply_id,
                    )
                )

            if has_embedded_image:
                continue

            try:
                fallback_refs = normalize_and_dedupe_strings(
                    await extract_quoted_message_images(
                        event,
                        reply_component,
                        settings=settings,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to collect quoted images: umo=%s reply_id=%s error=%s",
                    event.unified_msg_origin,
                    reply_id,
                    exc,
                    exc_info=True,
                )
                continue

            remaining_limit = max(
                config.max_quoted_fallback_images - payload.fallback_image_count,
                0,
            )
            if remaining_limit <= 0:
                if fallback_refs:
                    logger.warning(
                        "Skip quoted fallback images due to limit=%d for umo=%s",
                        config.max_quoted_fallback_images,
                        event.unified_msg_origin,
                    )
                continue

            if len(fallback_refs) > remaining_limit:
                logger.warning(
                    "Truncate quoted fallback images for umo=%s reply_id=%s from %d to %d",
                    event.unified_msg_origin,
                    reply_id,
                    len(fallback_refs),
                    remaining_limit,
                )
                fallback_refs = fallback_refs[:remaining_limit]

            for image_ref in fallback_refs:
                if image_ref in seen_image_refs:
                    continue
                seen_image_refs.add(image_ref)
                payload.images.append(
                    self._build_image_record_from_ref(
                        image_ref,
                        source="quoted",
                        resolution="fallback",
                        reply_id=reply_id,
                    )
                )
                payload.fallback_image_count += 1

        return payload

    async def _build_image_record(
        self,
        image_component: Image,
        *,
        source: str,
        resolution: str | None = None,
        reply_id: str | int | None = None,
    ) -> dict[str, Any] | None:
        image_ref = (getattr(image_component, "url", "") or "").strip()
        transport = "url"
        if not image_ref:
            image_ref = (getattr(image_component, "file", "") or "").strip()
            if image_ref.startswith("http://") or image_ref.startswith("https://"):
                transport = "url"
            elif image_ref.startswith("base64://"):
                transport = "base64"
            elif image_ref.startswith("file://"):
                transport = "file"
            elif image_ref:
                transport = "file"
        if not image_ref:
            image_ref = (getattr(image_component, "path", "") or "").strip()
            if image_ref:
                transport = "path"
        if not image_ref:
            try:
                image_ref = await image_component.convert_to_file_path()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to resolve image component: %s", exc, exc_info=True
                )
                return None
            transport = "resolved_path"

        return self._build_image_record_from_ref(
            image_ref,
            source=source,
            resolution=resolution,
            reply_id=reply_id,
            transport=transport,
        )

    def _build_image_record_from_ref(
        self,
        image_ref: str,
        *,
        source: str,
        resolution: str | None = None,
        reply_id: str | int | None = None,
        transport: str | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "ref": image_ref,
            "transport": transport or self._infer_transport(image_ref),
            "source": source,
        }
        if resolution is not None:
            record["resolution"] = resolution
        if reply_id is not None:
            record["reply_id"] = reply_id
        return record

    def _build_file_record(
        self,
        file_component: File,
        *,
        source: str,
        reply_id: str | int | None = None,
    ) -> dict[str, Any] | None:
        file_path = getattr(file_component, "file_", "") or ""
        file_url = getattr(file_component, "url", "") or ""
        file_name = getattr(file_component, "name", "") or ""

        if not file_name and not file_path and not file_url:
            return None

        record: dict[str, Any] = {
            "name": file_name,
            "file": file_path,
            "url": file_url,
            "source": source,
            "reply_id": reply_id,
        }
        return record

    def _get_quoted_message_parser_settings(
        self,
        config: MainAgentBuildConfig,
    ) -> QuotedMessageParserSettings:
        provider_settings = config.provider_settings
        if not isinstance(provider_settings, dict):
            return DEFAULT_QUOTED_MESSAGE_SETTINGS

        overrides = provider_settings.get("quoted_message_parser")
        if not isinstance(overrides, dict):
            return DEFAULT_QUOTED_MESSAGE_SETTINGS

        return DEFAULT_QUOTED_MESSAGE_SETTINGS.with_overrides(overrides)

    def _infer_transport(self, image_ref: str) -> str:
        if image_ref.startswith("http://") or image_ref.startswith("https://"):
            return "url"
        if image_ref.startswith("base64://"):
            return "base64"
        if image_ref.startswith("file://"):
            return "file"
        return "resolved_path"
