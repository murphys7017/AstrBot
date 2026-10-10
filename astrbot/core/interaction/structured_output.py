"""Schema-directed Persona text grammars, independent of the provider wire API."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

_HEADING = re.compile(r"^(?P<level>#{1,6})[ \t]+(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]*$")
_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_MAX_LENGTH = 64_000
_ITEM_NAMES = {"segments": "segment", "actions": "action", "effect_calls": "effect_call"}


def _reject_constant(value: str):
    raise ValueError(f"invalid_json_constant:{value}")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"duplicate_json_key:{name}")
        result[name] = value
    return result


def _default_schema() -> dict[str, Any]:
    # Import lazily: the expression agent also imports this parser.
    from .expression_agent import build_persona_expression_tool_parameters

    return build_persona_expression_tool_parameters()


def _schema_variants(schema: object) -> list[dict[str, Any]]:
    if not isinstance(schema, dict):
        raise ValueError("text_format_schema_required")
    branches = schema.get("oneOf", schema.get("anyOf"))
    if isinstance(branches, list):
        return [variant for branch in branches for variant in _schema_variants(branch)]
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return [{**schema, "type": item} for item in schema_type]
    if schema_type is None:
        if "const" in schema:
            return [{**schema, "type": "string"}]
        if "properties" in schema:
            return [{**schema, "type": "object"}]
        raise ValueError("text_format_schema_type_required")
    return [schema]


@dataclass
class _Node:
    name: str
    text: str = ""
    lines: list[str] = field(default_factory=list)
    children: list[_Node] = field(default_factory=list)


def _xml_node(element: ET.Element) -> _Node:
    if element.attrib or not _FIELD_NAME.fullmatch(element.tag):
        raise ValueError("invalid_xml_structure")
    for child in element:
        if child.tail and child.tail.strip():
            raise ValueError("invalid_xml_structure")
    if len(element) and element.text and element.text.strip():
        raise ValueError("invalid_xml_structure")
    return _Node(
        name=element.tag,
        text=element.text or "",
        children=[_xml_node(child) for child in element],
    )


def _markdown_node(text: str) -> _Node:
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines or lines[0] != "# output":
        raise ValueError("invalid_markdown_structure")
    root = _Node("output")
    stack = [(1, root)]
    for line in lines[1:]:
        match = _HEADING.fullmatch(line)
        if match is None:
            stack[-1][1].lines.append(line)
            continue
        level = len(match.group("level"))
        while stack and stack[-1][0] >= level:
            stack.pop()
        if not stack or level != stack[-1][0] + 1:
            raise ValueError("invalid_markdown_structure")
        node = _Node(match.group("name"))
        stack[-1][1].children.append(node)
        stack.append((level, node))
    return root


def _scalar(node: _Node, schema_type: str, output_format: str) -> Any:
    if node.children:
        raise ValueError(f"invalid_{output_format}_scalar")
    if output_format == "markdown":
        if schema_type == "string":
            if not node.lines or any(not line.startswith("> ") for line in node.lines):
                raise ValueError("invalid_markdown_string")
            return "\n".join(line[2:] for line in node.lines)
        if len(node.lines) != 1:
            raise ValueError("invalid_markdown_scalar")
        text = node.lines[0]
    else:
        text = node.text
        if schema_type == "string":
            return text
    if schema_type == "null":
        if text != ("null" if output_format == "markdown" else ""):
            raise ValueError(f"invalid_{output_format}_scalar")
        return None
    if schema_type == "boolean" and text in {"true", "false"}:
        return text == "true"
    if schema_type == "integer" and _INTEGER.fullmatch(text):
        return int(text)
    if schema_type == "number" and _NUMBER.fullmatch(text):
        value = float(text)
        if math.isfinite(value):
            return value
    raise ValueError(f"invalid_{output_format}_scalar")


def _decode_variant(node: _Node, schema: dict[str, Any], output_format: str) -> Any:
    schema_type = schema["type"]
    if schema_type in {"object", "array"}:
        if node.lines or node.text.strip():
            raise ValueError(f"invalid_{output_format}_structure")
        if schema_type == "array":
            item_name = _ITEM_NAMES.get(node.name, "item")
            if any(child.name != item_name for child in node.children):
                raise ValueError(f"invalid_{output_format}_array")
            if schema.get("items") is False:
                if node.children:
                    raise ValueError("unexpected_array_items")
                return []
            return [_decode(child, schema.get("items"), output_format) for child in node.children]
        properties = schema.get("properties", {})
        names = [child.name for child in node.children]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate_{output_format}_field")
        # Grammar checks presence and type. Bounds/enums/effect admission remain
        # owned by the Canonical validator after decoding.
        missing = set(schema.get("required", [])) - set(names)
        if missing:
            raise ValueError(f"missing_fields:{','.join(sorted(missing))}")
        extra = set(names) - set(properties)
        if extra:
            raise ValueError(f"unexpected_fields:{','.join(sorted(extra))}")
        return {
            child.name: _decode(child, properties[child.name], output_format)
            for child in node.children
        }
    return _scalar(node, schema_type, output_format)


def _decode(node: _Node, schema: object, output_format: str) -> Any:
    variants = _schema_variants(schema)
    if len(variants) == 1:
        return _decode_variant(node, variants[0], output_format)
    # Registered effect variants have a unique name const. Choose by that
    # discriminator before interpreting arguments with the branch's schema.
    for variant in variants:
        name_schema = variant.get("properties", {}).get("name", {})
        if "const" in name_schema:
            name_node = next((child for child in node.children if child.name == "name"), None)
            if name_node is None or _scalar(name_node, "string", output_format) != name_schema["const"]:
                continue
        try:
            return _decode_variant(node, variant, output_format)
        except ValueError:
            continue
    raise ValueError(f"invalid_{output_format}_schema_variant")


def parse_persona_text(
    text: object, output_format: str, *, schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    output = str(text or "")
    if len(output) > _MAX_LENGTH:
        raise ValueError("output_too_large")
    if output_format == "json":
        try:
            value = json.loads(output, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid_json") from exc
    elif output_format == "xml":
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b|<!--|<\?", output, re.I):
            raise ValueError("invalid_xml")
        try:
            element = ET.fromstring(output)
        except ET.ParseError as exc:
            raise ValueError("invalid_xml") from exc
        if element.tag != "output":
            raise ValueError("invalid_xml_structure")
        value = _decode(_xml_node(element), schema or _default_schema(), "xml")
    elif output_format == "markdown":
        value = _decode(_markdown_node(output), schema or _default_schema(), "markdown")
    else:
        raise ValueError("unsupported_output_format")
    if not isinstance(value, dict):
        raise ValueError("root_must_be_object")
    return value


def _example_value(schema: dict[str, Any]) -> Any:
    variant = _schema_variants(schema)[0]
    schema_type = variant["type"]
    if schema_type == "object":
        return {name: _example_value(child) for name, child in variant.get("properties", {}).items()}
    if schema_type == "array":
        items = variant.get("items")
        if items is False:
            return []
        return [_example_value(branch) for branch in _schema_variants(items)]
    if "const" in variant:
        return variant["const"]
    if variant.get("enum"):
        return variant["enum"][0]
    return {"string": "", "integer": 0, "number": 0.0, "boolean": False, "null": None}[schema_type]


def build_persona_text_example(schema: dict[str, Any], output_format: str) -> str:
    """Encode a schema-shaped example using the same semantic grammar."""
    example = _example_value(schema)
    if output_format == "xml":
        root = ET.Element("output")

        def append_xml(parent, name, value):
            if not _FIELD_NAME.fullmatch(name):
                raise ValueError("invalid_xml_schema_field")
            node = ET.SubElement(parent, name)
            if isinstance(value, dict):
                for key, item in value.items():
                    append_xml(node, key, item)
            elif isinstance(value, list):
                for item in value:
                    append_xml(node, _ITEM_NAMES.get(name, "item"), item)
            elif value is not None:
                node.text = str(value).lower() if isinstance(value, bool) else str(value)

        for name, value in example.items():
            append_xml(root, name, value)
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="unicode")
    lines = ["# output"]

    def append_markdown(name, value, level):
        if level > 6:
            raise ValueError("markdown_schema_depth_exceeds_six")
        if not _FIELD_NAME.fullmatch(name):
            raise ValueError("invalid_markdown_schema_field")
        lines.append(f"{'#' * level} {name}")
        if isinstance(value, dict):
            for key, item in value.items():
                append_markdown(key, item, level + 1)
        elif isinstance(value, list):
            for item in value:
                append_markdown(_ITEM_NAMES.get(name, "item"), item, level + 1)
        elif isinstance(value, str):
            lines.extend(f"> {line}" for line in value.split("\n"))
        elif value is None:
            lines.append("null")
        else:
            lines.append(str(value).lower() if isinstance(value, bool) else str(value))

    for name, value in example.items():
        append_markdown(name, value, 2)
    return "\n".join(lines)


def build_native_persona_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Project closed schemas to native strict JSON, retaining local validation."""
    result = deepcopy(schema)
    if "const" in result:
        result["enum"] = [result.pop("const")]
        result.setdefault("type", "string")
    if "oneOf" in result:
        result["anyOf"] = result.pop("oneOf")
    for key in ("anyOf", "allOf"):
        if key in result:
            result[key] = [build_native_persona_schema(branch) for branch in result[key]]
    if result.get("type") == "object":
        if isinstance(result.get("additionalProperties"), dict):
            raise ValueError("native_json_schema_requires_closed_objects")
        result["additionalProperties"] = False
        properties = result.get("properties", {})
        required = set(result.get("required", []))
        projected = {}
        for name, child in properties.items():
            value = build_native_persona_schema(child)
            if name not in required:
                value = {"anyOf": [value, {"type": "null"}]}
            projected[name] = value
        result["properties"] = projected
        result["required"] = list(properties)
    if result.get("type") == "array":
        if result.get("items") is False:
            # Native schemas require a schema object for items. The canonical
            # items=false constraint is still enforced by local effect admission.
            result["items"] = {"type": "string"}
            result["maxItems"] = 0
        elif isinstance(result.get("items"), dict):
            result["items"] = build_native_persona_schema(result["items"])
    return result


def restore_native_optional_fields(value: Any, schema: dict[str, Any]) -> Any:
    """Remove provider-required null placeholders for originally optional fields."""
    if isinstance(value, dict):
        variants = _schema_variants(schema)
        selected = next(
            (
                branch for branch in variants
                if branch.get("properties", {}).get("name", {}).get("const") == value.get("name")
            ),
            variants[0],
        )
        properties = selected.get("properties", {})
        required = set(selected.get("required", []))
        restored = {}
        for name, item in value.items():
            child = properties.get(name)
            if isinstance(child, dict):
                types = {branch.get("type") for branch in _schema_variants(child)}
                if item is None and name not in required and "null" not in types:
                    continue
                item = restore_native_optional_fields(item, child)
            restored[name] = item
        return restored
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [restore_native_optional_fields(item, schema["items"]) for item in value]
    return value
