"""Real database boundaries for target history and scene quota persistence."""

import asyncio
import json

import pytest
from sqlalchemy import text

from astrbot.core.conversation_mgr import ConversationManager
from astrbot.core.db.sqlite import SQLiteDatabase
from astrbot.core.interaction.conversation_history import (
    commit_interaction_conversation_turn,
)
from astrbot.core.interaction.personal_runtime import PersonalRuntimeKey
from astrbot.core.interaction.personal_state import (
    CompletionFeedback,
    PersonalDeliveryStatus,
    PersonalState,
)
from astrbot.core.interaction.personal_state_repository import PersonalStateRepository
from astrbot.core.interaction.turn_state import ensure_interaction_turn_state
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.prompt.collectors.conversation_history_collector import (
    ConversationHistoryCollector,
)
from astrbot.core.prompt.context_views import resolve_prompt_context_view
from astrbot.core.star.context import Context


def test_target_context_and_scene_quota(tmp_path):
    async def run():
        db = SQLiteDatabase(str(tmp_path / "context.db"))
        await db.initialize()
        try:
            manager = ConversationManager(db)
            context = Context(
                asyncio.Queue(),
                {},
                db,
                None,
                None,
                manager,
                None,
                None,
                None,
                None,
                None,
            )
            target = "desktop:FriendMessage:character"
            conversation = await db.create_conversation(
                user_id=target,
                platform_id="desktop",
                content=[
                    {"role": "user", "content": "private topic"},
                    {"role": "assistant", "content": "private response"},
                ],
            )
            manager.session_conversations[target] = conversation.conversation_id

            class Sensor:
                plugin_id = "live_sensor"
                source_id = "idle"

            sensor = context.register_runtime_observation_sensor(Sensor())
            sensor.configure_schedule(session=target, mode="live")
            old_binding = context.get_proactive_schedule(target)
            assert old_binding.allows("plugin_sensor:live_sensor:idle")
            assert not old_binding.allows("plugin_sensor:daily_sensor:idle")
            with pytest.raises(ValueError, match="daily, live or off"):
                sensor.configure_schedule(session=target, mode="invalid")

            message = AstrBotMessage()
            message.type = MessageType.FRIEND_MESSAGE
            message.message_str = "viewer question"
            message.message = []
            event = AstrMessageEvent(
                "viewer question",
                message,
                PlatformMetadata("live_input", "live", "live-input"),
                "character",
            )
            event.set_extra("interaction.context_target", target)
            event.set_extra("interaction.context_visibility", "public")
            ensure_interaction_turn_state(event, turn_id="public-turn")
            assert await commit_interaction_conversation_turn(
                event=event,
                plugin_context=context,
                turn_id="public-turn",
                turn_material={
                    "turn_id": "public-turn",
                    "source": "platform",
                    "user_message": {"role": "user", "content": "viewer question"},
                    "assistant_text": "public response",
                },
            )
            slots = await ConversationHistoryCollector().collect(event, context, None)
            history = json.dumps(slots[0].value)
            assert "public response" in history and "viewer question" in history
            assert "private topic" not in history and "private response" not in history
            assert event.get_platform_id() == "live-input"
            assert conversation.conversation_id == slots[0].value["conversation_id"]

            sensor.configure_schedule(session=target, mode="daily")
            assert old_binding.cancelled.is_set()
            current = context.get_proactive_schedule(target)
            assert not current.allows("plugin_sensor:live_sensor:idle")
            assert current.allows("plugin_sensor:daily_sensor:idle")
            proactive = resolve_prompt_context_view("proactive")
            assert proactive.history_turns is None
            assert proactive.allows_slot("persona.prompt")

            key = PersonalRuntimeKey("default", "persona", target, "private")
            state = PersonalState()
            state.apply_completion_feedback(
                CompletionFeedback(
                    action_id="daily",
                    turn_id="daily",
                    delivery_status=PersonalDeliveryStatus.DELIVERED,
                    output_completed_at=1,
                ),
                usage_day="2026-11-18",
                scene="daily",
            )
            state.apply_completion_feedback(
                CompletionFeedback(
                    action_id="live",
                    turn_id="live",
                    delivery_status=PersonalDeliveryStatus.DELIVERED,
                    output_completed_at=2,
                ),
                usage_day="2026-11-18",
                scene="live",
            )
            repository = PersonalStateRepository(db)
            await repository.save(key, state.persistent_snapshot())
            restored = await repository.load(key)
            assert restored.proactive_outputs_by_scene == {"daily": 1, "live": 1}
            # Exercise migration against an existing row, not just create_all.
            async with db.engine.begin() as connection:
                await connection.execute(
                    text(
                        "ALTER TABLE personal_runtime_states DROP COLUMN proactive_outputs_by_scene"
                    )
                )
            await db.initialize()
            migrated = await repository.load(key)
            assert migrated.daily_proactive_outputs == 2
            assert migrated.proactive_outputs_by_scene == {}
        finally:
            await db.engine.dispose()

    asyncio.run(run())
