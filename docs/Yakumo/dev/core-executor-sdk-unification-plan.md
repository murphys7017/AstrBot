# Core 多执行内核切换与 Codex SDK 常驻实施方案

日期：2026-10-22
状态：分批实施中；S0 和 S1 尚未达到最终验收条件。
适用对象：GPT-6.1 SOL 执行模型；当前范围仅限 AstrBot Core。

## 实施进度（2026-10-22）

- 依赖已固定为 `openai-codex==0.163.0`，`uv.lock` 已包含 SDK 与匹配平台 runtime；隔离项目副本中的 `uv lock --check` 通过。
- Windows SDK smoke 使用独立 `CODEX_HOME` 启动真实 `AsyncCodex`，成功创建两个不同 thread 并关闭 client；未运行已认证 turn。
- SDK fake 边界覆盖共享 client、多 thread 隔离、跨 thread turn 串行等待、取消超时、启动取消清理，以及启动锁等待和 runtime 关闭均有界；启动晚于关闭请求时不会发布 client。真实 SDK 的跨 thread 并行仍关闭，须先通过 Windows 并发 smoke。
- Core 全局 selector 已覆盖唯一活动内核、停止旧准入、等待 run/清理 task、超时保留旧内核和 legacy profile 冲突。
- 普通 Interaction 与 Cron/主动任务都使用 Core-wide selector lease；Codex progress 只映射 allowlist 阶段，经 Output Controller 的 `core_progress` 路径呈现。
- 当前窄回归：41 项执行器、selector、registry、桥接和 proactive 测试通过；4 项进度输出边界测试通过；相关 Ruff 检查和 `git diff --check` 通过。
- 2026-10-22 复核追加：Codex session 5 项并发/关闭边界和 executor adapter 3 项测试通过；使用系统 Python 3.11，并在进程内禁用 Loguru 文件 sink 以避开 Windows IPC 权限限制。项目 Python 3.12 虚拟环境因 `_ssl` DLL 加载失败无法收集 pytest；改动文件在 Python 3.12 下编译通过，Ruff 和 `git diff --check` 通过。
- 未完成验收：真实账号 turn 与 interrupt、取消中的真实 runtime 子进程回收、管理界面的运行时切换入口、Native 普通 Interaction 共用 coordinator 的完整收口，以及 OLV/Live/Live2D 实机回归。不得据当前 fake/启动 smoke 宣布 SDK 准入或全链路实施完成。

关联文档：

- [Core 内部执行器替换实施方案](internal-executor-replacement-plan.md)
- [内部可替换执行器：操作级实施手册](internal-executor-replacement-implementation-guide.md)
- [Codex 长期 Core 执行器实施计划](codex-persistent-executor-implementation-plan.md)
- [执行后端真实验收矩阵](execution-backend-acceptance-matrix.md)

## 1. 结论与推荐方向

建议把 OpenAI Python Codex SDK 作为 Codex 在 Core 中唯一的生产接入路径。启用 Codex 后，由 Core 生命周期持有长期运行的异步 SDK runtime；一个 SDK 客户端服务多个 Core-owned thread 和 turn，不能按每次请求创建、关闭客户端，也不能在 SDK 失败时静默回退到手写 JSON-RPC 或 `codex exec`。

Core 允许注册多个执行内核，例如 Native 和 Codex，但在任一时刻只有一个 Core-wide `active_executor_id` 接收新任务。它不是按用户、平台、任务类型或 bot 配置分别选内核；不得同时路由给多个 backend，也不得在一个任务中并行询问多个内核后择优。切换是明确的全局操作：现有执行先按正常 Core 生命周期完成或取消，不做运行中迁移；切换窗口暂停新的 Core 执行准入，完成旧内核的活动 run 清理后再切换 selector。其他已启用 backend 可以保持已加载但处于 idle，不接收新 run。切换期间的请求使用现有交互失败/等待策略，不新增第二套队列。

内核切换不要求迁移或继承引擎私有的对话历史。AstrBot 的上下文、记忆和可见对话历史是唯一跨内核事实来源；每轮由 Core 使用当前 AstrBot 状态准备输入，再交给当前唯一选中的内核。某个内核自己的 thread/session 可以独立保留，但它不能代替 AstrBot 记忆，也不能作为切换成功的前置条件。

SDK 的选择仍有一个实施前准入门槛：当前官方资料确认 Python 包 `openai-codex` 有稳定发布、`AsyncCodex` 和随 SDK 固定版本的 Codex CLI runtime；Python 文档示例明确展示异步创建 thread、运行 turn 和沙箱 preset。Codex 平台指南也称 SDK 可用于启动、恢复和流式任务，同时把需要产品级持久对话、直接流式事件和审批处理的集成指向 app-server。不能把 TypeScript 示例直接当成 Python API 保证。6.1 必须针对选定的 Python SDK 精确版本，核对并实测公开 API 是否满足 Core 必需的事件流、取消/interrupt、thread 创建、关闭和权限配置。thread resume 只在启用同内核连续性时验证，不作为切换内核的条件。不能依赖未公开的 SDK 私有对象或协议细节。

如果公开 SDK API 不满足 Core 必须的取消或进度能力，暂停该批并报告能力缺口，等待确定是缩小首期能力还是把 app-server 定为唯一传输方案。不要在一个实现里长期并存“SDK 主路径 + 手写 JSON-RPC 兜底”。

期望结果是 Native 与 Codex 都由同一 Core 运行协调器负责准入、执行身份、deadline、取消、唯一终态和资源清理；Codex 的 SDK 线程和进度细节留在 Core Adapter 内。Personal 和 Output 继续是唯一用户表达与平台投递边界。

## 2. 范围与非目标

本方案只覆盖：

- 多个执行内核的 Core registry，以及单一、全局、可切换的 active backend 选择；
- AstrBot Core 的执行器准备、选择、装配、运行协调和生命周期；
- 用 Python Codex SDK 替换当前 Codex app-server 手写 JSON-RPC 传输层；
- Core-owned Codex runtime；Codex thread/session 的隔离，及可选的同内核连续性；
- 执行进度经 Core 契约和既有 Output Controller 的受控呈现；
- Native 普通交互与 Codex 外部执行共享 Core 终态和结算规则，同时保留各自必须的输出适配；
- Native -> Codex -> Native 切换验收，确认共享 AstrBot 上下文，无需跨内核历史复制。

本方案不做：

- 不开发插件、不修改 self-code 插件，也不新建插件调用服务；
- 不把插件工具、AstrBot 全部 FunctionTool、平台 Event、Persona Prompt 或 TTS/effect 暴露给 Codex；
- 不把 AstrBot Core 变成 Codex Desktop 的控制面板；
- 首期不承诺接管正在 Desktop 中运行的对话。首期只使用 AstrBot 自己创建并映射的 Codex thread；
- 不自动列出、导入或复用 Codex Desktop 的历史 thread。历史 thread 的只读、fork 或恢复另立验证项；
- 不要求 Native、Codex 或未来 backend 之间复制、导入或同步对话 transcript/thread id；
- 不在本批接入天气搜索、任意联网能力、MCP 或用户逐项审批 UI。Core 当前准入的能力仍是唯一授权来源；
- 不改写 OLV、Live2D、TTS 和平台适配器协议。迁移必须保持这些输出行为；
- 不引入分布式 Core、多个 Core Head、第二个 deadline owner 或新的最终回复通道；
- 不通过模型名称、关键词或执行失败自动切换 Native/Codex。

## 3. 已核对的代码状态

以下是本次源码核对结果，不等于完整平台验收：

1. `astrbot/core/executors/contracts.py` 已有 SDK 无关的 `ExecutorRun`、`ExecutionProgressUpdate`、`ExecutionOutputUpdate` 和 `ExecutionFinalUpdate` 契约；`runtime.py` 已负责统一消费 run、驱动 Head 终态并关闭 run。
2. 当前 Codex 适配仍由 `codex_session.py` 自行启动 `codex app-server --stdio` 并维护 JSON-RPC；`codex_protocol.py` 是自制协议层。当前 `pyproject.toml` 和 `uv.lock` 没有 Codex Python SDK 依赖。
3. `ExternalExecutorSessionRegistry` 是进程内映射；当前按完整 session key 为会话创建独立的 `CodexSessionManager`。AstrBot 重启后没有 Core 持久化的 session-key 到 Codex thread-id 映射。
4. `CodexExecutorRun` 会积累 agent message delta 供最终结果使用，但只对少数通知产生粗粒度进度；`ExecutionResultOutputBridge.accept()` 目前只投递最终结果，忽略进度并抑制增量正文。
5. `core_execution.executor_id` 目前通过当前 bot 的配置快照解析。它能做到每个 run 选择一个 backend，但不能表达用户现在提出的“Core 全局只有一个活动内核”；新方案必须将选择 owner 收敛到 Core runtime 的单值配置，并处理旧 per-bot 配置冲突。
6. Native 的 `ExecutorRun`/adapter 与主动任务路径已经存在，但普通 Interaction 仍保留 Native 专用生产输出路径；因此不能把“已有 ExecutorRun 契约”当作“Core 整体执行生命周期已统一完成”。
7. `core_lifecycle.py` 创建并关闭 external executor session registry，表明 Core 生命周期已有资源 owner 落点。后续 SDK runtime 应沿用 Core 生命周期，不转交插件或平台事件。
8. 现有 Codex 会话测试使用 fake subprocess；先前 Windows smoke 曾记录关闭阶段等待进程退出失败，但本轮未重新复现。必须用真实 SDK/runtime 重新验收 Windows 启动、取消和关闭。

实际文件入口：

- `astrbot/core/executors/contracts.py`
- `astrbot/core/executors/runtime.py`
- `astrbot/core/executors/codex_cli.py`
- `astrbot/core/executors/codex_session.py`
- `astrbot/core/executors/codex_protocol.py`
- `astrbot/core/executors/session_registry.py`
- `astrbot/core/executors/assembly.py`
- `astrbot/core/executors/coordinator.py`
- `astrbot/core/core_lifecycle.py`
- `astrbot/core/interaction/executor_result_bridge.py`
- 普通交互入口 `astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py`
- 主动任务入口 `astrbot/core/proactive_agent_turn.py`

## 4. 目标架构和所有权

```text
OLV / 普通交互 / Cron / 主动任务
  -> AstrBot-owned context/memory snapshot + provider-neutral Core preparation
  -> Core-wide active_executor_id（单值）+ Core executor registry
  -> Core coordinator + CoreExecutionHead + 唯一 deadline
  -> ExecutorRun
       Native adapter
       Codex SDK adapter -> Core-owned long-lived AsyncCodex runtime
                           -> optional Codex-private thread/session
  -> normalized progress/output/final updates
  -> Core result/progress bridge
  -> Personal / Output Controller / platform delivery
```

| 对象 | 唯一责任 |
| --- | --- |
| Personal Runtime | 决定是否委派、管理对话顺序和统一用户表达 |
| Core executor selector | 保存唯一 active executor id；切换时管理准入与旧 run drain |
| Core Head/Lifecycle | execution identity、取消、deadline 结算、唯一终态和生命周期清理 |
| Core coordinator | 创建并驱动所选 `ExecutorRun`，投影更新，统一处理失败与关闭 |
| Native Adapter | 保留 Native Provider、工具、Hook、富文本/流式语义，并投影到中立 Core 契约 |
| Codex SDK Adapter | SDK API 转换、thread/turn 调用、事件归一化和 Codex 错误转换 |
| Core Codex runtime owner | 持有 SDK client/runtime、并发控制和全局关闭 |
| Core per-engine thread repository（可选） | 启用同内核连续性时，持久化 Core 会话键与该 backend thread-id 的绑定及恢复元数据 |
| Output Controller | 唯一负责可见状态、文本、语音、effect、平台投递、历史和最终回执 |

Codex SDK Adapter 不得直接调用 `event.send()`，不接收完整的 AstrBot Event/Context，不写可见对话历史。Codex 终态正文仍经既有 Personal Core-final 表达路径；进度只能走既有 Output Controller 的 progress 边界。

AstrBot 生成的 `CoreExecutionSpec`、上下文投影和 memory snapshot 是 backend-neutral 输入。切换内核只改变执行 Body，不更换或复制 AstrBot 的 memory、conversation history、Personal 或 Planner。backend 私有 thread 的存在与否不改变跨内核上下文来源。

## 5. SDK 采用边界

### 5.1 依赖和 runtime

- 使用官方 Python 包 `openai-codex` 的稳定发布，不使用 prerelease。
- 精确固定经过验收的 SDK 版本，并将对应 runtime 解析结果写入 `uv.lock`；禁止仅写宽松下限或在部署时自动升级。
- 默认使用 SDK 自带的固定 Codex CLI runtime。除非显式的运维配置和版本检查需要，不传 `CodexConfig(codex_bin=...)`，避免绕过 SDK 版本绑定。
- 对异步 AstrBot 使用官方异步 API `AsyncCodex`。SDK 对象由 Core Lifecycle/runtime registry 持有。
- 启用 Codex 时可以在首次选中时惰性启动；一旦启动，只在 Codex 被显式禁用、runtime identity/权限配置变更或 Core shutdown 时关闭。selector 切到其他 backend 不关闭 Codex runtime；不能按 turn 创建 client/process。
 Core runtime 按 Codex runtime identity/认证环境复用 SDK client，不按用户 session 创建。不同安全配置或不同 `CODEX_HOME` 不得错误共享；selector 切到 Native 时，已启动的 Codex runtime 保持 idle。
- SDK import、版本检查、启动失败时明确将 Codex executor 标记不可用并返回可诊断错误；不悄悄回退到 Native，也不启动另一条传输路径。
- `executor_id=codex_cli` 是现有配置/日志身份。首期保留该值，避免无必要的配置和 thread key 迁移；内部实现类可改为 `CodexSdkExecutorRun` 等名称。

### 5.2 SDK 公共 API 准入检查

在改变当前生产传输之前，对锁定版本逐项验证并记录确切 API：

| Core 需要 | 准入证据 |
| --- | --- |
| 异步创建/关闭长期 client | 可重复启动、关闭，AstrBot 事件循环无阻塞 |
| 创建 thread、运行 turn、Core-owned thread/session 隔离 | SDK 的公开、受支持 API；不得依赖其他 backend 的 thread/history |
| 获取终态和有界进度事件 | 公共 API 能提供足够事件；不把私有推理或原始 tool trace 传给用户 |
| 取消/中断活动 turn | 有公开、受支持的 interrupt/cancel API；不能只取消本地 Python Task |
| sandbox 和 approval 设置 | 能从 Core 配置显式映射；未知值 fail closed |
| Windows 生命周期 | 在目标 Windows 环境成功启动、多轮、取消、关闭且无残留进程 |

SDK 对同一 Codex thread 的恢复能力只在明确启用“Codex 内核自己的多轮连续性”时才是准入条件；它不是切换 Native/Codex 的条件。若首期采用每轮新 thread，则必须证明 AstrBot 当前上下文已完整投影到新 thread。

如果 Core 必需的异步关闭、取消或输出事件不能通过 SDK 公共 API 验证，停止 SDK 替换批次。不要通过 monkey-patch SDK 内部对象来通过准入检查。

### 5.3 传输唯一性

最终生产态只能留一个 Codex transport：

- SDK 准入通过：Core 仅使用 SDK；删去被替代的手写 JSON-RPC 生产路径和配置，完成迁移后再删旧协议测试。
- SDK 准入不通过：该批停止并回报；由架构决策确定是缩小首期能力还是采用 app-server 作为唯一协议层。
- 不保留 SDK 失败后的运行时 fallback，不依据异常类型、平台或 task 类型切换 transport。

旧 app-server 代码可以在有明确隔离和删除期限的迁移提交中暂存；它不是长期双栈方案。

## 6. 内核切换与 backend 私有 session

### 6.1 内核切换和上下文语义

- Core runtime 只有一个单值 `active_executor_id`，初始值为 Native。registry 可以注册多个 factory，但只有选中的 backend 创建 run 并接收任务；未选中的 backend 不启动新的 runtime。已启用且启动过的 Codex SDK runtime 可以保留为 idle，直到 Core shutdown 或 Codex 被禁用。
- 该单值归 Core runtime 的全局配置所有，不放在每个平台 bot 的独立配置快照里；所有 bot 的 Core 委派都使用同一个活动内核。建议配置语义为 `core_execution.active_executor_id`，具体 schema 位置要在配置字段清点后确定。
- 新执行在 Core 准入时读取一次 active id，并把它固定到 execution identity/diagnostics；一项执行从开始到终态只属于这一个 executor。禁止 provider fallback 和多 backend fan-out。
- 切换请求先进入 draining：不再向旧 backend 接纳新 Core run，已有 run 由原 Head 完成或按明确的 Core cancel 结束。全部旧 run 清理后，原子更新 active id 并接纳新 run；已启用的持久 runtime 可以继续 idle，不等于仍有资格处理任务。
- 切换不会把旧 backend transcript/thread 内容导入新 backend。新 backend 使用当轮由 AstrBot 构造的 context/memory snapshot。AstrBot 的 memory 更新流程保持现有 owner 和时序，不等待或依赖 backend 私有记忆同步。
- 同一 backend 下是否恢复自己的私有 thread 是独立配置/产品能力。切回某 backend 可以从其自己的 thread 继续，也可以新建 thread；两种方式都必须以当前 AstrBot context 为准，不能假定它包含全量用户记忆。
- 当前按 bot 配置快照选择 executor 的实现与全局 active selector 不兼容。实施时统一选择来源；检测到旧 bot 配置值彼此冲突时必须报清楚并要求迁移，不能静默挑一个值。

### 6.2 会话身份

现有 `ExternalExecutorSessionKey` 包含 `executor_id`、`executor_instance_id`、`runtime_config_id`、`session_id`、`workspace_root` 和 `workspace`。实施时要先核实 session id 的真实生成规则，确保它在 bot/平台/对话 owner 范围内唯一；不能假定裸平台 session 字符串足够。thread/session key 必须包含 executor identity，使两个 backend 的私有 session 永不串用。

如果产品选择持久化某 backend 自己的 thread，映射逻辑唯一键至少覆盖：

- executor id 和 executor instance；
- 当前 bot 的 runtime config identity；
- 平台/bot 下的逻辑对话 session identity；
- canonical workspace root 与 workspace；
- Codex home/runtime identity；
- 会影响 thread 权限的 sandbox/approval policy fingerprint。

改变 workspace、runtime config、认证 home 或权限策略后，不得复用旧 thread。应创建新绑定或明确失败，不能让线程在新权限下悄悄继续。

### 6.3 Core 持久化记录（可选）

同内核的 Codex thread continuity 是可选增强，不是 Core 执行器解耦或跨内核切换的完成条件。启用后，Core repository 保存：

- schema version；
- 上述会话唯一键或其稳定、不可逆索引；
- Codex thread id；
- canonical workspace 与 Codex home identity；
- SDK/runtime version 和权限配置 fingerprint；
- created_at、last_used_at、last_known_status；
- 可选的失效原因；不得保存凭据、原始 SDK event stream 或隐藏推理。

先复用 Core 已有数据库/仓储 owner；若没有适配的持久化边界，再为 Core 设计最小 repository 与迁移。不得借用插件 session、`AstrMessageEvent.extra` 或内存 registry 伪装为跨重启持久化。

### 6.4 并发与恢复

- 同一 Core thread 的 turn 必须串行；相同会话同时到达时由 Core Head 决定排队、拒绝或取消旧 turn，不由 SDK Adapter 自行猜测。
- 不同 thread 的并行度由明确的 Core 限额控制；先通过同一个 SDK runtime 的 Windows 并发 smoke，再开放超过 1 的并发。
- 若启用同内核 thread continuity，AstrBot 重启后才按 repository 中 thread id 调 SDK resume。若记录损坏、thread 不存在或权限 fingerprint 不匹配，按明确策略恢复或新建，并把新 thread 以当前 AstrBot context 初始化；不能把它伪装成跨内核历史继承。
- SDK runtime 进程崩溃后，当前 turn 进入唯一失败/取消结算；后续请求按启用的 per-engine continuity 策略 resume，或以当前 AstrBot context 新建 thread。
- 同一用户的 AstrBot Core thread 与 Codex Desktop 当前活动 turn 分开管理。不得因为本机数据目录相同就向 Desktop 活动 thread 发送新 turn。

首期只保证 AstrBot 创建并管理的专用 Codex 会话。发现/读取历史 Desktop thread、选择后 fork/resume，必须在独立实验确认共享 `CODEX_HOME`、来源可读、权限一致和 Windows 恢复行为后再决定；读取到 thread id 不等于能够附着或控制 Desktop 当前活动 turn。

## 7. Capability、沙箱和审批

- Codex 可用能力必须是 Core 本轮已准入能力与 Adapter 实际支持能力的交集。现在的外部执行请求以空 Core capability snapshot 运行；不得把 SDK 默认能力误认为 AstrBot 已授权。
- 首期文件执行默认映射到 SDK 的 `Sandbox.workspace_write` 或更严格的 `Sandbox.read_only`，且工作目录必须位于已校验 workspace 内。拒绝 `Sandbox.full_access`。
- 逐项验证现有 `sandbox`、`approval_policy`、`executable` 配置到 SDK 类型的映射；不认识的配置值启动失败。配置 migration 必须给出旧配置的确定转换或明确报错，不能静默忽略。
- 现有 `approval_policy: never` 不应直接解释为“用户已批准所有操作”。核实其对应 SDK approval mode 后，首期采用 deny/fail-closed 策略；不要把自动审查模式称为 QQ 用户的逐项批准。
- SDK 沙箱 preset 不自动授予天气搜索、任意网络访问、MCP 或 AstrBot 插件工具。此类 capability 不在本方案交付范围内。
- 日志只记录 execution id、executor id、thread/turn 状态、耗时、错误类型和清理结果；thread id 只进受限诊断日志，不写入用户可见正文。

## 8. 进度与最终输出

当前 `ExecutionProgressUpdate` 是非可见事实，外部结果桥也没有投递它。目标分为两层：

1. Executor Adapter 将 SDK 事件归一化为稳定、执行器无关的阶段事实。优先使用有限枚举，例如 `accepted`、`working`、`running_tests`、`completed`；自由文本必须经过 allowlist/长度限制。
2. Core result/progress bridge 仅把允许展示的简短状态交给 Output Controller 的既有 `core_progress` 边界；不由 SDK Adapter 直接向平台发消息。输出策略可选择合并、节流或关闭状态展示，且 progress 不能完成 turn、写入记忆或重复最终回复。

禁止透传：

- 推理/analysis 内容；
- 原始命令、参数、tool arguments、stdout/stderr；
- 未审核的逐 token assistant delta；
- 文件全文、敏感路径或凭据；
- SDK 原始通知/JSON-RPC payload。

Final result 仍只有一个 `ExecutionFinalUpdate`，经 Personal Core-final 表达和既有输出事务投递。取消、替换、超时后的迟到 delta/progress/final 全部丢弃。进度投递失败只记录可诊断失败并继续执行，不应让任务终止或吞掉最终结果。Native 原有 OLV 流式、语音、effect 和动作仍走 Native 专属输出 projection，不因抽象统一而退化为 Codex 的最终纯文本行为。

## 9. 分批实施与退出条件

每批单独形成可审阅改动，验证通过后再进入下一批。此方案不授权提交、部署或自动重启服务。

### S0：源码基线和 SDK 准入

范围：Codex SDK 文档/锁定版本、`pyproject.toml`、`uv.lock`、现有 Codex adapter/session/registry、Core lifecycle 和相关测试。

工作：

1. 逐项完成第 5.2 节的 SDK 公共 API 准入表，附最小 PoC 代码位置、SDK/runtime 精确版本和 Windows 运行证据。
2. 特别验证活动 turn 的 interrupt 是否到达 Codex runtime，而不只是取消本地 async task。
3. 记录开始 Codex runtime 数量、thread 数、同 thread 并行行为、关闭后的子进程状态。
4. 不改普通输出行为；本批若准入失败则停在设计决策，不做 SDK 替换。

退出条件：公开 API 覆盖所有 Core 必需行为，Windows 真实 smoke 可重复；SDK/runtime 版本固定且可由 lockfile 重装。

### S1：Core 统一运行入口收口

范围：`internal.py`、`proactive_agent_turn.py`、`executors/runtime.py`、`assembly.py`、Native adapter、result bridge。

工作：

1. 重新核对 R1-R7 和 C1-C6 哪些已在当前源码完成，哪些只是文档历史，不重复实现已完成项。
2. 将普通 Interaction 的 Native 主路径接入同一 Core coordinator/Head 运行和唯一终态管理。
3. 将 selector 收敛为 Core runtime 全局单值配置；旧的 per-bot executor 值迁移或冲突时报错，不得让不同 bot 同时选中不同内核。
4. 实现切换状态：停止旧内核的新 run 准入，等现有 run 按原 Head 完成或取消并清理后再切换；切换窗口按既有交互策略拒绝/延后 Core 委派，不迁移 in-flight run，也不增加无界队列。
5. 让 Native 保留必要的 Provider Hook、工具执行、流式文本/动作/音频投影；只合并执行身份、取消、deadline、终态、清理和结果归属，不强迫所有 Body 用同一输出形式。
6. 外部执行路径不得先创建闲置 Native Runner；Native Provider 没配置时 Codex Core 路径仍可使用。
7. OLV 现有协议与可见响应不变。

退出条件：普通交互与 Cron/主动任务共用 Core 执行生命周期；任一时刻只有一个全局 backend 接收新 run；切换前旧 run 已结算和清理；Codex SDK 可在切出后保持 idle；Native 与 Codex 选择均不复制 Head 终态、deadline 或结果结算逻辑；既有 Native OLV 行为通过回归验收。

### S2：Core-owned SDK runtime 和 Codex Adapter

范围：`core_lifecycle.py`、`executors/session_registry.py`、`assembly.py`、`codex_cli.py` 及依赖锁文件。

工作：

1. 新增 Core 生命周期管理的 Codex SDK runtime owner；按 executor/runtime 安全配置复用 `AsyncCodex`，不是按 thread 或 turn 创建 SDK client。
2. 将现有 Codex ExecutorRun 改为 SDK-backed Adapter，保留 SDK 无关的 `ExecutorRun` 公共契约和 `executor_id=codex_cli`。
3. 把 thread start/run、cancel、close 映射到 SDK 的公开 API；仅当启用同内核 thread continuity 时才要求 thread resume。run `aclose()` 不得关闭被其他 session 共享的 SDK runtime。
4. Core shutdown 时先停止/清理活动 turn，再关闭 SDK runtime；切换 selector 本身不能关闭共享 SDK runtime。关闭有界、幂等，不能遗留 runtime 子进程。
5. SDK 初始化或版本异常必须明确失败；不存在 CLI 子进程 per-turn、裸 subprocess fallback 或第二 transport。

退出条件：一个长期 runtime 可服务多个独立 thread；同 thread 串行；取消和关闭真实有效；现有 Codex 最终结果继续经过 Core result bridge。

### S3：同内核 thread continuity（可选）

范围：`ExternalExecutorSessionKey`、session registry、Core repository/数据库迁移、配置 fingerprint。

工作：

1. 此阶段只有在产品明确要求“同一个 Codex session 跨 turn/重启继续其私有 thread”时才实施；否则跳过，不阻塞 Core 内核切换。
2. 先审计现有 Core execution ledger/repository 是否适合作为 thread binding 的持久化 owner；不要把执行日志和 AstrBot 用户记忆/可见历史混为一体。
3. 实现第 6.3 节的最小映射 repository，事务性创建/更新/失效，不存秘密或原始对话 dump。
4. 将 executor identity、会话唯一键和 sandbox/config fingerprint 纳入 lookup；冲突、workspace 变化和迁移失败显式处理。
5. 若启用此能力，AstrBot 重启后恢复同一 Codex thread；失效时依照已声明的 per-engine reset policy 处理，并用当前 AstrBot context 初始化新 thread。
6. 加入受控的过期清理/显式 reset 策略，防止历史映射无限增长；删除映射不得误删 Codex 用户数据。

退出条件：仅在此可选能力启用时，证明同一 Codex session 可跨重启恢复且跨 bot/user/workspace 和权限配置隔离。跳过此阶段不影响 Native/Codex 切换完成。

### S4：安全进度与输出结算

范围：`contracts.py`、SDK Adapter、`executor_result_bridge.py`、必要的 Output Controller progress API。

工作：

1. 对 SDK event 建立固定 allowlist 到 Core progress stage 的映射；未知事件可记录类型并忽略，不能导致协议崩溃。
2. 为“内部阶段事实”和“可展示短状态”保留明确字段/转换，不能将任意 `summary` 原样作为用户消息。
3. 将可展示状态送入既有 `core_progress` Output Controller 边界；实现节流、相同状态合并、取消后抑制和投递失败隔离。
4. 增加唯一 final/update 所有权校验：final 只能一次；输出成功与 Core 执行完成状态分开。
5. Native 现有渐进输出路径与 Codex 受控阶段状态并存，不在 Codex Adapter 中生成 TTS/effect。

退出条件：运行中可以得到经策略过滤的执行阶段状态；final、progress、取消和替换交付各一次且归属正确；日志与用户消息不含隐藏推理和原始工具输出。

### S5：真实验收和旧路径收尾

复用并扩充 `execution-backend-acceptance-matrix.md`，覆盖：

- 多个 backend 都已注册，但只有 Core-wide 配置指定的 `active_executor_id` 获得新 run；
- Native -> Codex -> Native 切换；每次切换先 drain 旧 run，切换窗口没有新 backend run 与旧 backend run 并行；
- 切换后新 backend 收到当前 AstrBot context/memory snapshot，不导入上一 backend 的 transcript/thread；
- 两个 bot 使用同一个 Core-wide active backend；互相冲突的旧 per-bot selector 被明确拒绝；
- Codex 配置和 Native Provider 缺失时，Core 仍只启动/使用 Codex SDK backend；
- 同一 Codex backend 多轮同 thread（仅当启用 per-engine continuity），以及彼此隔离的 session；
- Codex 任务进程重启后从 AstrBot context 重新执行；恢复 Codex 私有 thread 属于可选验收；
- 长任务取消、deadline 超时、运行中替换及迟到结果抑制；
- SDK 初始化失败、runtime 意外退出、thread resume 失败（仅在启用同内核 continuity 时）；
- Windows SDK runtime 正常关闭与强制关闭，无子进程遗留；
- 不同 bot、user、workspace、CODEX_HOME 和 sandbox fingerprint 的隔离；
- progress 安全过滤、节流、失败时最终输出仍能完成；
- Cron/主动任务的执行完成与提醒 delivery receipt 分离；
- Native OLV 文本、TTS、动作/effect 和历史只写入一次；
- Live 场景中使用 Core executor 的路径（若配置启用），验证原有动作与输出 owner 不变。

通过门槛：

1. Core runtime 的 active selector 始终只有一个值；每个 run 只有一个 executor id，且只有 selector 指向的 backend 接收新 run。
2. backend 切换后，没有旧 backend 活动 run；未选中的 backend 可保持 idle runtime，但不能收到任务。切换窗口的准入行为可观察且有界。
3. 由 AstrBot 管理的记忆/上下文在切换前后保持唯一 canonical owner；不要求跨 backend 复制 thread/transcript。
4. Codex SDK runtime 第一次启动后，在其启用周期跨 turn 和 selector 切换复用，不因每个 turn 或每次切换反复创建。
5. 同一个 Core Head 只有一个终态，成功结果只交付一次。
6. SDK/runtime 失败不会静默切换 Native 或 raw app-server。
7. 取消与 shutdown 后没有活动 turn、无主后台任务或 Codex 子进程。
8. Native 默认用户行为和 OLV/Live 相关输出没有回归。
9. 真实 Windows 测试记录与 fake SDK 测试分开报告；mock 通过不等于子进程验收通过。

S5 完成后，仅在 SDK 准入通过、真实验收通过、代码审阅无未解决 P1/P2 后，才可把本方案状态改为“实施完成”。不能因为 Codex 最终文本能返回就宣布全链路解耦完成。

## 10. 开始实施前仍须记录的决策

以下决策不得由 Adapter 临时猜测：

1. 锁定使用哪个 `openai-codex` 稳定版本，以及该版本的公开 async streaming、interrupt API 是否通过 Windows 准入；resume API 仅在启用同内核 continuity 时纳入准入。
2. 全局 active selector 的配置 schema 位置，以及旧 per-bot selector 的迁移/冲突处理。
3. 切换 draining 时，新 Core 委派按哪一个现有交互策略等待或明确拒绝。
4. 是否需要 Codex 内部 thread 跨 turn/重启连续性；它不影响跨内核切换能力。
5. `approval_policy: never`、现有 sandbox 配置与 SDK approval/sandbox 类型的确定映射。
6. progress 的用户可见策略：允许哪些阶段，多久合并一次，以及是否在平台不支持编辑消息时发送独立短状态。
7. 是否将 Codex Desktop 历史 thread 的只读/恢复作为下一阶段。它不影响首期 Core-owned thread 交付。

## 11. 官方资料

- [Codex SDK 官方文档](https://developers.openai.com/codex/codex-sdk)：Python SDK 安装包、稳定发布、固定 runtime、AsyncCodex、thread 运行示例和 sandbox presets。
- [Codex app-server 官方文档](https://developers.openai.com/codex/app-server)：需要自定义处理 conversation history、approvals 和 streamed agent events 的客户端接口。
- [Core 内部执行器替换实施方案](internal-executor-replacement-plan.md)：架构 owner、既有 Core 契约及 R1-R8 完成口径。
- [Codex 长期 Core 执行器实施计划](codex-persistent-executor-implementation-plan.md)：已有 app-server 适配与 C1-C6 历史记录。
- [执行后端真实验收矩阵](execution-backend-acceptance-matrix.md)：Native/Codex 的 OLV、主动任务、Live 和结果归属验收基线。
