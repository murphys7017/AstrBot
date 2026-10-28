import asyncio
from dataclasses import dataclass

from astrbot.core import logger
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
        self._owned_background_tasks: dict[asyncio.Task, bool] = {}
        self._shutting_down = False

    def create_background_task(
        self,
        coroutine,
        *,
        name: str,
        cancel_on_shutdown: bool = True,
    ) -> asyncio.Task:
        if self._shutting_down:
            close = getattr(coroutine, "close", None)
            if callable(close):
                close()
            raise RuntimeError("Dashboard service is shutting down")

        task = asyncio.create_task(coroutine, name=name)
        self._owned_background_tasks[task] = cancel_on_shutdown
        task.add_done_callback(self._on_background_task_done)
        return task

    def _on_background_task_done(self, task: asyncio.Task) -> None:
        self._owned_background_tasks.pop(task, None)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.error(
                "Dashboard background task failed: %s",
                task.get_name(),
                exc_info=(type(error), error, error.__traceback__),
            )

    async def shutdown(self) -> None:
        self._shutting_down = True
        tasks = list(self._owned_background_tasks)
        for task in tasks:
            if self._owned_background_tasks.get(task, True):
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


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
