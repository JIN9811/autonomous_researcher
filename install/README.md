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
atr model load e2b
atr model load 31b
atr model unload e4b
atr model unload e2b
atr model unload 31b
```

Live GUI chat API:

```bash
atr chat bootstrap "Plan a PLA compression specimen experiment"
atr chat "테스트 모드"
atr chat "실험 수행"
```

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
