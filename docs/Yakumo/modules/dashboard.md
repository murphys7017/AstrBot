# Dashboard Modules

## Dashboard 后端

### `astrbot/dashboard/server.py`

职责：

- 创建 Quart 应用
- 初始化认证中间件
- 注册 API routes
- 绑定核心运行时对象
- 提供静态资源服务

说明：

- 这是 Dashboard 服务端入口
- 也是 WebUI 和核心运行时之间的接口层

### 认证与改密状态

认证 API 由 `astrbot/dashboard/services/auth_service.py` 和
`astrbot/dashboard/password_state.py` 共同维护。登录成功响应包含新的 JWT，以及
`change_pwd_hint`、`legacy_pwd_hint`、`password_upgrade_required` 状态。需要改密时，
前端先保存 token 和改密标记，再用 `router.replace('/auth/setup')` 进入改密页；改密成功后
后端清除 `password_change_required` 并签发新 JWT。

`dashboard/src/views/authentication/auth/SetupPage.vue` 在已有 token 且
`change_pwd_hint=true` 时把该会话视为可继续的改密会话，即使 `setup-status` 暂时返回
不一致或请求失败也不会立即跳回登录。`dashboard/src/main.ts` 对 Axios 和 fetch 都记录
请求实际携带的 Bearer token；只有 401 对应当前 token 时才清理本地会话，避免登录或改密
期间迟到的旧请求覆盖新会话。认证挑战接口本身不触发全局 401 清理。

这是一条已实施的前端会话保护路径，生产构建和类型检查已通过；真实浏览器账号流程仍需
在部署实例上验收。

## Dashboard 路由

### `astrbot/dashboard/routes/*`

主要类别：

- `auth.py`: 登录和认证
- `config.py`: 配置管理
- `plugin.py`: 插件管理
- `platform.py`: 平台管理
- `conversation.py`: 对话管理
- `skills.py`: skills 管理
- `subagent.py`: 子 Agent 管理
- `knowledge_base.py`: 知识库管理
- `chat.py`: 聊天与流式交互

说明：

- 这里基本就是后端管理面 API 层
- 多数路由直接面向运行时 Manager

## Dashboard 前端

### `dashboard/src/router/MainRoutes.ts`

职责：

- 定义前端主页面路由

主要页面：

- Welcome
- Extension
- Platforms
- Providers
- Config
- Conversation
- SessionManagement
- Persona
- SubAgent
- Cron
- Console
- Trace
- KnowledgeBase
- Chat
- Settings

### `dashboard/src/views/*`

职责：

- 各个管理页面实现

### `dashboard/src/components/*`

职责：

- 复用组件
- Chat UI
- Extension 面板
- Persona 组件
- 消息渲染组件

## 当前判断

Dashboard 当前是 AstrBot 的管理和使用入口，但它不是 Yakumo 第一阶段的核心拆分对象。

原因：

- 现阶段最重要的是拆 runtime、foundation、agent、capability 的边界
- Dashboard 可以先继续作为现有平台的上层管理界面
- 等主平台和能力平台边界稳定后，再决定 Dashboard 是否需要感知多服务拓扑
