"""Target-owned scheduling policy shared by all proactive opportunity sources."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass(slots=True)
class ProactiveScheduleBinding:
    owner_source: str
    mode: str
    reply_cooldown_seconds: float = 300
    no_action_cooldown_seconds: float = 60
    daily_output_limit: int = 24
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    def allows(self, source: str) -> bool:
        if self.cancelled.is_set() or self.mode == "off":
            return False
        return (source == self.owner_source) == (self.mode == "live")


def output_target_busy(context, session: str) -> bool:
    from astrbot.core.platform.message_session import MessageSession

    target = MessageSession.from_str(session)
    platform = context.get_platform_inst(target.platform_id)
    if platform is None:
        return True
    available = getattr(platform, "is_proactive_output_available", None)
    return callable(available) and not available()
