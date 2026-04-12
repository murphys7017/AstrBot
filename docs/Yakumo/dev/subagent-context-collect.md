# Subagent Context Collect

记录本次 `SubagentCollector` v1 的实现范围、代码改动、数据结构和验证结果。

## 范围

- 新增 `SubagentCollector`
- 收集当前主 Agent 可见的 subagent handoff tools 和 router prompt
- 写入 `ContextPack` 供日志调试
- 不改 render
- 不改原有主链路 subagent 注入逻辑
- 不展开 subagent 内部 `Agent` 结构
- 不模拟 duplicate removal 后的最终工具集

## 本次实现

### 新增类

#### `astrbot/core/prompt/collectors/subagent_collector.py`

新增 `SubagentCollector`。

职责：

- 收集 `capability.subagent_handoff_tools`
- 收集 `capability.subagent_router_prompt`

主要函数：

- `collect(...)`
- `_resolve_orchestrator_config(...)`
- `_build_handoff_tools_slot(...)`
- `_build_router_prompt_slot(...)`
- `_serialize_handoff_tool(...)`

实现要点：

- `collect` 只做只读收集，不修改 `ProviderRequest`
- 数据来源固定为：
  - `plugin_context.get_config().get("subagent_orchestrator", {})`
  - `plugin_context.subagent_orchestrator.handoffs`
- 只有以下条件同时满足时才收集 subagent slot：
  - `subagent_orchestrator.main_enable == true`
  - `plugin_context.subagent_orchestrator` 存在
- `capability.subagent_handoff_tools` 采用贴近原版主 Agent 可见结构的“Thin + Flags”形式
- `tools[*]` 只保留 handoff tool 当前可见字段：
  - `name`
  - `description`
  - `parameters`
- 不展开：
  - `handoff.agent.instructions`
  - `handoff.agent.tools`
  - `handoff.agent.begin_dialogs`
  - `handoff.provider_id`
- `capability.subagent_router_prompt` 直接保留原始字符串
- fail-open，subagent 配置或运行时对象读取失败只打 warning，不中断 collect

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
- `SubagentCollector`

### `astrbot/core/prompt/collectors/__init__.py`

新增导出：

- `SubagentCollector`

### `astrbot/core/prompt/__init__.py`

新增导出：

- `SubagentCollector`

### `tests/unit/test_prompt_context_collect.py`

新增 subagent collect 测试。

新增测试：

- `test_collect_context_pack_skips_subagent_slots_when_main_enable_disabled()`
- `test_collect_context_pack_collects_subagent_handoff_tools_inventory()`
- `test_collect_context_pack_collects_subagent_router_prompt()`
- `test_collect_context_pack_skips_subagent_slots_when_orchestrator_missing()`

调整测试：

- `test_collect_context_pack_default_collectors_include_session_collector()`
  - 默认 collector 列表新增 `SubagentCollector`

## 当前 slot 结构

### `capability.subagent_handoff_tools`

value:

- `format`
- `main_enable`
- `remove_main_duplicate_tools`
- `tool_count`
- `tools`

其中 `tools[*]` 包含：

- `name`
- `description`
- `parameters`

meta:

- `format=handoff_tools_v1`
- `tool_count=<count>`
- `main_enable=<bool>`
- `remove_main_duplicate_tools=<bool>`

### `capability.subagent_router_prompt`

value:

- `str`

meta:

- `enabled_by_config`
- `main_enable`
- `source=subagent_orchestrator.router_system_prompt`

## 设计思路

- 这次 collector 明确贴近原版主 Agent 实际可见的 subagent 上下文
- 原版主链路本质上只消费两类 subagent 信息：
  - handoff tools
  - router system prompt
- 所以本次不把 subagent 内部 `Agent` 对象摊开成新的 prompt 数据结构
- `remove_main_duplicate_tools` 只作为配置摘要暴露，便于日志确认
- 保持 collect-only，不把运行态的工具合并和裁剪逻辑搬进本次实现

## 本次实现边界

- 不修改 `astrbot/core/astr_main_agent.py`
- 不修改 `_ensure_persona_and_skills(...)`
- 不修改 subagent orchestrator 现有行为
- 不处理最终 `req.func_tool` 的 duplicate removal 结果
- 不新增 catalog 槽位
- 不做 renderer
- 不做 selector
- 不改 `ProviderRequest`

## 验证

执行：

- `uv run pytest tests/unit/test_prompt_context_collect.py`
- `uv run ruff format astrbot/core/prompt/collectors/subagent_collector.py astrbot/core/prompt/collectors/__init__.py astrbot/core/prompt/__init__.py astrbot/core/prompt/context_collect.py tests/unit/test_prompt_context_collect.py`
- `uv run ruff check astrbot/core/prompt/collectors/subagent_collector.py astrbot/core/prompt/collectors/__init__.py astrbot/core/prompt/__init__.py astrbot/core/prompt/context_collect.py tests/unit/test_prompt_context_collect.py`

结果以实际命令输出为准。
