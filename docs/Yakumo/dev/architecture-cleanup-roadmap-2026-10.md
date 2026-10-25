# 架构收口与清理路线图

更新时间：2026-10-24

状态：总路线图提案，按独立批次执行；2026-10-24 已完成 Profile 删除失败语义、路由持久化原子性和计划校准，其余架构阶段尚未启动。

本文覆盖 AstrBot Python runtime、Dashboard Python 服务和 Vue/TypeScript 前端，负责安排架构收口的顺序、依赖和验收门槛。它不替代已有专项设计，也不把已完成源码实施、但尚未完成真实平台验收的工作重新列为待开发功能。

## 1. 目标

把当前“局部 typed owner 已建立、旧兼容通道仍在运行”的状态收口为清晰的运行时边界：

- 一个回合只有一个明确的配置身份、回合状态 owner 和可见输出结算路径。
- `CoreExecutionSpec -> Executor -> CoreExecutionOutcome` 保持单向关系。
- `event.extra` 只承担明确登记过的兼容投影，不再承担新的内部事实。
- 普通消息、插件输出、主动任务和延迟投递遵循同一套输出回执与完成语义。
- Dashboard 前后端的迁移兼容入口有调用者证据、切换条件和退役顺序；消息视图共用稳定的数据转换规则。
- 兼容代码按证据退役，而不是按文件大小或静态“看起来没用”删除。
- 通过真实运行 trace 证明边界后，再做高风险删除或合并。

## 2. 当前判断

### 已确认的结构问题

1. `InteractionOutputController` 仍同时处理输出意图、流式输出、插件输出、Core 结果、消息物化、平台发送和部分持久化，当前文件约 5,548 行。
2. `AstrMessageEvent` 同时保存 typed Interaction state、平台输出 hook 和 legacy `extra` 投影。兼容边界存在合理原因，但内部读取面尚未完全收口。
3. `AstrBotCoreLifecycle` 既是组合根，又修改进程级代理环境、初始化组件、启动后台任务并执行关闭编排。
4. Handler-first、Interaction/Personal、Core、Cron/主动任务和平台适配器仍需要用同一套运行证据证明终态与完成回执一致。
5. `astrbot/core/provider/entites.py` 是仓库内未发现引用的纯转发模块，但外部插件使用情况未知。
6. Dashboard Profile 删除必须避免“路由已删除、Profile 仍存在”的失败状态，并区分 Profile 删除与孤立路由清理。
7. 前端多个消息视图有相似的数据转换逻辑；`MessageListDEPRECATED.vue` 已完成静态、动态、插件和构建源码核验并于 2026-10-25 删除。旧知识库路由仍有页面链接。
8. `dashboard/routes` 导入别名和 `dashboard/api` 路由注册属于 Dashboard 迁移兼容边界；迁移切换和调用者核验前不按重复业务实现删除。

### 不应当作为首轮清理目标的内容

- 本地 `__pycache__`、`node_modules`、文档构建产物：当前未被 Git 跟踪，属于工作区生成物。
- `MessageSesion`：当前仍有 Dashboard、Context 和测试引用，不能按死代码处理。
- 公开 Event API、`send`/`send_streaming` 兼容拦截：在内部消费者和外部插件迁移前不能删除。
- 再造一个新的总 Context、Output Runtime 或 Executor Body：现有 typed owner 尚未完成证据闭环。

## 3. 目标边界

```text
ConfigRouteTable
  -> RuntimeSelection
  -> TurnConfigSnapshot
  -> PersonalTurnContext / InteractionTurnState
  -> CoreExecutionSpec
  -> selected Executor
  -> CoreExecutionOutcome
  -> OutputIntent
  -> MaterializedMessage
  -> PhysicalDelivery
  -> DeliveryReceipt
  -> turn settlement / history / postprocess
```

职责约束：

| 领域 | 长期 owner | 其他组件可以做什么 |
|---|---|---|
| 配置选择 | `AstrBotConfigManager` / `RuntimeSelection` | 生成只读回合快照，不在下游重新路由 |
| 回合准入与并发 | `PersonalRuntimeManager` / `PersonalTurnContext` | 管理 session、lease、取消和 follow-up |
| 回合规范状态 | `InteractionTurnState` | 保存回合事实、输出事实和 delivery receipt |
| Core 执行 | `CoreExecutionHead` 与选定 Executor | 生成执行结果和执行事件，不直接决定平台投递 |
| 逻辑消息输出 | `InteractionOutputController` | 处理各输出来源并更新现有 receipt |
| 物理投递 | Output Adapter / 平台适配器 | 执行物理发送并报告结果，不决定整轮终态 |
| 整轮可见完成 | `TurnDeliveryCoordinator` | 逻辑消息满足完成条件后触发 visible-turn completion |
| 兼容状态 | Event adapter projection | 只读/写已登记的旧字段，不成为内部主读取路径 |

## 4. 实施阶段

### 阶段 0：冻结范围与建立基线

目的：防止清理工作继续引入新的并行通道。

工作项：

- 本路线图的整改批次内，不新增 Executor、输出类型、Event extra 或新的跨层回调；正常功能开发另行评估，不受此提案自动冻结。
- 以现有文档为基线：
  - [Output Runtime Owner Inventory](./output-runtime-owner-inventory.md)
  - [event.extra Owner Inventory](./event-extra-owner-inventory.md)
  - [legacy retirement inventory](./legacy-retirement-inventory.md)
  - [configuration boundary convergence plan](./configuration-boundary-convergence-plan.md)
  - [cross-component convergence plan](./cross-component-convergence-plan.md)
- 对照当前代码复核现有清单，记录文档差异、未决 owner 边界和真实验收缺口，不另建重复的完整盘点。
- 覆盖 Python runtime、Dashboard 后端和 `.ts/.js/.vue` 源码；按行为与引用评估，不只按文件大小判定。
- 为仍有争议的字段补齐主写者、主读者、兼容读者、生命周期和删除门槛。
- 将配置删除、输出状态、整轮完成和平台发送分别记录责任点及失败语义。

交付物：代码与现有文档的差异清单、未决 owner 边界、前后端清理候选和验收缺口。

通过条件：所有后续批次都能指出修改的是哪个 owner，且不需要新增总 Context 或兼容开关。

### 阶段 1：核对现有输出回执，再拆输出控制器

目的：在不改变平台 API 的情况下，明确逻辑输出与物理投递的关系。

工作项：

- 复核现有 receipt helper 和 `InteractionTurnState.output_delivery_receipts` 对各输出来源的覆盖；只补已证实缺失的 identity 或状态，不重建 receipt helper 或第二套回执。
- 把输出控制器内的状态分为规范事实和 diagnostics；失败原因、模式和观察任务不能继续混成第二个输出状态机。
- 核对 Plugin Artifact、Delayed Delivery 和 Turn Delivery 是否都按现有 identity/receipt 协作，为仍旁路 receipt 的路径登记迁移门槛。
- 沿现有 `PreOutputProcessor`、`InteractionEventOutputAdapter`、`TurnDeliveryCoordinator` 边界拆分控制器内部职责；保留原入口作为过渡委托。
- 继续保留 Event 方法拦截，直到普通、流式、插件、Core-final、主动和迟到输出都通过同一回执语义。

最小验收：

- 单个逻辑消息的所有物理组件成功后才产生完成回调。
- 部分失败不能伪造成功 receipt。
- 迟到输出不能重新打开已经完成的 turn。
- 取消、超时、重复投递和平台发送失败分别留下可区分的终态。

依赖：阶段 0。不得先删除 Event hook。

### 阶段 2：按字段家族收敛 `event.extra`

目的：让 `InteractionTurnState`、`PersonalTurnContext`、`CoreExecutionSpec` 和专属 runtime 对象继续成为内部主状态。配置路由和准入快照的既有 C2-C5 成果不重复规划。

迁移顺序：

1. 已有 typed owner 的输出状态和回合标记。
2. `ProviderRequest`：明确 Native adapter 请求边界，插件委托请求改由显式任务对象携带。
3. Core 执行规格、取消信号和生命周期句柄中仍以 extra 作为主读取路径的字段。
4. 只剩外部插件或分支事件需要的兼容字段；配置投影只处理新发现的偏差。

每组字段都必须完成：

- 写入方迁移；
- 内部读取方迁移；
- 分支/复制事件验证；
- 外部消费者检索或兼容周期说明；
- 删除旧主读取路径，只保留单向投影。

禁止：批量删除所有 `get_extra`/`set_extra`，或以默认值掩盖缺失 owner。

### 阶段 3：收敛多入口运行时并完成真实验收

目的：证明不同入口最终遵循相同的回合、执行和输出语义。

验收矩阵至少包含：

| 入口 | 成功 | 取消/超时 | 输出与历史 | 额外要求 |
|---|---|---|---|---|
| 普通私聊 | 一次可见完成 | 无迟到成功覆盖 | 文本、TTS、effect 一致 | Provider 失败可诊断 |
| 群聊连续对话 | owner 唯一 | 新输入正确打断 | 不产生重复完成 | 其他成员不误接续 |
| Core 工具任务 | 即时与最终输出不重复 | follow-up 保持同一 execution | Ledger 与历史分工清晰 | 工具失败不伪造成功 |
| 插件输出 | direct/progress/streaming | 插件失败隔离 | artifact receipt 正确 | 兼容 Hook 行为明确 |
| Cron/主动任务 | 目标和配置身份稳定 | 预算耗尽可收口 | 不复用错误的用户 turn | 一次性副作用不自动重试 |
| reload/关闭 | 活跃任务可收口 | 取消只产生一个终态 | 无资源泄漏 | 插件任务和平台任务可追踪 |

通过条件：trace 按路径携带适用字段：Interaction turn 有 `turn_id`，进入 Core 的路径有 `execution_id`，存在逻辑可见消息时有 `message_id`，需要去重或延迟恢复的投递有 delivery identity。纯 Personal 或插件 direct 路径不伪造 `execution_id`。

### 阶段 4：拆生命周期组合根

目的：降低启动和关闭的隐式副作用，不改变组件 owner。

工作项：

- 将代理环境设置移入明确的进程配置阶段，并定义恢复/重载语义。
- 将 `initialize()` 分成可独立检查的阶段：基础设施与配置、交互服务、插件与 Provider、平台、后台任务。
- 让 `start()` 只启动已初始化的服务，`stop()` 按依赖反向关闭；保留 `AstrBotCoreLifecycle` 作为组合根。
- 统一后台 task 的创建、命名、失败记录和取消等待。

通过条件：初始化失败能指出阶段和已创建资源；停止过程不会依赖未初始化属性，也不会吞掉仍需报告的失败。

依赖：阶段 3 的真实验收结果，避免在运行时 owner 尚未稳定时重排启动顺序。

### 阶段 5：低风险删除候选

目的：在兼容边界已有证据后，删除真正无消费者的残留。

候选顺序：

1. `astrbot/core/provider/entites.py`：先查已安装插件、发布包和外部导入，再删除或进入正式弃用周期。
2. 已经由 typed owner 完全替代、且无外部消费者的 Event extra 投影。
3. 已被新输出回执完全替代的旧完成标记。
4. `MessageListDEPRECATED.vue`：2026-10-25 已删除；保留仍被页面显式链接的旧知识库路由。

明确不做：删除 `MessageSesion`、公开 Event API 或未经运行证据证明无用的 Native/Provider 兼容层。

### 阶段 6：跨语言重复实现与高影响迁移整理

- 对 `ChatMessageList.vue`、`MessageList.vue`、`StandaloneChat.vue` 的纯消息转换逻辑逐项比对，只抽取行为相同的转换规则，保留各视图自己的交互职责。
- 按配置域记录 `AstrBotConfig.vue` 与 `AstrBotConfigV4.vue` 的迁移状态，不凭组件名称或版本号删除旧组件。
- `dashboard/routes` 导入别名及旧 API path 在 FastAPI 生产切换、HTTP/WS/SSE 验收和调用者核验完成前继续保留。
- 将 `astrbot/core/config/default.py` 拆分作为独立高影响变更，验证默认配置加载、Dashboard schema、迁移器和公开导入兼容。

通过条件：每个抽取或删除都有调用者证据；前端视图行为验收通过；Dashboard 兼容契约未回归。

## 5. 依赖与门禁

```text
阶段 0
  -> 阶段 1 输出回执
      -> 阶段 2 extra 收口
          -> 阶段 3 真实入口验收
              -> 阶段 4 生命周期拆分
                  -> 阶段 5 低风险删除候选
                      -> 阶段 6 跨语言与高影响迁移整理
```

每阶段的门禁：

- 只改一个语义边界，不把 Provider、模型、配置默认值和无关格式化混入同一批。
- 先有 owner 和删除条件，再写代码。
- 先跑受影响的边界测试，再做真实平台验收；未验证的路径不能标记完成。
- 发现外部插件调用者、协议差异或用户数据迁移风险时，停止删除并记录兼容方案。
- 每个批次都保留回滚点，不把多个高风险迁移攒成一个提交。

## 6. 风险控制

| 风险 | 控制措施 |
|---|---|
| 输出重复或漏发 | 先建立 receipt/identity，再拆 Controller |
| 兼容插件被破坏 | Event API 保持稳定，按字段和调用者逐项退役 |
| 取消后资源泄漏 | 用 turn/execution scope 追踪任务，验收关闭和重复取消 |
| 配置重载污染已准入回合 | 只读 `TurnConfigSnapshot`，禁止下游重新路由 |
| 文档与代码漂移 | 每批完成后只更新对应现状文档，不提前勾选长期目标 |
| 工作区用户改动被覆盖 | 实施前检查 diff；本次只修复 `config_service.py` 的 Profile 删除一致性，保留 Prompt/Provider 改动和 `uv.lock` |

## 7. 完成定义

本路线图完成不以“文件变少”或“类变小”为标准，而以以下事实为准：

- 一个回合的配置、执行、输出和结算 owner 可从代码入口直接追踪。
- 内部新增状态不再通过未登记的 Event extra 传播。
- 所有生产入口都能关联到同一套执行与投递 trace。
- 兼容层清单中的每一项都有保留理由、消费者证据和删除门槛。
- 普通、插件、主动、Core、取消、超时、reload 和迟到输出场景完成真实验收。
- 只有满足上述条件的兼容模块和转发文件才进入删除批次。

## 8. 当前执行批次

本轮先修复 Profile 删除与路由清理的失败语义，收口 UMO 路由持久化与 Profile Adapter 准入的失败补偿，并同步校准 receipt 状态及跨语言清理范围。其余阶段按独立批次推进；本次不删除公开兼容接口、不拆大型协调器，也不提交代码。
