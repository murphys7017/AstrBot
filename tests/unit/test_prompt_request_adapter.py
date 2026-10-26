"""Tests for adapting rendered prompt output back into ProviderRequest."""

from __future__ import annotations

import pytest

from astrbot.core.agent.message import (
    AudioURLPart,
    ImageURLPart,
    Message,
    TextPart,
    bind_checkpoint_messages,
)
from astrbot.core.agent.tool import ToolSet
from astrbot.core.prompt.context_types import ContextPack, ContextSlot
from astrbot.core.prompt.render import (
    BasePromptRenderer,
    OutputContract,
    PromptRenderEngine,
    ProviderRequestAdapter,
    RenderResult,
    apply_render_result_to_request,
)
from astrbot.core.provider.entities import ProviderRequest


@pytest.mark.parametrize(
    ("source", "expected_url"),
    [
        (
            {"type": "url", "url": "https://example.com/image.png"},
            "https://example.com/image.png",
        ),
        (
            {"type": "base64", "media_type": "image/png", "data": "aW1hZ2U="},
            "data:image/png;base64,aW1hZ2U=",
        ),
    ],
)
@pytest.mark.parametrize("request_prompt", [None, "Return the persona expression."])
def test_rendered_context_images_are_valid_agent_messages(
    source, expected_url, request_prompt
):
    from astrbot.core.agent.message import bind_checkpoint_messages

    messages = [
        {
            "role": "user",
            "_no_save": True,
            "content": [
                {"type": "text", "text": "Describe this image"},
                {"type": "image", "source": source, "_no_save": True},
            ],
        },
        {"role": "user", "content": "Please answer"},
    ]
    request = ProviderRequest()
    apply_render_result_to_request(
        RenderResult(messages=messages, request_prompt=request_prompt), request
    )

    bound = bind_checkpoint_messages(request.contexts)
    assert bound
    assert request.contexts[0]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": expected_url, "id": None},
        "_no_save": True,
    }
    assert request.contexts[0]["_no_save"] is True
    assert messages[0]["content"][1]["type"] == "image"


def test_render_result_preserves_legacy_positional_field_order():
    messages = [{"role": "user", "content": "hello"}]
    metadata = {"legacy": True}

    result = RenderResult(None, "system", messages, None, None, None, metadata)

    assert result.system_prompt == "system"
    assert result.messages is messages
    assert result.metadata is metadata
    assert result.request_prompt is None


def test_request_adapter_applies_system_prompt_history_and_text_user_message():
    adapter = ProviderRequestAdapter()
    tool_set = ToolSet()
    request = ProviderRequest(
        prompt="old prompt",
        system_prompt="old system",
        contexts=[{"role": "assistant", "content": "old history"}],
        image_urls=["file:///tmp/old.png"],
        audio_urls=["file:///tmp/old.mp3"],
        extra_user_content_parts=[TextPart(text="old extra")],
        func_tool=tool_set,
    )
    result = RenderResult(
        system_prompt="<system>new system</system>",
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "final user input"},
        ],
        tool_schema=[
            {
                "type": "function",
                "function": {
                    "name": "tool_a",
                    "description": "Tool A",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    apply_result = adapter.apply_render_result(result, request)

    assert request.system_prompt == "<system>new system</system>"
    assert request.contexts == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    assert request.prompt == "final user input"
    assert request.extra_user_content_parts == []
    assert request.image_urls == []
    assert request.audio_urls == []
    assert request.func_tool is tool_set
    assert apply_result.applied_system_prompt is True
    assert apply_result.history_message_count == 2
    assert apply_result.used_user_message is True
    assert apply_result.user_content_part_count == 0
    assert apply_result.tool_schema_count == 1
    assert apply_result.warnings == []


def test_transient_prompt_message_is_near_current_input_and_not_cached_in_pack():
    class TransientCollector:
        plugin_id = "transient_state"
        prompt_message_targets = frozenset({"persona"})

        def collect_prompt_messages(
            self,
            event,
            plugin_context,
            *,
            target,
            context_view=None,
            provider_request=None,
        ):
            del event, plugin_context, context_view, provider_request
            if target != "persona":
                return []
            return [{"role": "user", "content": "latest state"}]

    class PluginContext:
        def list_prompt_extension_collectors(self, event=None):
            del event
            return [TransientCollector()]

    pack = ContextPack(
        slots={
            "input.text": ContextSlot(
                name="input.text",
                value="current input",
                category="input",
                source="test",
            )
        }
    )
    result = PromptRenderEngine().render(
        pack,
        target="persona",
        plugin_context=PluginContext(),
    )

    assert result.messages[-1] == {"role": "user", "content": "current input"}
    assert result.messages[-2]["content"] == "latest state"
    assert result.messages[-2]["_no_save"] is True
    assert result.metadata["transient_prompt_message_count"] == 1

    request = ProviderRequest()
    apply_render_result_to_request(result, request)
    assert request.prompt == "current input"
    assert request.contexts[-1]["content"] == "latest state"
    assert "_prompt_message_injector" not in request.contexts[-1]

    core_result = PromptRenderEngine().render(
        pack,
        target="core_planner",
        plugin_context=PluginContext(),
    )
    assert core_result.metadata.get("transient_prompt_message_count", 0) == 0
    assert all(
        message.get("content") != "latest state"
        for message in core_result.messages
    )


def test_transient_prompt_message_drops_provider_unknown_fields():
    class TransientCollector:
        plugin_id = "transient_state"
        prompt_message_targets = frozenset({"persona"})

        def collect_prompt_messages(self, *args, **kwargs):
            del args, kwargs
            return [
                {
                    "role": "user",
                    "content": "latest state",
                    "custom_field": "must not reach provider",
                }
            ]

    class PluginContext:
        def list_prompt_extension_collectors(self, event=None):
            del event
            return [TransientCollector()]

    result = PromptRenderEngine().render(
        ContextPack(
            slots={
                "input.text": ContextSlot(
                    name="input.text",
                    value="current input",
                    category="input",
                    source="test",
                )
            }
        ),
        target="persona",
        plugin_context=PluginContext(),
    )
    request = ProviderRequest()
    apply_render_result_to_request(result, request)

    assert request.contexts[-1] == {
        "role": "user",
        "content": "latest state",
        "_no_save": True,
    }


def test_refresh_transient_prompt_message_replaces_old_state():
    values = iter(("state-1", "state-2"))

    class TransientCollector:
        plugin_id = "transient_state"
        prompt_message_targets = frozenset({"persona"})

        def collect_prompt_messages(self, *args, **kwargs):
            del args, kwargs
            return [{"role": "user", "content": next(values)}]

    class PluginContext:
        def list_prompt_extension_collectors(self, event=None):
            del event
            return [TransientCollector()]

    pack = ContextPack(
        slots={
            "input.text": ContextSlot(
                name="input.text",
                value="current input",
                category="input",
                source="test",
            )
        }
    )
    plugin_context = PluginContext()
    engine = PromptRenderEngine()
    result = engine.render(pack, target="persona", plugin_context=plugin_context)
    request = ProviderRequest()
    apply_render_result_to_request(result, request)
    run_messages = bind_checkpoint_messages(request.contexts)
    for index in request.metadata["_prompt_transient_message_indices"]:
        run_messages[index]._prompt_transient = True
    run_messages.append(Message(role="user", content=request.prompt))

    engine.refresh_transient_prompt_messages(
        provider_request=request,
        run_context_messages=run_messages,
        event=None,
        plugin_context=plugin_context,
        target="persona",
    )

    assert request.contexts[0]["content"] == "state-2"
    assert [
        message.content
        for message in run_messages
        if getattr(message, "_prompt_transient", False)
    ] == ["state-2"]


def test_request_adapter_preserves_internal_context_messages():
    request = ProviderRequest(prompt="old prompt")
    result = RenderResult(
        system_prompt="<system>stable</system>",
        messages=[
            {
                "role": "user",
                "content": "<memory>context</memory>",
                "_no_save": True,
            },
            {"role": "user", "content": "final user input"},
        ],
    )

    apply_result = apply_render_result_to_request(result, request)

    assert request.system_prompt == "<system>stable</system>"
    assert request.contexts == [
        {
            "role": "user",
            "content": "<memory>context</memory>",
            "_no_save": True,
        }
    ]
    assert request.prompt == "final user input"
    assert apply_result.history_message_count == 1
    assert apply_result.used_user_message is True


def test_request_adapter_keeps_rendered_messages_as_context_for_profile_prompt():
    request = ProviderRequest(prompt="old prompt")
    result = RenderResult(
        request_prompt="Classify this context.",
        messages=[
            {"role": "user", "content": "current observation"},
        ],
    )

    apply_result = apply_render_result_to_request(result, request)

    assert request.contexts == [
        {"role": "user", "content": "current observation"},
    ]
    assert request.prompt == "Classify this context."
    assert apply_result.history_message_count == 1
    assert apply_result.used_user_message is True


def test_request_adapter_maps_multimodal_user_content_into_request_parts():
    result = RenderResult(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<request_context>ctx</request_context>"},
                    {"type": "text", "text": "<user_input>hello</user_input>"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "file:///tmp/demo.png", "id": "img-1"},
                    },
                    {
                        "type": "audio_url",
                        "audio_url": {"url": "file:///tmp/demo.mp3", "id": "aud-1"},
                    },
                ],
            }
        ]
    )
    request = ProviderRequest()

    apply_result = apply_render_result_to_request(result, request)

    assert request.prompt == "<request_context>ctx</request_context>"
    assert len(request.extra_user_content_parts) == 3
    assert request.extra_user_content_parts[0] == TextPart(
        text="<user_input>hello</user_input>"
    )
    assert request.extra_user_content_parts[1] == ImageURLPart(
        image_url=ImageURLPart.ImageURL(url="file:///tmp/demo.png", id="img-1")
    )
    assert request.extra_user_content_parts[2] == AudioURLPart(
        audio_url=AudioURLPart.AudioURL(url="file:///tmp/demo.mp3", id="aud-1")
    )
    assert apply_result.user_content_part_count == 4
    assert apply_result.warnings == []


def test_request_adapter_maps_anthropic_image_content_into_request_parts():
    result = RenderResult(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "QUJD",
                        },
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "https://example.com/demo.png",
                        },
                    },
                ],
            }
        ]
    )
    request = ProviderRequest()

    apply_result = apply_render_result_to_request(result, request)

    assert request.prompt == "look"
    assert request.extra_user_content_parts == [
        ImageURLPart(
            image_url=ImageURLPart.ImageURL(url="data:image/png;base64,QUJD")
        ),
        ImageURLPart(
            image_url=ImageURLPart.ImageURL(url="https://example.com/demo.png")
        ),
    ]
    assert apply_result.user_content_part_count == 3
    assert apply_result.warnings == []


def test_request_adapter_keeps_all_messages_as_history_when_no_final_user_exists():
    request = ProviderRequest(prompt="old")
    result = RenderResult(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "assistant only"},
        ]
    )

    apply_result = apply_render_result_to_request(result, request)

    assert request.contexts == [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "assistant only"},
    ]
    assert request.prompt is None
    assert request.extra_user_content_parts == []
    assert apply_result.used_user_message is False
    assert apply_result.history_message_count == 2


def test_request_adapter_preserves_runtime_only_fields_when_applying_visible_prompt():
    tool_set = ToolSet()
    conversation = object()
    tool_calls_result = ["tool-result"]
    request = ProviderRequest(
        prompt="old prompt",
        session_id="session-1",
        model="gpt-test",
        func_tool=tool_set,
        conversation=conversation,
        tool_calls_result=tool_calls_result,
    )
    result = RenderResult(
        system_prompt="<system>new system</system>",
        messages=[{"role": "user", "content": "new prompt"}],
    )

    apply_result = apply_render_result_to_request(result, request)

    assert request.prompt == "new prompt"
    assert request.system_prompt == "<system>new system</system>"
    assert request.session_id == "session-1"
    assert request.model == "gpt-test"
    assert request.func_tool is tool_set
    assert request.conversation is conversation
    assert request.tool_calls_result == tool_calls_result
    assert apply_result.used_user_message is True


def test_request_adapter_applies_output_contract_to_provider_request():
    request = ProviderRequest()
    output_contract = OutputContract(
        mode="tool_call",
        strict=True,
        schema={"type": "object", "properties": {"value": {"type": "string"}}},
        preferred_tool_name="interaction_decision",
        allow_text_fallback=False,
    )
    pack = ContextPack(slots={})
    pack.meta["output_contract"] = output_contract.to_dict()
    compiled_contract = PromptRenderEngine(
        default_renderer=BasePromptRenderer()
    ).render(pack).compiled_output_contract
    result = RenderResult(
        messages=[{"role": "user", "content": "new prompt"}],
        output_contract=output_contract,
        compiled_output_contract=compiled_contract,
    )

    apply_render_result_to_request(result, request)

    assert request.output_contract is not None
    assert request.output_contract.mode == "tool_call"
    assert request.output_contract.preferred_tool_name == "interaction_decision"
    assert request.compiled_output_contract == compiled_contract


def test_base_renderer_compiles_prompt_only_output_contract_with_fallback():
    output_contract = OutputContract(
        mode="tool_call",
        strict=True,
        schema={"type": "object", "properties": {"value": {"type": "string"}}},
        preferred_tool_name="structured_output",
        allow_text_fallback=False,
    )
    pack = ContextPack(slots={})
    pack.meta["output_contract"] = output_contract.to_dict()

    result = PromptRenderEngine(default_renderer=BasePromptRenderer()).render(pack)

    assert result.compiled_output_contract is not None
    assert result.compiled_output_contract.strategy == "prompt_only"
    assert result.compiled_output_contract.degraded is True
    assert (
        result.compiled_output_contract.degrade_reason
        == "renderer_has_no_protocol_support"
    )
    assert "在无法使用协议级 tool call 时" in (
        result.compiled_output_contract.fallback_prompt_text or ""
    )
    assert "`structured_output` 工具调用参数对应的单个 JSON object" in (
        result.compiled_output_contract.fallback_prompt_text or ""
    )


def test_base_renderer_treats_strict_json_object_as_native_prompt_only_contract():
    output_contract = OutputContract(
        mode="json_object",
        strict=True,
        schema={"type": "object", "properties": {"value": {"type": "string"}}},
        allow_text_fallback=False,
    )
    pack = ContextPack(slots={})
    pack.meta["output_contract"] = output_contract.to_dict()

    result = PromptRenderEngine(default_renderer=BasePromptRenderer()).render(pack)

    assert result.compiled_output_contract is not None
    assert result.compiled_output_contract.strategy == "prompt_only"
    assert result.compiled_output_contract.degraded is False
    assert result.compiled_output_contract.degrade_reason is None
    assert "只输出一个 JSON object" in (
        result.compiled_output_contract.fallback_prompt_text or ""
    )


def test_request_adapter_skips_invalid_user_parts_without_touching_tool_runtime():
    tool_set = ToolSet()
    request = ProviderRequest(func_tool=tool_set)
    result = RenderResult(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "image_url", "image_url": {}},
                    {"type": "unsupported", "value": "nope"},
                ],
            }
        ],
        tool_schema=[{"type": "function", "function": {"name": "tool_a"}}],
    )

    apply_result = apply_render_result_to_request(result, request)

    assert request.func_tool is tool_set
    assert request.prompt == "hello"
    assert request.extra_user_content_parts == []
    assert apply_result.tool_schema_count == 1
    assert len(apply_result.warnings) == 2


@pytest.mark.asyncio
async def test_request_adapter_reconstructs_rendered_user_message_order():
    pack = ContextPack(
        slots={
            "session.user_info": ContextSlot(
                name="session.user_info",
                value={
                    "user_id": "u1",
                    "nickname": "Alice",
                    "platform_name": "qq",
                    "umo": "qq:group:1",
                    "group_id": "1",
                    "group_name": "AstrBot Dev",
                    "is_group": True,
                },
                category="session",
                source="test",
            ),
            "input.text": ContextSlot(
                name="input.text",
                value="Check this image",
                category="input",
                source="test",
            ),
            "input.images": ContextSlot(
                name="input.images",
                value=[
                    {
                        "ref": "file:///tmp/demo.png",
                        "transport": "file",
                        "source": "current",
                    }
                ],
                category="input",
                source="test",
            ),
        }
    )
    engine = PromptRenderEngine(default_renderer=BasePromptRenderer())
    rendered = engine.render(pack)
    request = ProviderRequest()

    apply_render_result_to_request(rendered, request)
    assembled_message = await request.assemble_context()

    assert assembled_message == {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    "<request_context>\n"
                    "  <session>\n"
                    "    <user_info>\n"
                    "      <nickname>Alice</nickname>\n"
                    "      <platform_name>qq</platform_name>\n"
                    "      <group_name>AstrBot Dev</group_name>\n"
                    "      <is_group>true</is_group>\n"
                    "    </user_info>\n"
                    "  </session>\n"
                    "</request_context>"
                ),
            },
            {
                "type": "text",
                "text": "<user_input>\n  <text>Check this image</text>\n</user_input>",
            },
            {
                "type": "image_url",
                "image_url": {"url": "file:///tmp/demo.png", "id": None},
            },
        ],
    }


@pytest.mark.asyncio
async def test_provider_request_assemble_context_places_extra_text_before_media():
    request = ProviderRequest(
        prompt="Current request",
        extra_user_content_parts=[
            ImageURLPart(
                image_url=ImageURLPart.ImageURL(url="file:///tmp/plugin.png")
            ),
            TextPart(text="Plugin context"),
        ],
    )

    assembled_message = await request.assemble_context()

    assert [
        part["type"] for part in assembled_message["content"]
    ] == ["text", "text", "image_url"]
    assert assembled_message["content"][1]["text"] == "Plugin context"
