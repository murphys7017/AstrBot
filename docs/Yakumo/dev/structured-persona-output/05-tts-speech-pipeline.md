# 第四阶段：TTS 与 speech 处理

## 目标

将 TTS 需要的时序和表现标签直接放在 `speech` 中，由 TTS 适配器负责 Prompt 注入和结果清理。

## 1. Core 边界

Core 只处理：

```text
Persona 输出中的 speech
  → Output Runtime
  → TTS 适配器
```

Core 不维护独立的 `speech_cues` 数组，也不使用 `phrase_index`、`before`、`after` 等外部时序字段。

## 2. TTS 适配器职责

TTS 适配器后续负责：

1. 根据 TTS provider 能力，在请求前向 Prompt 注入可用标签规则。
2. 要求模型把标签直接嵌入 `speech`。
3. 只在 TTS 边界清理 provider 不应展示的控制标记。
4. 保留标签和文本的原始顺序，确保语音时序可确定。
5. 记录标签解析失败和降级原因。

## 3. 与其他字段的关系

- `speech`：可见文本和 TTS 文本。
- `thought`：不进入 TTS。
- `tendency`：不直接作为 TTS cue；是否影响声音表现由 TTS 适配器另行决定。
- `actions`：不直接进入 TTS。
- `effect_calls`：走插件 effect 链，不当作 TTS 标签。

本阶段不能重新引入一个与 `speech` 并行的通用 cue 数组，否则会再次失去时序确定性。

