# NeuroBrain Bridge

这是 AG99 专用桥接插件。AstrBot 负责产生并校验 Persona 的八维 `tendency`，插件把结构化结果发送到独立 NeuroBrain WebSocket 服务；插件本身不导入 PyTorch、CUDA 或 `ncps`。

## 启动顺序

在 NeuroBrain 自己的虚拟环境中启动服务：

```powershell
$env:NEUROBRAIN_WRITE_TOKEN = "replace-with-a-long-random-secret"
uv run --locked python scripts/neurobrain_server.py `
  --checkpoint artifacts/kurisu-two-volumes-baseline-cfc512.pt `
  --device cpu `
  --host 127.0.0.1 `
  --port 8765 `
  --write-token $env:NEUROBRAIN_WRITE_TOKEN
```

然后在 AstrBot 中启用本插件，并把同一令牌填入 `write_token`。Persona 结果提交在后台执行，不会等待 NeuroBrain 服务响应；服务不可用时会记录警告，AG99live 本轮动作上下文会跳过 NeuroBrain 状态。

## 只读状态

其他插件通过已加载的插件实例读取，不应调用写入方法：

```python
metadata = context.get_registered_star("astrbot_plugin_neurobrain")
plugin = metadata.star_cls if metadata is not None else None
state = plugin.readonly_api.get_state("persona:Alice pro") if plugin else None
```

`get_state()`、`list_states()` 都只读取桥接插件缓存，不推进模型。需要主动从服务查询时使用异步 `await plugin.readonly_api.fetch_state(state_key)`。

服务端必须配置非空 writer token，匿名写入会被拒绝。reader 未配置读令牌时可以直接读取；配置了读令牌后，reader 需提供读令牌或 writer token。
