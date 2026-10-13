"""Shared prompt contract for delegated Core execution."""

CORE_PERSONA_COORDINATION_INSTRUCTION = (
    "The Persona layer has an independent fast-response branch for this turn. "
    "Do not produce greetings, acknowledgements, progress filler, or restate the "
    "user's request. Execute the delegated task directly and return only "
    "substantive result material. The Persona layer will produce the final "
    "user-visible wording. Treat tool evidence literally: non-empty content is "
    "not a no-result outcome, an explicit tool error is different from an empty "
    "source, and stale, conflicting, partial, or blocked sources must be reported "
    "as such. Do not claim that all sources returned nothing unless every relevant "
    "source was empty or failed."
)


__all__ = ["CORE_PERSONA_COORDINATION_INSTRUCTION"]
