"""Opt-in gzip encoding for dashboard JS, CSS and HTML responses."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import os
from pathlib import Path

from starlette.datastructures import Headers
from starlette.responses import FileResponse, Response

_COMPRESSIBLE_MEDIA_TYPES = {
    "text/html",
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
}


def accepts_gzip(header: str) -> bool:
    for entry in header.split(","):
        encoding, *parameters = entry.strip().split(";")
        if encoding.strip().lower() != "gzip":
            continue
        quality = 1.0
        for parameter in parameters:
            key, separator, value = parameter.strip().partition("=")
            if separator and key.lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    return False
        return 0 < quality <= 1
    return False


def _read_compressed_file(path: Path) -> tuple[os.stat_result, bytes | None]:
    with path.open("rb") as source:
        stat = os.fstat(source.fileno())
        if stat.st_size < 1024:
            return stat, None
        data = source.read()
    encoded = gzip.compress(data, compresslevel=6, mtime=0)
    return stat, encoded if len(encoded) < len(data) else None


class DashboardStaticFileResponse(FileResponse):
    async def __call__(self, scope, receive, send) -> None:
        media_type = (self.media_type or "").split(";", 1)[0].lower()
        if media_type not in _COMPRESSIBLE_MEDIA_TYPES:
            await super().__call__(scope, receive, send)
            return

        headers = Headers(scope=scope)
        self.headers.add_vary_header("Accept-Encoding")
        if headers.get("range") or not accepts_gzip(headers.get("accept-encoding", "")):
            await super().__call__(scope, receive, send)
            return

        stat, encoded = await asyncio.to_thread(_read_compressed_file, Path(self.path))
        self.stat_result = stat
        self.set_stat_headers(stat)
        if encoded is None:
            await super().__call__(scope, receive, send)
            return

        response_headers = dict(self.headers)
        response_headers.pop("accept-ranges", None)
        response_headers["content-encoding"] = "gzip"
        response_headers["content-length"] = str(len(encoded))
        response_headers["etag"] = '"' + hashlib.sha256(encoded).hexdigest() + '"'
        response = Response(
            b"" if scope["method"] == "HEAD" else encoded,
            status_code=self.status_code,
            headers=response_headers,
            background=self.background,
        )
        await response(scope, receive, send)
