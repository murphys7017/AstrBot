"""Tests for prompt tree building and base renderer routing."""

from astrbot.core.prompt.context_types import ContextPack, ContextSlot
from astrbot.core.prompt.render import (
    BasePromptRenderer,
    PromptBuilder,
    PromptRenderEngine,
    SerializedRenderValue,
)


def test_prompt_builder_builds_nested_tag_tree():
    builder = PromptBuilder("prompt")
    builder.tag("persona").add("You are Alice.")
    policy_ref = builder.tag("policy")
    policy_ref.tag("safety").add("Be safe.")

    rendered = builder.build()

    assert "<prompt>" in rendered
    assert "<persona>" in rendered
    assert "You are Alice." in rendered
    assert "<policy>" in rendered
    assert "<safety>" in rendered
    assert "Be safe." in rendered
    assert "</prompt>" in rendered


def test_prompt_builder_include_and_extend_work():
    prompt = PromptBuilder("prompt")
    persona = PromptBuilder("persona")
    persona.add("Alice")
    prompt.include(persona)

    policy = PromptBuilder("policy")
    policy.add("Safe mode.")
    prompt.extend(policy)

    rendered = prompt.build()

    assert "<prompt>" in rendered
    assert "<persona>" in rendered
    assert "Alice" in rendered
    assert "<policy>" in rendered
    assert "Safe mode." in rendered


def test_base_prompt_renderer_enables_all_slot_groups():
    renderer = BasePromptRenderer()

    assert renderer.get_enabled_slot_groups() == (
        "system",
        "persona",
        "policy",
        "input",
        "session",
        "conversation",
        "knowledge",
        "capability",
        "memory",
    )


def test_base_prompt_renderer_returns_nested_node_structure():
    renderer = BasePromptRenderer()
    structure = renderer.get_node_structure()

    assert structure["system"] == "system/core"
    assert structure["persona"] == "system/persona"
    assert structure["policy"] == "system/policy"
    assert structure["session"] == "system/session"
    assert structure["conversation"] == "history/conversation"
    assert structure["knowledge"] == "system/knowledge"
    assert structure["capability"] == "system/capability"
    assert structure["memory"] == "system/memory"


def test_base_prompt_renderer_serializes_dict_slot_to_structured_object():
    renderer = BasePromptRenderer()
    slot = ContextSlot(
        name="session.user_info",
        value={"user_id": "u1", "nickname": "Alice"},
        category="session",
        source="test",
    )

    serialized = renderer.serialize_slot_value(slot, group="session")

    assert isinstance(serialized, SerializedRenderValue)
    assert serialized.kind == "mapping"
    assert serialized.tag == "user_info"
    assert serialized.value == {"user_id": "u1", "nickname": "Alice"}


def test_base_prompt_renderer_serializes_list_slot_to_structured_object():
    renderer = BasePromptRenderer()
    slot = ContextSlot(
        name="input.files",
        value=[{"name": "a.txt"}, {"name": "b.txt"}],
        category="input",
        source="test",
    )

    serialized = renderer.serialize_slot_value(slot, group="input")

    assert isinstance(serialized, SerializedRenderValue)
    assert serialized.kind == "sequence"
    assert serialized.tag == "files"
    assert serialized.value == [{"name": "a.txt"}, {"name": "b.txt"}]


def test_render_engine_builds_prompt_tree_from_nested_slots():
    pack = ContextPack(
        slots={
            "system.base": ContextSlot(
                name="system.base",
                value="Base system prompt.",
                category="system",
                source="test",
            ),
            "persona.prompt": ContextSlot(
                name="persona.prompt",
                value="You are Alice.",
                category="persona",
                source="test",
            ),
            "policy.safety_prompt": ContextSlot(
                name="policy.safety_prompt",
                value="Safety prompt.",
                category="system",
                source="test",
            ),
            "knowledge.snippets": ContextSlot(
                name="knowledge.snippets",
                value={
                    "format": "kb_text_block_v1",
                    "query": "test",
                    "text": "Knowledge result.",
                },
                category="memory",
                source="test",
            ),
        }
    )

    engine = PromptRenderEngine(default_renderer=BasePromptRenderer())
    result = engine.render(pack)
    rendered = result.system_prompt

    assert result.prompt_tree is not None
    assert "<system>" in rendered
    assert "<core>" in rendered
    assert "<base>" in rendered
    assert "Base system prompt." in rendered
    assert "<persona>" in rendered
    assert "You are Alice." in rendered
    assert "<policy>" in rendered
    assert "<safety>" in rendered
    assert "Safety prompt." in rendered
    assert "<knowledge>" in rendered
    assert "<snippets>" in rendered
    assert "Knowledge result." in rendered
    assert "<tools>" not in rendered
    assert result.messages == []
    assert result.tool_schema is None


def test_render_engine_prunes_empty_persona_segment_nodes():
    pack = ContextPack(
        slots={
            "persona.segments": ContextSlot(
                name="persona.segments",
                value={
                    "identity": {},
                    "core_persona": [],
                    "unparsed_sections": ["You are Alice."],
                },
                category="persona",
                source="test",
            )
        }
    )

    engine = PromptRenderEngine(default_renderer=BasePromptRenderer())
    result = engine.render(pack)

    assert result.system_prompt is not None
    assert "<persona>" in result.system_prompt
    assert "<identity>" not in result.system_prompt
    assert "<core_persona>" not in result.system_prompt
    assert "<unparsed_sections>" in result.system_prompt
    assert "You are Alice." in result.system_prompt


def test_render_engine_routes_cross_target_slots():
    pack = ContextPack(
        slots={
            "persona.prompt": ContextSlot(
                name="persona.prompt",
                value="You are Alice.",
                category="persona",
                source="test",
            ),
            "persona.begin_dialogs": ContextSlot(
                name="persona.begin_dialogs",
                value=[
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi"},
                ],
                category="persona",
                source="test",
            ),
            "capability.subagent_router_prompt": ContextSlot(
                name="capability.subagent_router_prompt",
                value="Route carefully.",
                category="tools",
                source="test",
            ),
            "capability.tools_schema": ContextSlot(
                name="capability.tools_schema",
                value={
                    "format": "tool_inventory_v1",
                    "tool_count": 1,
                    "tools": [
                        {
                            "name": "tool_a",
                            "description": "Run tool A",
                            "parameters": {"type": "object", "properties": {}},
                            "schema": {"type": "function"},
                            "active": True,
                            "handler_module_path": "mod.tool_a",
                        }
                    ],
                },
                category="tools",
                source="test",
            ),
        }
    )

    engine = PromptRenderEngine(default_renderer=BasePromptRenderer())
    result = engine.render(pack)

    assert "<history>" not in result.system_prompt
    assert "<tools>" not in result.system_prompt
    assert "Route carefully." in result.system_prompt
    assert result.messages == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]
    assert result.tool_schema == [
        {
            "type": "function",
            "function": {
                "name": "tool_a",
                "description": "Run tool A",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_render_engine_applies_persona_whitelists_to_capabilities():
    pack = ContextPack(
        slots={
            "persona.tools_whitelist": ContextSlot(
                name="persona.tools_whitelist",
                value=["tool_a"],
                category="persona",
                source="test",
            ),
            "persona.skills_whitelist": ContextSlot(
                name="persona.skills_whitelist",
                value=["skill_a"],
                category="persona",
                source="test",
            ),
            "capability.skills_prompt": ContextSlot(
                name="capability.skills_prompt",
                value={
                    "format": "skills_inventory_v1",
                    "runtime": "local",
                    "skill_count": 2,
                    "skills": [
                        {
                            "name": "skill_a",
                            "description": "Alpha skill",
                            "path": "/skills/a/SKILL.md",
                            "source_type": "local_only",
                            "source_label": "local",
                            "active": True,
                            "local_exists": True,
                            "sandbox_exists": False,
                        },
                        {
                            "name": "skill_b",
                            "description": "Beta skill",
                            "path": "/skills/b/SKILL.md",
                            "source_type": "local_only",
                            "source_label": "local",
                            "active": True,
                            "local_exists": True,
                            "sandbox_exists": False,
                        },
                    ],
                },
                category="tools",
                source="test",
            ),
            "capability.tools_schema": ContextSlot(
                name="capability.tools_schema",
                value={
                    "format": "tool_inventory_v1",
                    "tool_count": 2,
                    "tools": [
                        {
                            "name": "tool_a",
                            "description": "Tool A",
                            "parameters": {"type": "object", "properties": {}},
                            "schema": {"type": "function"},
                            "active": True,
                            "handler_module_path": "mod.tool_a",
                        },
                        {
                            "name": "tool_b",
                            "description": "Tool B",
                            "parameters": {"type": "object", "properties": {}},
                            "schema": {"type": "function"},
                            "active": True,
                            "handler_module_path": "mod.tool_b",
                        },
                    ],
                },
                category="tools",
                source="test",
            ),
        }
    )

    engine = PromptRenderEngine(default_renderer=BasePromptRenderer())
    result = engine.render(pack)

    assert "skill_a" in result.system_prompt
    assert "skill_b" not in result.system_prompt
    assert result.tool_schema == [
        {
            "type": "function",
            "function": {
                "name": "tool_a",
                "description": "Tool A",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_render_engine_compiles_user_input_and_merged_tool_schema():
    pack = ContextPack(
        slots={
            "input.text": ContextSlot(
                name="input.text",
                value="Look at this",
                category="input",
                source="test",
            ),
            "input.images": ContextSlot(
                name="input.images",
                value=[
                    {
                        "ref": "file:///tmp/demo.png",
                        "transport": "file",
                        "source": "current",
                    }
                ],
                category="input",
                source="test",
            ),
            "input.files": ContextSlot(
                name="input.files",
                value=[
                    {
                        "name": "spec.txt",
                        "file": "/tmp/spec.txt",
                        "url": "",
                        "source": "current",
                        "reply_id": None,
                    }
                ],
                category="input",
                source="test",
            ),
            "capability.tools_schema": ContextSlot(
                name="capability.tools_schema",
                value={
                    "format": "tool_inventory_v1",
                    "tool_count": 1,
                    "tools": [
                        {
                            "name": "tool_a",
                            "description": "Tool A",
                            "parameters": {"type": "object", "properties": {}},
                            "schema": {"type": "function"},
                            "active": True,
                            "handler_module_path": "mod.tool_a",
                        }
                    ],
                },
                category="tools",
                source="test",
            ),
            "capability.subagent_handoff_tools": ContextSlot(
                name="capability.subagent_handoff_tools",
                value={
                    "format": "handoff_tools_v1",
                    "main_enable": True,
                    "remove_main_duplicate_tools": False,
                    "tool_count": 1,
                    "tools": [
                        {
                            "name": "transfer_to_writer",
                            "description": "Delegate to writer",
                            "parameters": {"type": "object", "properties": {}},
                        }
                    ],
                },
                category="tools",
                source="test",
            ),
        }
    )

    engine = PromptRenderEngine(default_renderer=BasePromptRenderer())
    result = engine.render(pack)

    assert result.messages[-1]["role"] == "user"
    assert isinstance(result.messages[-1]["content"], list)
    assert result.messages[-1]["content"] == [
        {
            "type": "text",
            "text": "Look at this",
            "section": "input_text",
        },
        {
            "type": "image_url",
            "image_url": {"url": "file:///tmp/demo.png"},
            "section": "attachment_image",
            "transport": "file",
            "source": "current",
        },
        {
            "type": "file_ref",
            "file_ref": {"name": "spec.txt", "ref": "/tmp/spec.txt"},
            "section": "attachment_file",
            "source": "current",
            "file": "/tmp/spec.txt",
            "url": "",
        },
    ]
    assert result.tool_schema == [
        {
            "type": "function",
            "function": {
                "name": "tool_a",
                "description": "Tool A",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "transfer_to_writer",
                "description": "Delegate to writer",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


def test_render_engine_keeps_text_only_user_input_as_plain_string_message():
    pack = ContextPack(
        slots={
            "input.text": ContextSlot(
                name="input.text",
                value="Hello there",
                category="input",
                source="test",
            )
        }
    )

    engine = PromptRenderEngine(default_renderer=BasePromptRenderer())
    result = engine.render(pack)

    assert result.messages == [{"role": "user", "content": "Hello there"}]


def test_render_engine_returns_prompt_tree_and_system_prompt():
    pack = ContextPack(
        slots={
            "persona.prompt": ContextSlot(
                name="persona.prompt",
                value="You are Alice.",
                category="persona",
                source="test",
            )
        }
    )

    engine = PromptRenderEngine()
    result = engine.render(pack)

    assert result.prompt_tree is not None
    assert result.system_prompt is not None
    assert "<persona>" in result.system_prompt
    assert result.messages == []
    assert result.tool_schema is None
    assert result.metadata["renderer"] == "base"
    assert result.metadata["engine"] == "PromptRenderEngine"
    assert result.metadata["enabled_slot_groups"] == list(
        BasePromptRenderer.ALL_SLOT_GROUPS
    )
    assert result.metadata["rendered_slots"] == ["persona.prompt"]
    assert result.metadata["compiled_message_count"] == 0
    assert result.metadata["compiled_tool_count"] == 0


def test_render_engine_respects_renderer_disabled_groups():
    class NoKnowledgeRenderer(BasePromptRenderer):
        def get_enabled_slot_groups(self) -> tuple[str, ...]:
            return tuple(
                group for group in self.ALL_SLOT_GROUPS if group != "knowledge"
            )

    pack = ContextPack(
        slots={
            "knowledge.snippets": ContextSlot(
                name="knowledge.snippets",
                value={
                    "format": "kb_text_block_v1",
                    "query": "test",
                    "text": "Knowledge result.",
                },
                category="memory",
                source="test",
            )
        }
    )

    engine = PromptRenderEngine(default_renderer=NoKnowledgeRenderer())
    result = engine.render(pack)

    assert result.system_prompt is None
    assert result.messages == []
    assert result.tool_schema is None


def test_custom_renderer_can_override_group_renderer():
    class CompactSessionRenderer(BasePromptRenderer):
        def render_session_context(
            self,
            target,
            slots,
            *,
            pack,
            resolve_node,
            event=None,
            plugin_context=None,
            config=None,
            provider_request=None,
        ) -> list[str]:
            del (
                slots,
                pack,
                resolve_node,
                event,
                plugin_context,
                config,
                provider_request,
            )
            self._add_text_tag(target, "compact", "user=Alice")
            return ["session.user_info"]

    pack = ContextPack(
        slots={
            "session.user_info": ContextSlot(
                name="session.user_info",
                value={"user_id": "u1", "nickname": "Alice"},
                category="session",
                source="test",
            )
        }
    )

    engine = PromptRenderEngine(default_renderer=CompactSessionRenderer())
    result = engine.render(pack)

    assert "user=Alice" in result.system_prompt
    assert "<compact>" in result.system_prompt
    assert "<nickname>" not in result.system_prompt
