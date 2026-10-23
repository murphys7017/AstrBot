from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Generic, TypeVar

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_MODULE_PATH = REPO_ROOT / "astrbot/core/agent/tool.py"


def load_tool_module():
    package_names = [
        "astrbot",
        "astrbot.core",
        "astrbot.core.agent",
        "astrbot.core.message",
    ]
    for name in package_names:
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = []
            sys.modules[name] = module

    message_result_module = types.ModuleType(
        "astrbot.core.message.message_event_result"
    )
    message_result_module.MessageEventResult = type("MessageEventResult", (), {})
    sys.modules[message_result_module.__name__] = message_result_module

    run_context_module = types.ModuleType("astrbot.core.agent.run_context")
    run_context_module.TContext = TypeVar("TContext")

    class ContextWrapper(Generic[run_context_module.TContext]):
        pass

    run_context_module.ContextWrapper = ContextWrapper
    sys.modules[run_context_module.__name__] = run_context_module

    spec = importlib.util.spec_from_file_location(
        "astrbot.core.agent.tool", TOOL_MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_google_schema_fills_missing_array_items_with_string_schema():
    tool_module = load_tool_module()
    FunctionTool = tool_module.FunctionTool
    ToolSet = tool_module.ToolSet

    tool = FunctionTool(
        name="search_sources",
        description="Search sources by UUID.",
        parameters={
            "type": "object",
            "properties": {
                "source_uuids": {
                    "type": "array",
                    "description": "Optional list of source UUIDs.",
                }
            },
            "required": ["source_uuids"],
        },
    )

    schema = ToolSet([tool]).google_schema()
    source_uuids = schema["function_declarations"][0]["parameters"]["properties"][
        "source_uuids"
    ]

    assert source_uuids["type"] == "array"
    assert source_uuids["items"] == {"type": "string"}


def test_google_schema_keeps_non_string_enum_types_valid():
    tool_module = load_tool_module()
    FunctionTool = tool_module.FunctionTool
    ToolSet = tool_module.ToolSet

    tool = FunctionTool(
        name="list_items",
        description="List items.",
        parameters={
            "type": "object",
            "properties": {
                "page_size": {
                    "type": "integer",
                    "description": "Items per page.",
                    "enum": [10, 20, 50],
                },
                "strict": {"type": "boolean", "enum": [True]},
                "order": {
                    "type": ["string", "null"],
                    "enum": ["asc", "desc", None],
                },
            },
        },
    )

    properties = ToolSet([tool]).google_schema()["function_declarations"][0][
        "parameters"
    ]["properties"]

    assert properties["page_size"] == {
        "type": "integer",
        "description": "Items per page.\nAllowed values: 10, 20, 50",
    }
    assert properties["strict"] == {
        "type": "boolean",
        "description": "Allowed values: true",
    }
    assert properties["order"] == {
        "type": "string",
        "enum": ["asc", "desc"],
        "nullable": True,
    }
    assert tool.parameters["properties"]["page_size"]["enum"] == [10, 20, 50]


def test_openai_schema_sorts_tools_by_name_without_mutating_toolset_order():
    tool_module = load_tool_module()
    FunctionTool = tool_module.FunctionTool
    ToolSet = tool_module.ToolSet

    toolset = ToolSet(
        [
            FunctionTool(
                name="zebra",
                description="Zebra tool.",
                parameters={"type": "object", "properties": {}},
            ),
            FunctionTool(
                name="alpha",
                description="Alpha tool.",
                parameters={"type": "object", "properties": {}},
            ),
            FunctionTool(
                name="middle",
                description="Middle tool.",
                parameters={"type": "object", "properties": {}},
            ),
        ]
    )

    schema = toolset.openai_schema()

    assert [tool["function"]["name"] for tool in schema] == [
        "alpha",
        "middle",
        "zebra",
    ]
    assert [tool.name for tool in toolset.tools] == ["zebra", "alpha", "middle"]


def test_provider_schemas_supply_fallback_descriptions_for_undocumented_tools():
    tool_module = load_tool_module()
    FunctionTool = tool_module.FunctionTool
    ToolSet = tool_module.ToolSet

    toolset = ToolSet(
        [
            FunctionTool(
                name="weather_lookup",
                description="",
                parameters={
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            )
        ]
    )

    openai_description = toolset.openai_schema()[0]["function"]["description"]
    anthropic_description = toolset.anthropic_schema()[0]["description"]
    google_description = toolset.google_schema()["function_declarations"][0][
        "description"
    ]

    assert "weather_lookup" in openai_description
    assert "city" in anthropic_description
    assert google_description == openai_description
