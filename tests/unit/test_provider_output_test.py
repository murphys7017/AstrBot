import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.dashboard.services.provider_output_test import (
    build_json_output_test_prompt,
    parse_json_template,
    run_json_output_stability_test,
    validate_json_output,
)


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
