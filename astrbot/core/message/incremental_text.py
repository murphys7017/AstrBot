"""Append-only preparation of decoded speech deltas before display or TTS."""

from __future__ import annotations

from collections.abc import Callable

_OPEN = "<system_reminder>"
_CLOSE = "</system_reminder>"
_MAX_TAG_LENGTH = max(len(_OPEN), len(_CLOSE))
_MAX_RAW_BYTES = 1024 * 1024
_MAX_VISIBLE_UTF16_UNITS = 65536


class IncrementalTextError(ValueError):
    """The accepted prefix is still available as preparer.text after failure."""


class IncrementalTextPreparer:
    """One decoded Persona segment, with state across all its text deltas.

    Private tags can cross delta boundaries and nest, but must close within this
    segment. Only unambiguous visible text is returned. Complete-message plugin
    decorators are deliberately outside this boundary: they cannot retract text
    already spoken, and repeating them per delta can repeat their side effects.
    The mandatory checker sees the whole visible prefix, including cross-delta
    keyword matches. A rejected candidate never replaces the accepted prefix.
    """

    def __init__(self, check_response: Callable[[str], bool]) -> None:
        self._check_response = check_response
        self._pending = ""
        self._depth = 0
        self._newlines = 0
        self._raw_bytes = 0
        self._visible_units = 0
        self._text = ""
        self._closed = False

    @property
    def text(self) -> str:
        return self._text

    def _visible(self, text: str) -> str:
        result: list[str] = []
        for char in text:
            self._newlines = self._newlines + 1 if char == "\n" else 0
            if self._newlines <= 2:
                result.append(char)
        return "".join(result)

    def _filter(self, delta: str) -> str:
        buffer = self._pending + delta
        self._pending = ""
        parts: list[str] = []
        pos = 0
        while pos < len(buffer):
            tag_at = buffer.find("<", pos)
            if tag_at < 0:
                if self._depth == 0:
                    parts.append(self._visible(buffer[pos:]))
                break
            if self._depth == 0:
                parts.append(self._visible(buffer[pos:tag_at]))
            pos = tag_at
            candidate = buffer[pos : pos + _MAX_TAG_LENGTH].lower()
            if candidate.startswith(_OPEN):
                self._depth += 1
                pos += len(_OPEN)
            elif candidate.startswith(_CLOSE):
                self._depth = max(0, self._depth - 1)
                pos += len(_CLOSE)
            elif _OPEN.startswith(candidate) or _CLOSE.startswith(candidate):
                self._pending = buffer[pos:]
                break
            else:
                if self._depth == 0:
                    parts.append(self._visible("<"))
                pos += 1
        return "".join(parts)

    def feed(self, delta: str) -> str:
        if self._closed:
            raise IncrementalTextError("incremental_text_already_closed")
        try:
            if not isinstance(delta, str) or not delta:
                raise IncrementalTextError("incremental_text_delta_invalid")
            if len(delta) > _MAX_RAW_BYTES - self._raw_bytes:
                raise IncrementalTextError("incremental_text_input_too_large")
            try:
                raw_bytes = len(delta.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise IncrementalTextError("incremental_text_unicode_invalid") from exc
            if self._raw_bytes + raw_bytes > _MAX_RAW_BYTES:
                raise IncrementalTextError("incremental_text_input_too_large")
            self._raw_bytes += raw_bytes
            prepared = self._filter(delta)
            if not prepared:
                return ""
            if len(prepared) > _MAX_VISIBLE_UTF16_UNITS - self._visible_units:
                raise IncrementalTextError("incremental_text_output_too_large")
            units = len(prepared.encode("utf-16-le")) // 2
            if self._visible_units + units > _MAX_VISIBLE_UTF16_UNITS:
                raise IncrementalTextError("incremental_text_output_too_large")
            candidate = self._text + prepared
            if not self._check_response(candidate):
                raise IncrementalTextError("unsafe_response")
            self._text = candidate
            self._visible_units += units
            return prepared
        except Exception:
            self._closed = True
            raise

    def finish(self) -> str:
        """Seal and return the full accepted text for validation, never a new delta."""
        if self._closed:
            raise IncrementalTextError("incremental_text_already_closed")
        self._closed = True
        if self._pending or self._depth:
            raise IncrementalTextError("incremental_text_hidden_markup_unclosed")
        if not self._check_response(self._text):
            raise IncrementalTextError("unsafe_response")
        return self._text
