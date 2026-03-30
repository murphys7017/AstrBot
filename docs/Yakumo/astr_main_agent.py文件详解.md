# astr_main_agent.py 文件详解

> 本文档详细解释 `astrbot/core/astr_main_agent.py` 文件中的所有类和函数，仅描述当前实现，不涉及未来计划。

---

## 目录

1. [文件概述](#文件概述)
2. [数据类](#数据类)
3. [辅助函数](#辅助函数)
4. [主函数](#主函数)
5. [完整流程图](#完整流程图)

---

## 文件概述

**文件路径**: `astrbot/core/astr_main_agent.py`

**核心职责**:
- 构建主 Agent 的 LLM 请求
- 收集和组装所有上下文信息（persona、skills、tools、知识库等）
- 创建 AgentRunner 并返回

---

## 数据类

### MainAgentBuildConfig

主 Agent 构建配置类，大部分配置来自 `cmd_config.json`。

```python
@dataclass(slots=True)
class MainAgentBuildConfig:
    """主 Agent 构建配置。"""
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `tool_call_timeout` | `int` | 工具调用超时时间（秒） |
| `tool_schema_mode` | `str` | 工具 Schema 模式，`"full"` 或 `"skills-like"` |
| `provider_wake_prefix` | `str` | 提供商唤醒前缀 |
| `streaming_response` | `bool` | 是否使用流式响应 |
| `sanitize_context_by_modalities` | `bool` | 是否根据提供商支持的模态清理上下文 |
| `kb_agentic_mode` | `bool` | 是否使用知识库 agentic 模式（注入查询工具而非直接注入结果） |
| `file_extract_enabled` | `bool` | 是否启用上传文件内容提取 |
| `file_extract_prov` | `str` | 文件提取提供商（如 `"moonshotai"`） |
| `file_extract_msh_api_key` | `str` | Moonshot AI 文件提取的 API Key |
| `context_limit_reached_strategy` | `str` | 上下文长度限制到达策略，`"truncate_by_turns"` 或 `"llm_compress"` |
| `llm_compress_instruction` | `str` | LLM 压缩策略中的压缩指令 |
| `llm_compress_keep_recent` | `int` | LLM 压缩策略中保留最近轮数 |
| `llm_compress_provider_id` | `str` | 用于上下文压缩的 LLM 提供商 ID |
| `max_context_length` | `int` | 最大上下文轮数，-1 表示无限制 |
| `dequeue_context_length` | `int` | 上下文长度限制到达时移除的最旧轮数 |
| `llm_safety_mode` | `bool` | 是否启用 LLM 安全模式（注入健康安全的系统 prompt） |
| `safety_mode_strategy` | `str` | 安全模式策略，当前仅支持 `"system_prompt"` |
| `computer_use_runtime` | `str` | 计算机使用运行时，`"none"` / `"local"` / `"sandbox"` |
| `sandbox_cfg` | `dict` | 沙箱配置 |
| `add_cron_tools` | `bool` | 是否添加定时任务管理工具 |
| `provider_settings` | `dict` | 提供商设置 |
| `subagent_orchestrator` | `dict` | 子代理编排配置 |
| `timezone` | `str | None` | 时区 |
| `max_quoted_fallback_images` | `int` | 从引用消息回退提取注入的最大图片数 |

---

### MainAgentBuildResult

主 Agent 构建结果类。

```python
@dataclass(slots=True)
class MainAgentBuildResult:
    """主 Agent 构建结果。"""
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_runner` | `AgentRunner` | Agent 运行器 |
| `provider_request` | `ProviderRequest` | 提供商请求 |
| `provider` | `Provider` | 选中的模型提供商 |
| `reset_coro` | `Coroutine | None` | reset 协程（如果 `apply_reset=False`） |

---

## 辅助函数

### _select_provider()

选择对话提供商。

```python
def _select_provider(
    event: AstrMessageEvent,
    plugin_context: Context
) -> Provider | None:
```

**参数**:
- `event`: 消息事件
- `plugin_context`: 插件上下文

**返回**:
- `Provider | None`: 选中的提供商，失败返回 None

**逻辑**:
1. 检查 `event.get_extra("selected_provider")` 是否指定了提供商
2. 如果指定了，通过 `plugin_context.get_provider_by_id()` 获取
3. 否则，通过 `plugin_context.get_using_provider(umo=...)` 获取当前使用的提供商

---

### _get_session_conv()

获取或创建会话。

```python
async def _get_session_conv(
    event: AstrMessageEvent,
    plugin_context: Context
) -> Conversation:
```

**参数**:
- `event`: 消息事件
- `plugin_context`: 插件上下文

**返回**:
- `Conversation`: 会话对象

**逻辑**:
1. 通过 `plugin_context.conversation_manager.get_curr_conversation_id(umo)` 获取当前会话 ID
2. 如果没有，创建新会话
3. 获取会话对象
4. 如果会话不存在，再创建一次并返回

---

### _apply_kb()

应用知识库检索结果。

```python
async def _apply_kb(
    event: AstrMessageEvent,
    req: ProviderRequest,
    plugin_context: Context,
    config: MainAgentBuildConfig,
) -> None:
```

**参数**:
- `event`: 消息事件
- `req`: 提供商请求（会被修改）
- `plugin_context`: 插件上下文
- `config`: 构建配置

**逻辑**:
- **非 agentic 模式**（`kb_agentic_mode=False`）：
  1. 调用 `retrieve_knowledge_base()` 检索知识库
  2. 直接追加到 `req.system_prompt`
- **agentic 模式**（`kb_agentic_mode=True`）：
  1. 注入 `KNOWLEDGE_BASE_QUERY_TOOL` 工具到 `req.func_tool`
  2. 让 Agent 自己决定何时查询知识库

**修改**:
- `req.system_prompt`（非 agentic 模式）
- `req.func_tool`（agentic 模式）

---

### _apply_file_extract()

应用文件内容提取（上传的文件）。

```python
async def _apply_file_extract(
    event: AstrMessageEvent,
    req: ProviderRequest,
    config: MainAgentBuildConfig,
) -> None:
```

**参数**:
- `event`: 消息事件
- `req`: 提供商请求（会被修改）
- `config`: 构建配置

**逻辑**:
1. 从 `event.message_obj.message` 提取 `File` 组件（包括引用消息中的文件）
2. 如果 `file_extract_prov == "moonshotai"`：
   - 调用 `extract_file_moonshotai()` 提取文件内容
   - 将结果追加到 `req.contexts` 作为 system message

**修改**:
- `req.contexts`

---

### _apply_prompt_prefix()

应用 prompt 前缀配置。

```python
def _apply_prompt_prefix(req: ProviderRequest, cfg: dict) -> None:
```

**参数**:
- `req`: 提供商请求（会被修改）
- `cfg`: 配置字典

**逻辑**:
1. 读取 `cfg.get("prompt_prefix")`
2. 如果包含 `{{prompt}}`，替换模板
3. 否则，直接前缀追加

**修改**:
- `req.prompt`

---

### _apply_local_env_tools()

应用本地环境工具（非沙箱模式）。

```python
def _apply_local_env_tools(req: ProviderRequest) -> None:
```

**参数**:
- `req`: 提供商请求（会被修改）

**逻辑**:
1. 添加 `LOCAL_EXECUTE_SHELL_TOOL` 工具
2. 添加 `LOCAL_PYTHON_TOOL` 工具
3. 追加 `_build_local_mode_prompt()` 到 `req.system_prompt`

**修改**:
- `req.func_tool`
- `req.system_prompt`

---

### _build_local_mode_prompt()

构建本地模式 prompt。

```python
def _build_local_mode_prompt() -> str:
```

**返回**:
- `str`: 本地模式 prompt 字符串

**逻辑**:
1. 获取当前操作系统类型
2. 根据 Windows / Unix 构建不同的 shell 提示
3. 返回完整的 prompt

---

### _ensure_persona_and_skills()

确保人格和技能被应用到请求的系统 prompt 或用户 prompt。

**这是最核心的函数之一**。

```python
async def _ensure_persona_and_skills(
    req: ProviderRequest,
    cfg: dict,
    plugin_context: Context,
    event: AstrMessageEvent,
) -> None:
```

**参数**:
- `req`: 提供商请求（会被修改）
- `cfg`: 配置字典
- `plugin_context`: 插件上下文
- `event`: 消息事件

**逻辑**:

#### 1. 解析人格
```python
(persona_id, persona, _, use_webchat_special_default) =
    await plugin_context.persona_manager.resolve_selected_persona(...)
```

#### 2. 应用人格
- 如果 `persona["prompt"]` 存在：
  - 追加到 `req.system_prompt`（格式：`\n# Persona Instructions\n\n{prompt}\n`）
- 如果 `persona["_begin_dialogs_processed"]` 存在：
  - 插入到 `req.contexts[:0]`（最前面）
- 如果是 WebChat 特殊默认人格：
  - 追加 `CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT`

#### 3. 应用 Skills
```python
skill_manager = SkillManager()
skills = skill_manager.list_skills(active_only=True, runtime=runtime)
```

- 如果 `persona["skills"]` 不为 None：
  - 为空则清空 skills
  - 否则按白名单过滤
- 如果 skills 非空：
  - 追加 `build_skills_prompt(skills)` 到 `req.system_prompt`
  - 如果 `runtime == "none"`，追加提示信息

#### 4. 应用 Tools
```python
tmgr = plugin_context.get_llm_tool_manager()
```

- 如果 `persona["tools"]` 为 None 或没有 persona：
  - 获取 `tmgr.get_full_tool_set()`，过滤非活跃工具
- 否则：
  - 按 persona 的 tools 白名单构建 `persona_toolset`
- 合并到 `req.func_tool`

#### 5. 应用 SubAgent
```python
orch_cfg = plugin_context.get_config().get("subagent_orchestrator", {})
so = plugin_context.subagent_orchestrator
```

- 如果启用：
  - 收集分配的工具（根据子代理配置）
  - 添加 `so.handoffs` 中的 handoff 工具到 `req.func_tool`
  - 如果 `remove_dup=True`，移除重复工具
  - 追加 `router_system_prompt` 到 `req.system_prompt`

**修改**:
- `req.system_prompt`
- `req.contexts`
- `req.func_tool`

---

### _request_img_caption()

请求图片描述（使用 LLM）。

```python
async def _request_img_caption(
    provider_id: str,
    cfg: dict,
    image_urls: list[str],
    plugin_context: Context,
) -> str:
```

**参数**:
- `provider_id`: 图片描述提供商 ID
- `cfg`: 配置字典
- `image_urls`: 图片 URL 列表
- `plugin_context`: 插件上下文

**返回**:
- `str`: 图片描述文本

**逻辑**:
1. 获取提供商
2. 调用 `prov.text_chat()`，prompt 为 `cfg.get("image_caption_prompt", "Please describe the image.")`
3. 返回 `llm_resp.completion_text`

---

### _ensure_img_caption()

确保图片描述被应用。

```python
async def _ensure_img_caption(
    req: ProviderRequest,
    cfg: dict,
    plugin_context: Context,
    image_caption_provider: str,
) -> None:
```

**参数**:
- `req`: 提供商请求（会被修改）
- `cfg`: 配置字典
- `plugin_context`: 插件上下文
- `image_caption_provider`: 图片描述提供商 ID

**逻辑**:
1. 调用 `_request_img_caption()` 获取描述
2. 将描述包装在 `<image_caption>...</image_caption>` 中追加到 `req.extra_user_content_parts`
3. 清空 `req.image_urls`

**修改**:
- `req.extra_user_content_parts`
- `req.image_urls`

---

### _append_quoted_image_attachment()

追加引用消息中的图片附件说明。

```python
def _append_quoted_image_attachment(req: ProviderRequest, image_path: str) -> None:
```

**参数**:
- `req`: 提供商请求（会被修改）
- `image_path`: 图片路径

**逻辑**:
- 追加 `[Image Attachment in quoted message: path {image_path}]` 到 `req.extra_user_content_parts`

**修改**:
- `req.extra_user_content_parts`

---

### _resolve_image_component_ref()

解析图片组件引用。

```python
async def _resolve_image_component_ref(comp: Image) -> str:
```

**参数**:
- `comp`: 图片组件

**返回**:
- `str`: 图片引用路径/URL

**逻辑**:
1. 尝试 `comp.url`
2. 尝试 `comp.file`
3. 尝试 `comp.path`
4. 最后调用 `comp.convert_to_file_path()`

---

### _get_quoted_message_parser_settings()

获取引用消息解析器设置。

```python
def _get_quoted_message_parser_settings(
    provider_settings: dict[str, object] | None,
) -> QuotedMessageParserSettings:
```

**参数**:
- `provider_settings`: 提供商设置

**返回**:
- `QuotedMessageParserSettings`: 解析器设置

**逻辑**:
- 从 `provider_settings.get("quoted_message_parser")` 读取覆盖配置
- 返回 `DEFAULT_QUOTED_MESSAGE_SETTINGS.with_overrides(overrides)`

---

### _process_quote_message()

处理引用消息。

```python
async def _process_quote_message(
    event: AstrMessageEvent,
    req: ProviderRequest,
    img_cap_prov_id: str,
    plugin_context: Context,
    quoted_message_settings: QuotedMessageParserSettings = DEFAULT_QUOTED_MESSAGE_SETTINGS,
) -> None:
```

**参数**:
- `event`: 消息事件
- `req`: 提供商请求（会被修改）
- `img_cap_prov_id`: 图片描述提供商 ID
- `plugin_context`: 插件上下文
- `quoted_message_settings`: 引用消息解析器设置

**逻辑**:
1. 从 `event.message_obj.message` 提取 `Reply` 组件
2. 提取引用消息的文本和发送者昵称
3. 如果引用消息有 `Image` 组件：
   - 尝试调用 LLM 生成图片描述
4. 组装完整引用内容，包装在 `<Quoted Message>...</Quoted Message>` 中
5. 追加到 `req.extra_user_content_parts`

**修改**:
- `req.extra_user_content_parts`

---

### _append_system_reminders()

追加系统提醒（用户 ID、群组名、时间等）。

```python
def _append_system_reminders(
    event: AstrMessageEvent,
    req: ProviderRequest,
    cfg: dict,
    timezone: str | None,
) -> None:
```

**参数**:
- `event`: 消息事件
- `req`: 提供商请求（会被修改）
- `cfg`: 配置字典
- `timezone`: 时区

**逻辑**:
- 如果 `cfg.get("identifier")`：
  - 追加 `User ID: {user_id}, Nickname: {user_nickname}`
- 如果 `cfg.get("group_name_display")` 且有群组：
  - 追加 `Group name: {group_name}`
- 如果 `cfg.get("datetime_system_prompt")`：
  - 追加 `Current datetime: {current_time}`
- 组装完整内容，包装在 `<system_reminder>...</system_reminder>` 中
- 追加到 `req.extra_user_content_parts`

**修改**:
- `req.extra_user_content_parts`

---

### _decorate_llm_request()

装饰 LLM 请求（调用上述多个函数）。

```python
async def _decorate_llm_request(
    event: AstrMessageEvent,
    req: ProviderRequest,
    plugin_context: Context,
    config: MainAgentBuildConfig,
) -> None:
```

**参数**:
- `event`: 消息事件
- `req`: 提供商请求（会被修改）
- `plugin_context`: 插件上下文
- `config`: 构建配置

**逻辑**:
1. 调用 `_apply_prompt_prefix(req, cfg)`
2. 如果 `req.conversation` 存在：
   - 调用 `_ensure_persona_and_skills(req, cfg, plugin_context, event)`
   - 如果配置了图片描述提供商且有图片：
     - 调用 `_ensure_img_caption(...)`
3. 调用 `_process_quote_message(...)`
4. 调用 `_append_system_reminders(...)`

**修改**:
- `req`（通过上述函数）

---

### _modalities_fix()

根据提供商支持的模态修复输入。

```python
def _modalities_fix(provider: Provider, req: ProviderRequest) -> None:
```

**参数**:
- `provider`: 提供商
- `req`: 提供商请求（会被修改）

**逻辑**:
- **图片处理**：
  - 如果 `req.image_urls` 非空且提供商不支持 `"image"` 模态：
    - 将图片转为 `[图片]` 占位符，追加到 `req.prompt`
    - 清空 `req.image_urls`
- **工具处理**：
  - 如果 `req.func_tool` 非空且提供商不支持 `"tool_use"` 模态：
    - 清空 `req.func_tool`

**修改**:
- `req.prompt`
- `req.image_urls`
- `req.func_tool`

---

### _sanitize_context_by_modalities()

根据提供商支持的模态清理上下文历史。

```python
def _sanitize_context_by_modalities(
    config: MainAgentBuildConfig,
    provider: Provider,
    req: ProviderRequest,
) -> None:
```

**参数**:
- `config`: 构建配置
- `provider`: 提供商
- `req`: 提供商请求（会被修改）

**逻辑**:
- 如果 `config.sanitize_context_by_modalities` 为 False，跳过
- 如果不支持 `"tool_use"`：
  - 移除 `role="tool"` 的消息
  - 移除 `role="assistant"` 消息中的 `tool_calls` 和 `tool_call_id`
- 如果不支持 `"image"`：
  - 移除消息内容中的 `type="image_url"` / `type="image"` 部分
- 更新 `req.contexts`

**修改**:
- `req.contexts`

---

### _plugin_tool_fix()

根据事件中的插件设置过滤请求中的工具列表。

```python
def _plugin_tool_fix(event: AstrMessageEvent, req: ProviderRequest) -> None:
```

**参数**:
- `event`: 消息事件
- `req`: 提供商请求（会被修改）

**逻辑**:
- 如果 `event.plugins_name` 不为 None 且 `req.func_tool` 存在：
  - 遍历工具：
    - 如果是 `MCPTool`：保留
    - 如果没有 `handler_module_path`：保留
    - 如果插件在 `event.plugins_name` 中或是保留插件：保留
    - 否则：移除
- 更新 `req.func_tool`

**修改**:
- `req.func_tool`

---

### _handle_webchat()

处理 WebChat（生成对话标题）。

```python
async def _handle_webchat(
    event: AstrMessageEvent,
    req: ProviderRequest,
    prov: Provider,
) -> None:
```

**参数**:
- `event`: 消息事件
- `req`: 提供商请求
- `prov`: 提供商

**逻辑**（后台任务，不阻塞主流程）:
1. 从 `event.session_id` 提取 WebChat 会话 ID
2. 如果会话没有 `display_name`：
   - 调用 LLM 生成对话标题（10 字以内）
   - 更新会话的 `display_name`

---

### _apply_llm_safety_mode()

应用 LLM 安全模式。

```python
def _apply_llm_safety_mode(config: MainAgentBuildConfig, req: ProviderRequest) -> None:
```

**参数**:
- `config`: 构建配置
- `req`: 提供商请求（会被修改）

**逻辑**:
- 如果 `config.safety_mode_strategy == "system_prompt"`：
  - 前置 `LLM_SAFETY_MODE_SYSTEM_PROMPT` 到 `req.system_prompt`

**修改**:
- `req.system_prompt`

---

### _apply_sandbox_tools()

应用沙箱工具。

```python
def _apply_sandbox_tools(
    config: MainAgentBuildConfig,
    req: ProviderRequest,
    session_id: str,
) -> None:
```

**参数**:
- `config`: 构建配置
- `req`: 提供商请求（会被修改）
- `session_id`: 会话 ID

**逻辑**:
1. 添加工具：
   - `EXECUTE_SHELL_TOOL`
   - `PYTHON_TOOL`
   - `FILE_UPLOAD_TOOL`
   - `FILE_DOWNLOAD_TOOL`
2. 如果 `booter == "shipyard_neo"`：
   - 添加 Neo 特定路径规则 prompt
   - 添加 Neo Skill 生命周期工作流 prompt
   - 检查沙箱能力，决定是否添加浏览器工具
   - 添加 Neo 特定工具（10+ 个）
3. 追加 `SANDBOX_MODE_PROMPT`

**修改**:
- `req.func_tool`
- `req.system_prompt`

---

### _proactive_cron_job_tools()

添加主动定时任务工具。

```python
def _proactive_cron_job_tools(req: ProviderRequest) -> None:
```

**参数**:
- `req`: 提供商请求（会被修改）

**逻辑**:
- 添加工具：
  - `CREATE_CRON_JOB_TOOL`
  - `DELETE_CRON_JOB_TOOL`
  - `LIST_CRON_JOBS_TOOL`

**修改**:
- `req.func_tool`

---

### _get_compress_provider()

获取上下文压缩提供商。

```python
def _get_compress_provider(
    config: MainAgentBuildConfig,
    plugin_context: Context,
) -> Provider | None:
```

**参数**:
- `config`: 构建配置
- `plugin_context`: 插件上下文

**返回**:
- `Provider | None`: 压缩提供商

**逻辑**:
- 如果没有配置 `llm_compress_provider_id`，返回 None
- 如果策略不是 `"llm_compress"`，返回 None
- 否则返回 `plugin_context.get_provider_by_id(...)`

---

### _get_fallback_chat_providers()

获取回退聊天提供商列表。

```python
def _get_fallback_chat_providers(
    provider: Provider,
    plugin_context: Context,
    provider_settings: dict,
) -> list[Provider]:
```

**参数**:
- `provider`: 当前提供商
- `plugin_context`: 插件上下文
- `provider_settings`: 提供商设置

**返回**:
- `list[Provider]`: 回退提供商列表

**逻辑**:
- 读取 `provider_settings.get("fallback_chat_models", [])`
- 遍历 ID，获取提供商，去重，验证类型
- 返回列表

---

## 主函数

### build_main_agent()

构建主对话代理（Main Agent），并且自动 reset。

**这是整个文件的核心入口函数**。

```python
async def build_main_agent(
    *,
    event: AstrMessageEvent,
    plugin_context: Context,
    config: MainAgentBuildConfig,
    provider: Provider | None = None,
    req: ProviderRequest | None = None,
    apply_reset: bool = True,
) -> MainAgentBuildResult | None:
```

**参数**:
- `event`: 消息事件
- `plugin_context`: 插件上下文
- `config`: 构建配置
- `provider`: 可选，已选提供商
- `req`: 可选，已有的 ProviderRequest
- `apply_reset`: 是否立即执行 reset

**返回**:
- `MainAgentBuildResult | None`: 构建结果，失败返回 None

---

#### 完整流程

| 步骤 | 操作 | 说明 |
|------|------|------|
| **1** | 选择 Provider | 调用 `_select_provider()`，如果未提供 |
| **2** | 初始化 ProviderRequest | 如果 `req` 为 None：<br>a. 检查 `event.get_extra("provider_request")` 复用<br>b. 否则新建 `ProviderRequest` |
| **2a** | 提取输入文本 | `req.prompt = event.message_str`（去掉唤醒前缀） |
| **2b** | 提取图片 | 从 `event.message_obj.message` 提取 `Image` 组件，追加到 `req.image_urls` |
| **2c** | 提取文件 | 从 `event.message_obj.message` 提取 `File` 组件，追加说明 |
| **2d** | 处理引用消息 | 提取 `Reply` 组件，处理其中的图片和文件 |
| **2e** | 获取会话 | 调用 `_get_session_conv()`，加载 `req.contexts` |
| **3** | 规范化图片 URL | 去重 `req.image_urls` |
| **4** | 应用文件提取 | 如果启用，调用 `_apply_file_extract()` |
| **5** | 装饰 LLM 请求 | 调用 `_decorate_llm_request()`<br>（内部调用：prompt_prefix、persona/skills、引用消息、系统提醒） |
| **6** | 应用知识库 | 调用 `_apply_kb()` |
| **7** | 设置会话 ID | `req.session_id = event.unified_msg_origin` |
| **8** | Modalities 修复 | 调用 `_modalities_fix()` |
| **9** | 插件工具修复 | 调用 `_plugin_tool_fix()` |
| **10** | 按模态清理上下文 | 调用 `_sanitize_context_by_modalities()` |
| **11** | 应用安全模式 | 调用 `_apply_llm_safety_mode()` |
| **12** | 应用沙箱/本地工具 | `_apply_sandbox_tools()` 或 `_apply_local_env_tools()` |
| **13** | 添加 Cron 工具 | 如果启用，调用 `_proactive_cron_job_tools()` |
| **14** | 添加主动消息工具 | 如果平台支持，添加 `SEND_MESSAGE_TO_USER_TOOL` |
| **15** | 设置 max_context_tokens | 如果未设置，从 `LLM_METADATAS` 读取 |
| **16** | 处理 WebChat 标题 | 后台任务 `asyncio.create_task(_handle_webchat())` |
| **17** | 添加 Tool Call Prompt | 如果有工具，追加 `TOOL_CALL_PROMPT` |
| **18** | 添加 Live Mode Prompt | 如果是 Live Mode，追加 `LIVE_MODE_SYSTEM_PROMPT` |
| **19** | 创建 AgentRunner | `agent_runner = AgentRunner()` |
| **20** | 调用 reset | `reset_coro = agent_runner.reset(...)` |
| **21** | 执行 reset | 如果 `apply_reset=True`，`await reset_coro` |
| **22** | 返回结果 | `MainAgentBuildResult(...)` |

---

## 完整流程图

```
build_main_agent()
│
├─ 1. 选择 Provider
│   └─ _select_provider()
│
├─ 2. 初始化 ProviderRequest
│   ├─ 复用 event 中的 provider_request，或新建
│   ├─ req.prompt = event.message_str
│   ├─ req.image_urls = 提取 Image 组件
│   ├─ req.extra_user_content_parts = 添加 File/Reply 说明
│   └─ req.contexts = json.loads(conversation.history)
│
├─ 3. 规范化图片 URL（去重）
│
├─ 4. 应用文件提取
│   └─ _apply_file_extract()
│
├─ 5. 装饰 LLM 请求
│   └─ _decorate_llm_request()
│       ├─ _apply_prompt_prefix()
│       ├─ _ensure_persona_and_skills()  ← 核心！
│       │   ├─ persona_manager.resolve_selected_persona()
│       │   ├─ req.system_prompt += persona["prompt"]
│       │   ├─ req.contexts[:0] = persona["_begin_dialogs_processed"]
│       │   ├─ SkillManager().list_skills()
│       │   ├─ req.system_prompt += build_skills_prompt(skills)
│       │   ├─ plugin_context.get_llm_tool_manager()
│       │   ├─ req.func_tool = persona_toolset
│       │   └─ plugin_context.subagent_orchestrator
│       │       └─ req.func_tool.add_tool(tool) for tool in so.handoffs
│       ├─ _process_quote_message()
│       └─ _append_system_reminders()
│
├─ 6. 应用知识库
│   └─ _apply_kb()
│       ├─ 非 agentic 模式: req.system_prompt += KB 结果
│       └─ agentic 模式: req.func_tool.add_tool(KNOWLEDGE_BASE_QUERY_TOOL)
│
├─ 7. 设置 req.session_id
│
├─ 8. Modalities 修复
│   └─ _modalities_fix()
│       ├─ 不支持 image: 转为 [图片] 占位符
│       └─ 不支持 tool_use: 清空 req.func_tool
│
├─ 9. 插件工具修复
│   └─ _plugin_tool_fix()
│       └─ 根据 event.plugins_name 过滤工具
│
├─ 10. 按模态清理上下文
│   └─ _sanitize_context_by_modalities()
│       ├─ 移除不支持的 tool 消息
│       └─ 移除不支持的 image 部分
│
├─ 11. 应用安全模式
│   └─ _apply_llm_safety_mode()
│       └─ req.system_prompt = LLM_SAFETY_MODE_SYSTEM_PROMPT + "\n\n" + req.system_prompt
│
├─ 12. 应用沙箱/本地工具
│   ├─ _apply_sandbox_tools()  (sandbox 模式)
│   │   └─ 添加 EXECUTE_SHELL_TOOL / PYTHON_TOOL / 等 10+ 个工具
│   └─ _apply_local_env_tools()  (local 模式)
│       └─ 添加 LOCAL_EXECUTE_SHELL_TOOL / LOCAL_PYTHON_TOOL
│
├─ 13. 添加 Cron 工具
│   └─ _proactive_cron_job_tools()
│
├─ 14. 添加主动消息工具
│
├─ 15. 设置 max_context_tokens
│
├─ 16. 处理 WebChat 标题（后台）
│   └─ asyncio.create_task(_handle_webchat())
│
├─ 17. 添加 Tool Call Prompt
│   └─ req.system_prompt += "\n{TOOL_CALL_PROMPT}\n"
│
├─ 18. 添加 Live Mode Prompt
│
├─ 19. 创建 AgentRunner
│   └─ agent_runner = AgentRunner()
│
├─ 20. 调用 reset
│   └─ reset_coro = agent_runner.reset(...)
│
├─ 21. 执行 reset (如果 apply_reset=True)
│   └─ await reset_coro
│
└─ 22. 返回 MainAgentBuildResult
    └─ (agent_runner, provider_request, provider, reset_coro)
```

---

## ProviderRequest 字段修改汇总

| 字段 | 被哪些函数修改 |
|------|---------------|
| `req.prompt` | `_apply_prompt_prefix()` / `_modalities_fix()` |
| `req.system_prompt` | `_ensure_persona_and_skills()` / `_apply_kb()` / `_apply_llm_safety_mode()` / `_apply_sandbox_tools()` / `_apply_local_env_tools()` / 添加 Tool Call Prompt / 添加 Live Mode Prompt |
| `req.contexts` | `_ensure_persona_and_skills()` / `_apply_file_extract()` / `_sanitize_context_by_modalities()` |
| `req.image_urls` | 初始化 / `_ensure_img_caption()` / `_modalities_fix()` |
| `req.extra_user_content_parts` | 初始化 / `_ensure_img_caption()` / `_append_quoted_image_attachment()` / `_process_quote_message()` / `_append_system_reminders()` |
| `req.func_tool` | `_ensure_persona_and_skills()` / `_apply_kb()` / `_apply_sandbox_tools()` / `_apply_local_env_tools()` / `_proactive_cron_job_tools()` / `_modalities_fix()` / `_plugin_tool_fix()` |
| `req.session_id` | 初始化 |
| `req.conversation` | 初始化 |
| `req.model` | 初始化 |

---

*文档版本: 1.0*
*最后更新: 2026-03-30*
