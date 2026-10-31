"""Shared magic-byte helpers for supported audio wire formats."""

from __future__ import annotations

TENCENT_SILK_MAGIC = b"#!SILK_V3"
TENCENT_SILK_PREFIXES = (b"", b"\x02", b"\x03")


def is_tencent_silk_header(data: bytes) -> bool:
    """Return whether *data* starts with a supported Tencent SILK header."""
    return any(
        data.startswith(prefix + TENCENT_SILK_MAGIC)
        for prefix in TENCENT_SILK_PREFIXES
    )


def strip_tencent_silk_prefix(data: bytes) -> bytes:
    """Remove a supported Tencent marker while preserving the SILK header."""
    for prefix in TENCENT_SILK_PREFIXES[1:]:
        if data.startswith(prefix + TENCENT_SILK_MAGIC):
            return data[len(prefix) :]
    return data


__all__ = [
    "TENCENT_SILK_MAGIC",
    "TENCENT_SILK_PREFIXES",
    "is_tencent_silk_header",
    "strip_tencent_silk_prefix",
]
