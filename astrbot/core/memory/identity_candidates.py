"""Runtime identity candidates collected from inbound message events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DEFAULT_IDENTITY_CANDIDATE_LIMIT = 512


@dataclass
class IdentityCandidate:
    """One observed platform account in a conversation."""

    platform_id: str
    sender_user_id: str
    sender_name: str
    conversation_id: str
    conversation_name: str
    message_type: str
    last_seen_at: datetime
    seen_count: int = 1

    @property
    def key(self) -> tuple[str, str, str]:
        return self.platform_id, self.sender_user_id, self.conversation_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": "\x1f".join(self.key),
            "platform_id": self.platform_id,
            "sender_user_id": self.sender_user_id,
            "sender_name": self.sender_name,
            "conversation_id": self.conversation_id,
            "conversation_name": self.conversation_name,
            "message_type": self.message_type,
            "last_seen_at": self.last_seen_at.isoformat(),
            "seen_count": self.seen_count,
        }


class IdentityCandidateRegistry:
    """Keep a bounded, process-local index of observed platform accounts.

    The registry is a discovery aid for the dashboard. It does not resolve an
    identity and it never writes ``memory.identity.bindings``. The actual
    binding remains an explicit configuration decision.
    """

    def __init__(self, *, max_candidates: int = DEFAULT_IDENTITY_CANDIDATE_LIMIT):
        if max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        self.max_candidates = max_candidates
        self._candidates: dict[tuple[str, str, str], IdentityCandidate] = {}

    def observe(self, event: Any) -> None:
        """Record one inbound event when it contains a stable sender ID."""

        platform_id = self._event_string(event, "get_platform_id") or self._event_string(
            event, "get_platform_name"
        )
        sender_user_id = self._event_string(event, "get_sender_id")
        if not platform_id or not sender_user_id:
            return

        self_id = self._event_string(event, "get_self_id")
        if self_id and self_id == sender_user_id:
            return

        group_id = self._event_string(event, "get_group_id")
        session_id = self._event_string(event, "get_session_id")
        conversation_id = group_id or session_id
        if not conversation_id:
            conversation_id = self._event_string(event, "unified_msg_origin")
        if not conversation_id:
            return

        message_type = self._message_type(event)
        sender_name = self._event_string(event, "get_sender_name")
        conversation_name = self._conversation_name(event)
        now = datetime.now(UTC)
        key = (platform_id, sender_user_id, conversation_id)
        current = self._candidates.get(key)
        if current is None:
            self._candidates[key] = IdentityCandidate(
                platform_id=platform_id,
                sender_user_id=sender_user_id,
                sender_name=sender_name,
                conversation_id=conversation_id,
                conversation_name=conversation_name,
                message_type=message_type,
                last_seen_at=now,
            )
        else:
            current.last_seen_at = now
            current.seen_count += 1
            if sender_name:
                current.sender_name = sender_name
            if conversation_name:
                current.conversation_name = conversation_name
            if message_type:
                current.message_type = message_type

        self._trim()

    def list_candidates(
        self,
        *,
        platform_id: str = "",
        conversation_id: str = "",
        query: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return recent candidates matching the dashboard filters."""

        normalized_platform = platform_id.strip().lower()
        normalized_conversation = conversation_id.strip().lower()
        normalized_query = query.strip().lower()
        candidates = []
        for candidate in self._candidates.values():
            if normalized_platform and candidate.platform_id.lower() != normalized_platform:
                continue
            if (
                normalized_conversation
                and candidate.conversation_id.lower() != normalized_conversation
            ):
                continue
            haystack = " ".join(
                (
                    candidate.platform_id,
                    candidate.sender_user_id,
                    candidate.sender_name,
                    candidate.conversation_id,
                    candidate.conversation_name,
                    candidate.message_type,
                )
            ).lower()
            if normalized_query and normalized_query not in haystack:
                continue
            candidates.append(candidate)

        bounded_limit = max(1, min(limit, self.max_candidates))
        candidates.sort(key=lambda item: item.last_seen_at, reverse=True)
        return [candidate.as_dict() for candidate in candidates[:bounded_limit]]

    def _trim(self) -> None:
        excess = len(self._candidates) - self.max_candidates
        if excess <= 0:
            return
        oldest_keys = sorted(
            self._candidates,
            key=lambda key: self._candidates[key].last_seen_at,
        )[:excess]
        for key in oldest_keys:
            self._candidates.pop(key, None)

    @staticmethod
    def _event_string(event: Any, name: str) -> str:
        value = getattr(event, name, None)
        try:
            value = value() if callable(value) else value
        except Exception:  # noqa: BLE001
            return ""
        if isinstance(value, str):
            return value.strip()
        if value is None:
            return ""
        return str(value).strip()

    @classmethod
    def _message_type(cls, event: Any) -> str:
        value = getattr(event, "get_message_type", None)
        try:
            value = value() if callable(value) else value
        except Exception:  # noqa: BLE001
            return ""
        if isinstance(value, Mapping):
            value = value.get("value") or value.get("name")
        else:
            value = getattr(value, "value", None) or getattr(value, "name", None) or value
        return str(value).strip() if value is not None else ""

    @classmethod
    def _conversation_name(cls, event: Any) -> str:
        message_obj = getattr(event, "message_obj", None)
        group = getattr(message_obj, "group", None)
        for source in (group, message_obj):
            value = getattr(source, "group_name", None) or getattr(source, "name", None)
            if value:
                return str(value).strip()
        return ""
