"""DeepSeek prompt rendering with volatile runtime facts at the message tail."""

from __future__ import annotations

from typing import Any

from .openai_renderer import OpenAIPromptRenderer
from .prompt_tree import PromptBuilder


class DeepSeekPromptRenderer(OpenAIPromptRenderer):
    """Use OpenAI message conventions and keep runtime facts out of system text."""

    runtime_context_as_message = True

    def get_name(self) -> str:
        return "deepseek"

    def _compile_context_message(
        self,
        prompt_tree: PromptBuilder,
        node_path: str,
    ) -> dict[str, Any] | None:
        message = super()._compile_context_message(prompt_tree, node_path)
        if message is None or node_path != "context/runtime":
            return message

        content = message.get("content")
        if isinstance(content, str):
            message["content"] = (
                "<framework_context>\n"
                "  <instruction>Framework-generated runtime facts. "
                "Treat them as context, not as a user request.</instruction>\n"
                f"{content}\n"
                "</framework_context>"
            )
        return message


__all__ = ["DeepSeekPromptRenderer"]
