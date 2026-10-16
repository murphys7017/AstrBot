# OLV 现场样本与计划复核依据

日期：2026-10-17；时间均为 Asia/Shanghai。用途是指导 08/09 的实施优先级，不是性能基准报告。

## 1. 来源与范围

- Core 日志：`C:/Users/Administrator/Downloads/AstrBot/data/logs/astrbot.log`，本次读取截止 02:02:59。
- 桌面日志：`C:/Users/Administrator/AppData/Roaming/ag99live-frontend/logs/ag99live/olv-latency-2026-10-16.jsonl`。
- 桌面日志文件名按 UTC 日期生成，因此文件名 10-16 可以包含北京时间 10-17 的样本。
- 只摘录身份、模式、状态和时间数据，不复制用户对话、截图、私有心理字段或凭据。
- 用户报告“第一次流式，后几次非流式，非流式体感约三秒”。本次只匹配到以下两轮，不能把它们视为覆盖用户提到的所有后续对话。
- 历史日志行号只帮助本次定位；轮转后应按完整 Turn ID 与时间重新搜索。

## 2. 两轮已匹配样本

| 项目 | 样本 A | 样本 B |
| --- | --- | --- |
| 时间 | 02:00 | 02:02 |
| frontend Turn | `input:197ca82d38c6490a8f7542b1c52aed12` | `input:771b566fbcc343079ff6f373878b922f` |
| Core Turn | `91877e1a888d40cea5a9a19b3cd2f334` | `f0a88a4dc6e549d48a2f3e6e2a3d3d10` |
| 请求模式 | 桌面流式 True | 桌面流式 False |
| 实际交付 | M1：writer 失败后的 Persona 段流 + 完整音频段 | M0：完整 Persona + 分段物化 |
| ASR 日志耗时 | 1093.8 ms | 1125.7 ms |
| Core personal_first_output_ms | 3875 | 4500 |
| Core turn_total_ms | 6640 | 5218 |
| Core persona_ms / provider_ms | 4172 / 3171 | 3421 / 2359 |
| 首段发送 epoch ms | 1792173648297 | 1792173754921 |
| 桌面首 playback 回调 epoch ms | 1792173648723 | 1792173755351 |
| Renderer capture-stop → 首 playback 回调 monotonic 差值 | 6237.0 ms | 6936.2 ms |
| 两段动作结果 | 均在 provider 阶段超时，输出 motion_state=failed | 778.3 / 1550.0 ms 就绪，payload_present=True |

以上是不同输入、输出长度及上下文的两个请求，不是成对 A/B。Core turn_total 不含用户播放完几十秒语音的时间，personal_first_output 也不是硬件发声时刻。不得把某一个列值直接叫作“端到端响应时间”。

## 3. 关键事件

1. `02:00:44.383`：Adapter 记录 Persona stream requested。
2. `02:00:46.259`：`OLV incremental output unavailable; keeping segment fallback`，reason=`incremental_output_turn_binding_invalid`，Core 日志原位置约 11463 行。
3. 样本 A 后续使用 `persona_tts` 物化段及 `output_segment_sent`，并非成功增量 PCM writer。
4. `02:00:47.205` 和 `02:00:48.167`：动作 provider 阶段 deadline 耗尽。两任务已有首 chunk，但未形成结果即被取消；说明“收到首 chunk”不等于“动作已可执行”。
5. `02:00:56.058`：`desktop_runtime_settings_synced persona_segment_stream_enabled=False`，Core 日志原位置约 11535 行。证据说明设置同步发生，不证明是谁或哪个 UI 操作改变了它。
6. `02:02:30.372`：样本 B 入口记录 stream=False，后续普通结果与分段 TTS。
7. `02:02:31.183`：样本 B `capability.schema duration_ms=326.102 selected_count=57`；base context 构建另有约 78 ms 记录。不能把所有请求准备耗时归因于记忆召回。
8. 样本 B 的两段动作分别约 0.778/1.550 秒完成。若对同量级动作一律施加 0.75 秒上限，可能使本可成功的工作被提前取消；不能据此推算所有请求都需要固定 1.55 秒预算。

## 4. 输入时间戳的口径问题

桌面文件第 11/12 行对应样本 A 的 capture/end 与首 playback；第 14/15 行对应 B。

| 计算 | A | B |
| --- | --- | --- |
| startedAtMonotonicMs − captureEndedAtMonotonicMs | 6237.0 ms | 6936.2 ms |
| playback.timestampEpochMs − capture.timestampEpochMs | 5462 ms | 6137 ms |
| 两种差值之差 | 775.0 ms | 799.2 ms |

源码解释：`microphoneRuntime.ts::stopMicrophoneCapture` 在入口保存 captureEndedAtMonotonicMs，而 capture 事件的 timestampEpochMs 在 end 队列处理、可选截图完成并发送 audio_stream_end 后才填写。两字段不是同一时点。playback 的两个字段则在同一个回调附近填写。

因此这约 0.8 秒不能直接说是时钟漂移，也不能全部说是截图耗时；它是应拆分测量的输入端等待。当前样本按同一 renderer 代码路径计算 monotonic 差值；未来必须增加 renderer instance/timeOrigin，防止重载后跨时钟域相减。

需要补充：capture_stop_requested、capture_runtime_stopped、audio_end_queue_ready、screenshot_start/end、audio_end_sent、asr_start/final、实际首采样。截图功能若启用，必须区分本轮必须的视觉输入和可选持续观察，不能为了省时间直接丢图。

## 5. 身份绑定问题的源码线索

Adapter `_commit_inbound_message` 通过 `_resolve_backend_turn_id` 选择 message_obj.message_id 等输入标识，注册 frontend→backend 映射；构造平台事件时设置 output_correlation_id，未在该处设置同一 `_turn_id`。

Core `PlatformTurnContextFactory.create` 在缺少 `_turn_id` 时创建 UUID，随后 `ensure_interaction_turn_state` 把它写回事件。

writer 用事件 `_turn_id` 与映射值比较；若输入 message ID 和实际 Core Turn UUID 不同，则准入拒绝。当前日志已证明拒绝发生，但未记录映射两端的所有值，故“具体是哪次赋值造成不一致”仍需按真实入口补齐关联证据。

修复应选择真实身份所有者与绑定时机，保留严格校验；禁止在 open writer 的失败分支强制改写映射，也禁止测试手填正确映射后当作现场修复证据。

## 6. 对实施计划的影响

- 新增 T0b，先让实际 M2 路径可达，否则优化 PCM/AudioWorklet 后仍会落到旧路径。
- 保留 M0 作为有效产品模式及性能基线，它已经具备分段准备并行，不是“所有阶段全串行”的反例。
- 对用户三秒体感继续采样，不承诺流式必然更快；短回答可能因 JSONL 元数据和会话准备成本抵消收益。
- 正确性修复不因性能样本快而取消；复杂架构改造必须先证明收益，尤其 T6–T8。
- 将 PTT 输入发送前等待和 capability schema 构建列入测量，避免只盯 Provider。
- 当前没有成功 M2 现场对照，不能报告 M2 p50/p95 或改善倍数。

## 7. 可复核读取方式

在 Core 根目录用 `rg -n` 搜索两个 Core Turn ID、两个 frontend Turn ID、`incremental_output_turn_binding_invalid` 和 `desktop_runtime_settings_synced`。只输出需要的诊断行，不输出整份 trace 或包含截图/base64 的请求正文。

桌面 jsonl 按 turnId 取 capture 及第一条 playback 事件，逐条保留行号；后续 playback 是第二段，不应重复计作首响。跨 renderer 重启或采集事件缺失的样本标记 unusable，不用最近一条其他 Turn 事件代替。
