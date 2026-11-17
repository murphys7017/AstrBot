"""Public prompt and scheduling boundaries from the proactive review."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from astrbot.core.interaction.observation import (
    RuntimeObservation,
    RuntimeObservationTarget,
)
from astrbot.core.interaction.runtime_event import RuntimeObservationEvent
from astrbot.core.platform.message_type import MessageType
from astrbot.core.prompt.context_types import ContextPack, ContextSlot
from astrbot.core.prompt.interfaces.prompt_extension_collector_interface import (
    PromptExtensionCollectorInterface,
)
from astrbot.core.prompt.render.engine import PromptRenderEngine
from astrbot.core.star.context import Context
from astrbot.core.star.star import StarMetadata, star_map


def test_bound_target_selects_its_configuration(tmp_path, monkeypatch):
    from astrbot.core import astrbot_config_mgr as config_module
    from astrbot.core.config.astrbot_config import AstrBotConfig
    from astrbot.core.db.sqlite import SQLiteDatabase
    from astrbot.core.interaction.turn_context import PlatformTurnContextFactory
    from astrbot.core.interaction.turn_state import set_interaction_turn_runtime_config
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.umop_config_router import UmopConfigRouter
    from astrbot.core.utils.shared_preferences import SharedPreferences

    monkeypatch.setattr(config_module, "get_astrbot_config_path", lambda: str(tmp_path))

    async def run():
        db = SQLiteDatabase(str(tmp_path / "routing.db"))
        await db.initialize()
        prefs = SharedPreferences(db, str(tmp_path / "preferences.json"))
        try:
            default = AstrBotConfig(
                str(tmp_path / "default.json"),
                default_config={
                    "provider_settings": {"default_personality": "target-persona"},
                    "platform": [
                        {"id": "desktop", "type": "olv_pet_adapter"},
                        {"id": "live-input", "type": "ag99live_stream_input"},
                    ],
                },
            )
            router = UmopConfigRouter(prefs)
            manager = config_module.AstrBotConfigManager(default, router, prefs)
            foreign = deepcopy(dict(default))
            foreign["provider_settings"]["default_personality"] = "input-persona"
            source_id = manager.create_conf(foreign, "input-profile")
            await router.update_route("live-input:FriendMessage:character", source_id)
            assert (
                manager.resolve_configuration_selection(
                    "live-input:FriendMessage:character"
                ).config_id
                == source_id
            )
            context = Context(
                asyncio.Queue(),
                default,
                db,
                None,
                SimpleNamespace(platform_insts=[]),
                None,
                None,
                None,
                manager,
                None,
                None,
            )

            def event():
                message = AstrBotMessage()
                message.type = MessageType.FRIEND_MESSAGE
                message.message = []
                item = AstrMessageEvent(
                    "viewer",
                    message,
                    PlatformMetadata("olv_pet_adapter", "live", "live-input"),
                    "character",
                )
                item.set_extra(
                    "interaction.context_target", "desktop:FriendMessage:character"
                )
                return item

            bound = PlatformTurnContextFactory.create(
                event(),
                config_id=source_id,
                runtime_config=foreign,
                plugin_context=context,
            )
            direct_message = event()
            direct_message.set_extra("interaction.context_target", None)
            direct_message.unified_msg_origin = "desktop:FriendMessage:character"
            direct = PlatformTurnContextFactory.create(
                direct_message,
                config_id="default",
                runtime_config=default,
                plugin_context=context,
            )
            assert bound.session.config_id == direct.session.config_id == "default"
            assert bound.session.unified_msg_origin == direct.session.unified_msg_origin
            assert (
                bound.runtime_config["provider_settings"]["default_personality"]
                == "target-persona"
            )
            assert bound.event.get_platform_id() == "live-input"
            conflicting = event()
            set_interaction_turn_runtime_config(conflicting, foreign)
            with pytest.raises(ValueError, match="conflicts with frozen"):
                PlatformTurnContextFactory.create(
                    conflicting,
                    config_id=source_id,
                    runtime_config=foreign,
                    plugin_context=context,
                )
        finally:
            prefs._scheduler.shutdown(wait=False)
            prefs._sync_loop.call_soon_threadsafe(prefs._sync_loop.stop)
            await db.engine.dispose()

    asyncio.run(run())


def observation_event(cancel=None):
    event = RuntimeObservationEvent(
        context=None,
        observation=RuntimeObservation(
            kind="personal_action",
            source="personal_runtime.policy",
            occurred_at=1,
            target_session=RuntimeObservationTarget(
                "desktop",
                "olv_pet_adapter",
                MessageType.FRIEND_MESSAGE,
                "character",
                True,
                True,
            ),
            cancel_event=cancel,
        ),
    )
    event.set_extra("interaction.context_visibility", "public")
    event.set_extra("provider_type", "deepseek_chat_completion")
    return event


def test_public_prompt_excludes_unscoped_recall(monkeypatch):
    monkeypatch.setitem(
        star_map, __name__, StarMetadata(name="review_test", module_path=__name__)
    )

    class Recall(PromptExtensionCollectorInterface):
        plugin_id = "unscoped_recall"
        prompt_message_targets = frozenset({"persona"})

        async def collect(self, *args, **kwargs):
            return []

        def collect_prompt_messages(self, *args, **kwargs):
            return [{"role": "user", "content": "PRIVATE_RECALL"}]

    class PublicState(Recall):
        plugin_id = "public_state"
        prompt_message_visibility = "public"

        def collect_prompt_messages(self, *args, **kwargs):
            return [{"role": "user", "content": "PUBLIC_CURRENT_STATE"}]

    context = Context(
        asyncio.Queue(), {}, None, None, None, None, None, None, None, None, None
    )
    context.register_prompt_extension_collector(Recall())
    context.register_prompt_extension_collector(PublicState())
    pack = ContextPack(
        slots={
            "memory.short_term": ContextSlot(
                "memory.short_term", "PRIVATE_SUMMARY", "memory", "memory"
            ),
            "extension.system": ContextSlot(
                "extension.system", "PRIVATE_EXTENSION", "extension", "plugin"
            ),
            "memory.topic_state": ContextSlot(
                "memory.topic_state",
                {"current_topic": "PUBLIC_TOPIC", "topic_summary": "PUBLIC_TOPIC"},
                "memory",
                "public_memory",
                meta={"visibility": "public"},
            ),
            "persona.prompt": ContextSlot(
                "persona.prompt", "ROLE_SETTINGS", "persona", "persona"
            ),
        }
    )
    result = PromptRenderEngine().render(
        pack,
        target="persona",
        context_view="proactive",
        event=observation_event(),
        plugin_context=context,
    )
    rendered = json.dumps(
        {"messages": result.messages, "system": result.system_prompt},
        ensure_ascii=False,
    )
    assert "PRIVATE_" not in rendered
    assert "PUBLIC_TOPIC" in rendered
    assert "PUBLIC_CURRENT_STATE" in rendered
    assert "ROLE_SETTINGS" in rendered
    # Projection must not remove private data from the canonical pack.
    assert pack.get_slot("memory.short_term").value == "PRIVATE_SUMMARY"


def test_opportunity_handoff_preserves_user_interruption():
    cancelled_before_handoff = asyncio.Event()
    pending = observation_event(cancelled_before_handoff)
    cancelled_before_handoff.set()
    with pytest.raises(asyncio.CancelledError):
        pending.consume_scheduling_opportunity()

    cancelled_after_handoff = asyncio.Event()
    active = observation_event(cancelled_after_handoff)
    active.consume_scheduling_opportunity()
    cancelled_after_handoff.set()
    assert not active.is_stopped()
    active.stop_event()
    assert active.is_stopped()
