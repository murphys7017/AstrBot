from __future__ import annotations

from typing import Any

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.output_contract import CompiledOutputContract, OutputContract


def _mark_strict_output_contract_tool(
    tool: FunctionTool,
    *,
    strict: bool,
) -> FunctionTool:
    """Mark a protocol tool for providers with provider-specific strict modes."""
    setattr(tool, "_astrbot_strict_output_contract", strict)
    return tool


def build_single_tool_set_from_contract(
    contract: OutputContract,
    *,
    description: str = "",
) -> ToolSet | None:
    tool_name = (contract.preferred_tool_name or "").strip()
    if contract.mode != "tool_call" or not tool_name:
        return None

    tool_set = ToolSet()
    tool_set.add_tool(
        _mark_strict_output_contract_tool(
            FunctionTool(
                name=tool_name,
                description=description,
                parameters=_build_tool_parameters_from_contract(contract),
                handler=None,
            ),
            strict=contract.strict,
        )
    )
    return tool_set


def build_single_tool_set_from_compiled_contract(
    compiled_contract: CompiledOutputContract | None,
    *,
    description: str = "",
) -> ToolSet | None:
    if compiled_contract is None:
        return None
    tool_name = (compiled_contract.tool_name or "").strip()
    if compiled_contract.strategy != "protocol_tool_call" or not tool_name:
        return None

    tool_set = ToolSet()
    tool_set.add_tool(
        _mark_strict_output_contract_tool(
            FunctionTool(
                name=tool_name,
                description=description,
                parameters=_normalize_tool_schema(compiled_contract.tool_schema),
                handler=None,
            ),
            strict=compiled_contract.contract.strict,
        )
    )
    return tool_set


def merge_output_contract_tool_set(
    func_tool: ToolSet | None,
    contract_tool_set: ToolSet | None,
) -> ToolSet | None:
    """Combine executable tools with a protocol-level output tool.

    The returned ToolSet is detached from the executable inventory. A name
    collision is resolved in favor of the output contract so a plugin cannot
    replace a terminal protocol schema with an executable handler.
    """
    if contract_tool_set is None or contract_tool_set.empty():
        return func_tool

    merged = ToolSet(list(func_tool.tools) if func_tool is not None else [])
    for tool in contract_tool_set:
        merged.add_tool(tool)
    return merged


def resolve_output_contract_binding(
    output_contract: OutputContract | None,
    compiled_output_contract: CompiledOutputContract | None,
    func_tool: ToolSet | None,
    tool_choice: Any,
) -> tuple[ToolSet | None, Any]:
    """Attach the protocol output tool without duplicating provider adapters."""
    if isinstance(compiled_output_contract, CompiledOutputContract):
        func_tool = merge_output_contract_tool_set(
            func_tool,
            build_single_tool_set_from_compiled_contract(
                compiled_output_contract,
                description="Return structured output.",
            ),
        )
        if compiled_output_contract.strategy == "protocol_tool_call":
            tool_choice = "required"
        return func_tool, tool_choice
    if not isinstance(output_contract, OutputContract):
        return func_tool, tool_choice

    normalized_contract = output_contract
    if output_contract.mode == "json_object" and output_contract.strict:
        normalized_contract = OutputContract(
            mode="tool_call",
            strict=True,
            schema=output_contract.schema,
            preferred_tool_name=output_contract.preferred_tool_name,
            allow_text_fallback=output_contract.allow_text_fallback,
        )
    if normalized_contract.mode == "tool_call":
        func_tool = merge_output_contract_tool_set(
            func_tool,
            build_single_tool_set_from_contract(
                normalized_contract,
                description="Return structured output.",
            ),
        )
        if normalized_contract.strict:
            tool_choice = "required"
    return func_tool, tool_choice


def _build_tool_parameters_from_contract(contract: OutputContract) -> dict[str, Any]:
    schema = contract.schema if isinstance(contract.schema, dict) else None
    return _normalize_tool_schema(schema)


def _normalize_tool_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    if schema is None:
        return {"type": "object", "properties": {}}

    normalized_schema = dict(schema)
    normalized_schema.setdefault("type", "object")
    properties = normalized_schema.get("properties")
    if not isinstance(properties, dict):
        normalized_schema["properties"] = {}
    required = normalized_schema.get("required")
    if required is not None and not isinstance(required, list):
        normalized_schema.pop("required", None)
    return normalized_schema


__all__ = [
    "build_single_tool_set_from_compiled_contract",
    "build_single_tool_set_from_contract",
    "merge_output_contract_tool_set",
    "resolve_output_contract_binding",
]
