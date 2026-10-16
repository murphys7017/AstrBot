# OLV 非流式模式：问题总结与低延迟优化任务书

日期：2026-10-17。用途：独立指导普通模式优化，也供 6.1 SOL 执行时参考。状态：N0–N7 已按下文限定范围实施并逐项提交；真实对话性能和 Live2D 观感待现场验收。第 3 节统计仍是改动前基线，第 16 节记录实现与验证。

## 1. 目标和用户已确认的约束

目标是在保持现有回答质量、记忆语义、动作表现和普通模式可用性的前提下，缩短输入结束到第一声的等待，减少段间停顿。无需先完成全流式改造。

用户已明确：

- 暂不改动复杂的 Prompt 上下文系统结构；不重新设计 collector、上下文选择或记忆注入规则。
- 优先考虑麦克风开始输入时提前准备已有材料。文本输入检测暂不做。
- 记忆更新独立后台运行，Prompt 读取已有快照，可以是上一轮或更早的已发布记忆；不能新增“必须等本轮记忆更新”的屏障。
- 普通模式已经有较好的响应体感，必须保留并作为性能基线，不为了实现流式而强制迁移。

用户后续已授权在本会话实施，并要求“完成一项提交一项”。本轮按该授权修改和本地提交；服务重启和运行模式切换未执行。提交时 Live 仓库现有 post-commit 钩子自动同步 Adapter 源码到 AstrBot 插件目录，不代表运行中的进程已加载新代码。

## 2. 这里的“非流式”具体指什么

本文件沿用 08 文档的 M0 定义：Persona 先生成完整结构化结果，随后各段 TTS 和动作可以并行准备，再按顺序投递完整音频段。

因此 M0 不是所有处理都串行。不能把动作 Provider 的 `stream=True` 当成 Persona/TTS 全流式，也不能为了优化普通模式就引入 M2 的整套 PCM 传输。

当前主要链路：

```text
麦克风松手
  → 停止采集/结束队列/可选截图
  → audio_stream_end
  → 完整音频段 ASR
  → 正式 Turn、上下文及能力准备
  → Persona 完整结果
  → 各段 TTS 与动作并行准备
  → 等本段物料汇合后发送
  → 桌面设备准备和播放
  → 本段音频/动作结束后释放下一段
```

优化重点是提前准备和解除不必要依赖，而不是默认更换模型、减少回答内容或关闭动作。

## 3. 日志依据与测量口径

### 3.1 样本

本次总结使用 2026-10-17 02:02–02:16 的 13 轮已完成普通模式语音对话。统计窗口截止 02:16:20，不包含之后的未完成/新增请求。

来源：

- Core：`C:/Users/Administrator/Downloads/AstrBot/data/logs/astrbot.log`。
- 桌面：`C:/Users/Administrator/AppData/Roaming/ag99live-frontend/logs/ag99live/olv-latency-2026-10-16.jsonl`。文件名按 UTC 日期，内容含北京时间 10-17。
- 关联键使用 frontend Turn、Core Turn 及 segment index/message ID；一轮多次 playback 只取第一次作为首响。

这些是自然对话，不是同输入、同输出长度的严格 A/B。未修改配置，也未主动调用 Provider 生成测量请求。

### 3.2 已观察到的时间

| 指标 | 样本结果 | 正确解释 |
| --- | --- | --- |
| 松手到 audio_stream_end 发送附近的输入准备窗口 | 约 0.58–0.89 秒，中位数约 0.65 秒 | 包含停止/排队/可选截图等，不能全部算作截图时间 |
| ASR | 约 0.78–1.16 秒 | 转写阶段日志耗时 |
| Persona Provider | 中位数约 1.92 秒 | 模型请求耗时，不含全部前后准备 |
| Persona 总阶段 | 中位数约 2.89 秒 | 包含 Provider，不能与上一行相加 |
| persona_ms − provider_ms | 约 0.81–1.16 秒，中位数约 0.91 秒 | 未细分的非模型阶段开销，不等于全部是上下文构建 |
| Core 首输出指标 | 中位数约 4.28 秒 | 后端口径，不能当成用户听见声音 |
| 首段 TTS ready → 首段发送 | 约 0.011–1.218 秒，中位数约 0.203 秒 | 包含等待动作及物化/发送开销 |
| 首段发送 → 桌面 playback 回调 | 约 0.055–0.542 秒 | 包含传输、准备和启动，不等于单纯网络时间 |
| 麦克风松手 → 桌面首次 playback 回调 | 约 4.95–6.95 秒，中位数约 6.23 秒 | 同 renderer monotonic 字段计算，是软件事件，不是硬件录音测得的发声 |

用户观察到“约三秒”的体验作为独立产品反馈保留；不能直接用不同起点的六秒指标否定，也不能把 Persona 阶段三秒包装为完整首响。

capture 事件的 monotonic 在停止入口采集，epoch 在后续 end 发送后填写，两者不属于同一时点。这能提示输入准备窗口，但要靠独立事件进一步归因。未来增加 renderer instance/timeOrigin，禁止跨重载相减。

## 4. 优化项总表

| ID | 项目 | 证据级别 | 当前决定 |
| --- | --- | --- | --- |
| N0 | 补齐阶段观测、固定普通模式基线 | 已有指标口径不同 | 必须先做最小补充，不建新诊断系统 |
| N1 | 麦克风开始时提前准备已有材料 | 有明确触发信号；具体可前移耗时待量化 | 第一优先，先做窄切片 |
| N2 | 音频输出设备提前预热 | 源码存在冷启动约 350 ms 预热 | 第一优先，与 N1 共用触发但独立生命周期 |
| N3 | 输入结束与截图准备重叠 | 存在约 0.6–0.9 秒窗口及串行截图入口 | 先分项测量，再选择最小改动 |
| N4 | 语音发送不硬等动作结果 | 有日志及源码证据，单轮最多观察到约 1.22 秒等待 | 高价值，需完善后到动作契约 |
| N5 | 下一段语音不被上一段动作尾部过度阻塞 | 已观察大间隙；动作尾部是源码支持的嫌疑 | 先核实 actual motion end，再改调度 |
| N6 | 轻量能力摘要、schema 延迟物化/缓存 | 每轮完整快照 schema 约 0.25–0.33 秒 | 保留候选；当前不直接重构上下文体系 |
| N7 | TTS 连接与资源提前准备 | 存在可重叠机会，但普通文件 TTS 接口需单独追踪 | N1/N2 后评估，不套用 M2 bidi 的假设 |
| N8 | Provider、提示词、AudioWorklet 等大改 | 当前没有充分收益证据 | 暂不实施 |

## 5. N0：先建立能解释首响的时间线

复用现有诊断，记录以下里程碑即可，不按每帧输出大量日志：

```text
capture_start
capture_stop_requested
capture_runtime_stopped
audio_end_queue_ready
screenshot_start / screenshot_end（仅有截图时）
audio_end_sent
asr_start / asr_final
prepare_started / prepare_ready / prepare_adopted / prepare_discarded
persona_request / persona_result_ready
segment_tts_ready / segment_motion_ready
segment_sent
audio_prepare_start / audio_prepare_end
audio_started / audio_ended
motion_started / motion_ended
```

每条带当前可获得的 capture/Turn/segment 身份；还未建立 Core Turn 时不要伪造 `_turn_id`。明确 event time 与 recorded time，进程内用 monotonic，跨进程用关联 ID 和有误差说明的 epoch。

**验收：**一轮可以解释“松手后到底在等什么”；缺失字段标 unknown，不把所有未归因时间归给 Prompt 或网络。

## 6. N1：麦克风开始时提前准备材料

### 6.1 可做与不可做

可提前准备：已有 Persona/配置材料、同作用域记忆快照、可安全读取的历史材料及现有能力准备结果。实际哪些可抽出，先追踪依赖；不能把含当前用户输入的整个 context material 原样提前缓存。

不提前执行：缺失用户输入的正式 Prompt 请求、Persona 回答、TTS 文本合成、工具副作用、正式历史提交。

现有记忆路径是 `MemoryCollector → MemoryService.get_prompt_snapshot → local snapshot + RecallSnapshotManager.get_or_schedule`。已有缓存可直接使用，后台刷新独立进行。不因当前轮尚未结束而等记忆更新，也不改成按本轮 ASR 文本同步查询。

### 6.2 触发与所有权

- 先检查已有 `input.audio_stream_start` 接收入口，优先复用这个明确事件，不新增高频音频包监听。
- PTT 从本次开始采集触发一次；自动/VAD 常开模式应按实际 speech-start 或有效语音段定义触发，不能把麦克风设备常开当作用户每次开口。第一版若只支持 PTT，要明确范围。
- 准备工作归属 capture scope，不提前创建正式 Core Turn。只在输入提交后，把允许复用的材料交给本次正式 Turn。
- 先核对开始事件是否已经携带最终会话/用户/Persona/config 信息；缺失时仅准备不依赖这些值的资源，不猜当前用户。
- 每个有效采集只允许一份有界准备任务，设置生命周期上限并去重。取消、断连、切换会话时回收。

### 6.3 结果接纳

建议表达以下状态语义，具体实现复用现有结构，不要求新建通用框架：

```text
idle → preparing → ready → adopted
                 ↘ failed / cancelled / expired
ready → discarded（身份或配置不再匹配）
```

最终 ASR/输入确认后：

1. 校验用户、会话、Persona、权限、配置及连接代次。
2. 有效已就绪材料通过现有上下文入口复用。
3. 同一份必要准备仍在进行时，能安全接管就复用该任务，不能等待预取失败后再完整重做两遍。
4. 无效材料丢弃，正常入口按原有语义准备；预取失败不能使原本可用的普通回复失败。
5. 最终 Prompt 始终加入确认后的本轮输入，并执行原有组装/校验。

失效应区分两类：权限/会话/Persona 不匹配必须拒绝；记忆后台发布了新版本不等于旧快照不可用，继续遵守现有允许滞后的语义。正式对话历史需处理用户说话期间上一轮新增消息，不能与记忆缓存混为一谈。

### 6.4 实施停止线

如果为了前移准备，需要重写 collector 选择、Prompt 结构或 Memory 契约，则超出当前窄切片；先交付设备预热或可单独复用的材料，并记录受阻边界，不以“预取”为名重构整个上下文系统。

**验收：**说话期间任务已开始；正式输入使用正确材料；取消录音无残留；会话/权限切换不串数据；后台记忆慢不阻塞；预取未命中时普通模式仍正常。报告实际隐藏掉的等待及额外工作量，不把预取总耗时全算收益。

## 7. N2：音频设备提前预热

入口：Live `frontend/src/playback-timeline/speechOutputRuntime.ts` 及麦克风开始入口。

- 在麦克风开始/明确语音输入信号时调用可复用的输出准备能力。
- 预热不能调用会 dispose 当前 activeSession 的播放 attach 路径；正在播放的上一轮语音不能被准备下一轮中断。
- 处理 AudioContext resume、设备切换及空闲失效；避免每个输入包重做 350 ms primer。
- 预热不计为 audio_started，不产生假的播放回执。
- 复用现有输出图、设备和音量设置，不创建第二个 AudioContext/播放器来绕开所有权。

**验收：**冷启动设备准备与用户说话/ASR 重叠；热启动无重复预热；当前播放不被破坏。先区分需要 primer 的样本，不把所有 55–542 ms 都当成可消除成本。

## 8. N3：减少输入结束前的串行等待

入口：Live `frontend/src/adapter-connection/runtime/microphoneRuntime.ts::stopMicrophoneCapture` 及 `outbound/desktopCapture.js` 对应源码；Adapter `services/speech_service.py`。

当前截图发生在 end 队列里，截图完成后才发 audio_stream_end。先通过 N0 确认各阶段耗时，再二选一或渐进实施：

**方案 A：提前采集图像。** 在合理时点准备截图，发送时校验捕获时间和用户语义。不能把几秒前的画面冒充“此刻截图”；必要时仍刷新。

**方案 B：ASR 和截图并行。** 音频结束先触发转写，截图另行绑定到同一输入。最终输入 assembly 在必需视觉材料就绪后才交给 Persona，避免漏图。

B 涉及协议变更，需定义输入完整条件、图片到达期限、取消和身份关联，两端一起实现。不能只把 send 提前、让旧接收端永远看不到后到图片。

**验收：**视觉问题仍有正确图像；网络/截图失败沿原产品语义明确处理；ASR 确实提前开始。优先选择与收益匹配的最小方案。

## 9. N4：解除语音发送对动作生成的硬依赖

### 9.1 事实

02:16 样本 Core Turn `87683bd1979249ab8373aabf89ef4360`：

- 02:16:04.687：首段 TTS ready。
- 02:16:05.888：首段 motion result ready。
- 02:16:05.905：首段发送。

从 TTS ready 到发送约 1.218 秒。Core `output_controller.py::_deliver_ready_persona_segments` 在 yield 前调用 post-materialization contribution；Adapter `middleware/interaction_motion/scheduling.py` 的段 finalizer 会 await 本段动作 Future。

这属于当前原子段汇合设计，不是证明 TTS 算得慢。后段提前做好也不能跳过前段音频顺序。

### 9.2 改造方向

完整音频文件做好即可提交，动作通过同一段身份后续加入；因此可保持非流式 Persona/文件 TTS，但必须支持延迟动作，不是简单删除 await。

必须定义：

- pending 动作与 absent/failed 不同；音频先发时不能提前永久标成 absent。
- 后到动作归属稳定的 segment_message_id，不按到达顺序猜测。
- 动作若在音频播放中到达，按合法时间锚点加入；不能重复播放旧 payload。
- 无音频、音频失败、动作超时/迟到各有明确结算。
- 动作过期只影响可选动作，不无限阻塞 Turn，也不取消所有动作来伪装提速。
- 复用既有时间线与动作执行器。是否复用现有 motion stream 协议须先检查“同 Turn 不混用交付模式”的约束，不能给 M0 偷塞 M2 事件导致消费者拒绝。

**验收：**制造/观察动作比 TTS 慢的正常输入，音频先开始且后到动作有效；没有重复字幕/声音；纯动作和取消仍结束。收益上限不能直接照搬单个 1.218 秒样本，要统计动作确实慢于 TTS 的比例。

## 10. N5：核实并减少动作尾部造成的段间空隙

已观察样本：02:12 的相邻段额外间隙约 1.10/0.51 秒；02:13 的一处约 1.87 秒。按前段声明音频时长与下一段播放开始时间差估算，其他多数间隙只有几十毫秒。

这些后段已提前发送。源码 `playbackTimelineRuntime.ts::findPlaybackReleaseBlockers` 要求必需 sink 终态，包括 motion；`useTurnPlaybackOrchestrator` 在 blocker 存在时不释放下一段。

目前动作尾部是可信嫌疑，还没有各样本的 actual motion end 来完成因果证明。需要同时排查播放器准备、音频实际结束回调和任务调度。

若确认动作尾部是原因，设计上允许下一段语音按音频顺序接续；动作按其参数控制权、剩余时长和意图决定衔接/融合/截断。不能直接删全局 blocker 后允许多个动作无规则抢写参数。

**验收：**后段音频已就绪时没有无依据的长空隙；动作自然衔接；确有语义停顿的情况保留；记录实际 audio end/motion end/release，不只比较估算 duration。

## 11. N6：能力摘要开销，先保留候选

现有 `execution_capability_summary.py::resolve_core_execution_capability_summary` 为 Persona 委派判断调用完整 `CapabilityResolver.resolve`。日志多次出现 57 个工具，schema 阶段约 0.25–0.33 秒。

`CapabilitySnapshot.__post_init__` 会调用 `_serialize_tool` 生成 schema，但摘要随后主要读取 semantic capability bindings。候选优化是同一套准入结果的轻量投影、静态 schema 缓存或真正执行时延迟物化。

当前优先遵循用户“不改上下文结构”：先看这部分能否在 N1 中安全提前准备，不立即拆整个 resolver。只有数据证明仍是瓶颈且用户后续允许，再独立实施。

权限、插件状态、Persona 工具白名单仍需正确更新。禁止通过绕过准入或永远缓存可用工具列表来省时间；本轮无 Core 执行不代表以后都不需要它。

## 12. 暂缓项与不建议的做法

- **AudioWorklet：**当前主要等待在上游及动作汇合；文件音频播放没有证据显示必须更换消费架构。先不做。
- **重写 Prompt/Memory：**现有读取不等后台更新，不能将非模型约一秒都归因于记忆。先不做。
- **更换模型、减少上下文、缩短回答：**会改变质量和对照条件，不作为本轮结构优化的默认动作。
- **提高所有并发数：**可能竞争连接、GPU 或 Provider 配额；已有 TTS/动作并行，不能无测量地继续加。
- **TTS 连接复用：**普通模式走文件合成，必须追踪其实际 Provider 方法；不能依据 M2 的 MiniMax bidi 实现声称 M0 一定每轮同样握手或支持复用。
- **文本输入预取、预测意图：**按用户选择暂不做。
- **麦克风开始就生成一句“好的”：**不是材料预热，也不是有效首响优化。

## 13. 推荐实施批次与边界

| 批次 | 内容 | 交付条件 |
| --- | --- | --- |
| A | N0 + N1 最小可复用材料 + N2 | 普通模式行为保持，准备前移有证据，取消/切换正确 |
| B | N3 | 输入准备分项已测量，ASR 与图像准备按合法契约重叠 |
| C | N4 | 音频可先于动作发送，后到动作仍正常，不改成全流式 Persona |
| D | N5 | 原因先确证，再改善段间连续性 |
| 后续候选 | N6/N7 | 按实际剩余瓶颈及用户后续范围决定 |

N4 价值高但协议风险高，不要求在 A 完成前一起实现。A 若无法无侵入地提前准备某类材料，先交付能做的准备，明确未覆盖项，不偷偷扩大到上下文重构。

## 14. 验收与报告

固定模型、音色、Persona、截图设置及可比输入，分别记录冷/热设备。普通 M0 为基线，不混入 M1 fallback 或 M2。

最小场景：正常短回复、两段回复、取消录音、会话/Persona 切换、上一轮仍在播放、背景记忆更新慢、需要截图的问题、动作慢于 TTS。按当前批次选择相关公开边界验证，不为清单每行创建大套 mock 测试。

报告至少包含：

1. 实际改了什么，仍保持什么模式。
2. 输入到首声各阶段的可比时间、样本数和失败数。
3. 预取命中/丢弃/取消数量，是否重复工作。
4. 动作成功率、段间空隙、取消响应有没有退化。
5. 源码/边界/真实设备分别验证到哪里。
6. 未提交用户修改是否保留，部署与运行版本是否一致。

先证明优化减少了实际关键路径等待，再讨论固定秒数目标；不把单轮体感或 Provider 单独测速当作全链路提升。

## 15. 给执行者的启动说明

> 优先阅读本文件第 16 节的实施记录及两仓库 AGENTS.md/.ai/index.md。保持普通 M0 模式，不改 Prompt/Memory 的结构或读取语义，不等待后台记忆更新。保留用户工作区改动，按用户“完成一项提交一项”的授权逐项提交。必要检查以相关静态检查、最小公开边界及真实日志为准，不能把模拟验证称作现场完成。先核对已实现的资源准备、v6 后到动作和动作交接，避免重复造实现；后续根据新日志调整，不把候选收益当成已经实现的秒数。

关联资料：[全流式主任务书](08-olv-full-streaming-execution-plan.md)、[实施细则](09-olv-implementation-playbook.md)、[早期两轮现场证据](10-olv-runtime-evidence-2026-10-17.md)。本文件新增的 13 轮统计不能与早期两轮表混作同一个样本集。

## 16. 2026-10-17 本会话实施记录

### 16.1 实际交付与提交

Core 仓库：`C:/Users/Administrator/Downloads/AstrBot`；Live 仓库：`C:/Users/Administrator/Documents/GitHub/AG99live`。提交均为本地提交，未推送。

| 项目 | 实际实现与边界 | 仓库 / 提交 |
| --- | --- | --- |
| N0 | 新增输入停止、队列、截图、发送、音频准备/起止里程碑；白名单 IPC 只记录身份和时间。带 renderer timeOrigin，区分 streamId 与 messageId。后端继续复用 ASR/Persona/TTS 现有计时。动作计时在 N5 中补上。 | Live `92c376b`；N5 的 `cf6bed2` 补齐动作事件 |
| N1 | PTT 音频流开始和 VAD speech-start 启动一个有界准备任务；使用真实 Adapter 身份和严格配置路由，初始化 Memory 服务并提前触发现有召回缓存读取/异步刷新。结束、替换、断连时取消。 | Live `10e6dcd` |
| N2 | 同一输出图新增 `prepare()`，麦克风首个有效音频包触发；进行中的准备共享，冷设备预热结束后记活动时间，热设备不重复 primer。预热不调用 attach、不释放当前播放。播放前继续复核设备状态。 | Live `355ce34` |
| N3 | 在松手时立即采集此刻截图，与设备停止和已有 end 队列等待重叠；图片仍放在原 audio_stream_end 中原子提交。 | Live `667e91b` |
| N4 | 文件音频可声明 `motion=pending` 并先发送；同段动作通过 `output.segment_motion` 后到。后端按原动作预算有界等待，发完终态结果再关闭 synth；桌面以稳定 Turn/message 身份接入正在运行的原音频时间线。 | Live `4b76b5c` |
| N4 复核修正 | 真实桌面的 speech-only 动作准入排除 pending，防止占用后到动作槽位。此问题是沿应用装配链复核发现，最初的局部时间线检查不覆盖它。 | Live `daf0041` |
| N5 | 同 Turn 后段音频已就绪、前段音频实际结束时，通过 ModelEngine 结束旧动作尾部，按正常交接结算，再释放下一段。保留纯动作和最后一段尾部。过了语音窗口的未生成动作明确过期。 | Live `cf6bed2` |
| N6 | 能力摘要向同一个 resolver 请求 admission-only 快照，完整执行相同准入检查，但不生成无用 schema；实际执行快照保持原有即时序列化。元数据快照若被误用于完整 inventory 序列化会显式拒绝。 | Core `dffae9430` |
| N7 | 确认普通 MiniMax 文件 TTS 每次创建 HTTP session 后，改为 Provider 持有惰性会话/连接池，终止时关闭，转发已有代理设置。没有发送额外预热合成请求。 | Core `e2ad65a09` |

N1 是**现有 Memory 资源/召回缓存预热**，不是把整个 Prompt 提前构造并跨事件移交。正式 collector 仍读取当前身份、配置、会话和本地状态，只通过 Memory 已有缓存键复用召回结果；不另建跨会话快照池。它可能增加一次本地读取，收益取决于真实缓存命中和冷启动占比。Persona、工具准入和正式历史没有按录音开始时的状态冻结。任务书 6.3 的完整材料接纳状态机并未作为通用框架实现。

N3 没有实施分离音频结束与图片到达的协议方案 B，ASR 仍在完整 end 信封之后开始。此次只消除截图与设备停止/排队之间可重叠的等待，截图本身的耗时仍存在。

N5 采用明确的动作尾部交接策略，复用现有停止语义；没有实现新的动作融合引擎。它解除一个已确认的架构等待机制，不能据此宣布此前 1.87 秒样本的原因已经现场证明，或视觉衔接已经验证。

N8 及第 12 节明确暂缓项保持暂缓：AudioWorklet、模型/提示词更换、文本输入预测、整个上下文系统重写不在本轮交付中。

### 16.2 关键代码入口

- Live：`services/input_preparation.py`、`platform_adapter.py`、`runtime/turn_coordinator.py`（上述路径相对 Adapter 插件目录）。
- Live：`frontend/src/playback-timeline/speechOutputRuntime.ts` 与 `frontend/src/adapter-connection/runtime/microphoneRuntime.ts`。
- Live：Adapter `middleware/interaction_motion/scheduling.py`、`runtime/deferred_motion.py`、`runtime/output_segment_coordinator.py`。
- Live：`frontend/src/adapter-connection/inbound/deferredMotionProtocol.ts`、`frontend/src/turn-playback/useTurnPlaybackSessionStore.ts`、`useTurnPlaybackOrchestrator.ts`、`frontend/src/app/usePetDesktopRuntime.ts`。
- Live：`frontend/src/playback-timeline/playbackTimelineRuntime.ts`、`frontend/src/playback-integrations/modelEngineMotionSink.ts`。
- Core：`astrbot/core/capabilities.py`、`astrbot/core/interaction/execution_capability_summary.py`、`astrbot/core/provider/sources/minimax_tts_api_source.py`。

### 16.3 协议与生命周期

`output.segment` schema 从 v5 升为 v6。普通文件音频的 motion 槽位新增 `{state:"pending"}`；后到 `output.segment_motion` 带同一 turn_id/message_id、v6 schema 和一次终态 motion 槽位，不重新发送文字/音频。

这不是 M2 增量段，不能混用 PCM 流注册。pending 必须配文件音频，重复/身份错误的结果会拒绝；已经取消的 Turn 不恢复播放；音频结束后的动作只结算、不重播。后端先等后到动作发送结束，再发送 synth_finished，避免把未解析状态隐式改成 absent。断线或 Turn 清理同时取消挂起的后到任务。

两端 manifest 必须匹配。旧版桌面与新版 Adapter 会在握手拒绝，需要让桌面和后端加载同一批版本后重连。现有提交钩子只同步插件文件，不会重启服务。Electron 完整构建产物已生成在 Live `frontend/out`，不代表运行中的桌面已经换成它。

### 16.4 已完成的验证

- Electron 完整 `npm run build` 成功，包含 renderer、WebSDK 和 node 三类类型检查及主进程/preload/renderer 构建；AstrBot 控制页构建也成功。
- 新增/修改的 Python 文件通过针对性的 Ruff/AST 检查，协议 manifest 一致性检查通过。
- Adapter 插件结构检查为 0 error、0 warning；两仓库 state YAML 无重复键，Core 最小 AI runtime 检查通过。
- 能力摘要的两个公开边界检查通过：配置隔离；完整/轻量快照的选择、排除、语义能力绑定一致，轻量快照拒绝完整 inventory 序列化。
- Memory 准备检查覆盖一次读取调度、去重和执行前取消；没有调用真实记忆模型或 Persona，不能当成现场命中收益证据。
- 输出预热公开边界检查覆盖共享冷准备、热复用、当前播放不被释放、终止后拒绝。
- MiniMax 文件 TTS 用真实本机 HTTP 服务连续请求两次：复用同一 transport，WAV 字节一致，终止后拒绝新请求。没有调用外部 MiniMax 服务。
- 后到动作使用真实本机 WebSocket 检查发送次序和取消；桌面 Store/规范化器/实际 Timeline/Orchestrator 边界验证音频先释放、后到动作不重播音频、重复结果拒绝，以及下一段在真实音频终态后交接旧动作。
- IPC 事件白名单和既有独立时间线尾部阻塞检查通过。

验证限制：通用测试编译入口带入了无关 SDK 类型错误，改用最小相关测试编译；正式三类类型检查和构建已通过。插件目录的 py_compile 曾遇到本地 pycache 写权限错误，使用 AST 检查补充。没有用更多模拟测试替代真实设备验收。

另曾将 Core 的通用 AI runtime 验证器用于 Live；它要求 task/context/checks_run/validation_gap 字段，而 Live 原有 state 为独立任务记录格式，因此报告四项缺失。此次保留 Live 现有治理格式，只做 YAML 结构检查，未将这个不匹配检查写成“通过”。完整构建与该治理格式检查是两件事。最终构建及该限制另记录在 Live `15c174d`。

### 16.5 后续现场验收

1. 确认两端加载新版本后，保持原模型、音色、Persona、截图开关和普通 M0 模式，进行可比短回复/两段回复。
2. 观察预热是否在说话期间完成，音频准备阶段是否省去冷 primer；记录 Memory cache 实际复用而非推断整个 Prompt 准备耗时都被隐藏。
3. 对照 `segment_tts_ready`、`output_segment_sent` 与 `pipeline_stage`，确认 motion=pending 的首段发送确实早于对应动作结果；核对后到动作仍播放。
4. 对照 audio_ended、motion_ended、motion_handoff 和下一段 audio_started，确认长空隙的实际原因以及交接策略效果。
5. 人工检查 Live2D 交接观感，尤其多段回复、很短音频、动作迟到、取消录音、上一轮仍播放及会话/Persona 切换。

在这些现场数据产生前，不报告“整体减少了几秒”“所有问题已在运行中修复”或具体性能达标比例。
