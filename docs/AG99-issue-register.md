# AG99 问题登记册（原 102 项复核版，含补充发现）

更新时间：2026-10-03
范围：当前工作区代码、配置、工作流、治理文件和已提供的历史审计结果。
验证方式：本次只做静态复核，没有重新运行测试套件或应用。

这份文档把原始的 102 项问题清单转成可持续维护的登记册。每项保留原编号，增加当前复核结论和处理状态，便于后续逐批关闭。

## 状态说明

- `✓ confirmed`：当前仓库可以直接证明问题描述中的事实。
- `△ partial`：事实存在，但因果、严重度、统计口径或“这是缺陷”的判断需要限定。
- `? historical`：主要依赖此前实跑或工具统计，本次没有重跑。
- `✗ stale/incorrect`：当前代码、路径或工作区状态与原描述不一致。
- `open`：尚未处理。
- `in_progress`：正在处理。
- `resolved`：已修复并完成相应验收。
- `wont_fix`：确认是有意设计或暂不处理，必须补充理由。

## 复核边界

- B1-B5、B7-B8 的耗时/失败数字保留为历史实跑证据，不在本次重新验证。
- D、E、F、G、H、I 主要是源码追踪结果；其中相似度、重复块、函数数量等统计依赖工具和口径。
- 原报告提到的 `chat.py`、`jieba.cache` 和 `pytest-of-Administrator/` 在本轮开始时均已不在工作区；本轮继续处理后新增了 `astrbot/core/star/updator.py` 的未提交修改。
- 这份登记册不把架构观察自动升级成产品缺陷。删除兼容路径、改变安全模型或合并生命周期前，必须补充真实运行验收。

## A · 工程门禁

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| A1 | ✓ resolved | 按用户决定删除 `.github/workflows/code-format.yml`，避免该格式门禁继续阻断 PR；当前没有替代 CI 格式检查。 | resolved |
| A2 | ? historical | 该历史统计在当前 HEAD 已不适用：`.github/workflows/` 下没有受跟踪 workflow，硬编码条件随 workflow 删除而消失；这不是修复门控。 | open |
| A3 | ? historical | 当前没有受跟踪 workflow，Dashboard/coverage/Docker/release 自动化均不存在；原“被 repo 条件门控”描述已被整体删除取代。 | open |
| A4 | ✓ confirmed | 无 typecheck job；pyright 只有配置且不在 dev 依赖。 | open |
| A5 | ✗ stale/incorrect | 当前 HEAD 不含 `.github/workflows/build-docs.yml`；原 secrets 依赖不再是当前可执行路径。 | open |
| A6 | ✓ resolved | Ruff `target-version` 与 pyupgrade pre-commit 参数均已统一到 Python 3.12。 | resolved |
| A7 | ✓ resolved | 已按上游 `1240156f9` 统一到 Ruff `0.15.22`：pre-commit 与 dev 依赖使用同一精确版本。 | resolved |
| A8 | △ partial | Ruff 已纳入 `tests`；当前 fork 仍无 workflow 自动执行 lint/format，CI 门禁问题未解决。 | open |
| A9 | ✓ resolved | 已取消 `.gitignore` 对 `uv.lock` 的忽略，并生成当前项目锁文件。 | resolved |
| A10 | ✓ resolved | `pyproject.toml` 是唯一手写依赖来源；`scripts/export_requirements.py` 生成 pip 兼容清单，pre-commit 在依赖清单变更时检查同步。pip 部署入口保留，Docker 继续从 uv 锁文件导出。 | resolved |
| A11 | ✓ resolved | 已确认源码与测试均无 `silero-vad` 引用；已从 `pyproject.toml`、`requirements.txt` 和锁文件移除，锁文件不再解析 Torch/CUDA 依赖链。 | resolved |
| A12 | ✓ confirmed | `whisper`、`faiss-cpu`、Volcengine、MarkItDown 等是无条件依赖；是否 optional 属于设计决策。 | open |
| A13 | ✓ implementation / △ build pending | Hatch Dashboard 构建已统一使用 pnpm；每次显式构建前通过 `pnpm install --frozen-lockfile` 对齐依赖。Windows 通过 `cmd.exe` 调用 pnpm 启动器；Hatch 完整构建待验收。 | in_progress |
| A14 | ✓ merged | pip 部署文档确实使用 `requirements.txt`；原来的依赖来源疑问并入 A10，由生成脚本维持同步。 | merged |

## B · 测试

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| B1 | ? historical | 全量测试 40 分钟后被中止。 | open |
| B2 | ? historical | 分项约 15 分钟、单进程超过 40 分钟；超线性机制仍未隔离验证。 | open |
| B3 | ? historical | unit 层 39 个失败。 | open |
| B4 | △ partial | EventBus 新配置选择契约与旧 fixture 存在静态不匹配；9 个失败同根因依赖原始日志。 | open |
| B5 | ? historical | 根级至少还有两个失败。 | open |
| B6 | △ partial | 上游 `dd36979ec` 加入 Tenacity provider-request retry，但当前本地 embedding 指数 sleep 与 Gemini 固定 10 次 key-retry 仍在；上游 Gemini 也仍保留该循环。 | open |
| B7 | ? historical | 备份测试真压缩耗时较高；具体 62 用例/79.6 秒未重跑。 | open |
| B8 | ? historical | mimo、provider user agent、dashboard、API key 文件较慢。 | open |
| B9 | △ partial | integration 分支存在但没有 `tests/integration`；marker 也会由 conftest 动态添加。 | open |
| B10 | △ partial | `test_security_fixes.py` 部分测试只验证标准库配置，但整个文件仍调用 AstrBot 代码。 | open |
| B11 | △ partial | 至少若干测试/fixture 不直接 import `astrbot`；不等于完全不测项目代码。 | open |
| B12 | ✓ confirmed | state 中存在 6 条 `validated_with_pytest_collection_gap`。 | open |

## C · 治理与文档一致性

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| C1 | △ partial | `.ai/state.yaml` 当前 222,093 bytes / 2,127 行 / 72 个顶层记录键；是否违反治理规则属于判断。 | open |
| C2 | △ partial | 当前 72 个顶层记录键中，35 条 status 含 `pending_live_acceptance`；risk 字段计数为 38 high / 23 medium / 7 low，另有 4 条未匹配这三类。 | open |
| C3 | △ partial | 离线验证不全依赖测试，也包含 compile/diff/静态检查。 | open |
| C4 | △ partial | `current-state.md` 保留历史快照，是否过期需结合用途判断。 | open |
| C5 | △ partial | Prompt 实现阶段比文档描述复杂；阶段数差异有依据但需明确文档口径。 | open |
| C6 | △ partial | `event.extra` 使用远超“只读诊断”；精确调用数需统一统计规则。 | open |
| C7 | ? historical | `set_extra/get_extra` 从 329 增至 451 属于历史统计。 | open |
| C8 | △ partial | `openspec/` 仅有配置，`.agents/` 当前无受跟踪文件，`.claude/` 已在用户清理提交中删除；“空壳”仍是评价性结论。 | open |
| C9 | ✓ confirmed | 既有审计文档存在，且与本清单有重叠。 | open |

## D · 双轨实现

以下条目大多是“并存事实”，不是单独的运行时 bug。删除前必须完成 live acceptance。

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| D1 | ✓ confirmed | RespondStage/legacy send 与 Interaction 输出控制器同时存活。 | open |
| D2 | ✓ confirmed | 旧 Agent 路径与 CoreExecution/executors 同时存活。 | open |
| D3 | ✓ confirmed | `event.extra` 与 typed turn state 同时存活。 | open |
| D4 | ✓ confirmed | Provider 内仍有 legacy output contract 兼容分支。 | open |
| D5 | ✓ confirmed | `get_conf` fallback 与新 `UmopConfigRouter` 同时存在。 | open |
| D6 | ✓ confirmed | proactive/Cron 使用独立生命周期入口。 | open |
| D7 | △ partial | pipeline voice 与 `core/voice` 并存；是否应合并需运行路径确认。 | open |
| D8 | ✓ confirmed | 根目录 `main.py` 与 `cli/commands/cmd_run.py` 均各自创建 `InitialLoader` 并调用 `asyncio.run`；原登记误把根路径写成 `astrbot/main.py`。 | open |
| D9 | ✓ confirmed | `render/interfaces.py` 定义 `BasePromptRenderer`，`base_renderer.py` 重新导出同一类；两个导入路径仍并存。 | open |
| D10 | ✓ confirmed | admission/runtime/capability inventory 都遍历插件 registry。 | open |
| D11 | ✓ resolved | 递归配置合并已集中到纯函数 `interaction/runtime_config.py`，保留 middleware 对非 Mapping 输入的兼容行为。 | resolved |
| D12 | ✓ confirmed | skills 中存在针对测试 monkeypatch 的 TypeError 兼容分支。 | open |
| D13 | ✓ confirmed | session management 同时返回旧格式和结构化格式。 | open |
| D14 | ✓ confirmed | `provider/entities.py` 有兼容包装，当前未发现调用方。 | open |
| D15 | ✓ confirmed | `CommandResult` 是旧名兼容别名。 | open |
| D16 | ✓ implementation / △ live pending | Dashboard 会话列表已吸收渐进分页，旧接口无分页参数时仍保留数组响应；后端契约、稳定排序和深链接元数据已通过定向测试，运行中页面滚动尚待验收。 | in_progress |
| D17 | ✓ confirmed | 配置项保留兼容旧配置的注释。 | open |
| D18* | ✓ implementation / △ live pending | `PluginManager.update_plugin()` 总是向 updater 传 `download_url`，但本地 `PluginUpdator.update()` 原签名不接收该参数，导致插件更新调用抛 `TypeError`；已吸收上游直链更新参数契约，真实更新验收待做。 | in_progress |

`D18*` 是处理原清单时发现的补充问题，不计入原 102 项。

## E · 补丁式实现

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| E1 | ✓/△ | output adapter 通过 MethodType 替换 send/stream/complete，并维护额外状态；“本可一两行解决”是判断。 | open |
| E2 | ✓ confirmed | plugin branch 再次替换多个事件方法。 | open |
| E3 | ✓/△ | branch event 手动复制字段；新增字段漏拷是风险而非已证实 bug。 | open |
| E4 | ✓ confirmed | branch extra 清单有硬编码 key，平台模块已有常量。 | open |
| E5 | △ partial | 类属性与实例属性都写入相同值，但实例化前注入类属性有明确用途。 | open |
| E6 | ✓/△ | 多处使用 `setattr` 回填对象字段；是否应改为显式模型需结合边界判断。 | open |
| E7 | ✓/△ | Context 使用字符串动态 registry 字段，静态可见性较弱。 | open |

## F · 腐败模式

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| F1 | ✓/△ | `_interaction_enabled` 是裸字符串，约 15 个读取点；实际行为风险需运行验证。 | open |
| F2 | ✓ resolved | 生产读取/写入点统一使用 `INTERACTION_OUTPUT_CONTROLLER_EXTRA_KEY`；字符串只保留在平台常量定义处。 | resolved |
| F3 | △ partial | 超长函数示例属实；211 个的精确数量依赖统计脚本。 | open |
| F4 | ? historical | satori 转换器相似度数据未本次复核。 | open |
| F5 | △ partial | Provider text/stream 函数成对存在；相似度数字未复核。 | open |
| F6 | ? historical | “三胞胎”函数簇及相似度未复核。 | open |
| F7 | ✓/△ | 生产代码检索到约 69 行 `assert`；`python -O` 会移除它们，但不代表每个都承担安全校验。 | open |
| F8 | ✓ resolved | 5 个 runner 共用 `REQUEST_NOT_SET_MESSAGE`，错误文本和异常类型保持不变。 | resolved |
| F9 | ✓ confirmed | `except Exception` 当前约 1128 处。 | open |
| F10 | △ partial | `getattr` 数量随匹配规则约 700–756，原数字不稳定。 | open |
| F11 | ? historical | 56 处静默吞异常未按同一规则重新核对。 | open |
| F12 | ✓ confirmed | `hasattr` 当前约 115 处。 | open |
| F13 | ✓ confirmed | `type: ignore`/`noqa` 当前约 82/142。 | open |
| F14 | △ partial | 硬编码端点确实分散；精确 13 处需固定口径。 | open |
| F15 | ? historical | 872 个重复块依赖相似度工具，未本次复核。 | open |
| F16 | ✗ stale/partial | 当前 Python 源码检索约 22 个 TODO/FIXME/HACK，不是 31。 | open |

## G · 安全

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| G1 | ✓/△ | API key 使用静态 PBKDF2 salt；是盐复用问题，不是 salt 泄露。 | open |
| G2 | ✓ implementation / ✓ isolated runtime / △ production rollout | Dashboard JWT 新增凭据版本 claim，HTTP、Live Chat WebSocket 与备份下载校验；隔离完整运行实例中改密码、改用户名后，旧 HTTP/WS/备份 JWT 均失效，新凭据可登录。生产账户迁移和部署仍待验收。 | in_progress |
| G3 | ✓ confirmed | JWT secret 首次启动生成后写回配置文件。 | open |
| G4 | ✓ implementation / ✓ isolated browser / △ UI action pending | 真实 Chromium 在 localhost 接受 `Secure; HttpOnly; SameSite=Strict` cookie，并以仅含 filename 的同源请求下载到预置备份；没有 token query。`BackupDialog` 按钮的实际点击流程与生产部署仍待验收。 | in_progress |
| G5 | ✗ stale/incorrect | 当前默认 `secure` 是非 debug 且非 testing 时为 true。 | open |
| G6 | ✓ implementation / ✓ isolated Windows runtime / △ public integration pending | 插件、CLI、skill 与 core ZIP 解包均限制成员路径和资源；Windows symlink/junction 会被拒绝，插件文件通过同目录临时文件原子替换。隔离运行验证了默认 `HEAD.zip` URL 构造与下载、插件换版、坏包保留旧版、core 包应用到临时安装根；公网 GitHub 跳转、运行中插件加载/回滚仍待验收。 | in_progress |
| G7 | ✓/△ | 插件可访问数据库和 provider registry；这是可信插件模型下的能力，非传统沙箱。 | open |
| G8 | △ partial | `ChatService.get_session` 当前已校验 `session.creator == username`，与上游 `041fba4df` 的修复一致；其他 Dashboard 配置接口是否需要租户隔离仍取决于产品模型。 | open |
| G9 | ✗/△ | registry 有 clear/remove 路径，不能称为完全不可注销。 | open |
| G10 | △ partial | plugin page 使用通配 CORS，代码注释说明有 iframe 场景；需按威胁模型审查。 | open |

## H · 结构与规模

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| H1 | △ partial | 当前提交图相对共同基点 `67c7445d` 为本地独有 986、上游独有 771；提交数不是代码量/自有代码占比的替代指标。 | open |
| H2 | △ partial | `default.py` 确实约 5k 行；935 配置键需固定解析口径。 | open |
| H3 | △ partial | 大文件事实成立，但报告中的多个行数已过时。 | open |
| H4 | ✓/△ | interaction 配置面复杂；这是运维/架构风险，不是单一 bug。 | open |
| H5 | ✓ confirmed | turn 生命周期存在全序列入口及 prepare/complete 分支入口。 | open |
| H6 | ✓/△ | branch extra 清单硬编码，字段一致性缺乏机制保障。 | open |

## I · 死代码与仓库垃圾

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| I1 | ✓/△ | `provider/entites.py` 存在且未发现调用；原报告行数已过时。 | open |
| I2 | ✓ confirmed | `filter_llm_exposed_context_pack` 当前未发现生产调用方。 | open |
| I3 | △ partial | `_encode_image_bs64` 未发现生产调用方，动态调用仍不能完全排除。 | open |
| I4 | △ partial | Persona runtime 三个方法未发现调用方，需排除反射/插件调用。 | open |
| I5 | ✗ stale/incorrect | `session_controller/`、`web_searcher/` 当前都不存在，也没有受跟踪源码；原“目录只含 pycache”不适用于当前工作区。 | open |
| I6 | ✓ resolved | `test.db` 已由本地提交 `4731f970d` 删除，当前不再跟踪且文件不存在。 | resolved |
| I7 | ✓ confirmed | `video-fix.patch` 已被 git 跟踪。 | open |
| I8 | ✗ stale/incorrect | 本次检查该 exe 当前不存在；原报告是工作区状态，不是仓库跟踪文件。 | open |
| I9 | ? historical | 当前 `git status` 干净；忽略文件和所有本地缓存未做递归清理审计。 | open |
| I10 | ✓ resolved | 已从 `.gitignore` 移除对已跟踪 `AGENTS.md` 与 `pyproject.toml` 的忽略规则；两文件仍由 Git 跟踪。 | resolved |
| I11 | △ partial | `openspec/config.yaml` 存在，`.agents/` 无受跟踪文件，`.claude/` 已删除；治理投入低的观察仍成立但不宜称为残留空目录。 | open |

## 建议处理批次

### Batch 1：先恢复可控门禁

A4、A6、A9、A10、A13。A2/A3/A5 已被 workflow 整体删除这一状态取代；是否恢复 CI 由用户另行决定。A7 已按上游版本统一。

目标是让 fork 的 CI、依赖解析、格式化和构建入口先拥有清晰且可重复的边界。

### Batch 2：运行时安全与入口正确性

G2、G3、G4、G6、G8、G10、D5、D6、H5。

这批需要真实启动后的 Dashboard、备份、配置路由、普通对话和 proactive smoke；不以测试套件全绿作为完成条件。

### Batch 3：契约迁移与兼容债

B4、D1-D4、D9-D15、E1-E7、F1-F2、F7、H6。

每次只收敛一个 owner，先记录 live acceptance，再删除兼容路径。

### Batch 4：规模和可维护性

D7、D10、F3-F6、F8-F10、F12-F16、H1-H4、I1-I5。

这些条目多数不是紧急线上故障，应在边界稳定后按模块拆解。

### Batch 5：测试与文档治理

B1-B3、B5-B12、C1-C9。

历史测试数字只作为背景；后续以实际运行验收和可追踪的 acceptance 记录关闭。

## 工作区状态

本节所述干净状态是上一轮复核时的快照，不代表当前工作区。后续 G6 复核产生的 updater、技能导入、插件服务、关联记录与验收用例按其对应提交单独收口；用户删除的 `openspec/config.yaml` 不属于本轮范围，保留删除状态且不纳入提交。

## 上游对照与本轮优先级（2026-10-01）

对照基准为 `upstream/master` 的 `9d4f52346`（2026-10-01）。当前提交图共同基点为 `67c7445d`（2026-04-27）；分支两侧差异较大，避免整段合并，仅按具体修复判断可移植性。

| 问题 | 上游证据 | 本 fork 现状与结论 |
|---|---|---|
| A1-A5 | 上游仍保留官方 workflows；当前 fork 的 workflows 已整体不在 HEAD。 | A1 格式 workflow 已删；A2/A3/A5 的旧描述不再适用，但 CI/build 自动化也不存在，不能视为功能修复。 |
| A6-A13 | 上游仍有 `target-version = "py310"`、排除 tests、忽略 `uv.lock`、依赖双源及 npm/pnpm 并存；`silero-vad` 仍列依赖。 | 本 fork 已修 A6（Ruff/pyupgrade 对齐 Python 3.12）、A7（Ruff 版本统一）、A9（追踪 `uv.lock`）、A10（由 pyproject 生成 pip 兼容清单）、A11（移除未引用的 `silero-vad`）；A13 已实现 Hatch/pnpm 对齐，完整构建待验收。A8 的 Ruff 范围已包含 tests，但仍无 CI 执行入口。A4 仍待处理，A12 属依赖分层设计决策。 |
| B4 | 上游近期没有对应的 EventBus fixture 修复提交。 | 仍应按当前 config-selection 契约修 fixture；这是测试适配问题，不等同于证明生产路由错误。本轮未跑测试。 |
| B6 | `dd36979ec` 新增 Tenacity 重试封装；当前上游 Gemini 仍保留 `retry = 10` 的 key 轮换。 | 属于部分重试体系更新，不解决本条的可注入 sleep/测试墙钟问题；不整体移植其 provider API 改造。 |
| B7 | 上游 `astrbot/core/backup/exporter.py` 仍用 `ZIP_DEFLATED` 且不传 `compresslevel`。 | 未发现压缩快路径；测试耗时属性能优化而非生产行为缺陷。 |
| B8 | `d524b8708` 统一 provider User-Agent。 | 与测试起真实 aiohttp server 的耗时原因不同，不能据此关闭慢测问题。 |
| D8 | 上游 `main.py` 与 `cli/commands/cmd_run.py` 目前仍各自构造 `InitialLoader`。 | 本 fork 的重复入口属实；上一版登记的“`astrbot/main.py` 不存在”是路径误读，未发现上游已消除这项重复。 |
| D16 | `2f7675140` 为 ChatUI sidebar 添加渐进加载和分页。 | 已完成后端兼容响应、侧栏按需加载及边界测试；真实页面滚动验收待服务更新后进行。 |
| G4 | `573367b7f` 在备份下载中接受 Bearer header。 | 已保留上游 Bearer 能力，并增加 HttpOnly cookie 下载鉴权；前端原生下载不再携带 query token，旧 query 仍兼容。 |
| G1-G3 | 当前上游仍用固定 `b"astrbot_api_key"` 做 PBKDF2 salt；JWT 仍主要含 `username` 与 7 天 `exp`，JWT secret 仍写回 Dashboard config。 | 未发现上游提交解决静态 salt 或 secret 持久化；G2 已在本地增加凭据版本绑定及 HTTP/WebSocket/备份校验，需实际运行验收。TOTP 是额外认证，不等于 token 吊销。 |
| G6 / D18* | `3d4c4ed01`（#9061）增加插件 archive 元数据验证；`7ec39bdef`（#10053）支持 URL/文件插件更新；`b53999e95`（#10193）缩短 GitHub 提交归档根目录以支持 Windows 长路径。上游仍通过 `extractall` 解包，未发现拒绝越界成员路径的修复。 | 本 fork 已吸收 `download_url` 更新契约、#10193 根目录缩短，并分别为插件、CLI、skill 与 core updater 加入 ZIP 边界和资源限制；core/plugin 在构造 `ZipFile` 前校验中央目录大小与真实记录数。隔离归档输入输出已验收；实际远程插件更新及 core 更新尚未运行。 |
| G8 | `041fba4df` 增加 ChatUI session owner 校验。 | 当前本地 `ChatService.get_session` 已有同等 creator 校验；这条应限定到未明确租户边界的其他管理 API。 |
| I6/I8/I9 | 非上游问题，属本地仓库/工作区状态。 | I6 已随 `4731f970d` 删除；I8 文件当前不存在；I9 的历史工作区产物本次不做清理。 |
| C/D/E/F/H/I 其余项 | 未发现能直接消除 AG99 自有 Interaction/Persona 双轨、治理或结构问题的对应上游提交。 | 维持登记册的静态观察结论；D8/D9/I5 等路径错误已在本轮更正，逐项重构前仍要有具体运行场景和验收。 |

建议的实际处理顺序：

1. **G6 ZIP 更新流程收口**：Windows junction 绕过已在 core 与插件解包入口复现并修复；本机代理上的默认 HEAD 归档更新、坏包保护及临时 core 更新应用已通过。仍需公网 GitHub 重定向和隔离插件真实加载/失败回滚验收。
2. **G2/G4 Dashboard token 生命周期与传递**：隔离完整运行实例已验证改密/改用户名后 HTTP、WebSocket、备份旧 token 失效，真实浏览器 cookie 下载成功；仍需点击 `BackupDialog` 下载按钮并按部署方式验收。
3. **B4 EventBus fixture 契约**：修正测试构造，让它提供真实 config selection；随后用一条真实消息/实际运行路径确认事件能到对应 pipeline。
4. **A4/A9/A10 与 CI 去留**：先由用户决定是否恢复最小 CI；再统一依赖解析来源。不得把“所有 workflow 删除”记成 CI 修复。
5. **D16 分页**：参考 `2f7675140`，同步改后端兼容响应、前端按需加载和边界场景；这是有真实规模收益的功能修复，但不应压过安全核验。
6. **G1/G3/G10 与插件权限边界**：按部署威胁模型处理；API key 是高熵随机值，静态盐值得改但优先级低于会话/下载边界。
7. **D/E/F/H 结构债**：不按行数批量拆分，选一个具体行为边界逐个收敛，并用真实应用流程验收。

验证边界：本轮不运行测试套件。G2/G4 在新建 `ASTRBOT_ROOT` 的完整本地运行实例中通过改密码、改用户名、旧 HTTP/WS/备份 JWT 拒绝及浏览器 cookie 备份下载验收；生产环境未触碰，`BackupDialog` 按钮点击和生产部署仍待确认。启动时核心自动访问 `models.dev` 获取模型元数据。D18/G6 的 ZIP 成员边界、Windows junction 拒绝、同目录原子写、loopback 默认 HEAD 归档更新、插件坏包保留旧版及隔离 core 更新应用均已通过直接运行验证；公网 GitHub 跳转、运行中插件加载/失败回滚仍未验收，未验证前不标记 resolved。

## 2026-10-01 D16 分页吸收跟进

已按上游 `2f7675140` 完成会话分页的本地适配：旧 `/api/chat/sessions` 调用仍返回原数组，新分页请求返回页数据；列表触底加载后续会话，失败可重试，深链接会话保留标题和选中态。定向后端测试、Python 检查、Dashboard 类型检查和生产构建通过。当前运行中的服务未重启，真实浏览器滚动行为留待服务更新后验收，因此 D16 暂记 `in_progress`。

## 2026-10-02 G6 Windows Junction Follow-up

Windows 隔离运行发现，`os.path.islink()` 不识别目录 junction。更新包根目录命中预置 junction 时，core 与插件解包都曾把外部 sentinel 移入更新目标；插件 commit-root 缩短还会让解包实际路径与前置校验路径不同。修复后，两条生产解包入口均通过 `os.path.isjunction()` 拒绝 junction，插件文件先写入同目录临时文件再 `os.replace`，同时避免覆盖硬链接时改写外部 inode。

本轮直接运行验收通过：loopback GitHub 形状代理收到了默认 `HEAD.zip` 路径并返回归档，隔离插件更新成功；随后恶意归档被拒，已安装文件逐字节不变且 staging 清理。core 更新包应用到临时 `MAIN_PATH`，更新 marker 生效且旧 sentinel 保留。core 和插件 junction 归档均在外部 sentinel 改变前拒绝；平铺插件归档替换硬链接路径后，外部原文件保持不变。公网 GitHub 服务/重定向、运行中插件加载与失败回滚仍待验收；没有运行测试套件或重启当前服务。
