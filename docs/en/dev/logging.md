# Logging Guidelines

AstrBot uses three logging layers. Normal runtime logs show whether the system is healthy, diagnostic logs explain state and latency boundaries, and Trace stores controlled detailed material.

| Channel | Purpose | Allowed content |
| --- | --- | --- |
| `INFO` | Startup, configuration changes, actual task dispatch, and important user-visible outcomes | Stable IDs, state, counts, durations, capability names |
| `DEBUG` | Stage diagnostics in the `DIAG <domain>.<event>` form | Stages, reason codes, counts, lengths, durations, slot/tool names |
| Trace file | Prompt structure, context slots, and controlled troubleshooting material | Written only when `trace_log_enable=true` |
| `WARNING` / `ERROR` | Recoverable exceptions, failures, and configuration issues | Stage, exception type, status code, response length, and `exc_info` |

## Do not write to normal logs

- Full user input, model replies, STT text, or TTS source text;
- Full Prompts, histories, context slot values, tool arguments, or tool results;
- API keys, Authorization headers, file callback tokens, or signed URLs;
- Raw provider/platform request bodies, responses, or WebSocket messages.

Use summaries such as `text_length`, `message_count`, `response_keys`, `tool_count`, `status`, and `error_length` instead.

## Correlation Fields

For Interaction flows, prefer `turn_id`, `session_id`, `platform_id`, and `lifecycle_id`. Duration fields use `*_ms` and make their boundaries explicit, such as `personal_first_output_ms`, `provider_ms`, and `turn_total_ms`.

A normal conversation must not print Prompts, tool-loop details, or every internal stage at `INFO`. Use `DEBUG` for summary diagnostics. To inspect full Prompt structure, additionally enable `trace_log_enable` and protect the resulting Trace file.

## Adding a Log

Choose the channel before writing the message:

1. Does an operator need it during ordinary operation? Use brief `INFO`.
2. Does it explain latency or an internal decision? Use content-free `DEBUG DIAG`.
3. Does it contain Prompt, input, output, or a raw remote object? Write it only to the Trace file.
4. For a failure, record the error type, stage, and length; never append raw requests, responses, or sensitive values to the exception message.
