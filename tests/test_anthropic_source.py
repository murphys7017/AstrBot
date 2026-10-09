import json

import pytest
from anthropic import _base_client as anthropic_base_client
from anthropic.types import MessageDeltaUsage, Usage

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.provider.entities import TokenUsage
from astrbot.core.provider.sources.anthropic_source import ProviderAnthropic

sdk_httpx = getattr(
    anthropic_base_client,
    "httpx",
    getattr(anthropic_base_client, "httpx2", None),
)


def _provider() -> ProviderAnthropic:
    return ProviderAnthropic.__new__(ProviderAnthropic)


def test_anthropic_extract_usage_counts_cache_creation_input():
    provider = _provider()

    usage = provider._extract_usage(
        Usage(
            input_tokens=10,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=50,
            output_tokens=20,
        )
    )

    # Anthropic's input_tokens excludes cache writes, so cache_creation
    # must be folded into input_other to keep total input accurate.
    assert usage.input_other == 60
    assert usage.input_cached == 100
    assert usage.input == 160
    assert usage.output == 20


def test_anthropic_extract_usage_without_cache_breakpoints():
    provider = _provider()

    usage = provider._extract_usage(Usage(input_tokens=30, output_tokens=10))

    assert usage.input_other == 30
    assert usage.input_cached == 0
    assert usage.input == 30
    assert usage.output == 10


def test_anthropic_extract_usage_none_returns_empty():
    provider = _provider()

    assert provider._extract_usage(None) == TokenUsage()


def test_anthropic_update_usage_counts_cache_creation_input():
    provider = _provider()
    token_usage = TokenUsage(input_other=5, input_cached=0, output=0)

    provider._update_usage(
        token_usage,
        MessageDeltaUsage(
            input_tokens=10,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=50,
            output_tokens=20,
        ),
    )

    assert token_usage.input_other == 60
    assert token_usage.input_cached == 100
    assert token_usage.input == 160
    assert token_usage.output == 20


def test_anthropic_update_usage_omitted_fields_are_preserved():
    provider = _provider()
    token_usage = TokenUsage(input_other=5, input_cached=0, output=0)

    # message_delta usage only carries output tokens in practice.
    provider._update_usage(token_usage, MessageDeltaUsage(output_tokens=7))

    assert token_usage.input_other == 5
    assert token_usage.input_cached == 0
    assert token_usage.output == 7


def _tool_use_stream(partial_json: str, start_input: dict) -> bytes:
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "get_time",
                "input": start_input,
            },
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": partial_json},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("partial_json", "start_input", "expected_args"),
    [
        ("", {}, {}),
        ("", {"tz": "UTC"}, {"tz": "UTC"}),
        ('{"tz": "UTC"}', {}, {"tz": "UTC"}),
    ],
)
async def test_anthropic_stream_preserves_empty_and_started_tool_input(
    monkeypatch, partial_json, start_input, expected_args
):
    body = _tool_use_stream(partial_json, start_input)
    transport = sdk_httpx.MockTransport(
        lambda request: sdk_httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )
    )
    monkeypatch.setattr(
        ProviderAnthropic,
        "_create_http_client",
        lambda self, provider_config: sdk_httpx.AsyncClient(transport=transport),
    )
    provider = ProviderAnthropic(
        {
            "id": "test",
            "type": "anthropic_chat_completion",
            "key": ["sk-test"],
            "model": "claude-test",
            "api_base": "https://api.anthropic.test",
        },
        {},
    )
    tools = ToolSet(
        [
            FunctionTool(
                name="get_time",
                description="Return the current time.",
                parameters={"type": "object", "properties": {}},
            )
        ]
    )

    try:
        responses = [
            response
            async for response in provider.text_chat_stream(
                prompt="What time is it?",
                func_tool=tools,
            )
        ]
    finally:
        await provider.terminate()

    tool_chunks = [response for response in responses if response.role == "tool"]
    assert len(tool_chunks) == 1
    for response in (tool_chunks[0], responses[-1]):
        assert response.tools_call_name == ["get_time"]
        assert response.tools_call_args == [expected_args]
        assert response.tools_call_ids == ["toolu_01"]


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True], ids=["standard", "stream"])
async def test_anthropic_requests_merge_custom_server_tools(monkeypatch, streaming):
    custom_tools = [
        {"type": "web_search_20250305", "name": "web_search"},
        {"type": "custom_server_tool", "name": "get_time"},
    ]
    captured_requests = []

    def handle_request(request):
        captured_requests.append(json.loads(request.content))
        if streaming:
            events = [
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-test",
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    },
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "ok"},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 1},
                },
                {"type": "message_stop"},
            ]
            body = "".join(
                f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                for event in events
            )
            return sdk_httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=body.encode(),
            )

        return sdk_httpx.Response(
            200,
            json={
                "id": "msg_1",
                "content": [{"type": "text", "text": "ok"}],
                "model": "claude-test",
                "role": "assistant",
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "type": "message",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    transport = sdk_httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        ProviderAnthropic,
        "_create_http_client",
        lambda self, provider_config: sdk_httpx.AsyncClient(transport=transport),
    )
    provider = ProviderAnthropic(
        {
            "id": "test",
            "type": "anthropic_chat_completion",
            "key": ["sk-test"],
            "model": "claude-test",
            "api_base": "https://api.anthropic.test",
            "custom_extra_body": {"tools": custom_tools, "custom_flag": True},
        },
        {},
    )
    tools = ToolSet(
        [
            FunctionTool(
                name="get_time",
                description="Client-side time tool.",
                parameters={"type": "object", "properties": {}},
            ),
            FunctionTool(
                name="get_weather",
                description="Client-side weather tool.",
                parameters={"type": "object", "properties": {}},
            ),
        ]
    )

    try:
        if streaming:
            responses = [
                response
                async for response in provider.text_chat_stream(
                    prompt="hi",
                    func_tool=tools,
                )
            ]
            assert responses[-1].completion_text == "ok"
        else:
            response = await provider.text_chat(prompt="hi", func_tool=tools)
            assert response.completion_text == "ok"
    finally:
        await provider.terminate()

    assert len(captured_requests) == 1
    request_body = captured_requests[0]
    assert [tool["name"] for tool in request_body["tools"]] == [
        "get_time",
        "get_weather",
        "web_search",
    ]
    assert request_body["tools"][0] == custom_tools[1]
    assert request_body["custom_flag"] is True
    assert provider.provider_config["custom_extra_body"]["tools"] == custom_tools
