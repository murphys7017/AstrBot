"""Incompatible optional plugins must not suppress an OLV Persona stream."""

import pytest

from astrbot.core.interaction.effects import PersonaEffectSpec
from astrbot.core.interaction.expression_agent import (
    InteractionExpressionAgent,
    InteractionExpressionError,
    PersonaExpressionRequest,
    PersonaExpressionResult,
)
from astrbot.core.interaction.output_controller import InteractionOutputController
from astrbot.core.interaction.turn_state import ensure_interaction_turn_state
from astrbot.core.interaction.types import PersonalResponseAction
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain, ResultContentType
from astrbot.core.output_lifecycle import PreOutputProcessor
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.star.context import Context, plugin_owner_scope
from astrbot.core.star.star import StarMetadata, star_map
from astrbot.core.star.star_handler import (
    EventType,
    StarHandlerMetadata,
    star_handlers_registry,
)


class AdmissionEvent(AstrMessageEvent):
    async def flush_visible_segment(self, *, message_id: str) -> None:
        raise AssertionError("A silent admission probe must not publish output")

    async def complete_visible_turn(self) -> None:
        self.set_extra("completion_sent", True)


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
async def test_active_unsafe_decorator_is_skipped_only_for_olv_stream(monkeypatch):
    module = "data.plugins.stream_admission_probe.main"
    owner = StarMetadata(name="stream_admission_probe", module_path=module, activated=True)
    monkeypatch.setitem(star_map, module, owner)

    async def strip(event):
        event.stop_event()
        event.set_result(None)

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
        event = make_event()
        event.set_extra("_interaction_persona_segment_stream_active", True)
        prepared = await PreOutputProcessor().prepare_interaction_message(
            event, MessageChain([Plain("hello")]), ResultContentType.LLM_RESULT
        )
        assert prepared.message is not None
        assert prepared.message.get_plain_text() == "hello"
        assert not event.is_stopped()
        controller = InteractionOutputController()
        outcome = await controller.emit_persona_segment_stream(
            event, producer=producer, on_header=on_header
        )
        assert outcome.status == "completed"
        # The ordinary (including gate-off/delegated-final) path still runs it.
        event.set_extra("_interaction_persona_segment_stream_active", False)
        prepared = await PreOutputProcessor().prepare_interaction_message(
            event, MessageChain([Plain("hello")]), ResultContentType.LLM_RESULT
        )
        assert prepared.message is None and prepared.stop_requested
        with pytest.raises(InteractionExpressionError, match="persona_stream_output_hooks_unsupported"):
            await controller.emit_persona_segment_stream(
                make_event(), producer=producer, on_header=on_header
            )
    finally:
        star_handlers_registry.remove(handler)


@pytest.mark.asyncio
async def test_terminal_observer_and_legacy_extensions_have_stream_scoped_admission(monkeypatch):
    module = "data.plugins.stream_observer_probe.main"
    monkeypatch.setitem(star_map, module, StarMetadata(name="probe", module_path=module))

    async def stop(event, result):
        event.stop_event()

    async def observe(event, result):
        result.metadata["observed"] = True

    handlers = [
        StarHandlerMetadata(
            event_type=EventType.OnPersonaExpressionResultEvent,
            handler_full_name=f"{module}_{name}",
            handler_name=name,
            handler_module_path=module,
            handler=callback,
            event_filters=[],
            extras_configs=extras,
        )
        for name, callback, extras in (
            ("stop", stop, {}),
            ("observe", observe, {"persona_segment_stream_safe": True}),
        )
    ]
    for handler in handlers:
        star_handlers_registry.append(handler)
    context = Context(*([None] * 11))

    class Contributor:
        plugin_id = "probe"

    with plugin_owner_scope(module_path=module, plugin_name="probe"):
        context.register_interaction_result_contributor(Contributor())
        context.register_persona_effect(PersonaEffectSpec(
            plugin_id="probe", name="probe.effect", description="probe",
            parameters={"type": "object", "properties": {}},
        ))
    event = make_event()
    event.set_extra("_interaction_persona_segment_stream_active", True)
    try:
        result = await InteractionExpressionAgent().publish_local_expression(
            event, speech="hello", request=PersonaExpressionRequest()
        )
        assert result.speech == "hello" and result.metadata["observed"] is True
        assert not event.is_stopped()
        assert context.list_persona_effects(event=event) == []
        assert context.list_interaction_result_contributors(event=event) == []
        event.set_extra("_interaction_persona_segment_stream_active", False)
        assert len(context.list_persona_effects(event=event)) == 1
        assert len(context.list_interaction_result_contributors(event=event)) == 1
    finally:
        for handler in handlers:
            star_handlers_registry.remove(handler)


@pytest.mark.asyncio
async def test_unsafe_after_send_hook_cannot_block_finished_stream_completion(monkeypatch):
    module = "data.plugins.stream_completion_probe.main"
    monkeypatch.setitem(star_map, module, StarMetadata(name="probe", module_path=module))

    async def stop(event):
        event.stop_event()

    handler = StarHandlerMetadata(
        event_type=EventType.OnAfterMessageSentEvent,
        handler_full_name=f"{module}_stop",
        handler_name="stop",
        handler_module_path=module,
        handler=stop,
        event_filters=[],
    )
    star_handlers_registry.append(handler)
    try:
        event = make_event()
        # Middleware has returned from generation and cleared active at this point.
        event.set_extra("_interaction_persona_segment_stream_active", False)
        event.set_extra("_interaction_persona_segment_stream_status", "completed")
        controller = InteractionOutputController()
        assert await controller.complete_visible_delivery(event) is True
        assert event.get_extra("completion_sent") is True
        assert not event.is_stopped()

        ordinary = make_event()
        assert await controller.complete_visible_delivery(ordinary) is False
        assert ordinary.get_extra("completion_sent") is None
    finally:
        star_handlers_registry.remove(handler)
