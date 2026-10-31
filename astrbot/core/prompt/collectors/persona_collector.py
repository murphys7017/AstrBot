"""
人格信息收集器 - Context Data Layer (Phase 1)

本模块实现 PersonaCollector，负责收集人格相关的上下文信息。
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from astrbot.core import logger
from astrbot.core.persona_context import (
    PersonaContextSeed,
    PersonaContextSlot,
    build_persona_slots_from_resolution,
)
from astrbot.core.persona_resolution import (
    PersonaResolution,
    build_event_persona_resolution_key,
    resolve_event_persona,
)
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context

from ..context_types import ContextSlot
from ..interfaces.context_collector_inferface import ContextCollectorInterface

if TYPE_CHECKING:
    from astrbot.core.astr_main_agent import MainAgentBuildConfig


_PERSONA_RESOLUTION_CACHE_EXTRA_KEY = "_prompt_persona_resolution_cache"


class PersonaCollector(ContextCollectorInterface):
    """
    人格信息收集器。

    收集以下 context items:
    - persona.prompt: 人格设定 prompt
    - persona.begin_dialogs: 开场对话（已处理）
    - persona.tools_whitelist: 工具白名单
    - persona.skills_whitelist: Skills 白名单
    """

    parallel_safe = True

    def __init__(
        self,
        persona_resolution: PersonaResolution | None = None,
        persona_context_seed: PersonaContextSeed | None = None,
    ) -> None:
        self.persona_resolution = persona_resolution
        self.persona_context_seed = persona_context_seed

    @property
    def lifecycle(self) -> str:
        # Runtime-owned Seeds already have an event-local cache below. Keeping
        # that path out of Prompt's generic static cache avoids a second deep
        # copy of the same immutable persona projection.
        return "dynamic" if self.persona_context_seed is not None else "static"

    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        provider_request: ProviderRequest | None = None,
    ) -> list[ContextSlot]:
        """
        收集人格相关的上下文信息。

        流程:
        1. 从 event 中获取 provider_request（如果有），从中获取 conversation
        2. 优先使用 Runtime/Interaction 已解析的人格；否则调用
           persona_manager.resolve_selected_persona() 解析当前生效的 persona
        3. 从 persona 对象中提取 4 个 context items
        4. 构造 ContextSlot 列表返回
        """
        if self.persona_context_seed is not None:
            seed_cache_key = ("runtime_seed", id(self.persona_context_seed))
            cached_slots = _get_cached_resolution_slots(event, seed_cache_key)
            if cached_slots is not None:
                return cached_slots
            slots = _materialize_prompt_slots(
                self.persona_context_seed.materialize_slots()
            )
            _store_resolution_slots(event, seed_cache_key, slots)
            return slots

        slots: list[ContextSlot] = []

        # Persona is a required collector. Let collection failures reach the
        # prompt pipeline instead of turning an unavailable persona into an
        # indistinguishable empty result.
        # 步骤 1: 获取 conversation
        req = provider_request or event.get_extra("provider_request")
        conversation_persona_id = None
        if req and hasattr(req, "conversation") and req.conversation:
            conversation_persona_id = req.conversation.persona_id

        # 步骤 2: 复用上游已解析的人格，只有兼容路径才重新解析。
        persona_mgr = getattr(plugin_context, "persona_manager", None)
        if not persona_mgr:
            raise RuntimeError("PersonaManager not available")

        resolution_key = build_event_persona_resolution_key(
            event=event,
            persona_manager=persona_mgr,
            conversation_persona_id=conversation_persona_id,
            provider_settings=config.provider_settings,
        )
        cached_slots = _get_cached_resolution_slots(event, resolution_key)
        if cached_slots is not None:
            return cached_slots

        resolution = self.persona_resolution
        if resolution is None and self.persona_context_seed is None:
            resolution = await resolve_event_persona(
                event=event,
                persona_manager=persona_mgr,
                conversation_persona_id=conversation_persona_id,
                provider_settings=config.provider_settings,
            )
        if self.persona_context_seed is not None:
            projected_slots = self.persona_context_seed.materialize_slots()
        else:
            assert resolution is not None
            projected_slots = build_persona_slots_from_resolution(resolution)
        slots = _materialize_prompt_slots(projected_slots)
        _store_resolution_slots(event, resolution_key, slots)
        return slots


def _materialize_prompt_slots(
    projected_slots: list[PersonaContextSlot],
) -> list[ContextSlot]:
    """Adapt core persona projections to the Prompt transport model."""
    return [
        ContextSlot(
            name=slot.name,
            value=slot.value,
            category=slot.category,
            source=slot.source,
            llm_exposure=slot.llm_exposure,
            placement=slot.placement,
            render_mode=slot.render_mode,
            priority=slot.priority,
            meta=slot.meta,
        )
        for slot in projected_slots
    ]


def _get_cached_resolution_slots(
    event: AstrMessageEvent,
    key: object,
) -> list[ContextSlot] | None:
    cache = event.get_extra(_PERSONA_RESOLUTION_CACHE_EXTRA_KEY, {})
    if not isinstance(cache, dict) or key not in cache:
        return None
    try:
        return deepcopy(cache[key])
    except Exception:  # noqa: BLE001
        return None


def _store_resolution_slots(
    event: AstrMessageEvent,
    key: object,
    slots: list[ContextSlot],
) -> None:
    cache = event.get_extra(_PERSONA_RESOLUTION_CACHE_EXTRA_KEY, {})
    if not isinstance(cache, dict):
        cache = {}
    try:
        cache[key] = deepcopy(slots)
        event.set_extra(_PERSONA_RESOLUTION_CACHE_EXTRA_KEY, cache)
    except Exception:  # noqa: BLE001
        logger.debug("Failed to cache resolved persona slots", exc_info=True)
