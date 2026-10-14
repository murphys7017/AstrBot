# Package Manager Deployment (uv)

Use `uv` to install and run AstrBot quickly.

## Before You Start

If `uv` is not installed, install it first by following the official guide:
<https://docs.astral.sh/uv/>

`uv` supports Linux, Windows, and macOS.

This project’s in-process NeuroBrain integration also uses fixed CUDA 13.0 PyTorch wheels.
`uv sync` installs those wheels only on Linux `x86_64/aarch64` and Windows `AMD64`.
macOS and Windows ARM are not blocked by those CUDA requirements, but the current NeuroBrain
plugin does not receive a usable CUDA runtime on those platforms. Whether the full AstrBot
environment installs on another platform still depends on wheel support for its other
dependencies; use `uv`'s resolution result as the source of truth.

## Important Notes

> [!WARNING]
> AstrBot deployed via `uv` **does not support upgrading through the WebUI**. To update, run `uv tool upgrade astrbot --python 3.12` from the command line.

AstrBot requires Python 3.12 or later. Use `--python 3.12` to ensure that `uv` creates the tool environment with Python 3.12; if Python downloads are enabled, `uv` will download Python 3.12 automatically when it is missing.

## Install and Start

```bash
uv tool install astrbot --python 3.12
astrbot
```
