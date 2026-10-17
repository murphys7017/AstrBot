"""Read-only access for other AstrBot plugins."""

from __future__ import annotations

from typing import Any


class NeuroBrainReadOnlyAPI:
    """Expose only an immediate read of the single current state."""

    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin

    def get_state(self) -> dict[str, Any] | None:
        """Return a detached complete snapshot without waiting for inference."""
        return self._plugin.get_state()
