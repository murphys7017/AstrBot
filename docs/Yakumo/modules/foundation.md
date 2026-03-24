# Foundation Modules

## Provider

### `astrbot/core/provider/manager.py`

职责：

- 管理聊天模型 Provider
- 管理 STT Provider
- 管理 TTS Provider
- 管理 Embedding Provider
- 管理 Rerank Provider
- 提供 session/global 维度的 provider 选择

说明：

- 这是当前模型能力的统一入口
- 还兼带了一部分 persona 相关兼容逻辑

重构关注点：

- 更适合收敛为 `ProviderGateway`
- 不应继续持有过多 persona 语义

## Persona

### `astrbot/core/persona_mgr.py`

职责：

- 加载和维护人格
- 解析默认人格
- 根据 session/conversation/provider settings 决定最终生效人格
- 管理人格文件夹

说明：

- 当前 Persona 不只是一个静态 Prompt
- 它还包含 begin dialogs、tools、skills、自定义错误消息等

重构关注点：

- 未来适合拆成 `PersonaRepository + PersonaResolver`

## Conversation

### `astrbot/core/conversation_mgr.py`

职责：

- 创建和切换会话中的对话
- 删除对话
- 获取当前会话绑定的对话
- 将持久化对话模型转换为运行时对话对象

说明：

- 这里区分了 session 和 conversation
- `unified_msg_origin` 是会话级标识

重构关注点：

- 未来适合变成 `ConversationStore` 或 `SessionConversationService`

## Message Platform

### `astrbot/core/platform/manager.py`

职责：

- 加载各类平台适配器
- 启动平台 run task
- 管理平台实例生命周期
- 将平台接收到的消息送入 `event_queue`

说明：

- 当前支持多种消息平台
- 还会额外创建 WebChat 平台

重构关注点：

- 未来适合抽象为 `MessageGateway`
- 不同平台适配器可以作为独立 capability 或 connector service

## Database

### `astrbot/core/db/*`

职责：

- 提供 Conversation、Persona、API Key 等持久化存储
- 为上层 Manager 提供数据库访问

说明：

- 这是基础设施层
- 当前更多作为内部实现使用

重构关注点：

- Yakumo 下建议对上层暴露仓储接口，而不是直接暴露完整数据库能力

## 当前判断

这一层是 Yakumo 的“基础服务层”候选区域。

建议保留为主服务器的一部分，先抽接口，再决定是否进一步独立部署：

- ProviderGateway
- PersonaResolver
- ConversationStore
- MessageGateway
- Persistence Layer
