"""事件总线, 用于处理事件的分发和处理
事件总线是一个异步队列, 用于接收各种消息事件, 并将其发送到Scheduler调度器进行处理
其中包含了一个无限循环的调度函数, 用于从事件队列中获取新的事件, 并创建一个新的异步任务来执行管道调度器的处理逻辑

class:
    EventBus: 事件总线, 用于处理事件的分发和处理

工作流程:
1. 维护一个异步队列, 来接受各种消息事件
2. 无限循环的调度函数, 从事件队列中获取新的事件, 打印日志并创建一个新的异步任务来执行管道调度器的处理逻辑
"""

import asyncio
from asyncio import Queue
from collections.abc import Mapping

from astrbot.core import logger
from astrbot.core.astrbot_config_mgr import AstrBotConfigManager
from astrbot.core.pipeline.scheduler import PipelineScheduler
from astrbot.core.platform.unique_session import apply_unique_session
from astrbot.core.utils.error_redaction import sanitize_control_chars

from .platform import AstrMessageEvent

MAX_PENDING_EVENTS = 1024
MAX_CONCURRENT_PIPELINES = 64


class EventBus:
    """用于处理事件的分发和处理"""

    def __init__(
        self,
        event_queue: Queue,
        pipeline_scheduler_mapping: dict[str, PipelineScheduler],
        astrbot_config_mgr: AstrBotConfigManager,
        *,
        max_concurrent_pipelines: int = MAX_CONCURRENT_PIPELINES,
    ) -> None:
        if max_concurrent_pipelines < 1:
            raise ValueError("max_concurrent_pipelines must be positive")
        self.event_queue = event_queue  # 事件队列
        # abconf uuid -> scheduler
        self.pipeline_scheduler_mapping = pipeline_scheduler_mapping
        self.astrbot_config_mgr = astrbot_config_mgr
        self._pending_tasks: set[asyncio.Task] = set()
        self._pipeline_slots = asyncio.Semaphore(max_concurrent_pipelines)
        self._accepting_events = True
        self._stopped = False

    async def dispatch(self) -> None:
        while self._accepting_events:
            await self._pipeline_slots.acquire()
            slot_transferred = False
            try:
                event: AstrMessageEvent = await self.event_queue.get()
                if not self._accepting_events:
                    return
                trace = getattr(event, "trace", None)
                record_trace = getattr(trace, "record", None)
                if callable(record_trace):
                    event_age_ms = None
                    elapsed_ms = getattr(trace, "elapsed_ms", None)
                    if callable(elapsed_ms):
                        try:
                            elapsed_value = elapsed_ms()
                            if isinstance(elapsed_value, (int, float)):
                                event_age_ms = round(elapsed_value, 3)
                        except (TypeError, ValueError):
                            pass
                    record_trace(
                        "event_dispatch_started",
                        event_age_ms=event_age_ms,
                    )
                selection_resolver = getattr(
                    self.astrbot_config_mgr,
                    "resolve_configuration_selection",
                    None,
                )
                selection = (
                    selection_resolver(event.unified_msg_origin)
                    if callable(selection_resolver)
                    else None
                )
                selection_is_usable = (
                    isinstance(getattr(selection, "config_id", None), str)
                    and isinstance(getattr(selection, "config_info", None), Mapping)
                    and isinstance(
                        getattr(
                            getattr(selection, "runtime_selection", None),
                            "adapter_binding_id",
                            None,
                        ),
                        str,
                    )
                )
                if selection_is_usable:
                    apply_unique_session(event, selection.runtime_config)
                    # Import at the live boundary to keep configuration selection
                    # independent from Interaction module initialization.
                    from astrbot.core.interaction.turn_state import (
                        set_interaction_turn_configuration_selection,
                    )

                    set_interaction_turn_configuration_selection(
                        event,
                        config_id=selection.config_id,
                        runtime_config=selection.runtime_config,
                        adapter_binding_id=selection.runtime_selection.adapter_binding_id,
                        provider_references=selection.runtime_selection.provider_references,
                    )
                    conf_id = selection.config_id
                    conf_name = selection.config_info.get("name") or conf_id
                else:
                    # Keep older test doubles and embedders working while they
                    # migrate from get_conf_info() to the typed selection API.
                    conf_info = self.astrbot_config_mgr.get_conf_info(
                        event.unified_msg_origin
                    )
                    conf_id = conf_info.get("id")
                    conf_name = conf_info.get("name") or conf_id
                self._print_event(event, conf_name)
                scheduler = self.pipeline_scheduler_mapping.get(conf_id)
                if not scheduler:
                    logger.error(
                        f"PipelineScheduler not found for id: {conf_id}, event ignored."
                    )
                    continue
                task = asyncio.create_task(scheduler.execute(event))
                self._pending_tasks.add(task)
                task.add_done_callback(self._on_task_done)
                slot_transferred = True
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "Event dispatch preparation failed: event_type=%s",
                    type(event).__name__,
                    exc_info=True,
                )
            finally:
                if not slot_transferred:
                    self._pipeline_slots.release()

    async def stop(self) -> None:
        """Stop accepting events and settle every dispatched pipeline task."""
        if self._stopped:
            return

        self._accepting_events = False
        pending_tasks = list(self._pending_tasks)
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        self._stopped = True

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._pending_tasks.discard(task)
        self._pipeline_slots.release()
        if task.cancelled():
            return
        if exc := task.exception():
            logger.error(
                "Pipeline task failed.",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    def _print_event(self, event: AstrMessageEvent, conf_name: str) -> None:
        """用于记录事件信息

        Args:
            event (AstrMessageEvent): 事件对象

        """
        safe_conf_name = sanitize_control_chars(str(conf_name))
        safe_platform_id = sanitize_control_chars(str(event.get_platform_id()))
        safe_platform_name = sanitize_control_chars(str(event.get_platform_name()))
        message_type = event.get_message_type()
        message_type_name = str(getattr(message_type, "name", message_type))
        try:
            component_count = len(event.get_messages())
        except (AttributeError, TypeError):
            component_count = 0
        logger.info(
            "[%s] [%s(%s)] Received message: type=%s components=%d",
            safe_conf_name,
            safe_platform_id,
            safe_platform_name,
            sanitize_control_chars(message_type_name),
            component_count,
        )
