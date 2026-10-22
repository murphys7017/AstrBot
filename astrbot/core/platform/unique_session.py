from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from astrbot.core.platform.message_type import MessageType

if TYPE_CHECKING:
    from astrbot.core.platform.astr_message_event import AstrMessageEvent

UNIQUE_SESSION_ID_BUILDERS: dict[
    str,
    Callable[[AstrMessageEvent], str | None],
] = {
    "aiocqhttp": lambda event: f"{event.get_sender_id()}_{event.get_group_id()}",
    "slack": lambda event: f"{event.get_sender_id()}_{event.get_group_id()}",
    "dingtalk": lambda event: event.get_sender_id(),
    "qq_official": lambda event: f"{event.get_sender_id()}_{event.get_group_id()}",
    "qq_official_webhook": lambda event: (
        f"{event.get_sender_id()}_{event.get_group_id()}"
    ),
    "lark": lambda event: f"{event.get_sender_id()}%{event.get_group_id()}",
    "misskey": lambda event: f"{event.get_session_id()}_{event.get_sender_id()}",
    "matrix": lambda event: (
        f"{event.get_sender_id()}_{event.get_group_id() or event.get_session_id()}"
    ),
}


def build_unique_session_id(event: AstrMessageEvent) -> str | None:
    builder = UNIQUE_SESSION_ID_BUILDERS.get(event.get_platform_name())
    return builder(event) if builder else None


def apply_unique_session(
    event: AstrMessageEvent,
    runtime_config: Mapping[str, object],
) -> None:
    platform_settings = runtime_config.get("platform_settings", {})
    if not isinstance(platform_settings, Mapping):
        return
    if not platform_settings.get("unique_session", False):
        return
    if event.message_obj.type != MessageType.GROUP_MESSAGE:
        return

    session_id = build_unique_session_id(event)
    if session_id:
        event.session_id = session_id
