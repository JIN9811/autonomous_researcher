<a id="install"></a>

# Install and reach your first virtual experiment

Use this guide to prepare a workstation, open AX4LAB and complete a first virtual
experiment. You do not need a printer, robot, camera or local model server for the
API-only path. Add those integrations after the core application works.

Keep the source checkout: the supported operator installation is the repository
plus its `.venv`, not a standalone wheel. Configuration, web templates, graph YAML,
install helpers and local memory directories are read from that checkout.
`python -m build` remains a packaging sanity check, not the deployment procedure.

Choose the inference route before installing optional runtimes:

| Route | What to prepare | How it is selected |
|---|---|---|
| API-only | An OpenAI API key and network access | `AUTONOMOUS_BACKEND=openai` in `.env` |
| Local-first | A configured `vllm`, `ollama` or `nemoclaw` server | Select the local backend; `backend.fallback: openai` in `configs/models.yaml` permits API fallback |

With local-first routing, the active local model and its model fallback are tried
before the OpenAI fallback. Explicitly selecting `openai`, or loading Main's
`API Key` cell, makes OpenAI the first route; unloading that cell removes the
temporary preference. Installing a local runtime alone does not select it.

## Recommended Fresh-Install Flow

The bootstrap is the normal installation path. The manual environment commands
in the OS sections below are alternatives for an existing checkout, not a second
installation to run after bootstrap.

After bootstrap, follow only your OS path:
[Windows API-only configuration](#windows-quick-start-api-key-no-local-ai) or
[Linux/WSL configuration](#linux--wsl-quick-start). Both lead to the same virtual
first-run exercise before any optional device installation.

1. Clone the private repository and enter it.
2. Run the bootstrap for your host OS.
3. Configure private inference credentials using the matching OS section below.
4. Run the non-actuating readiness check, start the server, then follow
   [your first virtual experiment](#complete-the-first-run).

Linux or WSL:

```bash
git clone <private-repo-url> autonomous_researcher
cd autonomous_researcher
bash install/bootstrap_linux.sh
```

Windows supported path:

```powershell
git clone <private-repo-url> autonomous_researcher
cd autonomous_researcher
powershell -ExecutionPolicy Bypass -File .\install\bootstrap_windows.ps1
```

Choose the host that fits the work you intend to do:

- Native Windows is the supported path for API-key GUI/API use and the
  Windows PyAutoGUI bridge server.
- The Linux `atr` launcher is intended for Linux, WSL, or Git Bash. Native
  Windows starts the backend with `python -m app.serve`.
- LeRobot live hardware, RealSense RSUSB, local NemoClaw/vLLM and Dockerized
  slicers need WSL/Linux or their separately prepared conda/toolchain environment.
  Linux device permissions are configured on the Linux host, not in PowerShell.
- Hardware memory files such as `memory/bambu_connection.json`,
  `memory/prusa_connection.json`, and `memory/lerobot_device_ports.json` are
  intentionally not copied through Git. Recreate them from the GUI on each PC.

After configuration, use `doctor` to distinguish missing core dependencies from
optional capabilities you have not chosen to install. It does not start printers,
robots, model servers or camera streams:

```bash
atr doctor
atr doctor --core-only
atr doctor --json
```

Before installing `atr`, run the same check directly:

```bash
.venv/bin/python scripts/doctor.py
```

On native Windows, use `.\.venv\Scripts\python.exe scripts/doctor.py --core-only`.
Resolve a core failure before proceeding. A missing printer or LeRobot dependency
is not a reason to install every optional stack for an API-only virtual exercise.
Use [Requirements](../REQUIREMENTS.md) for dependency/version details. The active
application requires no graph database; runtime graph YAML is a different feature.

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

Only if your later work needs them:

- Miniconda or Mambaforge for LeRobot environments
- Microsoft C++ Build Tools only if a Python dependency has to build from source
- PrusaSlicer for local slicing, or Docker Desktop if using Linux containers

### 2. Create the Main Python Environment

If bootstrap already created `.venv` and installed requirements, skip this step.
For manual setup, enter your actual checkout path in PowerShell:

```powershell
cd "$env:USERPROFILE\Documents\autonomous_researcher"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

If your Python command is not `py -3.11`, use the installed Python 3.11+ path.

### 3. Configure API-Key Inference

Create `.env` from the example only if it does not already exist. Otherwise edit
the existing file so that you retain its private settings:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
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

Open Main first:

```text
http://127.0.0.1:7860/
```

When Main loads, continue to [complete the first run](#complete-the-first-run).
`/live` opens the Live conversation and `/docs` opens the documentation, but loading
a page is not proof that a model is ready or a run has started. Stop the server
with `Ctrl+C` in this PowerShell window only after active work has finished.

The Bash `atr` launcher below is for Linux, WSL, or Git Bash. Native Windows can
run the same backend through `python -m app.serve` and the browser UI.

## Linux / WSL Quick Start

Use this manual alternative on Linux or WSL if you did not run bootstrap. Git Bash
can use the Bash launcher, but it does not supply Linux hardware/runtime support.

```bash
cd /path/to/autonomous_researcher
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
```

Edit `.env` in your editor. Keep one intentional value for each key and never put
real credentials in the tracked `.env.example`. For API-only operation, set:

```text
AUTONOMOUS_BACKEND=openai
OPENAI_API_KEY=<your-api-key>
```

For an already configured local-first backend, set:

```text
AUTONOMOUS_BACKEND=vllm
OPENAI_API_KEY=<your-api-key>
```

API fallback additionally needs `backend.fallback: openai` in `configs/models.yaml`.
You may start with `python -m app.serve` from the activated environment, or install
the convenience launcher below. Bootstrap users can skip launcher installation
if `atr` already resolves to this checkout.

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

After the readiness check, start the server from a terminal:

```bash
atr up
```

Open `http://localhost:7860`. Keep the terminal available for startup errors.
If another instance is already serving an experiment, use that instance rather
than restarting it. Once the page loads, follow the first-run section below.

### Complete the first run

Main should show **Run Control** and the model/backend controls. Select the prepared
inference route, then use the [English first-run walkthrough](../docs/tutorials/first_autonomous_run.en.md)
or [한국어 첫 실험 안내](../docs/tutorials/first_autonomous_run.ko.md). It takes you through
**Test Mode Settings → Virtual Bridge**, one cycle, plan review, stage evidence and
saved output. **Test mode alone is not hardware-free**: Installed Printer can send
an ejection-only artifact, and Physical Print uses the full print path. Per-agent
boundaries also matter.

The installation journey is complete when you can open the resulting run's
artifacts and identify its terminal result, not merely when the server starts.
For a blocked run, retain its ID and failure details and use
[run recovery](../docs/gui/run_resume.md); restarting the server is not Resume.

### Shut down after active work finishes

On Linux/WSL, stop this checkout's server with:

```bash
atr down
```

`atr down` targets this checkout's `app.serve` process. During clean shutdown, the server releases LeRobot live subprocesses tied to this checkout so stale teleoperation/recording jobs do not keep cameras or serial ports open.

Use `atr restart` to run the same `down` command followed by `up`. If `down` fails, it does not start a replacement. Existing shutdown/cleanup behavior and `ATR_DOWN_FORCE` apply unchanged; the restarted server runs in the foreground like `atr up`. Finish active work before using it.

## CLI Help

Show every available command:

```bash
atr
```

## Common Commands

The following is a lookup reference, not a sequence to execute during installation.
Begin with read-only navigation and status; the later groups change configuration,
load models or control runs.

Open GUI pages (without starting an experiment):

```bash
atr gui
atr live
atr docs
```

Runtime status:

```bash
atr status
atr events
```

Run control changes execution state. Check the saved profile and per-agent physical
boundaries before `start`, including `start test`. A resume continues an eligible
existing run and can repeat a recovery step; it is not a new start.

```bash
atr run start test
atr run start live "PLA compression specimen"
atr run pause
atr run resume
atr run stop
atr run safe-stop
```

Inspect or change the inference backend:

```bash
atr backend
atr backend vllm
atr backend nemoclaw
atr backend ollama
atr backend openai
```

GPU/model control changes model availability; do not unload a model in active use:

```bash
atr gpu clear
atr models
atr model load e4b
atr model load 31b
atr model unload e4b
atr model unload 31b
```

Live GUI chat API submits planning/execution requests through the conversation.
These are not read-only status commands:

```bash
atr chat bootstrap "Plan a PLA compression specimen experiment"
atr chat "테스트 모드"
atr chat "실험 수행"
```

### Advanced: runtime graphs and modules

For inspecting workflow composition, use the [Runtime IDE guide](../docs/runtime/runtime_ide.md).
The commands below are the CLI counterpart. Validation and inspection are distinct
from saving, activating or running an edited graph; do not modify the active loop
as an installation check.

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
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_supervisor.ps1
```

From **Main → Device Workspaces → Windows Automation** (`/equipment/windows`),
scan the internal network, select the Windows PC, enter its four-digit code, and
use **Pair & Save**. Running `program1` is a
separate operator-triggered check, not part of discovery or pairing.

<a id="5-windows-lerobot-conda-environment"></a>

## Optional: Windows LeRobot Conda Environment

This is a separate device setup task, not step five of API-only installation.
Finish the virtual exercise first unless you are commissioning a robot workstation.

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

For SmolVLA training/rollout experiments, the tracked `smolvla_conda_env_name`
uses the isolated `lerobot-pi05-torch211` environment. Prepare that environment
as described in [Requirements](../REQUIREMENTS.md#optional-smolvla-training-branch),
then install the extra and cache the required Hub repos there. The following is
a **Linux/WSL** example for that external checkout, not a PowerShell continuation:

```bash
cd ~/lerobot_pi05
conda run --no-capture-output -n lerobot-pi05-torch211 python -m pip install -e ".[smolvla]"
conda run --no-capture-output -n lerobot-pi05-torch211 hf download lerobot/smolvla_base --max-workers 1
conda run --no-capture-output -n lerobot-pi05-torch211 hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct --exclude "onnx/*" --max-workers 1
```

Use the `/lerobot` GUI page for port detection, teleoperation, recording,
training, and rollout. Hardware actions still require live confirmation gates.

<a id="6-optional-windows-equipment-bridge"></a>

## Optional Windows Equipment Bridge

If this same or another Windows PC controls UTM software through PyAutoGUI,
copy the complete bridge package and install it in an interactive Windows session:

```powershell
.\Pyautogui_server_for_window\INSTALL_WINDOWS_BRIDGE.cmd
```

Pair the selected worker with its one-time four-digit console code in Linux
ATR's **Main → Device Workspaces → Windows Automation** workspace. Do not distribute
a model/API key to Windows.
See [Windows bridge setup](../Pyautogui_server_for_window/README.md).

## Packaged Piper TTS

The remaining sections install optional capabilities. Choose the printer, robot
or voice integration you actually use; none is required for the first API-only
virtual run.

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

This overrides inference routing, not the hardware boundary. The example starts a
test run using its saved execution profile; inspect that profile first.

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

## If setup stops here

| What you see | What to check next |
|---|---|
| `atr` is not found | Open a new terminal after launcher installation; check shell PATH and the installed checkout path |
| Main does not load | Read server startup output and confirm the URL/port before attempting device actions |
| Main loads but inference fails | Selected backend, private key, model availability and provider quota; a GUI page alone does not test inference |
| Doctor reports an optional stack missing | Install it only if the selected workflow uses it; consult the corresponding Requirements section |
| Slicer wrapper exists but slicing fails | The wrapper is not the slicer; resolve the actual executable and selected printer profile |
| Connection settings disappeared on a new PC | Recreate private `memory/` settings in the appropriate workspace; they are intentionally absent from Git |

For device operation after installation, use the
[operator manual](../docs/tutorials/user_manual.en.md) or
[한국어 운영 안내](../docs/tutorials/user_manual.ko.md). For contributing code, see
[CONTRIBUTING](../CONTRIBUTING.md).

Source audit: 2026-09-29 against `dd0d772`. That review did not install software,
restart services or commission hardware. The editorial restructuring does not
constitute a new installation or physical verification.
