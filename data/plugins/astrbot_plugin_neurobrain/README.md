# NeuroBrain for AstrBot

AstrBot owns Persona's eight-dimensional `tendency` input. This plugin runs one NeuroBrain model on a dedicated thread, submits Persona emotions without waiting for inference, and reads its current state into eligible prompts. Other plugins have read-only access. No NeuroBrain service or WebSocket connection is required.

This plugin targets the customized AstrBot 4.29.0-beta.1 environment used by this project. It is not a compatibility claim for unmodified upstream AstrBot.

## Source and deployment

The source of truth for this plugin is this repository at
`C:\Users\Administrator\Documents\GitHub\astrbot_plugin_neurobrain`. The copy at
`C:\Users\Administrator\Downloads\AstrBot\data\plugins\astrbot_plugin_neurobrain`
is generated deployment output. Edit the source repository and commit there; the local
`post-commit` hook runs `deploy_neurobrain.ps1` and synchronizes the plugin files into
AstrBot. Do not edit the generated copy as source.

The deployment script skips test and Python cache directories and excludes itself from the
runtime plugin. It removes stale managed plugin files but does not touch files outside this
plugin directory.

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

The model loads on its dedicated thread when the plugin initializes. It publishes an initial snapshot before becoming ready and keeps evolving without new inputs. `delta_seconds` is the positive internal update interval in seconds (default `1.0`). Each tick consumes the newest pending emotion, or uses zero stimulus if the queue is empty; a newer submission replaces any older pending input. Input submissions do not reset the tick clock; overdue ticks are skipped instead of triggering a catch-up burst. Model/checkpoint math and the tendency converter are unchanged.

Input and reading are independent. AstrBot submits exactly eight integer emotions from `0` through `10`; the converter clamps out-of-range integers and normalizes to `0..1`. The runtime keeps one pending input slot, so stale inputs are discarded before the next model tick. Each completed update replaces the published snapshot as a whole. Reads copy the last complete snapshot immediately, never wait for inference, and never advance the model. Runtime state is in memory and starts fresh after reload. A missing or invalid checkpoint leaves the plugin unready; startup errors are logged.

The live NeuroBrain state is injected as a request-local, non-persistent message
after AstrBot selects and renders the cached ContextPack, and is refreshed again
before each Persona provider request. This keeps the stable system/persona/history context reusable while each Persona request reads the
latest state. It explicitly targets Persona only and never enters Core Planner,
Core Router, or Personal Policy. The default `plugin_set=["*"]` allows this plugin; if using a
plugin whitelist, include `astrbot_plugin_neurobrain` and ensure the current
session has not disabled it.

## Application API

There is one model and one current state. No session ID, Persona ID, state key, result ID, or result-wait API is needed.

AstrBot owns emotion input. The normal Persona result hook submits each completed
segment once, and the OLV streaming hook submits each validated `segment_start`
intent once before speech delivery:

```python
plugin.submit_emotion({
    "Joy": 3, "Trust": 4, "Fear": 0, "Surprise": 1,
    "Sadness": 0, "Disgust": 0, "Anger": 0, "Anticipation": 2,
})
```

Other plugins only read:

```python
metadata = context.get_registered_star("astrbot_plugin_neurobrain")
plugin = metadata.star_cls if metadata is not None else None
state = plugin.readonly_api.get_state() if plugin else None
```

The detached snapshot contains `emotion`, `behavior`, `step`, `protocol_version`, `updated_at`, and `last_tendency`. `None` means the model has not initialized (or the plugin has stopped), not that an update is in progress. Both AstrBot prompts and AG99live read current state independently of the current Persona result. No separate server is used.

## License

This plugin is licensed under the MIT License. See [LICENSE](LICENSE).
