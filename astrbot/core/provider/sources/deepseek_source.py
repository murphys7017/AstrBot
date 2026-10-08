import copy
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlsplit

from openai.lib.streaming.chat._completions import ChatCompletionStreamState
from openai.types.chat.chat_completion import ChatCompletion

import astrbot.core.message.components as Comp
from astrbot import logger
from astrbot.core.agent.tool import ToolSet
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import LLMResponse

from ..headers import build_conversation_headers
from ..register import register_provider_adapter
from .openai_source import ProviderOpenAIOfficial


class _DeepSeekStrictSchemaUnsupported(ValueError):
    """Raised when a schema cannot be represented without changing meaning."""


_DEEPSEEK_SCHEMA_ANNOTATION_KEYS = frozenset({"title", "examples", "$comment"})


def _deepseek_json_type(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return None


def _reject_unsupported_schema_keys(
    schema: dict[str, Any],
    supported_keys: set[str],
) -> None:
    unsupported = set(schema) - supported_keys - _DEEPSEEK_SCHEMA_ANNOTATION_KEYS
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise _DeepSeekStrictSchemaUnsupported(
            f"unsupported schema keyword(s): {names}"
        )


def _normalize_deepseek_strict_schema(schema: object) -> dict[str, Any]:
    """Convert a JSON Schema to the subset accepted by DeepSeek strict mode.

    DeepSeek validates strict tool schemas on the ``/beta`` endpoint. The
    provider's regular tool schemas are shared with other providers, so this
    conversion intentionally happens only while preparing a DeepSeek strict
    request and never mutates the source schema.
    """

    if not isinstance(schema, dict):
        raise _DeepSeekStrictSchemaUnsupported("schema must be an object")

    source = copy.deepcopy(schema)
    result: dict[str, Any] = {}
    if isinstance(source.get("description"), str):
        result["description"] = source["description"]

    if "$ref" in source:
        if not isinstance(source["$ref"], str):
            raise _DeepSeekStrictSchemaUnsupported("$ref must be a string")
        result["$ref"] = source["$ref"]

    if "$def" in source:
        definitions = source["$def"]
        if not isinstance(definitions, dict):
            raise _DeepSeekStrictSchemaUnsupported("$def must be an object")
        result["$def"] = {
            str(name): _normalize_deepseek_strict_schema(definition)
            for name, definition in definitions.items()
        }

    if "oneOf" in source:
        raise _DeepSeekStrictSchemaUnsupported(
            "oneOf is not representable without changing its exclusivity"
        )
    if "allOf" in source or "not" in source:
        raise _DeepSeekStrictSchemaUnsupported(
            "allOf/not are not representable in DeepSeek strict mode"
        )

    if "$ref" in source:
        _reject_unsupported_schema_keys(
            source,
            {"$ref", "$def", "description"},
        )
        return result

    if "anyOf" in source:
        any_of = source["anyOf"]
        if not isinstance(any_of, list) or not any_of:
            raise _DeepSeekStrictSchemaUnsupported("anyOf must be a non-empty list")
        _reject_unsupported_schema_keys(
            source,
            {"anyOf", "$def", "description"},
        )
        normalized_branches = []
        for branch in any_of:
            if not isinstance(branch, dict):
                raise _DeepSeekStrictSchemaUnsupported(
                    "anyOf branches must be schema objects"
                )
            normalized_branches.append(_normalize_deepseek_strict_schema(branch))
        result["anyOf"] = normalized_branches
        return result

    raw_type = source.get("type")
    if isinstance(raw_type, list):
        if any(type_name == "null" for type_name in raw_type):
            raise _DeepSeekStrictSchemaUnsupported(
                "null is not representable in DeepSeek strict mode"
            )
        if len(raw_type) != 1 or not isinstance(raw_type[0], str):
            raise _DeepSeekStrictSchemaUnsupported(
                "multi-type schemas are not representable safely"
            )
        raw_type = raw_type[0]

    if raw_type is None:
        if isinstance(source.get("properties"), dict):
            raw_type = "object"
        elif "items" in source:
            raw_type = "array"
        elif "const" in source:
            raw_type = _deepseek_json_type(source["const"])
        elif isinstance(source.get("enum"), list) and source["enum"]:
            enum_types = {_deepseek_json_type(value) for value in source["enum"]}
            if None in enum_types or "null" in enum_types:
                raise _DeepSeekStrictSchemaUnsupported(
                    "enum values must use supported non-null JSON types"
                )
            if enum_types <= {"integer", "number"}:
                raw_type = "number" if "number" in enum_types else "integer"
            elif len(enum_types) == 1:
                raw_type = next(iter(enum_types))
            else:
                raise _DeepSeekStrictSchemaUnsupported(
                    "mixed-type enum values are not representable safely"
                )

    if raw_type is None and "const" in source and source["const"] is None:
        raise _DeepSeekStrictSchemaUnsupported(
            "null is not representable in DeepSeek strict mode"
        )

    if raw_type not in {"object", "array", "string", "number", "integer", "boolean"}:
        raise _DeepSeekStrictSchemaUnsupported(
            "schema has no supported DeepSeek strict type"
        )

    common_keys = {"type", "description", "$def"}
    if "enum" in source:
        enum_values = source["enum"]
        if not isinstance(enum_values, list) or not enum_values:
            raise _DeepSeekStrictSchemaUnsupported("enum must be a non-empty list")
        if any(_deepseek_json_type(value) is None for value in enum_values):
            raise _DeepSeekStrictSchemaUnsupported("enum has an unsupported value")
        if "null" in {_deepseek_json_type(value) for value in enum_values}:
            raise _DeepSeekStrictSchemaUnsupported(
                "null is not representable in DeepSeek strict mode"
            )
        for value in enum_values:
            value_type = _deepseek_json_type(value)
            matches_type = value_type == raw_type or (
                raw_type == "number" and value_type == "integer"
            )
            if not matches_type:
                raise _DeepSeekStrictSchemaUnsupported(
                    "enum value does not match its declared type"
                )
        result["enum"] = copy.deepcopy(enum_values)

    if "const" in source:
        const_value = source["const"]
        if const_value is None:
            raise _DeepSeekStrictSchemaUnsupported(
                "null is not representable in DeepSeek strict mode"
            )
        if "enum" in source:
            raise _DeepSeekStrictSchemaUnsupported(
                "const combined with enum is not representable safely"
            )
        if raw_type in {"number", "integer"}:
            if isinstance(const_value, bool) or not isinstance(
                const_value, (int, float)
            ):
                raise _DeepSeekStrictSchemaUnsupported(
                    "numeric const must have a numeric value"
                )
            if raw_type == "integer" and not isinstance(const_value, int):
                raise _DeepSeekStrictSchemaUnsupported(
                    "integer const must have an integer value"
                )
            result["const"] = copy.deepcopy(const_value)
        elif raw_type in {"string", "boolean"}:
            if _deepseek_json_type(const_value) != raw_type:
                raise _DeepSeekStrictSchemaUnsupported(
                    "const value does not match its declared type"
                )
            result["enum"] = [copy.deepcopy(const_value)]
        else:
            raise _DeepSeekStrictSchemaUnsupported(
                "const is unsupported for this schema type"
            )

    if raw_type == "object":
        _reject_unsupported_schema_keys(
            source,
            common_keys | {"properties", "required", "additionalProperties"},
        )
        properties = source.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        required = source.get("required", [])
        if (
            not isinstance(required, list)
            or any(not isinstance(name, str) for name in required)
            or len(required) != len(set(required))
        ):
            raise _DeepSeekStrictSchemaUnsupported(
                "object required must contain unique property names"
            )
        if any(not isinstance(name, str) for name in properties):
            raise _DeepSeekStrictSchemaUnsupported(
                "object property names must be strings"
            )
        property_names = set(properties)
        required_names = set(required)
        if property_names != required_names:
            raise _DeepSeekStrictSchemaUnsupported(
                "DeepSeek strict mode cannot preserve optional object properties"
            )
        if source.get("additionalProperties") is not False:
            raise _DeepSeekStrictSchemaUnsupported(
                "additionalProperties must be false in strict mode"
            )
        normalized_properties: dict[str, Any] = {}
        for name, property_schema in properties.items():
            if not isinstance(property_schema, dict):
                raise _DeepSeekStrictSchemaUnsupported(
                    "boolean property schemas are not representable safely"
                )
            normalized_properties[name] = _normalize_deepseek_strict_schema(
                property_schema
            )
        result["type"] = "object"
        result["properties"] = normalized_properties
        # DeepSeek strict mode requires every object property to be required.
        result["required"] = list(normalized_properties)
        result["additionalProperties"] = False
        return result

    if raw_type == "array":
        _reject_unsupported_schema_keys(source, common_keys | {"items"})
        items = source.get("items")
        if isinstance(items, dict):
            normalized_items = _normalize_deepseek_strict_schema(items)
        elif isinstance(items, list):
            raise _DeepSeekStrictSchemaUnsupported(
                "tuple array items are not representable without changing order"
            )
        else:
            # ``items: false`` is emitted for an empty Persona effect list.
            # Replacing it with an object schema would allow values that the
            # original schema explicitly forbids, so let the caller fall back
            # to the regular non-strict tool request instead.
            raise _DeepSeekStrictSchemaUnsupported(
                "boolean array items are not representable in strict mode"
            )
        result["type"] = "array"
        result["items"] = normalized_items
        return result

    if raw_type == "string":
        _reject_unsupported_schema_keys(
            source,
            common_keys | {"enum", "const", "pattern", "format"},
        )
        if "format" in source and source["format"] not in {
            "email",
            "hostname",
            "ipv4",
            "ipv6",
            "uuid",
        }:
            raise _DeepSeekStrictSchemaUnsupported("unsupported string format")
        if "pattern" in source and not isinstance(source["pattern"], str):
            raise _DeepSeekStrictSchemaUnsupported("string pattern must be a string")
        result["type"] = raw_type
        for key in ("pattern", "format"):
            if key in source:
                result[key] = copy.deepcopy(source[key])
        return result

    if raw_type in {"number", "integer"}:
        numeric_keys = {
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "multipleOf",
            "default",
            "const",
        }
        _reject_unsupported_schema_keys(
            source,
            common_keys | {"enum"} | numeric_keys,
        )
        for key in numeric_keys:
            if key in source and key != "default":
                result[key] = copy.deepcopy(source[key])
        if (
            "default" in source
            and not isinstance(source["default"], bool)
            and isinstance(source["default"], (int, float))
        ):
            result["default"] = copy.deepcopy(source["default"])
        result["type"] = raw_type
        return result

    if raw_type == "boolean":
        _reject_unsupported_schema_keys(source, common_keys | {"enum", "const"})
        result["type"] = raw_type
        return result

    raise _DeepSeekStrictSchemaUnsupported(
        f"unsupported DeepSeek strict type: {raw_type}"
    )


@register_provider_adapter(
    "deepseek_chat_completion",
    "DeepSeek Chat Completion 提供商适配器",
    prompt_renderer_family="openai",
)
class ProviderDeepSeek(ProviderOpenAIOfficial):
    def supports_output_contract_strategy(self, strategy: str) -> bool:
        if strategy == "prompt_only":
            return True
        return (
            strategy == "protocol_tool_call"
            and not self._is_thinking_enabled({})
            and self._is_beta_endpoint()
        )

    def _is_beta_endpoint(self) -> bool:
        api_base = self.provider_config.get("api_base")
        if not api_base:
            api_base = getattr(
                getattr(self, "client", None),
                "base_url",
                "",
            )
        path = urlsplit(str(api_base)).path.rstrip("/").casefold()
        return path.endswith("/beta")

    @staticmethod
    def _parse_reasoning_enabled(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "enabled", "on", "1"}:
                return True
            if normalized in {"false", "disabled", "off", "none", "0"}:
                return False
        return None

    @staticmethod
    def _extract_thinking_type(source: Any) -> str | None:
        if not isinstance(source, dict):
            return None
        thinking = source.get("thinking")
        if not isinstance(thinking, dict):
            return None
        thinking_type = thinking.get("type")
        if not isinstance(thinking_type, str):
            return None
        normalized = thinking_type.strip().lower()
        return normalized or None

    def _is_thinking_enabled(
        self,
        payloads: dict,
        extra_body: dict[str, Any] | None = None,
    ) -> bool:
        configured_reasoning = self._parse_reasoning_enabled(
            self.provider_config.get("reasoning")
        )
        if configured_reasoning is not None:
            return configured_reasoning

        # Keep existing provider entries working while they migrate from the
        # provider-native field to the model-level reasoning switch.
        for source in (
            payloads,
            extra_body,
            self.provider_config.get("custom_extra_body", {}),
        ):
            thinking_type = self._extract_thinking_type(source)
            if thinking_type == "enabled":
                return True
            if thinking_type == "disabled":
                return False
        # DeepSeek documents thinking mode as enabled by default.
        return True

    def _prepare_request(
        self,
        payloads: dict,
        tools: ToolSet | None,
    ) -> tuple[dict, dict[str, Any], ToolSet | None]:
        self._drop_provider_only_request_keys(payloads)
        tool_list: list[dict[str, Any]] = []
        strict_output_contract_tool_names: set[str] = set()
        if tools:
            strict_output_contract_tool_names = {
                tool.name
                for tool in tools
                if bool(getattr(tool, "_astrbot_strict_output_contract", False))
            }
            tool_list = tools.openai_schema(
                omit_empty_parameter_field=False,
            )
            if tool_list:
                payloads["tools"] = tool_list

        strict_output_contract = bool(strict_output_contract_tool_names)

        extra_body: dict[str, Any] = {}
        to_del = []
        for key in payloads:
            if key not in self.default_params:
                extra_body[key] = payloads[key]
                to_del.append(key)
        for key in to_del:
            del payloads[key]

        custom_extra_body = self.provider_config.get("custom_extra_body", {})
        if isinstance(custom_extra_body, dict):
            extra_body.update(custom_extra_body)
        self._apply_provider_specific_request_overrides(payloads, extra_body)
        self._drop_provider_only_request_keys(extra_body)

        thinking_enabled = self._is_thinking_enabled(payloads, extra_body)
        if (
            self._parse_reasoning_enabled(self.provider_config.get("reasoning"))
            is not None
        ):
            extra_body["thinking"] = {
                "type": "enabled" if thinking_enabled else "disabled"
            }

        # Thinking mode supports tool calls, but DeepSeek rejects required or
        # named tool_choice values there. Strict output contracts are filtered
        # before this request because they require tool_choice=required.
        configured_tool_choice = extra_body.pop("tool_choice", None)
        if "tool_choice" not in payloads and configured_tool_choice is not None:
            payloads["tool_choice"] = configured_tool_choice

        if thinking_enabled:
            tool_choice = payloads.get("tool_choice")
            if tool_choice == "required" or isinstance(tool_choice, dict):
                payloads.pop("tool_choice", None)

        if (
            tool_list
            and payloads.get("tool_choice") == "required"
            and self._is_beta_endpoint()
            and strict_output_contract
        ):
            strict_tool_list = copy.deepcopy(tool_list)
            try:
                for tool in strict_tool_list:
                    function = tool.get("function")
                    if (
                        not isinstance(function, dict)
                        or function.get("name")
                        not in strict_output_contract_tool_names
                    ):
                        continue
                    function["strict"] = True
                    function["parameters"] = _normalize_deepseek_strict_schema(
                        function.get("parameters")
                    )
            except _DeepSeekStrictSchemaUnsupported as exc:
                logger.warning(
                    "DeepSeek strict tool schema is not representable; "
                    "sending the original non-strict schemas: %s",
                    exc,
                )
            else:
                payloads["tools"] = strict_tool_list

        self._sanitize_assistant_messages(payloads)
        return payloads, extra_body, tools

    def _finally_convert_payload(self, payloads: dict) -> None:
        thinking_enabled = self._is_thinking_enabled(payloads)

        super()._finally_convert_payload(payloads)

        if thinking_enabled:
            return

        for message in payloads.get("messages", []):
            if isinstance(message, dict) and message.get("role") == "assistant":
                message.pop("reasoning_content", None)

    async def _query(
        self,
        payloads: dict,
        tools: ToolSet | None,
        *,
        conversation_id: str | None = None,
    ) -> LLMResponse:
        payloads, extra_body, tools = self._prepare_request(payloads, tools)

        completion = await self.client.chat.completions.create(
            **payloads,
            stream=False,
            extra_body=extra_body,
            extra_headers=build_conversation_headers(conversation_id),
        )

        if not isinstance(completion, ChatCompletion):
            raise Exception(
                f"API 返回的 completion 类型错误：{type(completion)}: {completion}。",
            )

        logger.debug(
            "DeepSeek completion received: id=%s choices=%s",
            getattr(completion, "id", None),
            len(getattr(completion, "choices", None) or []),
        )

        return await self._parse_openai_completion(completion, tools)

    async def _query_stream(
        self,
        payloads: dict,
        tools: ToolSet | None,
        *,
        conversation_id: str | None = None,
    ) -> AsyncGenerator[LLMResponse, None]:
        payloads, extra_body, tools = self._prepare_request(payloads, tools)

        stream = await self.client.chat.completions.create(
            **payloads,
            stream=True,
            extra_body=extra_body,
            extra_headers=build_conversation_headers(conversation_id),
            stream_options={"include_usage": True},
        )

        llm_response = LLMResponse("assistant", is_chunk=True)
        state = ChatCompletionStreamState()

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            delta = choice.delta if choice else None

            if delta and (dtcs := delta.tool_calls):
                for idx, tc in enumerate(dtcs):
                    if tc.function and tc.function.arguments:
                        tc.type = "function"
                    if not hasattr(tc, "index") or tc.index is None:
                        tc.index = idx

            if delta is not None or chunk.usage:
                try:
                    state.handle_chunk(chunk)
                except Exception as e:
                    logger.error("Saving chunk state error: " + str(e))

            reasoning = self._extract_reasoning_content(chunk)
            has_delta = False
            llm_response.id = chunk.id
            llm_response.reasoning_content = None
            llm_response.completion_text = ""
            if reasoning is not None:
                llm_response.reasoning_content = reasoning
                has_delta = True
            if delta and delta.content:
                completion_text = self._normalize_content(delta.content, strip=False)
                llm_response.result_chain = MessageChain(
                    chain=[Comp.Plain(completion_text)],
                )
                has_delta = True
            if chunk.usage:
                llm_response.usage = self._extract_usage(chunk.usage)
            elif choice and (choice_usage := getattr(choice, "usage", None)):
                llm_response.usage = self._extract_usage(choice_usage)
                state.current_completion_snapshot.usage = choice_usage
            if has_delta:
                yield llm_response

        try:
            final_completion = state.get_final_completion()
            llm_response = await self._parse_openai_completion(final_completion, tools)
            yield llm_response
        except Exception as e:
            logger.error("get_final_completion failed: error_type=%s", type(e).__name__)
            return
