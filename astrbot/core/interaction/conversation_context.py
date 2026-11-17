"""One context binding for history reads and writes, preserving input identity."""

from __future__ import annotations

from astrbot.core.platform.message_session import MessageSession


def conversation_session(event) -> str:
    target = event.get_extra("interaction.context_target")
    return str(MessageSession.from_str(target or event.unified_msg_origin))


def public_context(event, context=None) -> bool:
    if event is None:
        return False
    frozen = event.get_extra("interaction.context_public_snapshot")
    if isinstance(frozen, bool):
        return frozen
    if event.get_extra("interaction.context_visibility") == "public":
        event.set_extra("interaction.context_public_snapshot", True)
        return True
    binding = (
        context.get_proactive_schedule(conversation_session(event)) if context else None
    )
    public = binding is not None and binding.mode == "live"
    if context is not None:
        event.set_extra("interaction.context_public_snapshot", public)
    return public


def project_public_context(pack, *, public: bool):
    """Unscoped memories/extensions cannot enter a public invocation's prompt."""
    if not public:
        return pack
    from astrbot.core.prompt.context_types import ContextPack

    return ContextPack(
        slots={
            name: slot
            for name, slot in pack.slots.items()
            if (
                not name.startswith(("memory.", "extension."))
                or slot.meta.get("visibility") == "public"
            )
        },
        meta=dict(pack.meta),
        provider_request_ref=pack.provider_request_ref,
    )


def visible_history(history, *, public: bool):
    from astrbot.core.memory.history_source import parse_conversation_history

    messages = parse_conversation_history(history)
    if not public:
        return messages
    return [
        m
        for m in messages
        if (
            isinstance(m.get("_astrbot_metadata"), dict)
            and m["_astrbot_metadata"].get("visibility") == "public"
        )
    ]
