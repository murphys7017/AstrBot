# Persona Context Collect

本文件记录本次 `persona context collect` 链路开发的实际改动、接入位置、设计约束和验证结果。

## 本次目标

- 只完成 `Collect`
- 当前仅收集 `persona` 相关 context
- 将收集结果汇总为 `ContextPack`
- 将结果写入日志供人工确认
- 不改变现有 `ProviderRequest` 渲染和执行行为
- 保留现有 `_ensure_persona_and_skills()` / `_apply_persona` 风格逻辑作为运行时真实行为

## 本次改动摘要

- 新增 prompt collect 协调层
- 将 `PersonaCollector` 接入主链路
- 在 `build_main_agent()` 中收集并记录 `ContextPack`
- 将 `ContextPack` 挂入 `event extra`
- 补齐 `webchat` special default persona 的收集行为
- 补充最小测试覆盖 collect 和主链路接入
- 顺手修复 `astr_main_agent.py` 中一个图片附件文本使用未定义变量的问题

## 新增目录

- `docs/Yakumo/dev/`

## 新增文件

### `astrbot/core/prompt/context_collect.py`

新增 prompt context collect 协调层。

包含：

- `PROMPT_CONTEXT_PACK_EXTRA_KEY = "prompt_context_pack"`
- `_default_collectors()`
- `_stringify_value_preview(value, *, max_len=400)`
- `collect_context_pack(...)`
- `log_context_pack(...)`

职责：

- 统一注册当前阶段启用的 collectors
- 统一执行 collect
- 将 `ContextSlot` 汇总进 `ContextPack`
- 将 `provider_request` 引用挂到 `ContextPack.provider_request_ref`
- 记录 `catalog_version`、`collectors`、`slot_count`
- 统一做 fail-open 异常处理
- 将结果写入日志

当前默认 collectors：

- `PersonaCollector`

### `tests/unit/test_prompt_context_collect.py`

新增最小测试文件。

包含测试：

- `test_collect_context_pack_collects_persona_prompt()`
- `test_collect_context_pack_collects_webchat_default_persona_prompt()`
- `test_build_main_agent_stores_prompt_context_pack_in_event_extra()`

覆盖点：

- 普通 persona prompt 收集
- `webchat` special default persona prompt 收集
- 主链路中 `ContextPack` 写入 `event extra`

## 修改文件

### `astrbot/core/astr_main_agent.py`

本次修改：

- 新增导入：
  - `PROMPT_CONTEXT_PACK_EXTRA_KEY`
  - `collect_context_pack`
  - `log_context_pack`
- 在 `build_main_agent()` 中接入 collect 链路
- 在 collect 前再次确保 `event.set_extra("provider_request", req)`
- 将收集结果写入 `event.set_extra("prompt_context_pack", pack)`
- 记录 pack 日志
- 修复图片附件文本中的未定义变量：
  - 原来使用 `image_ref`
  - 改为使用 `image_path`

本次新增的主链路步骤：

1. 构造或复用 `ProviderRequest`
2. 获取 `Conversation`
3. 将 `provider_request` 写入 `event extra`
4. 调用 `collect_context_pack(...)`
5. 将 `ContextPack` 写入 `event extra`
6. 调用 `log_context_pack(...)`
7. 后续继续走原有 `build_main_agent()` 逻辑

本次没有改动的行为：

- 不使用 `ContextPack` 反向渲染 `req.system_prompt`
- 不修改当前 tool / kb / sandbox / skills 注入方式
- 不改变 `OnLLMRequestEvent` 时机
- 不改变 AgentRunner reset 和 provider compile 行为

### `astrbot/core/prompt/collectors/persona_collector.py`

本次修改：

- 使用 `TYPE_CHECKING` 引入 `MainAgentBuildConfig`
- 将类型标注从 `List[...]` 改为 `list[...]`
- 补齐 `webchat` special default persona 的 `persona.prompt` 收集

新增行为：

- 当 `resolve_selected_persona()` 返回 `use_webchat_special_default=True` 时：
  - 生成一个 `ContextSlot(name="persona.prompt", ...)`
  - `value` 使用 `CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT`
  - `meta["use_webchat_special_default"] = True`

保持不变的行为：

- 仍然收集：
  - `persona.prompt`
  - `persona.begin_dialogs`
  - `persona.tools_whitelist`
  - `persona.skills_whitelist`
- 仍然从 `event.get_extra("provider_request")` 中读取 `conversation_persona_id`
- 仍然只负责 collect，不负责写回 `ProviderRequest`

### `astrbot/core/prompt/interfaces/context_collector_inferface.py`

本次修改：

- 使用 `TYPE_CHECKING` 避免运行时直接导入 `MainAgentBuildConfig`
- 将返回类型从 `List[ContextSlot]` 改为 `list[ContextSlot]`

目的：

- 降低 `prompt` 模块与 `astr_main_agent` 的运行时耦合
- 保持接口定义更轻

### `astrbot/core/prompt/__init__.py`

本次修改：

- 导出新增 collect 相关对象：
  - `PROMPT_CONTEXT_PACK_EXTRA_KEY`
  - `collect_context_pack`
  - `log_context_pack`
- 同时导出：
  - `ContextCollectorInterface`
  - `PersonaCollector`

目的：

- 让 `astrbot.core.prompt` 作为统一入口可以直接暴露当前阶段的 collect 能力

## 本次涉及的函数和常量

### 新增常量

- `astrbot/core/prompt/context_collect.py`
  - `PROMPT_CONTEXT_PACK_EXTRA_KEY`

用途：

- 作为 `event extra` 的 key，保存 `ContextPack`

### 新增函数

#### `collect_context_pack(...)`

位置：

- `astrbot/core/prompt/context_collect.py`

输入：

- `event`
- `plugin_context`
- `config`
- `provider_request`
- `collectors` 可选覆盖

输出：

- `ContextPack`

行为：

- 加载 catalog
- 获取当前 collectors
- 逐个执行 collect
- 将 slot 写入 pack
- 记录 pack 元数据：
  - `catalog_version`
  - `collectors`
  - `slot_count`

失败策略：

- 某个 collector 报错时记录 warning
- 跳过失败 collector
- 不终止主链路

#### `log_context_pack(pack, *, event=None)`

位置：

- `astrbot/core/prompt/context_collect.py`

行为：

- 先输出 pack 级别日志
- 再按 slot 输出逐条日志

当前日志字段：

- `umo`
- `catalog`
- `collectors`
- `slot_count`
- `slot.name`
- `slot.category`
- `slot.source`
- `slot.meta`
- `slot.value` 预览

#### `_default_collectors()`

位置：

- `astrbot/core/prompt/context_collect.py`

当前返回：

- `[PersonaCollector()]`

用途：

- 作为当前阶段默认启用的 collect 列表

#### `_stringify_value_preview(value, *, max_len=400)`

位置：

- `astrbot/core/prompt/context_collect.py`

用途：

- 生成日志里的 value 预览
- 避免长文本直接刷满日志

### 修改函数

#### `PersonaCollector.collect(...)`

本次新增逻辑：

- 支持 `webchat` special default persona prompt 收集

#### `build_main_agent(...)`

本次新增逻辑：

- 在 `ProviderRequest` 和 `Conversation` 就绪后触发 collect
- 将 `ContextPack` 写入 `event extra`
- 记录日志

## 本次没有新增的类

本次没有新增 class。

原因：

- 当前阶段目标是先把 collect 链路接通
- 用函数式协调层就足够
- 暂时不需要额外引入 `PromptEngine` / `ContextBuilder` 类

## 主链路接入位置

接入点位于 `build_main_agent()` 中，时机是：

- `req.conversation` 已就绪
- `req.contexts` 已就绪
- `event.set_extra("provider_request", req)` 已完成

这样做的原因：

- `PersonaCollector` 当前需要从 `provider_request.conversation.persona_id` 读取 `conversation_persona_id`
- 如果 collect 太早执行，就拿不到会话级 persona 信息
- 先放在这里接入，可以最大化复用现有逻辑，不改变主链路行为

## 设计思路

### 1. 先接 collect，不碰 render

当前阶段只做：

- 收集
- 汇总
- 观察日志

当前阶段不做：

- select
- render
- compile
- 替换旧 prompt 注入逻辑

原因：

- 先验证 collect 数据是否正确
- 先确认 slot 模型是否够用
- 避免一开始就同时改数据流和运行行为

### 2. fail-open

collect 失败不能影响主链路。

具体做法：

- 每个 collector 自己捕获内部异常
- `collect_context_pack()` 也再次包一层 collector 级别异常保护
- `build_main_agent()` 对整个 collect 调用也再包一层异常保护

目的：

- 将 collect 视为当前阶段的观察性能力
- 不让它影响真实回复流程

### 3. 不回写 `ProviderRequest`

当前 `ContextPack` 只做旁路数据，不改：

- `req.prompt`
- `req.system_prompt`
- `req.contexts`
- `req.func_tool`

原因：

- 当前还没有 selector / renderer
- 现在回写只会让新旧链路混杂得更重
- 当前最重要的是先确认“收到了什么”

### 4. 保留旧 persona 注入逻辑

当前系统里真实影响模型请求的仍然是原有 persona 注入逻辑。

原因：

- 这次开发目标不是替换旧逻辑
- 而是把新的 collect 链路先铺好
- 后续等 collect 数据确认没问题，再考虑 render persona prompt

### 5. 补齐 `webchat` special default

如果 collect 不处理这个分支，会出现：

- 真实请求有 persona prompt
- collect 日志却没有 `persona.prompt`

这会导致日志和真实行为不一致。

因此本次将这个特例一起迁到 collect 阶段。

## 当前日志形态

collect 成功后，当前会产生两类日志。

### pack 级日志

示例字段：

- `Prompt context pack collected`
- `umo`
- `catalog`
- `collectors`
- `slot_count`

### slot 级日志

示例字段：

- `Prompt context slot`
- `name=persona.prompt`
- `category=persona`
- `source=persona_mgr`
- `meta={...}`
- `value=...`

## 本次验证

执行过：

- `uv run pytest tests/unit/test_prompt_context_collect.py -q`
- `uv run ruff check astrbot/core/prompt/context_collect.py astrbot/core/prompt/collectors/persona_collector.py astrbot/core/prompt/interfaces/context_collector_inferface.py astrbot/core/astr_main_agent.py tests/unit/test_prompt_context_collect.py`
- `uv run ruff format astrbot/core/prompt/context_collect.py astrbot/core/prompt/collectors/persona_collector.py astrbot/core/prompt/interfaces/context_collector_inferface.py astrbot/core/astr_main_agent.py tests/unit/test_prompt_context_collect.py`

结果：

- 3 个新增测试通过
- ruff check 通过
- ruff format 已执行

## 顺手修复的问题

### `astrbot/core/astr_main_agent.py` 图片附件文本变量错误

问题：

- 构造图片附件文本时使用了未定义变量 `image_ref`

修复：

- 改为 `image_path`

影响：

- 这个问题不是本次 persona collect 设计的一部分
- 但在 lint 阶段被暴露出来，已一并修复

## 当前边界

本次只完成了 `persona collect`，尚未处理：

- `input.text`
- `input.images`
- `input.quoted_text`
- `input.files`
- `conversation.history`
- `knowledge.snippets`
- `capability.skills_prompt`
- `capability.tools_schema`
- `policy.safety_prompt`
- `session.datetime`

也尚未完成：

- selector
- renderer
- PromptIR
- provider compile 抽象

## 下一步建议

建议按下面顺序继续推进：

1. 接 `input` collect
2. 接 `history` collect
3. 接 `skills/tools` collect
4. 让日志覆盖全部 collect 结果
5. 在确认 collect 数据稳定后，再开始做 persona render
6. 最后再考虑 selector 和结构化中间表示

## 当前结论

本次开发完成的是：

- 将 `persona context` 从“只有旧逻辑直接注入 request”推进到“新 collect 链路也能稳定收集并记录”

本次没有完成的是：

- 用 `ContextPack` 驱动真实的 prompt 渲染

当前状态可以理解为：

- collect 链路已接通
- 日志观察点已建立
- 运行行为仍由旧链路控制
- 后续可以在这个基础上继续接 `input/history/skills/tools`
