"""Bounded native ASGI host for standalone platform callbacks."""

from fastapi import FastAPI
from hypercorn.asyncio import serve
from hypercorn.config import Config
from starlette.responses import PlainTextResponse

from astrbot.dashboard.asgi_runtime import FastAPIAppAdapter, request

__all__ = ["create_webhook_app", "request"]


class WebhookTextResponse(PlainTextResponse):
    @property
    def content_type(self):
        return self.media_type

    async def get_data(self):
        return self.body


class WebhookApp(FastAPIAppAdapter):
    def route(self, path, *, methods=None):
        def decorator(handler):
            self.add_url_rule(path, handler, methods=methods)
            return handler

        return decorator

    async def __call__(self, scope, receive, send):
        await self._app(scope, receive, send)

    async def run_task(self, *, host, port, shutdown_trigger=None, debug=False):
        config = Config()
        config.bind = [f"[{host}]:{port}" if ":" in host else f"{host}:{port}"]
        config.accesslog = None
        await serve(self._app, config, shutdown_trigger=shutdown_trigger)


def create_webhook_app(name: str) -> WebhookApp:
    app = WebhookApp(FastAPI(docs_url=None, redoc_url=None, openapi_url=None))
    app.name = name

    async def allow_callback():
        return None

    # Platform signature checks stay in the callback; this bounds and closes bodies.
    app.before_request(allow_callback)
    return app
