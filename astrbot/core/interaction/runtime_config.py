from collections.abc import Mapping
from typing import Any


def merge_runtime_config(base: Any, override: Any) -> Any:
    if not isinstance(base, Mapping):
        return override if isinstance(override, Mapping) else base
    if not isinstance(override, Mapping):
        return dict(base)

    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = merge_runtime_config(merged[key], value)
        else:
            merged[key] = value
    return merged
