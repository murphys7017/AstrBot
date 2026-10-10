from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from hashlib import sha256
from statistics import median
from typing import Any
from urllib.parse import urlsplit

from astrbot.core.utils.error_redaction import safe_error

JSON_OUTPUT_TEST_RUNS = 10
JSON_OUTPUT_TEST_MODES = {"prompt_only", "provider_native_json"}
MAX_JSON_TEMPLATE_LENGTH = 16_000
MAX_OUTPUT_PREVIEW_LENGTH = 4_000
_URL_PATTERN = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>\"']+")


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


def attach_json_output_test_evidence(
    result: dict[str, Any], provider, provider_id: str, model: str
) -> dict[str, Any]:
    """Attach safe, comparable probe metadata without exposing endpoint secrets."""
    provider_config = getattr(provider, "provider_config", {})
    if not isinstance(provider_config, dict):
        provider_config = {}

    endpoint_value = next(
        (
            provider_config.get(key)
            for key in ("api_base", "base_url", "api_url")
            if isinstance(provider_config.get(key), str)
            and provider_config[key].strip()
        ),
        None,
    )
    endpoint_host = None
    endpoint_fingerprint = None
    if endpoint_value:
        endpoint_text = endpoint_value.strip()
        try:
            parsed = urlsplit(
                endpoint_text if "://" in endpoint_text else f"//{endpoint_text}"
            )
            hostname = parsed.hostname
        except ValueError:
            hostname = None

        if hostname:
            hostname = hostname.lower()
            try:
                port = parsed.port
            except ValueError:
                port = None
            endpoint_host = f"[{hostname}]" if ":" in hostname else hostname
            if port is not None:
                endpoint_host = f"{endpoint_host}:{port}"

            scheme = parsed.scheme.lower()
            endpoint_key = f"{scheme}://{endpoint_host}"
            endpoint_fingerprint = sha256(endpoint_key.encode("utf-8")).hexdigest()[:16]

    mode = result.get("mode")
    status = result.get("status")
    if mode != "provider_native_json":
        capability_assessment = "not_tested"
    elif status == "unsupported_provider":
        capability_assessment = "adapter_unsupported"
    elif status == "unsupported_endpoint":
        capability_assessment = "endpoint_rejected"
    elif status == "request_error":
        capability_assessment = "unverified_request_failed"
    else:
        capability_assessment = "request_accepted"

    latencies = [
        item["latency_ms"]
        for item in result.get("results", [])
        if isinstance(item, dict) and isinstance(item.get("latency_ms"), int)
    ]
    result.update(
        {
            "provider_id": provider_id,
            "adapter_type": provider_config.get("type")
            or provider.__class__.__name__,
            "model": model,
            "endpoint_configured": bool(endpoint_value),
            "endpoint_host": endpoint_host,
            "endpoint_fingerprint": endpoint_fingerprint,
            "observed_at": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "capability_assessment": capability_assessment,
            "mean_latency_ms": round(sum(latencies) / len(latencies), 1)
            if latencies
            else None,
            "median_latency_ms": median(latencies) if latencies else None,
        }
    )
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


def build_json_output_test_prompt(
    template: dict[str, Any], mode: str = "prompt_only"
) -> str:
    template_text = json.dumps(template, ensure_ascii=False, indent=2)
    output_instruction = (
        "请只输出一个 JSON object，不要使用 Markdown 代码围栏或附加说明。"
        if mode == "prompt_only"
        else "请输出一个 JSON object。"
    )
    return (
        "这是一次 JSON 输出格式稳定性测试。请完成一个简短的角色表达："
        "面对意外的好消息，生成一句自然的中文回复，并给出简短的角色心理想法、"
        "简单动作意图和当前情绪倾向。\n"
        f"{output_instruction}"
        "参照下面的 JSON 示例保持对象字段、嵌套结构和字段值类型一致；"
        "字符串内容可以根据任务生成，空数组可以填入符合示例元素类型的项目。\n\n"
        f"JSON 示例：\n{template_text}"
    )


def _supports_mode(provider, mode: str) -> bool:
    supports_mode = getattr(provider, "supports_json_output_test_mode", None)
    if callable(supports_mode):
        return bool(supports_mode(mode))
    return mode == "prompt_only"


def _is_native_json_mode_unsupported(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if not isinstance(status_code, int):
        status_code = getattr(error, "code", None)
    if not isinstance(status_code, int):
        status_code = getattr(error, "status", None)
    if status_code not in {400, 404, 422}:
        return False

    candidates = [str(error)]
    structured_param = ""
    structured_code = ""
    body = getattr(error, "body", getattr(error, "details", None))
    if isinstance(body, (dict, list)):
        candidates.append(json.dumps(body, ensure_ascii=False, default=str))
        error_body = body.get("error") if isinstance(body, dict) else None
        if isinstance(error_body, dict):
            structured_param = str(
                error_body.get("param") or error_body.get("parameter") or ""
            ).lower()
            structured_code = str(error_body.get("code") or "").lower()
    elif isinstance(body, str):
        candidates.append(body)
    response = getattr(error, "response", None)
    response_text = getattr(response, "text", None)
    if isinstance(response_text, str):
        candidates.append(response_text)

    error_text = " ".join(candidates).lower()
    names_json_mode = any(
        marker in error_text
        for marker in (
            "response_format",
            "response_mime_type",
            "responsemimetype",
            "json_object",
            "json mode",
            "json_mode",
        )
    )
    structured_unsupported_parameter = structured_param in {
        "response_format",
        "response_format.type",
        "response_mime_type",
    } and any(
        marker in structured_code
        for marker in ("unsupported", "unknown", "invalid", "not_allowed")
    )
    rejects_parameter = any(
        marker in error_text
        for marker in (
            "unsupported",
            "not supported",
            "does not support",
            "isn't supported",
            "unknown parameter",
            "unrecognized",
            "invalid parameter",
            "not allowed",
            "not available",
            "unavailable",
            "unexpected",
        )
    )
    return structured_unsupported_parameter or (names_json_mode and rejects_parameter)


def _safe_provider_error_detail(error: Exception) -> str:
    detail = safe_error("provider_error:", error)
    return _URL_PATTERN.sub("[URL redacted]", detail)[:500]


async def run_json_output_stability_test(
    provider,
    template: dict[str, Any],
    mode: str = "prompt_only",
) -> dict[str, Any]:
    if mode not in JSON_OUTPUT_TEST_MODES:
        raise ValueError("unsupported_json_output_test_mode")
    if not _supports_mode(provider, mode):
        return {
            "mode": mode,
            "status": "unsupported_provider",
            "total": 0,
            "attempted": 0,
            "passed": 0,
            "failed": 0,
            "results": [],
        }

    prompt = build_json_output_test_prompt(template, mode)
    results = []
    status = "completed"
    detail = None

    for index in range(1, JSON_OUTPUT_TEST_RUNS + 1):
        started_at = time.perf_counter()
        output = ""
        try:
            test_chat = getattr(provider, "text_chat_for_json_output_test", None)
            if callable(test_chat):
                response = await test_chat(prompt=prompt, mode=mode)
            else:
                response = await provider.text_chat(prompt=prompt)
            output = str(getattr(response, "completion_text", "") or "")
            passed, error = validate_json_output(template, output)
        except Exception as exc:
            passed = False
            if mode == "provider_native_json":
                if _is_native_json_mode_unsupported(exc):
                    status = "unsupported_endpoint"
                    error = "unsupported_endpoint_json_mode"
                else:
                    status = "request_error"
                    error = "provider_request_failed"
                detail = _safe_provider_error_detail(exc)
            else:
                error = _safe_provider_error_detail(exc)

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
        if status != "completed":
            break

    passed_count = sum(result["passed"] for result in results)
    return {
        "mode": mode,
        "status": status,
        "detail": detail,
        "total": JSON_OUTPUT_TEST_RUNS,
        "attempted": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "results": results,
    }
