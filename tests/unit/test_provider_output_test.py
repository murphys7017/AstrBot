import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.dashboard.services.provider_output_test import (
    attach_json_output_test_evidence,
    build_json_output_test_prompt,
    parse_json_template,
    run_json_output_stability_test,
    validate_json_output,
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
    assert result["results"][0]["error"] == "unsupported_endpoint_json_mode"


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
