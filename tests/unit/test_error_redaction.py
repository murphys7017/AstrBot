from astrbot.core.utils.error_redaction import (
    redact_sensitive_text,
    sanitize_control_chars,
)


def test_redact_sensitive_text_hides_api_keys_and_media_rkeys():
    text = (
        "message=sk-abcdefghijklmnopqrstuvwxyz "
        "url=https://example.test/file?rkey=temporary-value&file_size=1"
    )

    redacted = redact_sensitive_text(text)

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "rkey=temporary-value" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_sensitive_text_hides_hyphenated_sk_tokens():
    token = "sk-cp-example-token-with-hyphens-123456"

    redacted = redact_sensitive_text(f"command failed: {token}")

    assert token not in redacted
    assert redacted == "command failed: [REDACTED]"


def test_sanitize_control_chars_escapes_terminal_controls_and_newlines():
    assert sanitize_control_chars("bell\a\x1b[31m\r\nnext") == (
        "bell\\x07\\x1b[31m\\x0d\\x0anext"
    )


def test_sanitize_control_chars_can_preserve_structural_newlines():
    assert sanitize_control_chars("traceback\nValueError: bell\a", preserve_newlines=True) == (
        "traceback\nValueError: bell\\x07"
    )
