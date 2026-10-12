"""Content-free diagnostics for request preparation and provider controls."""

from collections.abc import Mapping
from contextlib import contextmanager
from time import perf_counter

from astrbot import logger


@contextmanager
def measure_runtime_stage(event, stage: str, **fields):
    started = perf_counter()
    status = "completed"
    error_type = None
    try:
        yield
    except BaseException as exc:
        status = "failed"
        error_type = type(exc).__name__
        raise
    finally:
        get_extra = getattr(event, "get_extra", None)
        turn_id = get_extra("_turn_id") if callable(get_extra) else None
        logger.debug(
            "DIAG request.prepare: turn_id=%s stage=%s duration_ms=%.3f "
            "status=%s error_type=%s fields=%s",
            turn_id,
            stage,
            (perf_counter() - started) * 1000,
            status,
            error_type,
            fields,
        )


def log_provider_controls(provider, payloads: dict, extra_body: dict, *, stream: bool):
    # SDK extra_body fields take precedence over the generated request body.
    effective = {**payloads, **extra_body}
    thinking = effective.get("thinking")
    output_config = effective.get("output_config")

    def scalar(value):
        return value if isinstance(value, (str, int, float, bool)) else None

    logger.debug(
        "DIAG provider.controls: provider_id=%s model=%s stream=%s "
        "thinking_type=%s budget_tokens=%s effort=%s max_tokens=%s",
        provider.provider_config.get("id"),
        scalar(effective.get("model")),
        stream,
        scalar(thinking.get("type"))
        if isinstance(thinking, Mapping)
        else "provider_default",
        scalar(thinking.get("budget_tokens"))
        if isinstance(thinking, Mapping)
        else None,
        scalar(output_config.get("effort"))
        if isinstance(output_config, Mapping)
        else scalar(effective.get("reasoning_effort")),
        scalar(effective.get("max_tokens")),
    )
