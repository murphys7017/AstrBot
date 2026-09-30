# 接口差异与文件映射

本表对照 [总纲](./README.md) 中固定的本地和官方基线。只做静态源码盘点，不表示目标接口已经实现或运行验证。

## 1. 盘点口径

通过 Python AST 读取 `routes/*.py` 的 `self.routes`、显式 `add_url_rule()` 和 WebSocket 注册，不导入或启动应用。

- `self.routes` 声明共 222 个 HTTP 方法/路径组合。
- 插件内容/SDK 3 个、日志/Trace 4 个、平台 4 个、服务器插件分发 2 个，共增加 13 个显式组合。
- 合计 235 个声明的 HTTP 方法/路径组合，以及 3 个 WebSocket 入口。
- 不计自动生成的 HEAD/OPTIONS、20 个前端 HTML 入口、框架静态文件路径或插件运行时注册的具体 API。
- 这些数值不是运行后的完整路由总数；P0 仍需对实际注册表及调用方复核。声明清单也不证明相应功能可用。

下表列出全部现有功能模块，但接口列只展示代表入口，不是逐接口迁移签收表。实施时每个功能域补齐方法、路径、输入、状态码、响应头、身份和副作用后才能签收。

## 2. 功能域与目标文件

当前模块均位于 `astrbot/dashboard/routes/`；目标文件采用官方 `astrbot/dashboard/api/`、`services/` 的命名。目标列是规划，当前工作区尚未生成这些文件。

| 当前模块 / HTTP 声明数 | 代表入口 | 官方目标 API / Service | 本地迁移重点 |
| --- | --- | --- | --- |
| `auth.py` / 6 | `/api/auth/login`、`setup`、`account/edit` | `auth.py` / `auth_service.py` | 旧密码升级、登录 Cookie、初始化与退出；不能顺带启用未验收的新认证流程 |
| `api_key.py` / 4 | `/api/apikey/list`、`create`、`revoke` | `api_keys.py` / `api_key_service.py` | Key 格式、哈希、吊销、scope、已有数据兼容 |
| `stat.py` / 12 | `/api/stat/get`、`personal-runtime`、`restart-core` | `stats.py` / `stat_service.py` | 官方没有同名 Personal Runtime 状态路由，需保留；复核时间序列化和桌面重启限制 |
| `config.py` / 31 | `/api/config/abconf/update`、`astrbot/update`、`provider/list` | `config_profiles.py`、`bots.py`、`providers.py`、部分 `plugins.py` / `config_service.py` | 官方按 Profile、资源和插件配置拆分；迁移本地所有者语义，而非直接换官方实现 |
| `persona.py` / 13 | `/api/persona/create`、`update`、`folder/tree` | `personas.py` / `persona_service.py` | 显式空 tools/skills、目录与排序；保持缺省值/空列表/null 的区别 |
| `conversation.py` / 6 | `/api/conversation/list`、`detail`、`export` | `conversations.py` / `conversation_service.py` | 查询隔离、历史结构与已有过滤语义，不引入 Ledger 到可见历史 |
| `session_management.py` / 12 | `/api/session/list-rule`、`batch-update-provider` | `sessions.py` / `session_management_service.py` | 会话路由、批量写入、Profile 与权限，不旁路 Manager |
| `cron.py` / 5 | `GET/POST /api/cron/jobs`、`PATCH/DELETE /api/cron/jobs/<job_id>` | `cron.py` / `cron_service.py` | 更新与手动运行的原语义；框架路径参数转换不能漏 PATCH/DELETE |
| `subagent.py` / 3 | `GET/POST /api/subagent/config` | `subagents.py` / `subagent_service.py` | 保留 `conf_id` 选择、对应 Profile reload 和默认 Profile 隔离 |
| `knowledge_base.py` / 16 | `/api/kb/list`、`document/upload`、`retrieve` | `knowledge_bases.py` / `knowledge_base_service.py` | 名称别名、分页、省略/null 更新、上传与导入进度；不改底层检索引擎 |
| `plugin.py` / 24 | `/api/plugin/detail`、`capabilities`、`page/entry`、`page/content/...` | `plugins.py` / `plugin_service.py`、`plugin_page_service.py` | 管理与 Pages 拆分；本地 capabilities 入口须保留；插件选中/owner 行为不能被官方服务覆盖 |
| `command.py` / 5 | `/api/commands`、`commands/toggle` | `extensions.py` / `command_service.py` | 保留命令冲突、权限、重命名与配置唤醒前缀 |
| `tools.py` / 9 | `/api/tools/list`、`tools/mcp/servers`、`tools/permission` | `tools.py` / `tools_service.py` | 工具准入、MCP 生命周期和已有安全修复；不重建 PluginExecutionRuntime |
| `skills.py` / 18 | `/api/skills`、`skills/file`、`skills/neo/promote` | `skills.py` / `skills_service.py` | 插件来源 Skill 的修改限制、档案上传校验；Neo 管理逐项映射，不默认官方已经覆盖 |
| `chatui_project.py` / 8 | `/api/chatui_project/create`、`add_session` | `chat_projects.py` / `chatui_project_service.py` | workspace 路径边界与会话归属，旧 GET 删除暂时保留契约 |
| `chat.py` / 17 | `/api/chat/send`、`stop`、`thread/send`、`post_file` | `chat.py`、`files.py` / `chat_service.py` | 本地消息分段、附件、用户隔离、编辑/重生成；与现有 Personal/Core 链路衔接 |
| `open_api.py` / 7 + 1 WS | `/api/v1/chat`、`configs`、`file`、`im/message`、`chat/ws` | `open_api.py` / `open_api_service.py` | 外部 API 与新 Dashboard v1 共用前缀；输入别名、身份和 scope 不可机械替换 |
| `live_chat.py` / 0 + 2 WS | `/api/live_chat/ws`、`/api/unified_chat/ws` | `live_chat.py` / `live_chat_service.py` | 音频、打断、订阅清理、发送锁；保留旧 WS 地址和认证 |
| `log.py` / 4 | `/api/live-log`、`log-history`、`trace/settings` | `logs.py` / `log_service.py` | 日志增量交付与 Trace 设置；保留原始流格式 |
| `file.py` / 1 | `/api/file/<file_token>` | `files.py` / `file_service.py` | 单用途文件令牌、过期、路径与 MIME；文件下载不是通用免鉴权 API |
| `backup.py` / 13 | `/api/backup/upload/chunk`、`import`、`download` | `backups.py` / `backup_service.py` | 分块状态、大小校验、取消与清理；导入验收只用隔离数据 |
| `update.py` / 7 | `/api/update/do`、`dashboard`、`migration` | `updates.py` / `update_service.py` | 分阶段下载/应用、错误脱敏、桌面托管保护；不能在验收中实际升级生产副本 |
| `t2i.py` / 8 | `/api/t2i/templates`、`templates/<name>` | `t2i.py` / `t2i_service.py` | 模板 CRUD、活动模板与所有配置/调度器的同步 |
| `platform.py` / 4 | `GET/POST /api/platform/webhook/<webhook_uuid>`、`registration/<platform_type>` | `platform.py` / `platform_service.py` | 官方新增 v1 webhook 地址；旧地址必须显式保留，原始响应不包 JSON |
| `static_file.py` / HTML 入口 | `/`、`/chat`、`/settings` 等 | `static_files.py` / `static_file_service.py` | 保留自定义前端路由刷新与资源路径；SPA fallback 不得吞掉 API 的 404 |
| `server.py` / 2，位于上级目录 | `GET/POST /api/plug/<path:subpath>` | `plugins.py` + `asgi_runtime.py` | 官方 v1 插件 API 与旧动态注册分发桥接；保持现有方法集合，扩展方法另行评估 |

## 3. 不能机械合并的差异

### D1：v1 鉴权和外部身份

本地 `server.py.auth_middleware()` 对所有 `/api/v1*` HTTP 请求执行 API Key 验证，WebSocket 由对应 Handler 单独验证。官方 `server.py` 把 v1 HTTP 鉴权交给 `api/auth.py` 的依赖，其通用 scope 依赖可接受 Dashboard JWT 或 API Key。

迁移方法：按实际路由区分旧外部接口、新 Dashboard 接口、公开认证接口、资源令牌入口与 WS；为每类指定合法凭据、scope 和访问主体。不能照搬“v1 中间件返回 None”却遗漏依赖，也不能不经审核让普通 Key 获得管理权限。前缀判断须按路径边界处理，不能把 `/api/v10` 当作 `/api/v1`。

本地 `/api/stat/start-time` 等入口已有公开访问约定，不能把“受保护接口拒绝匿名访问”扩展为“所有 API 拒绝匿名访问”。当前 logout 只清除 Dashboard Cookie，不吊销已签发 JWT；迁移保留这一行为，若需要服务端 JWT 吊销，另行评估，不把它写成已有契约。

官方外部聊天还引入了 Key 身份与 `chat_admin` 对指定用户名的限制。本地现在接受请求 `username`，并检查 session 的用户归属。此处涉及现有客户端的授权行为，不在框架替换中偷偷改变：P0 记录调用方需求，涉及权限收紧的变更单独说明和验收。

### D2：资源、Profile 和本地状态

`config.py.global_resource_config` 是 Provider/Adapter 的全局持久化所有者；Profile 保存准入 binding。配置变更还触发对应 Memory cache/service 失效；SubAgent 的 `conf_id` 决定修改和 reload 的目标。

迁移方法：把这些行为搬入官方对应服务，继续调用现有 Core 的 Manager。保留 `/api/stat/personal-runtime` 和 `/api/plugin/capabilities` 两个本地入口，不能只以官方路由集合为完成标准。

### D3：插件 API 和旧 Quart 上下文

本地 `Context.register_web_api()` 保存注册项及 owner，卸载时按 owner 删除；HTTP 分发实时读取注册表，用 Werkzeug 匹配动态参数。官方兼容 app 及响应转换只是参考。

迁移方法：复用现有注册表和清理机制，避免把插件 API 固定注册到 FastAPI 后留下旧 Handler。核对动态 converter、方法匹配、重复注册、请求作用域、Cookie、上传对象及重载期间的行为。普通 JSON Handler 与流式 Handler 分开验收；不宣称兼容所有 Quart API。

### D4：Pages 的后端与前端闭环

当前已有 `pages/<name>/index.html` 扫描、受限资源 URL、Bridge SDK、sandbox iframe、卡片与侧栏入口；但 `dashboard/src/router/MainRoutes.ts` 缺少被调用的 `PluginPage` 路由，详情页没有多页面入口。

迁移方法：`plugin_page_auth.py` 改为接收显式请求数据，不再依赖 Quart 全局 request；旧 Pages 路径和 Bridge 协议先保持兼容。前端注册 `PluginPage` 路由，在 `PluginDetailPage.vue` 添加紧凑页面选择，复核 `PluginPagePage.vue` 的高度、滚动和空/禁用状态。插件资源令牌只授权对应资源，不授权插件管理 API。

资源令牌当前 TTL 为 60 秒。真实页面的懒加载和长时间停留需验收；这不是已经确认的失败，也不应直接用无限期令牌“修复”。

### D5：流式响应与请求正文

对照基线的 `asgi_runtime.py._quart_response_to_starlette()` 会 `await quart_response.get_data()`；Quart 请求兼容绑定会 `await request_.body()`。前者不是流式转接证明，后者不是有界大文件处理证明。

迁移方法：原生 SSE 使用异步迭代输出，必要的旧插件流式响应保留流式转接与取消；上传按入口限制和流式/落盘边界处理。保留多个 `Set-Cookie`、MIME、下载文件名等响应语义；不把所有响应强制合成 JSON 或 bytes。

### D6：启动、停止和 webhook

本地 `initial_loader.py` 创建 `AstrBotDashboard`，Core 持有 `dashboard_shutdown_event`；本地更新器属性叫 `astrbot_updator`，官方 app 装配使用 `astrbot_updater`。平台统一回调接收 Quart request，部分 Adapter 另有独立 Quart 服务。

迁移方法：在装配处适配真实对象名，不顺带重命名整个 Core。按 Adapter 单独检查请求/响应契约；新旧框架间不能损坏签名验证原文。检查 Slack、QQ 官方、企业微信、企微 AI Bot、微信公众号等独立服务，未迁移完前保留 Quart 依赖。

## 4. 基础文件具体改法

| 文件 | 计划中的改法 |
| --- | --- |
| `astrbot/dashboard/server.py` | 通过 app factory 装配 FastAPI，绑定现有生命周期、DB 和关闭信号；迁移鉴权/静态资源/上传限制，不复制 Core |
| `astrbot/dashboard/api/app.py`、`router.py` | 按阶段接入已迁移服务与旧路径兼容路由；检查每条新保护路由的鉴权及 scope |
| `astrbot/dashboard/api/auth.py`、`services/auth_service.py` | 拆分凭据提取、身份验证、权限与登录业务；以 D1 的矩阵确定本地行为 |
| `astrbot/dashboard/asgi_runtime.py`、`astrbot/api/web.py` | 引入必要的插件 Web 请求/响应接口和有限旧插件兼容；不把缓冲转换当流式支持 |
| `astrbot/dashboard/plugin_page_auth.py`、`plugin_page_bridge.js` | 去除框架全局耦合、保留 URL/资源权限/Bridge 协议，地址调整必须与前端配套 |
| `astrbot/dashboard/responses.py`、`schemas.py` | 保持旧响应包与参数别名；新 schema 的 422、默认值和省略字段不能改变旧接口 |
| `astrbot/core/initial_loader.py`、`core_lifecycle.py` | 仅在装配/关闭契约确有必要时修改，不迁移执行器和 turn 生命周期 |
| `astrbot/core/star/context.py`、`star_manager.py` | 尽量不改公开注册接口；如兼容装配必须调整，保留 owner 归属与卸载清理 |
| `astrbot/core/platform/sources/*` | 逐个迁移 Web 服务或做请求适配，保留平台签名与原始响应；不批量替换 import |
| `pyproject.toml`、`requirements.txt`、`uv.lock` | 引入经过验证的 FastAPI/解析依赖，同步现有依赖入口；不照抄旧官方下限或升级无关依赖 |
| `dashboard/src/router/MainRoutes.ts`、`views/extension/PluginDetailPage.vue`、`views/PluginPagePage.vue` | 完成 Pages 入口与布局验收，不重新设计整套管理页 |
| `dashboard/src/api/*` | 暂不全量切换；后台稳定后再单独迁移 typed client，避免与框架切换捆绑 |
| `tests/test_dashboard.py` 等现有边界测试 | 改造框架相关 fixture，保留对公开行为的断言；不因测试依赖 Quart 就删除测试 |

## 5. P0 尚待补齐

- 逐接口核对前端、插件及外部客户端的实际调用；本表的代表入口不足以完成切换。
- 固定目标依赖版本及后续官方修复列表，本次未刷新远端或安装依赖。
- 扫描实际插件对 Quart request/Response/上传/SSE 的依赖，不读取或记录凭据和私密内容。
- 记录原服务真实启动与流式链路结果，区分源码与运行副本。
- 复核实施时工作区的运行时修改，避免基线漂移；本次没有修改这些文件。
