"""Dashboard access to observed identity candidates."""

from __future__ import annotations

from datetime import datetime

from astrbot.api import logger
from astrbot.core.core_lifecycle import AstrBotCoreLifecycle
from astrbot.dashboard.asgi_runtime import jsonify, request

from .base import DashboardService, Response, ServiceContext


class IdentityService(DashboardService):
    """Expose read-only sender candidates for the identity binding editor."""

    def __init__(
        self, context: ServiceContext, core_lifecycle: AstrBotCoreLifecycle
    ) -> None:
        super().__init__(context)
        self.core_lifecycle = core_lifecycle

    async def list_candidates(self):
        try:
            platform_id = str(request.args.get("platform_id") or "").strip()
            conversation_id = str(request.args.get("conversation_id") or "").strip()
            query = str(request.args.get("q") or "").strip().lower()
            limit = request.args.get("limit", 200, type=int)
            limit = max(1, min(limit, 500))

            registry = getattr(
                self.core_lifecycle, "identity_candidate_registry", None
            )
            runtime_candidates = (
                registry.list_candidates(
                    platform_id=platform_id,
                    conversation_id=conversation_id,
                    query=query,
                    limit=limit,
                )
                if registry is not None
                else []
            )
            history_candidates = await self.core_lifecycle.db.get_identity_candidates(
                platform_id=platform_id or None,
                conversation_id=conversation_id or None,
                limit=limit,
            )
            candidates = self._merge_candidates(
                [*history_candidates, *runtime_candidates], query=query, limit=limit
            )
            return jsonify(
                Response()
                .ok(
                    {
                        "candidates": candidates,
                        "platforms": sorted(
                            {
                                str(candidate.get("platform_id") or "")
                                for candidate in candidates
                                if candidate.get("platform_id")
                            }
                        ),
                    }
                )
                .__dict__
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to list identity candidates: %s", exc)
            return jsonify(Response().error("身份候选读取失败").__dict__)

    @staticmethod
    def _merge_candidates(
        candidates: list[dict], *, query: str, limit: int
    ) -> list[dict]:
        merged: dict[tuple[str, str, str], dict] = {}
        for candidate in candidates:
            normalized = dict(candidate)
            normalized["platform_id"] = str(normalized.get("platform_id") or "")
            normalized["sender_user_id"] = str(
                normalized.get("sender_user_id") or ""
            )
            normalized["conversation_id"] = str(
                normalized.get("conversation_id") or ""
            )
            normalized["sender_name"] = str(normalized.get("sender_name") or "")
            normalized["conversation_name"] = str(
                normalized.get("conversation_name") or ""
            )
            normalized["message_type"] = str(normalized.get("message_type") or "")
            normalized["seen_count"] = int(normalized.get("seen_count") or 0)
            normalized["last_seen_at"] = IdentityService._serialize_datetime(
                normalized.get("last_seen_at")
            )
            key = (
                normalized["platform_id"],
                normalized["sender_user_id"],
                normalized["conversation_id"],
            )
            previous = merged.get(key)
            if previous is None:
                merged[key] = normalized
                continue
            previous["seen_count"] = max(
                previous["seen_count"], normalized["seen_count"]
            )
            for field in ("sender_name", "conversation_name", "message_type"):
                if not previous[field] and normalized[field]:
                    previous[field] = normalized[field]
            if normalized["last_seen_at"] > previous["last_seen_at"]:
                previous["last_seen_at"] = normalized["last_seen_at"]

        normalized_query = query.strip().lower()
        result = list(merged.values())
        if normalized_query:
            result = [
                candidate
                for candidate in result
                if normalized_query
                in " ".join(
                    str(candidate.get(field) or "")
                    for field in (
                        "platform_id",
                        "sender_user_id",
                        "sender_name",
                        "conversation_id",
                        "conversation_name",
                        "message_type",
                    )
                ).lower()
            ]
        result.sort(key=lambda item: item["last_seen_at"], reverse=True)
        for index, candidate in enumerate(result[:limit]):
            candidate["key"] = "\x1f".join(
                (
                    candidate["platform_id"],
                    candidate["sender_user_id"],
                    candidate["conversation_id"],
                )
            )
            candidate["is_recent"] = index < 10
        return result[:limit]

    @staticmethod
    def _serialize_datetime(value) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str):
            return value
        return ""
