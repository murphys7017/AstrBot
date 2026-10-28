"""日志系统，统一将标准 logging 输出转发到 loguru。"""

import asyncio
import copy
import logging
import os
import sys
import time
import traceback
from asyncio import Queue
from collections import deque
from typing import TYPE_CHECKING

from loguru import logger as _raw_loguru_logger

from astrbot.core.config.default import VERSION
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.error_redaction import sanitize_control_chars

CACHED_SIZE = 500
_SAFE_LOGURU_SINK_OPTIONS = {"backtrace": False, "diagnose": False}

if TYPE_CHECKING:
    from loguru import Record


class _RecordEnricherFilter(logging.Filter):
    """为 logging.LogRecord 注入 AstrBot 日志字段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.plugin_tag = "[Plug]" if _is_plugin_path(record.pathname) else "[Core]"
        record.short_levelname = _get_short_level_name(record.levelname)
        record.astrbot_version_tag = (
            f" [v{VERSION}]" if record.levelno >= logging.WARNING else ""
        )
        record.source_file = _build_source_file(record.pathname)
        record.source_line = record.lineno
        record.is_trace = record.name == "astrbot.trace"
        return True


class _QueueAnsiColorFilter(logging.Filter):
    """Attach ANSI color prefix for WebUI console rendering."""

    _LEVEL_COLOR = {
        "DEBUG": "\u001b[1;34m",
        "INFO": "\u001b[1;36m",
        "WARNING": "\u001b[1;33m",
        "ERROR": "\u001b[31m",
        "CRITICAL": "\u001b[1;31m",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        record.ansi_prefix = self._LEVEL_COLOR.get(record.levelname, "\u001b[0m")
        record.ansi_reset = "\u001b[0m"
        return True


def _is_plugin_path(pathname: str | None) -> bool:
    if not pathname:
        return False
    norm_path = os.path.normcase(os.path.normpath(pathname)).replace("\\", "/")
    return ("data/plugins/" in norm_path) or ("astrbot/builtin_stars/" in norm_path)


def _get_short_level_name(level_name: str) -> str:
    level_map = {
        "DEBUG": "DBUG",
        "INFO": "INFO",
        "WARNING": "WARN",
        "ERROR": "ERRO",
        "CRITICAL": "CRIT",
    }
    return level_map.get(level_name, level_name[:4].upper())


def _build_source_file(pathname: str | None) -> str:
    if not pathname:
        return "unknown"
    dirname = os.path.dirname(pathname)
    return (
        os.path.basename(dirname) + "." + os.path.basename(pathname).replace(".py", "")
    )


def _ensure_loguru_extra(record: "Record") -> None:
    extra = record["extra"]
    extra.setdefault("plugin_tag", "[Core]")
    extra.setdefault("short_levelname", _get_short_level_name(record["level"].name))
    level_no = record["level"].no
    extra.setdefault("astrbot_version_tag", f" [v{VERSION}]" if level_no >= 30 else "")
    extra.setdefault("source_file", _build_source_file(record["file"].path))
    extra.setdefault("source_line", record["line"])
    extra.setdefault("is_trace", False)


def _format_safe_exception(exception) -> str:
    if exception is None:
        return ""
    try:
        if isinstance(exception, tuple):
            exc_type, exc_value, exc_traceback = exception
        else:
            exc_type = exception.type
            exc_value = exception.value
            exc_traceback = exception.traceback
        formatted = traceback.TracebackException(
            exc_type,
            exc_value,
            exc_traceback,
        )
        _sanitize_traceback_exception(formatted)
        text = "".join(formatted.format())
    except Exception:
        exc_type = (
            exception[0]
            if isinstance(exception, tuple) and exception
            else getattr(exception, "type", None)
        )
        type_name = getattr(exc_type, "__name__", "Exception")
        text = f"{type_name}: <exception text unavailable>\n"
    return sanitize_control_chars(text, preserve_newlines=True)


def _sanitize_traceback_exception(formatted, _seen=None) -> None:
    if _seen is None:
        _seen = set()
    if id(formatted) in _seen:
        return
    _seen.add(id(formatted))

    formatted._str = sanitize_control_chars(formatted._str)
    for frame in formatted.stack:
        frame.filename = sanitize_control_chars(frame.filename)
        frame.name = sanitize_control_chars(frame.name)
        source_line = frame.line
        if source_line is not None:
            frame._line = sanitize_control_chars(source_line)
    notes = getattr(formatted, "__notes__", None)
    if isinstance(notes, (list, tuple)):
        formatted.__notes__ = [sanitize_control_chars(note) for note in notes]
    for attr in ("filename", "text", "msg"):
        value = getattr(formatted, attr, None)
        if isinstance(value, str):
            setattr(formatted, attr, sanitize_control_chars(value))
    for nested in (
        getattr(formatted, "__cause__", None),
        getattr(formatted, "__context__", None),
        *(getattr(formatted, "exceptions", None) or ()),
    ):
        if nested is not None:
            _sanitize_traceback_exception(nested, _seen)


def _sanitize_log_value(value, *, preserve_newlines: bool, _seen=None):
    if isinstance(value, str):
        return sanitize_control_chars(value, preserve_newlines=preserve_newlines)
    if isinstance(value, (dict, list, tuple)):
        if _seen is None:
            _seen = set()
        identity = id(value)
        if identity in _seen:
            return "<recursive log value>"
        _seen.add(identity)
        try:
            if isinstance(value, dict):
                return {
                    _sanitize_log_value(
                        key,
                        preserve_newlines=preserve_newlines,
                        _seen=_seen,
                    ): _sanitize_log_value(
                        item,
                        preserve_newlines=preserve_newlines,
                        _seen=_seen,
                    )
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [
                    _sanitize_log_value(
                        item,
                        preserve_newlines=preserve_newlines,
                        _seen=_seen,
                    )
                    for item in value
                ]
            return tuple(
                _sanitize_log_value(
                    item,
                    preserve_newlines=preserve_newlines,
                    _seen=_seen,
                )
                for item in value
            )
        finally:
            _seen.remove(identity)
    return value


def _patch_record(record: "Record") -> None:
    _ensure_loguru_extra(record)
    record["message"] = sanitize_control_chars(record["message"])
    record["extra"] = _sanitize_log_value(
        record["extra"],
        preserve_newlines=False,
    )
    record["extra"]["safe_exception"] = _format_safe_exception(
        record.get("exception"),
    )


def _format_console_record(record: "Record") -> str:
    _ensure_loguru_extra(record)
    return (
        "<green>[{time:HH:mm:ss.SSS}]</green> {extra[plugin_tag]} "
        "<level>[{extra[short_levelname]}]</level>{extra[astrbot_version_tag]} "
        "[{extra[source_file]}:{extra[source_line]}]: <level>{message}</level>\n"
        "{extra[safe_exception]}"
    )


def _format_file_record(record: "Record") -> str:
    _ensure_loguru_extra(record)
    return (
        "[{time:YYYY-MM-DD HH:mm:ss.SSS}] {extra[plugin_tag]} "
        "[{extra[short_levelname]}]{extra[astrbot_version_tag]} "
        "[{extra[source_file]}:{extra[source_line]}]: {message}\n"
        "{extra[safe_exception]}"
    )


_loguru = _raw_loguru_logger


class _LoguruInterceptHandler(logging.Handler):
    """将 logging 记录转发到 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = _loguru.level(record.levelname).name
        except ValueError:
            level = record.levelno

        payload = {
            "plugin_tag": getattr(record, "plugin_tag", "[Core]"),
            "short_levelname": getattr(
                record,
                "short_levelname",
                _get_short_level_name(record.levelname),
            ),
            "astrbot_version_tag": getattr(record, "astrbot_version_tag", ""),
            "source_file": getattr(
                record, "source_file", _build_source_file(record.pathname)
            ),
            "source_line": getattr(record, "source_line", record.lineno),
            "is_trace": getattr(record, "is_trace", record.name == "astrbot.trace"),
        }

        _loguru.bind(**payload).opt(exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


class LogBroker:
    """日志代理类，用于缓存和分发日志消息。"""

    def __init__(self) -> None:
        self.log_cache = deque(maxlen=CACHED_SIZE)
        self.subscribers: list[Queue] = []

    def register(self) -> Queue:
        q = Queue(maxsize=CACHED_SIZE + 10)
        self.subscribers.append(q)
        return q

    def unregister(self, q: Queue) -> None:
        self.subscribers.remove(q)

    def publish(self, log_entry: dict) -> None:
        if log_entry.get("type") == "trace":
            safe_log_entry = _sanitize_log_value(
                log_entry,
                preserve_newlines=False,
            )
        else:
            # LogQueueHandler sanitizes rendered data before adding trusted ANSI styling.
            safe_log_entry = {
                key: value
                if key == "data"
                else _sanitize_log_value(value, preserve_newlines=False)
                for key, value in log_entry.items()
            }
        self.log_cache.append(safe_log_entry)
        for q in self.subscribers:
            try:
                q.put_nowait(safe_log_entry)
            except asyncio.QueueFull:
                pass


class LogQueueHandler(logging.Handler):
    """日志处理器，用于将日志消息发送到 LogBroker。"""

    def __init__(self, log_broker: LogBroker) -> None:
        super().__init__()
        self.log_broker = log_broker

    def emit(self, record: logging.LogRecord) -> None:
        safe_record = copy.copy(record)
        safe_record.msg = sanitize_control_chars(record.getMessage())
        safe_record.args = ()
        safe_record.exc_text = _format_safe_exception(record.exc_info)
        safe_record.exc_info = None
        for field in (
            "plugin_tag",
            "short_levelname",
            "astrbot_version_tag",
            "source_file",
        ):
            value = getattr(safe_record, field, None)
            if isinstance(value, str):
                setattr(safe_record, field, sanitize_control_chars(value))
        log_entry = self.format(safe_record)
        self.log_broker.publish(
            {
                "level": record.levelname,
                "time": time.time(),
                "data": log_entry,
            },
        )


class LogManager:
    _LOGGER_HANDLER_FLAG = "_astrbot_loguru_handler"
    _ENRICH_FILTER_FLAG = "_astrbot_enrich_filter"

    _configured = False
    _configured_log_level: int | None = None
    _console_sink_id: int | None = None
    _file_sink_id: int | None = None
    _trace_sink_id: int | None = None
    _NOISY_LOGGER_LEVELS: dict[str, int] = {
        "aiosqlite": logging.WARNING,
        "filelock": logging.WARNING,
        "asyncio": logging.WARNING,
        "tzlocal": logging.WARNING,
        "apscheduler": logging.WARNING,
        "httpx": logging.WARNING,
        "httpcore": logging.WARNING,
    }

    @classmethod
    def _default_log_path(cls) -> str:
        return os.path.join(get_astrbot_data_path(), "logs", "astrbot.log")

    @classmethod
    def _resolve_log_path(cls, configured_path: str | None) -> str:
        if not configured_path:
            return cls._default_log_path()
        if os.path.isabs(configured_path):
            return configured_path
        return os.path.join(get_astrbot_data_path(), configured_path)

    @classmethod
    def _setup_loguru(cls) -> None:
        if cls._configured:
            return

        _raw_loguru_logger.configure(patcher=_patch_record)
        _loguru.remove()
        cls._console_sink_id = _loguru.add(
            sys.stdout,
            level="DEBUG",
            colorize=True,
            filter=lambda record: not record["extra"].get("is_trace", False),
            format=_format_console_record,
            **_SAFE_LOGURU_SINK_OPTIONS,
        )
        cls._configured = True

    @classmethod
    def _setup_root_bridge(cls) -> None:
        root_logger = logging.getLogger()

        has_handler = any(
            getattr(handler, cls._LOGGER_HANDLER_FLAG, False)
            for handler in root_logger.handlers
        )
        if not has_handler:
            handler = _LoguruInterceptHandler()
            setattr(handler, cls._LOGGER_HANDLER_FLAG, True)
            root_logger.addHandler(handler)
        root_logger.setLevel(cls._configured_log_level or logging.DEBUG)
        for name, level in cls._NOISY_LOGGER_LEVELS.items():
            logging.getLogger(name).setLevel(level)

    @classmethod
    def _ensure_logger_enricher_filter(cls, logger: logging.Logger) -> None:
        has_filter = any(
            getattr(existing_filter, cls._ENRICH_FILTER_FLAG, False)
            for existing_filter in logger.filters
        )
        if not has_filter:
            enrich_filter = _RecordEnricherFilter()
            setattr(enrich_filter, cls._ENRICH_FILTER_FLAG, True)
            logger.addFilter(enrich_filter)

    @classmethod
    def _ensure_logger_intercept_handler(cls, logger: logging.Logger) -> None:
        has_handler = any(
            getattr(handler, cls._LOGGER_HANDLER_FLAG, False)
            for handler in logger.handlers
        )
        if not has_handler:
            handler = _LoguruInterceptHandler()
            setattr(handler, cls._LOGGER_HANDLER_FLAG, True)
            logger.addHandler(handler)

    @classmethod
    def GetLogger(cls, log_name: str = "default") -> logging.Logger:
        cls._setup_loguru()
        cls._setup_root_bridge()

        logger = logging.getLogger(log_name)
        cls._ensure_logger_enricher_filter(logger)
        cls._ensure_logger_intercept_handler(logger)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        return logger

    @classmethod
    def set_queue_handler(cls, logger: logging.Logger, log_broker: LogBroker) -> None:
        cls._ensure_logger_enricher_filter(logger)

        for handler in logger.handlers:
            if isinstance(handler, LogQueueHandler):
                return

        handler = LogQueueHandler(log_broker)
        handler.setLevel(logging.DEBUG)
        handler.addFilter(_QueueAnsiColorFilter())
        handler.setFormatter(
            logging.Formatter(
                "%(ansi_prefix)s[%(asctime)s.%(msecs)03d] %(plugin_tag)s [%(short_levelname)s]%(astrbot_version_tag)s "
                "[%(source_file)s:%(source_line)d]: %(message)s%(ansi_reset)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ),
        )
        logger.addHandler(handler)

    @classmethod
    def _remove_sink(cls, sink_id: int | None) -> None:
        if sink_id is None:
            return
        try:
            _loguru.remove(sink_id)
        except ValueError:
            pass

    @classmethod
    def _add_file_sink(
        cls,
        *,
        file_path: str,
        level: int,
        max_mb: int | None,
        backup_count: int,
        trace: bool,
    ) -> int:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        rotation = f"{max_mb} MB" if max_mb and max_mb > 0 else None
        retention = (
            backup_count if rotation and backup_count and backup_count > 0 else None
        )
        if trace:
            return _loguru.add(
                file_path,
                level="INFO",
                format="[{time:YYYY-MM-DD HH:mm:ss.SSS}] {message}",
                encoding="utf-8",
                rotation=rotation,
                retention=retention,
                enqueue=True,
                filter=lambda record: record["extra"].get("is_trace", False),
                **_SAFE_LOGURU_SINK_OPTIONS,
            )

        logging_level_name = logging.getLevelName(level)
        if isinstance(logging_level_name, int):
            logging_level_name = "INFO"
        return _loguru.add(
            file_path,
            level=logging_level_name,
            format=_format_file_record,
            encoding="utf-8",
            rotation=rotation,
            retention=retention,
            enqueue=True,
            filter=lambda record: not record["extra"].get("is_trace", False),
            **_SAFE_LOGURU_SINK_OPTIONS,
        )

    @classmethod
    def configure_logger(
        cls,
        logger: logging.Logger,
        config: dict | None,
        override_level: str | None = None,
    ) -> None:
        if not config:
            return

        level = override_level or config.get("log_level")
        if level:
            try:
                logger.setLevel(level)
            except Exception:
                logger.setLevel(logging.INFO)
            cls._configured_log_level = logger.level

            try:
                configured_level = logging.getLevelName(logger.level)
                if isinstance(configured_level, str):
                    new_sink_id = _loguru.add(
                        sys.stdout,
                        level=configured_level,
                        colorize=True,
                        filter=lambda record: not record["extra"].get(
                            "is_trace", False
                        ),
                        format=_format_console_record,
                        **_SAFE_LOGURU_SINK_OPTIONS,
                    )
                    cls._remove_sink(cls._console_sink_id)
                    cls._console_sink_id = new_sink_id
            except Exception:
                pass

            logging.getLogger().setLevel(logger.level)
            for name, noisy_level in cls._NOISY_LOGGER_LEVELS.items():
                logging.getLogger(name).setLevel(noisy_level)

        enable_file = bool(config.get("log_file_enable", False))
        file_path = config.get("log_file_path")
        max_mb = config.get("log_file_max_mb")

        cls._remove_sink(cls._file_sink_id)
        cls._file_sink_id = None

        if not enable_file:
            return

        try:
            cls._file_sink_id = cls._add_file_sink(
                file_path=cls._resolve_log_path(file_path),
                level=logger.level,
                max_mb=max_mb,
                backup_count=3,
                trace=False,
            )
        except Exception as e:
            logger.error(f"Failed to add file sink: {e}")

    @classmethod
    def configure_trace_logger(cls, config: dict | None) -> None:
        if not config:
            return

        enable = bool(config.get("trace_log_enable"))
        path = config.get("trace_log_path")
        max_mb = config.get("trace_log_max_mb")

        trace_logger = logging.getLogger("astrbot.trace")
        cls._ensure_logger_enricher_filter(trace_logger)
        cls._ensure_logger_intercept_handler(trace_logger)
        trace_logger.setLevel(logging.INFO)
        trace_logger.propagate = False

        cls._remove_sink(cls._trace_sink_id)
        cls._trace_sink_id = None

        if not enable:
            return

        cls._trace_sink_id = cls._add_file_sink(
            file_path=cls._resolve_log_path(path or "logs/astrbot.trace.log"),
            level=logging.INFO,
            max_mb=max_mb,
            backup_count=3,
            trace=True,
        )
