from astrbot.core.utils.error_redaction import redact_sensitive_text


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
