# 第五阶段：迁移、验证与发布

## 目标

在完成 tool call 迁移和 provider 策略适配后，统一更新文档、测试、插件边界和运行诊断，并按阶段启用。

## 1. 迁移顺序

1. 冻结并审阅 Canonical Schema。
2. 修改 `persona_expression` tool-call Schema 和 Prompt。
3. 更新结果解析、校验和运行时消费。
4. 删除 `spoken_reply`、`speech_cues` 的 Core 兼容读取。
5. 更新 effect、Interaction、Output Runtime 和 TTS 边界文档。
6. 建立 provider 能力矩阵和策略诊断。
7. 接入原生 JSON Schema、JSON mode 和 prompt-only JSON。
8. 在有实际数据后再接入 XML/Markdown。
9. 最后实施 TTS 标签注入和清理。

## 2. 验证范围

每个阶段至少验证：

- Schema 序列化和解析。
- `reply`、`delegate`、`silent` 三种路由。
- `speech`、`actions`、`thought` 和八维 `tendency` 的字段边界。
- `silent` 的空输出约束。
- `effect_calls` 继续按原有 effect Schema 执行。
- `speech` 不混入 `thought`、`tendency` 或动作字段。
- provider 格式失败时不会生成错误的可见回复。
- TTS 只读取 `speech`。

## 3. Provider 验收

对每个 provider/model/策略组合记录：

- 请求是否成功构造。
- 返回格式是否符合预期。
- Schema 成功率。
- 解析失败率。
- 重试和 fallback 率。
- 首 token 和完整响应延迟。
- token 消耗。

没有稳定数据前，不改变 tool call 的默认优先级。

## 4. 文档同步

需要同步审阅和更新：

- `docs/Yakumo/dev/output-contract.md`
- `docs/Yakumo/dev/interaction-output-plugin-contract.md`
- `docs/Yakumo/current-state.md`
- Persona effects 文档
- provider 和 Prompt 系统文档
- 相关测试说明和迁移记录

旧文档中出现 `spoken_reply`、`speech_cues` 或五维情绪字段的地方，都应改为新的 Canonical Schema，或明确标注为历史记录。

## 5. 发布边界

这是破坏性协议更新，发布前需要确认：

- Core 不再接受旧字段。
- 依赖 `speech_cues` 的插件已经有迁移安排。
- tool call 主路径已通过最小输入输出检查。
- provider fallback 不会静默吞掉结构化错误。
- 新增格式没有改变业务层字段含义。
- 文档、测试 fixture 和训练数据标注全部使用 Plutchik 八维情绪体系。

本计划本身不要求立即提交代码；每个阶段完成设计审阅后，再单独进入实现和验证。

