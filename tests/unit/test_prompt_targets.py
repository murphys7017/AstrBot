from types import SimpleNamespace

import pytest

from astrbot.core.prompt import (
    ContextPack,
    ContextSlot,
    PromptContextView,
    PromptTarget,
)
from astrbot.core.prompt.context_collect import log_context_pack
from astrbot.core.prompt.render import (
    AnthropicPromptRenderer,
    BasePromptRenderer,
    OpenAIPromptRenderer,
    PromptRenderProfile,
    apply_render_result_to_request,
)
from astrbot.core.prompt.render.engine import PromptRenderEngine
from astrbot.core.prompt.render.minimax_renderer import MiniMaxPromptRenderer
from astrbot.core.prompt.targets import project_context_pack


def _slot(name: str, value, category: str) -> ContextSlot:
    return ContextSlot(name=name, value=value, category=category, source="test")


@pytest.mark.parametrize("view", [PromptContextView.TURN_PLAN, PromptContextView.OLV_STREAM])
@pytest.mark.parametrize("text", ["帮我看看", "你好", "", "你能看得出来我在玩什么吗"])
def test_attached_visual_context_does_not_require_keywords(view, text):
    from astrbot.core.prompt.context_views import project_prompt_context_view

    snapshot = {"ref": "desktop.png", "semantic_type": "desktop_snapshot"}
    explicit_image = {"ref": "upload.png"}
    pack = ContextPack(slots={
        "input.text": _slot("input.text", text, "input"),
        "input.images": _slot("input.images", [snapshot, explicit_image], "input"),
        "input.explicit_content_parts": _slot("input.explicit_content_parts", [
            {"type": "image_url", "image_url": {"url": "desktop.png"}},
            {"type": "image_url", "image_url": {"url": "upload.png"}},
        ], "input"),
        "input.media_content_parts": _slot("input.media_content_parts", [
            {"type": "image_url", "image_url": {"url": "desktop.png"}},
            {"type": "image_url", "image_url": {"url": "upload.png"}},
        ], "input"),
    })
    projected = project_prompt_context_view(pack, view)
    assert projected.get_slot("input.images").value == [snapshot, explicit_image]
    assert pack.get_slot("input.images").value == [snapshot, explicit_image]
    for name in ("input.explicit_content_parts", "input.media_content_parts"):
        assert projected.get_slot(name).value == pack.get_slot(name).value


@pytest.mark.parametrize("view", [PromptContextView.TURN_PLAN, PromptContextView.OLV_STREAM])
def test_olv_desktop_image_and_source_label_reach_provider_request(view):
    import asyncio
    import base64
    import json
    from io import BytesIO

    from PIL import Image

    from astrbot.core.prompt.render import apply_render_result_to_request
    from astrbot.core.provider.entities import ProviderRequest
    from astrbot.core.provider.request_media import normalize_provider_request_images

    buffer = BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
    reference = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    pack = ContextPack(slots={
        "input.text": _slot("input.text", "你好", "input"),
        "input.images": _slot("input.images", [{
            "ref": reference,
            "semantic_type": "desktop_snapshot",
            "explanation": "这是用户当前桌面截图。",
        }], "input"),
    })
    rendered = PromptRenderEngine().render(
        pack, target=PromptTarget.PERSONA, context_view=view,
    )
    # Persona uses a separate request prompt and keeps rendered input in contexts.
    rendered.request_prompt = "Reply to the user."
    request = ProviderRequest()
    apply_render_result_to_request(rendered, request)
    stats = asyncio.run(normalize_provider_request_images(
        request, max_images=4, max_total_bytes=4 * 1024 * 1024, max_dimension=1536,
    ))
    wire_context = json.dumps(request.contexts, ensure_ascii=False)
    assert stats.normalized == 1 and stats.dropped == 0
    image_urls = [
        part["image_url"]["url"]
        for message in request.contexts
        for part in message.get("content", [])
        if isinstance(part, dict) and part.get("type") == "image_url"
    ]
    assert len(image_urls) == 1
    normalized_image = base64.b64decode(image_urls[0].split(",", 1)[1])
    assert Image.open(BytesIO(normalized_image)).size == (2, 2)
    assert "image_url" in wire_context
    assert "这是用户当前桌面截图。" in wire_context


def test_persona_request_omits_bookkeeping_without_losing_context():
    import json
    from copy import deepcopy

    from astrbot.core.prompt.render import apply_render_result_to_request
    from astrbot.core.provider.entities import ProviderRequest

    pack = ContextPack(slots={
        "input.text": _slot("input.text", "你好", "input"),
        "session.user_info": _slot("session.user_info", {
            "nickname": "Alice", "role": "friend", "is_group": False,
            "platform_name": "internal-platform", "umo": "internal-session",
            "user_id": "internal-user", "conversation_scope": "internal-scope",
        }, "session"),
        "input.visible_reply_material": _slot("input.visible_reply_material", {
            "source_text": "提醒已经创建，任务 ID：business-task-42",
            "short_reply": True, "allow_empty": True, "preserve_facts": True,
        }, "input"),
        "memory.topic_state": _slot("memory.topic_state", {
            "current_topic": "收衣服", "topic_confidence": 0.987654321,
        }, "memory"),
        "input.images": _slot("input.images", [{
            "ref": "https://example.com/desktop.png",
            "semantic_type": "desktop_snapshot",
            "explanation": "这是用户当前桌面截图。",
            "explanation_source": "internal-platform",
            "context_role": "supporting", "transport": "url",
        }], "input"),
        "extension.system": _persona_identity_extension_slot(),
    })
    pack.get_slot("input.text").meta.update({
        "raw_text": "internal-raw", "source_field": "internal-source",
        "explanation": "internal-explanation", "context_role": "primary",
    })
    original = deepcopy(pack)
    rendered = PromptRenderEngine().render(pack, target=PromptTarget.PERSONA)
    rendered.request_prompt = "Reply to the user."
    request = ProviderRequest()
    apply_render_result_to_request(rendered, request)
    wire = json.dumps({
        "system": request.system_prompt, "prompt": request.prompt,
        "contexts": request.contexts, "images": request.image_urls,
    }, ensure_ascii=False)
    for diagnostic in (
        "internal-", "topic_confidence", "short_reply", "allow_empty",
        "preserve_facts", "ag99live.companion_identity.prompt",
        "explanation_source", "context_role", "semantic_type",
    ):
        assert diagnostic not in wire
    for fact in (
        "Alice", "friend", "你好", "收衣服", "business-task-42",
        "AG99live Companion Identity", "这是用户当前桌面截图。",
    ):
        assert fact in wire
    assert "image_url" in wire and "https://example.com/desktop.png" in wire
    assert "<ref>" not in wire
    assert pack == original
    core = project_context_pack(pack, PromptTarget.CORE)
    assert core.get_slot("session.user_info").value["umo"] == "internal-session"


def _persona_identity_extension_slot() -> ContextSlot:
    return ContextSlot(
        name="extension.system",
        value={
            "items": [
                {
                    "plugin_id": "ag99live.companion_identity.prompt",
                    "value": "AG99live Companion Identity",
                    "meta": {"targets": ["persona"]},
                }
            ]
        },
        category="extension",
        source="test",
    )


def test_redacted_slot_never_renders_original_value_or_metadata(monkeypatch):
    slot = ContextSlot(
        "system.global", "private value", "system", "test",
        llm_exposure="redacted", meta={"private_note": "private metadata"},
    )
    pack = ContextPack(slots={slot.name: slot})
    rendered = PromptRenderEngine().render(pack, target=PromptTarget.CORE)
    assert "private value" not in rendered.system_prompt
    assert "private metadata" not in rendered.system_prompt
    assert "[REDACTED]" in rendered.system_prompt
    assert slot.value == "private value"
    assert rendered.metadata["render_timings"]
    records = []
    monkeypatch.setattr("astrbot.core.prompt.context_collect.prompt_trace_enabled", lambda: True)
    monkeypatch.setattr(
        "astrbot.core.prompt.context_collect.record_prompt_trace",
        lambda *args, **fields: records.append(fields),
    )
    log_context_pack(pack, event=SimpleNamespace())
    assert "private value" not in str(records)
    assert "private metadata" not in str(records)
    assert "[REDACTED]" in str(records)


def _canonical_pack() -> ContextPack:
    return ContextPack(
        slots={
            "system.global": _slot("system.global", "global instructions", "system"),
            "system.base": _slot("system.base", "system", "system"),
            "system.core_execution_context": _slot(
                "system.core_execution_context",
                {"execution_prompt": "run core task"},
                "system",
            ),
            "persona.prompt": _slot("persona.prompt", "full persona", "persona"),
            "persona.summary": _slot("persona.summary", "brief persona", "persona"),
            "input.text": _slot("input.text", "current", "input"),
            "input.visible_reply_material": _slot(
                "input.visible_reply_material", {"source_text": "core"}, "input"
            ),
            "input.previous_persona_acknowledgement": _slot(
                "input.previous_persona_acknowledgement",
                {"text": "I am checking that now."},
                "input",
            ),
            "conversation.history": _slot(
                "conversation.history",
                {
                    "turn_count": 5,
                    "turns": [{"id": index} for index in range(5)],
                },
                "memory",
            ),
            "conversation.group_recent": _slot(
                "conversation.group_recent",
                {
                    "format": "group_recent_v2",
                    "instruction": "untrusted",
                    "records": [
                        {
                            "id": "ambient-1",
                            "sender": "Alice",
                            "user_id": "10001",
                            "time": "10:00:00",
                            "content": "ambient",
                        }
                    ],
                },
                "conversation",
            ),
            "conversation.pending_execution_continuity": _slot(
                "conversation.pending_execution_continuity",
                {
                    "instruction": "continuity data",
                    "task_summary": "look up the weather",
                    "task_intent": "weather lookup",
                    "status": "cancelled",
                    "cancellation_reason": "superseded_by_new_user_input",
                    "resume_recommended": True,
                },
                "conversation",
            ),
            "memory.topic_state": _slot(
                "memory.topic_state", {"topics": ["topic"]}, "memory"
            ),
            "memory.short_term": _slot(
                "memory.short_term", {"active_focus": "current task"}, "memory"
            ),
            "memory.persona_state": _slot(
                "memory.persona_state", {"mood": "calm"}, "memory"
            ),
            "knowledge.snippets": _slot(
                "knowledge.snippets", {"text": "docs"}, "rag"
            ),
            "capability.tools_schema": _slot(
                "capability.tools_schema", {"tools": []}, "tools"
            ),
            "capability.plugin_directory": _slot(
                "capability.plugin_directory",
                {
                    "plugins": [
                        {
                            "name": "Planner Plugin",
                            "description": "Planner-visible capability",
                            "targets": ["core_planner"],
                        },
                    ]
                },
                "capability",
            ),
            "interaction.route_decision": _slot(
                "interaction.route_decision", {"route_mode": "hybrid"}, "internal"
            ),
        }
    )


def _rendered_prompt_text(result) -> str:
    return "\n".join(
        [
            result.system_prompt or "",
            *[
                str(message.get("content", ""))
                for message in result.messages
            ],
        ]
    )


def test_persona_projection_keeps_history_and_hides_core_capabilities():
    projected = project_context_pack(_canonical_pack(), PromptTarget.PERSONA)

    assert projected.get_slot("persona.prompt") is not None
    assert projected.get_slot("conversation.history") is not None
    assert projected.get_slot("conversation.pending_execution_continuity") is None
    assert projected.get_slot("memory.persona_state") is not None
    assert projected.get_slot("capability.tools_schema") is None
    assert projected.get_slot("knowledge.snippets") is None
    assert projected.get_slot("system.core_execution_context") is None


def test_persona_projection_applies_target_local_history_window():
    source = _canonical_pack()

    projected = project_context_pack(
        source,
        PromptTarget.PERSONA,
        history_turns=2,
    )

    assert projected.get_slot("conversation.history").value["turns"] == [
        {"id": 3},
        {"id": 4},
    ]
    assert source.get_slot("conversation.history").value["turn_count"] == 5


@pytest.mark.parametrize("view", [PromptContextView.TURN_PLAN, PromptContextView.OLV_STREAM])
def test_direct_persona_views_use_recent_history_without_topic_summaries(view):
    from astrbot.core.prompt.context_views import project_prompt_context_view

    pack = _canonical_pack()
    projected = project_prompt_context_view(pack, view)

    assert projected.get_slot("conversation.history") is not None
    assert projected.get_slot("memory.topic_state") is None
    assert projected.get_slot("memory.short_term") is None
    assert projected.get_slot("memory.persona_state") is not None
    assert pack.get_slot("memory.topic_state") is not None
    assert pack.get_slot("memory.short_term") is not None


def test_persona_projection_drops_execution_capability_extensions():
    pack = ContextPack(
        slots={
            "extension.capability": _slot(
                "extension.capability",
                {
                    "items": [
                        {
                            "plugin_id": "shared-capability",
                            "value": "large execution contract",
                            "meta": {"targets": ["persona", "core"]},
                        }
                    ]
                },
                "extension",
            )
        }
    )

    persona = project_context_pack(pack, PromptTarget.PERSONA)
    core = project_context_pack(pack, PromptTarget.CORE)

    assert persona.get_slot("extension.capability") is None
    assert core.get_slot("extension.capability") is not None


def test_core_planner_projection_uses_facts_without_router_or_persona_decisions():
    projected = project_context_pack(_canonical_pack(), PromptTarget.CORE_PLANNER)

    assert projected.get_slot("input.text") is not None
    assert projected.get_slot("conversation.history") is not None
    assert projected.get_slot("memory.short_term") is not None
    assert projected.get_slot("capability.plugin_directory") is None
    assert projected.get_slot("persona.summary") is None
    assert projected.get_slot("conversation.pending_execution_continuity") is not None
    assert projected.get_slot("interaction.route_decision") is None
    assert projected.get_slot("system.core_execution_context") is None


def test_core_router_projection_is_bounded_and_excludes_persona_context():
    history = {
        "turns": [
            {
                "user_message": {"role": "user", "content": f"user-{index}-" + "x" * 900},
                "assistant_message": {"role": "assistant", "content": f"reply-{index}"},
            }
            for index in range(6)
        ]
    }
    pack = ContextPack(
        slots={
            "system.global": _slot("system.global", "global identity", "system"),
            "system.base": _slot("system.base", "base instructions", "system"),
            "persona.prompt": _slot("persona.prompt", "persona identity", "persona"),
            "memory.persona_state": _slot("memory.persona_state", {"name": "Alice"}, "memory"),
            "memory.short_term": _slot("memory.short_term", {"summary": "personal memory"}, "memory"),
            "input.text": _slot("input.text", "Continue that task", "input"),
            "input.quoted_text": _slot("input.quoted_text", "quoted request", "input"),
            "input.images": _slot("input.images", [{"ref": "image"}], "input"),
            "input.attachment_summary": _slot("input.attachment_summary", {"images": 1}, "input"),
            "input.visible_reply_material": _slot("input.visible_reply_material", {"text": "already sent"}, "input"),
            "session.datetime": _slot("session.datetime", {"text": "2026-10-23"}, "session"),
            "conversation.history": _slot("conversation.history", history, "conversation"),
            "conversation.group_recent": _slot("conversation.group_recent", {"records": ["ambient"]}, "conversation"),
            "conversation.pending_execution_continuity": ContextSlot(
                name="conversation.pending_execution_continuity",
                value={
                    "instruction": "do not expose this instruction",
                    "task_summary": "unfinished task",
                    "task_intent": "research",
                    "status": "cancelled",
                    "resume_recommended": True,
                    "cancellation_reason": "private diagnostic",
                },
                category="conversation",
                source="test",
                meta={"targets": ["core_router", "core_planner"]},
            ),
            "capability.core_execution": ContextSlot(
                name="capability.core_execution",
                value={"executor_policy": "fixed_by_profile"},
                category="capability",
                source="test",
                meta={"targets": ["core_router"]},
            ),
            "capability.tools_schema": ContextSlot(
                name="capability.tools_schema",
                value={"tools": [{"name": "shell", "description": "run commands"}]},
                category="capability",
                source="test",
                meta={"targets": ["core_router"]},
            ),
            "capability.plugin_directory": ContextSlot(
                name="capability.plugin_directory",
                value={"plugins": [{"name": "internal plugin"}]},
                category="capability",
                source="test",
                meta={"targets": ["core_router"]},
            ),
        }
    )

    projected = project_context_pack(pack, PromptTarget.CORE_ROUTER)

    assert set(projected.slots) == {
        "input.text",
        "input.quoted_text",
        "input.attachment_summary",
        "session.datetime",
        "conversation.history",
        "conversation.pending_execution_continuity",
    }
    assert projected.get_slot("capability.core_execution") is None
    assert projected.get_slot("capability.tools_schema") is None
    history_turns = projected.get_slot("conversation.history").value["turns"]
    assert len(history_turns) == 3
    assert all(len(turn["user_message"]["content"]) <= 600 for turn in history_turns)
    assert history_turns[-1]["user_message"]["content"].startswith("user-5-")
    assert projected.get_slot("conversation.pending_execution_continuity").value == {
        "task_summary": "unfinished task",
        "task_intent": "research",
        "status": "cancelled",
        "resume_recommended": True,
    }
    assert len(pack.get_slot("conversation.history").value["turns"]) == 6
    assert "global identity" not in _rendered_prompt_text(
        PromptRenderEngine().render(
            pack,
            target=PromptTarget.CORE_ROUTER,
            profile=PromptRenderProfile(
                name="router_isolation",
                system_prompt="isolated router instructions",
            ),
        )
    )


def test_plugin_directory_entries_remain_hidden_from_core_planner():
    pack = ContextPack(
        slots={
            "capability.plugin_directory": ContextSlot(
                name="capability.plugin_directory",
                value={
                    "plugins": [
                        {
                            "name": "Direct Plugin",
                            "description": "Direct capability",
                        }
                    ]
                },
                category="capability",
                source="plugin",
                meta={"targets": ["core_planner"]},
            )
        }
    )

    planner = project_context_pack(pack, PromptTarget.CORE_PLANNER)

    assert planner.get_slot("capability.plugin_directory") is None


def test_direct_slot_targets_are_enforced_before_target_rules():
    pack = ContextPack(
        slots={
            "conversation.group_recent": ContextSlot(
                name="conversation.group_recent",
                value={"records": ["ambient"]},
                category="conversation",
                source="plugin",
                meta={"targets": ["core"]},
            )
        }
    )

    assert (
        project_context_pack(pack, PromptTarget.CORE_PLANNER).get_slot(
            "conversation.group_recent"
        )
        is None
    )
    assert (
        project_context_pack(pack, PromptTarget.CORE).get_slot(
            "conversation.group_recent"
        )
        is not None
    )


def test_targetless_render_defaults_to_core_projection():
    pack = ContextPack(
        slots={
            "system.base": _slot("system.base", "Core instructions", "system"),
            "input.text": ContextSlot(
                name="input.text",
                value="Persona-only input",
                category="input",
                source="test",
                meta={"targets": ["persona"]},
            ),
        }
    )

    result = PromptRenderEngine().render(pack)

    assert result.metadata["prompt_target"] == PromptTarget.CORE.value
    assert "input.text" not in result.metadata["selected_slot_names"]
    assert "Persona-only input" not in str(result.messages)


def test_persona_progress_view_keeps_only_phase_local_persona_facts():
    pack = _canonical_pack()
    pack.add_slot(_persona_identity_extension_slot())
    result = PromptRenderEngine().render(
        pack,
        target=PromptTarget.PERSONA,
        context_view=PromptContextView.PROGRESS,
    )

    assert result.metadata["context_view"] == "progress"
    assert result.metadata["context_view_source_requirement"] == "base_only"
    assert set(result.metadata["selected_slot_names"]) == {
        "system.global",
        "extension.system",
        "persona.summary",
        "input.visible_reply_material",
        "input.previous_persona_acknowledgement",
    }
    assert "AG99live Companion Identity" in _rendered_prompt_text(result)
    assert "conversation.history" not in result.metadata["selected_slot_names"]
    assert "persona.prompt" not in result.metadata["selected_slot_names"]


@pytest.mark.parametrize("renderer", [
    BasePromptRenderer, OpenAIPromptRenderer, AnthropicPromptRenderer,
    MiniMaxPromptRenderer,
])
def test_progress_acknowledgement_reaches_final_request_once(renderer):
    import json
    from copy import deepcopy

    from astrbot.core.provider.entities import ProviderRequest

    pack = ContextPack(slots={
        "input.visible_reply_material": _slot(
            "input.visible_reply_material", {"progress_context": "工具仍在执行"}, "input"
        ),
        "input.previous_persona_acknowledgement": _slot(
            "input.previous_persona_acknowledgement", {"text": "已经确认 marker_ack"}, "input"
        ),
    })
    original = deepcopy(pack)
    engine = PromptRenderEngine(default_renderer=renderer())
    rendered = engine.render(
        pack, target=PromptTarget.PERSONA, context_view=PromptContextView.PROGRESS,
        profile=PromptRenderProfile(name="progress", request_prompt="报告进度"),
    )
    request = ProviderRequest()
    apply_render_result_to_request(rendered, request)
    assert json.dumps(request.contexts, ensure_ascii=False).count("marker_ack") == 1
    assert "marker_ack" not in request.system_prompt
    assert pack == original

    # An empty acknowledgement must not create an extra data block/message.
    pack.get_slot("input.previous_persona_acknowledgement").value = {"text": " "}
    empty = engine.render(
        pack, target=PromptTarget.PERSONA, context_view=PromptContextView.PROGRESS
    )
    pack.slots.pop("input.previous_persona_acknowledgement")
    absent = engine.render(
        pack, target=PromptTarget.PERSONA, context_view=PromptContextView.PROGRESS
    )
    assert empty.messages == absent.messages


@pytest.mark.parametrize("view", [
    PromptContextView.TURN_PLAN, PromptContextView.OLV_STREAM,
    PromptContextView.FINAL_RESULT,
])
@pytest.mark.parametrize("window", [0, 1, 50, 300])
def test_direct_persona_views_preserve_configured_history_candidate_window(view, window):
    import json
    from copy import deepcopy

    from astrbot.core.provider.entities import ProviderRequest

    pack = ContextPack(slots={
        "input.text": _slot("input.text", "继续", "input"),
        "conversation.history": _slot("conversation.history", {"turns": [
            {"user_message": {"role": "user", "content": f"marker_history_{i}"},
             "assistant_message": {"role": "assistant", "content": "好"}}
            for i in range(12)
        ]}, "conversation"),
    })
    original = deepcopy(pack)
    rendered = PromptRenderEngine().render(
        pack, target=PromptTarget.PERSONA, context_view=view,
        profile=PromptRenderProfile(
            name="configured_persona", history_turns=window, request_prompt="回复"
        ),
    )
    request = ProviderRequest()
    apply_render_result_to_request(rendered, request)
    wire = json.dumps(request.contexts, ensure_ascii=False)
    expected = min(window, 12)
    assert wire.count("marker_history_") == expected
    if expected:
        assert "marker_history_11" in wire
    budget = rendered.metadata["context_budgets"]["conversation_history"]
    assert budget["limit_amount"] == window
    assert budget["retained_amount"] == expected
    assert budget["limit_estimated_tokens"] == (
        1800 if view is PromptContextView.OLV_STREAM else 3000
    )
    assert pack == original


def test_persona_turn_plan_view_bounds_history_and_keeps_persona_extension():
    pack = _canonical_pack()
    pack.add_slot(_persona_identity_extension_slot())

    result = PromptRenderEngine().render(
        pack,
        target=PromptTarget.PERSONA,
        context_view=PromptContextView.TURN_PLAN,
    )

    selected = set(result.metadata["selected_slot_names"])
    history_budget = result.metadata["context_budgets"]["conversation_history"]

    assert result.metadata["context_view"] == "turn_plan"
    assert result.metadata["context_view_source_requirement"] == "base_only"
    assert "conversation.pending_execution_continuity" not in selected
    assert "extension.system" in selected
    assert "AG99live Companion Identity" in _rendered_prompt_text(result)
    assert history_budget["limit_amount"] == 300
    assert history_budget["limit_estimated_tokens"] == 3000
    continuity_messages = [
        message
        for message in result.messages
        if "look up the weather" in str(message.get("content", ""))
    ]
    assert continuity_messages == []
    assert result.messages[-1]["role"] == "user"
    assert "current" in str(result.messages[-1]["content"])


def test_minimax_turn_plan_does_not_receive_core_execution_continuity():
    result = PromptRenderEngine(
        default_renderer=MiniMaxPromptRenderer()
    ).render(
        _canonical_pack(),
        target=PromptTarget.PERSONA,
        context_view=PromptContextView.TURN_PLAN,
    )

    continuity_messages = [
        message
        for message in result.messages
        if "look up the weather" in str(message.get("content", ""))
    ]
    assert continuity_messages == []
    assert result.messages[-1]["role"] == "user"
    assert "current" in str(result.messages[-1]["content"])


def test_persona_proactive_view_keeps_persona_system_extensions():
    pack = _canonical_pack()
    pack.add_slot(_persona_identity_extension_slot())
    result = PromptRenderEngine().render(
        pack,
        target=PromptTarget.PERSONA,
        context_view=PromptContextView.PROACTIVE,
    )

    selected = set(result.metadata["selected_slot_names"])
    assert result.metadata["context_view"] == "proactive"
    assert "persona.summary" in selected
    assert "conversation.history" in selected
    assert "memory.short_term" in selected
    assert "extension.system" in selected
    assert "AG99live Companion Identity" in _rendered_prompt_text(result)
    assert result.metadata["context_budgets"]["conversation_history"]["limit_amount"] == 2
    assert (
        result.metadata["context_budgets"]["conversation_history"]
        ["limit_estimated_tokens"]
        == 1200
    )


def test_persona_proactive_view_enforces_its_history_token_budget():
    pack = _canonical_pack()
    pack.get_slot("conversation.history").value = {
        "turn_count": 3,
        "turns": [
            {
                "id": index,
                "user_message": {"content": "x" * 2200},
                "assistant_message": {"content": "y" * 2200},
            }
            for index in range(3)
        ],
    }

    result = PromptRenderEngine().render(
        pack,
        target=PromptTarget.PERSONA,
        context_view=PromptContextView.PROACTIVE,
    )
    history_budget = result.metadata["context_budgets"]["conversation_history"]

    assert history_budget["retained_amount"] < 3
    assert history_budget["retained_estimated_tokens"] <= 1200
    assert "context_view_history_limit" in history_budget["truncation_reasons"]
    assert "persona_recent_token_budget" in history_budget["truncation_reasons"]


def test_plugin_prompt_extensions_do_not_reach_core_planner():
    pack = ContextPack(
        slots={
            "extension.system": ContextSlot(
                name="extension.system",
                value={
                    "items": [
                        {
                            "value": "route rule",
                            "meta": {
                                "targets": [
                                    "core_planner",
                                    "persona",
                                    "core",
                                ]
                            },
                        }
                    ]
                },
                category="extension",
                source="plugin",
                meta={
                    "targets": [
                        "core_planner",
                        "persona",
                        "core",
                    ]
                },
            )
        }
    )

    assert project_context_pack(pack, PromptTarget.CORE_PLANNER).get_slot("extension.system") is None
    assert project_context_pack(pack, PromptTarget.PERSONA).get_slot("extension.system") is not None
    assert project_context_pack(pack, PromptTarget.CORE).get_slot("extension.system") is not None


def test_render_profile_replaces_local_base_without_dropping_global_instructions():
    pack = ContextPack(
        slots={
            "system.global": _slot(
                "system.global",
                "Stable global instructions.",
                "system",
            ),
            "system.base": _slot(
                "system.base",
                "Stale target instructions.",
                "system",
            )
        }
    )

    result = PromptRenderEngine().render(
        pack,
        target=PromptTarget.CORE_PLANNER,
        profile=PromptRenderProfile(
            name="planner_boundary",
            system_prompt="Planner instruction.",
        ),
    )

    assert "Planner instruction." in result.system_prompt
    assert "Stable global instructions." in result.system_prompt
    assert "Stale target instructions." not in result.system_prompt

    persona_result = PromptRenderEngine().render(
        pack,
        target=PromptTarget.PERSONA,
        profile=PromptRenderProfile(
            name="persona_compatibility",
            system_prompt="Persona instruction.",
        ),
    )

    assert "Persona instruction." in persona_result.system_prompt
    assert "Stable global instructions." in persona_result.system_prompt
    assert "Stale target instructions." not in persona_result.system_prompt


def test_direct_slot_with_malformed_targets_is_hidden():
    pack = ContextPack(
        slots={
            "input.text": ContextSlot(
                name="input.text",
                value="private",
                category="input",
                source="plugin",
                meta={"targets": "router"},
            )
        }
    )

    for target in PromptTarget:
        assert project_context_pack(pack, target).get_slot("input.text") is None


def test_planner_view_removes_runtime_diagnostics_without_mutating_source():
    source = _canonical_pack()
    history = source.get_slot("conversation.history")
    history.value["turns"][-1] = {
        "user_message": {"role": "user", "content": "请继续"},
        "assistant_message": {
            "role": "assistant",
            "content": "Traceback (most recent call last): failed",
            "reasoning_content": "private",
            "tool_calls": [{"name": "internal"}],
        },
    }
    group_recent = source.get_slot("conversation.group_recent")
    group_recent.value = {
        "records": [
            "user_id=1: hello",
            "bot: 获取图片描述失败: invalid image input",
        ],
        "text": "raw diagnostics",
    }

    planner = project_context_pack(source, PromptTarget.CORE_PLANNER)

    assistant = planner.get_slot("conversation.history").value["turns"][-1][
        "assistant_message"
    ]
    assert assistant["content"] == "[runtime diagnostic omitted]"
    assert "reasoning_content" not in assistant
    assert "tool_calls" not in assistant
    assert planner.get_slot("conversation.group_recent").value["records"][-1] == {
        "content": "[runtime diagnostic omitted]"
    }
    assert "Traceback" in history.value["turns"][-1]["assistant_message"]["content"]


def test_core_projection_keeps_execution_context_without_persona_material():
    projected = project_context_pack(_canonical_pack(), PromptTarget.CORE)

    assert projected.get_slot("conversation.history") is not None
    assert projected.get_slot("conversation.group_recent") is not None
    assert projected.get_slot("knowledge.snippets") is not None
    assert projected.get_slot("capability.tools_schema") is not None
    assert projected.get_slot("persona.prompt") is None
    assert projected.get_slot("persona.summary") is None
    assert projected.get_slot("memory.persona_state") is None
    assert projected.get_slot("input.visible_reply_material") is None
    assert projected.get_slot("system.core_execution_context") is not None


def test_target_budgets_bound_history_and_execution_without_mutating_facts():
    turns = [
        {
            "user_message": {"role": "user", "content": f"user-{index}"},
            "assistant_message": {
                "role": "assistant",
                "content": f"assistant-{index}",
            },
        }
        for index in range(80)
    ]
    pack = ContextPack(
        slots={
            "conversation.history": _slot(
                "conversation.history",
                {"turn_count": len(turns), "turns": turns},
                "memory",
            ),
            "conversation.core_execution_history": ContextSlot(
                name="conversation.core_execution_history",
                value={
                    "record_count": 6,
                    "records": [{"execution_id": index} for index in range(6)],
                },
                category="conversation",
                source="test",
                meta={"targets": ["core"]},
            ),
            "capability.tools_schema": _slot(
                "capability.tools_schema",
                {"tool_count": 2, "tools": [{"name": "a"}, {"name": "b"}]},
                "tools",
            ),
        }
    )

    planner = project_context_pack(pack, PromptTarget.CORE_PLANNER)
    persona = project_context_pack(pack, PromptTarget.PERSONA)
    core = project_context_pack(
        pack,
        PromptTarget.CORE,
        config=SimpleNamespace(max_context_length=-1),
    )
    configured_core = project_context_pack(
        pack,
        PromptTarget.CORE,
        config=SimpleNamespace(max_context_length=12),
    )
    compatibility_render = PromptRenderEngine().render(
        pack,
        config=SimpleNamespace(max_context_length=-1),
    )

    assert len(planner.get_slot("conversation.history").value["turns"]) == 8
    assert len(persona.get_slot("conversation.history").value["turns"]) == 28
    assert len(core.get_slot("conversation.history").value["turns"]) == 64
    assert len(
        configured_core.get_slot("conversation.history").value["turns"]
    ) == 12
    assert len(
        core.get_slot("conversation.core_execution_history").value["records"]
    ) == 4
    assert len(pack.get_slot("conversation.history").value["turns"]) == 80
    assert (
        core.meta["context_budgets"]["conversation_history"]["truncation_reasons"]
        == ["core_history_hard_fallback"]
    )
    assert configured_core.meta["context_budgets"]["conversation_history"][
        "truncation_reasons"
    ] == ["configured_core_history_limit"]
    assert core.meta["context_budgets"]["conversation_history"][
        "original_message_count"
    ] == 160
    assert core.meta["context_budgets"]["conversation_history"][
        "retained_message_count"
    ] == 128
    assert core.meta["context_budgets"]["tool_schema"]["enforced"] is False
    assert compatibility_render.metadata["context_budgets"][
        "conversation_history"
    ]["retained_amount"] == 64


def test_persona_history_keeps_relevant_old_anchor_after_recent_compaction():
    turns = []
    for index in range(60):
        topic = "星图计划" if index == 4 else "日常闲聊"
        turns.append(
            {
                "user_message": {
                    "role": "user",
                    "content": topic + "甲" * 900,
                },
                "assistant_message": {
                    "role": "assistant",
                    "content": topic + "乙" * 900,
                },
            }
        )
    pack = ContextPack(
        slots={
            "input.text": _slot("input.text", "请继续星图计划", "input"),
            "conversation.history": _slot(
                "conversation.history",
                {"turn_count": len(turns), "turns": turns},
                "memory",
            ),
        }
    )

    persona = project_context_pack(
        pack,
        PromptTarget.PERSONA,
        history_turns=300,
    )

    history = persona.get_slot("conversation.history")
    retained_turns = history.value["turns"]
    projection = history.meta["persona_history_projection"]

    assert projection["candidate_turn_count"] == 60
    assert projection["recent_turn_count"] < 28
    assert projection["anchor_turn_count"] >= 1
    assert any(
        turn["user_message"]["content"].startswith("星图计划")
        for turn in retained_turns
    )
    assert len(pack.get_slot("conversation.history").value["turns"]) == 60


def test_group_context_records_remain_structured_in_all_rendered_targets():
    pack = _canonical_pack()

    for target in (PromptTarget.PERSONA, PromptTarget.CORE):
        result = PromptRenderEngine().render(pack, target=target)

        rendered = "\n".join(
            str(message.get("content", "")) for message in result.messages
        )
        assert "ambient" in rendered
        assert "Alice" in rendered


def test_extension_targets_are_filtered_for_extension_enabled_prompt_targets():
    pack = ContextPack(
        slots={
            "extension.context": _slot(
                "extension.context",
                {
                    "items": [
                        {
                            "plugin_id": "core_planner",
                            "meta": {"targets": ["core_planner"]},
                        },
                        {"plugin_id": "persona", "meta": {"targets": ["persona"]}},
                        {"plugin_id": "core", "meta": {"targets": ["core"]}},
                    ]
                },
                "extension",
            )
        }
    )

    assert project_context_pack(pack, PromptTarget.CORE_PLANNER).get_slot(
        "extension.context"
    ) is None

    for target in (PromptTarget.PERSONA, PromptTarget.CORE):
        projected = project_context_pack(pack, target)
        items = projected.get_slot("extension.context").value["items"]
        assert [item["plugin_id"] for item in items] == [target.value]

    policy = project_context_pack(pack, PromptTarget.PERSONAL_POLICY)
    assert policy.get_slot("extension.context") is None
