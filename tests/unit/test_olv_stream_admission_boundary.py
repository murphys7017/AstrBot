"""Public stream admission must match the Hooks admitted for this event."""

import pytest

from astrbot.core.interaction.expression_agent import (
    InteractionExpressionError,
    PersonaExpressionResult,
)
from astrbot.core.interaction.output_controller import InteractionOutputController
from astrbot.core.interaction.turn_state import ensure_interaction_turn_state
from astrbot.core.interaction.types import PersonalResponseAction
from astrbot.core.message.components import Plain
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.star.star import StarMetadata, star_map
from astrbot.core.star.star_handler import (
    EventType,
    StarHandlerMetadata,
    star_handlers_registry,
)


class AdmissionEvent(AstrMessageEvent):
    async def flush_visible_segment(self, *, message_id: str) -> None:
        raise AssertionError("A silent admission probe must not publish output")


def make_event() -> AdmissionEvent:
    message = AstrBotMessage()
    message.type = MessageType.FRIEND_MESSAGE
    message.message = [Plain("probe")]
    message.message_str = "probe"
    message.sender = MessageMember(user_id="probe", nickname="probe")
    event = AdmissionEvent(
        "probe", message, PlatformMetadata("olv_pet_adapter", "probe", "probe"), "probe"
    )
    event.set_extra("_interaction_persona_segment_stream_requested", True)
    ensure_interaction_turn_state(event, turn_id="probe").runtime_config_snapshot = {}
    return event


@pytest.mark.asyncio
async def test_disabled_hook_does_not_block_but_active_unsafe_hook_does(monkeypatch):
    module = "data.plugins.stream_admission_probe.main"
    owner = StarMetadata(name="stream_admission_probe", module_path=module, activated=False)
    monkeypatch.setitem(star_map, module, owner)

    async def strip(_event):
        raise AssertionError("This admission probe must not execute the Hook")

    handler = StarHandlerMetadata(
        event_type=EventType.OnDecoratingResultEvent,
        handler_full_name=f"{module}_strip",
        handler_name="strip",
        handler_module_path=module,
        handler=strip,
        event_filters=[],
    )
    star_handlers_registry.append(handler)

    async def producer(emit, _message_id):
        result = PersonaExpressionResult(turn_action=PersonalResponseAction.SILENT)
        await emit({"type": "header", "turn_action": "silent"})
        await emit({"type": "finish", "result": result})
        return result

    async def on_header(_record):
        return False

    try:
        controller = InteractionOutputController()
        outcome = await controller.emit_persona_segment_stream(
            make_event(), producer=producer, on_header=on_header
        )
        assert outcome.status == "completed"
        owner.activated = True
        with pytest.raises(InteractionExpressionError, match="persona_stream_output_hooks_unsupported"):
            await controller.emit_persona_segment_stream(
                make_event(), producer=producer, on_header=on_header
            )
    finally:
        star_handlers_registry.remove(handler)
