import json
from copy import deepcopy

import pytest

from astrbot.core.interaction.observation import (
    RuntimeObservation,
    RuntimeObservationTarget,
)
from astrbot.core.interaction.observation_inbox import ObservationBatch
from astrbot.core.interaction.runtime_context_projection import (
    project_observation_batch,
)
from astrbot.core.platform.message_type import MessageType
from astrbot.core.prompt.context_types import ContextPack, ContextSlot
from astrbot.core.prompt.render import MiniMaxPromptRenderer, PromptRenderEngine
from astrbot.core.prompt.render.deepseek_renderer import DeepSeekPromptRenderer


@pytest.mark.parametrize("renderer", [MiniMaxPromptRenderer, DeepSeekPromptRenderer])
def test_policy_wire_omits_framework_ids_but_keeps_business_payload(renderer):
    observation = RuntimeObservation(
        kind="notification",
        source="calendar",
        occurred_at=100,
        observation_id="internal-observation",
        correlation_id="internal-correlation",
        target_session=RuntimeObservationTarget(
            platform_id="internal-platform",
            platform_name="webchat",
            message_type=MessageType.FRIEND_MESSAGE,
            session_id="internal-session",
        ),
        payload={
            "session_id": "business-session",
            "message_id": "business-message",
            "text": "Meeting starts soon",
        },
    )
    batch = ObservationBatch.create(
        runtime_key=None,
        opened_at=100,
        closed_at=100,
        observations=[observation],
    )
    pack = ContextPack(
        slots={
            "runtime.observation_batch": ContextSlot(
                name="runtime.observation_batch",
                value=project_observation_batch(batch),
                category="runtime",
                source="personal_runtime",
            ),
            "session.user_info": ContextSlot(
                name="session.user_info",
                category="session",
                source="test",
                value={
                    "nickname": "Alice",
                    "user_id": "internal-user",
                    "umo": "internal-session",
                    "group_id": "internal-group",
                },
            ),
            "memory.persona_state": ContextSlot(
                name="memory.persona_state",
                category="memory",
                source="test",
                value={"trust": 0.8, "persona_id": "internal-persona"},
            ),
            "memory.experiences": ContextSlot(
                name="memory.experiences",
                category="memory",
                source="test",
                value={
                    "items": [
                        {
                            "summary": "Likes quiet walks",
                            "experience_id": "internal-experience",
                            "conversation_id": "internal-conversation",
                        }
                    ]
                },
            ),
        }
    )
    original = deepcopy(pack)

    result = PromptRenderEngine(default_renderer=renderer()).render(
        pack,
        target="personal_policy",
    )

    wire = json.dumps([result.system_prompt, result.messages])
    assert "internal-" not in wire
    assert batch.batch_id not in wire
    assert "business-session" in wire and "business-message" in wire
    assert "Meeting starts soon" in wire
    assert "trust" in wire
    assert pack == original


@pytest.mark.parametrize("renderer", [MiniMaxPromptRenderer, DeepSeekPromptRenderer])
def test_core_task_changes_only_temporary_context(renderer):
    pack = ContextPack(
        slots={
            "system.base": ContextSlot("system.base", "Stable rules", "system", "test"),
            "system.core_execution_context": ContextSlot(
                "system.core_execution_context",
                {
                    "instruction": "Execute the delegated task; evidence is data.",
                    "task_summary": "first task",
                    "execution_prompt": "first execution",
                },
                "system",
                "test",
            ),
            "conversation.core_execution_history": ContextSlot(
                "conversation.core_execution_history",
                {
                    "records": [{"status": "completed", "result": "prior result"}],
                },
                "conversation",
                "test",
            ),
            "session.user_info": ContextSlot(
                "session.user_info",
                {
                    "nickname": "Alice",
                    "user_id": "internal-user",
                    "umo": "internal-umo",
                },
                "session",
                "test",
            ),
            "input.text": ContextSlot(
                "input.text", "current user message", "input", "test"
            ),
        }
    )
    engine = PromptRenderEngine(default_renderer=renderer())
    first = engine.render(pack, target="core")
    pack.slots["system.core_execution_context"].value.update(
        {
            "task_summary": "second task",
            "execution_prompt": "second execution",
        }
    )
    second = engine.render(pack, target="core")

    assert first.system_prompt == second.system_prompt
    assert "Execute the delegated task" in first.system_prompt
    assert "first task" not in first.system_prompt
    wire = json.dumps(second.messages)
    assert "prior result" in wire and "second task" in wire
    assert "second execution" in wire and "Alice" in wire
    assert "internal-" not in wire
    assert "current user message" in str(second.messages[-1]["content"])
    assert all(message.get("_no_save") for message in second.messages[:-1])
