"""Chat stream admission uses the chat API, independently of TTS."""

from astrbot.core.provider import Provider, supports_text_chat_stream
from astrbot.core.provider.sources.deepseek_source import ProviderDeepSeek
from astrbot.core.provider.sources.minimax_token_plan_source import (
    ProviderMiniMaxTokenPlan,
)
from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial


def test_openai_chat_stream_is_supported_without_a_tts_capability():
    # Capability inspection needs no client, API key or network request.
    streaming = ProviderOpenAIOfficial.__new__(ProviderOpenAIOfficial)
    assert not hasattr(streaming, "support_stream")
    assert supports_text_chat_stream(streaming) is True
    assert supports_text_chat_stream(ProviderDeepSeek.__new__(ProviderDeepSeek)) is True
    assert supports_text_chat_stream(
        ProviderMiniMaxTokenPlan.__new__(ProviderMiniMaxTokenPlan)
    ) is True

    class NonStreamingChat(ProviderOpenAIOfficial):
        text_chat_stream = Provider.text_chat_stream

    non_streaming = NonStreamingChat.__new__(NonStreamingChat)
    assert supports_text_chat_stream(non_streaming) is False
