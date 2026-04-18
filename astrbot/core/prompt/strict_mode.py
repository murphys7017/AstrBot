"""Shared helpers for prompt-pipeline strict mode."""

from __future__ import annotations

from collections.abc import Callable


def is_prompt_pipeline_strict(config: object | None = None) -> bool:
    """Return whether prompt-pipeline strict mode is enabled."""
    return bool(getattr(config, "prompt_pipeline_strict_mode", False))


def handle_prompt_pipeline_failure(
    *,
    strict: bool,
    message: str,
    exc: Exception | None = None,
    error_cls: type[Exception] = RuntimeError,
    log_failure: Callable[[], None] | None = None,
) -> None:
    """Raise in strict mode, otherwise execute the provided logging callback."""
    if strict:
        raise error_cls(message) from exc

    if log_failure is not None:
        log_failure()


__all__ = [
    "handle_prompt_pipeline_failure",
    "is_prompt_pipeline_strict",
]
