import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from astrbot.core import log as log_module
from astrbot.core.log import (
    LogBroker,
    LogManager,
    LogQueueHandler,
    _format_console_record,
    _format_file_record,
    _is_plugin_path,
    _patch_record,
    _sanitize_traceback_exception,
)
from astrbot.core.utils import trace as trace_utils


def _make_loguru_record():
    return {
        "extra": {},
        "level": SimpleNamespace(name="INFO", no=20),
        "file": SimpleNamespace(path=__file__),
        "line": 12,
    }


def test_loguru_console_formatter_enriches_missing_astrbot_fields():
    record = _make_loguru_record()

    template = _format_console_record(record)

    assert "{extra[plugin_tag]}" in template
    assert record["extra"]["plugin_tag"] == "[Core]"
    assert record["extra"]["short_levelname"] == "INFO"
    assert record["extra"]["source_line"] == 12


def test_loguru_file_formatter_enriches_missing_astrbot_fields():
    record = _make_loguru_record()

    template = _format_file_record(record)

    assert "{extra[plugin_tag]}" in template
    assert record["extra"]["plugin_tag"] == "[Core]"
    assert record["extra"]["short_levelname"] == "INFO"
    assert record["extra"]["source_line"] == 12


def test_loguru_sinks_disable_exception_diagnostics(monkeypatch, tmp_path):
    add_sink = MagicMock(side_effect=[101, 102, 103])
    configure = MagicMock()
    monkeypatch.setattr(log_module._loguru, "add", add_sink)
    monkeypatch.setattr(log_module._loguru, "remove", MagicMock())
    monkeypatch.setattr(log_module._raw_loguru_logger, "configure", configure)
    monkeypatch.setattr(LogManager, "_configured", False)
    monkeypatch.setattr(LogManager, "_console_sink_id", None)

    LogManager._setup_loguru()
    LogManager._add_file_sink(
        file_path=str(tmp_path / "astrbot.log"),
        level=20,
        max_mb=None,
        backup_count=3,
        trace=False,
    )
    LogManager._add_file_sink(
        file_path=str(tmp_path / "astrbot.trace.log"),
        level=20,
        max_mb=None,
        backup_count=3,
        trace=True,
    )

    assert add_sink.call_count == 3
    assert configure.call_args.kwargs["patcher"] is _patch_record
    for call in add_sink.call_args_list:
        assert call.kwargs["backtrace"] is False
        assert call.kwargs["diagnose"] is False


def test_global_loguru_patcher_escapes_message_and_exception_controls():
    try:
        raise ValueError("untrusted\a\r\ntext")
    except ValueError as exc:
        exception = SimpleNamespace(
            type=type(exc),
            value=exc,
            traceback=exc.__traceback__,
        )
    record = _make_loguru_record()
    record.update(message="user\a\r\nmessage", exception=exception)

    _patch_record(record)

    assert record["message"] == "user\\x07\\x0d\\x0amessage"
    assert (
        "ValueError: untrusted\\x07\\x0d\\x0atext\n"
        in record["extra"]["safe_exception"]
    )
    assert "\a" not in record["extra"]["safe_exception"]


def test_traceback_sanitizer_handles_recursive_exception_links():
    formatted = SimpleNamespace(_str="bad\a", stack=[], exceptions=())
    formatted.__cause__ = formatted
    formatted.__context__ = None

    _sanitize_traceback_exception(formatted)

    assert formatted._str == "bad\\x07"


def test_log_broker_sanitizes_trace_values_without_mutating_input():
    broker = LogBroker()
    recursive_value = []
    recursive_value.append(recursive_value)
    entry = {
        "type": "trace",
        "message_outline": "hello\a\nworld",
        "fields": {"response": "bad\x1b[2J", "recursive": recursive_value},
    }

    broker.publish(entry)

    assert entry["message_outline"] == "hello\a\nworld"
    assert broker.log_cache[-1]["message_outline"] == "hello\\x07\\x0aworld"
    assert broker.log_cache[-1]["fields"]["response"] == "bad\\x1b[2J"
    assert broker.log_cache[-1]["fields"]["recursive"] == ["<recursive log value>"]


def test_log_queue_handler_sanitizes_messages_and_preserves_safe_traceback_lines():
    broker = LogBroker()
    handler = LogQueueHandler(broker)
    handler.setFormatter(
        logging.Formatter("\x1b[1;34m%(message)s\x1b[0m"),
    )
    try:
        raise ValueError("bad\a\r\ninput")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "astrbot", logging.ERROR, __file__, 1, "message\a\r\ninjected", (), exc_info
    )

    handler.emit(record)
    data = broker.log_cache[-1]["data"]

    assert data.startswith("\x1b[1;34m")
    assert "injected\x1b[0m\nTraceback" in data
    assert "message\\x07\\x0d\\x0ainjected" in data
    assert "ValueError: bad\\x07\\x0d\\x0ainput\n" in data
    assert "\a" not in data
    assert "\r" not in data
    assert record.exc_info is exc_info


def test_plugin_log_paths_are_detected_on_windows():
    assert _is_plugin_path(r"C:\AstrBot\data\plugins\sample\main.py")
    assert _is_plugin_path(r"C:\AstrBot\astrbot\builtin_stars\sample.py")


def test_prompt_trace_is_disabled_without_trace_file_logging(monkeypatch):
    trace_logger = MagicMock()
    event = SimpleNamespace(
        trace=SimpleNamespace(span_id="span-1"),
        session_id="session-1",
        get_extra=lambda key, default=None: "turn-1"
        if key == "_turn_id"
        else default,
        get_platform_id=lambda: "platform-1",
    )
    monkeypatch.setattr(trace_utils, "astrbot_config", {"trace_log_enable": False})
    monkeypatch.setattr(trace_utils, "_get_trace_logger", lambda: trace_logger)

    trace_utils.record_prompt_trace(
        event,
        "prompt.render_result",
        system_prompt_preview="sensitive prompt",
        messages=[{"role": "user", "content": "private conversation"}],
        duration_ms=12,
    )

    trace_logger.info.assert_not_called()


def test_prompt_trace_writes_details_only_to_trace_logger(monkeypatch):
    trace_logger = MagicMock()
    event = SimpleNamespace(
        trace=SimpleNamespace(span_id="span-1"),
        session_id="session-1",
        get_extra=lambda key, default=None: "turn-1"
        if key == "_turn_id"
        else default,
        get_platform_id=lambda: "platform-1",
    )
    monkeypatch.setattr(trace_utils, "astrbot_config", {"trace_log_enable": True})
    monkeypatch.setattr(trace_utils, "_get_trace_logger", lambda: trace_logger)

    trace_utils.record_prompt_trace(
        event,
        "prompt.render_result",
        system_prompt_preview="sensitive prompt",
        messages=[{"role": "user", "content": "private conversation"}],
        contexts=[{"role": "user", "content": "private context"}],
        system="private system prompt",
        image_urls=["https://example.invalid/private-image"],
        response_tail="private model response",
        duration_ms=12,
    )

    payload = json.loads(trace_logger.info.call_args.args[0])
    assert payload["type"] == "prompt_trace"
    assert payload["span_id"] == "span-1"
    assert payload["turn_id"] == "turn-1"
    assert payload["platform_id"] == "platform-1"
    assert payload["fields"]["system_prompt_preview"] == "[REDACTED]"
    assert payload["fields"]["messages"] == "[REDACTED]"
    assert payload["fields"]["contexts"] == "[REDACTED]"
    assert payload["fields"]["system"] == "[REDACTED]"
    assert payload["fields"]["image_urls"] == "[REDACTED]"
    assert payload["fields"]["response_tail"] == "[REDACTED]"
    assert payload["fields"]["duration_ms"] == 12


def test_event_trace_redacts_content_and_keeps_timing(monkeypatch):
    broker = LogBroker()
    monkeypatch.setattr(trace_utils, "astrbot_config", {"trace_enable": True})
    monkeypatch.setattr(trace_utils, "_get_log_broker", lambda: broker)
    monkeypatch.setattr(
        trace_utils,
        "_get_trace_logger",
        lambda: SimpleNamespace(handlers=[]),
    )

    span = trace_utils.TraceSpan(
        "test",
        sender_name="private sender",
        message_outline="private message",
    )
    span.record(
        "agent_tool_result",
        tool_result="private tool output",
        tool_name={"name": "search", "arguments": "private tool arguments"},
        duration_ms=42.5,
    )

    record = broker.log_cache[-1]
    assert record["sender_name"] is None
    assert record["message_outline"] is None
    assert record["fields"]["tool_result"] == "[REDACTED]"
    assert record["fields"]["tool_name"] == {
        "name": "search",
        "arguments": "[REDACTED]",
    }
    assert record["fields"]["duration_ms"] == 42.5
