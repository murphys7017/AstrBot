# 第一阶段：当前 tool call 迁移

## 目标

只修改现有 `persona_expression` tool call 的参数 Schema、Prompt、解析和运行时消费，不在本阶段切换 provider 的输出传输方式。

## 1. OutputContract

继续使用当前契约：

```text
mode = tool_call
strict = true
preferred_tool_name = persona_expression
```

`effect_calls` 仍由现有动态 effect 注册结果生成。新增的 `actions`、`thought` 和八维 `tendency` 放入同一组 tool-call arguments。

## 2. Prompt 修改

Persona Prompt 需要明确：

1. 必须调用 `persona_expression`。
2. `turn_action` 只能输出 `reply`、`delegate` 或 `silent`。
3. `speech` 是唯一用户可见文本。
4. `actions` 只输出简单动作词数组，不写参数。
5. `thought` 是简短心理摘要，不输出完整推理过程。
6. `tendency` 使用八个固定的 Plutchik 角色情绪维度，表示角色当前的情绪状态。
7. 八个情绪值使用 `-10` 到 `10` 的整数范围。
8. `silent` 必须返回空 `speech`、空 `actions` 和空 `effect_calls`。
9. TTS 专用标签暂时不由 Core 自行扩展；后续由 TTS 适配器注入规则。

Prompt 中还要区分 `actions` 和 `effect_calls`：前者是动作意图，后者是插件 effect 执行请求。

## 3. 解析与规范化

需要调整 `expression_agent.py` 中的：

- `PersonaExpressionResult` 字段。
- `build_persona_expression_tool_parameters()`。
- tool-call arguments 的 JSON 解析。
- `turn_action` 的枚举转换。
- `tendency` 八维范围和完整性校验。
- `actions` 简单字符串数组校验。
- `speech` 的空值处理。
- effect correction flow 中对字段的保留逻辑。

严格 tool call 缺失时继续沿用当前错误和受控降级行为；本阶段不新增 JSON mode、XML 或 Markdown 解析路径。

## 4. 运行时消费

需要检查并改造：

- `middleware.py`：使用 `speech` 进行输出和路由后的空值判断。
- `persona_runtime.py`：读取规范化后的 `speech`。
- `output_controller.py`：把 `speech` 交给消息输出和 TTS。
- `capability_route_guard.py`：继续校验 `turn_action`，更新 silent 约束。
- `contributors.py`、`turn_state.py`：如需保存表达快照，使用新的字段名称。

`thought` 和 `tendency` 不得被拼接进用户文本、TTS 文本或普通对话历史。`actions` 只作为结构化动作意图继续向后传递。

## 5. speech_cues 处理

Core 的 `speech_cues` 字段在本阶段删除：

- 不再加入 tool-call Schema。
- 不再从结果中读取或生成。
- 不再参与 silent 判定。
- 不再由 Output Controller 传给 TTS。

AG99live 等外部消费方的迁移在独立兼容任务中处理，Core 不为旧接口保留长期双轨协议。

## 6. 阶段验收

- 当前支持严格 tool call 的 provider 能返回完整新 Schema。
- `spoken_reply` 和 `speech_cues` 不再被 Core 接受。
- 五维情绪字段全部替换为八维 Plutchik 字段。
- `silent`、`delegate`、`reply` 三条路径都能正确工作。
- `speech` 是唯一进入输出和 TTS 的文本。
- `effect_calls` 执行行为不变。
- 不发生 provider 输出模式切换。

