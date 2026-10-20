# Prompt 文本与系统审阅（2026-10-20）

审阅基线：AstrBot `ee38dfadc`。先完成源码、配置、确定性渲染与测试审阅，随后落实第一批四项局部修复，并按用户要求复核、提交本批变更。没有修改运行中的人格或数据库，没有真实模型联调或重启。以下问题描述保留审阅时证据；完成状态以本节为准，不能把所有建议视为已实现。

## 第一批实施状态

| 项目 | 当前改动 | 验证与边界 |
|---|---|---|
| A1 确认语遗漏 | Layout 写入 `user_input/previous_persona_acknowledgement`，Base/OpenAI/Anthropic 显式编译为输入数据；MiniMax 通过既有 framework state JSON 自动携带，无须重复插入 | 四种 renderer 经 request apply 后确认语恰好出现一次；空值与无 slot 输出相同，原 Pack 不变 |
| A2 历史配置覆盖 | TURN_PLAN、OLV_STREAM、FINAL_RESULT 不再声明固定轮数或虚假的轮数限制原因，沿用 Profile 配置候选窗口 | 真实最终请求验证 0/1/50/300 配置；PROACTIVE 仍固定 2 轮；3000/1800 token 预算、近期压缩与旧锚点选择策略保留 |
| A3 轴分类丢失 | 原始 Profile 摘要保留 semantic_group；独立动作最终能力文本同时保留 semantic_group 和 control_role | 合成合法原始 Profile → 摘要 → capability → 独立动作 Prompt，head/body/gaze 分类与角色均保留，源 Profile 不变 |
| A4 时长契约歧义 | 独立动作明确 duration_weight 为整数、相对权重而非秒/毫秒；步数与权重上下界在 normalizer、effect schema、参考投影、能力限制文本、调参样本验证和 Prompt 共用常量 | 经当前参考投影进入最终 Prompt 的两步示例同时通过真实 normalizer 与动态 schema；拒绝小数、布尔值、非法步数，保留既有越界饱和策略 |

本批不自动追加新的两步示例；使用既有参考投影验证真实契约。是否按动作请求选择并补齐示例，留到 A5 的契约文本优化一起评估，避免每次请求无条件增加示例长度。

验证：`tests/unit/test_prompt_targets.py` **49 passed**（新增 16 项公开最终请求输入输出回归检查）；渲染器和请求适配相关测试 **66 passed、1 deselected**（排除审阅已确认的旧 Persona 诊断字段断言）。插件真实导入、Profile 到最终能力文本、schema/normalizer 的直接验收通过，修改文件 Ruff 和插件结构检查通过。原审阅的 10 项基线失败未在本批修复，不作为已通过项。

提交范围：下列六个源文件原本被根目录 `.gitignore` 的 `data` 规则排除。本次按用户授权显式加入版本控制，保留既有内容及本批局部修复，未修改全局忽略规则；因此提交统计包含这些文件的完整现有快照：

- `data/plugins/astrbot_plugin_ag99live_adapter/middleware/interaction_motion/prompt_context.py`
- `data/plugins/astrbot_plugin_ag99live_adapter/middleware/interaction_motion/prompt_builder.py`
- `data/plugins/astrbot_plugin_ag99live_adapter/middleware/interaction_motion/prompt_references.py`
- `data/plugins/astrbot_plugin_ag99live_adapter/middleware/interaction_motion/effects.py`
- `data/plugins/astrbot_plugin_ag99live_adapter/motion/motion_intent.py`
- `data/plugins/astrbot_plugin_ag99live_adapter/runtime/motion_state/tuning_store.py`

提交前复核又补齐能力文本和调参样本中的步数/权重常量引用。通过公开 `MotionTuningStore.normalize_sample()` → `refresh_reference_examples()` → `normalize_motion_steps()` 的直接验收，确认合法序列可投影、非法步数和权重被拒绝，原始样本不变。首个验收输入缺必需的 `original_axes`，补齐合法输入后通过，未为此放宽生产校验。本批沿用上述 115 项已通过检查；没有重复运行未变更的测试套件。旧插件其他未跟踪依赖仍沿用现有本地安装，本提交不声称提供可独立安装的完整插件包。

A5–A8、稳定能力缓存与协议实验仍待实施。实际模型成功率、桌面动作质量和端到端延迟需要后续真实联调验证。

## 判断

可以优化，优先解决事实进入最终请求的完整性、配置语义和输出协议一致性，再减少重复文本与重复构建。当前主架构有明确的事实源、投影和渲染边界，应保留。不能只按 Prompt 字符数评价效果，也不能靠缩短历史来宣称等价加速。

不改记忆更新机制，不要求它等待当前轮；读取快照与后台记忆更新仍是两件事。不修改用户人格，不取消 actions、thought、tendency，不改变当前 JSONL 协议。

## 当前链路与职责

```text
输入、人格、Conversation、Memory 快照、插件事实
  → Context Collectors
  → PromptContextBuilder / 派生 ContextPack
  → PromptContextView（本次阶段能看哪些事实）
  → PromptTarget（模型角色的可见边界与预算）
  → PromptRenderProfile（阶段指令、输出契约）
  → Layout / PromptTree
  → Base / OpenAI / Anthropic / MiniMax Renderer
  → ProviderRequestAdapter
  → lifecycle hooks / agent runner / Provider
```

| 消费者 | 文本与入口 | 必须保留的边界 |
|---|---|---|
| Persona 即时回复 | `interaction/expression_agent.py`：runtime system、阶段 request、JSON/XML/Markdown/tool/JSONL 输出 | 人格表达、reply/delegate、动作意图和情绪 |
| Persona 结果改写 | 同一入口，`source_text`、`immediate_reply` | 已确认结果不被历史或人格能力声明覆盖 |
| Persona 进度 / 主动表达 | progress / proactive View | 不把单个工具结束当成整轮完成；避免重复发言 |
| Core Planner | `interaction/core_planner.py` | 已委派后只整理执行规格，不再重新路由 |
| Core 执行 | `prompt/resources.py`、system/policy/tool/skill collectors | 实际工具能力、结果真实性、执行历史 |
| Personal Policy | `interaction/personal_policy.py` | 只决策是否主动表达，不生成最终台词 |
| AG99live Persona effect | `middleware/interaction_motion/prompt.py`、`prompt_builder.py`、`effects.py` | 每段 effect 绑定、合法轴等级与资源 |
| AG99live 独立动作 | `middleware/interaction_motion/independent.py` | 消费本段 speech/actions/tendency，产出动作参数 |
| AG99live 预动作 / 被动动作 / 表演节奏 | `prompts/pre_action.py`、`passive_behavior.py`、`performance_curve.py` | 职责不同，不应合并成一段通用 Prompt |

## 确认的问题与优先级

### P2 / A1：进度表达的已发送确认语在渲染时丢失

- `interaction/collectors.py` 收集 `input.previous_persona_acknowledgement`，PROGRESS View 也允许它。
- `render/interfaces.py::render_input_context` 没有消费这个 slot；`_compile_user_input_message` 也没有对应输出。
- 合成 Pack 经真实 `PromptRenderEngine.render()` 后，Base、Anthropic、MiniMax 都表现为 selected=true、最终请求 marker=false。合法 mapping 形式的人格摘要则正常进入输出，不能把它误判为同类缺陷。
- 影响：本来用于避免重复确认、维持同轮连续性的事实没有到模型；仅检查 selected slot 的日志会误导诊断。
- 修复：在 Layout 中明确落位，在 user content 编译中明确输出，保持数据身份与原 Pack 不变；不通过重新注入全部历史补救。
- 验收：带唯一确认语的 progress Pack，经四种 renderer 和 request apply 后都能在实际 messages 中找到一次；不改写源 Pack 或历史事实。MiniMax 沿用 `_no_save` framework state。

### P2 / A2：View 固定窗口覆盖用户 Persona 历史配置

- `expression_agent.py:3600` 读取 `persona_history_window_size`；`render/engine.py:78` 随后直接用 View 值覆盖。
- `context_views.py` 给 TURN_PLAN、FINAL_RESULT 固定 6 轮，OLV_STREAM 固定 3 轮；因此配置并非实际生效的候选上限。
- 使用 12 个短回合、配置分别为 0、1、50、300，真实 render 的 TURN_PLAN 一律 retained=6，OLV_STREAM 一律 retained=3。该问题包括向上扩大 0/1 的配置，不能只理解为减少大窗口。
- 当前本地配置存在 50、300、500 等值；这只证明磁盘配置与代码存在冲突，不证明当前会话具体使用哪个 profile。
- `docs/zh/use/astrbot-config.md` 把该设置定义为历史候选池；`dev/multimodal-turn-context-plan.md` 明确禁止直接表达用固定小窗口覆盖配置。
- 修复：声明候选池上限、近期连续历史、相关旧锚点、输入 token 预算四者的关系。普通与 OLV 的传输方式不应自行改变人格事实语义。progress/proactive 的明确轻量 View 单独处理。
- 验收：配置 0/1 不被扩大；长候选池保留预算内相关锚点；同一输入在两条响应链路的差异有显式策略与诊断；遵守现有记忆快照语义。

### P2 / A3：动作指令引用的 semantic_group 在前置投影中丢失

- `prompt_builder.py::_build_motion_decision_contract_text` 要求优先使用 primary 且 semantic_group=head/body/gaze 的轴。
- `_build_motion_capability_prompt_payload` 本身允许 semantic_group；但 `prompt_context.py::_summarize_semantic_profile` 构造 prompt_axes 时没有拷贝 semantic_group。
- 因而正常能力构建路径里，指令让模型依据它没有拿到的分类选轴。只单测末端 capability 函数会漏掉此问题。
- 修复：从实际 Profile 保留该合法语义字段，或移除无事实支撑的分类要求；不让模型凭 ID 猜测组别。
- 验收：从包含不同 group 的原始 Profile 走到最终能力文本，分类仍可见；不暴露 Live2D 原始参数或内部资源路径。

### P2 / A4：独立动作 Prompt 没明确 duration_weight 必须为整数

- `independent.py:1736` 写“1 到 3 的 duration_weight”，没有写整数；同文件的最小 JSON 形状示例只展示单姿态或资源，不一定提供 sequence 实例。
- `motion_intent.py::normalize_motion_steps` 拒绝范围内的 1.5；动态 effect schema 则已经明确 integer。
- 对源码中真实 normalization 函数作隔离调用：1 和 2 接受，1.5 返回 `motion_step_duration_weight_invalid:0`。这证明契约拒绝，不证明实际模型一定生成了小数。
- 修复：统一写“整数 1、2、3；表示相对时长权重，不是秒或毫秒”。展示从当前合法轴生成的完整两步示例。
- 验收：生成示例送真实 normalizer 通过；不得复用固定、不属于当前模型的轴；保持稀疏轴保持语义。

### P2 / A5：非流式 JSON 同时承载规则、完整示例和完整 schema

- `_prepare_render_result` 先把格式说明和 `build_persona_text_example` 拼进 system。
- Renderer 又由 OutputContract 生成完整 schema fallback，追加到 system。共享 actions/thought/tendency 描述再次出现在 schema 中。
- Base/Anthropic 的 XML 外壳还会把示例中的引号、尖括号进行转义；这未必造成失败，但会增加模型理解示例的间接步骤。不能简单全局关闭转义。
- 合成无人格、无历史、无记忆请求的尺寸如下。为测量采用生产函数，示例 schema 使用函数默认允许动作；不同阶段枚举和实际扩展会改变长度。数值是字符数，不是 token，不是线上耗时。

| 输出格式 | 最终 system 字符 | 最终 request 字符 | 其中 schema fallback 字符 |
|---|---:|---:|---:|
| JSON | 4,926 | 400 | 2,860 |
| XML | 2,376 | 400 | 0 |
| Markdown | 1,979 | 400 | 0 |
| segment_stream_v1 | 1,117 | 1,506 | 0 |

- 修复：为每种传输选唯一的契约表达源。Prompt-only JSON 可由统一 schema 生成紧凑约束和一个合法实例；原生工具路径优先使用实际 schema，不再拷贝整套同义文字。
- 必须保留：必填字段、允许 turn_action、8 维情绪 0–10 整数、actions 方向性和同时/先后关系、thought 隔离、effect 通道规则。
- 验收：修改前后合法字段集合与解析规则一致，非法输入仍被拒绝；字符/token 有确切对比；格式成功率与语义质量经过模型样本验证后才能认定可上线。

### P2 / A6：动态事实混入 system，且各 renderer 布局不一致

- `independent.py::_build_independent_system_prompt` 把 `_motion_guidance_for_prompt` 产生的最近执行动作放进 system；随回合/分段变化的动作历史会改变 system 的后部。
- 对同一 PERSONAL_POLICY Pack 实际渲染：Base/Anthropic 把 runtime.observation_batch 放入 system，MiniMax 放入 user messages。观察事实本身未丢失，但物理布局和指令层级不同。
- 这是可定位的布局差异和缓存优化候选，不应把它写成已测得缓存失效或某个百分比的提速。服务端是否命中还取决于具体 Provider、模型和请求前缀。
- 修复：稳定职责、协议、Profile 能力与稳定示例在静态前部；本轮输入、最近动作、NeuroBrain 状态、ObservationBatch、阶段材料在显式动态数据块。先定义跨 renderer 的语义等价规则，再处理物理布局。
- 缓存应按 Profile revision、模型/renderer、协议、人格版本等明确失效；禁止跨轮缓存当前 memory/history 或把不同会话混用。
- 验收：只改变 runtime 后稳定指令部分逐字不变；事实仍可见且不被当指令；实际 Provider 回传缓存 usage 时才统计命中收益。

### P2 / A7：表达与 effect 双通道的文本要求存在冲突，纠正请求还保留旧指令

- 非流式 JSON 格式提示要求“只输出一个完整 JSON”，适用 effect 的共同提示又要求同一响应独立调用 persona_effect_batch；表达对象禁止内嵌 effect。这是需要明确限定作用域的要求。
- 缺通道纠正路径复制旧请求，追加“只补 effect”或“只补表达”，但 system 中原来的“双通道都必须输出”仍存在。
- 不把双通道设计本身视为已证实 bug。它是既有协议，当前纠正逻辑也有处理；但模糊指令和额外模型调用会增加失败/延迟风险，需要单独度量。
- 第一阶段：明确“普通文本通道仅包含表达 JSON；effect 走独立工具”，纠正 Profile 从同一规则源生成，只要求缺失通道，避免反复追加补丁式指令。
- 暂缓方案：改成统一工具对象或全量单 JSON，需要版本、Provider 能力和插件绑定设计，不能在一次文案精简里偷偷修改。
- 验收：双通道都齐全；缺表达/缺 effect 纠正不重新执行业务工具，不重复下发动作，不改变 segment_index；记录纠正率和额外调用耗时。

### P2 / A8：Prompt 测试基线不能直接作为当前质量门禁

- 实施前审阅选定五个文件共 199 项：189 passed、10 failed。不是完整测试套件，也不是实机效果评分。
- 10 项在隔离数据根目录后单独复跑仍失败：1 项期望 Persona 保留已被主动清理的 user_id/platform/umo 等诊断；2 项 stream fixture 的 run_context 缺 context；另 7 项涉及 mock 工具响应缺 tool_call ID，被现有 runner 提前拒绝，掩盖 hook/回退等原测试目标。
- 这些失败在本批修改生产代码之前已存在；其中 7 项的第一失败点是 mock ID 缺失，不能据此宣布补 ID 后所有后续断言都正确。
- 初次测试写到了正在使用的日志路径，引发 trace 文件轮转 PermissionError；随后改用 `.tmp/prompt-audit` 隔离根目录复跑，仍得到相同 10 项失败。系统临时目录尝试则因路径权限而没有成功收集测试。
- 修复：调整 fixture 使其符合当前公开输入契约，保留原目标断言；过时字段预期按目标投影规则更新。不要为让旧 mock 通过而关闭生产 tool-call 校验。
- 新验证集中在最终 ProviderRequest / 公开渲染边界，不能只证明某个内部函数被调用或 selected_slot_names 含某项。

## 其他可以加速的设计，尚未测得收益

1. **稳定能力编译结果复用。** 同一 Profile revision 的轴能力、合法资源、契约和静态例子可复用；本轮输入、历史、最近动作、memory 仍动态读取。先看现有 per-event 缓存和 revision 变化，避免第二套全局缓存。
2. **只读投影减少重复深拷贝。** Builder、目标投影、Profile、request apply 多次复制。先记录阶段 p50/p95、大小与分段数；收益足够再采用不可变基础事实加局部覆盖。直接删除 deepcopy 会破坏隔离，不可作为机械优化。
3. **减少首个 speech 前的必要输出。** v1 JSONL 必须先输出 header、segment_start、actions 与八维 tendency，再到 speech_delta。首 token 不等于首个可播文本；应统计这段结构的 token/耗时。若改协议，必须另做 v2、能力协商、默认情绪语义和兼容适配，不能把 v1 字段静默改为可选。
4. **按阶段编译指令。** 当前 progress/proactive 也沿用较完整的 Persona runtime 规则。可以由同一规则目录选择当前实际适用的段落，不把路由、结果改写、动作参数等不适用说明塞入每次请求。不能截断人格或删真实性边界换取短文本。
5. **减少纯诊断数据。** 表演节奏 Prompt 包含 turn_id/message_id，二者只用于追踪，不参与曲线判断；可留在 metadata。类似字段要逐项登记，不能递归删除用户结果里的 ID。
6. **约束驱动示例选择。** 显式动作请求展示相关、合法的稀疏轴示例；普通闲聊不必携带多组 sequence。例子优先级和预算应确定，不为此再调用一个 LLM 做选择。
7. **按真实端到端目标评估。** 格式成功率、重复发言、事实保真、方向动作完成、首可播文本 p50/p95、首声 p50/p95、总 token、纠正率共同评估。没有线上/离线 Provider 样本前，不承诺节省秒数。

## 实施顺序与回滚

| 批次 | 内容 | 前置验收 | 回滚单位 |
|---|---|---|---|
| 1 | A1 丢确认语、A2 历史配置语义、A3 轴分类、A4 整数契约 | 实际最终请求/normalizer 边界通过，原 Pack 未改 | 每项独立变更 |
| 2 | A8 修复 fixture，补最小最终请求验证与固定评测样本 | 不削弱生产校验，原失败根因可解释 | 测试与验证工具 |
| 3 | A5 统一契约文本生成、A7 明确通道与纠正 Profile | 解析契约等价，模型样本格式与语义不退化 | 每种输出路径 |
| 4 | A6 稳定前缀与静态能力复用 | 三类 renderer 事实等价、revision 失效正确、测量实际收益 | 布局/缓存分别回滚 |
| 5 | 复制开销与 v2 首包协议实验 | 先有瓶颈数据；协议改动单独评审 | 独立实验配置 |

每批先保留变更前最终请求样本，再比较变更后。默认不修改 JSONL 记录名、必填字段、Turn 生命周期、TTS/动作播放行为，也不更换模型。代码修好后仍须真实 Provider + 桌面端验收，不能只凭字符串断言宣告模型效果改善。

## 最小实测场景

- 普通问候和确认：一句自然回复、正确结构、不额外强制委派。
- 先向左再向右：方向与先后段序都正确，非流式和流式一致。
- 第 4 / 7 / 20 轮的指代：保留在用户设定候选池、预算内的相关上下文，不偷改历史上限。
- 实时查询、提醒创建：delegate 与执行事实一致，不靠记忆声称成功。
- 部分工具完成、整轮失败、缺通道纠正：不夸大进度、不重放动作。
- 当前图片与被动桌面截图：只在实际相关任务中使用画面，引用图片不被误当作无图输入。
- 主动表达与进度：包含人格摘要、避免重复此前确认，允许无合适内容时安静。
- 人格/配置/模型 revision 切换：静态缓存立即失效，跨会话无污染。

## 本轮限制

没有真实模型质量评测，没有当前完整线上 Prompt 捕获，没有测得 Provider 缓存命中率或端到端延迟变化。只读枚举了本地两份人格的长度与格式特征，未改写其内容；没有据此认定当前桌宠使用哪一份人格。审阅早期部分动作验证采用从源码抽取纯函数执行；第一批实施后补充了真实模块导入和合成合法 Profile 到最终能力文本、动态 schema/normalizer 的直接验收，仍不能代替真实模型与桌面播放联调。历史配置覆盖与确认语丢失通过真实 PromptRenderEngine 合成输入复现，并已增加最终 ProviderRequest 回归检查。
