from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from time import time
from typing import Any

from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, Group, MessageMember
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.platform_metadata import PlatformMetadata

from .observation import RuntimeObservation


class RuntimeObservationEvent(AstrMessageEvent):
    """Event adapter for an internal observation that may produce visible output."""

    def __init__(self, *, context: Any, observation: RuntimeObservation) -> None:
        target = observation.target_session
        session = MessageSession(
            target.platform_id,
            target.message_type,
            target.session_id,
        )
        message = AstrBotMessage()
        message.type = target.message_type
        message.self_id = "astrbot"
        message.session_id = target.session_id
        message.message_id = observation.correlation_id or uuid.uuid4().hex
        message.sender = MessageMember(user_id="astrbot", nickname="AstrBot")
        message.message = []
        message.message_str = ""
        message.raw_message = {
            "post_type": "system",
            "sub_type": "runtime_observation",
            "observation_id": message.message_id,
        }
        if target.group_id:
            message.group = Group(
                group_id=target.group_id, group_name=target.group_name
            )

        super().__init__(
            "",
            message,
            PlatformMetadata(
                name=target.platform_name,
                description="Runtime observation",
                id=target.platform_id,
                support_proactive_message=target.support_proactive_message,
                support_personal_runtime=target.support_personal_runtime,
            ),
            target.session_id,
        )
        self.session = session
        self.context_obj = context
        self.observation = observation
        self._runtime_output = None
        self.set_extra("_runtime_observation_event", True)
        self.set_extra("_runtime_observation", observation)

    def prepare_runtime_output(self) -> None:
        platform = self.context_obj.get_platform_inst(self.session.platform_id)
        factory = getattr(platform, "create_runtime_output", None)
        if callable(factory):
            self._runtime_output = factory(self)

    def consume_scheduling_opportunity(self) -> None:
        """Transfer a valid opportunity to output ownership exactly at handoff.

        The source keeps its original guard for pending-work cancellation; this
        event now obeys user interruption and output failure, not scene changes.
        """
        if self.is_stopped():
            raise asyncio.CancelledError
        self.observation = replace(self.observation, cancel_event=None, expires_at=None)
        self.set_extra("_runtime_observation", self.observation)

    async def send_message_with_extras(
        self,
        message,
        *,
        platform_extras=None,
        record_send_operation=True,
    ) -> None:
        if self._runtime_output is None:
            await super().send_message_with_extras(
                message=message,
                platform_extras=platform_extras,
                record_send_operation=record_send_operation,
            )
            return
        await self._runtime_output.send(message, platform_extras)
        if record_send_operation:
            await super().send(message)

    async def complete_visible_message(self, *, message_id: str) -> None:
        if self._runtime_output is not None:
            await self._runtime_output.flush()
        await super().complete_visible_message(message_id=message_id)

    async def complete_visible_turn(self) -> None:
        if self._runtime_output is not None:
            await self._runtime_output.complete()
        await super().complete_visible_turn()

    async def abort_visible_turn(self, *, reason: str) -> None:
        if self._runtime_output is not None:
            await self._runtime_output.abort(reason)
        await super().abort_visible_turn(reason=reason)

    def is_stopped(self) -> bool:
        return super().is_stopped() or not self.observation.is_current(time())

    async def send(self, message: MessageChain) -> None:
        if message is None:
            return
        if not self.observation.is_current(time()):
            raise RuntimeError("runtime_observation_no_longer_current")
        delivered = await self.context_obj._send_message_direct(self.session, message)
        if not delivered:
            raise RuntimeError(
                f"Runtime observation target is unavailable: {self.session}"
            )
        await super().send(message)

    async def send_streaming(self, generator, use_fallback: bool = False) -> None:
        async for chain in generator:
            await self.send(chain)


__all__ = ["RuntimeObservationEvent"]
