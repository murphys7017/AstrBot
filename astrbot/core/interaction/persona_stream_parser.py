"""Streaming Persona expression protocol parser."""

from __future__ import annotations

import json
from typing import Any

from astrbot.core.prompt.json_recovery import parse_json_record, recover_json_record

from .persona_expression_types import (
    InteractionExpressionError,
    PersonaExpressionRequest,
    PersonaExpressionResult,
    PersonaExpressionSegment,
)
from .persona_expression_validation import PersonaStreamValidationContract
from .types import PersonalResponseAction

_UNPARSED_STREAM_RECORD = object()


class PersonaSegmentStreamParser:
    """Parse and validate the line-framed segment_stream_v1 model protocol."""

    MAX_RECORD_CHARS = 64_000
    MAX_RECORDS = 2_048
    MAX_SEGMENTS = 128
    MAX_STREAM_CHARS = 256_000

    def __init__(
        self,
        req: PersonaExpressionRequest,
        validation_contract: PersonaStreamValidationContract | None = None,
    ) -> None:
        self.req = req
        self._validation = validation_contract or PersonaStreamValidationContract()
        self._buffer = ""
        self._wire_text = ""
        self._record_count = 0
        self._turn_action: PersonalResponseAction | None = None
        self._segments: list[PersonaExpressionSegment] = []
        self._current_segment: PersonaExpressionSegment | None = None
        self._delta_index = 0
        self._finished = False
        self._last_record_shape: dict[str, Any] = {}

    def _append_text(self, text: str, *, final: bool = False) -> list[str]:
        if self._finished and text.strip():
            raise InteractionExpressionError("persona_stream_data_after_finish")
        if len(self._wire_text) + len(text) > self.MAX_STREAM_CHARS:
            raise InteractionExpressionError("persona_stream_too_large")
        self._wire_text += text
        self._buffer += text
        records = self._buffer.split("\n")
        self._buffer = records.pop()
        if final and self._buffer:
            records.append(self._buffer)
            self._buffer = ""
        if len(self._buffer) > self.MAX_RECORD_CHARS:
            raise InteractionExpressionError("persona_stream_record_too_large")
        return records

    def feed(self, text: str) -> list[dict[str, Any]]:
        events = []
        for line in self._append_text(text):
            event = self._consume_line(line)
            if event is not None and event.get("type") != "finish":
                events.append(event)
        return events

    async def feed_async(self, text: str, *, plugin_context, event, final: bool = False):
        """Repair only complete lines; retain original wire bytes for auditing."""
        for line in self._append_text(text, final=final):
            if len(line) > self.MAX_RECORD_CHARS:
                raise InteractionExpressionError("persona_stream_record_too_large")
            parsed_record: object = _UNPARSED_STREAM_RECORD
            if line.strip():
                try:
                    parsed_record = json.loads(
                        line,
                        object_pairs_hook=self._unique_object,
                    )
                except json.JSONDecodeError:
                    parsed_record = await recover_json_record(
                        line, plugin_context=plugin_context, event=event,
                        scope="persona_stream_record",
                    )
                    if parsed_record is None:
                        raise InteractionExpressionError("persona_stream_invalid_json") from None
            record = self._consume_line(line, parsed_record=parsed_record)
            if record is not None and record.get("type") != "finish":
                yield record

    def recover_normal_end(self) -> list[dict[str, Any]]:
        """Close existing content after a verified normal Provider stop only."""
        if self._finished or self._buffer or self._turn_action is None:
            return []
        events = []
        if self._current_segment is not None:
            if not self._current_segment.speech:
                return []
            event = self._consume_line('{"v":1,"record":"segment_end"}')
            if event is not None:
                events.append(event)
        if not self._segments and self._turn_action is not PersonalResponseAction.SILENT:
            return []
        self._consume_line('{"v":1,"record":"finish","effect_calls":[]}')
        return events

    def finish(self) -> PersonaExpressionResult:
        if self._buffer:
            event = self._consume_line(self._buffer)
            self._buffer = ""
            if event is not None and event.get("type") == "finish":
                self._finished = True
        if not self._finished:
            raise InteractionExpressionError("persona_stream_missing_finish")
        result = PersonaExpressionResult(
            segments=self._segments,
            turn_action=self._turn_action,
        )
        self._validation.validate_result(self.req, result)
        return result

    @property
    def wire_text(self) -> str:
        return self._wire_text

    @property
    def diagnostics(self) -> dict[str, Any]:
        stripped = self._wire_text.lstrip()
        first_line = stripped.splitlines()[0] if stripped else ""
        first_line_kind = (
            "empty"
            if not stripped
            else "markdown_fence"
            if stripped.startswith("```")
            else "json_object"
            if stripped.startswith("{")
            else "plain_text"
        )
        lines = self._wire_text.splitlines()
        return {
            "record_count": self._record_count,
            "received_chars": len(self._wire_text),
            "header_seen": self._turn_action is not None,
            "first_line_kind": first_line_kind,
            "first_line_length": len(first_line),
            "line_count": len(lines),
            "blank_line_count": sum(not line.strip() for line in lines),
            **self._last_record_shape,
        }

    def _consume_line(
        self,
        line: str,
        *,
        parsed_record: object = _UNPARSED_STREAM_RECORD,
    ) -> dict[str, Any] | None:
        if len(line) > self.MAX_RECORD_CHARS:
            raise InteractionExpressionError("persona_stream_record_too_large")
        if not line.strip():
            # Blank separators carry no record and must not cancel the turn.
            return None
        self._record_count += 1
        self._last_record_shape = {}
        if self._record_count > self.MAX_RECORDS:
            raise InteractionExpressionError("persona_stream_too_many_records")
        if parsed_record is _UNPARSED_STREAM_RECORD:
            try:
                record = json.loads(line, object_pairs_hook=self._unique_object)
            except InteractionExpressionError:
                raise
            except (json.JSONDecodeError, TypeError) as exc:
                try:
                    record = parse_json_record(line)
                except ValueError as duplicate:
                    raise InteractionExpressionError("persona_stream_duplicate_field") from duplicate
                if record is None:
                    raise InteractionExpressionError(
                        "persona_stream_invalid_json", str(exc)
                    ) from exc
        else:
            record = parsed_record
        if not isinstance(record, dict):
            raise InteractionExpressionError("persona_stream_record_not_object")
        self._last_record_shape = {
            "field_count": len(record),
            "has_version": "v" in record,
            "version_type": type(record.get("v")).__name__,
            "version": record["v"] if type(record.get("v")) is int else None,
            "has_segments": "segments" in record,
            "has_turn_action": "turn_action" in record,
        }
        if self._finished:
            raise InteractionExpressionError("persona_stream_data_after_finish")
        if "v" not in record:
            reason = (
                "persona_stream_nonstream_expression"
                if "turn_action" in record and "segments" in record
                else "persona_stream_missing_version"
            )
            raise InteractionExpressionError(reason)
        if type(record["v"]) is not int:
            raise InteractionExpressionError("persona_stream_invalid_version_type")
        if record["v"] != 1:
            raise InteractionExpressionError("persona_stream_unsupported_version")
        record_type = record.get("record")

        if self._turn_action is None:
            if record_type != "header" or set(record) != {"v", "record", "turn_action"}:
                raise InteractionExpressionError("persona_stream_header_required")
            try:
                action = PersonalResponseAction(str(record["turn_action"]))
            except ValueError as exc:
                raise InteractionExpressionError(
                    "persona_stream_invalid_turn_action"
                ) from exc
            if action not in self._validation.allowed_turn_actions(self.req):
                raise InteractionExpressionError(
                    "persona_stream_disallowed_turn_action"
                )
            self._turn_action = action
            return {"type": "header", "turn_action": action.value}

        if record_type == "header":
            raise InteractionExpressionError("persona_stream_duplicate_header")
        if record_type == "segment_start":
            if self._turn_action is PersonalResponseAction.SILENT:
                raise InteractionExpressionError(
                    "persona_stream_segment_without_reply"
                )
            if self._current_segment is not None:
                raise InteractionExpressionError("persona_stream_nested_segment")
            if set(record) != {"v", "record", "actions", "tendency"}:
                raise InteractionExpressionError("persona_stream_invalid_segment_start")
            if len(self._segments) >= self.MAX_SEGMENTS:
                raise InteractionExpressionError("persona_stream_too_many_segments")
            self._current_segment = self._validation.validate_segment(
                {
                    "speech": "",
                    "actions": record.get("actions"),
                    "tendency": record.get("tendency"),
                },
                discard_invalid_actions=True,
            )
            return {
                "type": "segment_start",
                "segment_index": len(self._segments),
                "actions": list(self._current_segment.actions),
                "tendency": dict(self._current_segment.tendency),
            }
        if record_type == "speech_delta":
            if self._current_segment is None:
                raise InteractionExpressionError("persona_stream_delta_outside_segment")
            if set(record) != {"v", "record", "text"}:
                raise InteractionExpressionError("persona_stream_invalid_speech_delta")
            delta = record.get("text")
            if not isinstance(delta, str) or not delta:
                raise InteractionExpressionError("persona_stream_invalid_speech_delta")
            self._current_segment.speech += delta
            event = {
                "type": "speech_delta",
                "segment_index": len(self._segments),
                "delta_index": self._delta_index,
                "text": delta,
            }
            self._delta_index += 1
            return event
        if record_type == "segment_end":
            if self._current_segment is None:
                raise InteractionExpressionError("persona_stream_end_without_segment")
            if set(record) != {"v", "record"}:
                raise InteractionExpressionError("persona_stream_invalid_segment_end")
            segment = self._validation.validate_segment(
                self._current_segment.to_mapping(),
                discard_invalid_actions=True,
            )
            self._segments.append(segment)
            self._current_segment = None
            self._delta_index = 0
            return {
                "type": "segment_end",
                "segment_index": len(self._segments) - 1,
                "segment": segment.to_mapping(),
            }
        if record_type == "finish":
            if self._current_segment is not None:
                raise InteractionExpressionError("persona_stream_unclosed_segment")
            if set(record) != {"v", "record", "effect_calls"}:
                raise InteractionExpressionError("persona_stream_invalid_finish")
            if record.get("effect_calls") != []:
                raise InteractionExpressionError("persona_stream_effects_unsupported")
            self._finished = True
            return {"type": "finish", "segment_count": len(self._segments)}
        raise InteractionExpressionError("persona_stream_unknown_record")

    @staticmethod
    def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                previous = result[key]
                # Some providers occasionally repeat an already emitted field
                # verbatim while serializing a streamed record. This is
                # redundant but unambiguous; accept it. Conflicting values
                # remain a protocol violation and fail closed.
                if type(previous) is type(value) and previous == value:
                    continue
                raise InteractionExpressionError("persona_stream_duplicate_field")
            result[key] = value
        return result



__all__ = ["PersonaSegmentStreamParser"]
