# Install

This folder installs the terminal command for the local `autonomous_researcher` checkout.

## Install `atr`

Run from the repository root:

```bash
bash install/install_cli.sh
```

The installer creates:

```text
~/.local/bin/atr
```

It also adds `~/.local/bin` to your shell rc file if needed.

If this is the first time `~/.local/bin` was added to PATH, open a new terminal or run:

```bash
source ~/.bashrc
```

For zsh:

```bash
source ~/.zshrc
```

## Start Server

From any terminal:

```bash
atr up
```

Stop the server from any terminal:

```bash
atr down
```

`atr down` targets this checkout's `app.serve` process. During clean shutdown, the server releases LeRobot live subprocesses tied to this checkout so stale teleoperation/recording jobs do not keep cameras or serial ports open.

## CLI Help

Show every available command:

```bash
atr
```

## Common Commands

Open GUI pages:

```bash
atr gui
atr live
atr docs
atr down
```

Runtime status:

```bash
atr status
atr events
```

Run control:

```bash
atr run start test
atr run start live "PLA compression specimen"
atr run pause
atr run resume
atr run stop
atr run safe-stop
```

Inference backend:

```bash
atr backend
atr backend vllm
atr backend nemoclaw
atr backend ollama
```

GPU/model control:

```bash
atr gpu clear
atr models
atr model load e4b
atr model load 31b
atr model unload e4b
atr model unload 31b
```

Live GUI chat API:

```bash
atr chat bootstrap "Plan a PLA compression specimen experiment"
atr chat "테스트 모드"
atr chat "실험 수행"
```

Runtime graph management:

```bash
atr graphs
atr graph show atr_closed_loop
atr graph validate atr_closed_loop
atr graph compile atr_closed_loop
atr graph dry-run atr_closed_loop
atr graph gate atr_closed_loop
atr graph export-yaml atr_closed_loop /tmp/atr_closed_loop.yaml
atr graph import-yaml atr_closed_loop /tmp/atr_closed_loop.yaml
atr graph save-yaml atr_closed_loop /tmp/atr_closed_loop.yaml
atr graph save-yaml atr_closed_loop /tmp/atr_closed_loop.yaml --no-activate
atr graph run atr_closed_loop test "candidate route smoke"
```

Runtime graph commands call the same `/api/graphs` endpoints used by the Runtime IDE. A graph edited in the browser is visible from `atr graph show`; a graph saved from `atr graph save-yaml` is versioned and reflected in the browser after reload. `save-yaml` validates, stores a version under `memory/runtime_graph_versions/<graph-id>/`, and activates the graph unless `--no-activate` is passed.

Runtime module management:

```bash
atr modules
atr module show design
atr module validate design
atr module dry-run design
atr module load design
atr module unload design
atr module versions design
atr module version design 20260526T000000000000Z
atr module save-yaml design graphs/modules/design/module.yaml
atr module save-yaml design graphs/modules/design/module.yaml --no-activate
atr module register-generated my_internal_module
atr module create ./my_internal_module.py my_internal_module "My Internal Module"
```

Module management commands call the same `/api/modules` endpoints used by the Module Management Tool. `load` and `unload` only change the management workspace state; they do not delete files or modify the executable graph. `save-yaml` validates the module payload, performs the non-device module dry-run, saves a version under `memory/module_versions/<module-id>/`, and activates the YAML unless `--no-activate` is passed. `register-generated` is the explicit approval step for Module Designer output: it statically checks `handler.py`, flips the module handler to `module.generated_adapter`, removes staging-only `runtime.step_complete` internal-step handlers, records a version, and enables runtime execution through the generated adapter wrapper.

`atr module create` sends the Python file to the same `/api/modules` Module Designer endpoint used by the GUI. By default the API asks Gemma 31B (`gemma4:31b`) to convert the uploaded source into an ATR protocol adapter, writes `graphs/modules/<module-id>/handler.py`, stores the original source beside it for audit, writes `module.yaml`, saves a version under `memory/module_versions/<module-id>/`, then leaves execution bound to an allowlisted handler. If the generated handler is not registered yet, the module remains `pending_handler_registration` and uses `runtime.step_complete` until explicit `atr module register-generated <module-id>` approval.

Windows PyAutoGUI bridge helper:

```text
install/windows_pyautogui_bridge_server.py
```

Copy this file to the Windows PC, then run in PowerShell:

```powershell
$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = "<random-token>"
py windows_pyautogui_bridge_server.py
```

From the Live GUI, open `Windows Bridge` to scan the internal network, select the Windows PC, save the connection, and test `program1`.

## Packaged Piper TTS

LeRobot recording voice cues use ATR-packaged Piper English TTS by default.
Install or repair the local runtime and voice model from the repository root:

```bash
bash install/install_piper_tts.sh
```

This installs `piper-tts` into `.venv`, downloads the `en_US-lessac-medium`
voice to `models/tts/piper/en_US-lessac-medium`, and verifies synthesis without
requiring the LeRobot conda environment to install Piper.

## PrusaSlicer Docker Wrapper

The Prusa MK4S printer bridge can use a Dockerized PrusaSlicer when host-native PrusaSlicer is not installed.

Build the image from the repository root:

```bash
docker build -t atr-prusa-slicer:ubuntu24.04 install/prusaslicer
```

The wrapper is:

```text
install/prusaslicer/prusa-slicer-docker
```

`configs/devices.yaml` uses this wrapper as the fallback `slicer.executable_path`. If `PRUSA_SLICER_EXECUTABLE` is set, that environment variable overrides the wrapper.

The wrapper mounts this repository into the container and runs PrusaSlicer without shell expansion. Keep generated G-code under repository paths so the container can write it.

For live Prusa MK4S communication, store connection values in:

```text
memory/prusa_connection.json
```

Do not put passwords in docs, prompts, command history, or runtime logs.

## Environment Variables

Use a different server URL:

```bash
ATR_URL=http://127.0.0.1:7860 atr status
```

Use a different backend for `run` and `chat` commands:

```bash
ATR_BACKEND=vllm atr run start test
```

## Reinstall After Moving The Repo

The generated `atr` command stores the repository path from install time.
If you move the repository, reinstall:

```bash
bash install/install_cli.sh
```

## Existing `atr` Command Conflict

The installer refuses to overwrite another `atr` found outside `~/.local/bin/atr`.
Force install only if you know the existing command is safe to replace:

```bash
ATR_FORCE_INSTALL=1 bash install/install_cli.sh
```
