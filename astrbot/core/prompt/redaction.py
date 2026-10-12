"""Conservative handling of slots explicitly marked as redacted."""

from copy import deepcopy

from .context_types import ContextSlot


def redact_context_slot(slot: ContextSlot) -> ContextSlot:
    if slot.llm_exposure != "redacted":
        return slot
    redacted = deepcopy(slot)
    redacted.value = "[REDACTED]"
    redacted.meta = {
        "redaction": "full_value",
        **({"targets": slot.meta["targets"]} if "targets" in slot.meta else {}),
    }
    return redacted
