from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .persona_expression_types import PERSONA_TENDENCY_DIMENSIONS


def persona_response_shape(text: str) -> dict[str, Any]:
    stripped = text.lstrip()
    first_line = stripped.splitlines()[0] if stripped else ""
    return {
        "received_chars": len(text),
        "line_count": len(text.splitlines()),
        "blank_line_count": sum(not line.strip() for line in text.splitlines()),
        "starts_with_json_object": stripped.startswith("{"),
        "starts_with_markdown_fence": stripped.startswith("```"),
        "has_carriage_return": "\r" in text,
        "has_raw_control_chars": any(
            ord(char) < 0x20 and char not in "\n\r\t" for char in text
        ),
        "first_line_length": len(first_line),
    }


def build_persona_segment_stream_prompt(
    *, allowed_actions: Sequence[str], allow_action_only: bool,
) -> str:
    dimensions = ", ".join(PERSONA_TENDENCY_DIMENSIONS)
    action_choices = ", ".join(f'"{action}"' for action in allowed_actions)
    example = "\n".join(
        json.dumps(record, ensure_ascii=False)
        for record in (
            {"v": 1, "record": "header", "turn_action": "reply"},
            {
                "v": 1,
                "record": "segment_start",
                "actions": [],
                "tendency": dict.fromkeys(PERSONA_TENDENCY_DIMENSIONS, 0),
            },
            {"v": 1, "record": "speech_delta", "text": "本段要说的话。"},
            {"v": 1, "record": "segment_end"},
            {"v": 1, "record": "finish", "effect_calls": []},
        )
    )
    return (
        "\n\n【本轮输出协议：segment_stream_v1】"
        "只输出逐行 JSONL 记录，不要 Markdown、"
        "代码围栏、解释、空行或协议外文本。每条记录必须完整后再换行。"
        '第一条必须是 {"v":1,"record":"header","turn_action":"..."}；'
        f"turn_action 必须从 {action_choices} 中选择，并遵守本轮回复规则。"
        '每段依次输出 {"v":1,"record":"segment_start","actions":[],"tendency":{...}}，'
        '零到多条 {"v":1,"record":"speech_delta","text":"本段连续文本"}，'
            '再输出 {"v":1,"record":"segment_end"}。'
        'tendency 必须且只能包含八维整数，键为 '
        f"{dimensions}，取值 0 到 10。"
        '最后必须且只能输出 {"v":1,"record":"finish","effect_calls":[]}。'
        "每个 JSON 对象中的字段名只能出现一次；禁止重复键。"
        "同一 segment 内的 speech_delta 按原文顺序拼接。"
        "reply 时输出 Persona segment；silent 时只输出 header 和 finish，不输出 segment。"
        "effect_calls 必须为空；不要调用工具。"
        + (
            "reply 时允许纯动作回复：可以不输出 speech_delta，但至少一段必须包含动作。"
            if allow_action_only else "reply 时必须包含非空语音文本。"
        )
        + "\n以下是完整 JSONL 格式示例；文本、动作和情绪按本轮事实生成，不要复述示例内容：\n"
        + example
        + "\n"
    )

__all__ = ["build_persona_segment_stream_prompt", "persona_response_shape"]
