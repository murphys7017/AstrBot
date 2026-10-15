"""AstrBot owner for in-process NeuroBrain state and prompt integration."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.persona_resolution import resolve_event_persona
from astrbot.core.prompt.extensions import PromptExtension
from astrbot.core.prompt.interfaces import PromptExtensionCollectorInterface

from .client import NeuroBrainReadOnlyAPI


def _optional_persona_hook():
    hook = getattr(filter, "on_persona_expression_result", None)
    if callable(hook):
        return hook()

    def _identity(handler):
        return handler

    return _identity


def _create_state_store(
    checkpoint_path: str,
    *,
    device_preference: str,
    delta_seconds: float,
):
    import torch
    from neurobrain import NeuroBrainStateStore

    if device_preference == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    elif device_preference.startswith("cuda"):
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable")
        device = device_preference
    else:
        device = device_preference

    store = NeuroBrainStateStore(
        checkpoint_path,
        device=device,
        delta_seconds=delta_seconds,
    )
    return store, device


class _CurrentStatePromptCollector(PromptExtensionCollectorInterface):
    """Read the latest state for each prompt build without using a cache."""

    def __init__(self, plugin: NeuroBrainPlugin) -> None:
        self._plugin = plugin

    @property
    def plugin_id(self) -> str:
        return "neurobrain_current_state"

    @property
    def priority(self) -> int:
        return 30

    @property
    def lifecycle(self) -> str:
        return "dynamic"

    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: Any,
        provider_request: Any | None = None,
    ) -> list[PromptExtension]:
        if not self._plugin.enabled:
            return []

        state_key = await self._plugin._resolve_state_key(
            event,
            provider_request=provider_request,
            plugin_context=plugin_context,
            config=config,
        )
        state = self._plugin.readonly_api.get_state(state_key)
        if state is None:
            return []

        emotion = _format_dimension_values(state.get("emotion"))
        behavior = _format_dimension_values(state.get("behavior"))
        if not emotion:
            return []

        step = state.get("step")
        step_text = (
            str(step)
            if isinstance(step, int) and not isinstance(step, bool)
            else "未知"
        )
        text = (
            "NeuroBrain 当前内部状态（供角色表达参考，不要向用户展示数值）：\n"
            f"情绪（0 到 1）：{emotion}\n"
            f"行为倾向（0 到 1，表示倾向而非动作命令）：{behavior or '无'}\n"
            f"状态步数：{step_text}。请结合当前消息自然调整表达，不要机械复述状态。"
        )
        return [
            PromptExtension(
                plugin_id=self.plugin_id,
                mount="system",
                title="NeuroBrain 当前状态",
                value=text,
                value_kind="text",
                order=30,
                meta={"targets": ["core", "persona"]},
            )
        ]


def _format_dimension_values(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    items = []
    for name, raw_value in value.items():
        if (
            not isinstance(name, str)
            or isinstance(raw_value, bool)
            or not isinstance(raw_value, (int, float))
            or not math.isfinite(float(raw_value))
        ):
            continue
        items.append(f"{name}={min(1.0, max(0.0, float(raw_value))):.2f}")
    return "、".join(items)


@register(
    "astrbot_plugin_neurobrain",
    "YakumoAki",
    "AG99 NeuroBrain in-process integration",
    "0.2.0",
)
class NeuroBrainPlugin(Star):
    """Advance NeuroBrain from Persona results and expose read-only state."""

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
        self._store: Any | None = None
        self._device: str | None = None
        self._load_attempted = False
        self._seen_events: set[str] = set()
        self._submission_tasks: set[asyncio.Task[Any]] = set()
        self._submission_lock = asyncio.Lock()
        self._persona_result_snapshots: OrderedDict[
            str, asyncio.Future[dict[str, Any] | None]
        ] = OrderedDict()
        self.readonly_api = NeuroBrainReadOnlyAPI(self)
        self._prompt_collector = _CurrentStatePromptCollector(self)
        register_collector = getattr(
            self.context,
            "register_prompt_extension_collector",
            None,
        )
        if callable(register_collector):
            register_collector(self._prompt_collector)

        logger.info(
            "NeuroBrain configured: enabled=%s state_scope=%s",
            self.enabled,
            self.state_scope,
        )

    @property
    def is_ready(self) -> bool:
        return self.enabled and self._store is not None

    async def initialize(self) -> None:
        """Load the configured checkpoint whenever the plugin is loaded."""

        await self._load_store()

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self) -> None:
        """Keep startup-hook compatibility for a full AstrBot boot."""

        if self._load_attempted:
            return
        await self._load_store()

    async def _load_store(self) -> None:
        if self._load_attempted:
            return
        self._load_attempted = True
        if not self.enabled:
            logger.info("NeuroBrain is disabled by configuration.")
            return

        checkpoint_value = str(self.config.get("checkpoint_path", "")).strip()
        if not checkpoint_value:
            logger.warning(
                "NeuroBrain is not initialized: configure checkpoint_path first."
            )
            return

        try:
            checkpoint_path = Path(checkpoint_value).expanduser().resolve(strict=True)
            if not checkpoint_path.is_file():
                raise FileNotFoundError(checkpoint_path)
            requested_device = str(self.config.get("device", "auto")).strip().lower()
            if requested_device not in {"auto", "cpu", "cuda", "cuda:0"}:
                raise ValueError("device must be auto, cpu, cuda, or cuda:0")
            delta_seconds = float(self.config.get("delta_seconds", 1.0))
            if not math.isfinite(delta_seconds) or delta_seconds < 0:
                raise ValueError("delta_seconds must be finite and non-negative")

            self._store, self._device = await asyncio.to_thread(
                _create_state_store,
                str(checkpoint_path),
                device_preference=requested_device,
                delta_seconds=delta_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("NeuroBrain checkpoint could not be loaded: %s", exc)
            return

        logger.info(
            "NeuroBrain loaded in AstrBot: checkpoint=%s device=%s state_scope=%s",
            checkpoint_path,
            self._device,
            self.state_scope,
        )
        try:
            await self._initialize_default_state()
        except Exception:
            logger.exception("NeuroBrain default state initialization failed")

    async def _initialize_default_state(self) -> None:
        if self._store is None:
            return
        if self.state_scope == "global":
            state_key = "global"
        elif self.state_scope == "persona":
            state_key = f"persona:{self.default_persona_id}"
        else:
            return
        if self._store.read(state_key) is not None:
            return

        from neurobrain import ASTRBOT_TENDENCY_DIMENSIONS

        tendency = dict.fromkeys(
            (source_name for source_name, _ in ASTRBOT_TENDENCY_DIMENSIONS),
            0,
        )
        result = await self._store.update(
            state_key,
            event_id=f"bootstrap:{state_key}",
            segments=[{"tendency": tendency}],
        )
        snapshot = result.get("snapshot")
        step = snapshot.get("step") if isinstance(snapshot, Mapping) else "unknown"
        logger.info(
            "NeuroBrain initialized default state from zero stimulus: state_key=%s step=%s",
            state_key,
            step,
        )

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

        state_key = await self._resolve_state_key(
            event,
            plugin_context=self.context,
        )
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
            self._register_persona_result(persona_result_id)

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
        response = None
        try:
            async with self._submission_lock:
                if self._store is not None:
                    response = await self._store.update(
                        state_key,
                        event_id=event_id,
                        segments=segments,
                    )
        except asyncio.CancelledError:
            self._seen_events.discard(event_id)
            raise
        except Exception as exc:  # noqa: BLE001
            self._seen_events.discard(event_id)
            logger.warning(
                "NeuroBrain stimulus update skipped: state_key=%s error=%s",
                state_key,
                exc,
            )
        finally:
            if persona_result_id:
                self._complete_persona_result(persona_result_id, response)

    async def _resolve_state_key(
        self,
        event: AstrMessageEvent,
        provider_request: Any | None = None,
        *,
        plugin_context: Context | None = None,
        config: Any = None,
    ) -> str:
        if self.state_scope == "global":
            return "global"
        if self.state_scope == "conversation":
            origin = str(event.unified_msg_origin or "").strip()
            return f"conversation:{origin or 'unknown'}"

        state = event.get_extra("_interaction_turn_state", None)
        persona_id = getattr(state, "persona_id", None)
        if isinstance(persona_id, str) and persona_id.strip():
            return f"persona:{persona_id.strip()}"

        request = provider_request
        if request is None:
            request = event.get_extra("provider_request", None)
        conversation = getattr(request, "conversation", None)
        conversation_persona_id = getattr(conversation, "persona_id", None)

        if config is None:
            config = getattr(state, "runtime_config_snapshot", None)
        if config is None:
            config = event.get_extra("_astrbot_config", None)
        provider_settings = getattr(config, "provider_settings", None)
        if not isinstance(provider_settings, Mapping) and isinstance(config, Mapping):
            provider_settings = config.get("provider_settings")
        if not isinstance(provider_settings, Mapping):
            provider_settings = {}

        context = plugin_context if plugin_context is not None else self.context
        persona_manager = getattr(context, "persona_manager", None)
        if persona_manager is not None:
            resolution = await resolve_event_persona(
                event=event,
                persona_manager=persona_manager,
                conversation_persona_id=conversation_persona_id,
                provider_settings=provider_settings,
            )
            persona_id = resolution.persona_id
        else:
            persona_id = conversation_persona_id

        resolved_persona_id = (
            str(persona_id or self.default_persona_id).strip()
            or self.default_persona_id
        )
        return f"persona:{resolved_persona_id}"

    def _get_state(self, state_key: str | None = None) -> dict[str, Any] | None:
        if self._store is None:
            return None
        if state_key is not None:
            return self._store.read(state_key)
        states = self._store.list_states()
        return states[0] if len(states) == 1 else None

    def _list_states(self) -> list[dict[str, Any]]:
        return self._store.list_states() if self._store is not None else []

    def _register_persona_result(self, persona_result_id: str) -> None:
        key = persona_result_id.strip()
        if not key:
            return
        future = self._persona_result_snapshots.get(key)
        if future is None or future.done():
            future = asyncio.get_running_loop().create_future()
            self._persona_result_snapshots[key] = future
        self._persona_result_snapshots.move_to_end(key)
        self._trim_persona_result_snapshots()

    def _complete_persona_result(
        self,
        persona_result_id: str,
        response: Mapping[str, Any] | None,
    ) -> None:
        key = persona_result_id.strip()
        if not key:
            return
        future = self._persona_result_snapshots.get(key)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._persona_result_snapshots[key] = future
        self._persona_result_snapshots.move_to_end(key)
        if not future.done():
            future.set_result(
                copy.deepcopy(dict(response)) if response is not None else None
            )
        self._trim_persona_result_snapshots()

    async def _wait_for_persona_result(
        self,
        persona_result_id: str,
        *,
        timeout_seconds: float = 1.0,
    ) -> dict[str, Any] | None:
        key = persona_result_id.strip()
        if not key or not self.is_ready:
            return None
        future = self._persona_result_snapshots.get(key)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._persona_result_snapshots[key] = future
        self._persona_result_snapshots.move_to_end(key)
        self._trim_persona_result_snapshots()
        try:
            response = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=max(0.0, float(timeout_seconds)),
            )
        except asyncio.TimeoutError:
            return None
        if not isinstance(response, Mapping):
            return None
        snapshot = response.get("snapshot")
        return copy.deepcopy(dict(snapshot)) if isinstance(snapshot, Mapping) else None

    def _trim_persona_result_snapshots(self) -> None:
        while len(self._persona_result_snapshots) > 4096:
            _, future = self._persona_result_snapshots.popitem(last=False)
            if not future.done():
                future.set_result(None)

    async def terminate(self) -> None:
        tasks = tuple(self._submission_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for future in self._persona_result_snapshots.values():
            if not future.done():
                future.set_result(None)
        self._persona_result_snapshots.clear()
        self._store = None
        self._device = None
        logger.info("NeuroBrain in-process integration stopped.")
