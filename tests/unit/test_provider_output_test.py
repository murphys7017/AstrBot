import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.dashboard.services.provider_output_test import (
    attach_json_output_test_evidence,
    build_json_output_test_prompt,
    build_json_output_test_schema,
    build_markdown_output_example,
    build_output_format_test_prompt,
    build_xml_output_example,
    parse_json_template,
    parse_markdown_output,
    parse_xml_output,
    run_json_output_stability_test,
    run_output_format_stability_test,
    validate_json_output,
    validate_markdown_output,
    validate_xml_output,
)


def test_json_output_test_evidence_is_comparable_without_exposing_endpoint_secrets():
    provider = SimpleNamespace(
        provider_config={
            "type": "openai_chat_completion",
            "api_base": "https://user:password@api.example.test:8443/v1?token=secret",
        }
    )
    result = {
        "mode": "provider_native_json",
        "status": "completed",
        "results": [{"latency_ms": 100}, {"latency_ms": 300}],
    }

    evidence = attach_json_output_test_evidence(
        result,
        provider,
        "provider-1",
        "model-1",
    )

    assert evidence["provider_id"] == "provider-1"
    assert evidence["adapter_type"] == "openai_chat_completion"
    assert evidence["model"] == "model-1"
    assert evidence["endpoint_configured"] is True
    assert evidence["endpoint_host"] == "api.example.test:8443"
    assert len(evidence["endpoint_fingerprint"]) == 16
    assert evidence["capability_assessment"] == "request_accepted"
    assert evidence["mean_latency_ms"] == 200
    assert evidence["median_latency_ms"] == 200
    serialized = json.dumps(evidence)
    assert "user" not in serialized
    assert "password" not in serialized
    assert "secret" not in serialized
    assert "/v1" not in serialized


def test_prompt_only_evidence_does_not_claim_native_json_capability():
    provider = SimpleNamespace(provider_config={"type": "openai_chat_completion"})
    result = {"mode": "prompt_only", "status": "completed", "results": []}

    evidence = attach_json_output_test_evidence(
        result,
        provider,
        "provider-1",
        "model-1",
    )

    assert evidence["capability_assessment"] == "not_tested"
    assert evidence["endpoint_configured"] is False
    assert evidence["endpoint_host"] is None
    assert evidence["endpoint_fingerprint"] is None


def test_unparseable_custom_endpoint_is_not_marked_as_provider_default():
    provider = SimpleNamespace(
        provider_config={"api_base": "https://[invalid"},
    )
    result = {"mode": "prompt_only", "status": "completed", "results": []}

    evidence = attach_json_output_test_evidence(
        result,
        provider,
        "provider-1",
        "model-1",
    )

    assert evidence["endpoint_configured"] is True
    assert evidence["endpoint_host"] is None
    assert evidence["endpoint_fingerprint"] is None


@pytest.fixture
def persona_template():
    return {
        "turn_action": "reply",
        "segments": [
            {
                "speech": "你好",
                "actions": ["wave"],
                "thought": "很高兴见到你",
                "tendency": {
                    "Joy": 8,
                    "Trust": 0,
                    "Fear": 0,
                    "Surprise": 0,
                    "Sadness": 0,
                    "Disgust": 0,
                    "Anger": 0,
                    "Anticipation": 0,
                },
            }
        ],
        "effect_calls": [],
    }


def test_json_output_validator_checks_json_and_template_shape(persona_template):
    valid_output = json.dumps(
        {
            "turn_action": "delegate",
            "segments": [
                {
                    "speech": "真是个好消息！",
                    "actions": ["smile", "wave"],
                    "thought": "这让我很开心",
                    "tendency": {
                        "Joy": 10,
                        "Trust": 0,
                        "Fear": 0,
                        "Surprise": 0,
                        "Sadness": 0,
                        "Disgust": 0,
                        "Anger": 0,
                        "Anticipation": 0,
                    },
                }
            ],
            "effect_calls": [],
        },
        ensure_ascii=False,
    )

    assert validate_json_output(persona_template, valid_output) == (True, None)
    assert validate_json_output(persona_template, f"```json\n{valid_output}\n```") == (
        False,
        "invalid_json",
    )


def test_json_output_validator_rejects_unstable_fields_and_types(persona_template):
    wrong_type = json.dumps(
        {
            **persona_template,
            "segments": [
                {
                    **persona_template["segments"][0],
                    "tendency": {
                        **persona_template["segments"][0]["tendency"],
                        "Joy": True,
                    },
                }
            ],
        }
    )
    extra_field = json.dumps({**persona_template, "unexpected": "extra"})
    assert validate_json_output(persona_template, wrong_type) == (
        False,
        "$.segments[0].tendency.Joy:expected_integer",
    )
    assert validate_json_output(persona_template, extra_field) == (
        False,
        "$:unexpected_keys:unexpected",
    )
    assert validate_json_output(persona_template, '{"speech":"x","speech":"y"}') == (
        False,
        "duplicate_json_key",
    )


def test_xml_output_round_trips_nested_values_and_escaped_text(persona_template):
    template = json.loads(json.dumps(persona_template))
    template["segments"][0]["speech"] = "A & B < C"
    template["segments"][0]["actions"] = ["<wave>", "look & smile"]

    xml_output = build_xml_output_example(template)

    assert validate_xml_output(template, xml_output) == (True, None)
    assert "&amp;" in xml_output
    assert "&lt;" in xml_output


@pytest.mark.parametrize(
    ("output", "expected_error"),
    [
        (
            "<output><turn_action>reply</turn_action>"
            "<turn_action>reply</turn_action></output>",
            "duplicate_xml_field",
        ),
        (
            '<!DOCTYPE output [<!ENTITY x "y">]><output><object /></output>',
            "invalid_xml",
        ),
        (
            "<output><turn_action>reply</turn_action>"
            "<unknown>x</unknown></output>",
            "$:missing_keys:effect_calls,segments",
        ),
    ],
)
def test_xml_output_rejects_duplicate_fields_entities_and_shape_drift(
    persona_template, output, expected_error
):
    assert validate_xml_output(persona_template, output) == (False, expected_error)


def test_markdown_requires_one_exact_block(persona_template):
    valid = build_markdown_output_example(persona_template)

    assert validate_markdown_output(persona_template, valid) == (
        True,
        None,
    )
    assert validate_markdown_output(
        persona_template, f"Here it is:\n{valid}"
    ) == (False, "invalid_markdown_structure")
    assert validate_markdown_output(
        persona_template, valid.replace("# output", "# wrong", 1)
    ) == (False, "invalid_markdown_structure")


@pytest.mark.parametrize(
    ("parser", "output"),
    [
        (
            parse_xml_output,
            "<output><segments><segment><speech>首行\n# heading\n</speech>"
            "<thought/><actions><action>nod</action></actions></segment>"
            "<segment><speech/><thought>文本 &amp; 标签</thought><actions/>"
            "</segment></segments><effect_calls><effect_call><name>deliver</name>"
            "<arguments><enabled>true</enabled><value>1.5</value></arguments>"
            "</effect_call></effect_calls><optional><item/></optional></output>",
        ),
        (
            parse_markdown_output,
            "# output\n## segments\n### segment\n#### speech\n> 首行\n"
            "> # heading\n> \n#### thought\n> \n#### actions\n##### action\n"
            "> nod\n### segment\n#### speech\n> \n#### thought\n> 文本 & 标签\n"
            "#### actions\n## effect_calls\n### effect_call\n#### name\n> deliver\n"
            "#### arguments\n##### enabled\ntrue\n##### value\n1.5\n"
            "## optional\n### item\nnull\n",
        ),
    ],
)
def test_semantic_formats_restore_text_arrays_and_effect_arguments(parser, output):
    template = {
        "segments": [{"speech": "", "thought": "", "actions": ["nod"]}],
        "effect_calls": [{"name": "", "arguments": {"enabled": True, "value": 0.0}}],
        "optional": [None],
    }
    assert parser(output, template) == {
        "segments": [
            {"speech": "首行\n# heading\n", "thought": "", "actions": ["nod"]},
            {"speech": "", "thought": "文本 & 标签", "actions": []},
        ],
        "effect_calls": [
            {"name": "deliver", "arguments": {"enabled": True, "value": 1.5}}
        ],
        "optional": [None],
    }


def test_xml_rejects_text_between_fields_and_untyped_array_items():
    assert validate_xml_output(
        {"speech": ""}, "<output><speech>你好</speech>多余文本</output>"
    ) == (False, "invalid_xml_structure")
    assert validate_xml_output(
        {"effect_calls": []},
        "<output><effect_calls><effect_call/></effect_calls></output>",
    ) == (False, "array_item_template_required")


def test_output_format_prompts_define_the_markdown_and_xml_grammars(persona_template):
    xml_prompt = build_output_format_test_prompt(persona_template, "xml")
    markdown_prompt = build_output_format_test_prompt(
        persona_template, "markdown"
    )

    assert "<output>" in xml_prompt
    assert "<turn_action>reply</turn_action>" in xml_prompt
    assert "# output" in markdown_prompt
    assert "不要嵌入 JSON" in markdown_prompt


def test_json_schema_is_inferred_from_template_without_guessing_empty_array_items(
    persona_template,
):
    schema = build_json_output_test_schema(persona_template)

    assert schema["type"] == "object"
    assert schema["required"] == ["turn_action", "segments", "effect_calls"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["effect_calls"] == {
        "type": "array",
        "items": {},
    }


def test_parse_template_requires_one_json_object():
    assert parse_json_template('{"value": 1}') == {"value": 1}
    with pytest.raises(ValueError, match="template_must_be_object"):
        parse_json_template('["value"]')
    with pytest.raises(ValueError, match="invalid_json_template"):
        parse_json_template('{"value": 1, "value": 2}')


@pytest.mark.asyncio
async def test_json_stability_test_makes_ten_independent_requests(persona_template):
    output = json.dumps(persona_template, ensure_ascii=False)
    provider = SimpleNamespace(
        text_chat=AsyncMock(return_value=SimpleNamespace(completion_text=output))
    )

    result = await run_json_output_stability_test(provider, persona_template)

    assert provider.text_chat.await_count == 10
    assert result["total"] == 10
    assert result["passed"] == 10
    assert result["failed"] == 0
    assert all(item["passed"] for item in result["results"])
    assert "JSON object" in build_json_output_test_prompt(persona_template)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output_format", "output"),
    [
        ("xml", build_xml_output_example),
        (
            "markdown",
            build_markdown_output_example,
        ),
    ],
)
async def test_output_format_test_runs_ten_times_for_xml_and_markdown(
    persona_template, output_format, output
):
    provider = SimpleNamespace(
        text_chat=AsyncMock(
            return_value=SimpleNamespace(completion_text=output(persona_template))
        )
    )

    result = await run_output_format_stability_test(
        provider,
        persona_template,
        output_format=output_format,
    )

    assert provider.text_chat.await_count == 10
    assert result["format"] == output_format
    assert result["mode"] == "prompt_only"
    assert result["passed"] == 10


@pytest.mark.asyncio
async def test_json_stability_test_continues_after_provider_error(persona_template):
    provider = SimpleNamespace(
        text_chat=AsyncMock(
            side_effect=[
                RuntimeError("authorization: Bearer secret-token"),
                *[
                    SimpleNamespace(completion_text=json.dumps(persona_template))
                    for _ in range(9)
                ],
            ]
        )
    )

    result = await run_json_output_stability_test(provider, persona_template)

    assert provider.text_chat.await_count == 10
    assert result["passed"] == 9
    assert result["failed"] == 1
    assert (
        result["results"][0]["error"]
        == "provider_error:authorization: Bearer [REDACTED]"
    )


@pytest.mark.asyncio
async def test_native_json_mode_stops_when_endpoint_rejects_response_format(
    persona_template,
):
    class ProviderBadRequest(Exception):
        status_code = 400
        body = {
            "error": {
                "param": "response_format",
                "code": "unsupported_parameter",
                "message": "response_format is unavailable for this model",
            }
        }

    class TestProvider:
        def __init__(self):
            self.calls = 0

        def supports_json_output_test_mode(self, mode):
            return mode in {"prompt_only", "provider_native_json"}

        async def text_chat_for_json_output_test(self, prompt, *, mode):
            assert mode == "provider_native_json"
            self.calls += 1
            raise ProviderBadRequest("bad request")

    provider = TestProvider()
    result = await run_json_output_stability_test(
        provider,
        persona_template,
        mode="provider_native_json",
    )

    assert provider.calls == 1
    assert result["status"] == "unsupported_endpoint"
    assert result["attempted"] == 1
    assert result["failed"] == 1
    assert result["results"][0]["error"] == "unsupported_endpoint_output_mode"


@pytest.mark.asyncio
async def test_native_json_mode_classifies_gemini_parameter_rejection(persona_template):
    class GeminiBadRequest(Exception):
        code = 400
        status = "INVALID_ARGUMENT"
        details = {
            "error": {
                "message": "response_mime_type is not supported for this model"
            }
        }

    class TestProvider:
        def supports_json_output_test_mode(self, mode):
            return mode in {"prompt_only", "provider_native_json"}

        async def text_chat_for_json_output_test(self, prompt, *, mode):
            raise GeminiBadRequest("bad request")

    result = await run_json_output_stability_test(
        TestProvider(),
        persona_template,
        mode="provider_native_json",
    )

    assert result["status"] == "unsupported_endpoint"
    assert result["attempted"] == 1


@pytest.mark.asyncio
async def test_native_json_mode_stops_after_an_unrelated_request_error(
    persona_template,
):
    class ProviderBadRequest(Exception):
        status_code = 400
        body = {"error": {"message": "invalid prompt"}}

    class TestProvider:
        def __init__(self):
            self.calls = 0

        def supports_json_output_test_mode(self, mode):
            return mode == "provider_native_json"

        async def text_chat_for_json_output_test(self, prompt, *, mode):
            self.calls += 1
            raise ProviderBadRequest("bad request")

    provider = TestProvider()
    result = await run_json_output_stability_test(
        provider,
        persona_template,
        mode="provider_native_json",
    )

    assert provider.calls == 1
    assert result["status"] == "request_error"
    assert result["attempted"] == 1
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_native_json_mode_does_not_call_unsupported_provider(persona_template):
    provider = SimpleNamespace(
        supports_json_output_test_mode=lambda mode: mode == "prompt_only",
        text_chat=AsyncMock(),
    )

    result = await run_json_output_stability_test(
        provider,
        persona_template,
        mode="provider_native_json",
    )

    provider.text_chat.assert_not_awaited()
    assert result["status"] == "unsupported_provider"
    assert result["attempted"] == 0


@pytest.mark.asyncio
async def test_provider_error_detail_redacts_custom_endpoint_urls(persona_template):
    class TestProvider:
        async def text_chat(self, prompt):
            raise RuntimeError(
                "request failed for "
                "https://user:password@api.example.test/private/v1?token=secret"
            )

    result = await run_json_output_stability_test(TestProvider(), persona_template)

    detail = result["results"][0]["error"]
    assert "[URL redacted]" in detail
    assert "user" not in detail
    assert "password" not in detail
    assert "private" not in detail
    assert "secret" not in detail


@pytest.mark.asyncio
async def test_json_schema_output_mode_builds_schema_and_stops_on_endpoint_rejection(
    persona_template,
):
    class ProviderBadRequest(Exception):
        status_code = 400
        body = {
            "error": {
                "param": "text.format",
                "code": "unsupported_parameter",
                "message": "text.format json_schema is unavailable",
            }
        }

    class TestProvider:
        def __init__(self):
            self.calls = []

        def supports_output_format_test_mode(self, output_format, mode):
            return output_format == "json" and mode in {
                "prompt_only",
                "provider_native_json_schema",
            }

        async def text_chat_for_output_format_test(
            self, prompt, *, output_format, mode, schema
        ):
            self.calls.append((output_format, mode, schema))
            raise ProviderBadRequest("text.format unavailable")

    provider = TestProvider()
    result = await run_output_format_stability_test(
        provider,
        persona_template,
        output_format="json",
        mode="provider_native_json_schema",
    )

    assert len(provider.calls) == 1
    assert provider.calls[0][0:2] == ("json", "provider_native_json_schema")
    assert provider.calls[0][2]["properties"]["segments"]["type"] == "array"
    assert result["status"] == "unsupported_endpoint"
    assert result["attempted"] == 1


@pytest.mark.asyncio
async def test_native_json_constraint_is_rejected_for_xml_before_provider_call(
    persona_template,
):
    provider = SimpleNamespace(text_chat=AsyncMock())

    with pytest.raises(ValueError, match="native_output_mode_only_supports_json"):
        await run_output_format_stability_test(
            provider,
            persona_template,
            output_format="xml",
            mode="provider_native_json",
        )

    provider.text_chat.assert_not_awaited()
