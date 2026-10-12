"""Content-free timing records for the canonical Prompt pipeline."""

from contextlib import contextmanager
from time import perf_counter

from astrbot import logger
from astrbot.core.utils.trace import record_prompt_trace


@contextmanager
def measure_prompt_stage(records: list[dict], stage: str, **fields):
    record = {"stage": stage, "status": "completed", **fields}
    started = perf_counter()
    try:
        yield record
    except BaseException as exc:
        record.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        record["duration_ms"] = round((perf_counter() - started) * 1000, 3)
        records.append(record)


def record_prompt_timings(event, scope: str, records: list[dict]) -> None:
    logger.debug("DIAG prompt.timings: scope=%s stages=%s", scope, records)
    try:
        record_prompt_trace(event, "prompt.timings", scope=scope, stages=records)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Prompt timing trace unavailable: error_type=%s", type(exc).__name__
        )
