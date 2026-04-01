# Persona Segments Prepare

记录本次 persona prompt 结构化解析开发。

## 本次目标

- 保持现有 persona 内容不变
- 保持现有 persona 注入行为不变
- 只新增一层数据准备能力
- 将现有 `persona.prompt` 解析成结构化 `persona.segments`
- 将解析结果挂入 collect 链路
- 不做 render
- 不做回写 `ProviderRequest`
- 不替换旧的 `_ensure_persona_and_skills()` 逻辑

## 本次结论

当前系统已经具备：

- 从 legacy persona prompt 解析结构化 segments
- 在 `PersonaCollector` 中收集 `persona.segments`
- 将 `persona.segments` 放入 `ContextPack`

当前系统还没有做：

- `persona.rendered`
- XML 渲染
- 用 `persona.segments` 替换现有 system prompt 注入

## 改动文件

### 新增文件

- `astrbot/core/prompt/persona_segments.py`
- `tests/unit/test_persona_segments.py`
- `docs/Yakumo/dev/persona-segments-prepare.md`

### 修改文件

- `astrbot/core/prompt/collectors/persona_collector.py`
- `astrbot/core/prompt/__init__.py`
- `data/config/prompt/context_catalog.yaml`
- `tests/unit/test_prompt_context_collect.py`

## 新增模块

## `astrbot/core/prompt/persona_segments.py`

新增 legacy persona prompt 解析模块。

职责：

- 将自由文本 persona prompt 解析为结构化 dict
- 将 section 标题映射为稳定的内部 key
- 为 collect 阶段提供稳定的数据结构
- 对未识别内容做兜底保留

## 新增函数

### `_empty_persona_segments()`

返回标准的 persona segments 初始结构。

当前结构包含：

- `identity`
- `core_persona`
- `tone_examples`
- `dialogue_style`
- `interaction_reactions`
- `progressive_understanding`
- `rational_bias`
- `memory_hooks`
- `personality_drives`
- `personality_state_machine`
- `relationship_layer`
- `interaction_memory`
- `stable_rules`
- `unparsed_sections`

### `_canonicalize_title(value: str) -> str`

用途：

- 规范化 section 标题
- 统一处理中英文括号
- 去掉尾部冒号
- 去掉空格
- 转小写

用于把：

- `认知偏差（Rational Bias）`
- `Personality State Machine`
- `Relationship Layer`

映射到稳定查找键。

### `normalize_section_name(title: str) -> str | None`

用途：

- 将原始标题映射到内部 section key

当前支持的 key：

- `identity`
- `core_persona`
- `tone_examples`
- `dialogue_style`
- `interaction_reactions`
- `progressive_understanding`
- `rational_bias`
- `memory_hooks`
- `personality_drives`
- `personality_state_machine`
- `relationship_layer`
- `interaction_memory`
- `stable_rules`

### `_normalize_interaction_reaction_name(title: str) -> str | None`

用途：

- 解析 `互动反应` 下的子块标题

当前支持：

- `被夸` -> `praised`
- `被取外号` -> `nickname`
- `暧昧/关心` -> `affection_or_care`

### `_parse_content_line(line: str) -> str`

用途：

- 去掉 `- ` 前缀
- 去掉 `「...」` 包裹
- 返回标准文本内容

### `_append_unique(items: list[str], value: str) -> None`

用途：

- 向列表追加非空且不重复的文本

### `_parse_state_machine_line(line: str) -> tuple[str, str] | None`

用途：

- 解析：
  - `Normal：xxx`
  - `Teaching：xxx`
  - `Mocking：xxx`
  - `Curious：xxx`
  - `Tsundere：xxx`

输出：

- `(state_key, state_value)`

### `_parse_relationship_affinity(line: str) -> int | None`

用途：

- 解析：
  - `当前关系值：100（最高亲近）`

输出：

- `100`

### `parse_legacy_persona_prompt(prompt: str) -> dict[str, object]`

本次核心函数。

职责：

- 扫描 legacy persona prompt
- 按 section 解析
- 识别列表、状态机、互动反应子块、关系值
- 输出结构化 `segments`

当前解析规则：

- 一级标题识别 section
- `- xxx` 识别为列表项
- `「xxx」` 识别为文本项
- `被夸：` / `被取外号：` / `暧昧/关心：` 识别为 reaction 子块
- `Normal：xxx` 识别为状态机项
- `当前关系值：100` 识别为 affinity
- 不能识别的内容进入 `unparsed_sections`

### `finalize_persona_segments(parsed: dict[str, object]) -> dict[str, object]`

用途：

- 将解析结果合并到标准结构
- 保证输出结构稳定
- 即使部分 section 未解析成功，返回值仍然完整

## `PersonaCollector` 修改

文件：

- `astrbot/core/prompt/collectors/persona_collector.py`

本次新增行为：

- 在收集到 `persona.prompt` 之后
- 调用 `parse_legacy_persona_prompt(prompt_slot.value)`
- 新增 `ContextSlot(name="persona.segments", ...)`

新 slot：

- `name`: `persona.segments`
- `category`: `persona`
- `source`: `persona_parser`

当前 `meta`：

- `persona_id`
- `source_slot = "persona.prompt"`
- `parser = "legacy_prompt_v1"`

当前保持不变：

- `persona.prompt`
- `persona.begin_dialogs`
- `persona.tools_whitelist`
- `persona.skills_whitelist`

## `context_catalog` 修改

文件：

- `data/config/prompt/context_catalog.yaml`

本次新增声明：

- `persona.segments`

配置：

- `category: persona`
- `slots: [persona]`
- `required: false`
- `multiple: false`
- `lifecycle: session`

目的：

- 让 collect 阶段新增的 `persona.segments` 成为正式 catalog 项

## `__init__.py` 修改

文件：

- `astrbot/core/prompt/__init__.py`

本次新增导出：

- `normalize_section_name`
- `parse_legacy_persona_prompt`
- `finalize_persona_segments`

目的：

- 让 persona parser 成为 prompt 模块的正式公开入口之一

## 测试

### `tests/unit/test_persona_segments.py`

新增 parser 测试。

测试内容：

- 能解析 `identity`
- 能解析 `tone_examples`
- 能解析 `interaction_reactions`
- 能解析 `personality_state_machine`
- 能解析 `relationship_layer.current_affinity`
- 能解析 `memory_hooks`
- 能解析 `interaction_memory`

测试输入：

- 使用 Alice 风格的完整 legacy persona prompt

### `tests/unit/test_prompt_context_collect.py`

本次补充验证：

- collect 结果中包含 `persona.segments`
- 简单单段 prompt 能走兜底路径
- `webchat` special default persona 也能生成 `persona.segments`
- 主链路 `build_main_agent()` 之后 `prompt_context_pack` 中可拿到 `persona.segments`

## 当前输出结构

`persona.segments` 当前结构：

```python
{
    "identity": list[str],
    "core_persona": list[str],
    "tone_examples": list[str],
    "dialogue_style": list[str],
    "interaction_reactions": {
        "praised": list[str],
        "nickname": list[str],
        "affection_or_care": list[str],
    },
    "progressive_understanding": list[str],
    "rational_bias": list[str],
    "memory_hooks": list[str],
    "personality_drives": list[str],
    "personality_state_machine": {
        "normal": str,
        "teaching": str,
        "mocking": str,
        "curious": str,
        "tsundere": str,
    },
    "relationship_layer": {
        "current_affinity": int | None,
        "traits": list[str],
    },
    "interaction_memory": list[str],
    "stable_rules": list[str],
    "unparsed_sections": list[str],
}
```

## 设计思路

### 1. 先保持 persona 内容不变

这次没有要求用户先把 persona 手工改成新结构。

做法：

- 直接读取现有 `persona.prompt`
- 在运行时解析

原因：

- 可以快速兼容已有 persona
- 不需要先改 DB / Dashboard / 配置来源

### 2. 先做 prepare，不做 render

这次只做：

- 读取
- 解析
- 结构化
- collect

这次不做：

- 渲染为 XML
- 渲染为 `<persona><identity>...</identity></persona>`
- 用新结构替换旧 prompt 行为

原因：

- 先确认数据结构够不够用
- 先确认 parser 是否能稳定覆盖当前 persona 文本

### 3. fail-open

这次 parser 设计成保守模式。

表现：

- 某些 section 识别不到，不会影响主链路
- 解析不了的内容进入 `unparsed_sections`
- 简单 prompt 也能得到稳定结构

### 4. 先兼容 legacy prompt，再考虑原生 segments

当前路线是：

- legacy persona prompt -> `persona.segments`

不是：

- 直接改 persona 存储格式

原因：

- 当前系统里 persona 还是 DB / Dashboard 驱动
- 直接改 schema 会扩大改动面
- 先用 parser 建中间层更稳

## 本次没有做的事

- 没有新增 `persona.rendered`
- 没有新增 XML renderer
- 没有把 `persona.segments` 渲染回 `system_prompt`
- 没有修改 persona Dashboard 表单
- 没有修改 persona DB schema
- 没有把 persona 原始存储改成 YAML

## 验证

执行过：

- `uv run pytest tests/unit/test_persona_segments.py tests/unit/test_prompt_context_collect.py -q`
- `uv run ruff format astrbot/core/prompt/persona_segments.py astrbot/core/prompt/collectors/persona_collector.py astrbot/core/prompt/__init__.py tests/unit/test_persona_segments.py tests/unit/test_prompt_context_collect.py`
- `uv run ruff check astrbot/core/prompt/persona_segments.py astrbot/core/prompt/collectors/persona_collector.py astrbot/core/prompt/__init__.py tests/unit/test_persona_segments.py tests/unit/test_prompt_context_collect.py`

结果：

- 4 个测试通过
- 针对本次新增和修改文件的 ruff check 通过

补充：

- 执行过 `uv run ruff format .`
- `uv run ruff check .` 仍然存在 `astrbot/core/prompt/context_catalog.py` 和 `astrbot/core/prompt/context_types.py` 的既有风格问题，这些不是本次 parser 改动引入

## 当前状态

当前 persona collect 链路已经能提供两层数据：

- `persona.prompt`
- `persona.segments`

这意味着下一步如果需要继续做：

- `persona.rendered`
- XML 预览
- segment 级渲染

就已经有稳定输入结构可以用了。
