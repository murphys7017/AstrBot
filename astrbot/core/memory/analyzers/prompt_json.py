from __future__ import annotations

from contextlib import aclosing
from time import perf_counter

from astrbot.core.provider import supports_text_chat_stream

from ..analyzer_prompt import render_prompt_template
from .base import (
    BaseMemoryAnalyzer,
    MemoryAnalyzerExecutionError,
    MemoryAnalyzerRequest,
    MemoryAnalyzerResult,
)

OUTPUT_SCHEMA_CONTRACTS: dict[str, str] = {
    "TopicStateResult": (
        'Return exactly one JSON object with keys: "current_topic", '
        '"topic_summary", "topic_confidence". '
        '"current_topic" and "topic_summary" must be non-empty strings. '
        '"topic_confidence" must be a number between 0 and 1.'
    ),
    "ShortTermFocusResult": (
        'Return exactly one JSON object with key: "active_focus". '
        '"active_focus" must be a non-empty string.'
    ),
    "ShortTermSummaryResult": (
        'Return exactly one JSON object with key: "short_summary". '
        '"short_summary" must be a non-empty string.'
    ),
    "SessionInsightResult": (
        'Return exactly one JSON object with keys: "topic_summary", '
        '"progress_summary", "summary_text". All values must be non-empty strings.'
    ),
    "ExperienceExtractResult": (
        'Return exactly one JSON object with key: "experiences". '
        '"experiences" must be a list of objects. Each object must include '
        '"category", "summary", "detail_summary", "importance", and "confidence".'
    ),
    "LongTermPromoteResult": (
        'Return exactly one JSON object with key: "actions". '
        '"actions" must be a list of objects. Each object must include '
        '"action", "target_memory_id", "category", "reason", and "experience_ids".'
    ),
    "LongTermComposeResult": (
        'Return exactly one JSON object with keys: "title", "summary", '
        '"detail_summary", "tags", "importance", "confidence", and "status".'
    ),
    "PersonaReflectResult": (
        'Return exactly one JSON object with keys: "should_update", "confidence", '
        '"reason", and "deltas". "should_update" must be a boolean. '
        '"confidence" must be a number between 0 and 1. "reason" must be a non-empty string. '
        '"deltas" must contain numeric keys "familiarity", "trust", "warmth", '
        '"formality_preference", and "directness_preference".'
    ),
}


class PromptJsonMemoryAnalyzer(BaseMemoryAnalyzer):
    kind = "prompt_json"

    async def analyze(self, request: MemoryAnalyzerRequest) -> MemoryAnalyzerResult:
        prompt_template = _append_output_schema_contract(
            request.prompt_template,
            request.output_schema,
        )
        prompt = render_prompt_template(prompt_template, request.payload)
        started = perf_counter()
        diagnostics = request.diagnostics
        diagnostics.update(
            phase="requesting", prompt_chars=len(prompt), response_chars=0,
            reasoning_chars=0, response_count=0,
        )
        parts = []
        final_text = ""
        options = {"temperature": request.temperature, "extra_body": request.extra_body}
        if supports_text_chat_stream(request.provider):
            diagnostics["transport"] = "stream"
            async with aclosing(request.provider.text_chat_stream(prompt=prompt, **options)) as stream:
                async for response in stream:
                    now_ms = round((perf_counter() - started) * 1000, 1)
                    diagnostics.setdefault("first_response_ms", now_ms)
                    diagnostics["response_count"] += 1
                    diagnostics["last_response_ms"] = now_ms
                    reasoning = str(getattr(response, "reasoning_content", "") or "")
                    if response.is_chunk:
                        diagnostics["reasoning_chars"] += len(reasoning)
                    elif reasoning:
                        diagnostics["reasoning_chars"] = max(
                            diagnostics["reasoning_chars"], len(reasoning),
                        )
                    if reasoning and "first_text_ms" not in diagnostics:
                        diagnostics["phase"] = "reasoning"
                    if response.role == "err":
                        raise MemoryAnalyzerExecutionError(
                            "memory Provider returned an error: " + str(response.completion_text or "")[:256],
                            reason="provider_error",
                        )
                    text = str(response.completion_text or "")
                    if text:
                        diagnostics.setdefault("first_text_ms", now_ms)
                        diagnostics["phase"] = "streaming"
                        if response.is_chunk:
                            parts.append(text)
                            diagnostics["response_chars"] += len(text)
                        else:
                            final_text = text
                    if diagnostics["response_chars"] > 256_000 or len(final_text) > 256_000:
                        raise MemoryAnalyzerExecutionError(
                            "memory analyzer output exceeded character limit", reason="output_too_large",
                        )
            raw_text = (final_text or "".join(parts)).strip()
        else:
            diagnostics["transport"] = "nonstream"
            response = await request.provider.text_chat(prompt=prompt, **options)
            diagnostics["first_response_ms"] = round((perf_counter() - started) * 1000, 1)
            if response.role == "err":
                raise MemoryAnalyzerExecutionError(
                    "memory Provider returned an error: " + str(response.completion_text or "")[:256],
                    reason="provider_error",
                )
            raw_text = str(response.completion_text or "").strip()
            if raw_text:
                diagnostics["first_text_ms"] = diagnostics["first_response_ms"]
            diagnostics["reasoning_chars"] = len(str(response.reasoning_content or ""))
        diagnostics.update(
            phase="parsing", response_chars=len(raw_text),
            provider_ms=round((perf_counter() - started) * 1000, 1),
        )
        if not raw_text:
            raise MemoryAnalyzerExecutionError(
                f"analyzer `{request.analyzer_name}` returned empty completion text",
                reason="empty_output",
            )

        # Prompt collectors also consume Memory. Load the shared parser only
        # after Memory initialization, avoiding a startup import cycle.
        from astrbot.core.prompt.json_recovery import parse_json_record

        try:
            data = parse_json_record(raw_text, max_chars=256_000)
        except ValueError as exc:
            raise MemoryAnalyzerExecutionError(
                f"analyzer `{request.analyzer_name}` returned ambiguous json",
                reason="invalid_json",
            ) from exc
        if data is None:
            raise MemoryAnalyzerExecutionError(
                f"analyzer `{request.analyzer_name}` returned invalid object json",
                reason="invalid_json",
            )
        diagnostics["phase"] = "completed"

        return MemoryAnalyzerResult(
            analyzer_name=request.analyzer_name,
            stage=request.stage,
            data=data,
            raw_text=raw_text,
            provider_id=request.provider_id,
            model=None,
        )


def _append_output_schema_contract(template: str, output_schema: str) -> str:
    schema_name = output_schema.strip()
    if not schema_name:
        return template

    contract = OUTPUT_SCHEMA_CONTRACTS.get(schema_name)
    if contract is None:
        return template

    return (
        f"{template.rstrip()}\n\n"
        "Output schema contract:\n"
        f"- Schema: {schema_name}\n"
        f"- {contract}\n"
        "- Do not omit required keys. Do not rename keys. Do not return null or empty strings for required fields.\n"
    )
