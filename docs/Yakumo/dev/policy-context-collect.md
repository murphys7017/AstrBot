# Policy Context Collect

本文件记录本次 `PolicyCollector` 链路开发的实际改动、接入位置、数据来源、约束和验证结果。

## 本次目标

- 完成 `policy` 类 context 的第一批 collect
- 将当前 system policy 信息整理进 `ContextPack`
- 先用于日志调试和后续 renderer/selector 准备
- 不改变现有 `ProviderRequest` 的注入与执行行为
- 不在本次实现中处理 `system.base` 或 `system.tool_call_instruction`

## 本次改动摘要

- 新增 `PolicyCollector`
- 将默认 collector 链路扩展为：
  - `PersonaCollector`
  - `InputCollector`
  - `SessionCollector`
  - `PolicyCollector`
- 收集当前安全模式 prompt
- 收集当前 sandbox runtime prompt
- 补充 policy collect 的单元测试

## 新增文件

### `astrbot/core/prompt/collectors/policy_collector.py`

新增 `PolicyCollector`。

职责：

- 收集 `policy.safety_prompt`
- 收集 `policy.sandbox_prompt`

主要内部函数：

- `collect(...)`
- `_build_safety_prompt_slot(...)`
- `_build_sandbox_prompt_slot(...)`

核心设计：

- `policy.safety_prompt` 只在以下条件同时满足时收集：
  - `config.llm_safety_mode = True`
  - `config.safety_mode_strategy = "system_prompt"`
- `policy.sandbox_prompt` 只在以下条件满足时收集：
  - `config.computer_use_runtime = "sandbox"`
- `collect` 阶段只读当前生效的 policy 文本，不反向写回 `ProviderRequest`
- 失败策略为 fail-open，局部失败只记录 warning，不中断整体 collect

## 修改文件

### `astrbot/core/prompt/context_collect.py`

本次修改：

- 新增 `PolicyCollector` 导入
- 修改 `_default_collectors()`
- 默认 collector 顺序变为：
  - `PersonaCollector`
  - `InputCollector`
  - `SessionCollector`
  - `PolicyCollector`

结果：

- `collect_context_pack(...)` 现在会在原有 collect 基础上继续收集 policy context
- `ContextPack.meta["collectors"]` 中会包含 `PolicyCollector`

### `astrbot/core/prompt/collectors/__init__.py`

本次修改：

- 导出 `PolicyCollector`

### `astrbot/core/prompt/__init__.py`

本次修改：

- 导出 `PolicyCollector`

### `tests/unit/test_prompt_context_collect.py`

本次新增测试：

- `test_collect_context_pack_collects_policy_safety_prompt_when_enabled()`
- `test_collect_context_pack_skips_policy_safety_prompt_when_disabled()`
- `test_collect_context_pack_collects_policy_sandbox_prompt_for_sandbox_runtime()`
- `test_collect_context_pack_skips_policy_sandbox_prompt_for_local_runtime()`

并扩展默认 collector 链测试：

- `test_collect_context_pack_default_collectors_include_session_collector()`

覆盖点：

- safety mode 开启时收集 `policy.safety_prompt`
- safety mode 关闭时不收集
- sandbox runtime 时收集 `policy.sandbox_prompt`
- local runtime 时不收集 sandbox prompt
- 默认 collector 链包含 `PolicyCollector`

## 当前 policy slot 结构

### `policy.safety_prompt`

value:

- `str`

来源：

- `astrbot/core/astr_main_agent_resources.py`
  - `LLM_SAFETY_MODE_SYSTEM_PROMPT`

meta:

- `enabled_by_config`
- `strategy`

### `policy.sandbox_prompt`

value:

- `str`

来源：

- `astrbot/core/astr_main_agent_resources.py`
  - `SANDBOX_MODE_PROMPT`

meta:

- `enabled_by_config`
- `runtime`

## 本次实现边界

- 不修改 `astrbot/core/astr_main_agent.py` 中现有行为：
  - `_apply_llm_safety_mode()`
  - `_apply_sandbox_tools()`
  - `_apply_local_env_tools()`
- 不收集 local runtime prompt
- 不处理 `system.base`
- 不处理 `system.tool_call_instruction`
- 不做 renderer
- 不做 selector
- 不改 `ProviderRequest`

## 数据来源说明

### `policy.safety_prompt`

使用：

- `config.llm_safety_mode`
- `config.safety_mode_strategy`
- `LLM_SAFETY_MODE_SYSTEM_PROMPT`

当前语义保持和旧链路一致：

- 只有 `system_prompt` 策略下，才产出 safety slot

### `policy.sandbox_prompt`

使用：

- `config.computer_use_runtime`
- `SANDBOX_MODE_PROMPT`

当前语义保持和旧链路一致：

- 只在 `sandbox` runtime 下产出 sandbox slot
- `local` runtime 不产出独立 policy slot

## 验证结果

本次执行：

- `uv run pytest tests/unit/test_prompt_context_collect.py`
- `uv run ruff check astrbot/core/prompt/collectors/policy_collector.py astrbot/core/prompt/collectors/__init__.py astrbot/core/prompt/__init__.py astrbot/core/prompt/context_collect.py tests/unit/test_prompt_context_collect.py`

结果：

- `tests/unit/test_prompt_context_collect.py` 全部通过
- 本次涉及文件的 `ruff check` 通过

## 本次思路

- 先把当前 system policy 从主链路里抽出一层结构化 collect
- 只做“当前哪些 policy 生效”的数据准备
- 不提前进入 render，也不替换旧的 req 注入逻辑
- 优先处理边界最清晰、来源最稳定的 policy：
  - safety
  - sandbox

这样可以在不改变运行行为的前提下，让 policy 进入统一的 prompt/context 数据层。
