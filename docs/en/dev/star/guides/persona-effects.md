---
outline: deep
---

# Persona Effects

Persona Effects are an AG99 extension created by YakumoAki for structured persona output. A plugin can let Persona Runtime produce presentation intent, such as a Live2D motion, light state, or client expression, alongside segmented user-visible text in `segments[].speech`.

A Persona Effect is not an executable business Agent Tool and is never run by the
Core Tool Loop or provided to the Core Planner. Expression is returned through the
strict `persona_expression` contract, which contains `turn_action` and
`segments`. When the current event has registered, applicable effects, the same
model response must also call the separate terminal tool `persona_effect_batch`,
whose parameters contain only `effect_calls`. Core aggregates both channels; it
does not make a second model request for effects. Action intents and plugin-owned
effect calls remain separate. When no effect applies, the effect tool is omitted
and the aggregated result contains an empty `effect_calls` array. The Personal
Response Plan selects `reply`, `delegate`, or an eligible-group `silent`.

## Register an Effect

```python
from astrbot.api.star import Context, Star
from astrbot.core.interaction import PersonaEffectSpec


def supports_current_event(event) -> bool:
    return event.get_platform_name() == "my_platform"


class Main(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        context.register_persona_effect(
            PersonaEffectSpec(
                plugin_id="my_plugin",
                name="my_plugin.expression",
                description="Select a client expression for the visible reply.",
                parameters={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "label": {"type": "string"},
                    },
                    "required": ["label"],
                },
            ),
            event_filter=supports_current_event,
        )
```

`event_filter` must be synchronous and side-effect free. Core passes the current event whenever it builds a Persona output contract:

- `True`: the effect schema is included in this turn's separate
  `persona_effect_batch` tool-call contract, not in `persona_expression`.
- `False`: the effect is hidden from the model and consumes no schema tokens for this turn.
- Exception: Core logs a warning and treats the result as `False`.

A platform-specific plugin should check the current platform, adapter, device capability, and required runtime instead of exposing its schema globally. Synthetic environment events can also be excluded by this filter.

## List and Unregister

```python
active = context.list_persona_effects(event=event)
all_enabled = context.list_persona_effects()
context.unregister_persona_effects(plugin_id="my_plugin")
```

The event-scoped query builds the current Persona contract. The unscoped query is for registry management and diagnostics; it lists all enabled registrations and does not imply that every effect applies to every event.

## Output and Consumption

The `persona_expression` parameters use this shape:

```json
{
  "turn_action": "reply",
  "segments": [
    {
      "speech": "User-visible reply",
      "actions": [],
      "thought": "The character's brief current thought",
      "tendency": {
        "Joy": 0,
        "Trust": 0,
        "Fear": 0,
        "Surprise": 0,
        "Sadness": 0,
        "Disgust": 0,
        "Anger": 0,
        "Anticipation": 0
      }
    }
  ]
}
```

When an effect applies, the initial model response is expected to also call
`persona_effect_batch` with:

```json
{
  "effect_calls": [
    {
      "name": "my_plugin.expression",
      "arguments": {"label": "happy"}
    }
  ]
}
```

When optional effects apply but none need to be called, the batch is still
returned with an empty array. Required effects must meet their registered count
constraints, except that an allowed silent response may return an empty batch.
Core validates calls against the registered schema and restores plugin ownership.
The plugin consumes its own calls from the current
`InteractionResultView.effect_calls`, then executes them through
`client_objects`, `platform_extras`, or its own transport. When no effect
applies, the model is not given the effect tool and Core aggregates an empty
array.

If the initial response omits either channel, Core makes one isolated request
for only the missing channel and merges the validated result before plugin
delivery. If both channels are missing, it fills the expression first and then
the effect batch. Repeated or malformed channel payloads still fail validation.

The plugin owns device constraints, resource mapping, and fallback behavior. Core does not understand motion semantics, Live2D parameters, or client protocols.
