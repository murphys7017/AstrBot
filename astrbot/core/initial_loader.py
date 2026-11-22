"""AstrBot 启动器，负责初始化和启动核心组件和仪表板服务器。

工作流程:
1. 初始化核心生命周期, 传递数据库和日志代理实例到核心生命周期
2. 运行核心生命周期任务和仪表板服务器
"""

import asyncio
import traceback

from astrbot.core import LogBroker, logger
from astrbot.core.core_lifecycle import AstrBotCoreLifecycle
from astrbot.core.db import BaseDatabase
from astrbot.dashboard.server import AstrBotDashboard


class InitialLoader:
    """AstrBot 启动器，负责初始化和启动核心组件和仪表板服务器。"""

    def __init__(self, db: BaseDatabase, log_broker: LogBroker) -> None:
        self.db = db
        self.logger = logger
        self.log_broker = log_broker
        self.webui_dir: str | None = None

    @staticmethod
    async def _drain_tasks(
        tasks: tuple[asyncio.Task, ...],
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        """Wait for lifecycle tasks after shutdown has been requested."""
        active_tasks = tuple(task for task in tasks if not task.done())
        if not active_tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            return

        try:
            await asyncio.wait_for(
                asyncio.gather(*active_tasks, return_exceptions=True),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("AstrBot 关闭等待超时，取消仍未结束的生命周期任务。")
            for task in active_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*active_tasks, return_exceptions=True)
        finally:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def start(self) -> None:
        core_lifecycle = AstrBotCoreLifecycle(self.log_broker, self.db)
        stop_started = False
        tasks: tuple[asyncio.Task, ...] = ()

        async def stop_lifecycle() -> None:
            nonlocal stop_started
            if stop_started:
                return
            stop_started = True
            await core_lifecycle.stop()

        try:
            try:
                await core_lifecycle.initialize()
            except Exception as e:
                logger.critical(traceback.format_exc())
                logger.critical(f"😭 初始化 AstrBot 失败：{e} !!!")
                return

            core_task = asyncio.create_task(
                core_lifecycle.start(),
                name="astrbot_core_lifecycle",
            )
            tasks = (core_task,)

            webui_dir = self.webui_dir

            self.dashboard_server = AstrBotDashboard(
                core_lifecycle,
                self.db,
                core_lifecycle.dashboard_shutdown_event,
                webui_dir,
            )

            coro = self.dashboard_server.run()
            lifecycle_tasks = [core_task]
            if coro:
                lifecycle_tasks.append(
                    asyncio.create_task(coro, name="astrbot_dashboard")
                )

            tasks = tuple(lifecycle_tasks)
            done, _ = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_EXCEPTION,
            )
            exceptions = [
                task.exception()
                for task in done
                if not task.cancelled() and task.exception() is not None
            ]
            if exceptions:
                await stop_lifecycle()
                await self._drain_tasks(tasks)
                raise exceptions[0]
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            logger.info("🌈 正在关闭 AstrBot...")
            if tasks:
                await stop_lifecycle()
                await self._drain_tasks(tasks)
        finally:
            try:
                await stop_lifecycle()
            except asyncio.CancelledError:
                logger.warning("AstrBot 清理过程被取消。")
            except Exception:
                logger.error("AstrBot 清理失败。", exc_info=True)
            if tasks:
                await self._drain_tasks(tasks)
