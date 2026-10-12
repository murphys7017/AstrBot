import json

from astrbot.core.interaction.prompt_diagnostics import project_prompt_diagnostics


def test_prompt_diagnostics_omit_media_and_credentials_without_mutating_request():
    request = {
        "system_prompt": "生成完整 JSON。Authorization: Bearer secret-token",
        "api_key": "private-key",
        "contexts": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看看这张图片"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64," + "A" * 4000,
                        },
                    },
                ],
            }
        ],
    }
    projected, media = project_prompt_diagnostics(request)
    serialized = json.dumps(projected, ensure_ascii=False)
    assert "看看这张图片" in serialized
    assert "private-key" not in serialized
    assert "secret-token" not in serialized
    assert "A" * 4000 not in serialized
    assert media == {"parts": 1, "base64_chars": 4000}
    assert request["api_key"] == "private-key"
    assert len(request["contexts"][0]["content"][1]["image_url"]["url"]) > 4000
    smaller = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    assert (
        projected["contexts"][0]["content"][1] == project_prompt_diagnostics(smaller)[0]
    )
