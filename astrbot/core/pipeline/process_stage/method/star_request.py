"""本地 Agent 模式的 AstrBot 插件调用 Stage"""

import time
import traceback
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

from astrbot.core import logger
from astrbot.core.interaction.plugin_execution_runtime import (
    PluginModuleDrainingError,
)
from astrbot.core.message.message_event_result import MessageEventResult
from astrbot.core.platform.astr_message_event import (
    INTERACTION_OUTPUT_CONTROLLER_EXTRA_KEY,
    AstrMessageEvent,
)
from astrbot.core.plugin_runtime import plugin_owner_module_path
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.star import star_map
from astrbot.core.star.star_handler import (
    EventType,
    StarHandlerMetadata,
    star_handlers_registry,
)

from ...context import PipelineContext, call_event_hook, call_handler
from ...stage import Stage
from ..plugin_handler_executor import PluginHandlerControl


class StarRequestSubStage(Stage):
    async def initialize(self, ctx: PipelineContext) -> None:
        self.ctx = ctx

    async def process(
        self,
        event: AstrMessageEvent,
    ) -> AsyncGenerator[Any, PluginHandlerControl | None]:
        activated_handlers: list[StarHandlerMetadata] = event.get_extra(
            "activated_handlers",
        )
        handlers_parsed_params: dict[str, dict[str, Any]] = event.get_extra(
            "handlers_parsed_params",
        )
        if not handlers_parsed_params:
            handlers_parsed_params = {}

        for handler_index, handler in enumerate(activated_handlers):
            if event.is_stopped():
                break
            registered_handler = star_handlers_registry.get_handler_by_full_name(
                handler.handler_full_name,
            )
            if registered_handler is not handler:
                logger.warning(
                    "Skipping stale Plugin Handler before execution: "
                    "handler=%s module_path=%s",
                    handler.handler_full_name,
                    handler.handler_module_path,
                )
                continue
            params = handlers_parsed_params.get(handler.handler_full_name, {})
            owner_module_path = plugin_owner_module_path(handler.handler_module_path)
            md = star_map.get(owner_module_path)
            if not md or not md.activated:
                logger.warning(
                    "Skipping unavailable Plugin Handler: handler=%s "
                    "module_path=%s",
                    handler.handler_full_name,
                    handler.handler_module_path,
                )
                continue
            logger.debug(f"plugin -> {md.name} - {handler.handler_name}")
            handler_invocation_id = (
                f"{handler.handler_full_name}:{handler_index}"
            )
            invocation_started_at = time.time()
            invocation_started_perf = time.perf_counter()
            provider_request_count = 0
            artifact_count_before = self._plugin_artifact_count(event)
            runtime = getattr(
                getattr(self, "ctx", None),
                "plugin_execution_runtime",
                None,
            )
            handler_skipped = False
            event.set_extra(
                "_interaction_plugin_handler_skipped_reason",
                None,
            )
            event.set_extra(
                "_interaction_plugin_handler_invocation_id",
                handler_invocation_id,
            )
            event.set_extra(
                "_interaction_plugin_handler_module_path",
                handler.handler_module_path,
            )
            event.set_extra(
                "_interaction_plugin_handler_name",
                handler.handler_name,
            )
            try:
                def on_draining(exc: PluginModuleDrainingError) -> None:
                    nonlocal handler_skipped
                    handler_skipped = True
                    logger.warning(
                        "DIAG plugin.handler_skipped: platform_id=%s "
                        "session_id=%s reason=module_draining module_path=%s",
                        event.get_platform_id(),
                        event.session_id,
                        exc.module_path,
                    )
                    event.set_extra(
                        "_interaction_plugin_handler_skipped_reason",
                        "module_draining",
                    )

                def run_handler():
                    return call_handler(event, handler.handler, **params)

                wrapper = (
                    runtime.run_foreground(
                        (owner_module_path,),
                        run_handler,
                        on_draining=on_draining,
                    )
                    if runtime is not None and owner_module_path is not None
                    else run_handler()
                )
                async with aclosing(wrapper):
                    async for ret in wrapper:
                        if isinstance(ret, ProviderRequest):
                            provider_request_count += 1
                        control = yield ret
                        if control is PluginHandlerControl.CLOSE_CURRENT_INVOCATION:
                            break
                if handler_skipped:
                    continue
                if event.is_stopped():
                    break
                event.clear_result()  # 清除上一个 handler 的结果
            except Exception as e:
                traceback_text = traceback.format_exc()
                logger.error(traceback_text)
                logger.error(f"Star {handler.handler_full_name} handle error: {e}")

                await call_event_hook(
                    event,
                    EventType.OnPluginErrorEvent,
                    md.name,
                    handler.handler_name,
                    e,
                    traceback_text,
                )

                if not event.is_stopped() and event.is_at_or_wake_command:
                    ret = f":(\n\n在调用插件 {md.name} 的处理函数 {handler.handler_name} 时出现异常：{e}"
                    event.set_result(MessageEventResult().message(ret))
                    yield
                    event.clear_result()

                event.stop_event()
            finally:
                invocation_completed_at = time.time()
                artifact_count = max(
                    0,
                    self._plugin_artifact_count(event) - artifact_count_before,
                )
                logger.info(
                    "DIAG plugin.handler_invocation: platform_id=%s "
                    "session_id=%s origin_plugin_id=%s "
                    "origin_handler_name=%s handler_invocation_id=%s "
                    "started_at=%.6f completed_at=%.6f duration_ms=%.2f "
                    "provider_request_count=%d artifact_count=%d",
                    event.get_platform_id(),
                    event.session_id,
                    handler.handler_module_path,
                    handler.handler_name,
                    handler_invocation_id,
                    invocation_started_at,
                    invocation_completed_at,
                    (time.perf_counter() - invocation_started_perf) * 1000,
                    provider_request_count,
                    artifact_count,
                )
                event.set_extra(
                    "_interaction_plugin_handler_invocation_id",
                    None,
                )
                event.set_extra(
                    "_interaction_plugin_handler_module_path",
                    None,
                )
                event.set_extra(
                    "_interaction_plugin_handler_name",
                    None,
                )
                event.set_extra(
                    "_interaction_plugin_handler_skipped_reason",
                    None,
                )

    @staticmethod
    def _plugin_artifact_count(event: AstrMessageEvent) -> int:
        controller = event.get_extra(INTERACTION_OUTPUT_CONTROLLER_EXTRA_KEY)
        result = getattr(controller, "result", None)
        artifacts = getattr(result, "output_artifacts", None)
        return len(artifacts) if isinstance(artifacts, list) else 0
