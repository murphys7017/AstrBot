"""
Policy context collector for prompt context packing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astrbot.core import logger
from astrbot.core.astr_main_agent_resources import (
    LLM_SAFETY_MODE_SYSTEM_PROMPT,
    SANDBOX_MODE_PROMPT,
)
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context

from ..context_types import ContextSlot
from ..interfaces.context_collector_inferface import ContextCollectorInterface

if TYPE_CHECKING:
    from astrbot.core.astr_main_agent import MainAgentBuildConfig


class PolicyCollector(ContextCollectorInterface):
    """Collect active request policy prompts without mutating the request."""

    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        provider_request: ProviderRequest | None = None,
    ) -> list[ContextSlot]:
        del event, plugin_context, provider_request

        slots: list[ContextSlot] = []

        try:
            safety_slot = self._build_safety_prompt_slot(config)
            if safety_slot is not None:
                slots.append(safety_slot)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to collect policy safety prompt: %s", exc, exc_info=True
            )

        try:
            sandbox_slot = self._build_sandbox_prompt_slot(config)
            if sandbox_slot is not None:
                slots.append(sandbox_slot)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to collect policy sandbox prompt: %s", exc, exc_info=True
            )

        return slots

    def _build_safety_prompt_slot(
        self,
        config: MainAgentBuildConfig,
    ) -> ContextSlot | None:
        if not config.llm_safety_mode:
            return None
        if config.safety_mode_strategy != "system_prompt":
            return None

        return ContextSlot(
            name="policy.safety_prompt",
            value=LLM_SAFETY_MODE_SYSTEM_PROMPT,
            category="system",
            source="main_agent_policy",
            meta={
                "enabled_by_config": True,
                "strategy": config.safety_mode_strategy,
            },
        )

    def _build_sandbox_prompt_slot(
        self,
        config: MainAgentBuildConfig,
    ) -> ContextSlot | None:
        if config.computer_use_runtime != "sandbox":
            return None

        return ContextSlot(
            name="policy.sandbox_prompt",
            value=SANDBOX_MODE_PROMPT,
            category="system",
            source="main_agent_policy",
            meta={
                "enabled_by_config": True,
                "runtime": config.computer_use_runtime,
            },
        )
