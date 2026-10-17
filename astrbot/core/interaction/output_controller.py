from __future__ import annotations

import asyncio
import math
import random
import time
import traceback
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import aclosing
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from astrbot import logger
from astrbot.core import file_token_service, html_renderer
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.deadline import TurnDeadlineExceeded
from astrbot.core.message.components import Image, Json, Plain, Record
from astrbot.core.message.incremental_text import IncrementalTextPreparer
from astrbot.core.message.message_chain_delivery import (
    MessageChainDeliveryResult,
    deliver_message_chain,
)
from astrbot.core.message.message_chain_transforms import (
    replace_leading_plain_components,
    replace_plain_text_preserving_components,
)
from astrbot.core.message.message_event_result import MessageChain, ResultContentType
from astrbot.core.output_lifecycle import PreOutputProcessor, TurnDeliveryCoordinator
from astrbot.core.persona_stream_policy import is_olv_persona_stream
from astrbot.core.pipeline.context_utils import call_event_hook
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.platform_metadata import supports_personal_runtime
from astrbot.core.plugin_admission import CapabilityKind, capability_allowed
from astrbot.core.plugin_runtime import PLUGIN_RUNTIME_TARGET_PERSONAL_EXPRESSION
from astrbot.core.star.session_llm_manager import SessionServiceManager
from astrbot.core.star.star_handler import (
    PERSONA_SEGMENT_STREAM_SAFE_KEY,
    EventType,
    star_handlers_registry,
)
from astrbot.core.voice import (
    TTSState,
    VoiceServiceError,
    build_tts_delivery_metadata,
    synthesize_text,
)
from astrbot.core.voice.pcm_stream import PCMTextPart, synthesize_pcm_stream

from .assistant_artifacts import serialize_assistant_message_chain
from .config import load_interaction_agent_config
from .contributors import (
    POST_MATERIALIZATION_TIMEOUT_MAX_SECONDS,
    InteractionOutputDraft,
    InteractionResultContribution,
    InteractionResultPurpose,
    InteractionResultView,
    InteractionStreamView,
    merge_result_contributions,
)
from .core_bridge import get_interaction_route_decision
from .expression_agent import (
    PERSONA_RESULT_ID_METADATA_KEY,
    InteractionExpressionError,
    PersonaExpressionIntent,
    PersonaExpressionRequest,
    PersonaExpressionResult,
    PersonaExpressionSegment,
)
from .failure_policy import (
    InteractionFailureKind,
    should_emit_failure_reply,
)
from .output_modes import (
    CORE_OUTPUT_DELIVERY_EXTRA_KEY,
    OUTPUT_ORIGIN_EXTRA_KEY,
    CoreOutputDelivery,
    OutputOrigin,
    PluginOutputMode,
    temporary_output_origin,
)
from .personal_expression_guard import fingerprint_personal_expression
from .plugin_execution_types import (
    PLUGIN_OUTPUT_DELIVERY_IDENTITY_EXTRA_KEY,
)
from .runtime_config import merge_runtime_config
from .turn_state import (
    InteractionFinalOutputStatus,
    add_interaction_turn_stream_observation_task,
    append_interaction_turn_assistant_artifacts,
    append_interaction_turn_visible_output,
    begin_interaction_turn_delivery_receipt,
    begin_interaction_turn_plugin_output_transaction,
    build_interaction_turn_reply,
    consume_interaction_turn_finalization_pending,
    finish_interaction_turn_delivery_receipt,
    finish_interaction_turn_final_output,
    get_interaction_turn_assistant_artifacts,
    get_interaction_turn_config,
    get_interaction_turn_delivery_metadata,
    get_interaction_turn_finalized_material,
    get_interaction_turn_immediate_persona_segments,
    get_interaction_turn_immediate_reply,
    get_interaction_turn_plugin_output_transaction,
    get_interaction_turn_runtime_config,
    get_interaction_turn_state,
    get_interaction_turn_stream_interjections_emitted,
    get_interaction_turn_stream_observation_count,
    get_interaction_turn_stream_observation_tasks,
    get_interaction_turn_stream_pending_text,
    get_interaction_turn_stream_text,
    get_interaction_turn_tool_stage_observation_records,
    get_interaction_turn_tool_stage_observation_state,
    get_interaction_turn_visible_outputs,
    has_interaction_turn_core_streaming_result_consumed,
    has_interaction_turn_final_output_claimed,
    is_interaction_turn_completed,
    is_interaction_turn_core_streaming_active,
    is_interaction_turn_emitting_immediate_reply,
    is_interaction_turn_finalization_deferred,
    is_interaction_turn_pipeline_output_suppressed,
    mark_interaction_turn_cancelled,
    mark_interaction_turn_core_streaming_result_consumed,
    mark_interaction_turn_finalization_pending,
    mark_interaction_turn_personal_emitted,
    mark_interaction_turn_stream_interjection_emitted,
    next_interaction_turn_output_segment_id,
    next_interaction_turn_visible_message_id,
    record_interaction_turn_completion_failure,
    record_interaction_turn_failure,
    record_interaction_turn_finalization_failure,
    record_interaction_turn_stream_observation_failure,
    record_interaction_turn_visible_message_fingerprint,
    remove_interaction_turn_stream_observation_task,
    reserve_interaction_turn_final_output,
    resolve_interaction_turn_runtime_configuration,
    set_interaction_turn_core_streaming_active,
    set_interaction_turn_emitting_immediate_reply,
    set_interaction_turn_finalized_material,
    set_interaction_turn_immediate_persona_state,
    set_interaction_turn_immediate_reply,
    set_interaction_turn_pipeline_output_suppressed,
    set_interaction_turn_plugin_output_metadata,
    set_interaction_turn_plugin_output_transaction,
    set_interaction_turn_stream_observation_count,
    set_interaction_turn_tool_stage_observation_records,
    update_interaction_turn_stream_buffer,
)
from .types import (
    InteractionAgentConfig,
    InteractionRouteMode,
    PersonalResponseAction,
)
from .visible_message_fingerprint import fingerprint_visible_message

PLUGIN_OUTPUT_TRANSACTION_ACTIVE_EXTRA_KEY = (
    "_interaction_plugin_output_transaction_active"
)
PLUGIN_OUTPUT_TRANSACTION_START_EXTRA_KEY = (
    "_interaction_plugin_output_transaction_start"
)
PLUGIN_OUTPUT_TRANSACTION_ARTIFACTS_EXTRA_KEY = (
    "_interaction_plugin_output_transaction_assistant_artifacts"
)
TOOL_STAGE_OBSERVATION_TASKS_EXTRA_KEY = "_interaction_tool_stage_observation_tasks"
TOOL_STAGE_OBSERVATION_STATE_EXTRA_KEY = "_interaction_tool_stage_observation_state"
CORE_REPLY_FALLBACK_TEXT = "模型服务暂时不可用，请稍后再试。"


def _visible_message_ids_from_extras(extras: Mapping[str, Any]) -> list[str]:
    visible_message_id = str(extras.get("visible_message_id", "") or "").strip()
    return [visible_message_id] if visible_message_id else []


@dataclass(slots=True)
class StreamObservationDecision:
    should_interject: bool = False
    reply: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class OutboundMaterializationOptions:
    reply_prefix: str
    show_reasoning: bool
    tts_enabled: bool
    tts_trigger_probability: float
    tts_dual_output: bool
    tts_use_file_service: bool
    callback_api_base: str
    t2i_enabled: bool
    t2i_word_threshold: int
    t2i_use_network: bool
    t2i_active_template: str


@dataclass(frozen=True, slots=True)
class PersonaSegmentStreamOutcome:
    expression: PersonaExpressionResult | None
    emitted: bool
    status: str
    failure_reason: str | None = None


class InteractionOutputController:
    def __init__(
        self,
        *,
        plugin_context: Any | None = None,
        interaction_config: InteractionAgentConfig | None = None,
        platform_settings: dict[str, Any] | None = None,
        persist_callback: (Callable[[AstrMessageEvent], Awaitable[None]] | None) = None,
        visible_reply_renderer: (
            Callable[
                [AstrMessageEvent, PersonaExpressionRequest],
                Awaitable[PersonaExpressionResult],
            ]
            | None
        ) = None,
        lifecycle_callback: (
            Callable[[AstrMessageEvent, str, dict[str, Any] | None], Awaitable[None]]
            | None
        ) = None,
        pre_output_processor: PreOutputProcessor | None = None,
        delivery_coordinator: TurnDeliveryCoordinator | None = None,
    ) -> None:
        self.plugin_context = plugin_context
        self.interaction_config = interaction_config or InteractionAgentConfig()
        self.platform_settings = deepcopy(platform_settings or {})
        self._persist_callback = persist_callback
        self.visible_reply_renderer = visible_reply_renderer
        self.lifecycle_callback = lifecycle_callback
        self.pre_output_processor = pre_output_processor or PreOutputProcessor()
        self.delivery_coordinator = delivery_coordinator or TurnDeliveryCoordinator()

    def _resolve_delivery_platform_settings(self, event: AstrMessageEvent) -> dict:
        config = self._get_runtime_config(event)
        configured = (
            config.get("platform_settings") if isinstance(config, Mapping) else None
        )
        if isinstance(configured, Mapping):
            return deepcopy(dict(configured))
        return deepcopy(self.platform_settings)

    def _resolve_outbound_options(
        self, event: AstrMessageEvent
    ) -> OutboundMaterializationOptions:
        config = self._get_runtime_config(event)
        config = config if isinstance(config, Mapping) else {}
        provider = config.get("provider_settings", {})
        provider = provider if isinstance(provider, Mapping) else {}
        tts = config.get("provider_tts_settings", {})
        tts = tts if isinstance(tts, Mapping) else {}
        settings = config.get("platform_settings", {})
        settings = settings if isinstance(settings, Mapping) else {}
        strategy = str(config.get("t2i_strategy", "remote") or "")
        return OutboundMaterializationOptions(
            reply_prefix=str(
                settings.get(
                    "reply_prefix", self.platform_settings.get("reply_prefix", "")
                )
                or ""
            ),
            show_reasoning=bool(provider.get("display_reasoning_text", False)),
            tts_enabled=bool(tts.get("enable")),
            tts_trigger_probability=self._coerce_probability(
                tts.get("trigger_probability", 1.0)
            ),
            tts_dual_output=bool(tts.get("dual_output")),
            tts_use_file_service=bool(tts.get("use_file_service")),
            callback_api_base=str(config.get("callback_api_base", "")),
            t2i_enabled=bool(config.get("t2i", False)),
            t2i_word_threshold=self._coerce_t2i_word_threshold(
                config.get("t2i_word_threshold", 150)
            ),
            t2i_use_network=strategy == "remote",
            t2i_active_template=str(
                config.get("t2i_active_template", "base") or "base"
            ),
        )

    @staticmethod
    def _coerce_t2i_word_threshold(value: Any) -> int:
        try:
            return max(int(value), 50)
        except (TypeError, ValueError):
            return 150

    @staticmethod
    def _coerce_probability(value: Any) -> float:
        try:
            return max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            return 1.0

    def _get_runtime_config(self, event: AstrMessageEvent | None = None) -> Any:
        if event is not None:
            admitted_config = get_interaction_turn_runtime_config(event)
            if admitted_config is not None:
                return admitted_config
            event_config, _ = resolve_interaction_turn_runtime_configuration(event)
            if isinstance(event_config, Mapping):
                plugin_config = self._get_plugin_runtime_config(event)
                if isinstance(plugin_config, Mapping):
                    return merge_runtime_config(event_config, plugin_config)
                return event_config
        if self.plugin_context is None:
            return None
        plugin_config = self._get_plugin_runtime_config(event)
        if isinstance(plugin_config, Mapping):
            return plugin_config
        return None

    def _get_plugin_runtime_config(
        self,
        event: AstrMessageEvent | None = None,
    ) -> Any:
        if self.plugin_context is None:
            return None
        get_config = getattr(self.plugin_context, "get_config", None)
        if not callable(get_config):
            return None
        if event is not None:
            return get_config(umo=event.unified_msg_origin)
        return get_config()

    def _get_interaction_config(
        self,
        event: AstrMessageEvent | None = None,
    ) -> InteractionAgentConfig:
        if event is not None:
            interaction_config = get_interaction_turn_config(event)
            if interaction_config is not None:
                return interaction_config
        runtime_config = self._get_runtime_config(event)
        if isinstance(runtime_config, Mapping):
            return load_interaction_agent_config(runtime_config)
        return self.interaction_config

    def _get_config_value(
        self,
        key: str,
        default: Any = None,
        *,
        event: AstrMessageEvent | None = None,
    ) -> Any:
        cfg = self._get_runtime_config(event)
        if isinstance(cfg, dict):
            return cfg.get(key, default)
        if cfg is not None and hasattr(cfg, "get"):
            return cfg.get(key, default)
        return default

    def _get_provider_settings(
        self,
        event: AstrMessageEvent | None = None,
    ) -> dict[str, Any]:
        value = self._get_config_value("provider_settings", {}, event=event)
        return value if isinstance(value, dict) else {}

    def _get_tts_settings(
        self,
        event: AstrMessageEvent | None = None,
    ) -> dict[str, Any]:
        value = self._get_config_value("provider_tts_settings", {}, event=event)
        return value if isinstance(value, dict) else {}

    async def emit_failure_reply(
        self,
        reply: str,
        event: AstrMessageEvent,
        *,
        failure_kind: InteractionFailureKind = InteractionFailureKind.INTERNAL_FAILURE,
    ) -> bool:
        if not await reserve_interaction_turn_final_output(event):
            return False
        if not should_emit_failure_reply(event, failure_kind):
            await finish_interaction_turn_final_output(
                event,
                InteractionFinalOutputStatus.SUPPRESSED,
            )
            return False
        try:
            delivered = await self.emit_immediate_spoken_reply(
                PersonaExpressionResult(
                    speech=reply,
                    turn_action=PersonalResponseAction.REPLY,
                ),
                event,
            )
            if not delivered:
                await finish_interaction_turn_final_output(
                    event,
                    InteractionFinalOutputStatus.SUPPRESSED,
                )
                return False
            self._materialize_finalized_turn(event)
            await self._persist_interaction_turn(event)
        except BaseException:
            await finish_interaction_turn_final_output(
                event,
                InteractionFinalOutputStatus.FAILED,
            )
            raise
        await finish_interaction_turn_final_output(
            event,
            InteractionFinalOutputStatus.DELIVERED,
        )
        return True

    async def emit_immediate_spoken_reply(
        self,
        result: PersonaExpressionResult,
        event: AstrMessageEvent,
    ) -> bool:
        reply = (result.speech or "").strip()
        if not reply:
            return False
        set_interaction_turn_emitting_immediate_reply(event)
        try:
            with temporary_output_origin(event, OutputOrigin.CORE.value):
                return await self.capture_message_chain(
                    MessageChain(
                        [
                            Plain(reply),
                            *self._persona_tool_attachment_components(result),
                        ]
                    ),
                    event,
                    prepared_expression=result,
                )
        finally:
            set_interaction_turn_emitting_immediate_reply(event, False)

    async def emit_persona_segment_stream(
        self,
        event: AstrMessageEvent,
        *,
        producer: Callable[
            [Callable[[dict[str, Any]], Awaitable[None]], str],
            Awaitable[PersonaExpressionResult],
        ],
        on_header: Callable[[dict[str, Any]], Awaitable[bool | None]],
    ) -> PersonaSegmentStreamOutcome:
        self._ensure_persona_segment_stream_compatible(event)
        is_olv_segment_stream = (
            str(event.get_platform_name() or "").lower() == "olv_pet_adapter"
            and bool(
                event.get_extra(
                    "_interaction_persona_segment_stream_requested",
                    False,
                )
            )
        )
        options = self._resolve_outbound_options(event)
        use_tts = (
            options.tts_enabled
            and random.random() <= options.tts_trigger_probability
            and await SessionServiceManager.should_process_tts_request(event)
        )
        message_id = self._next_output_segment_id(event, "persona_stream")
        platform_extras = self.build_platform_output_extras(
            event,
            message_kind="immediate_reply",
            output_segment_id=message_id,
        )
        platform_extras["persona_stream"] = {
            "protocol": "segment_stream_v1",
            "status": "streaming",
            "segment_count": 0,
        }
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=128)
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[bool] = loop.create_future()
        state: dict[str, Any] = {
            "header": False,
            "finish": False,
            "delivery_failed": False,
            "current_index": None,
            "current_text": [],
            "next_delta_index": 0,
            "text_parts": [],
            "delivered_text_parts": [],
            "delivered_segment_parts": {},
            "segments": [],
            "raw_segments_by_index": {},
            "legacy_delivered_motion_segment_indexes": set(),
            "tts": [],
            "tts_attempted": False,
            "tts_failures": [],
            "result": None,
            "error": None,
            "status": "failed",
            "persona_result_id": None,
            "turn_action": None,
        }
        event.set_extra(
            "_interaction_persona_stream_motion_downlink_indexes",
            state["legacy_delivered_motion_segment_indexes"],
        )
        incremental_writer: Any | None = None
        incremental_pcm_queue: asyncio.Queue[Any] | None = None
        incremental_pcm_task: asyncio.Task | None = None
        incremental_pcm_error: BaseException | None = None
        incremental_pcm_aborted = False
        incremental_started_segments: dict[int, str] = {}
        incremental_preparers: dict[int, IncrementalTextPreparer] = {}
        incremental_closed_resources: dict[int, set[str]] = {}
        incremental_motion_futures: dict[int, asyncio.Future[bool]] = {}
        incremental_motion_tasks: list[asyncio.Task] = []

        async def enqueue_pcm(item: PCMTextPart | None) -> bool:
            """A dead audio consumer must never hold the text producer's queue."""
            consumer = incremental_pcm_task
            if (
                incremental_pcm_queue is None or consumer is None
                or consumer.done() or incremental_pcm_error is not None
            ):
                return False
            pending = asyncio.create_task(incremental_pcm_queue.put(item))
            try:
                done, _ = await asyncio.wait(
                    (pending, consumer), return_when=asyncio.FIRST_COMPLETED,
                )
                return pending in done and not consumer.done()
            finally:
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

        async def close_incremental_audio(
            segment_index: int, *, status: str = "completed", reason: str = "",
        ) -> None:
            closed = incremental_closed_resources.setdefault(segment_index, set())
            if incremental_writer is None or "audio" in closed:
                return
            try:
                await incremental_writer.end_stream(
                    "audio", segment_index, status=status, reason=reason,
                )
            except (RuntimeError, ValueError):
                if status == "completed":
                    raise
                return
            closed.add("audio")

        async def close_incremental_resources(
            *, status: str, reason: str
        ) -> None:
            if incremental_writer is None:
                return
            for segment_index in tuple(incremental_started_segments):
                closed = incremental_closed_resources.setdefault(segment_index, set())
                for resource in ("text", "audio", "motion"):
                    if resource in closed:
                        continue
                    try:
                        await incremental_writer.end_stream(
                            resource,
                            segment_index,
                            status=status,
                            reason=reason,
                        )
                    except (RuntimeError, ValueError):
                        continue
                    closed.add(resource)

        async def start_incremental_output(persona_result_id: str) -> None:
            nonlocal incremental_writer, incremental_pcm_queue, incremental_pcm_task
            if not is_olv_segment_stream:
                return
            open_output = getattr(event, "open_interaction_incremental_output", None)
            if not callable(open_output):
                return
            try:
                incremental_writer = await open_output(
                    persona_result_id=persona_result_id,
                )
            except Exception as exc:  # noqa: BLE001 - keep the legacy OLV path available.
                logger.warning(
                    "OLV incremental output unavailable; keeping segment fallback: "
                    "turn_id=%s reason=%s",
                    event.get_extra("_turn_id"),
                    exc,
                )
                incremental_writer = None
                return

            event.set_extra("_interaction_incremental_output_writer", incremental_writer)
            event.set_extra("_interaction_incremental_motion_started", {})
            event.set_extra("_interaction_incremental_motion_futures", {})
            event.set_extra("_interaction_incremental_motion_pending", {})
            logger.debug(
                "OLV incremental output selected: turn_id=%s tts_admitted=%s",
                event.get_extra("_turn_id"), use_tts,
            )
            if not use_tts:
                platform_extras["persona_stream"]["tts_status"] = "not_attempted"
                return
            incremental_pcm_queue = asyncio.Queue(maxsize=128)

            async def text_source():
                while True:
                    item = await incremental_pcm_queue.get()
                    if item is None:
                        return
                    yield item

            async def consume_pcm() -> None:
                nonlocal incremental_pcm_error
                state["tts_attempted"] = True
                try:
                    async with aclosing(synthesize_pcm_stream(
                        self.plugin_context, event, text_source(),
                    )) as frames:
                        async for frame in frames:
                            if frame.kind == "audio":
                                await incremental_writer.append_audio(
                                    frame.segment_index,
                                    frame.sample_offset,
                                    frame.audio,
                                )
                            elif frame.kind == "end":
                                await close_incremental_audio(frame.segment_index)
                    platform_extras["persona_stream"]["tts_status"] = "succeeded"
                except asyncio.CancelledError:
                    # Producer errors abort audio without turning an incomplete
                    # Persona result into a user cancellation.
                    if not incremental_pcm_aborted:
                        raise
                except BaseException as exc:  # noqa: BLE001 - text remains primary output.
                    incremental_pcm_error = exc
                    platform_extras["persona_stream"]["tts_status"] = "failed"
                    state["tts_failures"].append(getattr(exc, "reason", None) or "pcm_stream_failed")
                    logger.warning(
                        "OLV incremental PCM failed; text continues: turn_id=%s reason=%s",
                        event.get_extra("_turn_id"),
                        exc,
                    )
                    for segment_index in tuple(incremental_started_segments):
                        await close_incremental_audio(
                            segment_index, status="failed",
                            reason=(getattr(exc, "reason", None) or "pcm_stream_failed"),
                        )

            incremental_pcm_task = asyncio.create_task(
                consume_pcm(),
                name=f"persona-incremental-pcm:{event.get_extra('_turn_id')}",
            )

        async def publish_incremental_text(segment_index: int, text: str) -> None:
            if not text:
                return
            await incremental_writer.append_text(segment_index, text)
            state["delivered_text_parts"].append(text)
            state["delivered_segment_parts"].setdefault(segment_index, []).append(text)
            await enqueue_pcm(PCMTextPart(segment_index, text))

        async def emit_record(record: dict[str, Any]) -> None:
            record_type = record.get("type")
            if record_type == "header":
                if state["header"]:
                    raise InteractionExpressionError("persona_stream_duplicate_header")
                publish_stream = await on_header(record)
                state["header"] = True
                state["publish_stream"] = publish_stream is not False
                state["turn_action"] = PersonalResponseAction(
                    record["turn_action"]
                )
                state["persona_result_id"] = str(
                    record.get("persona_result_id") or ""
                ).strip() or None
                if state["persona_result_id"] and state["publish_stream"]:
                    await start_incremental_output(state["persona_result_id"])
                platform_extras["persona_stream"].update(
                    {"persona_result_id": state["persona_result_id"]}
                )
                if state["publish_stream"]:
                    await self._notify_lifecycle(
                        event,
                        "speaking",
                        {
                            "message_kind": "immediate_reply",
                            "protocol": "segment_stream_v1",
                        },
                    )
                if not ready.done():
                    ready.set_result(state["publish_stream"])
                return

            if not state["header"]:
                raise InteractionExpressionError("persona_stream_header_required")

            if record_type == "segment_start":
                if state["current_index"] is not None:
                    raise InteractionExpressionError("persona_stream_nested_segment")
                state["current_index"] = int(record["segment_index"])
                state["current_text"] = []
                state["next_delta_index"] = 0
                if incremental_writer is not None:
                    segment_message_id = self._next_output_segment_id(
                        event,
                        "persona_incremental",
                    )
                    incremental_started_segments[state["current_index"]] = segment_message_id
                    incremental_closed_resources[state["current_index"]] = set()
                    incremental_preparers[state["current_index"]] = (
                        self.pre_output_processor.create_incremental_text_preparer(event)
                    )
                    for resource in ("text", "audio", "motion"):
                        await incremental_writer.start_stream(
                            resource,
                            segment_index=state["current_index"],
                            message_id=segment_message_id,
                        )
                    if not use_tts:
                        await close_incremental_audio(state["current_index"])
                    elif incremental_pcm_error is not None:
                        await close_incremental_audio(
                            state["current_index"], status="failed",
                            reason=(getattr(incremental_pcm_error, "reason", None) or "pcm_stream_failed"),
                        )
                    motion_future = asyncio.get_running_loop().create_future()
                    incremental_motion_futures[state["current_index"]] = motion_future
                    event.get_extra("_interaction_incremental_motion_started")[
                        state["current_index"]
                    ] = True
                    event.get_extra("_interaction_incremental_motion_futures")[
                        state["current_index"]
                    ] = motion_future
                    flush_motion = getattr(
                        event,
                        "flush_interaction_incremental_motion",
                        None,
                    )
                    if callable(flush_motion):
                        await flush_motion(segment_index=state["current_index"])
                return

            if record_type == "speech_delta":
                segment_index = int(record["segment_index"])
                delta_index = int(record["delta_index"])
                text = str(record.get("text") or "")
                if (
                    segment_index != state["current_index"]
                    or delta_index != state["next_delta_index"]
                    or not text
                ):
                    raise InteractionExpressionError("persona_stream_invalid_delta_order")
                state["current_text"].append(text)
                state["text_parts"].append(text)
                state["next_delta_index"] += 1
                if incremental_writer is not None:
                    preparer = incremental_preparers[segment_index]
                    visible_delta = preparer.feed(text)
                    await publish_incremental_text(segment_index, visible_delta)
                if not is_olv_segment_stream:
                    await queue.put(
                        {
                            "type": "speech_delta",
                            "text": text,
                            "segment_index": segment_index,
                            "delta_index": delta_index,
                        }
                    )
                return

            if record_type == "segment_end":
                segment_index = int(record["segment_index"])
                segment = record.get("segment")
                raw_speech = record.get(
                    "raw_speech",
                    segment.get("speech") if isinstance(segment, dict) else None,
                )
                if (
                    not isinstance(segment, dict)
                    or segment_index != state["current_index"]
                    or not isinstance(raw_speech, str)
                    or "".join(state["current_text"]) != raw_speech
                ):
                    raise InteractionExpressionError("persona_stream_segment_mismatch")
                if is_olv_segment_stream:
                    if incremental_writer is not None:
                        preparer = incremental_preparers[segment_index]
                        accepted_text = preparer.text
                        finished_text = preparer.finish()
                        await publish_incremental_text(
                            segment_index, finished_text[len(accepted_text):],
                        )
                        segment = dict(segment)
                        segment["speech"] = finished_text
                        await incremental_writer.end_stream("text", segment_index)
                        incremental_closed_resources[segment_index].add("text")
                        await enqueue_pcm(PCMTextPart(segment_index, None))
                        async def finish_motion() -> None:
                            motion_future = incremental_motion_futures[segment_index]
                            try:
                                get_deadline = getattr(event, "get_interaction_incremental_motion_deadline", None)
                                deadline = get_deadline(segment_index=segment_index) if callable(get_deadline) else None
                                if motion_future.done():
                                    await asyncio.shield(motion_future)
                                elif deadline is None:
                                    # No admitted producer owns this optional resource.
                                    await incremental_writer.end_stream("motion", segment_index)
                                    motion_future.set_result(False)
                                else:
                                    await asyncio.wait_for(
                                        asyncio.shield(motion_future),
                                        timeout=max(0.0, deadline - loop.time()),
                                    )
                                incremental_closed_resources[segment_index].add("motion")
                            except asyncio.TimeoutError:
                                if "motion" not in incremental_closed_resources[segment_index]:
                                    try:
                                        await incremental_writer.end_stream(
                                            "motion",
                                            segment_index,
                                            status="failed",
                                            reason="motion_result_timeout",
                                        )
                                    except RuntimeError:
                                        # A producer may have closed the stream while
                                        # the timeout was waiting for the writer lock.
                                        if not motion_future.done():
                                            raise
                                    if not motion_future.done():
                                        motion_future.set_result(False)
                                    incremental_closed_resources[segment_index].add("motion")
                            except asyncio.CancelledError:
                                raise

                        incremental_motion_tasks.append(
                            asyncio.create_task(
                                finish_motion(),
                                name=f"persona-incremental-motion:{segment_index}",
                            )
                        )
                    else:
                        prepared_segment = await self._prepare_model_expression(
                            event,
                            MessageChain(
                                [Plain(str(segment.get("speech") or ""))],
                                type="persona_stream_segment",
                            ),
                            message_kind="immediate_reply",
                        )
                        if prepared_segment is None:
                            raise InteractionExpressionError(
                                "persona_stream_segment_preoutput_suppressed"
                            )
                        if (
                            len(prepared_segment.chain) != 1
                            or not isinstance(prepared_segment.chain[0], Plain)
                        ):
                            raise InteractionExpressionError(
                                "persona_stream_segment_output_transform_unsupported"
                            )
                        segment = dict(segment)
                        segment["speech"] = prepared_segment.chain[0].text
                state["segments"].append(segment)
                state["raw_segments_by_index"][segment_index] = raw_speech
                state["current_index"] = None
                state["current_text"] = []
                platform_extras["persona_stream"]["segment_count"] = len(
                    state["segments"]
                )
                # State-only segments still occupy a validated Persona index.
                # Deliver an audio-free placeholder rather than leaving a gap.
                if is_olv_segment_stream and incremental_writer is None:
                    await queue.put(
                        {
                            "type": "persona_segment",
                            "text": segment["speech"],
                            "segment_index": segment_index,
                        }
                    )
                elif incremental_writer is None and use_tts and str(segment.get("speech") or "").strip():
                    await queue.put(
                        {
                            "type": "tts_segment",
                            "text": segment["speech"],
                            "segment_index": segment_index,
                        }
                    )
                return

            if record_type == "finish":
                result = record.get("result")
                if (
                    not isinstance(result, PersonaExpressionResult)
                    or result.speech != "".join(state["text_parts"])
                    or state["current_index"] is not None
                ):
                    raise InteractionExpressionError("persona_stream_result_mismatch")
                state["finish"] = True
                state["result"] = result
                return

            raise InteractionExpressionError("persona_stream_unknown_event")

        async def produce() -> None:
            nonlocal incremental_pcm_aborted
            try:
                result = await producer(emit_record, message_id)
                if not state["header"]:
                    raise InteractionExpressionError("persona_stream_header_required")
                if not state["finish"] or result.speech != "".join(state["text_parts"]):
                    raise InteractionExpressionError("persona_stream_finish_required")
                state["result"] = result
                state["status"] = "completed"
                await enqueue_pcm(None)
            except asyncio.CancelledError as exc:
                state["error"] = state["error"] or exc
                state["status"] = "cancelled" if state["header"] else "failed"
                raise
            except Exception as exc:  # noqa: BLE001
                state["error"] = exc
                state["status"] = "incomplete" if state["header"] else "failed"
                if incremental_pcm_task is not None and not incremental_pcm_task.done():
                    incremental_pcm_aborted = True
                    incremental_pcm_task.cancel()
                    platform_extras["persona_stream"]["tts_status"] = "failed"
                await close_incremental_resources(
                    status="failed",
                    reason=(getattr(exc, "reason", None) or "persona_stream_failed"),
                )
            finally:
                if not ready.done():
                    if state["error"] is not None:
                        ready.set_exception(state["error"])
                    else:
                        ready.set_exception(
                            InteractionExpressionError(
                                "persona_stream_header_required"
                            )
                        )
                if (
                    state["header"] and state.get("publish_stream")
                    and not state["delivery_failed"] and incremental_writer is None
                ):
                    await queue.put(None)

        async def stream_messages() -> AsyncGenerator[MessageChain, None]:
            while True:
                item = await queue.get()
                if item is None:
                    stream_meta = platform_extras["persona_stream"]
                    stream_meta["status"] = state["status"]
                    stream_meta["segment_count"] = len(state["segments"])
                    stream_meta["tts_status"] = (
                        "failed"
                        if state["tts_failures"]
                        else "succeeded"
                        if state["tts"]
                        else "not_attempted"
                    )
                    if state["error"] is not None:
                        stream_meta["failure_reason"] = self._persona_stream_error_reason(
                            state["error"]
                        )
                    return
                if item["type"] == "speech_delta":
                    yield MessageChain(
                        [
                            Plain(
                                item["text"],
                                delivery_metadata={
                                    "stream_event": "speech_delta",
                                    "persona_result_id": state["persona_result_id"],
                                    "segment_index": item["segment_index"],
                                    "delta_index": item["delta_index"],
                                },
                            )
                        ],
                        type="persona_speech_delta",
                    )
                    state["delivered_text_parts"].append(item["text"])
                    state["delivered_segment_parts"].setdefault(
                        item["segment_index"], []
                    ).append(item["text"])
                    continue

                if (
                    is_olv_segment_stream
                    and item["type"] == "persona_segment"
                    and not str(item["text"] or "").strip()
                ):
                    segment_message_id = self._next_output_segment_id(
                        event,
                        "persona_motion",
                    )
                    yield MessageChain(
                        [
                            Plain(
                                "",
                                delivery_metadata={
                                    "message_id": segment_message_id,
                                    "persona_result_id": state["persona_result_id"],
                                    "persona_segment_index": item["segment_index"],
                                    "semantic_text": "",
                                },
                            )
                        ],
                        type="persona_stream_motion",
                    )
                    continue

                if item["type"] == "persona_segment" and not use_tts:
                    segment_message_id = self._next_output_segment_id(
                        event,
                        "persona_segment",
                    )
                    yield MessageChain(
                        [
                            Plain(
                                item["text"],
                                delivery_metadata={
                                    "message_id": segment_message_id,
                                    "persona_result_id": state["persona_result_id"],
                                    "persona_segment_index": item["segment_index"],
                                    "semantic_text": item["text"],
                                },
                            )
                        ],
                        type="persona_stream_segment",
                    )
                    continue

                try:
                    tts_message_id = self._next_output_segment_id(
                        event,
                        "persona_tts",
                    )
                    state["tts_attempted"] = True
                    result = await synthesize_text(
                        self.plugin_context,
                        event,
                        item["text"],
                        stage="interaction.outbound_tts",
                        use_file_service=options.tts_use_file_service,
                        callback_api_base=options.callback_api_base,
                        require_file_registration_config=True,
                        turn_id=str(event.get_extra("_turn_id", "") or ""),
                        message_id=tts_message_id,
                        parent_message_id=message_id,
                        persona_result_id=state["persona_result_id"],
                        persona_segment_index=item["segment_index"],
                    )
                    delivery_metadata = build_tts_delivery_metadata(
                        result.state,
                        audio_attachment="present",
                    )
                    delivery_metadata.update(
                        {
                            "stream_event": "tts_segment",
                            "persona_result_id": state["persona_result_id"],
                            "persona_segment_index": item["segment_index"],
                            "semantic_text": item["text"],
                        }
                    )
                    if is_olv_segment_stream:
                        output_segment_metadata = delivery_metadata.get(
                            "output_segment"
                        )
                        tts_metadata = (
                            output_segment_metadata.get("tts")
                            if isinstance(output_segment_metadata, dict)
                            else None
                        )
                        if isinstance(tts_metadata, dict):
                            tts_metadata.pop("persona_segment_count", None)
                    state["tts"].append(
                        {
                            "persona_segment_index": item["segment_index"],
                            "tts_request_id": result.state.tts_request_id,
                            "message_id": result.state.message_id,
                            "audio_available": bool(result.audio_path),
                        }
                    )
                    yield MessageChain(
                        [
                            Record(
                                file=result.delivered_file,
                                url=result.delivered_file,
                                text=result.text,
                                delivery_metadata=delivery_metadata,
                            )
                        ],
                        type="persona_stream_tts",
                    )
                except VoiceServiceError as exc:
                    state["tts_failures"].append(exc.reason)
                    logger.warning(
                        "Persona segment stream TTS failed: turn_id=%s segment_index=%s reason=%s",
                        event.get_extra("_turn_id"),
                        item["segment_index"],
                        exc.reason,
                    )
                    if is_olv_segment_stream:
                        delivery_metadata = (
                            build_tts_delivery_metadata(
                                exc.state,
                                audio_attachment="absent",
                            )
                            if exc.state is not None
                            else {
                                "output_segment": {
                                    "turn_id": str(
                                        event.get_extra("_turn_id", "") or ""
                                    ),
                                    "message_id": tts_message_id,
                                    "tts": {
                                        "status": "failed",
                                        "failure_code": exc.reason,
                                    },
                                },
                                "audio_attachment": "absent",
                            }
                        )
                        delivery_metadata.update(
                            {
                                "message_id": tts_message_id,
                                "stream_event": "tts_segment",
                                "persona_result_id": state["persona_result_id"],
                                "persona_segment_index": item["segment_index"],
                                "semantic_text": item["text"],
                                "failure_code": exc.reason,
                            }
                        )
                        output_segment_metadata = delivery_metadata.get(
                            "output_segment"
                        )
                        tts_metadata = (
                            output_segment_metadata.get("tts")
                            if isinstance(output_segment_metadata, dict)
                            else None
                        )
                        if isinstance(tts_metadata, dict):
                            tts_metadata.pop("persona_segment_count", None)
                        yield MessageChain(
                            [
                                Plain(
                                    item["text"],
                                    delivery_metadata=delivery_metadata,
                                )
                            ],
                            type="persona_stream_segment",
                        )

        async def deliver_olv_segments() -> None:
            olv_platform_extras = dict(platform_extras)
            olv_platform_extras.pop("persona_stream", None)

            async def message_parts():
                async for message in stream_messages():
                    if message.type == "persona_speech_delta" or not message.chain:
                        continue
                    component = message.chain[0]
                    metadata = getattr(component, "delivery_metadata", None)
                    if not isinstance(metadata, dict):
                        metadata = {}
                    output_segment = metadata.get("output_segment")
                    segment_message_id = str(
                        metadata.get("message_id")
                        or (
                            output_segment.get("message_id")
                            if isinstance(output_segment, dict)
                            else ""
                        )
                        or ""
                    ).strip()
                    if not segment_message_id:
                        raise InteractionExpressionError(
                            "persona_stream_segment_message_id_missing"
                        )
                    segment_index = metadata.get("persona_segment_index")
                    if isinstance(segment_index, bool) or not isinstance(
                        segment_index,
                        int,
                    ):
                        raise InteractionExpressionError(
                            "persona_stream_segment_index_missing"
                        )
                    semantic_text = str(metadata.get("semantic_text") or "")
                    part_extras = {
                        "message_id": segment_message_id,
                        "persona_result_id": state["persona_result_id"],
                        "persona_segment_index": segment_index,
                        "persona_raw_speech": state[
                            "raw_segments_by_index"
                        ].get(segment_index, semantic_text),
                        "persona_streaming": True,
                        "persona_incremental_delivery": True,
                        "persona_delivery_parent_message_id": message_id,
                        "semantic_text": semantic_text,
                    }
                    if message.type == "persona_stream_motion":
                        part_extras["persona_motion_only"] = True
                    yield message, part_extras, segment_message_id
                    if semantic_text:
                        state["delivered_text_parts"].append(semantic_text)
                        state["delivered_segment_parts"].setdefault(
                            segment_index,
                            [],
                        ).append(semantic_text)
                    elif message.type == "persona_stream_motion":
                        accepted_motion_indexes = event.get_extra(
                            "_interaction_persona_stream_motion_downlink_indexes",
                            set(),
                        )
                        if (
                            isinstance(accepted_motion_indexes, set)
                            and segment_index in accepted_motion_indexes
                        ):
                            state["legacy_delivered_motion_segment_indexes"].add(
                                segment_index
                            )

            await self._deliver_visible_message(
                event,
                MessageChain([Plain("")], type="persona_stream_olv"),
                message_kind="immediate_reply",
                platform_extras=olv_platform_extras,
                output_segment_id=message_id,
                record_send_operation=False,
                result_is_model_result=True,
                allow_segmented_reply=False,
                semantic_text="",
                message_parts=message_parts(),
            )

        def finalize_outcome() -> PersonaSegmentStreamOutcome:
            status = state["status"]
            if state["error"] is not None and status != "cancelled":
                event.set_extra(
                    "_interaction_persona_segment_stream_failure_reason",
                    self._persona_stream_error_reason(state["error"]),
                )
            event.set_extra("_interaction_persona_segment_stream_status", status)
            emitted_text = "".join(state["delivered_text_parts"])
            delivered_motion_indexes = set(
                state["legacy_delivered_motion_segment_indexes"]
            )
            delivered_motion_indexes.update(
                incremental_writer.delivered_motion_segment_indexes
                if incremental_writer is not None
                else frozenset()
            )
            motion_count = len(delivered_motion_indexes)
            delivered_motion_segments = [
                {
                    "segment_index": segment_index,
                    "actions": list(
                        state["segments"][segment_index].get("actions", [])
                    ),
                }
                for segment_index in sorted(delivered_motion_indexes)
                if segment_index < len(state["segments"])
            ]
            if emitted_text:
                set_interaction_turn_immediate_reply(event, emitted_text)
            if emitted_text or motion_count:
                mappings = []
                for segment_index, segment in enumerate(state["segments"]):
                    text_delivered = bool(segment.get("speech")) and "".join(
                        state["delivered_segment_parts"].get(segment_index, [])
                    ) == segment["speech"]
                    motion_delivered = segment_index in delivered_motion_indexes
                    if not text_delivered and not motion_delivered:
                        continue
                    delivered_segment = deepcopy(segment)
                    if not text_delivered:
                        delivered_segment["speech"] = ""
                    if not motion_delivered:
                        delivered_segment["actions"] = []
                    mappings.append(delivered_segment)
                set_interaction_turn_immediate_persona_state(
                    event,
                    segments=mappings,
                    actions=[
                        action
                        for segment in mappings
                        for action in segment.get("actions", [])
                    ],
                    thought="\n".join(
                        str(segment.get("thought") or "")
                        for segment in mappings
                        if str(segment.get("thought") or "")
                    ),
                    tendency=(mappings[-1].get("tendency", {}) if mappings else {}),
                )
                tts_status = platform_extras["persona_stream"].get(
                    "tts_status",
                    "cancelled" if status == "cancelled" else "not_attempted",
                )
                self._record_visible_output(
                    event,
                    message_kind="immediate_reply",
                    text=emitted_text,
                    message_id=message_id,
                    delivered_message_ids=_visible_message_ids_from_extras(
                        platform_extras
                    ),
                    metadata={
                        "delivered_as": "stream",
                        "delivered_motion_segment_count": motion_count,
                        "delivered_motion_segments": delivered_motion_segments,
                        "persona_result_id": state["persona_result_id"],
                        "persona_stream_status": status,
                        "tts_status": tts_status,
                        "tts": list(state["tts"]),
                    },
                )

            expression = state["result"]
            if status == "completed" and incremental_writer is not None and expression is not None:
                # The producer's raw result remains authoritative for protocol
                # checks. Publish a detached result describing delivered speech.
                expression = PersonaExpressionResult(
                    segments=[
                        PersonaExpressionSegment(**deepcopy(segment))
                        for segment in state["segments"]
                    ],
                    turn_action=expression.turn_action,
                    effect_calls=deepcopy(expression.effect_calls),
                    metadata=deepcopy(expression.metadata),
                )
            if status != "completed" and (emitted_text or motion_count):
                expression = PersonaExpressionResult(
                    speech=emitted_text,
                    turn_action=state["turn_action"],
                    metadata={
                        PERSONA_RESULT_ID_METADATA_KEY: state["persona_result_id"],
                        "interaction.persona_stream_status": status,
                    },
                )
            elif expression is not None:
                expression.metadata["interaction.persona_stream_status"] = status

            return PersonaSegmentStreamOutcome(
                expression=expression,
                emitted=bool(emitted_text or motion_count),
                status=status,
                failure_reason=(
                    self._persona_stream_error_reason(state["error"])
                    if state["error"] is not None and status != "cancelled"
                    else None
                ),
            )

        async def notify_stream_finished(
            outcome: PersonaSegmentStreamOutcome,
        ) -> None:
            # Before a header announces a result ID there is no published stream
            # for Adapter listeners to finalize. Middleware owns the Turn abort.
            if not state["persona_result_id"]:
                return
            hook_type = EventType.OnPersonaExpressionStreamFinishedEvent
            if not star_handlers_registry.get_handlers_by_event_type(
                hook_type,
                only_activated=False,
                plugins_name=None,
            ):
                return
            try:
                await call_event_hook(
                    event,
                    hook_type,
                    turn_id=str(event.get_extra("_turn_id", "") or ""),
                    persona_result_id=state["persona_result_id"],
                    message_id=message_id,
                    segment_count=len(state["segments"]),
                    status=outcome.status,
                    failure_reason=outcome.failure_reason,
                    execution_surface=PLUGIN_RUNTIME_TARGET_PERSONAL_EXPRESSION,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Persona segment stream finished hook failed: "
                    "turn_id=%s message_id=%s status=%s",
                    event.get_extra("_turn_id"),
                    message_id,
                    outcome.status,
                )

        producer_task = asyncio.create_task(produce())
        try:
            publish_stream = await ready
        except BaseException as exc:
            state["delivery_failed"] = True
            if not producer_task.done():
                producer_task.cancel()
            if incremental_pcm_task is not None and not incremental_pcm_task.done():
                incremental_pcm_task.cancel()
            for task in incremental_motion_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                producer_task,
                *([incremental_pcm_task] if incremental_pcm_task is not None else []),
                *incremental_motion_tasks,
                return_exceptions=True,
            )
            if isinstance(exc, asyncio.CancelledError):
                state["status"] = "cancelled"
                platform_extras["persona_stream"]["tts_status"] = (
                    "cancelled" if state["tts_attempted"] else "not_attempted"
                )
            await close_incremental_resources(
                status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                reason="persona_stream_cancelled" if isinstance(exc, asyncio.CancelledError) else "persona_stream_failed",
            )
            outcome = finalize_outcome()
            await notify_stream_finished(outcome)
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(state["error"], BaseException):
                raise state["error"]
            raise

        delivery_task = (
            asyncio.create_task(
                deliver_olv_segments()
                if is_olv_segment_stream
                else event.send_interaction_streaming(
                    stream_messages(),
                    platform_extras=platform_extras,
                    use_fallback=False,
                )
            )
            if publish_stream and incremental_writer is None
            else None
        )
        try:
            children = asyncio.gather(
                producer_task,
                *([delivery_task] if delivery_task is not None else []),
            )
            await asyncio.shield(children)
            if incremental_pcm_task is not None:
                await asyncio.shield(incremental_pcm_task)
            if incremental_motion_tasks:
                await asyncio.gather(*incremental_motion_tasks)
        except asyncio.CancelledError:
            state["status"] = "cancelled"
            platform_extras["persona_stream"]["status"] = "cancelled"
            platform_extras["persona_stream"]["tts_status"] = (
                "cancelled" if state["tts_attempted"] else "not_attempted"
            )
            state["delivery_failed"] = True
            if delivery_task is not None and not delivery_task.done():
                delivery_task.cancel()
            if not producer_task.done():
                producer_task.cancel()
            if incremental_pcm_task is not None and not incremental_pcm_task.done():
                incremental_pcm_task.cancel()
            for task in incremental_motion_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                producer_task,
                *([delivery_task] if delivery_task is not None else []),
                *([incremental_pcm_task] if incremental_pcm_task is not None else []),
                *incremental_motion_tasks,
                return_exceptions=True,
            )
            await close_incremental_resources(
                status="cancelled",
                reason="persona_stream_cancelled",
            )
            await asyncio.gather(children, return_exceptions=True)
            outcome = finalize_outcome()
            await notify_stream_finished(outcome)
            raise
        except Exception as exc:  # noqa: BLE001
            state["error"] = state["error"] or exc
            state["delivery_failed"] = True
            if not producer_task.done():
                producer_task.cancel()
            if incremental_pcm_task is not None and not incremental_pcm_task.done():
                incremental_pcm_task.cancel()
            for task in incremental_motion_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                producer_task,
                *([incremental_pcm_task] if incremental_pcm_task is not None else []),
                *incremental_motion_tasks,
                return_exceptions=True,
            )
            state["status"] = "incomplete"
            platform_extras["persona_stream"]["status"] = "incomplete"

        outcome = finalize_outcome()
        await notify_stream_finished(outcome)
        return outcome

    def _ensure_persona_segment_stream_compatible(
        self,
        event: AstrMessageEvent,
    ) -> None:
        platform_name = str(event.get_platform_name() or "").lower()
        is_olv_segment_stream = (
            platform_name == "olv_pet_adapter"
            and bool(
                event.get_extra(
                    "_interaction_persona_segment_stream_requested",
                    False,
                )
            )
        )
        if platform_name == "webchat":
            if not callable(getattr(event, "send_interaction_streaming", None)):
                raise InteractionExpressionError("persona_stream_output_unsupported")
        elif platform_name == "olv_pet_adapter" and bool(
            event.get_extra("_interaction_persona_segment_stream_requested", False)
        ):
            if not all(
                callable(getattr(event, method, None))
                for method in (
                    "send_message_with_extras",
                    "flush_visible_segment",
                    "complete_visible_message",
                )
            ):
                raise InteractionExpressionError("persona_stream_output_unsupported")
        else:
            raise InteractionExpressionError("persona_stream_platform_unsupported")
        options = self._resolve_outbound_options(event)
        if (
            options.reply_prefix
            or options.show_reasoning
            or options.t2i_enabled
        ):
            raise InteractionExpressionError("persona_stream_output_transform_unsupported")
        runtime_config = self._get_runtime_config(event)
        if not isinstance(runtime_config, Mapping):
            raise InteractionExpressionError(
                "persona_stream_runtime_config_unavailable"
            )
        safety = runtime_config.get("content_safety", {})
        if safety and not isinstance(safety, Mapping):
            raise InteractionExpressionError(
                "persona_stream_safety_config_invalid"
            )
        if (
            isinstance(safety, Mapping)
            and safety.get("also_use_in_response")
            and not is_olv_segment_stream
        ):
            raise InteractionExpressionError("persona_stream_safety_filter_unsupported")
        # OLV dispatch skips incompatible plugin capabilities for this invocation.
        # Other stream transports retain their existing admission contract.
        if is_olv_persona_stream(event):
            return
        decorating_handlers = star_handlers_registry.get_handlers_by_event_type(
            EventType.OnDecoratingResultEvent,
            only_activated=False,
            plugins_name=None,
        )
        if is_olv_segment_stream:
            decorating_handlers = [
                handler
                for handler in decorating_handlers
                if capability_allowed(
                    event,
                    kind=CapabilityKind.OUTPUT_HOOK,
                    owner_module_path=handler.handler_module_path,
                    item_name=handler.handler_name,
                )
            ]
        if decorating_handlers and (
            not is_olv_segment_stream
            or any(
                getattr(handler, "extras_configs", {}).get(
                    PERSONA_SEGMENT_STREAM_SAFE_KEY
                )
                is not True
                for handler in decorating_handlers
            )
        ):
            logger.warning(
                "Persona stream incompatible output Hooks: %s",
                [
                    handler.handler_full_name
                    for handler in decorating_handlers
                    if not is_olv_segment_stream
                    or handler.extras_configs.get(PERSONA_SEGMENT_STREAM_SAFE_KEY) is not True
                ],
            )
            raise InteractionExpressionError("persona_stream_output_hooks_unsupported")
        list_contributors = getattr(
            self.plugin_context,
            "list_interaction_result_contributors",
            None,
        )
        contributors = (
            list_contributors(event=event) if callable(list_contributors) else []
        )
        if contributors and (
            not is_olv_segment_stream
            or any(
                getattr(contributor, "persona_segment_stream_safe", False)
                is not True
                for contributor in contributors
            )
        ):
            raise InteractionExpressionError(
                "persona_stream_output_contributors_unsupported"
            )

    @staticmethod
    def _persona_stream_error_reason(error: BaseException) -> str:
        reason = getattr(error, "reason", None)
        return str(reason or type(error).__name__)

    async def capture_message_chain(
        self,
        message: MessageChain | None,
        event: AstrMessageEvent,
        *,
        prepared_expression: PersonaExpressionResult | None = None,
    ) -> bool:
        if message is None:
            await self.capture_visible_completion(event)
            return True

        is_immediate = is_interaction_turn_emitting_immediate_reply(event)
        outbound_kind = self._classify_outbound_message(event, message, is_immediate)
        if is_immediate:
            semantic_text = message.get_plain_text()
            message_id = self._next_output_segment_id(event, "immediate_reply")
            tts_segments = (
                prepared_expression.speech_segments
                if prepared_expression is not None
                else None
            )
            persona_result_id = (
                str(
                    prepared_expression.metadata.get(
                        PERSONA_RESULT_ID_METADATA_KEY
                    )
                    or ""
                ).strip()
                if prepared_expression is not None
                else None
            )
            contributions = await self._collect_result_contributions(
                event,
                core_result=None,
                final_result=semantic_text,
                phase="immediate",
                candidate_message_kind="immediate_reply",
                candidate_message_id=message_id,
                effect_calls=(
                    prepared_expression.effect_calls
                    if prepared_expression is not None
                    else ()
                ),
                segments=(
                    prepared_expression.segment_mappings
                    if prepared_expression is not None
                    else ()
                ),
                actions=(
                    prepared_expression.actions
                    if prepared_expression is not None
                    else ()
                ),
                thought=(
                    prepared_expression.thought
                    if prepared_expression is not None
                    else ""
                ),
                tendency=(
                    prepared_expression.tendency
                    if prepared_expression is not None
                    else {}
                ),
                turn_action=(
                    prepared_expression.turn_action.value
                    if prepared_expression is not None
                    and prepared_expression.turn_action is not None
                    else None
                ),
                persona_result_id=persona_result_id,
            )
            merged = merge_result_contributions(contributions)
            if merged.final_text_override is not None:
                text_override = merged.final_text_override
                if prepared_expression is not None:
                    projected_segments = self._project_persona_text_override(
                        event,
                        merged,
                        prepared_expression,
                        text_override,
                    )
                    if projected_segments is not None:
                        tts_segments = projected_segments
                        message = replace_plain_text_preserving_components(
                            message,
                            text_override,
                        )
                        semantic_text = message.get_plain_text()
                else:
                    message = replace_plain_text_preserving_components(
                        message,
                        text_override,
                    )
                    semantic_text = message.get_plain_text()
            message = await self._prepare_model_expression(
                event,
                message,
                message_kind="immediate_reply",
            )
            if message is None:
                return False
            semantic_text = message.get_plain_text()
            set_interaction_turn_immediate_reply(event, semantic_text)
            set_interaction_turn_immediate_persona_state(
                event,
                segments=(
                    prepared_expression.segment_mappings
                    if prepared_expression is not None
                    else ()
                ),
                actions=prepared_expression.actions if prepared_expression else (),
                thought=(prepared_expression.thought if prepared_expression else ""),
                tendency=prepared_expression.tendency if prepared_expression else {},
            )
            incremental = await self._deliver_ready_persona_segments(
                event, message, contribution=merged, phase="immediate",
                message_kind="immediate_reply", parent_message_id=message_id,
                persona_result_id=persona_result_id, tts_segments=tts_segments,
            )
            if incremental is not None:
                delivered_message_ids, materialization = incremental
                self._record_visible_output(
                    event, message_kind="immediate_reply", text=semantic_text,
                    message_id=message_id, delivered_message_ids=delivered_message_ids,
                    metadata=materialization,
                )
                return True
            (
                message,
                materialization,
            ) = await self.materialize_immediate_interaction_outbound_message(
                event,
                message,
                message_id=message_id,
                tts_segments=tts_segments,
                persona_result_id=persona_result_id,
            )
            platform_extras = self.build_platform_output_base_extras(
                event,
                result_contribution=merged,
            )
            await self._apply_post_materialization_contributions(
                event,
                merged,
                platform_extras,
                phase="immediate",
                parent_message_id=message_id,
                persona_result_id=persona_result_id,
                materialization=materialization,
            )
            delivered_message_ids = await self._deliver_visible_message(
                event,
                message,
                message_kind="immediate_reply",
                platform_extras=platform_extras,
                output_segment_id=message_id,
                record_send_operation=False,
                allow_segmented_reply=False,
                semantic_text=semantic_text,
            )
            self._record_visible_output(
                event,
                message_kind="immediate_reply",
                text=semantic_text,
                message_id=message_id,
                delivered_message_ids=delivered_message_ids,
                metadata=materialization,
            )
            return True

        if outbound_kind == "streaming_finish_marker":
            if not await reserve_interaction_turn_final_output(event):
                return False
            logger.warning(
                "Interaction streaming finish marker skipped after streaming delivery: platform_id=%s session_id=%s turn_id=%s final_length=%s",
                event.get_platform_id(),
                event.session_id,
                event.get_extra("_turn_id"),
                len(message.get_plain_text()),
            )
            try:
                self._materialize_finalized_turn(event)
                await self._persist_interaction_turn(event)
            except BaseException:
                await finish_interaction_turn_final_output(
                    event,
                    InteractionFinalOutputStatus.FAILED,
                )
                raise
            await finish_interaction_turn_final_output(
                event,
                InteractionFinalOutputStatus.DELIVERED,
            )
            return True

        if outbound_kind in {"core_progress", "passthrough"}:
            is_progress = outbound_kind == "core_progress"
            semantic_text = message.get_plain_text()
            message_id = self._next_output_segment_id(event, outbound_kind)
            (
                message,
                materialization,
            ) = await self.materialize_interaction_outbound_message(
                event,
                message,
                message_kind=outbound_kind,
                result_is_model_result=False,
                message_id=message_id,
            )
            delivered_message_ids = await self._deliver_visible_message(
                event,
                message,
                message_kind=outbound_kind,
                output_segment_id=message_id,
                allow_segmented_reply=True,
                semantic_text=semantic_text,
            )
            self._record_visible_output(
                event,
                message_kind=outbound_kind,
                text=semantic_text,
                message_id=message_id,
                delivered_message_ids=delivered_message_ids,
                metadata=materialization,
                memory_relevant=not is_progress,
            )
            if is_progress:
                return True
            self._materialize_finalized_turn(event)
            await self._persist_interaction_turn(event)
            return True

        if outbound_kind == "suppressed_duplicate_final":
            return False

        if not await reserve_interaction_turn_final_output(event):
            return False
        full_message = self._get_full_core_final_message(event, message)
        try:
            await self._deliver_core_reply(full_message, event)
        except BaseException:
            await finish_interaction_turn_final_output(
                event,
                InteractionFinalOutputStatus.FAILED,
            )
            raise
        final_status = (
            InteractionFinalOutputStatus.SUPPRESSED
            if is_interaction_turn_pipeline_output_suppressed(event)
            else InteractionFinalOutputStatus.DELIVERED
        )
        await finish_interaction_turn_final_output(event, final_status)
        return final_status is InteractionFinalOutputStatus.DELIVERED

    async def capture_plugin_output(
        self,
        message: MessageChain | None,
        event: AstrMessageEvent,
        *,
        mode: str = PluginOutputMode.DIRECT.value,
        finalize: bool = True,
        platform_extras: dict[str, Any] | None = None,
    ) -> bool:
        """Entry point for plugin-origin output through the Output Runtime.

        Two modes are supported:

        * **direct** — deliver the message as-is.
        * **persona** — extract plain text, pass it through the unified
          visible-reply persona layer, then deliver the rewritten text.

        ``finalize=False`` is for a visible progress update that will be
        followed by another output in the same interaction turn.
        """
        if message is None:
            return False

        set_interaction_turn_plugin_output_metadata(event, mode=mode)
        resolved_kind = "plugin_direct"
        resolved_mode = PluginOutputMode(mode)
        result_contribution = None
        message_id = None
        persona_result_id = None

        if resolved_mode == PluginOutputMode.PERSONA:
            plain = message.get_plain_text().strip()
            if plain:
                result = await self._render_visible_reply(
                    event,
                    PersonaExpressionRequest(
                        source_text=plain,
                        preserve_facts=True,
                        intent=PersonaExpressionIntent(
                            source="plugin_output",
                            phase="plugin",
                        ),
                    ),
                )
                persona_result_id = str(
                    result.metadata.get(PERSONA_RESULT_ID_METADATA_KEY) or ""
                ).strip() or None
                if result.effect_calls:
                    set_interaction_turn_plugin_output_metadata(
                        event,
                        effect_calls=list(result.effect_calls),
                    )
                message = replace_plain_text_preserving_components(
                    message,
                    result.speech,
                )
                tts_segments = result.speech_segments
                resolved_kind = "plugin_persona"
            else:
                tts_segments = None
                resolved_kind = "plugin_direct"
        else:
            tts_segments = None

        set_interaction_turn_plugin_output_metadata(event, kind=resolved_kind)
        if resolved_kind == "plugin_persona":
            message_id = self._next_output_segment_id(event, resolved_kind)
            contributions = await self._collect_result_contributions(
                event,
                core_result=None,
                final_result=result.speech,
                phase="final" if finalize else "immediate",
                candidate_message_kind=resolved_kind,
                candidate_message_id=message_id,
                effect_calls=result.effect_calls,
                segments=result.segment_mappings,
                actions=result.actions,
                thought=result.thought,
                tendency=result.tendency,
                turn_action=(
                    result.turn_action.value if result.turn_action is not None else None
                ),
                purpose="plugin_reply",
                persona_result_id=persona_result_id,
            )
            result_contribution = merge_result_contributions(contributions)
            if result_contribution.final_text_override is not None:
                projected_segments = self._project_persona_text_override(
                    event,
                    result_contribution,
                    result,
                    result_contribution.final_text_override,
                )
                if projected_segments is not None:
                    tts_segments = projected_segments
                    message = replace_plain_text_preserving_components(
                        message,
                        result_contribution.final_text_override,
                    )
            message = await self._prepare_model_expression(
                event,
                message,
                message_kind=resolved_kind,
            )
            if message is None:
                return False
        if message_id is None:
            message_id = self._next_output_segment_id(event, resolved_kind)
        semantic_text = message.get_plain_text()
        deferred_by_transaction = finalize and self._begin_plugin_output_transaction(
            event
        )
        if finalize and resolved_kind == "plugin_direct":
            self._record_plugin_assistant_artifacts(
                event,
                message,
                deferred_by_transaction=deferred_by_transaction,
            )

        (
            message,
            materialization,
        ) = await self.materialize_interaction_outbound_message(
            event,
            message,
            message_kind=resolved_kind,
            result_is_model_result=resolved_mode is PluginOutputMode.PERSONA,
            message_id=message_id,
            tts_segments=tts_segments,
            persona_result_id=persona_result_id,
        )
        resolved_platform_extras = platform_extras
        if result_contribution is not None:
            resolved_platform_extras = self.build_platform_output_base_extras(
                event,
                result_contribution=result_contribution,
            )
            resolved_platform_extras.update(platform_extras or {})
            await self._apply_post_materialization_contributions(
                event,
                result_contribution,
                resolved_platform_extras,
                phase="final" if finalize else "immediate",
                parent_message_id=message_id,
                persona_result_id=persona_result_id,
                materialization=materialization,
            )
        delivered_message_ids = await self._deliver_visible_message(
            event,
            message,
            message_kind=resolved_kind,
            platform_extras=resolved_platform_extras,
            output_segment_id=message_id,
            allow_segmented_reply=True,
            semantic_text=semantic_text,
        )
        self._record_visible_output(
            event,
            message_kind=resolved_kind,
            text=semantic_text,
            message_id=message_id,
            delivered_message_ids=delivered_message_ids,
            metadata=materialization,
            memory_relevant=finalize and not deferred_by_transaction,
        )
        if not finalize or deferred_by_transaction:
            return True
        self._materialize_finalized_turn(event)
        await self._persist_interaction_turn(event)
        return True

    async def capture_plugin_streaming(
        self,
        generator: AsyncGenerator[MessageChain, None],
        event: AstrMessageEvent,
        *,
        mode: str = PluginOutputMode.DIRECT.value,
        use_fallback: bool = False,
    ) -> bool:
        """Deliver plugin-origin streaming output without core stream semantics.

        Persona rewriting needs the complete semantic text before it can form one
        coherent reply. Therefore an explicitly persona-routed plugin stream is
        buffered and delivered through ``capture_plugin_output`` once, while
        direct plugin streams retain their regular low-latency delivery path.
        """
        resolved_mode = PluginOutputMode(mode)
        if resolved_mode is PluginOutputMode.PERSONA:
            stream_text_parts: list[str] = []
            async for chain in generator:
                chunk_text = self._extract_observable_stream_text(chain)
                if chunk_text:
                    stream_text_parts.append(chunk_text)

            text = "".join(stream_text_parts).strip()
            set_interaction_turn_plugin_output_metadata(
                event,
                mode=resolved_mode.value,
                kind="plugin_persona",
            )
            if text:
                return await self.capture_plugin_output(
                    MessageChain([Plain(text)]),
                    event,
                    mode=resolved_mode.value,
                    finalize=True,
                )
            return False

        resolved_kind = "plugin_direct"
        set_interaction_turn_plugin_output_metadata(
            event,
            mode=resolved_mode.value,
            kind=resolved_kind,
        )
        deferred_by_transaction = self._begin_plugin_output_transaction(event)
        stream_text_parts: list[str] = []
        message_id = self._next_output_segment_id(event, resolved_kind)

        async def _observe_plugin_stream() -> AsyncGenerator[MessageChain, None]:
            async for chain in generator:
                chunk_text = self._extract_observable_stream_text(chain)
                if chunk_text:
                    stream_text_parts.append(chunk_text)
                yield chain

        platform_extras = {
            **self.build_platform_output_extras(
                event,
                message_kind=resolved_kind,
                output_segment_id=message_id,
            ),
            "interaction_plugin_streaming": True,
            "plugin_output_mode": resolved_mode.value,
        }
        await self._notify_lifecycle(
            event,
            "speaking",
            {"message_kind": resolved_kind},
        )
        try:
            await event.send_interaction_streaming(
                _observe_plugin_stream(),
                platform_extras=platform_extras,
                use_fallback=use_fallback,
            )
        except Exception as exc:
            event.set_extra("_interaction_plugin_streaming_failed", True)
            event.set_extra("_interaction_plugin_streaming_failure_reason", str(exc))
            logger.error(
                "Interaction middleware plugin streaming delivery failed: platform_id=%s session_id=%s turn_id=%s error=%s",
                event.get_platform_id(),
                event.session_id,
                event.get_extra("_turn_id"),
                exc,
                exc_info=True,
            )
            raise
        text = "".join(stream_text_parts).strip()
        if not text:
            return True
        self._record_visible_output(
            event,
            message_kind=resolved_kind,
            text=text,
            message_id=message_id,
            delivered_message_ids=_visible_message_ids_from_extras(platform_extras),
            memory_relevant=not deferred_by_transaction,
        )
        if deferred_by_transaction:
            return True
        self._materialize_finalized_turn(event)
        await self._persist_interaction_turn(event)
        return True

    async def finalize_plugin_output_transaction(
        self,
        event: AstrMessageEvent,
        *,
        delegated_to_core: bool,
    ) -> None:
        """Commit pending plugin output only when the handler owns the final reply."""
        active, start, pending_artifacts = (
            get_interaction_turn_plugin_output_transaction(event)
        )
        set_interaction_turn_plugin_output_transaction(
            event,
            active=False,
            start=None,
            artifacts=[],
        )
        if not active or delegated_to_core or not isinstance(start, int):
            return

        if pending_artifacts:
            self._append_assistant_artifacts(event, pending_artifacts)
        turn_state = get_interaction_turn_state(event)
        has_visible_outputs = (
            turn_state is not None and start < len(turn_state.visible_outputs)
        )
        if not has_visible_outputs and not pending_artifacts:
            return

        if has_visible_outputs and turn_state is not None:
            final_index = len(turn_state.visible_outputs) - 1
            for index in range(start, len(turn_state.visible_outputs)):
                memory_relevant = index == final_index
                turn_state.visible_outputs[index]["memory_relevant"] = memory_relevant
                if index < len(turn_state.utterances):
                    turn_state.utterances[index].memory_relevant = memory_relevant

        self._materialize_finalized_turn(event)
        await self._persist_interaction_turn(event)

    @staticmethod
    def _begin_plugin_output_transaction(event: AstrMessageEvent) -> bool:
        start = begin_interaction_turn_plugin_output_transaction(event)
        if start is None:
            return False
        return True

    @staticmethod
    def _record_plugin_assistant_artifacts(
        event: AstrMessageEvent,
        message: MessageChain,
        *,
        deferred_by_transaction: bool,
    ) -> None:
        if not any(not isinstance(component, Plain) for component in message.chain):
            return
        artifacts = serialize_assistant_message_chain(message)
        if deferred_by_transaction:
            active, start, pending = get_interaction_turn_plugin_output_transaction(
                event
            )
            if active:
                set_interaction_turn_plugin_output_transaction(
                    event,
                    start=start,
                    artifacts=[*pending, *artifacts],
                )
            return
        InteractionOutputController._append_assistant_artifacts(event, artifacts)

    @staticmethod
    def _append_assistant_artifacts(
        event: AstrMessageEvent,
        artifacts: list[dict[str, Any]],
    ) -> None:
        append_interaction_turn_assistant_artifacts(event, artifacts)

    async def capture_visible_completion(
        self,
        event: AstrMessageEvent,
    ) -> None:
        complete_visible_turn = event.get_interaction_original_complete_visible_turn()
        if callable(complete_visible_turn):
            await complete_visible_turn()
        else:
            await event.complete_visible_turn()

    async def complete_visible_delivery(
        self,
        event: AstrMessageEvent,
    ) -> bool:
        return await self.delivery_coordinator.complete_visible_delivery(
            event,
            plugin_context=self.plugin_context,
            complete_visible_turn=self.capture_visible_completion,
            cancel_deferred_turn_finalization=self.cancel_deferred_turn_finalization,
            flush_deferred_turn_finalization=self.flush_deferred_turn_finalization,
            is_interaction_turn=True,
        )

    async def flush_deferred_turn_finalization(
        self,
        event: AstrMessageEvent,
    ) -> None:
        if consume_interaction_turn_finalization_pending(event):
            await self._persist_interaction_turn(event)

    async def cancel_deferred_turn_finalization(
        self,
        event: AstrMessageEvent,
        *,
        reason: str,
    ) -> None:
        consume_interaction_turn_finalization_pending(event)
        mark_interaction_turn_cancelled(event)
        await self._notify_lifecycle(
            event,
            "cancelled",
            {"reason": reason},
        )

    @staticmethod
    def _get_full_core_final_message(
        event: AstrMessageEvent,
        fallback: MessageChain,
    ) -> MessageChain:
        result = event.get_result()
        if result is None or not result.chain:
            return fallback
        return result.derive(list(result.chain))

    async def capture_streaming(
        self,
        generator: AsyncGenerator[MessageChain, None],
        event: AstrMessageEvent,
        use_fallback: bool = False,
    ) -> None:
        set_interaction_turn_core_streaming_active(event, True)
        observed_generator = self._wrap_core_stream(generator, event)
        message_id = self._next_output_segment_id(event, "core_stream")
        platform_extras = self.build_platform_output_extras(
            event,
            message_kind="core_stream",
            output_segment_id=message_id,
        )
        await self._notify_lifecycle(
            event,
            "speaking",
            {"message_kind": "core_stream"},
        )
        try:
            await event.send_interaction_streaming(
                observed_generator,
                platform_extras=platform_extras,
                use_fallback=use_fallback,
            )
        except Exception as exc:
            event.set_extra("_interaction_core_streaming_failed", True)
            event.set_extra("_interaction_core_streaming_failure_reason", str(exc))
            logger.error(
                "Interaction middleware streaming delivery failed: platform_id=%s session_id=%s turn_id=%s error=%s",
                event.get_platform_id(),
                event.session_id,
                event.get_extra("_turn_id"),
                exc,
                exc_info=True,
            )
            raise
        else:
            self._finalize_interaction_stream_output(
                event,
                message_id=message_id,
                delivered_message_ids=_visible_message_ids_from_extras(
                    platform_extras
                ),
            )
            await self._persist_interaction_turn(event)
        finally:
            set_interaction_turn_core_streaming_active(event, False)

    async def _wrap_core_stream(
        self,
        generator: AsyncGenerator[MessageChain, None],
        event: AstrMessageEvent,
    ) -> AsyncGenerator[MessageChain, None]:
        interaction_config = self._get_interaction_config(event)
        if not interaction_config.stream_interjection_enabled:
            async for chain in generator:
                chunk_text = self._extract_observable_stream_text(chain)
                if chunk_text:
                    self._update_interaction_turn_stream_buffer(
                        event, chunk_text=chunk_text, observe=False
                    )
                yield chain
            return

        min_chars = interaction_config.stream_observation_min_chars
        observation_state = self._build_stream_observation_state()
        async for chain in generator:
            chunk_text = self._extract_observable_stream_text(chain)
            if chunk_text:
                self._update_interaction_turn_stream_buffer(
                    event, chunk_text=chunk_text, observe=True
                )
                total_text = get_interaction_turn_stream_text(event)
                pending_text = get_interaction_turn_stream_pending_text(event)
                while len(pending_text) >= min_chars:
                    window_index = (
                        get_interaction_turn_stream_observation_count(event) + 1
                    )
                    observed_text = pending_text[:min_chars]
                    pending_text = pending_text[min_chars:]
                    update_interaction_turn_stream_buffer(
                        event,
                        total_text=total_text,
                        pending_text=pending_text,
                    )
                    self._schedule_interaction_stream_observation(
                        event,
                        observed_text=observed_text,
                        total_text=total_text,
                        window_index=window_index,
                        observation_state=observation_state,
                        chain_type=chain.type,
                        is_final=False,
                    )
            yield chain

        total_text = get_interaction_turn_stream_text(event)
        pending_text = get_interaction_turn_stream_pending_text(event)
        if pending_text:
            window_index = get_interaction_turn_stream_observation_count(event) + 1
            update_interaction_turn_stream_buffer(
                event,
                total_text=total_text,
                pending_text=pending_text,
            )
            set_interaction_turn_stream_observation_count(
                event,
                window_index,
            )
            await self._observe_interaction_stream_window(
                event,
                observed_text=pending_text,
                total_text=total_text,
                window_index=window_index,
                observation_state=observation_state,
                is_final=True,
            )
        await self.wait_for_stream_observations(event)
        update_interaction_turn_stream_buffer(
            event,
            total_text=total_text,
            pending_text="",
        )

    @staticmethod
    def _update_interaction_turn_stream_buffer(
        event: AstrMessageEvent,
        *,
        chunk_text: str,
        observe: bool,
    ) -> None:
        current_total = get_interaction_turn_stream_text(event)
        current_pending = (
            get_interaction_turn_stream_pending_text(event) if observe else ""
        )
        next_total = f"{current_total}{chunk_text}"
        next_pending = f"{current_pending}{chunk_text}" if observe else ""
        update_interaction_turn_stream_buffer(
            event,
            total_text=next_total,
            pending_text=next_pending,
        )

    def _finalize_interaction_stream_output(
        self,
        event: AstrMessageEvent,
        *,
        message_id: str,
        delivered_message_ids: list[str] | None = None,
    ) -> None:
        mark_interaction_turn_core_streaming_result_consumed(event)
        self._record_visible_output(
            event,
            message_kind="core_stream",
            text=get_interaction_turn_stream_text(event),
            message_id=message_id,
            delivered_message_ids=delivered_message_ids,
        )
        self._materialize_finalized_turn(event)

    @staticmethod
    def _materialize_finalized_turn(event: AstrMessageEvent) -> None:
        turn_id = str(event.get_extra("_turn_id", "") or "").strip()
        visible_outputs = get_interaction_turn_visible_outputs(event)
        assistant_artifacts = get_interaction_turn_assistant_artifacts(event)
        turn_state = get_interaction_turn_state(event)
        canonical_reply = build_interaction_turn_reply(
            visible_outputs,
            turn_id=turn_id,
            utterances=turn_state.utterances if turn_state is not None else None,
        )
        if turn_id and (canonical_reply or assistant_artifacts):
            set_interaction_turn_finalized_material(
                event,
                {
                    "turn_id": turn_id,
                    "user_text": (event.message_str or "").strip(),
                    "assistant_text": canonical_reply,
                    "assistant_artifacts": list(assistant_artifacts),
                    "visible_outputs": visible_outputs,
                    "history_source": "interaction.turn.material",
                },
            )

    @staticmethod
    def _build_stream_observation_state() -> dict[str, Any]:
        return {
            "emitted": 0,
            "lock": asyncio.Lock(),
        }

    def _schedule_interaction_stream_observation(
        self,
        event: AstrMessageEvent,
        *,
        observed_text: str,
        total_text: str,
        window_index: int,
        observation_state: dict[str, Any],
        chain_type: str | None,
        is_final: bool,
    ) -> None:
        set_interaction_turn_stream_observation_count(event, window_index)
        turn_state = get_interaction_turn_state(event)
        if turn_state is None:
            raise RuntimeError("Interaction stream observation requires turn state")
        task = turn_state.execution_scope.create_task(
            self._observe_interaction_stream_window(
                event,
                observed_text=observed_text,
                total_text=total_text,
                window_index=window_index,
                observation_state=observation_state,
                is_final=is_final,
            ),
            role="stream_observation",
            name=f"interaction_stream_observation_{event.get_platform_id()}_{window_index}",
        )
        add_interaction_turn_stream_observation_task(event, task)
        task.add_done_callback(
            lambda done_task: self._on_stream_observation_task_done(event, done_task)
        )

    async def _observe_interaction_stream_window(
        self,
        event: AstrMessageEvent,
        *,
        observed_text: str,
        total_text: str,
        window_index: int,
        observation_state: dict[str, Any],
        is_final: bool,
    ) -> None:
        decision = await self._decide_stream_interjection(
            event,
            observed_text=observed_text,
            total_text=total_text,
            window_index=window_index,
            is_final=is_final,
        )
        if not decision.should_interject or not decision.reply:
            return
        turn_state = get_interaction_turn_state(event)
        lock = turn_state.stream_interjection_lock if turn_state is not None else None
        if not isinstance(lock, asyncio.Lock):
            lock = observation_state.get("lock")
            if not isinstance(lock, asyncio.Lock):
                lock = asyncio.Lock()
                observation_state["lock"] = lock
        async with lock:
            if (
                event.is_stopped()
                or is_interaction_turn_completed(event)
                or has_interaction_turn_final_output_claimed(event)
            ):
                return
            if (
                get_interaction_turn_stream_interjections_emitted(event)
                >= self._get_interaction_config(event).stream_interjection_max_per_turn
            ):
                return
            delivered = await self._emit_stream_interjection(
                event,
                decision.reply,
                window_index=window_index,
                reason=decision.reason,
            )
            if delivered:
                observation_state["emitted"] = (
                    mark_interaction_turn_stream_interjection_emitted(event)
                )

    def _on_stream_observation_task_done(
        self,
        event: AstrMessageEvent,
        task: asyncio.Task,
    ) -> None:
        remove_interaction_turn_stream_observation_task(event, task)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            record_interaction_turn_stream_observation_failure(event, str(exc))
            self._record_stream_interjection_failure(
                event,
                reason="observation_task_failed",
                exception=exc,
                user_visible_action="continue_core_stream",
            )
            logger.error(
                "Interaction stream observation task failed: platform_id=%s session_id=%s turn_id=%s error=%s",
                event.get_platform_id(),
                event.session_id,
                event.get_extra("_turn_id"),
                exc,
                exc_info=True,
            )

    async def wait_for_stream_observations(self, event: AstrMessageEvent) -> None:
        tasks = get_interaction_turn_stream_observation_tasks(event)
        if not tasks:
            return
        await asyncio.gather(*list(tasks), return_exceptions=True)

    async def observe_core_tool_start(
        self,
        event: AstrMessageEvent,
        tool: FunctionTool[Any],
        tool_args: dict | None,
        _tool_result: Any = None,
    ) -> None:
        """Schedule a bounded status for a long-running research-style tool."""
        descriptor = self._describe_tool_stage(tool, tool_args)
        if descriptor is None or not self._tool_stage_observation_allowed(event):
            return
        turn_state = get_interaction_turn_state(event)
        if turn_state is None:
            return
        stage_state = self._get_tool_stage_observation_state(event, descriptor)
        if stage_state["running_attempt_started"] or stage_state[
            "completed_attempt_started"
        ]:
            return
        record: dict[str, Any] = {
            "tool": tool,
            "descriptor": descriptor,
            "emitted": False,
            "tool_name": str(getattr(tool, "name", "") or "").strip(),
            "batch_index": event.get_extra("_interaction_tool_batch_index"),
            "batch_size": event.get_extra("_interaction_tool_batch_size"),
        }
        records = get_interaction_turn_tool_stage_observation_records(event)
        records.append(record)
        set_interaction_turn_tool_stage_observation_records(event, records)

        async def emit_delayed_stage() -> None:
            await asyncio.sleep(
                self._get_interaction_config(event).tool_stage_observation_delay_seconds
            )
            if event.is_stopped() or is_interaction_turn_completed(event):
                return
            stage_state = self._get_tool_stage_observation_state(event, descriptor)
            if stage_state["running_attempt_started"] or stage_state[
                "completed_attempt_started"
            ]:
                return
            stage_state["running_attempt_started"] = True
            record["stage_attempt_started"] = True
            emitted = await self._observe_tool_stage(
                event,
                descriptor=descriptor,
                phase="running",
                tool_name=str(record.get("tool_name", "") or ""),
                batch_index=(
                    record.get("batch_index")
                    if isinstance(record.get("batch_index"), int)
                    else None
                ),
                batch_size=(
                    record.get("batch_size")
                    if isinstance(record.get("batch_size"), int)
                    else None
                ),
            )
            record["emitted"] = emitted
            stage_state["running_emitted"] = emitted

        record["task"] = turn_state.execution_scope.create_task(
            emit_delayed_stage(),
            role="tool_stage_observation",
            name=(
                "interaction_tool_stage_"
                f"{event.get_platform_id()}_{getattr(tool, 'name', 'tool')}"
            ),
        )

    async def observe_core_tool_end(
        self,
        event: AstrMessageEvent,
        tool: FunctionTool[Any],
        tool_args: dict | None,
        _tool_result: Any = None,
    ) -> None:
        """Emit one bounded completion update for the final call in a tool batch."""
        records = get_interaction_turn_tool_stage_observation_records(event)
        record = next(
            (item for item in reversed(records) if item.get("tool") is tool), None
        )
        if record is None:
            return
        records.remove(record)
        set_interaction_turn_tool_stage_observation_records(event, records)
        task = record.get("task")
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()
        if (
            record.get("emitted")
            or record.get("stage_attempt_started")
            or not self._tool_stage_observation_allowed(event)
        ):
            return
        batch_index = record.get("batch_index")
        batch_size = record.get("batch_size")
        if (
            isinstance(batch_index, int)
            and isinstance(batch_size, int)
            and batch_size > 1
            and batch_index < batch_size - 1
        ):
            # ToolLoopAgentRunner executes one model response's tool calls
            # serially. The final call in the batch owns the completion update.
            return
        if any(
            item.get("descriptor") == record.get("descriptor") for item in records
        ):
            return
        stage_state = self._get_tool_stage_observation_state(
            event,
            str(record["descriptor"]),
        )
        if stage_state["running_attempt_started"] or stage_state[
            "completed_attempt_started"
        ]:
            return
        stage_state["completed_attempt_started"] = True
        await self._observe_tool_stage(
            event,
            descriptor=str(record["descriptor"]),
            phase="completed",
            tool_name=str(record.get("tool_name", "") or ""),
            tool_result=_tool_result,
            batch_index=batch_index if isinstance(batch_index, int) else None,
            batch_size=batch_size if isinstance(batch_size, int) else None,
        )
        stage_state["completed_emitted"] = True

    @staticmethod
    def _get_tool_stage_observation_state(
        event: AstrMessageEvent,
        descriptor: str,
    ) -> dict[str, bool]:
        return get_interaction_turn_tool_stage_observation_state(event, descriptor)

    def _tool_stage_observation_allowed(self, event: AstrMessageEvent) -> bool:
        config = self._get_interaction_config(event)
        return (
            config.stream_interjection_enabled
            and config.stream_interjection_max_per_turn > 0
            and not event.is_stopped()
            and not is_interaction_turn_completed(event)
            and not has_interaction_turn_final_output_claimed(event)
        )

    @staticmethod
    def _describe_tool_stage(
        tool: FunctionTool[Any],
        tool_args: dict | None,
    ) -> str | None:
        mode = str(getattr(tool, "interaction_progress_mode", "auto") or "auto").lower()
        if mode in {"off", "disabled", "none"}:
            return None
        name = str(getattr(tool, "name", "") or "").strip()
        description = str(getattr(tool, "description", "") or "")
        del tool_args
        searchable = f"{name} {description}".lower()
        if mode == "auto":
            skip_terms = ("send_message", "transfer_to", "handoff", "list_available_agents")
            if any(term in searchable for term in skip_terms):
                return None
            research_terms = (
                "search",
                "web",
                "browser",
                "crawl",
                "extract",
                "query",
                "knowledge",
                "read_file",
                "fetch",
                "download",
                "搜索",
                "检索",
                "查询",
                "读取",
                "抓取",
            )
            if not any(term in searchable for term in research_terms):
                return None
        if any(term in searchable for term in ("search", "web", "browser", "crawl", "搜索", "检索", "抓取")):
            return "资料检索"
        if any(term in searchable for term in ("read", "extract", "fetch", "读取", "提取")):
            return "资料读取"
        return "信息查询"

    async def _observe_tool_stage(
        self,
        event: AstrMessageEvent,
        *,
        descriptor: str,
        phase: str,
        tool_name: str = "",
        tool_result: Any = None,
        batch_index: int | None = None,
        batch_size: int | None = None,
    ) -> bool:
        if not self._tool_stage_observation_allowed(event):
            return False
        result_summary = self._summarize_tool_result(tool_result)
        batch_summary = self._format_tool_batch_summary(
            batch_index=batch_index,
            batch_size=batch_size,
        )
        if phase == "running":
            source_text = (
                f"工具 {tool_name or descriptor} 正在处理当前任务。"
                "只简短告知用户仍在处理，不要猜测或转述尚未返回的工具结果。"
            )
        else:
            source_text = (
                f"工具 {tool_name or descriptor} 已返回当前回执。"
                "这不等于任务阶段或整个任务完成；请根据当前材料说明正在核对、整理或继续处理。"
            )
        progress_context = "\n".join(
            item
            for item in (
                f"工具名称：{tool_name}" if tool_name else "",
                f"工具类别：{descriptor}",
                batch_summary,
                f"当前工具回执：{result_summary}" if phase == "completed" else "",
            )
            if item
        )
        decision = await self._decide_stream_interjection(
            event,
            observed_text=source_text,
            total_text=get_interaction_turn_stream_text(event),
            window_index=get_interaction_turn_stream_observation_count(event) + 1,
            source_text=source_text,
            progress_context=progress_context,
            observation_kind="tool_stage",
            progress_stage=f"tool_{phase}",
            metadata={"tool_stage": descriptor, "tool_phase": phase},
        )
        if not decision.should_interject or not decision.reply:
            return False
        turn_state = get_interaction_turn_state(event)
        lock = turn_state.stream_interjection_lock if turn_state is not None else None
        if not isinstance(lock, asyncio.Lock):
            return False
        async with lock:
            if (
                event.is_stopped()
                or is_interaction_turn_completed(event)
                or has_interaction_turn_final_output_claimed(event)
            ):
                return False
            if (
                get_interaction_turn_stream_interjections_emitted(event)
                >= self._get_interaction_config(event).stream_interjection_max_per_turn
            ):
                return False
            window_index = (
                get_interaction_turn_stream_interjections_emitted(event) + 1
            )
            delivered = await self._emit_stream_interjection(
                event,
                decision.reply,
                window_index=window_index,
                reason=decision.reason or f"tool_{phase}",
            )
            if delivered:
                mark_interaction_turn_stream_interjection_emitted(event)
        return delivered

    async def _decide_stream_interjection(
        self,
        event: AstrMessageEvent,
        *,
        observed_text: str,
        total_text: str,
        window_index: int,
        is_final: bool = False,
        source_text: str = "",
        progress_context: str = "",
        observation_kind: str = "stream_text",
        progress_stage: str = "stream_text",
        metadata: Mapping[str, Any] | None = None,
    ) -> StreamObservationDecision:
        interaction_config = self._get_interaction_config(event)
        if not interaction_config.stream_interjection_enabled:
            return StreamObservationDecision(reason="disabled")

        decision = await self._collect_stream_interjection_from_plugins(
            event,
            observed_text=observed_text,
            total_text=total_text,
            window_index=window_index,
            is_final=is_final,
            observation_kind=observation_kind,
            metadata=metadata,
        )
        if decision is not None:
            if not decision.should_interject:
                return decision
            return await self._render_stream_interjection_via_persona(
                event,
                source_text=(decision.reply or source_text).strip(),
                progress_context=progress_context,
                observed_text=observed_text,
                total_text=total_text,
                window_index=window_index,
                is_final=is_final,
                reason=decision.reason or "plugin_decider",
                observation_kind=observation_kind,
                progress_stage=progress_stage,
            )
        return await self._render_stream_interjection_via_persona(
            event,
            source_text=source_text,
            progress_context=progress_context,
            observed_text=observed_text,
            total_text=total_text,
            window_index=window_index,
            is_final=is_final,
            observation_kind=observation_kind,
            progress_stage=progress_stage,
        )

    async def _render_stream_interjection_via_persona(
        self,
        event: AstrMessageEvent,
        *,
        source_text: str = "",
        progress_context: str = "",
        observed_text: str,
        total_text: str,
        window_index: int,
        is_final: bool,
        reason: str = "persona_runtime",
        observation_kind: str = "stream_text",
        progress_stage: str = "stream_text",
    ) -> StreamObservationDecision:
        if (
            event.is_stopped()
            or is_interaction_turn_completed(event)
            or has_interaction_turn_final_output_claimed(event)
        ):
            return StreamObservationDecision(reason="turn_output_closed")
        try:
            result = await self._render_visible_reply(
                event,
                PersonaExpressionRequest(
                    source_text=source_text,
                    progress_context=progress_context,
                    observed_text=observed_text,
                    total_text=total_text,
                    pending_text=get_interaction_turn_stream_pending_text(event),
                    progress_stage=progress_stage,
                    short_reply=True,
                    allow_empty=True,
                    intent=PersonaExpressionIntent(
                        kind="interjection",
                        source=(
                            "tool_observation"
                            if observation_kind == "tool_stage"
                            else "stream_observation"
                        ),
                        phase="interjection",
                    ),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Interaction stream interjection skipped: reason=persona_render_failed platform_id=%s session_id=%s turn_id=%s window_index=%s error=%s",
                event.get_platform_id(),
                event.session_id,
                event.get_extra("_turn_id"),
                window_index,
                exc,
                exc_info=True,
            )
            self._record_stream_interjection_failure(
                event,
                reason="persona_render_failed",
                exception=exc,
                user_visible_action="continue_core_stream",
            )
            return StreamObservationDecision(reason="persona_render_failed")

        if (
            event.is_stopped()
            or is_interaction_turn_completed(event)
            or has_interaction_turn_final_output_claimed(event)
        ):
            return StreamObservationDecision(reason="turn_output_closed")
        reply = result.speech.strip()
        return StreamObservationDecision(
            should_interject=bool(reply),
            reply=reply or None,
            reason=reason,
        )

    @staticmethod
    def _summarize_tool_result(tool_result: Any) -> str:
        if tool_result is None:
            return "工具没有提供可读的结构化回执；不要据此断言来源为空。"
        content = getattr(tool_result, "content", None)
        if not content:
            return "工具返回空内容。"
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
                continue
            resource = getattr(item, "resource", None)
            resource_text = getattr(resource, "text", None)
            if resource_text:
                parts.append(str(resource_text))
                continue
            parts.append(f"[{type(item).__name__}]")
        summary = "\n\n".join(part.strip() for part in parts if part.strip())
        if not summary:
            return "工具返回了非文本内容。"
        if bool(getattr(tool_result, "isError", False)):
            summary = f"工具明确报告错误：{summary}"
        return summary if len(summary) <= 1200 else f"{summary[:1197].rstrip()}..."

    @staticmethod
    def _format_tool_batch_summary(
        *,
        batch_index: int | None,
        batch_size: int | None,
    ) -> str:
        if (
            isinstance(batch_index, int)
            and isinstance(batch_size, int)
            and batch_size > 0
        ):
            return (
                f"本轮模型工具调用批次：第 {batch_index + 1} 个，共 {batch_size} 个；"
                + (
                    "这是本批最后一个工具回执。"
                    if batch_index == batch_size - 1
                    else "本批仍有后续工具调用。"
                )
            )
        return "工具调用批次信息不可用；不要推断任务步骤已经完成。"

    async def _collect_stream_interjection_from_plugins(
        self,
        event: AstrMessageEvent,
        *,
        observed_text: str,
        total_text: str,
        window_index: int,
        is_final: bool,
        observation_kind: str = "stream_text",
        metadata: Mapping[str, Any] | None = None,
    ) -> StreamObservationDecision | None:
        if self.plugin_context is None:
            return None
        list_deciders = getattr(
            self.plugin_context,
            "list_interaction_stream_deciders",
            None,
        )
        if not callable(list_deciders):
            return None
        stream_view = self._build_stream_view(
            event,
            observed_text=observed_text,
            total_text=total_text,
            window_index=window_index,
            is_final=is_final,
            observation_kind=observation_kind,
            metadata=metadata,
        ).copy_read_only()
        for decider in list_deciders(event=event):
            try:
                payload = await decider.decide(
                    event,
                    self.plugin_context,
                    stream_view,
                )
            except Exception as exc:  # noqa: BLE001
                self._record_stream_interjection_failure(
                    event,
                    reason="plugin_error",
                    exception=exc,
                    message=getattr(decider, "plugin_id", "<unknown>"),
                    user_visible_action="continue_core_stream",
                )
                failures = event.get_extra("_interaction_stream_decider_failures", [])
                if not isinstance(failures, list):
                    failures = []
                failures.append(
                    {
                        "plugin_id": getattr(decider, "plugin_id", "<unknown>"),
                        "error": str(exc),
                    }
                )
                event.set_extra("_interaction_stream_decider_failures", failures)
                logger.warning(
                    "Interaction stream decider failed: plugin_id=%s error=%s",
                    getattr(decider, "plugin_id", "<unknown>"),
                    exc,
                    exc_info=True,
                )
                continue
            decision = self._coerce_stream_interjection_decision(payload)
            if decision is not None:
                return decision
            self._record_stream_interjection_failure(
                event,
                reason="invalid_plugin_payload",
                message=getattr(decider, "plugin_id", "<unknown>"),
                user_visible_action="continue_core_stream",
            )
        return None

    @staticmethod
    def _record_stream_interjection_failure(
        event: AstrMessageEvent,
        *,
        reason: str,
        exception: BaseException | None = None,
        message: str | None = None,
        user_visible_action: str = "continue_core_stream",
    ) -> None:
        record_interaction_turn_failure(
            event,
            stage="stream_interjection",
            reason=reason,
            exception=exception,
            message=message,
            user_visible_action=user_visible_action,
        )

    @staticmethod
    def _build_stream_view(
        event: AstrMessageEvent,
        *,
        observed_text: str,
        total_text: str,
        window_index: int,
        is_final: bool,
        observation_kind: str = "stream_text",
        metadata: Mapping[str, Any] | None = None,
    ) -> InteractionStreamView:
        turn_state = get_interaction_turn_state(event)
        pending_text = (
            turn_state.stream_state.pending_text if turn_state is not None else ""
        )
        utterances = tuple(turn_state.utterances) if turn_state is not None else ()
        return InteractionStreamView(
            turn_id=str(event.get_extra("_turn_id", "") or ""),
            platform_id=event.get_platform_id(),
            session_id=event.unified_msg_origin,
            observed_text=observed_text,
            total_text=total_text,
            pending_text=pending_text,
            window_index=window_index,
            is_final=is_final,
            observation_kind=observation_kind,
            utterances=utterances,
            metadata={
                "stream_observation_count": (
                    turn_state.stream_state.observation_count
                    if turn_state is not None
                    else 0
                ),
                **dict(metadata or {}),
            },
        )

    async def _emit_stream_interjection(
        self,
        event: AstrMessageEvent,
        reply: str,
        *,
        window_index: int,
        reason: str,
    ) -> bool:
        text = reply.strip()
        if (
            not text
            or event.is_stopped()
            or is_interaction_turn_completed(event)
            or has_interaction_turn_final_output_claimed(event)
        ):
            return False
        message = MessageChain([Plain(text)])
        message.type = "interaction_stream_reply"
        message = await self._prepare_model_expression(
            event,
            message,
            message_kind="stream_interjection",
        )
        if message is None:
            return False
        text = message.get_plain_text()
        message_id = self._next_output_segment_id(event, "stream_interjection")
        (
            materialized_message,
            materialization,
        ) = await self.materialize_immediate_interaction_outbound_message(
            event, message, message_id=message_id
        )
        platform_extras = {
            "interaction_stream_reply": True,
            "stream_window_index": window_index,
        }
        delivered_message_ids = await self._deliver_visible_message(
            event,
            materialized_message,
            message_kind="stream_interjection",
            platform_extras=platform_extras,
            output_segment_id=message_id,
            record_send_operation=False,
            allow_segmented_reply=False,
            semantic_text=text,
        )
        self._record_visible_output(
            event,
            message_kind="stream_interjection",
            text=text,
            message_id=message_id,
            delivered_message_ids=delivered_message_ids,
            metadata=materialization,
            memory_relevant=False,
        )
        return True

    async def _render_visible_reply(
        self,
        event: AstrMessageEvent,
        request: PersonaExpressionRequest,
    ) -> PersonaExpressionResult:
        if self.visible_reply_renderer is None:
            del event
            raise RuntimeError("interaction visible_reply_renderer unavailable")
        return await self.visible_reply_renderer(event, request)

    async def deliver_core_execution_result(
        self,
        message: MessageChain,
        event: AstrMessageEvent,
    ) -> None:
        """Deliver executor-neutral final text through the Core-final path.

        The caller supplies material only. Persona rendering, contributions,
        TTS, platform delivery, history and visible completion remain owned by
        this controller and its established downstream services.
        """

        await self._deliver_core_reply(message, event)

    async def _deliver_core_reply(
        self,
        message: MessageChain,
        event: AstrMessageEvent,
    ) -> None:
        if (
            event.get_extra("_interaction_protocol_core_bypass_reason")
            == "ag99live_independent_motion"
        ):
            logger.info(
                "Skipping Persona Core-final rewrite for AG99live independent motion: "
                "turn_id=%s",
                event.get_extra("_turn_id"),
            )
            await self.deliver_raw_core_reply(message, event)
            return

        core_result_text = message.get_plain_text()
        try:
            result = await self._render_visible_reply(
                event,
                PersonaExpressionRequest.core_final(
                    core_result_text,
                    immediate_reply=get_interaction_turn_immediate_reply(event),
                ),
            )
        except TurnDeadlineExceeded as exc:
            await self._deliver_core_result_without_persona(
                message,
                event,
                stage=exc.stage,
                reason=exc.reason,
                exception=exc,
            )
            return
        except Exception as exc:  # noqa: BLE001
            await self._deliver_core_result_without_persona(
                message,
                event,
                stage="core_persona_render",
                reason=str(getattr(exc, "reason", "") or "exception"),
                exception=exc,
            )
            return
        await self.deliver_prepared_core_reply(message, result, event)

    async def _deliver_core_result_without_persona(
        self,
        message: MessageChain,
        event: AstrMessageEvent,
        *,
        stage: str,
        reason: str,
        exception: BaseException,
    ) -> None:
        """Finish the current output transaction without another Persona call."""
        failure_kind = (
            InteractionFailureKind.TURN_TIMEOUT
            if isinstance(exception, TurnDeadlineExceeded)
            else InteractionFailureKind.PERSONA_EXPRESSION_FAILED
        )
        record_interaction_turn_failure(
            event,
            stage=stage,
            reason=reason,
            failure_kind=failure_kind.value,
            exception=exception,
            user_visible_action=(
                "failure_reply_suppressed"
                if not message.chain
                and not should_emit_failure_reply(event, failure_kind)
                else "deliver_core_result_without_persona"
            ),
        )
        logger.warning(
            "Core result Persona rendering failed; delivering the existing Core "
            "result without another model call: turn_id=%s stage=%s reason=%s",
            event.get_extra("_turn_id"),
            stage,
            reason,
        )
        fallback_message = message
        if not fallback_message.chain:
            if not should_emit_failure_reply(
                event,
                failure_kind,
            ):
                set_interaction_turn_pipeline_output_suppressed(event)
                logger.warning(
                    "Core result fallback suppressed for group message: "
                    "turn_id=%s stage=%s",
                    event.get_extra("_turn_id"),
                    stage,
                )
                return
            fallback_message = message.derive([Plain(CORE_REPLY_FALLBACK_TEXT)])
        await self.deliver_raw_core_reply(fallback_message, event)

    async def deliver_prepared_core_reply(
        self,
        source_message: MessageChain,
        result: PersonaExpressionResult,
        event: AstrMessageEvent,
    ) -> None:
        immediate_reply = get_interaction_turn_immediate_reply(event)
        immediate_persona_segments = (
            get_interaction_turn_immediate_persona_segments(event) or ()
        )
        same_persona_state = tuple(result.segment_mappings) == tuple(
            immediate_persona_segments
        )
        if (
            immediate_reply
            and fingerprint_personal_expression(result.speech)
            == fingerprint_personal_expression(immediate_reply)
            and same_persona_state
            and not result.effect_calls
            and not result.metadata.get("persona_tool_attachments")
        ):
            logger.info(
                "Suppressing exact duplicate Core-final Persona reply: "
                "turn_id=%s message=%s",
                event.get_extra("_turn_id"),
                immediate_reply,
            )
            # The Core-final path normally records and persists the visible
            # output here. A suppressed duplicate still has to close the
            # interaction turn without emitting a second platform message.
            self._materialize_finalized_turn(event)
            await self._persist_interaction_turn(event)
            return
        final_message = source_message.derive(
            [
                Plain(result.speech),
                *self._persona_tool_attachment_components(result),
            ]
        )
        await self._deliver_core_final_message(
            source_message,
            final_message,
            event,
            effect_calls=result.effect_calls,
            persona_expression=result,
        )

    async def deliver_raw_core_reply(
        self,
        source_message: MessageChain,
        event: AstrMessageEvent,
    ) -> None:
        """Deliver an existing Core result without Persona rewriting it."""
        await self._deliver_core_final_message(
            source_message,
            source_message,
            event,
        )

    async def _deliver_core_final_message(
        self,
        source_message: MessageChain,
        final_message: MessageChain,
        event: AstrMessageEvent,
        *,
        effect_calls: Sequence[Any] = (),
        persona_expression: PersonaExpressionResult | None = None,
    ) -> None:
        core_result_text = source_message.get_plain_text()
        contributions = await self._collect_result_contributions(
            event,
            core_result=core_result_text,
            final_result=final_message.get_plain_text(),
            phase="final",
            candidate_message_kind="core_reply",
            candidate_message_id=(
                message_id := self._next_output_segment_id(event, "core_reply")
            ),
            effect_calls=effect_calls,
            segments=(
                persona_expression.segment_mappings
                if persona_expression is not None
                else ()
            ),
            actions=(persona_expression.actions if persona_expression else ()),
            thought=persona_expression.thought if persona_expression else "",
            tendency=(persona_expression.tendency if persona_expression else {}),
            turn_action=(
                persona_expression.turn_action.value
                if persona_expression is not None
                and persona_expression.turn_action is not None
                else None
            ),
            persona_result_id=(
                str(
                    persona_expression.metadata.get(
                        PERSONA_RESULT_ID_METADATA_KEY
                    )
                    or ""
                ).strip()
                if persona_expression is not None
                else None
            ),
        )
        merged = merge_result_contributions(contributions)
        tts_segments = (
            persona_expression.speech_segments
            if persona_expression is not None
            else None
        )
        if merged.final_text_override is not None:
            text_override = merged.final_text_override
            if persona_expression is not None:
                projected_segments = self._project_persona_text_override(
                    event,
                    merged,
                    persona_expression,
                    text_override,
                )
                if projected_segments is not None:
                    tts_segments = projected_segments
                    final_message = replace_plain_text_preserving_components(
                        final_message,
                        text_override,
                    )
            else:
                final_message = replace_plain_text_preserving_components(
                    final_message,
                    text_override,
                )

        final_message = await self._prepare_model_expression(
            event,
            final_message,
            message_kind="core_reply",
        )
        if final_message is None:
            set_interaction_turn_pipeline_output_suppressed(event)
            mark_interaction_turn_cancelled(event)
            await self._notify_lifecycle(
                event,
                "cancelled",
                {"reason": "pipeline_pre_output_suppressed"},
            )
            return

        platform_extras = self.build_platform_output_base_extras(
            event, result_contribution=merged
        )
        semantic_text = final_message.get_plain_text()
        persona_result_id = (
            str(
                persona_expression.metadata.get(PERSONA_RESULT_ID_METADATA_KEY)
                or ""
            ).strip()
            if persona_expression is not None
            else None
        )
        incremental = await self._deliver_ready_persona_segments(
            event, final_message, contribution=merged, phase="final",
            message_kind="core_reply", parent_message_id=message_id,
            persona_result_id=persona_result_id, tts_segments=tts_segments,
        )
        if incremental is not None:
            delivered_message_ids, materialization = incremental
            self._record_visible_output(
                event, message_kind="core_reply", text=semantic_text,
                message_id=message_id, delivered_message_ids=delivered_message_ids,
                metadata=materialization,
            )
            self._materialize_finalized_turn(event)
            await self._persist_interaction_turn(event)
            return
        (
            materialized_message,
            materialization,
        ) = await self.materialize_interaction_outbound_message(
            event,
            final_message,
            message_kind="core_reply",
            result_is_model_result=True,
            message_id=message_id,
            tts_segments=tts_segments,
            persona_result_id=persona_result_id,
        )
        await self._apply_post_materialization_contributions(
            event,
            merged,
            platform_extras,
            phase="final",
            parent_message_id=message_id,
            persona_result_id=persona_result_id,
            materialization=materialization,
        )
        delivered_message_ids = await self._deliver_visible_message(
            event,
            materialized_message,
            message_kind="core_reply",
            platform_extras=platform_extras,
            output_segment_id=message_id,
            result_is_model_result=True,
            allow_segmented_reply=True,
            semantic_text=semantic_text,
        )
        self._record_visible_output(
            event,
            message_kind="core_reply",
            text=semantic_text,
            message_id=message_id,
            delivered_message_ids=delivered_message_ids,
            metadata=materialization,
        )
        self._materialize_finalized_turn(event)
        await self._persist_interaction_turn(event)

    async def _prepare_model_expression(
        self,
        event: AstrMessageEvent,
        message: MessageChain,
        *,
        message_kind: str,
    ) -> MessageChain | None:
        prepared = await self.pre_output_processor.prepare_interaction_message(
            event,
            message,
            ResultContentType.LLM_RESULT,
        )
        if prepared.message is not None:
            return prepared.message
        reason = prepared.reason or "pre_output_suppressed"
        if message_kind == "immediate_reply":
            event.set_extra(
                "_interaction_immediate_output_suppressed_reason",
                reason,
            )
        logger.info(
            "Interaction model expression suppressed before materialization: "
            "turn_id=%s message_kind=%s reason=%s",
            event.get_extra("_turn_id"),
            message_kind,
            reason,
        )
        if prepared.stop_requested:
            event.stop_event()
        return None

    @staticmethod
    def _persona_tool_attachment_components(
        result: PersonaExpressionResult,
    ) -> list[Any]:
        attachments = result.metadata.get("persona_tool_attachments", [])
        if not isinstance(attachments, list):
            return []
        return [
            component
            for message in attachments
            if isinstance(message, MessageChain)
            for component in message.chain
            if not isinstance(component, Plain)
        ]

    @staticmethod
    def _is_already_delivered_streaming_finish(event: AstrMessageEvent) -> bool:
        if not has_interaction_turn_core_streaming_result_consumed(event):
            return False
        result = event.get_result()
        if result is None:
            return False
        return result.result_content_type == ResultContentType.STREAMING_FINISH

    @staticmethod
    def _extract_observable_stream_text(chain: MessageChain) -> str:
        if chain.type in {
            "break",
            "tool_call",
            "tool_call_result",
            "tool_direct_result",
            "agent_stats",
        }:
            return ""
        if chain.type == "audio_chunk":
            for component in chain.chain:
                if isinstance(component, Json):
                    text = component.data.get("text")
                    return str(text or "")
            return ""
        return chain.get_plain_text()

    @staticmethod
    def _coerce_stream_interjection_decision(
        payload: Any,
    ) -> StreamObservationDecision | None:
        if isinstance(payload, StreamObservationDecision):
            return payload
        if not isinstance(payload, dict):
            return None
        reply = payload.get("reply")
        if reply is None:
            reply = payload.get("immediate_spoken_reply")
        reply_text = str(reply).strip() if reply is not None else None
        return StreamObservationDecision(
            should_interject=bool(payload.get("should_interject", False)),
            reply=reply_text,
            reason=str(payload.get("reason", "") or "plugin_decision"),
        )

    @staticmethod
    def _project_persona_text_override(
        event: AstrMessageEvent,
        contribution: InteractionResultContribution,
        expression: PersonaExpressionResult,
        value: str,
    ) -> tuple[str, ...] | None:
        try:
            segment_texts = contribution.platform_extras.get(
                "persona_speech_segments"
            )
            if not isinstance(segment_texts, (list, tuple)):
                segment_texts = None
            return expression.speech_segments_for_text(
                value,
                segment_texts=segment_texts,
            )
        except InteractionExpressionError as exc:
            logger.warning(
                "Rejected whole-text override for segmented Persona output; "
                "preserving original speech and action bindings: turn_id=%s "
                "plugin_id=%s reason=%s",
                event.get_extra("_turn_id", "<missing>"),
                contribution.plugin_id,
                exc.reason,
            )
            contribution.final_text_override = None
            return None

    async def _collect_result_contributions(
        self,
        event: AstrMessageEvent,
        *,
        core_result: str | None,
        final_result: str | None,
        phase: str,
        candidate_message_kind: str,
        candidate_message_id: str,
        effect_calls: Sequence[Any] = (),
        segments: Sequence[Mapping[str, Any]] = (),
        actions: Sequence[str] = (),
        thought: str = "",
        tendency: Mapping[str, int] | None = None,
        turn_action: str | None = None,
        purpose: InteractionResultPurpose | None = None,
        persona_result_id: str | None = None,
    ) -> list[InteractionResultContribution]:
        if self.plugin_context is None:
            return []
        list_contributors = getattr(
            self.plugin_context,
            "list_interaction_result_contributors",
            None,
        )
        if not callable(list_contributors):
            return []

        route_decision = get_interaction_route_decision(event)
        route_payload = route_decision.to_dict() if route_decision is not None else None
        route_mode = (
            route_decision.route_mode.value if route_decision is not None else None
        )
        resolved_purpose = purpose or (
            "persona_reply" if phase == "immediate" else "core_reply"
        )
        output_source = (
            "plugin"
            if resolved_purpose == "plugin_reply"
            else "core"
            if phase == "final" and core_result
            else "interaction"
        )
        effect_calls = tuple(effect_calls)
        logger.debug(
            "DIAG result_view.effect_calls: platform_id=%s session_id=%s phase=%s payload_present=%s effect_calls=%s",
            event.get_platform_id(),
            event.session_id,
            phase,
            bool(effect_calls),
            [call.name for call in effect_calls],
        )
        output_text = (final_result or core_result or "").strip()
        output_draft = InteractionOutputDraft(
            turn_id=str(event.get_extra("_turn_id", "") or ""),
            message_id=candidate_message_id,
            source=output_source,
            route_mode=route_mode,
            phase=phase,
            text=output_text,
            semantic_text=output_text,
            message_kind=candidate_message_kind,
            latency_policy="fast" if phase == "immediate" else "normal",
            metadata={
                "is_immediate": phase == "immediate",
                "is_final": phase == "final",
                "text_stage": "candidate_pre_contribution",
                "text_may_change_by_legacy_override": True,
            },
        )

        view = InteractionResultView(
            turn_id=str(event.get_extra("_turn_id", "") or ""),
            platform_id=event.get_platform_id(),
            session_id=event.unified_msg_origin,
            purpose=resolved_purpose,
            route_decision=route_payload,
            output_draft=output_draft.to_mapping(),
            immediate_reply=get_interaction_turn_immediate_reply(event),
            core_result=core_result,
            final_result=final_result,
            effect_calls=effect_calls,
            segments=tuple(deepcopy(dict(segment)) for segment in segments),
            actions=tuple(actions),
            thought=thought,
            tendency=dict(tendency or {}),
            turn_action=turn_action,
            visible_outputs=self._snapshot_result_visible_outputs(event),
            utterances=self._snapshot_result_utterances(event),
            turn_material_snapshot=get_interaction_turn_finalized_material(event),
            final_candidate_material=self._build_result_final_candidate_material(
                event,
                final_result=final_result,
                message_kind=candidate_message_kind,
            ),
            finalized_turn_material=get_interaction_turn_finalized_material(event),
            metadata={
                "phase": phase,
                "purpose": resolved_purpose,
                "message_kind": candidate_message_kind,
                "is_immediate": phase == "immediate",
                "is_final": phase == "final",
                **(
                    {"persona_result_id": persona_result_id}
                    if persona_result_id
                    else {}
                ),
            },
        )
        contributions: list[InteractionResultContribution] = []
        contributors = list_contributors(event=event)
        timeout = self._get_interaction_config(event).contributor_timeout

        async def _collect_one(contributor) -> InteractionResultContribution | None:
            try:
                payload = await asyncio.wait_for(
                    contributor.collect(
                        event,
                        self.plugin_context,
                        view.copy_read_only(),
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                failures = event.get_extra(
                    "_interaction_result_contributor_failures", []
                )
                if not isinstance(failures, list):
                    failures = []
                failures.append(
                    {
                        "plugin_id": getattr(contributor, "plugin_id", "<unknown>"),
                        "error": f"timeout after {timeout:.2f}s",
                    }
                )
                event.set_extra("_interaction_result_contributor_failures", failures)
                logger.warning(
                    "Interaction result contributor timed out: plugin_id=%s timeout=%.2fs",
                    getattr(contributor, "plugin_id", "<unknown>"),
                    timeout,
                )
                return None
            except Exception as exc:  # noqa: BLE001
                failures = event.get_extra(
                    "_interaction_result_contributor_failures", []
                )
                if not isinstance(failures, list):
                    failures = []
                failures.append(
                    {
                        "plugin_id": getattr(contributor, "plugin_id", "<unknown>"),
                        "error": str(exc),
                    }
                )
                event.set_extra("_interaction_result_contributor_failures", failures)
                logger.warning(
                    "Interaction result contributor failed: plugin_id=%s error=%s",
                    getattr(contributor, "plugin_id", "<unknown>"),
                    exc,
                    exc_info=True,
                )
                return None
            if isinstance(payload, InteractionResultContribution):
                return payload
            return None

        results = await asyncio.gather(
            *[_collect_one(contributor) for contributor in contributors],
        )
        contributions.extend(
            result
            for result in results
            if isinstance(result, InteractionResultContribution)
        )
        contributions.sort(key=lambda item: (item.priority, item.plugin_id))
        return contributions

    async def _apply_post_materialization_contributions(
        self,
        event: AstrMessageEvent,
        result_contribution: InteractionResultContribution,
        platform_extras: dict[str, Any],
        *,
        phase: str,
        parent_message_id: str,
        persona_result_id: str | None,
        materialization: Mapping[str, Any],
    ) -> None:
        if not result_contribution.post_materialization:
            return

        timeout = self._get_interaction_config(event).contributor_timeout
        requested_timeout = result_contribution.post_materialization_timeout_seconds
        if isinstance(requested_timeout, (int, float)) and not isinstance(
            requested_timeout, bool
        ):
            try:
                timeout_request = float(requested_timeout)
            except (OverflowError, ValueError):
                timeout_request = 0.0
            if math.isfinite(timeout_request) and timeout_request > 0:
                timeout = max(
                    timeout,
                    min(
                        timeout_request,
                        POST_MATERIALIZATION_TIMEOUT_MAX_SECONDS,
                    ),
                )
        finalizer_deadline = materialization.get("finalizer_deadline")
        for finalize in result_contribution.post_materialization:
            remaining = (max(0.001, finalizer_deadline - time.monotonic())
                         if isinstance(finalizer_deadline, (int, float)) else timeout)
            try:
                payload = await asyncio.wait_for(
                    finalize(
                        event,
                        self.plugin_context,
                        turn_id=str(event.get_extra("_turn_id", "") or ""),
                        phase=phase,
                        parent_message_id=parent_message_id,
                        persona_result_id=persona_result_id,
                        materialization=deepcopy(materialization),
                    ),
                    timeout=min(timeout, remaining),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Interaction output finalizer timed out: plugin_id=%s timeout=%.2fs",
                    result_contribution.plugin_id,
                    timeout,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Interaction output finalizer failed: plugin_id=%s error=%s",
                    result_contribution.plugin_id,
                    exc,
                    exc_info=True,
                )
                continue
            if not isinstance(payload, InteractionResultContribution):
                continue
            platform_extras.update(payload.platform_extras)
            if payload.client_objects:
                existing_objects = platform_extras.get("client_objects")
                if not isinstance(existing_objects, list):
                    existing_objects = []
                platform_extras["client_objects"] = [
                    *existing_objects,
                    *payload.client_objects,
                ]
            if payload.metadata:
                existing_metadata = platform_extras.get("metadata")
                merged_metadata = (
                    dict(existing_metadata)
                    if isinstance(existing_metadata, Mapping)
                    else {}
                )
                merged_metadata.update(payload.metadata)
                platform_extras["metadata"] = merged_metadata

    @staticmethod
    def _build_result_final_candidate_material(
        event: AstrMessageEvent,
        *,
        final_result: str | None,
        message_kind: str,
    ) -> dict[str, Any] | None:
        turn_id = str(event.get_extra("_turn_id", "") or "").strip()
        assistant_text = (final_result or "").strip()
        if not turn_id or not assistant_text:
            return None
        visible_outputs = [
            *get_interaction_turn_visible_outputs(event),
            {
                "turn_id": turn_id,
                "kind": message_kind,
                "text": assistant_text,
                "memory_relevant": True,
            },
        ]
        return {
            "turn_id": turn_id,
            "user_text": (event.message_str or "").strip(),
            "assistant_text": assistant_text,
            "visible_outputs": visible_outputs,
            "history_source": "interaction.turn.final_candidate",
        }

    @staticmethod
    def _snapshot_result_visible_outputs(event: AstrMessageEvent) -> tuple[Any, ...]:
        turn_state = get_interaction_turn_state(event)
        if turn_state is not None:
            return tuple(dict(output) for output in turn_state.visible_outputs)
        return ()

    @staticmethod
    def _snapshot_result_utterances(event: AstrMessageEvent) -> tuple[Any, ...]:
        turn_state = get_interaction_turn_state(event)
        if turn_state is not None:
            return tuple(turn_state.utterances)
        return ()

    def build_platform_output_extras(
        self,
        event: AstrMessageEvent,
        *,
        message_kind: str,
        output_segment_id: str | None = None,
        result_contribution: InteractionResultContribution | None = None,
    ) -> dict[str, Any]:
        extras = self.build_platform_output_base_extras(
            event,
            result_contribution=result_contribution,
        )
        visible_message_id = self._next_visible_message_id(event, message_kind)
        extras.update(
            {
                "turn_id": event.get_extra("_turn_id"),
                "visible_message_id": visible_message_id,
                "message_kind": message_kind,
                "composite_message_id": output_segment_id or visible_message_id,
            }
        )
        return {key: value for key, value in extras.items() if value is not None}

    def build_platform_output_base_extras(
        self,
        event: AstrMessageEvent,
        *,
        result_contribution: InteractionResultContribution | None = None,
    ) -> dict[str, Any]:
        extras: dict[str, Any] = {}
        extras.update(get_interaction_turn_delivery_metadata(event))
        if result_contribution is not None:
            extras.update(result_contribution.platform_extras)
            if result_contribution.client_objects:
                extras["client_objects"] = list(result_contribution.client_objects)
            if result_contribution.metadata:
                extras["metadata"] = dict(result_contribution.metadata)
        return extras

    async def _deliver_ready_persona_segments(
        self,
        event: AstrMessageEvent,
        message: MessageChain,
        *,
        contribution: InteractionResultContribution,
        phase: str,
        message_kind: str,
        parent_message_id: str,
        persona_result_id: str | None,
        tts_segments: Sequence[str] | None,
    ) -> tuple[list[str], dict[str, Any]] | None:
        """Prepare bounded audio jobs and deliver each ordered ready segment.

        Platforms must explicitly implement flushing without closing the parent
        message. Whole-message finalizers and media transformations retain their
        existing single-delivery boundary.
        """
        if (
            not callable(getattr(event, "flush_visible_segment", None))
            or not contribution.supports_segment_materialization
            or not contribution.post_materialization
            or contribution.client_objects
            or not persona_result_id
            or tts_segments is None
            or len(message.chain) != 1
            or not isinstance(message.chain[0], Plain)
        ):
            return None
        options = self._resolve_outbound_options(event)
        if (
            not options.tts_enabled
            or options.tts_trigger_probability != 1.0
            or options.show_reasoning
            or (message.use_t2i_ if message.use_t2i_ is not None else options.t2i_enabled)
        ):
            return None
        if not await SessionServiceManager.should_process_tts_request(event):
            return None
        prefixed = self._apply_interaction_reply_prefix(event, message, options=options)
        resolved = self._resolve_interaction_tts_segments(prefixed, tts_segments)
        if resolved is None:
            return None
        _, inputs, segment_count = resolved
        if not inputs:
            return None
        started = time.monotonic()
        requested_timeout = contribution.post_materialization_timeout_seconds
        wait_budget = self._get_interaction_config(event).contributor_timeout
        if isinstance(requested_timeout, (int, float)) and not isinstance(requested_timeout, bool):
            if math.isfinite(requested_timeout) and requested_timeout > 0:
                wait_budget = max(wait_budget, min(requested_timeout, POST_MATERIALIZATION_TIMEOUT_MAX_SECONDS))
        deadline = started + wait_budget
        gate = asyncio.Semaphore(2)
        converted: list[dict[str, Any]] = []
        failures: list[str] = []
        jobs: list[tuple[int | None, str, str, asyncio.Task]] = []

        async def prepare(index, text, message_id):
            async with gate:
                try:
                    result = await synthesize_text(
                        self.plugin_context, event, text,
                        stage="interaction.outbound_tts",
                        use_file_service=options.tts_use_file_service,
                        callback_api_base=options.callback_api_base,
                        require_file_registration_config=True,
                        turn_id=str(event.get_extra("_turn_id", "") or ""),
                        message_id=message_id, parent_message_id=parent_message_id,
                        persona_result_id=persona_result_id,
                        persona_segment_index=index, persona_segment_count=segment_count,
                    )
                    component = Record(
                        file=result.delivered_file, url=result.delivered_file, text=result.text,
                        delivery_metadata=build_tts_delivery_metadata(result.state, audio_attachment="present"),
                    )
                    item = {
                        "tts_source_text": result.text, "tts_audio_path": result.audio_path,
                        "tts_audio_url": result.audio_url, "tts_provider_id": result.provider_id,
                        "tts_request_id": result.state.tts_request_id,
                        "message_id": result.state.message_id,
                        "parent_message_id": parent_message_id,
                        "persona_result_id": persona_result_id,
                        "persona_segment_index": index, "persona_segment_count": segment_count,
                    }
                except VoiceServiceError as exc:
                    self._record_outbound_materialization_failure(event, "tts", exc.reason)
                    if exc.state is None:
                        raise
                    component = Plain(text, delivery_metadata=build_tts_delivery_metadata(exc.state, audio_attachment="absent"))
                    item = {
                        "message_id": message_id, "parent_message_id": parent_message_id,
                        "persona_result_id": persona_result_id,
                        "persona_segment_index": index, "persona_segment_count": segment_count,
                        "tts_request_id": exc.state.tts_request_id, "tts_failed": True,
                        "failure_code": exc.state.failure_code or exc.reason,
                    }
                # Carry the Persona identity at the physical delivery boundary,
                # as the full-message TTS path does. The materialization ledger
                # alone is not forwarded to platform motion consumers.
                if index is not None:
                    component.delivery_metadata.update({
                        "persona_segment_index": index,
                        "persona_segment_count": segment_count,
                    })
                logger.debug(
                    "DIAG interaction.segment_tts_ready: turn_id=%s segment_index=%s elapsed_ms=%.2f",
                    event.get_extra("_turn_id"), index, (time.monotonic() - started) * 1000,
                )
                return component, item

        async def parts():
            for index, text in inputs:
                child_id = parent_message_id if not jobs else self._next_output_segment_id(event, "tts")
                task = asyncio.create_task(prepare(index, text, child_id), name=f"persona-tts:{index}")
                jobs.append((index, text, child_id, task))
            try:
                for position, (index, text, child_id, task) in enumerate(jobs):
                    component, item = await task
                    converted.append(item)
                    if item.get("tts_failed"):
                        failures.append(str(item["failure_code"]))
                    materialization = {
                        "tts": [item], "persona_segment_index": index,
                        "persona_last_output_segment": position == len(jobs) - 1,
                        "finalizer_deadline": deadline,
                    }
                    extras = self.build_platform_output_base_extras(event, result_contribution=contribution)
                    extras.pop("persona_speech_segments", None)
                    extras.update({
                        "semantic_text": text,
                        "persona_incremental_delivery": True,
                        "persona_delivery_parent_message_id": parent_message_id,
                    })
                    await self._apply_post_materialization_contributions(
                        event, contribution, extras, phase=phase,
                        parent_message_id=parent_message_id,
                        persona_result_id=persona_result_id, materialization=materialization,
                    )
                    yield message.derive([component]), extras, child_id
            finally:
                for _, _, _, task in jobs:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*(task for _, _, _, task in jobs), return_exceptions=True)

        delivered = await self._deliver_visible_message(
            event, message, message_kind=message_kind,
            platform_extras=self.build_platform_output_base_extras(event, result_contribution=contribution),
            output_segment_id=parent_message_id, record_send_operation=False,
            result_is_model_result=True, semantic_text=message.get_plain_text(),
            message_parts=parts(),
        )
        return delivered, {
            "message_kind": message_kind, "semantic_text": message.get_plain_text(),
            "delivered_as": "record", "tts": converted,
            "tts_status": "failed" if failures else "succeeded",
            "tts_failed": bool(failures), "segment_delivery": "ordered_ready",
        }

    async def materialize_interaction_outbound_message(
        self,
        event: AstrMessageEvent,
        message: MessageChain,
        *,
        message_kind: str,
        result_is_model_result: bool = False,
        message_id: str | None = None,
        tts_segments: Sequence[str] | None = None,
        persona_result_id: str | None = None,
    ) -> tuple[MessageChain, dict[str, Any]]:
        options = self._resolve_outbound_options(event)
        materialization: dict[str, Any] = {
            "message_kind": message_kind,
            "semantic_text": message.get_plain_text(),
            "delivered_as": "text",
            "tts_status": "not_attempted",
        }
        materialized = self._apply_interaction_reply_prefix(
            event, message, options=options
        )
        materialized, reasoning_metadata = self._apply_interaction_reasoning_display(
            event,
            materialized,
            options=options,
        )
        materialization.update(reasoning_metadata)
        try:
            materialized, tts_metadata = await self._apply_interaction_tts(
                event,
                materialized,
                options=options,
                result_is_model_result=result_is_model_result,
                message_id=message_id,
                tts_segments=tts_segments,
                persona_result_id=persona_result_id,
            )
        except VoiceServiceError as exc:
            logger.error(
                "Interaction TTS failed; emitting an audio-failed materialization.",
                exc_info=True,
            )
            tts_metadata = {
                "tts_failed": True,
                "failure_code": (
                    exc.state.failure_code if exc.state is not None else exc.reason
                ),
                "tts_status": "failed",
            }
            if exc.state is not None:
                materialized = self._attach_tts_failure_segment(
                    materialized,
                    exc.state,
                )
        materialization.update(tts_metadata)
        if tts_metadata.get("delivered_as") == "record":
            return materialized, materialization
        try:
            materialized, t2i_metadata = await self._apply_interaction_t2i(
                event,
                materialized,
                options=options,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Interaction t2i failed; sending text fallback.",
                exc_info=True,
            )
            t2i_metadata = {
                "t2i_failed": True,
                "t2i_fallback": "text",
                "t2i_failure_reason": str(exc),
            }
        materialization.update(t2i_metadata)
        return materialized, materialization

    async def materialize_immediate_interaction_outbound_message(
        self,
        event: AstrMessageEvent,
        message: MessageChain,
        *,
        message_id: str | None = None,
        tts_segments: Sequence[str] | None = None,
        persona_result_id: str | None = None,
    ) -> tuple[MessageChain, dict[str, Any]]:
        options = self._resolve_outbound_options(event)
        materialization: dict[str, Any] = {
            "message_kind": "immediate_reply",
            "semantic_text": message.get_plain_text(),
            "delivered_as": "text",
            "tts_status": "not_attempted",
        }
        materialized = self._apply_interaction_reply_prefix(
            event, message, options=options
        )
        try:
            materialized, tts_metadata = await self._apply_interaction_tts(
                event,
                materialized,
                options=options,
                result_is_model_result=True,
                message_id=message_id,
                tts_segments=tts_segments,
                persona_result_id=persona_result_id,
            )
        except VoiceServiceError as exc:
            logger.error(
                "Immediate interaction TTS failed; emitting an audio-failed segment.",
                exc_info=True,
            )
            tts_metadata = {
                "tts_failed": True,
                "failure_code": (
                    exc.state.failure_code if exc.state is not None else exc.reason
                ),
                "tts_status": "failed",
            }
            if exc.state is not None:
                materialized = self._attach_tts_failure_segment(
                    materialized,
                    exc.state,
                )
        materialization.update(tts_metadata)
        return materialized, materialization

    def _apply_interaction_reply_prefix(
        self,
        event: AstrMessageEvent,
        message: MessageChain,
        *,
        options: OutboundMaterializationOptions,
    ) -> MessageChain:
        del event
        if not options.reply_prefix:
            return message
        chain = list(message.chain)
        for index, comp in enumerate(chain):
            if isinstance(comp, Plain):
                chain[index] = Plain(options.reply_prefix + comp.text)
                return message.derive(chain)
        return message

    def _apply_interaction_reasoning_display(
        self,
        event: AstrMessageEvent,
        message: MessageChain,
        *,
        options: OutboundMaterializationOptions,
    ) -> tuple[MessageChain, dict[str, Any]]:
        reasoning_content = str(event.get_extra("_llm_reasoning_content") or "")
        if not options.show_reasoning or not reasoning_content.strip():
            return message, {}
        chain = list(message.chain)
        if event.get_platform_name() == "lark":
            chain.insert(
                0,
                Json(
                    data={
                        "type": "lark_collapsible_panel_reasoning",
                        "title": "Thinking",
                        "expanded": False,
                        "content": reasoning_content,
                    },
                ),
            )
        else:
            chain.insert(0, Plain(f"思考: {reasoning_content}\n"))
        return message.derive(chain), {"reasoning_displayed": True}

    async def _apply_interaction_tts(
        self,
        event: AstrMessageEvent,
        message: MessageChain,
        *,
        options: OutboundMaterializationOptions,
        result_is_model_result: bool,
        message_id: str | None = None,
        tts_segments: Sequence[str] | None = None,
        persona_result_id: str | None = None,
    ) -> tuple[MessageChain, dict[str, Any]]:
        should_try_tts = (
            options.tts_enabled
            and result_is_model_result
            and await SessionServiceManager.should_process_tts_request(event)
            and random.random() <= options.tts_trigger_probability
        )
        if not should_try_tts:
            return message, {}

        parent_message_id = str(message_id or "").strip()
        segmented_tts = tts_segments is not None
        segment_inputs: list[tuple[int | None, str]] | None = None
        segment_count = 0
        target_plain_index: int | None = None
        if tts_segments is not None:
            resolved_tts_segments = self._resolve_interaction_tts_segments(
                message,
                tts_segments,
            )
            if resolved_tts_segments is None:
                return message, {}
            target_plain_index, segment_inputs, segment_count = resolved_tts_segments

        new_chain = []
        converted: list[dict[str, Any]] = []
        for component_index, comp in enumerate(message.chain):
            if segment_inputs is not None:
                if component_index != target_plain_index:
                    new_chain.append(comp)
                    continue
                inputs = segment_inputs
            else:
                if not isinstance(comp, Plain) or len(comp.text) <= 1:
                    new_chain.append(comp)
                    continue
                inputs = [(None, comp.text)]

            for segment_index, segment_text in inputs:
                try:
                    current_message_id = message_id or self._next_output_segment_id(
                        event, "tts"
                    )
                    message_id = None
                    logger.debug(
                        "Interaction TTS request: text_length=%s segment_index=%s",
                        len(segment_text),
                        segment_index,
                    )
                    result = await synthesize_text(
                        self.plugin_context,
                        event,
                        segment_text,
                        stage="interaction.outbound_tts",
                        use_file_service=options.tts_use_file_service,
                        callback_api_base=options.callback_api_base,
                        require_file_registration_config=True,
                        turn_id=str(event.get_extra("_turn_id", "") or ""),
                        message_id=current_message_id,
                        parent_message_id=parent_message_id or current_message_id,
                        persona_result_id=persona_result_id,
                        persona_segment_index=segment_index,
                        persona_segment_count=(
                            segment_count if segment_index is not None else None
                        ),
                    )
                    logger.debug(
                        "Interaction TTS completed: audio_available=%s segment_index=%s",
                        bool(result.audio_path),
                        segment_index,
                    )
                    delivery_metadata = build_tts_delivery_metadata(
                        result.state,
                        audio_attachment="present",
                    )
                    if segment_index is not None:
                        delivery_metadata.update(
                            {
                                "persona_segment_index": segment_index,
                                "persona_segment_count": segment_count,
                            }
                        )
                    new_chain.append(
                        Record(
                            file=result.delivered_file,
                            url=result.delivered_file,
                            text=result.text,
                            delivery_metadata=delivery_metadata,
                        )
                    )
                    converted_item = {
                        "tts_source_text": result.text,
                        "tts_audio_path": result.audio_path,
                        "tts_audio_url": result.audio_url,
                        "tts_provider_id": result.provider_id,
                        "tts_request_id": result.state.tts_request_id,
                        "message_id": result.state.message_id,
                        "parent_message_id": result.state.parent_message_id,
                        "persona_result_id": result.state.persona_result_id,
                    }
                    if segment_index is not None:
                        converted_item.update(
                            {
                                "persona_segment_index": segment_index,
                                "persona_segment_count": segment_count,
                            }
                        )
                    converted.append(converted_item)
                    if options.tts_dual_output and not segmented_tts:
                        text_delivery_metadata = build_tts_delivery_metadata(
                            result.state,
                            audio_attachment="absent",
                        )
                        if segment_index is not None:
                            text_delivery_metadata.update(
                                {
                                    "persona_segment_index": segment_index,
                                    "persona_segment_count": segment_count,
                                }
                            )
                        new_chain.append(
                            Plain(
                                segment_text,
                                delivery_metadata=text_delivery_metadata,
                            )
                        )
                except VoiceServiceError as exc:
                    self._record_outbound_materialization_failure(
                        event,
                        "tts",
                        exc.reason,
                    )
                    logger.error(traceback.format_exc())
                    raise
            if options.tts_dual_output and segmented_tts:
                # Keep one integrated text component for text platforms;
                # only the audio records follow Persona speech boundaries.
                new_chain.append(Plain(comp.text))
        if not converted:
            return message.derive(new_chain), {}
        return (
            message.derive(new_chain),
            {
                "delivered_as": "record",
                "tts": converted,
                "tts_status": "succeeded",
            },
        )

    @staticmethod
    def _resolve_interaction_tts_segments(
        message: MessageChain,
        tts_segments: Sequence[str],
    ) -> tuple[int, list[tuple[int | None, str]], int] | None:
        """Keep Persona speech boundaries while honoring visible text rewrites.

        The normal path has one Plain component whose text is the concatenation
        of all Persona segment speech. Text added around that speech is assigned
        to the first or last segment. If a later hook replaces the text, spread
        the final text over the existing segment boundaries so TTS never reads
        stale speech or silently collapses a segmented Persona result.
        """

        segment_texts = [str(text or "") for text in tts_segments]
        if not any(text.strip() for text in segment_texts):
            return None
        joined_text = "".join(segment_texts)
        candidates = [
            (index, component)
            for index, component in enumerate(message.chain)
            if isinstance(component, Plain) and component.text.strip()
        ]
        if not candidates:
            return None
        for index, component in candidates:
            if component.text == joined_text:
                projected = segment_texts
                break
            text_offset = component.text.find(joined_text)
            if text_offset >= 0:
                prefix = component.text[:text_offset]
                suffix = component.text[text_offset + len(joined_text) :]
                projected = list(segment_texts)
                projected[0] = prefix + projected[0]
                projected[-1] = projected[-1] + suffix
                break
        else:
            # A decorating hook may rewrite the speech after the model result.
            # Use the last Plain component, which is the speech component in
            # the interaction paths that also contain reasoning text.
            index, component = candidates[-1]
            original_total = sum(len(text) for text in segment_texts)
            if original_total <= 0:
                projected = [component.text] + ["" for _ in segment_texts[1:]]
            else:
                projected = []
                offset = 0
                for segment_index, text in enumerate(segment_texts):
                    if segment_index == len(segment_texts) - 1:
                        projected.append(component.text[offset:])
                        break
                    target_length = round(
                        len(component.text) * len(text) / original_total
                    )
                    target_length = max(
                        0,
                        min(target_length, len(component.text) - offset),
                    )
                    projected.append(component.text[offset : offset + target_length])
                    offset += target_length
        return index, [
            (segment_index, text)
            for segment_index, text in enumerate(projected)
            if text.strip()
        ], len(projected)

    @staticmethod
    def _attach_tts_failure_segment(
        message: MessageChain,
        state: TTSState,
    ) -> MessageChain:
        chain = list(message.chain)
        for index, component in enumerate(chain):
            if isinstance(component, Plain) and len(component.text) > 1:
                chain[index] = Plain(
                    component.text,
                    delivery_metadata=build_tts_delivery_metadata(
                        state,
                        audio_attachment="absent",
                    ),
                )
                break
        return message.derive(chain)

    async def _apply_interaction_t2i(
        self,
        event: AstrMessageEvent,
        message: MessageChain,
        *,
        options: OutboundMaterializationOptions,
    ) -> tuple[MessageChain, dict[str, Any]]:
        use_t2i = (
            message.use_t2i_ if message.use_t2i_ is not None else options.t2i_enabled
        )
        if not use_t2i:
            return message, {}
        parts: list[str] = []
        for comp in message.chain:
            if isinstance(comp, Plain):
                parts.append("\n\n" + comp.text)
            else:
                break
        plain_str = "".join(parts)
        if not plain_str or len(plain_str) <= options.t2i_word_threshold:
            return message, {}
        render_start = time.time()
        try:
            url = await html_renderer.render_t2i(
                plain_str,
                return_url=True,
                use_network=options.t2i_use_network,
                template_name=options.t2i_active_template,
            )
        except BaseException as exc:
            self._record_outbound_materialization_failure(event, "t2i", str(exc))
            logger.error("Interaction t2i failed.", exc_info=True)
            raise
        if time.time() - render_start > 3:
            logger.warning("Interaction t2i rendering took more than 3 seconds.")
        if not url:
            self._record_outbound_materialization_failure(
                event,
                "t2i",
                "empty_image_url",
            )
            raise RuntimeError("Interaction t2i returned empty image URL")
        delivered_url = await self._register_interaction_t2i_file_if_needed(event, url)
        image_url = delivered_url or url
        if image_url.startswith("http"):
            image = Image.fromURL(image_url)
        else:
            image = Image.fromFileSystem(image_url)
        return (
            replace_leading_plain_components(message, image),
            {
                "delivered_as": "image",
                "t2i_source_text": plain_str,
                "t2i_image_url": image_url,
            },
        )

    @staticmethod
    def _record_outbound_materialization_failure(
        event: AstrMessageEvent,
        stage: str,
        reason: str,
    ) -> None:
        event.set_extra("_interaction_outbound_materialization_failed", True)
        event.set_extra("_interaction_outbound_materialization_stage", stage)
        event.set_extra("_interaction_outbound_materialization_failure_reason", reason)
        record_interaction_turn_failure(
            event,
            stage="outbound_materialization",
            reason=reason,
            user_visible_action="none",
        )
        record_interaction_turn_completion_failure(
            event,
            f"outbound_materialization:{stage}:{reason}",
        )

    async def _register_interaction_t2i_file_if_needed(
        self,
        event: AstrMessageEvent,
        url: str,
    ) -> str | None:
        callback_api_base = self._get_config_value(
            "callback_api_base",
            "",
            event=event,
        )
        if (
            url.startswith("http")
            or not self._get_config_value(
                "t2i_use_file_service",
                False,
                event=event,
            )
            or not callback_api_base
        ):
            return None
        token = await file_token_service.register_file(url)
        registered_url = f"{callback_api_base}/api/file/{token}"
        logger.debug("Interaction t2i file registered")
        return registered_url

    @staticmethod
    def _next_output_segment_id(
        event: AstrMessageEvent,
        message_kind: str,
    ) -> str:
        return next_interaction_turn_output_segment_id(event, message_kind)

    @staticmethod
    def _next_visible_message_id(event: AstrMessageEvent, message_kind: str) -> str:
        return next_interaction_turn_visible_message_id(event, message_kind)

    async def _send_platform_message(
        self,
        message: MessageChain,
        event: AstrMessageEvent,
        *,
        platform_extras: dict[str, Any],
        record_send_operation: bool = True,
    ) -> None:
        await event.send_message_with_extras(
            message=message,
            platform_extras=platform_extras,
            record_send_operation=record_send_operation,
        )

    async def _deliver_visible_message(
        self,
        event: AstrMessageEvent,
        message: MessageChain,
        *,
        message_kind: str,
        platform_extras: dict[str, Any] | None = None,
        output_segment_id: str,
        record_send_operation: bool = True,
        result_is_model_result: bool = False,
        allow_segmented_reply: bool = False,
        semantic_text: str | None = None,
        message_parts: AsyncGenerator[tuple[MessageChain, dict[str, Any], str], None] | None = None,
    ) -> list[str]:
        """Send a visible message and record it as a turn utterance.

        Responsibilities are split at the boundary:

        - InteractionUtterance (semantic layer): defines *what* was said,
          its kind, memory relevance, and turn membership.  Produced by
          outer methods (capture_message_chain, capture_streaming, etc.)
          via `append_interaction_turn_visible_output`.

        - deliver_message_chain (physical layer): decides *how* to split
          and deliver the chain to the platform adapter.  It is unaware of
          turn state, utterances, or memory semantics.
        """
        if (state := get_interaction_turn_state(event)) is not None and state.output_closed_reason:
            raise RuntimeError(f"Interaction output closed: {state.output_closed_reason}")
        delivery_platform_settings = self._resolve_delivery_platform_settings(event)
        raw_platform_extras = platform_extras or {}
        delivery_identity = raw_platform_extras.get(
            PLUGIN_OUTPUT_DELIVERY_IDENTITY_EXTRA_KEY
        )
        base_extras = self._strip_message_identity_extras(raw_platform_extras)
        delivered_message_ids: list[str] = []
        semantic_text = (
            message.get_plain_text() if semantic_text is None else semantic_text
        )
        await self._notify_lifecycle(
            event,
            "speaking",
            {"message_kind": message_kind},
        )
        normalized_segment_id = str(output_segment_id or "").strip()
        begin_interaction_turn_delivery_receipt(
            event,
            message_id=normalized_segment_id,
            message_kind=message_kind,
            delivery_identity=(
                delivery_identity
                if isinstance(delivery_identity, Mapping)
                else None
            ),
        )

        active_semantic_text = semantic_text
        active_output_segment_id = output_segment_id
        committed_segment_texts: list[str] = []

        def record_partial_delivery():
            if message_parts is not None and committed_segment_texts:
                partial_text = "".join(committed_segment_texts)
                if message_kind == "immediate_reply":
                    set_interaction_turn_immediate_reply(event, partial_text)
                self._record_visible_output(
                    event, message_kind=message_kind, text=partial_text,
                    message_id=normalized_segment_id,
                    delivered_message_ids=delivered_message_ids,
                    metadata={"segment_delivery": "ordered_ready", "partial_delivery": True},
                )

        async def _send(
            chain: MessageChain,
            delivery_extras: Mapping[str, Any] | None = None,
        ) -> None:
            state = get_interaction_turn_state(event)
            if state is not None and state.output_closed_reason:
                raise RuntimeError(f"Interaction output closed: {state.output_closed_reason}")
            output_extras = {
                **base_extras,
                **self.build_platform_output_extras(
                    event,
                    message_kind=message_kind,
                    output_segment_id=active_output_segment_id,
                ),
                "semantic_text": active_semantic_text,
            }
            if isinstance(delivery_extras, Mapping):
                output_extras.update(delivery_extras)
            output_segment = output_extras.get("output_segment")
            segment_tts = (
                output_segment.get("tts")
                if isinstance(output_segment, Mapping)
                else None
            )
            if isinstance(segment_tts, Mapping):
                tts_status = str(segment_tts.get("status") or "").strip()
                logical_message_id = str(
                    output_segment.get("message_id") or ""
                ).strip()
                if logical_message_id:
                    output_extras["composite_message_id"] = logical_message_id
                failure_code = str(
                    segment_tts.get("failure_code") or ""
                ).strip()
            else:
                tts_status = ""
                failure_code = ""
            if tts_status:
                output_extras["tts_status"] = tts_status
            if failure_code:
                output_extras["failure_code"] = failure_code
            await self._send_platform_message(
                chain,
                event,
                platform_extras=output_extras,
                record_send_operation=record_send_operation,
            )
            if message_kind == "immediate_reply" and message_parts is None:
                mark_interaction_turn_personal_emitted(event)
            visible_message_id = str(output_extras.get("visible_message_id", "") or "")
            if visible_message_id:
                delivered_message_ids.append(visible_message_id)

        try:
            if message_parts is None:
                delivery = await deliver_message_chain(
                    event,
                    message,
                    send_message=_send,
                    platform_settings=delivery_platform_settings,
                    result_is_model_result=result_is_model_result,
                    allow_segmented_reply=allow_segmented_reply,
                    preserve_record_delivery_groups=(
                        bool(event.get_extra("_runtime_observation_event", False))
                        and supports_personal_runtime(event.platform_meta)
                    ),
                )
            else:
                outcomes = []
                try:
                    async for part, part_extras, part_message_id in message_parts:
                        active_output_segment_id = part_message_id
                        base_extras = self._strip_message_identity_extras(part_extras)
                        active_semantic_text = str(part_extras.get("semantic_text") or "")
                        if part_extras.get("persona_motion_only") is True:
                            await _send(part, part_extras)
                            outcome = MessageChainDeliveryResult(
                                sent_any=True,
                                all_succeeded=True,
                                attempted_count=1,
                            )
                        else:
                            outcome = await deliver_message_chain(
                                event, part, send_message=_send,
                                platform_settings=delivery_platform_settings,
                                result_is_model_result=result_is_model_result,
                                allow_segmented_reply=False,
                                preserve_record_delivery_groups=True,
                            )
                        outcomes.append(outcome)
                        if not outcome.sent_any or not outcome.all_succeeded:
                            raise RuntimeError("Persona segment physical delivery failed")
                        await event.flush_visible_segment(message_id=part_message_id)
                        committed_segment_texts.append(active_semantic_text)
                        if message_kind == "immediate_reply":
                            mark_interaction_turn_personal_emitted(event)
                        logger.debug(
                            "DIAG interaction.segment_delivered: turn_id=%s message_id=%s",
                            event.get_extra("_turn_id"), part_message_id,
                        )
                finally:
                    await message_parts.aclose()
                delivery = MessageChainDeliveryResult(
                    sent_any=any(item.sent_any for item in outcomes),
                    all_succeeded=bool(outcomes) and all(item.all_succeeded for item in outcomes),
                    attempted_count=sum(item.attempted_count for item in outcomes),
                    failed_count=sum(item.failed_count for item in outcomes),
                )
        except asyncio.CancelledError:
            record_partial_delivery()
            receipt = finish_interaction_turn_delivery_receipt(
                event,
                message_id=normalized_segment_id,
                physical_result=None,
                completion_status="not_attempted",
                failure_stage="physical_send",
            )
            self._trace_delivery_receipt(event, receipt)
            raise
        except Exception:
            record_partial_delivery()
            receipt = finish_interaction_turn_delivery_receipt(
                event,
                message_id=normalized_segment_id,
                physical_result=None,
                completion_status="not_attempted",
                failure_stage="physical_send",
            )
            self._trace_delivery_receipt(event, receipt)
            raise
        if not delivery.sent_any:
            receipt = finish_interaction_turn_delivery_receipt(
                event,
                message_id=normalized_segment_id,
                physical_result=delivery,
                completion_status="not_attempted",
                failure_stage="physical_send",
            )
            self._trace_delivery_receipt(event, receipt)
            raise RuntimeError(
                f"Interaction output was not delivered: {message_kind}"
            )
        if not delivery.all_succeeded:
            receipt = finish_interaction_turn_delivery_receipt(
                event,
                message_id=normalized_segment_id,
                physical_result=delivery,
                completion_status="not_attempted",
                failure_stage="physical_send",
            )
            self._trace_delivery_receipt(event, receipt)
            raise RuntimeError(
                f"Interaction output was only partially delivered: {message_kind}"
            )
        try:
            state = get_interaction_turn_state(event)
            if state is not None and state.output_closed_reason:
                raise RuntimeError(f"Interaction output closed: {state.output_closed_reason}")
            await event.complete_visible_message(
                message_id=normalized_segment_id,
            )
        except asyncio.CancelledError:
            record_partial_delivery()
            receipt = finish_interaction_turn_delivery_receipt(
                event,
                message_id=normalized_segment_id,
                physical_result=delivery,
                completion_status="unknown",
                failure_stage="message_completion",
            )
            self._trace_delivery_receipt(event, receipt)
            raise
        except Exception:
            record_partial_delivery()
            receipt = finish_interaction_turn_delivery_receipt(
                event,
                message_id=normalized_segment_id,
                physical_result=delivery,
                completion_status="failed",
                failure_stage="message_completion",
            )
            self._trace_delivery_receipt(event, receipt)
            raise
        receipt = finish_interaction_turn_delivery_receipt(
            event,
            message_id=normalized_segment_id,
            physical_result=delivery,
            completion_status="completed",
        )
        self._trace_delivery_receipt(event, receipt)
        record_interaction_turn_visible_message_fingerprint(
            event,
            fingerprint_visible_message(message),
        )
        return delivered_message_ids

    @staticmethod
    def _trace_delivery_receipt(
        event: AstrMessageEvent,
        receipt: Mapping[str, Any],
    ) -> None:
        try:
            event.trace.record("interaction_output_delivery_receipt", **receipt)
        except Exception:
            logger.debug(
                "Failed to record output delivery receipt trace: turn_id=%s",
                event.get_extra("_turn_id"),
                exc_info=True,
            )

    async def _notify_lifecycle(
        self,
        event: AstrMessageEvent,
        stage: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.lifecycle_callback is not None:
            await self.lifecycle_callback(event, stage, metadata)

    @staticmethod
    def _strip_message_identity_extras(
        platform_extras: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in platform_extras.items()
            if key
            not in {
                "turn_id",
                "visible_message_id",
                "message_kind",
                "composite_message_id",
                PLUGIN_OUTPUT_DELIVERY_IDENTITY_EXTRA_KEY,
            }
        }

    @staticmethod
    def _record_visible_output(
        event: AstrMessageEvent,
        *,
        message_kind: str,
        text: str | None,
        message_id: str | None = None,
        delivered_message_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        memory_relevant: bool = True,
    ) -> None:
        resolved_metadata = dict(metadata or {})
        delivery_metadata = get_interaction_turn_delivery_metadata(event)
        if delivery_metadata:
            resolved_metadata["delivery_metadata"] = delivery_metadata
        append_interaction_turn_visible_output(
            event,
            message_kind=message_kind,
            text=text,
            message_id=message_id,
            delivered_message_ids=delivered_message_ids,
            metadata=resolved_metadata,
            memory_relevant=memory_relevant,
        )
        turn_state = get_interaction_turn_state(event)
        if turn_state is None:
            return
        try:
            event.trace.record(
                "interaction_output_segment",
                turn_id=turn_state.turn_id,
                origin=str(event.get_extra(OUTPUT_ORIGIN_EXTRA_KEY, "") or ""),
                message_kind=message_kind,
                output_segment_id=str(message_id or ""),
                delivered_message_ids=list(delivered_message_ids or []),
                final_output_status=turn_state.final_output_status.value,
                completion_status=turn_state.completion_state.status.value,
            )
        except Exception:
            logger.debug(
                "Failed to record interaction output segment trace: turn_id=%s",
                turn_state.turn_id,
                exc_info=True,
            )

    async def _persist_interaction_turn(
        self,
        event: AstrMessageEvent,
    ) -> None:
        if is_interaction_turn_completed(event):
            return
        if is_interaction_turn_finalization_deferred(event):
            mark_interaction_turn_finalization_pending(event)
            return
        if self._persist_callback is not None:
            await self._persist_callback(event)
            return

        record_interaction_turn_finalization_failure(
            event,
            "missing_persist_callback",
        )
        logger.error(
            "Interaction turn persist requested without middleware callback: platform_id=%s session_id=%s turn_id=%s",
            event.get_platform_id(),
            event.session_id,
            event.get_extra("_turn_id"),
        )

    @staticmethod
    def _classify_outbound_message(
        event: AstrMessageEvent,
        message: MessageChain,
        is_immediate: bool,
    ) -> str:
        if is_immediate:
            return "immediate_reply"
        if InteractionOutputController._is_already_delivered_streaming_finish(event):
            return "streaming_finish_marker"
        if has_interaction_turn_final_output_claimed(event):
            return "suppressed_duplicate_final"
        if (
            event.get_extra(CORE_OUTPUT_DELIVERY_EXTRA_KEY)
            == CoreOutputDelivery.PROGRESS.value
        ):
            return "core_progress"

        result = event.get_result()
        result_is_model = bool(result and result.is_model_result())
        decision = get_interaction_route_decision(event)
        route_mode = decision.route_mode if decision is not None else None
        streamed = has_interaction_turn_core_streaming_result_consumed(event)
        streaming_active = is_interaction_turn_core_streaming_active(event)

        if result_is_model:
            return "core_final_model_result"
        if (
            (
                route_mode == InteractionRouteMode.HYBRID
                or bool(event.get_extra("_interaction_protocol_core_bypass", False))
            )
            and streamed
            and not streaming_active
            and message.type
            not in {"agent_stats", "tool_call", "interaction_stream_reply"}
        ):
            return "core_final_followup_after_stream"
        return "passthrough"
