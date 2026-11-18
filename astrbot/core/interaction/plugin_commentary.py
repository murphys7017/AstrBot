"""Submit plugin-owned reading material to the Core expression pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from astrbot import logger
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.plugin_admission import resolve_event_plugins_name

from .observation import RuntimeObservation, RuntimeObservationTarget
from .personal_gate import ObservationGateReason
from .personal_policy import (
    READING_COMMENTARY_OPPORTUNITY,
    PersonalPolicyAction,
    PersonalPolicyEvaluationStatus,
)

if TYPE_CHECKING:
    from astrbot.core.pipeline.context import PipelineContext
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.star.base import Star
    from astrbot.core.star.context import Context

    from .personal_runtime import PlatformEventSubmission

_EXTRA_KEY = "_core_plugin_commentary"
_REQUEST_TIMEOUT_SECONDS = 300


@dataclass(frozen=True, slots=True)
class PluginCommentaryResult:
    status: Literal["played", "silent", "busy", "rejected", "failed", "unknown"]
    turn_id: str
    delivery_turn_id: str | None = None
    text: str = ""
    reason: str | None = None


@dataclass(slots=True)
class PluginCommentary:
    owner: Star
    event: AstrMessageEvent
    target: MessageSession
    title: str
    text: str
    preceding: str
    presentation_effects: frozenset[tuple[str, str]]
    result: asyncio.Future[PluginCommentaryResult]
    automatic: bool = False
    claim_output: Callable[[], bool] | None = None
    task: asyncio.Task | None = None
    playback_text: str | None = None
    playback_confirmed: bool = False


def plugin_commentary_for(event: AstrMessageEvent) -> PluginCommentary | None:
    request = event.get_extra(_EXTRA_KEY)
    if isinstance(request, PluginCommentary) and request.event is event:
        return request
    return None


def _owner_is_active(context: Context, owner: Star) -> bool:
    metadata = context.get_registered_star(owner.name)
    return bool(metadata and metadata.activated and metadata.star_cls is owner)


async def submit_plugin_commentary(
    context: Context,
    *,
    owner: Star,
    source_platform_id: str,
    target_session: str,
    request_id: str,
    title: str,
    text: str,
    preceding: str,
    automatic: bool = False,
    claim_output: Callable[[], bool] | None = None,
) -> PluginCommentaryResult:
    if not _owner_is_active(context, owner):
        return PluginCommentaryResult("rejected", request_id, reason="plugin_inactive")
    try:
        if UUID(request_id).hex != request_id:
            raise ValueError
        target = MessageSession.from_str(target_session)
        if target.message_type is not MessageType.FRIEND_MESSAGE:
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        return PluginCommentaryResult("rejected", request_id, reason="invalid_request")
    if (
        not text.strip()
        or len(text) > 4000
        or len(title) > 200
        or len(preceding) > 4000
    ):
        return PluginCommentaryResult("rejected", request_id, reason="invalid_material")

    source = context.get_platform_inst(source_platform_id)
    adapter = context.get_platform_inst(target.platform_id)
    factory = getattr(adapter, "create_plugin_commentary_event", None)
    if (
        source is None
        or not callable(factory)
        or not adapter.meta().support_personal_runtime
    ):
        return PluginCommentaryResult(
            "rejected", request_id, reason="commentary_target_unavailable"
        )

    message = AstrBotMessage()
    message.type = target.message_type
    message.session_id = target.session_id
    message.self_id = source_platform_id
    message.message_id = request_id
    message.sender = MessageMember(user_id=owner.name, nickname=owner.name)
    message.message = []
    message.message_str = ""
    message.raw_message = {"post_type": "system", "sub_type": "plugin_commentary"}
    event = factory(message, source.meta())
    event.set_extra("_turn_id", request_id)
    event.set_extra("interaction.context_target", str(target))
    event.set_extra("interaction.context_visibility", "public")
    request = PluginCommentary(
        owner,
        event,
        target,
        title,
        text,
        preceding,
        frozenset(getattr(adapter, "plugin_commentary_presentation_effects", ())),
        asyncio.get_running_loop().create_future(),
        automatic=automatic,
        claim_output=claim_output,
    )
    event.set_extra(_EXTRA_KEY, request)
    try:
        source.commit_event(event)
    except asyncio.QueueFull:
        return PluginCommentaryResult("busy", request_id, reason="core_queue_full")

    try:
        async with asyncio.timeout(_REQUEST_TIMEOUT_SECONDS):
            return await asyncio.shield(request.result)
    except TimeoutError:
        return _interrupted_result(request, "commentary_result_timeout")
    finally:
        if not request.result.done():
            request.result.cancel()
            event.stop_event()
            if request.task is not None:
                request.task.cancel()
                await asyncio.gather(request.task, return_exceptions=True)


def _interrupted_result(
    request: PluginCommentary, reason: str
) -> PluginCommentaryResult:
    if not request.playback_confirmed and request.playback_text is not None:
        reason = "playback_receipt_unconfirmed"
    return PluginCommentaryResult(
        "played" if request.playback_confirmed else "unknown",
        request.event.message_obj.message_id,
        request.event.get_extra("output_correlation_id"),
        (request.playback_text or "") if request.playback_confirmed else "",
        reason=reason,
    )


async def run_plugin_commentary(
    request: PluginCommentary,
    ctx: PipelineContext,
    *,
    config_id: str,
    runtime_config: Mapping[str, Any],
) -> None:
    """Run the typed event after EventBus configuration selection."""
    if request.result.done():
        return
    request.task = asyncio.current_task()
    turn_id = request.event.message_obj.message_id
    try:
        result = await _run(request, ctx, config_id, runtime_config, turn_id)
    except asyncio.CancelledError:
        if not request.result.done():
            result = (
                _interrupted_result(request, "cancelled")
                if request.playback_text is not None
                else PluginCommentaryResult("failed", turn_id, reason="cancelled")
            )
            request.result.set_result(result)
        raise
    except Exception as exc:
        reason = str(getattr(exc, "reason", "") or type(exc).__name__)
        delivery_id = request.event.get_extra("output_correlation_id")
        busy = reason == "presentation_busy" and not delivery_id
        if not busy:
            logger.exception("Plugin commentary failed: turn_id=%s", turn_id)
        if request.playback_confirmed:
            result = _interrupted_result(request, reason)
        elif request.playback_text is not None and isinstance(exc, TimeoutError):
            result = _interrupted_result(request, reason)
        else:
            result = PluginCommentaryResult(
                "busy" if busy else "failed", turn_id, delivery_id, reason=reason
            )
    finally:
        request.task = None
    if not request.result.done():
        request.result.set_result(result)


async def _run(
    request: PluginCommentary,
    ctx: PipelineContext,
    config_id: str,
    runtime_config: Mapping[str, Any],
    turn_id: str,
) -> PluginCommentaryResult:
    from astrbot.core.star.session_llm_manager import SessionServiceManager

    from .config import load_interaction_agent_config
    from .turn_state import (
        get_interaction_turn_immediate_reply,
        mark_interaction_turn_cancelled,
        mark_interaction_turn_failed,
    )

    event = request.event
    context = ctx.plugin_manager.context
    middleware = ctx.interaction_middleware
    manager = ctx.personal_runtime_manager
    if (
        middleware is None
        or manager is None
        or not load_interaction_agent_config(runtime_config).enabled
    ):
        return PluginCommentaryResult(
            "rejected", turn_id, reason="personal_expression_unavailable"
        )
    event.plugins_name = resolve_event_plugins_name(runtime_config)
    if (
        not _owner_is_active(context, request.owner)
        or (
            event.plugins_name is not None
            and request.owner.name not in event.plugins_name
        )
        or not await SessionServiceManager.is_session_enabled(str(request.target))
        or not await SessionServiceManager.is_llm_enabled_for_session(
            str(request.target)
        )
    ):
        return PluginCommentaryResult(
            "rejected", turn_id, reason="commentary_session_disabled"
        )
    adapter = context.get_platform_inst(request.target.platform_id)
    if adapter is not event.adapter:
        return PluginCommentaryResult(
            "rejected", turn_id, reason="commentary_target_replaced"
        )
    status = adapter.plugin_commentary_output_status(request.target.session_id)
    if status == "busy":
        return PluginCommentaryResult("busy", turn_id, reason="presentation_busy")
    if status != "ready":
        return PluginCommentaryResult("rejected", turn_id, reason=status)

    async def wait_for_playback() -> None:
        request.playback_text = get_interaction_turn_immediate_reply(event) or ""
        await event.wait_for_plugin_commentary_output()
        request.playback_confirmed = True

    async with manager.submit_platform_event(
        event, config_id, context, dict(runtime_config)
    ) as submission:
        topic = ""
        if request.automatic:
            decision = await _evaluate_reading_topic(request, submission, turn_id)
            if isinstance(decision, PluginCommentaryResult):
                return decision
            topic = decision
        admission = await submission.admit(allow_follow_up=False, wait_if_busy=False)
        if admission.lease is None:
            return PluginCommentaryResult(
                "busy", turn_id, reason="personal_session_busy"
            )
        successful = False
        try:
            with manager.activate_turn(admission.turn):
                status = adapter.plugin_commentary_output_status(
                    request.target.session_id
                )
                if status == "busy":
                    return PluginCommentaryResult(
                        "busy", turn_id, reason="presentation_busy"
                    )
                if status != "ready":
                    return PluginCommentaryResult("rejected", turn_id, reason=status)
                if request.claim_output is not None and not request.claim_output():
                    return PluginCommentaryResult(
                        "busy", turn_id, reason="commentary_no_longer_current"
                    )
                deadline = admission.turn.state.deadline
                logger.info(
                    "Plugin commentary admitted: turn_id=%s source=%s target=%s",
                    turn_id,
                    request.owner.name,
                    request.target,
                )
                async with deadline.enforce("plugin_commentary"):
                    text = await middleware.handle_plugin_commentary(
                        event,
                        title=request.title,
                        text=request.text,
                        preceding=request.preceding,
                        topic=topic,
                        wait_for_playback=wait_for_playback,
                    )
                successful = True
                return PluginCommentaryResult(
                    "played" if text is not None else "silent",
                    turn_id,
                    event.get_extra("output_correlation_id"),
                    text or "",
                )
        except asyncio.CancelledError:
            mark_interaction_turn_cancelled(event)
            raise
        except Exception as exc:
            if getattr(exc, "reason", None) != "presentation_busy":
                mark_interaction_turn_failed(event)
            raise
        finally:
            try:
                if (
                    not successful
                    and not request.playback_confirmed
                    and event.get_extra("output_correlation_id")
                ):
                    try:
                        await event.abort_visible_turn(
                            reason="plugin_commentary_failed"
                        )
                    except Exception:
                        logger.exception(
                            "Plugin commentary cleanup failed: turn_id=%s", turn_id
                        )
            finally:
                await admission.lease.release()


async def _evaluate_reading_topic(
    request: PluginCommentary, submission: PlatformEventSubmission, turn_id: str
) -> str | PluginCommentaryResult:
    metadata = request.event.adapter.meta()
    fact = RuntimeObservation(
        kind=READING_COMMENTARY_OPPORTUNITY,
        source=f"plugin_commentary:{request.owner.name}",
        occurred_at=time(),
        target_session=RuntimeObservationTarget(
            platform_id=request.target.platform_id,
            platform_name=metadata.name,
            message_type=request.target.message_type,
            session_id=request.target.session_id,
            support_proactive_message=metadata.support_proactive_message,
            support_personal_runtime=metadata.support_personal_runtime,
        ),
        payload={
            "title": request.title,
            "passage": request.text,
            "preceding": request.preceding[-1200:],
        },
    )
    async with submission.turn.state.deadline.enforce("reading_policy"):
        gate_reason, evaluation = await submission.evaluate_reading_policy(fact)
    if gate_reason in {
        ObservationGateReason.RUNTIME_BUSY,
        ObservationGateReason.STATE_RESTORE_PENDING,
    }:
        return PluginCommentaryResult("busy", turn_id, reason=gate_reason.value)
    if evaluation is None:
        logger.debug(
            "Reading commentary skipped by Policy gate: turn_id=%s gate=%s",
            turn_id,
            "policy_disabled"
            if gate_reason is ObservationGateReason.ACCEPTED
            else gate_reason.value,
        )
        return PluginCommentaryResult("silent", turn_id)
    if evaluation.status is PersonalPolicyEvaluationStatus.FAIL_CLOSED:
        return PluginCommentaryResult(
            "failed", turn_id, reason=f"personal_policy_{evaluation.failure_code}"
        )
    if evaluation.decision.action is PersonalPolicyAction.EXPRESS:
        return evaluation.decision.reply_intent[:240]
    return PluginCommentaryResult("silent", turn_id)
