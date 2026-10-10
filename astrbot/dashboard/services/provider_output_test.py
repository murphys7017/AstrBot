from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone
from hashlib import sha256
from statistics import median
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from astrbot.core.utils.error_redaction import safe_error

JSON_OUTPUT_TEST_RUNS = 10
OUTPUT_FORMAT_TEST_FORMATS = {"json", "xml", "markdown"}
OUTPUT_FORMAT_TEST_MODES = {
    "prompt_only",
    "provider_native_json",
    "provider_native_json_schema",
}
JSON_OUTPUT_TEST_MODES = OUTPUT_FORMAT_TEST_MODES
MAX_JSON_TEMPLATE_LENGTH = 16_000
MAX_OUTPUT_PREVIEW_LENGTH = 4_000
MAX_XML_OUTPUT_LENGTH = 64_000
_URL_PATTERN = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>\"']+")
_FIELD_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INTEGER_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_NUMBER_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_MARKDOWN_HEADING_PATTERN = re.compile(
    r"^(?P<level>#{1,6})[ \t]+(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]*$"
)


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


def _xml_item_tag(name: str) -> str:
    return {
        "segments": "segment",
        "actions": "action",
        "effect_calls": "effect_call",
    }.get(name, "item")


def _append_xml_value(parent: ET.Element, name: str, value: Any) -> None:
    if not _FIELD_NAME_PATTERN.fullmatch(name):
        raise ValueError("invalid_xml_template_field_name")
    if isinstance(value, dict):
        node = ET.SubElement(parent, name)
        for child_name, child_value in value.items():
            _append_xml_value(node, str(child_name), child_value)
        return
    if isinstance(value, list):
        node = ET.SubElement(parent, name)
        item_name = _xml_item_tag(name)
        for item_value in value:
            _append_xml_value(node, item_name, item_value)
        return

    node = ET.SubElement(parent, name)
    if value is not None:
        if isinstance(value, bool):
            node.text = "true" if value else "false"
        else:
            node.text = str(value)


def build_xml_output_example(template: dict[str, Any]) -> str:
    root = ET.Element("output")
    for name, value in template.items():
        _append_xml_value(root, str(name), value)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode")


def _append_markdown_value(lines: list[str], name: str, value: Any, level: int) -> None:
    if level > 6:
        raise ValueError("markdown_template_depth_exceeds_six")
    if not _FIELD_NAME_PATTERN.fullmatch(name):
        raise ValueError("invalid_markdown_template_field_name")
    lines.append(f"{'#' * level} {name}")
    if isinstance(value, dict):
        for child_name, child_value in value.items():
            _append_markdown_value(lines, str(child_name), child_value, level + 1)
    elif isinstance(value, list):
        item_name = _xml_item_tag(name)
        for item_value in value:
            _append_markdown_value(lines, item_name, item_value, level + 1)
    elif value is None:
        lines.append("null")
    elif isinstance(value, bool):
        lines.append("true" if value else "false")
    elif isinstance(value, str):
        # Quote text lines so headings and empty/multiline strings are lossless.
        lines.extend(f"> {line}" for line in value.split("\n"))
    else:
        lines.append(str(value))


def build_markdown_output_example(template: dict[str, Any]) -> str:
    lines = ["# output"]
    for name, value in template.items():
        _append_markdown_value(lines, str(name), value, 2)
    return "\n".join(lines)


def _markdown_heading(line: str) -> tuple[int, str] | None:
    match = _MARKDOWN_HEADING_PATTERN.fullmatch(line)
    if match is None:
        return None
    return len(match.group("level")), match.group("name")


def _parse_markdown_scalar(text: str, expected: Any) -> Any:
    if expected is None:
        if text != "null":
            raise ValueError("invalid_markdown_scalar")
        return None
    if isinstance(expected, bool):
        if text not in {"true", "false"}:
            raise ValueError("invalid_markdown_scalar")
        return text == "true"
    if isinstance(expected, int) and not isinstance(expected, bool):
        if not _INTEGER_PATTERN.fullmatch(text):
            raise ValueError("invalid_markdown_scalar")
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError("invalid_markdown_scalar") from exc
    if isinstance(expected, float):
        if not _NUMBER_PATTERN.fullmatch(text):
            raise ValueError("invalid_markdown_scalar")
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError("invalid_markdown_scalar") from exc
        if not math.isfinite(value):
            raise ValueError("invalid_markdown_scalar")
        return value
    if isinstance(expected, str):
        return text
    raise ValueError("invalid_markdown_scalar")


def _parse_markdown_value(
    lines: list[str], position: int, expected: Any, level: int, name: str
) -> tuple[Any, int]:
    if position >= len(lines) or _markdown_heading(lines[position]) != (level, name):
        raise ValueError("invalid_markdown_structure")
    position += 1
    if isinstance(expected, dict):
        result = {}
        for child_name, child_expected in expected.items():
            value, position = _parse_markdown_value(
                lines, position, child_expected, level + 1, child_name
            )
            result[child_name] = value
        return result, position
    if isinstance(expected, list):
        result = []
        item_name = _xml_item_tag(name)
        item_expected = expected[0] if expected else None
        while position < len(lines):
            heading = _markdown_heading(lines[position])
            if heading != (level + 1, item_name):
                break
            if not expected:
                raise ValueError("array_item_template_required")
            value, position = _parse_markdown_value(
                lines, position, item_expected, level + 1, item_name
            )
            result.append(value)
        return result, position
    if isinstance(expected, str):
        text_lines = []
        while position < len(lines) and lines[position].startswith("> "):
            text_lines.append(lines[position][2:])
            position += 1
        if not text_lines:
            raise ValueError("invalid_markdown_scalar")
        return "\n".join(text_lines), position
    if position >= len(lines) or _markdown_heading(lines[position]) is not None:
        raise ValueError("invalid_markdown_scalar")
    value = _parse_markdown_scalar(lines[position], expected)
    return value, position + 1


def parse_markdown_output(
    output: str, expected_template: dict[str, Any]
) -> dict[str, Any]:
    if len(output) > MAX_XML_OUTPUT_LENGTH:
        raise ValueError("markdown_output_too_large")
    # Do not strip spaces: a final '> ' represents an empty string.
    lines = output.split("\n")
    lines = [line.removesuffix("\r") for line in lines]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines or _markdown_heading(lines[0]) != (1, "output"):
        raise ValueError("invalid_markdown_structure")
    position = 1
    result = {}
    for name, expected in expected_template.items():
        value, position = _parse_markdown_value(lines, position, expected, 2, name)
        result[name] = value
    if position != len(lines):
        raise ValueError("invalid_markdown_structure")
    return result


def _require_xml_whitespace(value: str | None) -> None:
    if value and value.strip():
        raise ValueError("invalid_xml_structure")


def _parse_xml_scalar(node: ET.Element, expected: Any) -> Any:
    if len(node) or node.attrib:
        raise ValueError("invalid_xml_structure")
    text = node.text or ""
    if expected is None:
        if text.strip():
            raise ValueError("invalid_xml_scalar")
        return None
    if isinstance(expected, bool):
        if text not in {"true", "false"}:
            raise ValueError("invalid_xml_scalar")
        return text == "true"
    if isinstance(expected, int) and not isinstance(expected, bool):
        if not _INTEGER_PATTERN.fullmatch(text):
            raise ValueError("invalid_xml_scalar")
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError("invalid_xml_scalar") from exc
    if isinstance(expected, float):
        if not _NUMBER_PATTERN.fullmatch(text):
            raise ValueError("invalid_xml_scalar")
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError("invalid_xml_scalar") from exc
        if not math.isfinite(value):
            raise ValueError("invalid_xml_scalar")
        return value
    if isinstance(expected, str):
        return text
    raise ValueError("invalid_xml_scalar")


def _parse_xml_value(node: ET.Element, expected: Any) -> Any:
    for child in node:
        _require_xml_whitespace(child.tail)
    if isinstance(expected, dict):
        if node.attrib or node.text and node.text.strip():
            raise ValueError("invalid_xml_structure")
        expected_keys = set(expected)
        actual_keys = [child.tag for child in node]
        if len(actual_keys) != len(set(actual_keys)):
            raise ValueError("duplicate_xml_field")
        if set(actual_keys) != expected_keys:
            missing = sorted(expected_keys - set(actual_keys))
            extra = sorted(set(actual_keys) - expected_keys)
            if missing:
                raise ValueError(f"$:missing_keys:{','.join(missing)}")
            raise ValueError(f"$:unexpected_keys:{','.join(extra)}")
        return {
            key: _parse_xml_value(next(child for child in node if child.tag == key), value)
            for key, value in expected.items()
        }
    if isinstance(expected, list):
        if node.attrib or node.text and node.text.strip():
            raise ValueError("invalid_xml_structure")
        item_tag = _xml_item_tag(node.tag)
        if any(child.tag != item_tag for child in node):
            raise ValueError("invalid_xml_structure")
        item_template = expected[0] if expected else None
        if not expected and len(node):
            raise ValueError("array_item_template_required")
        return [_parse_xml_value(child, item_template) for child in node]
    return _parse_xml_scalar(node, expected)


def parse_xml_output(
    output: str, expected_template: dict[str, Any]
) -> dict[str, Any]:
    if len(output) > MAX_XML_OUTPUT_LENGTH:
        raise ValueError("xml_output_too_large")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b|<!--|<\?", output, re.IGNORECASE):
        raise ValueError("invalid_xml")
    try:
        root = ET.fromstring(output)
    except ET.ParseError as exc:
        raise ValueError("invalid_xml") from exc
    if root.tag != "output" or root.attrib:
        raise ValueError("invalid_xml_structure")
    _require_xml_whitespace(root.text)
    result = _parse_xml_value(root, expected_template)
    if not isinstance(result, dict):
        raise ValueError("invalid_xml_structure")
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
    if mode == "prompt_only":
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


def _build_json_schema(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        properties = {key: _build_json_schema(item) for key, item in value.items()}
        return {
            "type": "object",
            "properties": properties,
            "required": list(value),
            "additionalProperties": False,
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "items": _build_json_schema(value[0]) if value else {},
        }
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if value is None:
        return {"type": "null"}
    raise ValueError("unsupported_template_value")


def build_json_output_test_schema(template: dict[str, Any]) -> dict[str, Any]:
    return _build_json_schema(template)


def validate_markdown_output(
    template: dict[str, Any], output: str
) -> tuple[bool, str | None]:
    try:
        value = parse_markdown_output(output, template)
    except ValueError as exc:
        return False, str(exc)
    error = _validate_json_shape(template, value)
    return (error is None, error)


def validate_xml_output(
    template: dict[str, Any], output: str
) -> tuple[bool, str | None]:
    try:
        value = parse_xml_output(output, template)
    except ValueError as exc:
        return False, str(exc)
    error = _validate_json_shape(template, value)
    return (error is None, error)


def validate_output_format(
    template: dict[str, Any], output: str, output_format: str
) -> tuple[bool, str | None]:
    if output_format == "json":
        return validate_json_output(template, output)
    if output_format == "xml":
        return validate_xml_output(template, output)
    if output_format == "markdown":
        return validate_markdown_output(template, output)
    return False, "unsupported_output_format"


def build_json_output_test_prompt(
    template: dict[str, Any], mode: str = "prompt_only"
) -> str:
    template_text = json.dumps(template, ensure_ascii=False, indent=2)
    output_instruction = (
        "请只输出一个 JSON object，不要使用 Markdown 代码围栏或附加说明；"
        "输出必须是有效的 json。"
        if mode == "prompt_only"
        else "请输出一个 JSON object，且输出必须是有效的 json。"
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


def build_output_format_test_prompt(
    template: dict[str, Any], output_format: str, mode: str = "prompt_only"
) -> str:
    if output_format == "json":
        return build_json_output_test_prompt(template, mode)

    if output_format == "xml":
        example = build_xml_output_example(template)
        return (
            "这是一次 XML 结构化输出稳定性测试。请完成一个简短的角色表达："
            "面对意外的好消息，生成一句自然的中文回复，并给出简短的角色心理想法、"
            "简单动作意图和当前情绪倾向。\n"
            "只输出一个 XML 文档，根节点必须是 <output>，不得添加说明或 Markdown 围栏。"
            "直接使用语义字段作为节点，例如 <turn_action>reply</turn_action>、"
            "<segments><segment><speech>...</speech><actions><action>...</action>"
            "</actions><thought>...</thought><tendency><Joy>0</Joy></tendency>"
            "</segment></segments>；数组使用语义单数节点（segment、action、effect_call）。"
            "字符串直接写入节点文本，不要加 JSON 引号；整数、数字使用十进制文本，"
            "布尔使用 true 或 false，null 使用空节点；空数组必须保持为空，"
            "需要生成数组元素时须先在模板中提供元素示例。字段与数组顺序按示例语义保留，"
            "不得遗漏、重复或新增字段。\n\n"
            f"XML 示例：\n{example}"
        )

    if output_format == "markdown":
        markdown_example = build_markdown_output_example(template)
        return (
            "这是一次 Markdown 结构化输出稳定性测试。请完成一个简短的角色表达："
            "面对意外的好消息，生成一句自然的中文回复，并给出简短的角色心理想法、"
            "简单动作意图和当前情绪倾向。\n"
            "只输出一个完整的 Markdown 文档，第一行必须是 # output；使用 Markdown 标题表示字段，"
            "数组使用重复的单数标题（segment、action、effect_call），其他数组使用 item 标题。"
            "字符串每行用 Markdown 引用前缀 > 加一个空格，空字符串写成 > 加一个空格；"
            "数字、布尔和 null 直接写在标题下一行，布尔仅用 true/false。"
            "空数组必须保持为空，需要生成数组元素时须先在模板中提供元素示例。"
            "字段顺序和标题级别须与示例一致，最多六级标题；不要嵌入 JSON、代码围栏或额外说明。\n\n"
            f"Markdown 示例：\n{markdown_example}"
        )

    raise ValueError("unsupported_output_format")


def _supports_mode(provider, output_format: str, mode: str) -> bool:
    supports_mode = getattr(provider, "supports_output_format_test_mode", None)
    if callable(supports_mode):
        return bool(supports_mode(output_format, mode))
    if output_format != "json":
        return mode == "prompt_only"
    supports_json_mode = getattr(provider, "supports_json_output_test_mode", None)
    if callable(supports_json_mode):
        return bool(supports_json_mode(mode))
    return mode == "prompt_only"


def _is_native_output_mode_unsupported(error: Exception) -> bool:
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
            "json_schema",
            "text.format",
            "output_config.format",
            "json mode",
            "json_mode",
        )
    )
    structured_unsupported_parameter = structured_param in {
        "response_format",
        "response_format.type",
        "response_format.json_schema",
        "response_mime_type",
        "text.format",
        "text.format.type",
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


async def run_output_format_stability_test(
    provider,
    template: dict[str, Any],
    output_format: str = "json",
    mode: str = "prompt_only",
) -> dict[str, Any]:
    if output_format not in OUTPUT_FORMAT_TEST_FORMATS:
        raise ValueError("unsupported_output_format")
    if mode not in OUTPUT_FORMAT_TEST_MODES:
        raise ValueError("unsupported_output_test_mode")
    if output_format != "json" and mode != "prompt_only":
        raise ValueError("native_output_mode_only_supports_json")
    if not _supports_mode(provider, output_format, mode):
        return {
            "format": output_format,
            "mode": mode,
            "status": "unsupported_provider",
            "total": 0,
            "attempted": 0,
            "passed": 0,
            "failed": 0,
            "results": [],
        }

    prompt = build_output_format_test_prompt(template, output_format, mode)
    schema = (
        build_json_output_test_schema(template)
        if mode == "provider_native_json_schema"
        else None
    )
    results = []
    status = "completed"
    detail = None

    for index in range(1, JSON_OUTPUT_TEST_RUNS + 1):
        started_at = time.perf_counter()
        output = ""
        try:
            test_chat = getattr(provider, "text_chat_for_output_format_test", None)
            if callable(test_chat):
                response = await test_chat(
                    prompt=prompt,
                    output_format=output_format,
                    mode=mode,
                    schema=schema,
                )
            elif output_format == "json" and callable(
                getattr(provider, "text_chat_for_json_output_test", None)
            ):
                response = await provider.text_chat_for_json_output_test(
                    prompt=prompt,
                    mode=mode,
                )
            elif mode != "prompt_only":
                raise ValueError("unsupported_output_test_mode")
            else:
                response = await provider.text_chat(prompt=prompt)
            output = str(getattr(response, "completion_text", "") or "")
            passed, error = validate_output_format(template, output, output_format)
        except Exception as exc:
            passed = False
            if mode != "prompt_only":
                if _is_native_output_mode_unsupported(exc):
                    status = "unsupported_endpoint"
                    error = "unsupported_endpoint_output_mode"
                else:
                    status = "request_error"
                    error = "provider_output_mode_request_failed"
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
        "format": output_format,
        "mode": mode,
        "status": status,
        "detail": detail,
        "total": JSON_OUTPUT_TEST_RUNS,
        "attempted": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "results": results,
    }


async def run_json_output_stability_test(
    provider,
    template: dict[str, Any],
    mode: str = "prompt_only",
) -> dict[str, Any]:
    return await run_output_format_stability_test(
        provider,
        template,
        output_format="json",
        mode=mode,
    )
