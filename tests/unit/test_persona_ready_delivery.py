import asyncio
from types import SimpleNamespace

import pytest

from astrbot.core.interaction.contributors import InteractionResultContribution
from astrbot.core.interaction.expression_agent import (
    PersonaExpressionResult,
    PersonaExpressionSegment,
)
from astrbot.core.interaction.output_controller import InteractionOutputController
from astrbot.core.interaction.turn_state import (
    ensure_interaction_turn_state,
    get_interaction_turn_immediate_reply,
    set_interaction_turn_emitting_immediate_reply,
    set_interaction_turn_runtime_config,
)
from astrbot.core.message.components import Plain, Record
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import (
    AstrBotMessage,
    MessageMember,
    MessageType,
)
from astrbot.core.platform.platform_metadata import PlatformMetadata


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "interrupt", "tts_failure"])
async def test_ready_delivery_emits_first_segment_before_second_finishes(tmp_path, mode):
    interrupt = mode == "interrupt"
    second_started = asyncio.Event()
    release_second = asyncio.Event()
    second_cancelled = asyncio.Event()
    flushed = []
    sent = []
    completed = []
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"audio fixture")

    class Event(AstrMessageEvent):
        async def send(self, message):
            sent.extend(message.chain)

        async def send_message_with_extras(self, message, **kwargs):
            extras = kwargs["platform_extras"]
            assert extras["persona_segment_index"] == len(sent)
            assert extras["persona_segment_count"] == 2
            assert extras["output_segment"]["message_id"] not in flushed
            sent.extend(message.chain)

        async def flush_visible_segment(self, *, message_id):
            flushed.append(message_id)
            assert [item.text for item in sent if isinstance(item, Record)] == (
                ["第一句"] if len(flushed) == 1 or mode == "tts_failure" else ["第一句", "第二句"]
            )
            if len(flushed) == 1:
                assert second_started.is_set()
                if interrupt:
                    asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
                    return
                release_second.set()

        async def complete_visible_message(self, *, message_id):
            completed.append(message_id)

    inbound = AstrBotMessage()
    inbound.type = MessageType.FRIEND_MESSAGE
    inbound.message_id = "incoming"
    inbound.sender = MessageMember(user_id="test-user", nickname="test")
    inbound.message = [Plain("测试")]
    inbound.message_str = "测试"
    inbound.self_id = "bot"
    event = Event("测试", inbound, PlatformMetadata(name="ready-test", description="test", id="ready-test"), "test")
    event.set_extra("_turn_id", "ready-turn")
    ensure_interaction_turn_state(event, turn_id="ready-turn")
    set_interaction_turn_runtime_config(event, {
        "provider_tts_settings": {"enable": True, "trigger_probability": 1.0, "dual_output": True},
        "provider_settings": {}, "platform_settings": {},
    })
    set_interaction_turn_emitting_immediate_reply(event, True)

    class VoiceProvider:
        async def get_audio(self, text):
            if text == "第一句":
                await second_started.wait()
            else:
                second_started.set()
                try:
                    await release_second.wait()
                except asyncio.CancelledError:
                    second_cancelled.set()
                    raise
                if mode == "tts_failure":
                    raise RuntimeError("TTS provider unavailable")
            return str(audio)

    async def finalize(_event, _context, **kwargs):
        index = kwargs["materialization"]["persona_segment_index"]
        if index == 1:
            await release_second.wait()
        return InteractionResultContribution(plugin_id="ready-test")

    class Contributor:
        async def collect(self, *args):
            return InteractionResultContribution(
                plugin_id="ready-test", post_materialization=[finalize],
                supports_segment_materialization=True,
            )

    provider = VoiceProvider()
    context = SimpleNamespace(
        list_interaction_result_contributors=lambda **kwargs: [Contributor()],
        get_using_tts_provider=lambda *args, **kwargs: provider,
        get_config=lambda **kwargs: {},
    )
    controller = InteractionOutputController(plugin_context=context)
    persona = PersonaExpressionResult(
        segments=[PersonaExpressionSegment(speech="第一句"), PersonaExpressionSegment(speech="第二句")],
        metadata={"interaction.persona_result_id": "ready-persona"},
    )
    operation = controller.capture_message_chain(event=event, message=MessageChain([Plain(persona.speech)]), prepared_expression=persona)
    if interrupt:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(operation, timeout=2)
        assert second_cancelled.is_set()
        assert completed == []
        assert get_interaction_turn_immediate_reply(event) == "第一句"
    else:
        assert await asyncio.wait_for(operation, timeout=2)
        assert len(flushed) == 2
        assert len(completed) == 1
        if mode == "tts_failure":
            failed = [item for item in sent if isinstance(item, Plain)]
            assert len(failed) == 1 and failed[0].text == "第二句"
            assert failed[0].delivery_metadata["output_segment"]["tts"]["status"] == "failed"
