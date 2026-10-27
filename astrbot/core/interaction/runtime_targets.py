from __future__ import annotations

from collections.abc import Mapping


def configured_runtime_observation_target_values(
    config: Mapping[str, object],
) -> tuple[str, ...]:
    """Return explicitly configured Personal Runtime session targets."""
    platform_settings = config.get("platform_settings", {})
    if not isinstance(platform_settings, Mapping):
        return ()

    configured_targets = platform_settings.get(
        "personal_runtime_observation_targets"
    )
    values = configured_targets if isinstance(configured_targets, list) else ()

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)
__all__ = [
    "configured_runtime_observation_target_values",
]
