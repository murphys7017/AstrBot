"""Tests for prompt context data types."""

from astrbot.core.prompt.context_types import ContextPack, ContextSlot


def test_context_pack_helper_methods_filter_slots_by_category_and_exposure():
    allowed_slot = ContextSlot(
        name="persona.prompt",
        value="You are Alice.",
        category="persona",
        source="test",
    )
    hidden_slot = ContextSlot(
        name="memory.secret",
        value="internal",
        category="memory",
        source="test",
        llm_exposure="never",
    )
    second_persona_slot = ContextSlot(
        name="persona.segments",
        value={"identity": {"name": "Alice"}},
        category="persona",
        source="test",
    )

    pack = ContextPack()
    pack.add_slot(allowed_slot)
    pack.add_slot(hidden_slot)
    pack.add_slot(second_persona_slot)

    assert pack.has_slot("persona.prompt") is True
    assert pack.get_slot("persona.prompt") is allowed_slot
    assert pack.get_slot("missing.slot") is None
    assert pack.list_by_category("persona") == [allowed_slot, second_persona_slot]
    assert pack.list_llm_allowed() == [allowed_slot, second_persona_slot]
