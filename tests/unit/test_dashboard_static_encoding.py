import httpx
import pytest
from fastapi import FastAPI

from astrbot.dashboard.asgi_runtime import FastAPIAppAdapter


@pytest.mark.asyncio
async def test_static_gzip_preserves_payload_range_and_cache_headers(tmp_path):
    body = b"const greeting = 'hello';\n" * 200
    (tmp_path / "app.js").write_bytes(body)
    app = FastAPI()
    adapter = FastAPIAppAdapter(app, static_folder=str(tmp_path))

    @app.api_route("/app.js", methods=["GET", "HEAD"])
    async def static_asset():
        response = await adapter.send_static_file("app.js")
        response.headers["Cache-Control"] = "no-cache"
        return response

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver"
    ) as client:
        compressed = await client.get("/app.js", headers={"Accept-Encoding": "gzip"})
        identity = await client.get("/app.js", headers={"Accept-Encoding": "gzip;q=0"})
        partial = await client.get(
            "/app.js", headers={"Accept-Encoding": "gzip", "Range": "bytes=0-4"}
        )
        head = await client.head("/app.js", headers={"Accept-Encoding": "gzip"})

    assert compressed.content == identity.content == body
    assert compressed.headers["Content-Encoding"] == "gzip"
    assert "Content-Encoding" not in identity.headers
    assert compressed.headers["ETag"] != identity.headers["ETag"]
    assert "Accept-Encoding" in identity.headers["Vary"]
    assert (
        compressed.headers["Cache-Control"]
        == identity.headers["Cache-Control"]
        == "no-cache"
    )
    assert partial.status_code == 206 and partial.content == body[:5]
    assert "Content-Encoding" not in partial.headers
    assert head.content == b""
    assert head.headers["Content-Length"] == compressed.headers["Content-Length"]
