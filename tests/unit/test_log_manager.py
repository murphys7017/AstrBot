import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from astrbot.core.log import _format_console_record, _format_file_record
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
    )

    payload = json.loads(trace_logger.info.call_args.args[0])
    assert payload["type"] == "prompt_trace"
    assert payload["span_id"] == "span-1"
    assert payload["turn_id"] == "turn-1"
    assert payload["platform_id"] == "platform-1"
    assert payload["fields"]["system_prompt_preview"] == "sensitive prompt"
