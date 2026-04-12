# Tools Context Collect

记录本次 `ToolsCollector` v1 的实现范围、代码改动、数据结构和验证结果。

## 范围

- 新增 `ToolsCollector`
- 收集当前会话可见的基础 tools inventory
- 写入 `ContextPack` 供日志调试
- 不改 render
- 不改原有主链路 tool 注入逻辑
- 不在本次实现中处理 subagent handoff / router prompt
- 不收集 safety / sandbox / local env / cron 等后续运行时追加工具

## 本次实现

### 新增类

#### `astrbot/core/prompt/collectors/tools_collector.py`

新增 `ToolsCollector`。

职责：

- 解析当前 persona 生效后的基础 tool 可见集
- 收集 `capability.tools_schema`

主要函数：

- `collect(...)`
- `_resolve_persona(...)`
- `_build_persona_toolset(...)`
- `_build_tools_slot(...)`
- `_serialize_tool(...)`

实现要点：

- `collect` 只做只读收集，不修改 `ProviderRequest`
- collector 不依赖 `provider_request.func_tool`
- 因为当前 `collect_context_pack(...)` 调用时机早于 `_decorate_llm_request(...)`
- 所以这里在 collector 内独立复现 `_ensure_persona_and_skills(...)` 里的“基础 tool 选择逻辑”
- 无 persona tools 白名单时：
  - 使用 `plugin_context.get_llm_tool_manager().get_full_tool_set()`
  - 再过滤 `active=False` 的工具
- persona tools 为具体列表时：
  - 按白名单调用 `tool_manager.get_func(name)` 收集
  - 仅保留 active tool
- persona tools 为空列表时：
  - 视为显式禁用 tools
  - 不产出 slot
- `slot.value` 使用结构化 inventory，不直接生成最终 prompt 字符串
- fail-open，tool manager 或 persona 解析失败只打 warning，不中断 collect

## 修改文件

### `astrbot/core/prompt/context_collect.py`

默认 collector 链扩展为：

- `PersonaCollector`
- `InputCollector`
- `SessionCollector`
- `PolicyCollector`
- `MemoryCollector`
- `ConversationHistoryCollector`
- `SkillsCollector`
- `ToolsCollector`

### `astrbot/core/prompt/collectors/__init__.py`

新增导出：

- `ToolsCollector`

### `astrbot/core/prompt/__init__.py`

新增导出：

- `ToolsCollector`

### `tests/unit/test_prompt_context_collect.py`

新增 tools collect 测试。

新增测试：

- `test_collect_context_pack_collects_tools_inventory_from_full_toolset()`
- `test_collect_context_pack_collects_tools_inventory_with_persona_whitelist()`
- `test_collect_context_pack_skips_tools_slot_when_persona_disables_tools()`
- `test_collect_context_pack_tools_fail_open_when_tool_manager_raises()`

调整测试：

- `test_collect_context_pack_default_collectors_include_session_collector()`
  - 默认 collector 列表新增 `ToolsCollector`

## 当前 slot 结构

### `capability.tools_schema`

value:

- `format`
- `tool_count`
- `tools`

其中 `tools[*]` 包含：

- `name`
- `description`
- `parameters`
- `active`
- `handler_module_path`
- `schema`

meta:

- `format=tool_inventory_v1`
- `tool_count=<count>`
- `persona_id=<resolved persona id>`
- `selection_mode=all|whitelist|none`

## 设计思路

- 先把当前基础 tool 可见集作为结构化 inventory 收集进 prompt context
- 不提前改写 `astr_main_agent.py` 里的原始 tool 注入逻辑
- 不在本次 collector 中处理后续 runtime augmentation
- 只对齐 `_ensure_persona_and_skills(...)` 里的基础 tools 解析语义
- 保留 `parameters` 和 `schema`，便于后续 renderer / selector 直接消费
- 保持 collect-only，不把运行期的 tool merge 逻辑混进这次实现

## 本次实现边界

- 不修改 `astrbot/core/astr_main_agent.py`
- 不修改 `_ensure_persona_and_skills(...)`
- 不修改 `_apply_llm_safety_mode()`
- 不修改 `_apply_sandbox_tools()`
- 不修改 `_apply_local_env_tools()`
- 不修改 `_proactive_cron_job_tools()`
- 不处理 `capability.subagent_handoff_tools`
- 不处理 `capability.subagent_router_prompt`
- 不做 renderer
- 不做 selector
- 不改 `ProviderRequest`

## 验证

执行：

- `uv run pytest tests/unit/test_prompt_context_collect.py`
- `uv run ruff format astrbot/core/prompt/collectors/tools_collector.py astrbot/core/prompt/collectors/__init__.py astrbot/core/prompt/__init__.py astrbot/core/prompt/context_collect.py tests/unit/test_prompt_context_collect.py`
- `uv run ruff check astrbot/core/prompt/collectors/tools_collector.py astrbot/core/prompt/collectors/__init__.py astrbot/core/prompt/__init__.py astrbot/core/prompt/context_collect.py tests/unit/test_prompt_context_collect.py`

结果以实际命令输出为准。
