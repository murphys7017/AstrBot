# 日志规范

AstrBot 将日志分为三层。普通运行日志用于判断系统是否正常工作；诊断日志用于定位耗时和状态边界；Trace 用于查看受控的详细材料。

| 通道 | 用途 | 允许内容 |
| --- | --- | --- |
| `INFO` | 启动、配置变更、实际任务分派和用户可见的关键结果 | 稳定 ID、状态、数量、耗时、能力名称 |
| `DEBUG` | `DIAG <domain>.<event>` 形式的阶段诊断 | 阶段、原因码、计数、长度、耗时、slot/tool 名称 |
| Trace 文件 | Prompt 结构、上下文槽位和受控排障材料 | 仅在 `trace_log_enable=true` 时写入 |
| `WARNING` / `ERROR` | 可恢复异常、失败和配置问题 | 阶段、异常类型、状态码、响应长度和 `exc_info` |

## 禁止写入普通日志

- 完整用户输入、模型回复、STT 文本和 TTS 原文；
- 完整 Prompt、历史消息、上下文槽位值和工具参数/结果；
- API Key、Authorization header、文件回调 token、签名 URL；
- Provider 或平台的原始请求体、完整响应和 WebSocket 原文。

普通日志应改为记录 `text_length`、`message_count`、`response_keys`、`tool_count`、`status` 或 `error_length` 等摘要字段。

## 关联字段

Interaction 链路优先携带 `turn_id`、`session_id`、`platform_id` 和 `lifecycle_id`。耗时日志使用 `*_ms`，并在事件名或字段中明确边界，例如 `personal_first_output_ms`、`provider_ms` 和 `turn_total_ms`。

一个正常对话不应在 `INFO` 级别输出 Prompt、工具循环或每个内部阶段。需要排查时将 `log_level` 调为 `DEBUG`；需要查看完整 Prompt 结构时额外开启 `trace_log_enable`，并妥善保护 Trace 文件。

## 新增日志

新增日志前先选择通道，而不是先选择文案：

1. 用户或运维是否需要在正常运行时看到它？若是，使用简短的 `INFO`。
2. 它是否用于解释性能或内部决策？使用无正文的 `DEBUG DIAG`。
3. 它是否包含 Prompt、输入、输出或原始远程对象？只进入 Trace 文件。
4. 失败时记录错误类型、阶段和长度；不要把原始请求、响应或敏感内容拼进异常消息。
