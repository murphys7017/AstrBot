from __future__ import annotations

import json
import time
from typing import Any

from astrbot.core.utils.error_redaction import safe_error

JSON_OUTPUT_TEST_RUNS = 10
MAX_JSON_TEMPLATE_LENGTH = 16_000
MAX_OUTPUT_PREVIEW_LENGTH = 4_000


class _DuplicateJSONKeyError(ValueError):
    pass


def _reject_nonstandard_constant(value: str):
    raise ValueError(f"invalid_json_constant:{value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKeyError(f"duplicate_key:{key}")
        result[key] = value
    return result


def parse_json_template(template_text: str) -> dict[str, Any]:
    if len(template_text) > MAX_JSON_TEMPLATE_LENGTH:
        raise ValueError("template_too_large")
    try:
        template = json.loads(
            template_text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except (json.JSONDecodeError, _DuplicateJSONKeyError) as exc:
        raise ValueError("invalid_json_template") from exc
    if not isinstance(template, dict):
        raise ValueError("template_must_be_object")
    return template


def _validate_json_shape(expected: Any, actual: Any, path: str = "$") -> str | None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return f"{path}:expected_object"
        expected_keys = set(expected)
        actual_keys = set(actual)
        if expected_keys != actual_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            if missing:
                return f"{path}:missing_keys:{','.join(missing)}"
            return f"{path}:unexpected_keys:{','.join(extra)}"
        for key, expected_value in expected.items():
            error = _validate_json_shape(expected_value, actual[key], f"{path}.{key}")
            if error:
                return error
        return None

    if isinstance(expected, list):
        if not isinstance(actual, list):
            return f"{path}:expected_array"
        if expected:
            for index, value in enumerate(actual):
                error = _validate_json_shape(expected[0], value, f"{path}[{index}]")
                if error:
                    return error
        return None

    if isinstance(expected, bool):
        return None if isinstance(actual, bool) else f"{path}:expected_boolean"
    if isinstance(expected, int):
        return None if type(actual) is int else f"{path}:expected_integer"
    if isinstance(expected, float):
        return (
            None
            if isinstance(actual, (int, float)) and not isinstance(actual, bool)
            else f"{path}:expected_number"
        )
    if expected is None:
        return None if actual is None else f"{path}:expected_null"
    if isinstance(expected, str):
        return None if isinstance(actual, str) else f"{path}:expected_string"
    return f"{path}:unsupported_template_value"


def validate_json_output(
    template: dict[str, Any], output: str
) -> tuple[bool, str | None]:
    try:
        value = json.loads(
            output,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except json.JSONDecodeError:
        return False, "invalid_json"
    except _DuplicateJSONKeyError:
        return False, "duplicate_json_key"
    except ValueError:
        return False, "invalid_json_constant"

    if not isinstance(value, dict):
        return False, "root_must_be_object"
    error = _validate_json_shape(template, value)
    return (error is None, error)


def build_json_output_test_prompt(template: dict[str, Any]) -> str:
    template_text = json.dumps(template, ensure_ascii=False, indent=2)
    return (
        "这是一次 JSON 输出格式稳定性测试。请完成一个简短的角色表达："
        "面对意外的好消息，生成一句自然的中文回复，并给出简短的角色心理想法、"
        "简单动作意图和当前情绪倾向。\n"
        "只输出一个 JSON object，不要使用 Markdown 代码围栏或附加说明。"
        "参照下面的 JSON 示例保持对象字段和嵌套结构一致，字段值类型也必须一致；"
        "字符串内容可以根据任务生成，空数组可以填入符合示例元素类型的项目。\n\n"
        f"JSON 示例：\n{template_text}"
    )


async def run_json_output_stability_test(
    provider, template: dict[str, Any]
) -> dict[str, Any]:
    prompt = build_json_output_test_prompt(template)
    results = []

    for index in range(1, JSON_OUTPUT_TEST_RUNS + 1):
        started_at = time.perf_counter()
        output = ""
        try:
            response = await provider.text_chat(prompt=prompt)
            output = str(getattr(response, "completion_text", "") or "")
            passed, error = validate_json_output(template, output)
        except Exception as exc:
            passed = False
            error = safe_error("provider_error:", exc)[:500]

        elapsed_ms = max(0, round((time.perf_counter() - started_at) * 1000))
        results.append(
            {
                "index": index,
                "passed": passed,
                "error": error,
                "latency_ms": elapsed_ms,
                "output": output[:MAX_OUTPUT_PREVIEW_LENGTH],
                "output_truncated": len(output) > MAX_OUTPUT_PREVIEW_LENGTH,
            }
        )

    passed_count = sum(result["passed"] for result in results)
    return {
        "total": JSON_OUTPUT_TEST_RUNS,
        "passed": passed_count,
        "failed": JSON_OUTPUT_TEST_RUNS - passed_count,
        "results": results,
    }
