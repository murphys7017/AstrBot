"""Tests for prompt selector placeholders."""

from astrbot.core.prompt.context_types import ContextPack, ContextSlot
from astrbot.core.prompt.render import (
    PassthroughPromptSelector,
    PromptSelectorInterface,
    select_context_pack,
)


class _CustomSelector(PromptSelectorInterface):
    def select(
        self,
        pack: ContextPack,
        *,
        event=None,
        plugin_context=None,
        config=None,
        provider_request=None,
    ) -> ContextPack:
        selected = ContextPack(
            slots=dict(pack.slots),
            provider_request_ref=pack.provider_request_ref,
            meta=dict(pack.meta),
        )
        selected.add_slot(
            ContextSlot(
                name="system.base",
                value="selected",
                category="system",
                source="test",
            )
        )
        return selected


def test_passthrough_prompt_selector_returns_original_pack():
    pack = ContextPack(
        slots={
            "input.text": ContextSlot(
                name="input.text",
                value="hello",
                category="input",
                source="test",
            )
        }
    )

    selected = PassthroughPromptSelector().select(pack)

    assert selected is pack


def test_select_context_pack_uses_passthrough_selector_by_default():
    pack = ContextPack(
        slots={
            "input.text": ContextSlot(
                name="input.text",
                value="hello",
                category="input",
                source="test",
            )
        }
    )

    selected = select_context_pack(pack)

    assert selected is pack


def test_select_context_pack_supports_custom_selector():
    pack = ContextPack(
        slots={
            "input.text": ContextSlot(
                name="input.text",
                value="hello",
                category="input",
                source="test",
            )
        }
    )

    selected = select_context_pack(pack, selector=_CustomSelector())

    assert selected is not pack
    assert selected.get_slot("input.text") is not None
    assert selected.get_slot("system.base") is not None
