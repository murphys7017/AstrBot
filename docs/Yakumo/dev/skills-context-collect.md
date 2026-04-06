# Skills Context Collect

记录本次 `SkillsCollector` v1 的实现范围、代码改动、数据结构和验证结果。

## 范围

- 新增 `SkillsCollector`
- 收集当前会话可用的 active skills inventory
- 写入 `ContextPack` 供日志调试
- 不改 render
- 不改 `_ensure_persona_and_skills(...)` 现有行为
- 不在 collect 阶段应用 persona skills 白名单

## 本次实现

### 新增类

#### `astrbot/core/prompt/collectors/skills_collector.py`

新增 `SkillsCollector`。

职责：

- 读取当前 runtime 下的 active skills
- 收集 `capability.skills_prompt`

主要函数：

- `collect(...)`
- `_resolve_runtime(...)`
- `_load_active_skills(...)`
- `_build_skills_slot(...)`
- `_serialize_skill(...)`

实现要点：

- 使用 `SkillManager.list_skills(active_only=True, runtime=runtime)` 收集 skills
- `runtime` 来自 `config.computer_use_runtime`，缺失时回退 `local`
- `slot.value` 使用结构化 inventory，不生成最终 prompt 文本
- 不读取或应用 `persona.skills_whitelist`
- 没有 active skills 时不产出 slot
- fail-open，skill 读取失败只打 warning，不中断 collect

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

### `astrbot/core/prompt/collectors/__init__.py`

新增导出：

- `SkillsCollector`

### `astrbot/core/prompt/__init__.py`

新增导出：

- `SkillsCollector`

### `tests/unit/test_prompt_context_collect.py`

新增 skills collect 测试，并增加默认 `SkillManager.list_skills(...)` patch，避免测试读取本机真实技能目录。

新增测试：

- `test_collect_context_pack_collects_skills_inventory_for_local_runtime()`
- `test_collect_context_pack_collects_skills_inventory_for_sandbox_runtime()`
- `test_collect_context_pack_skips_skills_slot_when_no_active_skills()`
- `test_collect_context_pack_skills_fail_open_when_skill_manager_raises()`

调整测试：

- `test_collect_context_pack_default_collectors_include_session_collector()`
  - 默认 collector 列表新增 `SkillsCollector`

## 当前 slot 结构

### `capability.skills_prompt`

value:

- `format`
- `runtime`
- `skill_count`
- `skills`

其中 `skills[*]` 包含：

- `name`
- `description`
- `path`
- `source_type`
- `source_label`
- `active`
- `local_exists`
- `sandbox_exists`

meta:

- `format=skills_inventory_v1`
- `runtime=<runtime>`
- `skill_count=<count>`

## 设计思路

- 先把当前 active skills 作为结构化 inventory 收集进 prompt context
- 不在 collect 阶段复刻旧的 skills prompt 注入逻辑
- persona 白名单保持独立，由 `PersonaCollector` 提供，后续 selector / renderer 再合并
- value 保留 runtime、path、source 元数据，便于日志观察和后续渲染
- 保持 collect-only，不把 `build_skills_prompt(...)` 混进本次实现

## 验证

执行：

- `uv run pytest tests/unit/test_prompt_context_collect.py`
- `uv run ruff format astrbot/core/prompt/collectors/skills_collector.py astrbot/core/prompt/collectors/__init__.py astrbot/core/prompt/__init__.py astrbot/core/prompt/context_collect.py tests/unit/test_prompt_context_collect.py`
- `uv run ruff check astrbot/core/prompt/collectors/skills_collector.py astrbot/core/prompt/collectors/__init__.py astrbot/core/prompt/__init__.py astrbot/core/prompt/context_collect.py tests/unit/test_prompt_context_collect.py`

结果以实际命令输出为准。
