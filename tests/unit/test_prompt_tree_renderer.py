"""Tests for prompt tree building and default rendering."""

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


def test_base_prompt_renderer_returns_basic_node_structure():
    renderer = BasePromptRenderer()
    structure = renderer.get_node_structure()

    assert structure["system"] == "system"
    assert structure["persona"] == "persona"
    assert structure["policy"] == "policy"
    assert structure["conversation"] == "conversation"
    assert structure["capability"] == "capability"


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


def test_render_engine_builds_prompt_tree_from_basic_slots():
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
    assert "<prompt>" in rendered
    assert "<system>" in rendered
    assert "<base>" in rendered
    assert "Base system prompt." in rendered
    assert "<persona>" in rendered
    assert "<knowledge>" in rendered
    assert "You are Alice." in rendered
    assert "<policy>" in rendered
    assert "<safety_prompt>" in rendered
    assert "Safety prompt." in rendered
    assert "<snippets>" in rendered
    assert "Knowledge result." in rendered


def test_render_group_uses_renderer_serializer_instead_of_raw_str():
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

    engine = PromptRenderEngine(default_renderer=BasePromptRenderer())
    result = engine.render(pack)

    assert '"nickname": "Alice"' in result.system_prompt
    assert '"user_id": "u1"' in result.system_prompt
    assert "'nickname': 'Alice'" not in result.system_prompt


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
    assert result.metadata["renderer"] == "base"
    assert result.metadata["engine"] == "PromptRenderEngine"
    assert result.metadata["enabled_slot_groups"] == list(
        BasePromptRenderer.ALL_SLOT_GROUPS
    )
    assert result.metadata["rendered_slots"] == ["persona.prompt"]


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

    assert result.system_prompt is not None
    assert "<knowledge>" not in result.system_prompt
    assert "Knowledge result." not in result.system_prompt


def test_custom_renderer_can_override_slot_serializer():
    class CompactSessionRenderer(BasePromptRenderer):
        def serialize_slot_value(
            self,
            slot: ContextSlot,
            *,
            group: str,
        ) -> SerializedRenderValue | None:
            if slot.name == "session.user_info":
                return SerializedRenderValue(
                    slot_name=slot.name,
                    group=group,
                    tag="user_info",
                    kind="text",
                    value="user=Alice",
                )
            return super().serialize_slot_value(slot, group=group)

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
    assert '"nickname": "Alice"' not in result.system_prompt
