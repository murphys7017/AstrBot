# NeuroBrain for AstrBot

AstrBot owns Persona's eight-dimensional `tendency` input. This plugin updates an in-process NeuroBrain session after each Persona result, reads the latest state into every eligible model prompt, and exposes a read-only API to other AstrBot plugins. No NeuroBrain service or WebSocket connection is required.

This plugin targets the customized AstrBot 4.29.0-beta.1 environment used by this project. It is not a compatibility claim for unmodified upstream AstrBot.

## Install

Install the local NeuroBrain package into AstrBot's Python environment. From the AstrBot repository root:

```powershell
$neuroBrainRepo = "C:\path\to\NeuroBrain"
git clone https://github.com/murphys7017/NeuroBrain.git $neuroBrainRepo
git -C $neuroBrainRepo checkout 368e4b730a770cf76bf3dcf66d58a43975f5ab0b
uv pip install --python .venv\Scripts\python.exe --no-deps $neuroBrainRepo
```

The AstrBot environment must also contain the NeuroBrain runtime dependencies from AstrBot's project configuration. The tracked CUDA 13.0 wheels are resolved only for Linux `x86_64/aarch64` and Windows `AMD64`; macOS and Windows ARM do not receive the CUDA runtime required by this current plugin. Whether the full AstrBot environment installs on another platform still depends on the wheels available for its other dependencies. Restart AstrBot after installing or replacing Python packages so the running process loads the installed package. Installing the plugin repository alone does not install NeuroBrain or its CUDA runtime dependencies.

NeuroBrain is installed from a local repository and is not pinned as an AstrBot lockfile dependency. Repeat the install command after any full environment sync that removes packages outside AstrBot's lockfile.

In the plugin settings, set `checkpoint_path` to a trained checkpoint for the Persona being used. The repository's current `kurisu-two-volumes-baseline-cfc512.pt` checkpoint was trained from Kurisu material; do not use it as an Alice pro checkpoint. Leave the path empty until a suitable checkpoint is available. `device=auto` selects CUDA when PyTorch reports it available and otherwise uses CPU.

The model loads when AstrBot loads or hot-reloads the plugin, so saving the plugin configuration applies a new `checkpoint_path`, device, or delta interval on the next reload. Persona updates run through NeuroBrain's asynchronous state store, with inference dispatched to a worker thread. Prompt collection is dynamic and reads the latest snapshot on every prompt build; reads never advance model state. If no checkpoint is configured or loading fails, the plugin logs the reason and omits NeuroBrain state from prompts.

Prompt extensions follow AstrBot's plugin admission policy. The default `plugin_set=["*"]` allows this plugin; if using a plugin whitelist, include `astrbot_plugin_neurobrain` and ensure the current session has not disabled it.

## State Scope

`state_scope` determines which continuous state is updated and read:

- `persona`: one state per active Persona; this is the default.
- `conversation`: one state per AstrBot conversation.
- `global`: one state shared by all conversations.

Each Persona speech segment advances the selected state once. AstrBot's tendency converter clamps integer values below `0` to `0` and above `10` to `10`, then normalizes them to NeuroBrain's `0..1` inputs.

## Read-Only API

Other plugins can read current snapshots without advancing NeuroBrain:

```python
metadata = context.get_registered_star("astrbot_plugin_neurobrain")
plugin = metadata.star_cls if metadata is not None else None
state = plugin.readonly_api.get_state("persona:Alice pro") if plugin else None
```

`get_state()`, `list_states()`, and `fetch_state()` read the in-process state. `wait_for_persona_result()` waits for the update associated with one AstrBot Persona result and returns that result's snapshot; AG99live uses this on its third motion chain. State writes remain owned by the NeuroBrain plugin.

## License

This plugin is licensed under the MIT License. See [LICENSE](LICENSE).
