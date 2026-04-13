"""Selector helpers for the prompt render pipeline."""

from __future__ import annotations

from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context

from ..context_types import ContextPack
from .interfaces import PromptSelectorInterface


class PassthroughPromptSelector(PromptSelectorInterface):
    """Return the collected context pack unchanged."""

    def select(
        self,
        pack: ContextPack,
        *,
        event: AstrMessageEvent | None = None,
        plugin_context: Context | None = None,
        config=None,
        provider_request: ProviderRequest | None = None,
    ) -> ContextPack:
        return pack


def select_context_pack(
    pack: ContextPack,
    *,
    selector: PromptSelectorInterface | None = None,
    event: AstrMessageEvent | None = None,
    plugin_context: Context | None = None,
    config=None,
    provider_request: ProviderRequest | None = None,
) -> ContextPack:
    """Run prompt selection with a default passthrough selector."""
    active_selector = selector or PassthroughPromptSelector()
    return active_selector.select(
        pack,
        event=event,
        plugin_context=plugin_context,
        config=config,
        provider_request=provider_request,
    )
