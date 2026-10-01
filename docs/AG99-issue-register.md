# AG99 问题登记册（102 项复核版）

更新时间：2026-10-01
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
- 当前工作区除已修改的 `astrbot/dashboard/routes/chat.py` 外，还存在未跟踪的 `jieba.cache` 和 `pytest-of-Administrator/` 测试产物；原报告“唯一未提交改动”不再准确。
- 这份登记册不把架构观察自动升级成产品缺陷。删除兼容路径、改变安全模型或合并生命周期前，必须补充真实运行验收。

## A · 工程门禁

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| A1 | △ partial | code-format workflow 无 fork 门控；234 个不合规文件和“每个 PR 必红”属于历史实跑结论。 | open |
| A2 | ✓ confirmed | 7 个 workflow 共 10 处硬编码 `github.repository == 'AstrBotDevs/AstrBot'`。 | open |
| A3 | △ partial | Dashboard、Docker、发布 job 被门控；coverage 测试仍运行，只有上传步骤被门控。 | open |
| A4 | ✓ confirmed | 无 typecheck job；pyright 只有配置且不在 dev 依赖。 | open |
| A5 | △ partial | `build-docs.yml` 依赖上游 secrets；“每次 tag 必失败”取决于 fork 是否配置 secrets。 | open |
| A6 | ✓ confirmed | `requires-python >=3.12` 与 Ruff `py310` 不一致。 | open |
| A7 | ✓ confirmed | pre-commit Ruff `v0.14.1` 与 pyproject `>=0.15.0` 分裂。 | open |
| A8 | △ partial | CI Ruff 排除 `tests`；“所有 lint/格式化都不管 tests”过于绝对。 | open |
| A9 | ✓ confirmed | `uv.lock` 被忽略，未纳入版本控制。 | open |
| A10 | ✓ confirmed | `requirements.txt` 与 `pyproject.toml` 双源并存，smoke workflow 使用前者。 | open |
| A11 | △ partial | `silero-vad` 当前源码无引用；权重/torch 安装成本需按依赖解析确认。 | open |
| A12 | ✓ confirmed | `whisper`、`faiss-cpu`、Volcengine、MarkItDown 等是无条件依赖；是否 optional 属于设计决策。 | open |
| A13 | △ partial | Hatch 使用 npm，Dashboard/文档 CI 使用 pnpm；存在工具链分裂但未必是错误。 | open |
| A14 | ✗ stale/incorrect | 原引用不能证明“requirements.txt 被列为运行时依赖”；问题应并入 A10。 | open |

## B · 测试

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| B1 | ? historical | 全量测试 40 分钟后被中止。 | open |
| B2 | ? historical | 分项约 15 分钟、单进程超过 40 分钟；超线性机制仍未隔离验证。 | open |
| B3 | ? historical | unit 层 39 个失败。 | open |
| B4 | △ partial | EventBus 新配置选择契约与旧 fixture 存在静态不匹配；9 个失败同根因依赖原始日志。 | open |
| B5 | ? historical | 根级至少还有两个失败。 | open |
| B6 | ✓ confirmed | provider 重试 sleep 不可注入；Gemini 有固定 10 次重试。 | open |
| B7 | ? historical | 备份测试真压缩耗时较高；具体 62 用例/79.6 秒未重跑。 | open |
| B8 | ? historical | mimo、provider user agent、dashboard、API key 文件较慢。 | open |
| B9 | △ partial | integration 分支存在但没有 `tests/integration`；marker 也会由 conftest 动态添加。 | open |
| B10 | △ partial | `test_security_fixes.py` 部分测试只验证标准库配置，但整个文件仍调用 AstrBot 代码。 | open |
| B11 | △ partial | 至少若干测试/fixture 不直接 import `astrbot`；不等于完全不测项目代码。 | open |
| B12 | ✓ confirmed | state 中存在 6 条 `validated_with_pytest_collection_gap`。 | open |

## C · 治理与文档一致性

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| C1 | △ partial | `.ai/state.yaml` 约 218KB/2084 行；是否违反治理规则属于判断。 | open |
| C2 | △ partial | 大量 live acceptance pending；精确 35/63 和风险分布需固定统计口径。 | open |
| C3 | △ partial | 离线验证不全依赖测试，也包含 compile/diff/静态检查。 | open |
| C4 | △ partial | `current-state.md` 保留历史快照，是否过期需结合用途判断。 | open |
| C5 | △ partial | Prompt 实现阶段比文档描述复杂；阶段数差异有依据但需明确文档口径。 | open |
| C6 | △ partial | `event.extra` 使用远超“只读诊断”；精确调用数需统一统计规则。 | open |
| C7 | ? historical | `set_extra/get_extra` 从 329 增至 451 属于历史统计。 | open |
| C8 | △ partial | openspec、agents、claude 治理目录内容较少；“空壳”是评价。 | open |
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
| D8 | ✗ stale/incorrect | 原引用的 `astrbot/main.py` 当前不存在；实际入口为 InitialLoader/cmd_run。 | open |
| D9 | △ partial | `prompt/render/interfaces.py` 与 `base_renderer.py` 包装并存；原路径已过时。 | open |
| D10 | ✓ confirmed | admission/runtime/capability inventory 都遍历插件 registry。 | open |
| D11 | ✓ confirmed | `_merge_runtime_config` 在两个模块各定义一次。 | open |
| D12 | ✓ confirmed | skills 中存在针对测试 monkeypatch 的 TypeError 兼容分支。 | open |
| D13 | ✓ confirmed | session management 同时返回旧格式和结构化格式。 | open |
| D14 | ✓ confirmed | `provider/entities.py` 有兼容包装，当前未发现调用方。 | open |
| D15 | ✓ confirmed | `CommandResult` 是旧名兼容别名。 | open |
| D16 | ✓ confirmed | `chat.py` 有注释为临时用途的 `page_size=100`。 | open |
| D17 | ✓ confirmed | 配置项保留兼容旧配置的注释。 | open |

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
| F2 | ✓ confirmed | `_interaction_output_controller` 有多处硬编码，同时已有常量。 | open |
| F3 | △ partial | 超长函数示例属实；211 个的精确数量依赖统计脚本。 | open |
| F4 | ? historical | satori 转换器相似度数据未本次复核。 | open |
| F5 | △ partial | Provider text/stream 函数成对存在；相似度数字未复核。 | open |
| F6 | ? historical | “三胞胎”函数簇及相似度未复核。 | open |
| F7 | ✓/△ | 生产代码有 67 个 assert；`python -O` 会移除它们，但不代表每个都承担安全校验。 | open |
| F8 | ✓ confirmed | `Request is not set...` 文案在 5 个 runner 中重复。 | open |
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
| G2 | ✓ confirmed | JWT 没有 iat/aud/吊销/version；改密码不会自动让旧 token 失效。 | open |
| G3 | ✓ confirmed | JWT secret 首次启动生成后写回配置文件。 | open |
| G4 | ✓ confirmed | backup download 在白名单中，token 通过 URL query。 | open |
| G5 | ✗ stale/incorrect | 当前默认 `secure` 是非 debug 且非 testing 时为 true。 | open |
| G6 | △ partial | `zip_updator.py` 使用 `extractall`，但原报告路径错误；备份 importer 另有路径校验。 | open |
| G7 | ✓/△ | 插件可访问数据库和 provider registry；这是可信插件模型下的能力，非传统沙箱。 | open |
| G8 | △ partial | 路由未见明显按用户隔离；是否是问题取决于产品是否单租户。 | open |
| G9 | ✗/△ | registry 有 clear/remove 路径，不能称为完全不可注销。 | open |
| G10 | △ partial | plugin page 使用通配 CORS，代码注释说明有 iframe 场景；需按威胁模型审查。 | open |

## H · 结构与规模

| 编号 | 复核 | 问题（压缩表述） | 处理 |
|---|---|---|---|
| H1 | ? historical | fork 行数/提交差异依赖 upstream 基线，未本次重新计算。 | open |
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
| I5 | △ partial | 对应源码目录当前不可见；“只含 pycache”需排除忽略目录后确认。 | open |
| I6 | ✓ confirmed | 0 字节 `test.db` 已被 git 跟踪。 | open |
| I7 | ✓ confirmed | `video-fix.patch` 已被 git 跟踪。 | open |
| I8 | ✓ confirmed | 未跟踪的 `deepseek-tui-windows-x64.exe` 约 39MB。 | open |
| I9 | ✓ confirmed | 工作区存在测试、tmp、cache 等本地产物。 | open |
| I10 | ✓ confirmed | `.gitignore` 忽略已被跟踪的 `AGENTS.md` 与 `pyproject.toml`。 | open |
| I11 | △ partial | 治理目录内容较少；“空壳”是评价性结论。 | open |

## 建议处理批次

### Batch 1：先恢复可控门禁

A2、A3、A4、A6、A7、A9、A10、A13、I9、I10。

目标是让 fork 的 CI、依赖解析、格式化和构建入口先拥有清晰且可重复的边界。

### Batch 2：运行时安全与入口正确性

G2、G3、G4、G6、G8、G10、D5、D6、H5。

这批需要真实启动后的 Dashboard、备份、配置路由、普通对话和 proactive smoke；不以测试套件全绿作为完成条件。

### Batch 3：契约迁移与兼容债

B4、D1-D4、D9-D15、E1-E7、F1-F2、F7、H6。

每次只收敛一个 owner，先记录 live acceptance，再删除兼容路径。

### Batch 4：规模和可维护性

D7、D10-D11、F3-F6、F8-F10、F12-F16、H1-H4、I1-I5。

这些条目多数不是紧急线上故障，应在边界稳定后按模块拆解。

### Batch 5：测试与文档治理

B1-B3、B5-B12、C1-C9。

历史测试数字只作为背景；后续以实际运行验收和可追踪的 acceptance 记录关闭。

## 当前工作区说明

本登记册不包含以下已有工作区内容，也不会替它们做决定：

- `astrbot/dashboard/routes/chat.py` 的用户改动；
- `jieba.cache`；
- `pytest-of-Administrator/` 测试产物。

后续每个修复批次应只提交对应源文件、文档和必要的验收记录。
