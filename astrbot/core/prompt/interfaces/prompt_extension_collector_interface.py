"""Interface for plugin-contributed prompt extension collectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context

from ..extensions.types import PromptExtension

if TYPE_CHECKING:
    from astrbot.core.astr_main_agent import MainAgentBuildConfig


class PromptExtensionCollectorInterface(ABC):
    """Base interface for plugin prompt extension collectors.

    Collectors may override the prompt-context hooks to avoid generating
    extension values that the active prompt view cannot consume. Renderers still
    enforce the view's slot allowlist after collection.
    """

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Return the stable plugin-owned identifier used in prompt output."""
        raise NotImplementedError

    @property
    def priority(self) -> int:
        """Return collection priority; lower values collect first."""
        return 100

    @property
    def lifecycle(self) -> str:
        """Return collector lifecycle.

        `static` collectors are cached per event after the first successful
        collection. `dynamic` collectors are evaluated on every prompt build.
        """
        return "dynamic"

    @abstractmethod
    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        provider_request: ProviderRequest | None = None,
    ) -> list[PromptExtension]:
        """Collect structured prompt extensions for the current request."""
        raise NotImplementedError

    async def collect_for_prompt_mounts(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        *,
        provider_request: ProviderRequest | None = None,
        allowed_mounts: frozenset[str],
    ) -> list[PromptExtension]:
        """Optionally skip work for mounts excluded by the active prompt view."""
        del allowed_mounts
        return await self.collect(
            event, plugin_context, config, provider_request=provider_request
        )

    async def collect_for_prompt_context(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        *,
        provider_request: ProviderRequest | None = None,
        allowed_mounts: frozenset[str] | None = None,
        allowed_targets: frozenset[str] | None = None,
    ) -> list[PromptExtension]:
        """Optionally specialize collection for the consuming prompt target."""
        del allowed_targets
        if allowed_mounts is None:
            return await self.collect(
                event, plugin_context, config, provider_request=provider_request
            )
        return await self.collect_for_prompt_mounts(
            event,
            plugin_context,
            config,
            provider_request=provider_request,
            allowed_mounts=allowed_mounts,
        )
