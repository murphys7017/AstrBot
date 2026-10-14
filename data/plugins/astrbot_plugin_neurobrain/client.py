"""Read-only in-process NeuroBrain API exposed to other AstrBot plugins."""

from __future__ import annotations

from typing import Any


class NeuroBrainReadOnlyAPI:
    """Expose current snapshots without exposing state-update operations."""

    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin

    def get_state(self, state_key: str | None = None) -> dict[str, Any] | None:
        """Return a detached latest snapshot without advancing NeuroBrain."""

        return self._plugin._get_state(state_key)

    def list_states(self) -> list[dict[str, Any]]:
        """Return detached latest snapshots without advancing NeuroBrain."""

        return self._plugin._list_states()

    def is_ready(self) -> bool:
        """Return whether the configured checkpoint is loaded."""

        return self._plugin.is_ready

    async def fetch_state(self, state_key: str) -> dict[str, Any] | None:
        """Compatibility alias for an immediate in-process state read."""

        return self.get_state(state_key)

    async def wait_for_persona_result(
        self,
        persona_result_id: str,
        *,
        timeout_seconds: float = 1.0,
    ) -> dict[str, Any] | None:
        """Wait for the state update associated with one Persona result."""

        return await self._plugin._wait_for_persona_result(
            persona_result_id,
            timeout_seconds=timeout_seconds,
        )
