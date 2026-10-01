from dataclasses import dataclass

from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.dashboard.asgi_runtime import FastAPIAppAdapter


@dataclass
class ServiceContext:
    config: AstrBotConfig
    app: FastAPIAppAdapter


class DashboardService:
    def __init__(self, context: ServiceContext) -> None:
        self.app = context.app
        self.config = context.config


@dataclass
class Response:
    status: str | None = None
    message: str | None = None
    data: dict | list | None = None

    def error(self, message: str):
        self.status = "error"
        self.message = message
        return self

    def ok(self, data: dict | list | None = None, message: str | None = None):
        self.status = "ok"
        if data is None:
            data = {}
        self.data = data
        self.message = message
        return self


RouteContext = ServiceContext
Route = DashboardService
