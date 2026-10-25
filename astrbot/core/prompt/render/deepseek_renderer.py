"""DeepSeek prompt rendering with volatile runtime facts at the message tail."""

from __future__ import annotations

from .openai_renderer import OpenAIPromptRenderer


class DeepSeekPromptRenderer(OpenAIPromptRenderer):
    """Use OpenAI message conventions and keep runtime facts out of system text."""

    def get_name(self) -> str:
        return "deepseek"

__all__ = ["DeepSeekPromptRenderer"]
