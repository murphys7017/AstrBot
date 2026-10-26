"""AstrBot input owner and prompt reader for one independent NeuroBrain."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.prompt.interfaces import PromptExtensionCollectorInterface

from .client import NeuroBrainReadOnlyAPI
from .runtime import NeuroBrainRuntime

CURRENT_STATE_PROMPT_MESSAGE_CONTEXT_VIEWS = frozenset(
    {
        "turn_plan",
        "olv_stream",
        "final_result",
        "progress",
        "proactive",
    }
)


class _CurrentStatePromptCollector(PromptExtensionCollectorInterface):
    """Provide the latest state as a request-local message."""

    prompt_message_context_views = CURRENT_STATE_PROMPT_MESSAGE_CONTEXT_VIEWS

    def __init__(self, plugin: NeuroBrainPlugin) -> None:
        self._plugin = plugin

    @property
    def plugin_id(self) -> str:
        return "neurobrain_current_state"

    @property
    def priority(self) -> int:
        return 30

    @property
    def prompt_message_targets(self) -> frozenset[str]:
        return frozenset({"persona"})

    @property
    def lifecycle(self) -> str:
        return "dynamic"

    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: Any,
        provider_request: Any | None = None,
    ) -> list[Any]:
        """Keep the legacy extension collector surface empty.

        NeuroBrain state is request-local and must not enter a cached
        ContextPack. The synchronous message hook below reads it after the
        target ContextPack has already been selected.
        """
        del event, plugin_context, config, provider_request
        return []

    def collect_prompt_messages(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        *,
        target: str,
        context_view: str | None = None,
        provider_request: Any | None = None,
    ) -> list[dict[str, Any]]:
        del event, plugin_context, provider_request
        if not self._plugin.is_ready:
            return []
        if target != "persona":
            return []
        if (
            context_view is not None
            and context_view not in self.prompt_message_context_views
        ):
            return []

        state = self._plugin.readonly_api.get_state()
        if state is None:
            return []

        text = _format_current_state_prompt(state)
        if not text:
            return []
        return [
            {
                "role": "user",
                "content": (
                    "<neurobrain_state>\n"
                    f"{text}\n"
                    "</neurobrain_state>"
                ),
            }
        ]


def _format_current_state_prompt(state: Mapping[str, Any]) -> str:
    emotion = _format_dimension_values(state.get("emotion"))
    behavior = _format_dimension_values(state.get("behavior"))
    if not emotion:
        return ""

    step = state.get("step")
    step_text = (
        str(step)
        if isinstance(step, int) and not isinstance(step, bool)
        else "未知"
    )
    return (
        "角色当前内部状态，仅供本次表达参考，不要向用户展示数值。\n"
        f"情绪（0 到 1）：{emotion}\n"
        f"行为倾向（0 到 1，表示倾向而非动作命令）：{behavior or '无'}\n"
        f"状态步数：{step_text}。请结合当前消息自然调整表达，不要机械复述状态。"
    )


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
    """Submit AstrBot emotions; expose the single current state to readers."""

    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context)
        self.config = config if config is not None else {}
        self.enabled = bool(self.config.get("enabled", True))
        self._runtime: NeuroBrainRuntime | None = None
        self.readonly_api = NeuroBrainReadOnlyAPI(self)
        self._prompt_collector = _CurrentStatePromptCollector(self)
        context.register_prompt_extension_collector(self._prompt_collector)

    @property
    def is_ready(self) -> bool:
        return self.enabled and self._runtime is not None and self._runtime.is_running

    async def initialize(self) -> None:
        if not self.enabled:
            return
        checkpoint = str(self.config.get("checkpoint_path", "")).strip()
        if not checkpoint:
            logger.warning(
                "NeuroBrain is not initialized: configure checkpoint_path first."
            )
            return
        runtime = None
        try:
            path = Path(checkpoint).expanduser().resolve(strict=True)
            if not path.is_file():
                raise FileNotFoundError(path)
            device = str(self.config.get("device", "auto")).strip().lower()
            if device not in {"auto", "cpu", "cuda", "cuda:0"}:
                raise ValueError("device must be auto, cpu, cuda, or cuda:0")
            delta_seconds = float(self.config.get("delta_seconds", 1.0))
            if not math.isfinite(delta_seconds) or delta_seconds <= 0:
                raise ValueError("delta_seconds must be finite and positive")
            runtime = NeuroBrainRuntime(
                str(path), device=device, delta_seconds=delta_seconds
            )
            await asyncio.to_thread(runtime.start)
            self._runtime = runtime
        except asyncio.CancelledError:
            if runtime is not None:
                await asyncio.to_thread(runtime.stop)
            raise
        except Exception:
            if runtime is not None:
                await asyncio.to_thread(runtime.stop)
            logger.exception("NeuroBrain could not be initialized")

    def submit_emotion(self, tendency: Mapping[str, int]) -> None:
        """AstrBot's input boundary: enqueue emotion without waiting for inference."""
        if not self.enabled or self._runtime is None:
            raise RuntimeError("NeuroBrain is not ready")
        self._runtime.submit_emotion(tendency)

    @filter.on_persona_expression_result(persona_segment_stream_safe=True)
    async def on_persona_expression_result(
        self, event: AstrMessageEvent, result: Any
    ) -> None:
        if not self.is_ready:
            return
        segments = getattr(result, "segment_mappings", ())
        for segment in segments:
            if not isinstance(segment, Mapping):
                continue
            self._submit_segment_tendency(segment.get("tendency"))

    @filter.on_persona_expression_segment_intent_ready(
        persona_segment_stream_safe=True
    )
    async def on_persona_expression_segment_intent_ready(
        self,
        event: AstrMessageEvent,
        *,
        tendency: Any,
        **_: Any,
    ) -> None:
        """Accept OLV stream segment intent before its speech is delivered."""
        del event
        if self.is_ready:
            self._submit_segment_tendency(tendency)

    def _submit_segment_tendency(self, tendency: Any) -> None:
        if not isinstance(tendency, Mapping):
            return
        try:
            self.submit_emotion(tendency)
        except (TypeError, ValueError, RuntimeError) as exc:
            logger.warning("NeuroBrain emotion input rejected: %s", exc)

    def get_state(self) -> dict[str, Any] | None:
        runtime = self._runtime
        if runtime is None or not runtime.is_running:
            return None
        return runtime.get_state()

    async def terminate(self) -> None:
        runtime, self._runtime = self._runtime, None
        if runtime is not None:
            await asyncio.to_thread(runtime.stop)
        logger.info("NeuroBrain model thread stopped.")
