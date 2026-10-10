import asyncio
from types import SimpleNamespace

import pytest
from openai.types.responses.response_input_param import ResponseInputParam
from pydantic import TypeAdapter

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.sources.openai_responses_source import (
    ProviderOpenAIResponses,
)


def _provider() -> ProviderOpenAIResponses:
    provider = ProviderOpenAIResponses.__new__(ProviderOpenAIResponses)
    provider.provider_config = {}
    provider.store_responses = False
    provider.default_params = {
        "model",
        "input",
        "instructions",
        "tools",
        "tool_choice",
        "store",
        "temperature",
        "reasoning",
        "text",
    }
    return provider


def test_messages_are_converted_to_responses_input_items():
    instructions, response_input = ProviderOpenAIResponses._messages_to_response_input(
        [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Call the tool."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "weather", "arguments": '{"city":"上海"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "晴天",
            },
        ]
    )

    assert instructions == "Be concise."
    assert response_input == [
        {"role": "user", "content": "Call the tool."},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "weather",
            "arguments": '{"city":"上海"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "晴天",
        },
    ]


def test_assistant_text_before_tool_call_is_preserved():
    _, response_input = ProviderOpenAIResponses._messages_to_response_input(
        [
            {
                "role": "assistant",
                "content": "I will check that.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "weather", "arguments": "{}"},
                    }
                ],
            }
        ]
    )

    assert response_input == [
        {"role": "assistant", "content": "I will check that."},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "weather",
            "arguments": "{}",
        },
    ]


def test_converted_history_is_accepted_by_openai_responses_schema():
    _, response_input = ProviderOpenAIResponses._messages_to_response_input(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Inspect these."},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,aa"},
                    },
                    {
                        "type": "input_image",
                        "image_url": "data:image/jpeg;base64,bb",
                        "detail": "low",
                    },
                ],
            }
        ]
    )

    TypeAdapter(ResponseInputParam).validate_python(response_input)


def test_audio_input_is_rejected_by_responses_adapter():
    try:
        ProviderOpenAIResponses._messages_to_response_input(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": "aa", "format": "wav"},
                        }
                    ],
                }
            ]
        )
    except ValueError as exc:
        assert "音频输入" in str(exc)
    else:
        raise AssertionError("audio input should be rejected")


def test_tools_are_converted_to_responses_schema():
    tools = ToolSet(
        [
            FunctionTool(
                name="weather",
                description="Get weather.",
                parameters={
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            )
        ]
    )

    assert ProviderOpenAIResponses._responses_tools(tools) == [
        {
            "type": "function",
            "name": "weather",
            "description": "Get weather.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]


def test_response_is_parsed_into_llm_response():
    response = SimpleNamespace(
        id="resp_1",
        output_text="Done",
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call_1",
                id="fc_1",
                name="weather",
                arguments='{"city":"上海"}',
            )
        ],
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=4,
            input_tokens_details=SimpleNamespace(cached_tokens=2),
        ),
    )

    parsed = ProviderOpenAIResponses._parse_response(response, ToolSet([]))

    assert parsed.id == "resp_1"
    assert parsed.completion_text == "Done"
    assert parsed.tools_call_name == ["weather"]
    assert parsed.tools_call_ids == ["call_1"]
    assert parsed.tools_call_args == [{"city": "上海"}]
    assert parsed.usage.input_other == 8
    assert parsed.usage.input_cached == 2


def test_response_request_options_keep_unknown_fields_in_extra_body():
    provider = _provider()
    provider.provider_config = {"custom_extra_body": {"temperature": 0.7}}

    request = provider._request_options(
        {"model": "gpt-5", "input": [], "vendor_flag": True},
        None,
        "auto",
    )

    assert request["temperature"] == 0.7
    assert request["extra_body"] == {"vendor_flag": True}
    assert request["store"] is False


def test_response_request_options_preserve_native_output_format_parameter():
    provider = _provider()
    text_format = {
        "format": {
            "type": "json_schema",
            "name": "provider_output_test",
            "strict": True,
            "schema": {"type": "object"},
        }
    }

    request = provider._request_options(
        {"model": "test-model", "input": [], "text": text_format},
        None,
        "auto",
    )

    assert request["text"] == text_format
    assert "extra_body" not in request


@pytest.mark.asyncio
async def test_responses_native_json_schema_test_sets_text_format_and_stops_after_one_call():
    provider = _provider()
    provider.provider_config = {"type": "openai_responses"}
    provider.chosen_api_key = "test-key"
    provider.client = SimpleNamespace(api_key="")
    schema = {
        "type": "object",
        "properties": {"speech": {"type": "string"}},
        "required": ["speech"],
        "additionalProperties": False,
    }
    calls = []

    async def prepare(*_args, **_kwargs):
        return {"model": "test-model", "input": []}, []

    async def query(payload, *_args, **_kwargs):
        calls.append(payload)
        raise RuntimeError("json_schema unavailable")

    provider._prepare_response_payload = prepare
    provider._query = query

    with pytest.raises(RuntimeError, match="json_schema unavailable"):
        await provider.text_chat_for_output_format_test(
            prompt="Return JSON.",
            output_format="json",
            mode="provider_native_json_schema",
            schema=schema,
        )

    assert len(calls) == 1
    assert calls[0]["text"] == {
        "format": {
            "type": "json_schema",
            "name": "provider_output_test",
            "strict": True,
            "schema": schema,
        }
    }


@pytest.mark.asyncio
async def test_responses_legacy_json_output_test_mode_is_consumed_before_payload_build():
    provider = _provider()
    provider.provider_config = {"type": "openai_responses"}
    provider.chosen_api_key = "test-key"
    provider.client = SimpleNamespace(api_key="")
    calls = []

    async def prepare(*_args, **kwargs):
        calls.append(kwargs)
        return {"model": "test-model", "input": []}, []

    async def query(payload, *_args, **_kwargs):
        calls.append(payload)
        return LLMResponse(role="assistant", completion_text="{}")

    provider._prepare_response_payload = prepare
    provider._query = query

    response = await provider.text_chat_for_json_output_test(
        prompt="Return JSON.",
        mode="provider_native_json",
    )

    assert response.completion_text == "{}"
    assert calls[-1]["text"] == {"format": {"type": "json_object"}}
    assert all(
        "_json_output_test_mode" not in item
        for item in calls
        if isinstance(item, dict)
    )


def test_response_request_options_drop_provider_only_abort_signal():
    provider = _provider()
    abort_signal = asyncio.Event()

    request = provider._request_options(
        {"model": "gpt-5", "input": [], "abort_signal": abort_signal},
        None,
        "auto",
    )

    assert "abort_signal" not in request
    assert "extra_body" not in request


def test_response_request_options_drop_provider_only_abort_signal_from_custom_body():
    provider = _provider()
    provider.provider_config = {
        "custom_extra_body": {
            "abort_signal": asyncio.Event(),
            "vendor_flag": True,
        }
    }

    request = provider._request_options(
        {"model": "gpt-5", "input": []},
        None,
        "auto",
    )

    assert "abort_signal" not in request
    assert request["extra_body"] == {"vendor_flag": True}


def test_response_request_options_translate_disabled_reasoning():
    provider = _provider()
    provider.provider_config = {"reasoning": False}

    request = provider._request_options(
        {"model": "gpt-5.6-luna", "input": []},
        None,
        "auto",
    )

    assert request["reasoning"] == {"effort": "none"}


def test_response_request_options_keep_explicit_reasoning_override():
    provider = _provider()
    provider.provider_config = {
        "reasoning": False,
        "custom_extra_body": {"reasoning": {"effort": "low"}},
    }

    request = provider._request_options(
        {"model": "gpt-5.6-luna", "input": []},
        None,
        "auto",
    )

    assert request["reasoning"] == {"effort": "low"}
