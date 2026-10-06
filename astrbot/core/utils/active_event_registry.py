from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astrbot.core.platform import AstrMessageEvent


class ActiveEventRegistry:
    """维护 unified_msg_origin 到活跃事件的映射。

    用于在 reset 等场景下终止该会话正在处理的事件。
    """

    def __init__(self) -> None:
        self._events: dict[str, set[AstrMessageEvent]] = defaultdict(set)
        self._background_tasks: dict[str, dict[asyncio.Task, AstrMessageEvent]] = (
            defaultdict(dict)
        )
        self._background_cancel_requested: set[asyncio.Task] = set()

    def register_background_task(
        self, event: AstrMessageEvent, task: asyncio.Task
    ) -> None:
        if task.done():
            return
        umo = event.unified_msg_origin
        self._background_tasks[umo][task] = event

        def remove_task(done_task: asyncio.Task) -> None:
            tasks = self._background_tasks.get(umo)
            if tasks is not None:
                tasks.pop(done_task, None)
                if not tasks:
                    self._background_tasks.pop(umo, None)
            self._background_cancel_requested.discard(done_task)

        task.add_done_callback(remove_task)
        if event.is_stopped() or event.get_extra("agent_stop_requested"):
            self._background_cancel_requested.add(task)
            task.cancel()

    def register(self, event: AstrMessageEvent) -> None:
        self._events[event.unified_msg_origin].add(event)

    def unregister(self, event: AstrMessageEvent) -> None:
        umo = event.unified_msg_origin
        self._events[umo].discard(event)
        if not self._events[umo]:
            del self._events[umo]

    def stop_all(
        self,
        umo: str,
        exclude: AstrMessageEvent | None = None,
    ) -> int:
        """终止指定 UMO 的所有活跃事件。

        Args:
            umo: 统一消息来源标识符。
            exclude: 需要排除的事件（通常是发起 reset 的事件本身）。

        Returns:
            被终止的事件数量。
        """
        events = set(self._events.get(umo, []))
        events.update(
            event
            for task, event in self._background_tasks.get(umo, {}).items()
            if not task.done()
        )
        for event in events:
            if event is not exclude:
                event.stop_event()
        return self.request_agent_stop_all(umo, exclude)

    def request_agent_stop_all(
        self,
        umo: str,
        exclude: AstrMessageEvent | None = None,
    ) -> int:
        """请求停止指定 UMO 的所有活跃事件中的 Agent 运行。

        与 stop_all 不同，这里不会调用 event.stop_event()，
        因此不会中断事件传播，后续流程（如历史记录保存）仍可继续。
        """
        count = 0
        tasks = self._background_tasks.get(umo, {})
        events = set(self._events.get(umo, []))
        events.update(event for task, event in tasks.items() if not task.done())
        for event in events:
            if event is not exclude:
                event.set_extra("agent_stop_requested", True)
                count += 1
        for task, event in list(tasks.items()):
            if (
                event is not exclude
                and not task.done()
                and task not in self._background_cancel_requested
            ):
                self._background_cancel_requested.add(task)
                task.cancel()
        return count


active_event_registry = ActiveEventRegistry()
