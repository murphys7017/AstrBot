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
