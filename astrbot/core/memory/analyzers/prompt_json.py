from __future__ import annotations

import json

from ..analyzer_prompt import render_prompt_template
from .base import (
    BaseMemoryAnalyzer,
    MemoryAnalyzerExecutionError,
    MemoryAnalyzerRequest,
    MemoryAnalyzerResult,
)


class PromptJsonMemoryAnalyzer(BaseMemoryAnalyzer):
    kind = "prompt_json"

    async def analyze(self, request: MemoryAnalyzerRequest) -> MemoryAnalyzerResult:
        prompt = render_prompt_template(request.prompt_template, request.payload)
        llm_response = await request.provider.text_chat(
            prompt=prompt,
            model=request.model,
            temperature=request.temperature,
        )
        raw_text = (llm_response.completion_text or "").strip()
        if not raw_text:
            raise MemoryAnalyzerExecutionError(
                f"analyzer `{request.analyzer_name}` returned empty completion text"
            )

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise MemoryAnalyzerExecutionError(
                f"analyzer `{request.analyzer_name}` returned non-json output"
            ) from exc

        if not isinstance(data, dict):
            raise MemoryAnalyzerExecutionError(
                f"analyzer `{request.analyzer_name}` returned non-object json"
            )

        return MemoryAnalyzerResult(
            analyzer_name=request.analyzer_name,
            stage=request.stage,
            data=data,
            raw_text=raw_text,
            provider_id=request.provider_id,
            model=request.model,
        )
