"""AstrBot bridge for the isolated NeuroBrain WebSocket service."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .client import NeuroBrainBridge, NeuroBrainReadOnlyAPI


def _optional_persona_hook():
    hook = getattr(filter, "on_persona_expression_result", None)
    if callable(hook):
        return hook()

    def _identity(handler):
        return handler

    return _identity


@register(
    "astrbot_plugin_neurobrain",
    "YakumoAki",
    "AG99 NeuroBrain WebSocket bridge",
    "0.1.0",
)
class NeuroBrainPlugin(Star):
    """Submit validated Persona tendency values and expose read-only state."""

    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context)
        self.context = context
        self.config = config if config is not None else {}
        self.enabled = bool(self.config.get("enabled", True))
        self.state_scope = (
            str(self.config.get("state_scope", "persona")).strip().lower()
        )
        if self.state_scope not in {"global", "persona", "conversation"}:
            self.state_scope = "persona"
        self.default_persona_id = (
            str(self.config.get("default_persona_id", "Alice pro")).strip()
            or "Alice pro"
        )
        self._bridge = NeuroBrainBridge(
            url=str(self.config.get("server_url", "ws://127.0.0.1:8765")),
            token=str(self.config.get("write_token", "")),
            request_timeout_seconds=float(
                self.config.get("request_timeout_seconds", 2.0)
            ),
            connect_timeout_seconds=float(
                self.config.get("connect_timeout_seconds", 5.0)
            ),
            client_id=str(self.config.get("client_id", "astrbot")),
        )
        self.readonly_api: NeuroBrainReadOnlyAPI = self._bridge.readonly_api
        self._seen_events: set[str] = set()
        self._submission_tasks: set[asyncio.Task[Any]] = set()
        self._submission_lock = asyncio.Lock()
        logger.info(
            "NeuroBrain bridge configured: enabled=%s url=%s state_scope=%s",
            self.enabled,
            self._bridge.url,
            self.state_scope,
        )

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self) -> None:
        if not self.enabled:
            logger.info("NeuroBrain bridge is disabled by configuration.")
            return
        try:
            await self._bridge.start()
            logger.info("NeuroBrain WebSocket bridge connected.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("NeuroBrain WebSocket unavailable: %s", exc)

    @_optional_persona_hook()
    async def on_persona_expression_result(
        self,
        event: AstrMessageEvent,
        result: Any,
    ) -> None:
        if not self.enabled:
            return
        segments = getattr(result, "segment_mappings", ())
        if not isinstance(segments, (list, tuple)) or not segments:
            return
        normalized_segments = [
            dict(segment) for segment in segments if isinstance(segment, Mapping)
        ]
        if not normalized_segments:
            return
        state_key = self._resolve_state_key(event)
        turn_id = str(event.get_extra("_turn_id", "") or "").strip()
        result_metadata = getattr(result, "metadata", None)
        persona_result_id = str(
            result_metadata.get("interaction.persona_result_id") or ""
            if isinstance(result_metadata, Mapping)
            else ""
        ).strip()
        fingerprint = hashlib.sha256(
            json.dumps(
                normalized_segments,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:24]
        event_identity = persona_result_id or fingerprint
        event_id = f"{turn_id or 'turnless'}:{event_identity}"
        if event_id in self._seen_events:
            return
        self._seen_events.add(event_id)
        if len(self._seen_events) > 4096:
            self._seen_events = set(tuple(self._seen_events)[-2048:])
        if persona_result_id:
            self._bridge.register_persona_result(persona_result_id)
        task = asyncio.create_task(
            self._submit_persona_result(
                state_key=state_key,
                event_id=event_id,
                persona_result_id=persona_result_id,
                segments=normalized_segments,
            ),
            name=f"neurobrain.submit.{persona_result_id[:12] or event_id[-12:]}",
        )
        self._submission_tasks.add(task)
        task.add_done_callback(self._submission_tasks.discard)

    async def _submit_persona_result(
        self,
        *,
        state_key: str,
        event_id: str,
        persona_result_id: str,
        segments: list[dict[str, Any]],
    ) -> None:
        try:
            async with self._submission_lock:
                response = await self._bridge.submit_stimulus(
                    state_key=state_key,
                    event_id=event_id,
                    segments=segments,
                )
        except Exception as exc:  # noqa: BLE001
            self._seen_events.discard(event_id)
            logger.warning(
                "NeuroBrain stimulus update skipped: state_key=%s error=%s",
                state_key,
                exc,
            )
            response = None
        except asyncio.CancelledError:
            response = None
            if persona_result_id:
                self._bridge.complete_persona_result(persona_result_id, response)
            raise
        if persona_result_id:
            self._bridge.complete_persona_result(persona_result_id, response)

    def _resolve_persona_id(self, event: AstrMessageEvent) -> str:
        state = event.get_extra("_interaction_turn_state", None)
        persona_id = getattr(state, "persona_id", None)
        return (
            str(persona_id or self.default_persona_id).strip()
            or self.default_persona_id
        )

    def _resolve_state_key(self, event: AstrMessageEvent) -> str:
        if self.state_scope == "global":
            return "global"
        if self.state_scope == "conversation":
            origin = str(event.unified_msg_origin or "").strip()
            return f"conversation:{origin or 'unknown'}"
        return f"persona:{self._resolve_persona_id(event)}"

    async def terminate(self) -> None:
        tasks = tuple(self._submission_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._bridge.close()
        logger.info("NeuroBrain WebSocket bridge stopped.")
