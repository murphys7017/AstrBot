# Image Moderator

监听指定群聊中的图片消息，使用 AstrBot 配置的多模态 Provider 进行安全分类；模型明确返回 `{"result":"BLOCK"}` 时，通过 OneBot `delete_msg` 撤回整条消息。

## 配置

- `group_ids`：需要审核的群号列表。只有列表中的群会被处理；留空时不审核任何群。
- `provider_id`：选择支持图片输入的 Provider。留空时使用当前群会话的 Provider。
- `ignore_self`：默认忽略机器人自己发送的图片。
- `timeout_seconds`：模型审核超时时间。调用失败、超时或返回 `REVIEW`、无法解析时默认放行。
- `max_concurrent_reviews`：同时运行的审核任务数，默认 `1`。审核在后台执行，不会阻塞群消息流水线。
- `max_pending_reviews`：最多排队的审核任务数，默认 `16`；队列满时放行新消息，避免高峰期无限积压。
- `prompt`：审核提示词，默认使用 PASS/BLOCK/REVIEW 分类规则。

QQ 动画表情会被识别为平台贴纸并跳过图片审核与视觉输入处理。普通图片仍按审核规则处理。

当前撤回实现适用于 `aiocqhttp`（OneBot）平台；其他平台会记录警告并放行，不会误删消息。
