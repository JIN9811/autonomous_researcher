# Install

This folder contains setup notes and launchers for the local
`autonomous_researcher` checkout.

ATR supports two inference modes:

- Local-first: use `vllm`, `ollama`, or `nemoclaw` first, then fall back to the
  OpenAI API when `configs/models.yaml` sets `backend.fallback: openai`.
- API-only: set `AUTONOMOUS_BACKEND=openai` in `.env` to skip local AI entirely.

`openai` is intentionally the lowest-priority static fallback unless the
operator explicitly selects it as the active backend or enables the Main GUI
`API Key` Loading control. When that API-key cell is loaded, OpenAI becomes the
first inference route until it is unloaded again.

## Recommended Fresh-Install Flow

Use this order on a new PC:

1. Clone the private repository.
2. Run the platform bootstrap for the host OS.
3. Run `doctor` to see which optional device/tool dependencies are still
   missing.
4. Install only the external runtimes needed for that workstation: local AI,
   Bambu/Prusa slicing, LeRobot/RealSense, Windows equipment bridge, or graph
   database.

Linux/WSL default:

```bash
git clone <private-repo-url> autonomous_researcher
cd autonomous_researcher
bash install/bootstrap_linux.sh
atr doctor
atr up
```

Windows supported path:

```powershell
git clone <private-repo-url> autonomous_researcher
cd autonomous_researcher
powershell -ExecutionPolicy Bypass -File .\install\bootstrap_windows.ps1
python -m app.serve
```

Windows limitations:

- Native Windows is the supported path for API-key GUI/API use and the
  Windows PyAutoGUI bridge server.
- The Linux `atr` launcher is intended for Linux, WSL, or Git Bash. Native
  Windows starts the backend with `python -m app.serve`.
- LeRobot live hardware, RealSense RSUSB, local NemoClaw/vLLM, Dockerized
  solvers/slicers, and Linux device permissions require WSL/Linux or separate
  conda/toolchain setup.
- Hardware memory files such as `memory/bambu_connection.json`,
  `memory/prusa_connection.json`, and `memory/lerobot_device_ports.json` are
  intentionally not copied through Git. Recreate them from the GUI on each PC.

The doctor command is non-actuating. It does not start printers, robots, model
servers, or camera streams:

```bash
atr doctor
atr doctor --core-only
atr doctor --json
```

Before installing `atr`, run the same check directly:

```bash
.venv/bin/python scripts/doctor.py
```

Supported distribution model:

- The supported operator install is a source checkout plus `.venv`.
- `python -m build` is kept as a packaging sanity check so Python package
  discovery does not accidentally include runtime artifacts, but the generated
  wheel is not the primary deployment artifact for the full GUI/device system.
- Do not delete the source checkout after installing dependencies; runtime
  config, web templates, graph YAML, install helpers, and local memory folders
  are expected to remain under the repository root.

## Windows Quick Start (API Key, No Local AI)

Use this path when running the GUI/API on Windows and using an API key instead
of a local model server.

### 1. Install System Tools

Required:

- Windows 10/11 64-bit
- Git for Windows
- Python 3.11 or newer, installed with the `py` launcher
- PowerShell 5.1 or PowerShell 7+
- An OpenAI API key

Recommended:

- Miniconda or Mambaforge for LeRobot and solver-specific environments
- Microsoft C++ Build Tools only if a Python dependency has to build from source
- PrusaSlicer for local slicing, or Docker Desktop if using Linux containers

### 2. Create the Main Python Environment

Run from PowerShell:

```powershell
cd C:\Users\user\Documents\autonomous_researcher
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

If your Python command is not `py -3.11`, use the installed Python 3.11+ path.

### 3. Configure API-Key Inference

Create `.env` from the example:

```powershell
Copy-Item .env.example .env
notepad .env
```

Keep real API keys in `.env` only. `.env.example` is tracked by Git and must
keep secret values blank.

For API-only Windows operation, set:

```text
AUTONOMOUS_BACKEND=openai
OPENAI_API_KEY=<your-api-key>
AUTONOMOUS_OPENAI_ORCHESTRATOR_MODEL=gpt-5.5
AUTONOMOUS_OPENAI_E4B_MODEL=gpt-5.5
AUTONOMOUS_MODULE_DESIGNER_MODEL=
```

Leave `AUTONOMOUS_MODULE_DESIGNER_MODEL` blank to use the active backend route.
Set it only when you want Module Designer to force a specific model.

If you want local-first behavior with OpenAI as the final fallback, keep:

```text
AUTONOMOUS_BACKEND=vllm
OPENAI_API_KEY=<your-api-key>
```

Then ATR tries the active local backend and its model fallback first; OpenAI is
used only after those fail.

### 4. Start the Server on Windows

```powershell
.\.venv\Scripts\Activate.ps1
python -m app.serve
```

Open:

```text
http://127.0.0.1:7860/
http://127.0.0.1:7860/live
http://127.0.0.1:7860/docs
```

Stop the server with `Ctrl+C` in the PowerShell window.

The Bash `atr` launcher below is for Linux, WSL, or Git Bash. Native Windows can
run the same backend through `python -m app.serve` and the browser UI.

### 5. Windows LeRobot Conda Environment

LeRobot workflows must run outside the main `.venv` in a conda environment.
The ATR bridge invokes them with:

```text
conda run --no-capture-output -n lerobot ...
```

Create the environment:

```powershell
$conda = "$env:USERPROFILE\miniconda3\Scripts\conda.exe"
winget install -e --id Anaconda.Miniconda3 --scope user
& $conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
& $conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
& $conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/msys2
& $conda create -y -n lerobot python=3.10
& $conda run -n lerobot python -m pip install --upgrade pip
```

Clone and install the LeRobot checkout outside this repository, then install it
editable inside the `lerobot` environment according to the LeRobot version you
are using. In ATR, keep these defaults unless your local setup differs:

```yaml
configs/lerobot.yaml:
  conda_executable: conda
  conda_env_name: lerobot
```

When `conda_executable` is left as `conda`, ATR first uses `conda` from PATH and
then auto-detects common user installs such as
`%USERPROFILE%\miniconda3\Scripts\conda.exe`.

For SmolVLA training/rollout experiments, install the LeRobot extra and cache
the required Hub repos in that same `lerobot` environment:

```bash
cd /home/jin/lerobot
conda run --no-capture-output -n lerobot python -m pip install -e ".[smolvla]"
conda run --no-capture-output -n lerobot hf download lerobot/smolvla_base --max-workers 1
conda run --no-capture-output -n lerobot hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct --exclude "onnx/*" --max-workers 1
```

Use the `/lerobot` GUI page for port detection, teleoperation, recording,
training, and rollout. Hardware actions still require live confirmation gates.

### 6. Optional Windows Equipment Bridge

If this same or another Windows PC controls UTM software through PyAutoGUI, run:

```powershell
py -m pip install pyautogui pywinauto Pillow
$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = "<random-token>"
py install\windows_pyautogui_bridge_server.py
```

Save the bridge URL/token from `http://127.0.0.1:7860/equipment/windows`.

## Linux / WSL Quick Start

Use this path on Linux workstations, WSL, or Git Bash environments.

```bash
cd /path/to/autonomous_researcher
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
cp .env.example .env
```

For API-only operation:

```bash
printf '\nAUTONOMOUS_BACKEND=openai\nOPENAI_API_KEY=<your-api-key>\n' >> .env
python -m app.serve
```

For local-first operation with OpenAI as final fallback:

```bash
printf '\nAUTONOMOUS_BACKEND=vllm\nOPENAI_API_KEY=<your-api-key>\n' >> .env
python -m app.serve
```

Install the optional `atr` terminal launcher only on Linux, WSL, or Git Bash:

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
atr backend openai
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

`atr module create` sends the Python file to the same `/api/modules` Module
Designer endpoint used by the GUI. The active backend's `module_designer` route
primary model is used first, its model fallback is used second, and if
`backend.fallback: openai` is configured the OpenAI API model is tried last.
The endpoint writes
`graphs/modules/<module-id>/handler.py`, stores the original source beside it
for audit, writes `module.yaml`, saves a version under
`memory/module_versions/<module-id>/`, then leaves execution bound to an
allowlisted handler. If the generated handler is not registered yet, the module
remains `pending_handler_registration` and uses `runtime.step_complete` until
explicit `atr module register-generated <module-id>` approval.

Windows PyAutoGUI bridge standalone deployment:

Do not copy only `install/windows_pyautogui_bridge_server.py`; recording,
image matching, the capability lab, and examples require the complete
`Pyautogui_server_for_window` package. On Windows, run:

```text
Double-click: Pyautogui_server_for_window\INSTALL_WINDOWS_BRIDGE.cmd
```

PowerShell alternative:

```powershell
cd .\Pyautogui_server_for_window
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_bridge.ps1 -OpenBrowser -ShowToken
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

## Bambu Studio Wrapper

The Bambu Lab X2D bridge resolves the slicer executable in this order:

1. `BAMBU_STUDIO_EXECUTABLE`
2. `install/bambustudio/bambu-studio-wrapper`
3. `PATH` names such as `bambu-studio` or `BambuStudio`

The repository-local wrapper is:

```text
install/bambustudio/bambu-studio-wrapper
```

It does not install Bambu Studio. It finds an existing Bambu Studio executable
from `BAMBU_STUDIO_EXECUTABLE`, `PATH`, common user install locations, `/opt`,
or Flatpak `com.bambulab.BambuStudio`, then forwards all slicer arguments
unchanged.

Recommended Linux setup:

```bash
export BAMBU_STUDIO_EXECUTABLE=/absolute/path/to/bambu-studio
install/bambustudio/bambu-studio-wrapper --help
atr doctor
```

If `atr doctor` reports that only the wrapper exists but Bambu Studio itself is
missing, install Bambu Studio or set `BAMBU_STUDIO_EXECUTABLE`. The 3DP GUI can
still run MQTT/status checks without slicing, but it cannot honestly generate a
new Bambu-native sliced artifact until the CLI path resolves.

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

## LeRobot D405 / RSUSB Patch Packaging

ATR does not vendor the external LeRobot repository. Live ROBOTIS/RealSense
workflows use a separate checkout, usually `~/lerobot`.

This repository packages the current Spark workstation RealSense D405/RSUSB
compatibility patch at:

```text
patches/lerobot/spark_realsense_d405_rsusb.patch
```

Apply it to the external LeRobot checkout with:

```bash
bash install/apply_lerobot_d405_patch.sh ~/lerobot
```

The apply script runs `git apply --check` first and stops without changing the
checkout if the patch does not match the current LeRobot branch. If that
happens, update the LeRobot branch/version deliberately; do not replace D405
with `/dev/video*` or OpenCV fallback.

After the patch, RealSense recording keeps the standard 8-bit LeRobot depth
video features and, when ATR passes `ATR_LEROBOT_RAW_DEPTH_DIR`, also writes
16-bit raw Z16 sidecars at
`<dataset>/sidecar/depth_raw/<camera_key>/frame_*.png`. It also writes
`<dataset>/sidecar/depth_raw/transform_manifest.json`, which records the
production RGB-D contract: depth aligned to color, metric scale
`0.001 m/unit`, and fixed visual-depth clipping range `0..2000 mm` unless
`configs/lerobot.yaml` is deliberately changed.

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
