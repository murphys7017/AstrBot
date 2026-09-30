import json
import logging
import time
import uuid
from typing import Any

from astrbot import logger
from astrbot.core import LogManager, astrbot_config
from astrbot.core.log import LogQueueHandler

_cached_log_broker = None
_trace_logger = None


def _get_log_broker():
    global _cached_log_broker
    if _cached_log_broker is not None:
        return _cached_log_broker
    for handler in logger.handlers:
        if isinstance(handler, LogQueueHandler):
            _cached_log_broker = handler.log_broker
            return _cached_log_broker
    return None


def _get_trace_logger():
    global _trace_logger
    if _trace_logger is not None:
        return _trace_logger

    # 按配置初始化 trace 文件日志
    LogManager.configure_trace_logger(astrbot_config)
    _trace_logger = logging.getLogger("astrbot.trace")
    return _trace_logger


def prompt_trace_enabled() -> bool:
    """Return whether detailed prompt records should be persisted."""
    return bool(astrbot_config.get("trace_log_enable", False))


def record_prompt_trace(
    event: Any | None,
    action: str,
    **fields: Any,
) -> None:
    """Write detailed prompt diagnostics only to the trace file channel."""
    if not prompt_trace_enabled():
        return

    trace_logger = _get_trace_logger()
    trace = getattr(event, "trace", None) if event is not None else None
    get_extra = getattr(event, "get_extra", None) if event is not None else None
    turn_id = ""
    if callable(get_extra):
        try:
            turn_id = str(get_extra("_turn_id", "") or "")
        except Exception:
            turn_id = ""
    platform_id = None
    get_platform_id = (
        getattr(event, "get_platform_id", None) if event is not None else None
    )
    if callable(get_platform_id):
        try:
            platform_id = get_platform_id()
        except Exception:
            platform_id = None

    payload = {
        "type": "prompt_trace",
        "level": "TRACE",
        "time": time.time(),
        "span_id": getattr(trace, "span_id", None),
        "turn_id": turn_id,
        "platform_id": platform_id,
        "session_id": getattr(event, "session_id", None)
        if event is not None
        else None,
        "action": action,
        "fields": fields,
    }
    trace_logger.info(json.dumps(payload, ensure_ascii=False, default=str))


class TraceSpan:
    def __init__(
        self,
        name: str,
        umo: str | None = None,
        sender_name: str | None = None,
        message_outline: str | None = None,
    ) -> None:
        self.span_id = str(uuid.uuid4())
        self.name = name
        self.umo = umo
        self.sender_name = sender_name
        self.message_outline = message_outline
        self.started_at = time.time()

    def record(self, action: str, **fields: Any) -> None:
        # Check if trace recording is enabled
        if not astrbot_config.get("trace_enable", True):
            return

        payload = {
            "type": "trace",
            "level": "TRACE",
            "time": time.time(),
            "span_id": self.span_id,
            "name": self.name,
            "umo": self.umo,
            "sender_name": self.sender_name,
            "message_outline": self.message_outline,
            "action": action,
            "fields": fields,
        }
        log_broker = _get_log_broker()
        if log_broker:
            log_broker.publish(payload)

        trace_logger = _get_trace_logger()
        if trace_logger and trace_logger.handlers:
            trace_logger.info(json.dumps(payload, ensure_ascii=False))
