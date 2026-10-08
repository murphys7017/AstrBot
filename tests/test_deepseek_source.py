import asyncio
from types import SimpleNamespace

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.output_contract import OutputContract
from astrbot.core.prompt.context_types import ContextPack
from astrbot.core.prompt.render import PromptRenderEngine
from astrbot.core.provider import supports_strict_tool_call_output_contract
from astrbot.core.provider.output_contract_tools import (
    build_single_tool_set_from_contract,
)
from astrbot.core.provider.sources.deepseek_source import ProviderDeepSeek


def _make_provider(overrides: dict | None = None) -> ProviderDeepSeek:
    provider_config = {
        "id": "test-deepseek",
        "type": "deepseek_chat_completion",
        "model": "deepseek-v4-flash",
        "key": ["test-key"],
        "custom_extra_body": {},
    }
    if overrides:
        provider_config.update(overrides)
    return ProviderDeepSeek(
        provider_config=provider_config,
        provider_settings={},
    )


def test_deepseek_uses_protocol_tool_call_output_contract():
    pack = ContextPack(slots={})
    pack.meta["output_contract"] = OutputContract(
        mode="tool_call",
        strict=True,
        schema={"type": "object", "properties": {}},
        preferred_tool_name="persona_expression",
        allow_text_fallback=False,
    ).to_dict()

    result = PromptRenderEngine().render(
        pack,
        provider_request=type(
            "RequestStub",
            (),
            {"provider_type": "deepseek_chat_completion"},
        )(),
    )

    assert result.metadata["renderer_name"] == "openai"
    assert result.compiled_output_contract is not None
    assert result.compiled_output_contract.strategy == "protocol_tool_call"
    assert result.compiled_output_contract.tool_name == "persona_expression"
    assert result.compiled_output_contract.degraded is False


def test_deepseek_thinking_mode_rejects_strict_tool_call_contract():
    provider = _make_provider(
        {
            "api_base": "https://api.deepseek.com/beta",
            "reasoning": True,
        }
    )
    contract = OutputContract(
        mode="tool_call",
        strict=True,
        schema={"type": "object", "properties": {}},
        preferred_tool_name="persona_expression",
        allow_text_fallback=False,
    )

    try:
        assert not provider.supports_output_contract_strategy("protocol_tool_call")
        assert not supports_strict_tool_call_output_contract(provider, contract)
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_non_thinking_mode_allows_strict_tool_call_contract():
    provider = _make_provider(
        {
            "api_base": "https://api.deepseek.com/beta",
            "reasoning": False,
        }
    )
    contract = OutputContract(
        mode="tool_call",
        strict=True,
        schema={"type": "object", "properties": {}},
        preferred_tool_name="persona_expression",
        allow_text_fallback=False,
    )

    try:
        assert provider.supports_output_contract_strategy("protocol_tool_call")
        assert supports_strict_tool_call_output_contract(provider, contract)
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_reasoning_enabled_maps_to_thinking_and_drops_unsupported_tool_choice():
    provider = _make_provider(
        {
            "reasoning": True,
            "custom_extra_body": {
                "thinking": {"type": "disabled"},
                "tool_choice": "required",
            },
        }
    )
    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "required",
        }

        normalized_payloads, extra_body, _ = provider._prepare_request(payloads, None)

        assert "tool_choice" not in normalized_payloads
        assert "tool_choice" not in extra_body
        assert extra_body["thinking"]["type"] == "enabled"
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_reasoning_disabled_maps_to_thinking_and_keeps_tool_choice():
    provider = _make_provider(
        {
            "reasoning": "false",
            "custom_extra_body": {
                "thinking": {"type": "enabled"},
            },
        }
    )
    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "required",
        }

        normalized_payloads, extra_body, _ = provider._prepare_request(payloads, None)

        assert normalized_payloads["tool_choice"] == "required"
        assert extra_body["thinking"]["type"] == "disabled"
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_custom_tool_choice_is_removed_in_thinking_mode():
    provider = _make_provider(
        {
            "reasoning": True,
            "custom_extra_body": {
                "tool_choice": "required",
            },
        }
    )
    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
        }

        normalized_payloads, extra_body, _ = provider._prepare_request(payloads, None)

        assert "tool_choice" not in normalized_payloads
        assert "tool_choice" not in extra_body
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_legacy_thinking_config_is_used_without_reasoning_setting():
    provider = _make_provider(
        {
            "custom_extra_body": {
                "thinking": {"type": "disabled"},
            }
        }
    )
    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "required",
        }

        normalized_payloads, extra_body, _ = provider._prepare_request(payloads, None)

        assert normalized_payloads["tool_choice"] == "required"
        assert extra_body["thinking"]["type"] == "disabled"
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_default_thinking_mode_drops_unsupported_tool_choice():
    provider = _make_provider()
    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "required",
        }

        normalized_payloads, extra_body, _ = provider._prepare_request(payloads, None)

        assert provider._is_thinking_enabled(normalized_payloads, extra_body) is True
        assert "tool_choice" not in normalized_payloads

        assert "tool_choice" not in extra_body
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_non_beta_endpoint_rejects_strict_tool_call_contract():
    provider = _make_provider(
        {
            "reasoning": False,
        }
    )
    contract = OutputContract(
        mode="tool_call",
        strict=True,
        schema={"type": "object", "properties": {}},
        preferred_tool_name="persona_expression",
        allow_text_fallback=False,
    )

    try:
        assert not provider.supports_output_contract_strategy("protocol_tool_call")
        assert not supports_strict_tool_call_output_contract(provider, contract)
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_beta_endpoint_enables_strict_tools_and_normalizes_schema():
    provider = _make_provider(
        {
            "api_base": "https://api.deepseek.com/beta",
            "reasoning": False,
        }
    )
    source_schema = {
        "type": "object",
        "properties": {
            "effect_calls": {
                "type": "array",
                "items": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "name": {"const": "demo.effect"},
                                "arguments": {
                                    "type": "object",
                                    "properties": {"message": {"type": "string"}},
                                    "required": ["message"],
                                    "additionalProperties": False,
                                },
                            },
                            "required": ["name", "arguments"],
                            "additionalProperties": False,
                        }
                    ]
                },
            },
            "ref_value": {"$ref": "#/$def/author"},
        },
        "required": ["effect_calls", "ref_value"],
        "additionalProperties": False,
        "$def": {
            "author": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            }
        },
    }
    tools = build_single_tool_set_from_contract(
        OutputContract(
            mode="tool_call",
            strict=True,
            schema=source_schema,
            preferred_tool_name="persona_expression",
            allow_text_fallback=False,
        )
    )
    assert tools is not None

    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "required",
        }

        normalized_payloads, extra_body, _ = provider._prepare_request(
            payloads,
            tools,
        )

        function = normalized_payloads["tools"][0]["function"]
        parameters = function["parameters"]
        effect_calls = parameters["properties"]["effect_calls"]
        effect_branch = effect_calls["items"]["anyOf"][0]

        assert extra_body["thinking"]["type"] == "disabled"
        assert function["strict"] is True
        assert parameters["required"] == ["effect_calls", "ref_value"]
        assert parameters["additionalProperties"] is False
        assert effect_branch["properties"]["name"] == {
            "type": "string",
            "enum": ["demo.effect"],
        }
        assert effect_branch["required"] == ["name", "arguments"]
        assert effect_branch["additionalProperties"] is False
        assert parameters["properties"]["ref_value"] == {"$ref": "#/$def/author"}
        assert parameters["$def"]["author"]["required"] == ["name"]
        assert source_schema["properties"]["effect_calls"]["items"]["anyOf"]
        assert source_schema["additionalProperties"] is False
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_beta_endpoint_falls_back_for_unsupported_strict_schema():
    provider = _make_provider(
        {
            "api_base": "https://api.deepseek.com/beta",
            "reasoning": False,
        }
    )
    source_schema = {
        "type": "object",
        "properties": {
            "effect_calls": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {"name": {"const": "demo.effect"}},
                            "required": ["name"],
                        }
                    ]
                },
            },
            "empty": {"type": "array", "items": False},
        },
        "required": ["effect_calls", "empty"],
        "additionalProperties": False,
    }
    tools = build_single_tool_set_from_contract(
        OutputContract(
            mode="tool_call",
            strict=True,
            schema=source_schema,
            preferred_tool_name="persona_expression",
            allow_text_fallback=False,
        )
    )
    assert tools is not None

    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "required",
        }

        normalized_payloads, _, _ = provider._prepare_request(payloads, tools)

        function = normalized_payloads["tools"][0]["function"]
        assert "strict" not in function
        assert function["parameters"] == source_schema
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_beta_endpoint_falls_back_without_changing_schema_semantics():
    provider = _make_provider(
        {
            "api_base": "https://api.deepseek.com/beta",
            "reasoning": False,
        }
    )
    source_schema = {
        "type": "object",
        "properties": {
            "value": {
                "type": "string",
                "contentMediaType": "application/json",
                "contentSchema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["value"],
        "additionalProperties": False,
    }
    tools = build_single_tool_set_from_contract(
        OutputContract(
            mode="tool_call",
            strict=True,
            schema=source_schema,
            preferred_tool_name="persona_expression",
            allow_text_fallback=False,
        )
    )
    assert tools is not None

    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "required",
        }

        normalized_payloads, _, _ = provider._prepare_request(payloads, tools)

        function = normalized_payloads["tools"][0]["function"]
        assert "strict" not in function
        assert function["parameters"] == source_schema
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_beta_endpoint_does_not_close_open_object_schema():
    provider = _make_provider(
        {
            "api_base": "https://api.deepseek.com/beta",
            "reasoning": False,
        }
    )
    source_schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }
    tools = build_single_tool_set_from_contract(
        OutputContract(
            mode="tool_call",
            strict=True,
            schema=source_schema,
            preferred_tool_name="persona_expression",
            allow_text_fallback=False,
        )
    )
    assert tools is not None

    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "required",
        }

        normalized_payloads, _, _ = provider._prepare_request(payloads, tools)

        function = normalized_payloads["tools"][0]["function"]
        assert "strict" not in function
        assert function["parameters"] == source_schema
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_non_strict_tool_request_keeps_original_schema():
    provider = _make_provider(
        {
            "api_base": "https://api.deepseek.com/beta",
            "reasoning": False,
        }
    )
    source_schema = {
        "type": "object",
        "properties": {
            "value": {"type": "string", "minLength": 2},
        },
        "required": [],
    }
    tools = ToolSet(
        [
            FunctionTool(
                name="demo_tool",
                description="Demo tool.",
                parameters=source_schema,
                handler=None,
            )
        ]
    )

    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "required",
        }
        normalized_payloads, _, _ = provider._prepare_request(payloads, tools)

        function = normalized_payloads["tools"][0]["function"]
        assert "strict" not in function
        assert function["parameters"] == source_schema
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_strict_conversion_only_marks_contract_tool():
    provider = _make_provider(
        {
            "api_base": "https://api.deepseek.com/beta",
            "reasoning": False,
        }
    )
    contract_tools = build_single_tool_set_from_contract(
        OutputContract(
            mode="tool_call",
            strict=True,
            schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            preferred_tool_name="persona_expression",
            allow_text_fallback=False,
        )
    )
    assert contract_tools is not None
    ordinary_tool = FunctionTool(
        name="ordinary_tool",
        description="Ordinary tool.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string", "minLength": 2}},
            "required": [],
        },
        handler=None,
    )
    tools = ToolSet([ordinary_tool, *contract_tools.tools])

    try:
        payloads = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "required",
        }
        normalized_payloads, _, _ = provider._prepare_request(payloads, tools)

        functions = {
            tool["function"]["name"]: tool["function"]
            for tool in normalized_payloads["tools"]
        }
        assert functions["persona_expression"]["strict"] is True
        assert functions["ordinary_tool"].get("strict") is None
        assert functions["ordinary_tool"]["parameters"] == ordinary_tool.parameters
    finally:
        asyncio.run(provider.terminate())


def test_deepseek_non_thinking_payload_does_not_inject_empty_reasoning_content():
    provider = ProviderDeepSeek.__new__(ProviderDeepSeek)
    provider.provider_config = {
        "reasoning": False,
        "custom_extra_body": {},
    }
    provider.client = SimpleNamespace(base_url=SimpleNamespace(host="api.deepseek.com"))

    payloads = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "assistant", "content": "previous reply"}],
    }

    provider._finally_convert_payload(payloads)

    assert "reasoning_content" not in payloads["messages"][0]


def test_deepseek_non_thinking_payload_removes_existing_reasoning_content():
    provider = ProviderDeepSeek.__new__(ProviderDeepSeek)
    provider.provider_config = {
        "reasoning": False,
        "custom_extra_body": {},
    }
    provider.client = SimpleNamespace(base_url=SimpleNamespace(host="api.deepseek.com"))

    payloads = {
        "model": "deepseek-v4-flash",
        "messages": [
            {
                "role": "assistant",
                "content": "previous reply",
                "reasoning_content": "old thinking",
            }
        ],
    }

    provider._finally_convert_payload(payloads)

    assert payloads["messages"][0]["content"] == "previous reply"
    assert "reasoning_content" not in payloads["messages"][0]


def test_deepseek_thinking_payload_keeps_empty_reasoning_content_for_history():
    provider = ProviderDeepSeek.__new__(ProviderDeepSeek)
    provider.provider_config = {
        "reasoning": True,
        "custom_extra_body": {},
    }
    provider.client = SimpleNamespace(base_url=SimpleNamespace(host="api.deepseek.com"))

    payloads = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "assistant", "content": "previous reply"}],
    }

    provider._finally_convert_payload(payloads)

    assert payloads["messages"][0]["reasoning_content"] == ""


def test_deepseek_thinking_tool_call_preserves_reasoning_content_for_next_request():
    provider = ProviderDeepSeek.__new__(ProviderDeepSeek)
    provider.provider_config = {
        "reasoning": True,
        "custom_extra_body": {},
    }
    provider.client = SimpleNamespace(base_url=SimpleNamespace(host="api.deepseek.com"))

    payloads = {
        "model": "deepseek-v4-flash",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "think", "think": "I should call the tool."},
                ],
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "demo_tool",
                            "arguments": "{}",
                        },
                    }
                ],
            }
        ],
    }

    provider._finally_convert_payload(payloads)

    assistant = payloads["messages"][0]
    assert assistant["reasoning_content"] == "I should call the tool."
    assert assistant["content"] is None
    assert assistant["tool_calls"][0]["function"]["name"] == "demo_tool"
