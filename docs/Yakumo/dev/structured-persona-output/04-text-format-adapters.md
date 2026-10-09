# 第三阶段：XML、Markdown 等文本格式适配

## 目标

为不能严格支持 tool call、原生 JSON Schema 或 JSON mode 的模型提供明确的文本格式适配器，同时保持 Canonical Persona Schema 不变。

## 1. XML

XML 适配器应定义固定标签和转义规则，例如：

```xml
<persona_expression>
  <turn_action>reply</turn_action>
  <speech>啊……怎么会这样？</speech>
  <actions>
    <action>lower_head</action>
  </actions>
  <thought>这件事出乎意料</thought>
  <tendency>
    <Joy>0</Joy>
    <Trust>1</Trust>
    <Fear>2</Fear>
    <Surprise>8</Surprise>
    <Sadness>7</Sadness>
    <Disgust>0</Disgust>
    <Anger>1</Anger>
    <Anticipation>0</Anticipation>
  </tendency>
</persona_expression>
```

不接受模型自由增加标签，也不根据普通 XML 文本猜测缺失字段。

## 2. Markdown

Markdown 也必须定义固定 grammar，例如固定标题、固定 fenced block 或字段表。不能把普通聊天 Markdown 当成结构化 Persona 输出直接解析。

解析器需要明确处理：

- 代码围栏是否必需。
- 字段标题是否大小写敏感。
- 多段 `speech` 如何合并。
- 列表中的动作如何提取。
- 情绪值和 effect_calls 如何表达。
- 多余说明是否拒绝。

## 3. 失败策略

XML/Markdown 解析失败时，应记录具体原因并使用有限纠正请求。不能通过模糊文本提取生成一个看似完整但语义不确定的 Persona 结果。

## 4. 启用条件

只有满足以下条件后，才将某种文本格式用于生产路径：

1. 有明确 grammar 和 parser。
2. 有语法、类型和语义校验。
3. 有 provider/model 级成功率数据。
4. 失败时有明确的 fallback 或静默策略。
5. 不影响 `speech`、`turn_action` 和 `effect_calls` 的现有消费边界。

