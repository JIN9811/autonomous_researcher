# Autonomous Researcher Requirements

This file lists non-Python installation requirements, external checkouts, local
services, model downloads, and device-side programs required by this repository.

Use `requirements.txt` only for Python packages installed into the main
`autonomous_researcher` virtual environment.

## Core Workstation

Required for the main GUI/API:

- Windows 10/11, Linux, WSL, or another Python 3.11+ workstation.
- Python 3.11 or newer for the main ATR environment.
- `git`.
- `curl` for CLI/API checks.
- Python virtual environment support:
  - Windows: `py -3.11 -m venv .venv`
  - `python3 -m venv .venv`
  - `pip install -r requirements.txt`
- API key based inference, normally through `OPENAI_API_KEY`, when local AI is
  unavailable or intentionally skipped.

Optional but commonly used:

- `conda` or Miniconda for LeRobot-specific environments.
- `nvidia-smi` and NVIDIA driver stack for local GPU runtime checks.
- Docker for PrusaSlicer, FEniCSx, local Neo4j, or local vLLM/NemoClaw paths.
- `ffmpeg` for the Bambu Lab live camera browser proxy. Without it, the Bambu
  video status API can still report that the printer's LAN video port is
  reachable, but `/api/printer/video-stream.mjpeg` stays unavailable.
- Intel RealSense Python SDK (`pyrealsense2==2.58.2.10647`) for live RealSense
  camera checks and future VisionAgent depth/RGB capture. The Spark workstation
  uses Ubuntu 24.04 on `aarch64`; the tested wheel is
  `manylinux2014_aarch64` for Python 3.12 in the main `.venv` and Python 3.10
  in the `lerobot` conda environment. `rs-enumerate-devices` is not required for
  ATR operation when the Python SDK is installed, but it may still be useful if
  the full librealsense CLI package is installed later.
- Bambu Studio CLI for Bambu Lab X2D slicing/pre-start validation. The 3DP
  GUI/backend resolves the executable in this order: `BAMBU_STUDIO_EXECUTABLE`,
  configured wrapper path (`install/bambustudio/bambu-studio-wrapper`), then a
  `PATH` executable such as `bambu-studio`. Without a resolved CLI, the bridge
  can still run MQTT/FTPS/status checks, but it cannot honestly claim a new
  Bambu-native sliced artifact was generated.
  Current Spark workstation smoke check:
  `timeout 15s /home/jin/.local/bin/bambu-studio --help` reports
  `BambuStudio-02.07.01.57` and documents `--slice`, `--arrange`,
  `--ensure-on-bed`, `--outputdir`, `--load-settings`, and `--load-filaments`.
  The 3DP GUI `Slice Bambu Artifact` action uses those CLI options, passes
  `--export-3mf` as a basename inside `--outputdir` rather than as an absolute
  path, and records the generated artifact hash before any HTTP route or MQTT
  start gate is considered. The runner also creates a local no-skirt process
  profile copy under the slicing output folder so Bambu autoejection validation
  does not inherit skirt/brim/raft residue from default slicer settings.
- Microsoft C++ Build Tools on Windows only when a package has to compile from
  source instead of installing a wheel.

Ubuntu/Spark workstation example:

```bash
sudo apt-get install -y ffmpeg
```

## Main Python Environment

Install the tracked Python dependencies from:

```bash
pip install -r requirements.txt
```

Windows PowerShell equivalent:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

The main dependency file covers FastAPI, HTTP clients, YAML parsing, testing,
browser-based GUI inspection, and the TPMS/STL geometry stack (`numpy`,
`scikit-image`, `trimesh`). It also includes `pyrealsense2` so the main ATR
runtime can enumerate RealSense devices and validate live depth/RGB frames from
Python.

Selenium is included for GUI browser inspection and screenshot audits. Use it
when a GUI route, layout, report panel, Runtime IDE canvas, or Live GUI chat
surface changes and visual verification is required. The current local audit
path uses Firefox plus geckodriver:

```bash
# Example: start a temporary server in one terminal
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 7862

# Example: run a Selenium/Firefox inspection script from the main venv
.venv/bin/python tests/ui/live_runtime_ide_browser_audit.py
```

If a one-off inspection script is used, keep screenshots under `runs/` or
`artifacts/` and stop the temporary server/browser processes after the audit.

## BoTorch BO Backend

BoTorch/GPyTorch are part of the default Python dependency set because the BO
Workspace exposes `Numeric Backend = botorch_optional` as a first-class backend.
Install the main environment with:

```bash
.venv/bin/pip install -r requirements.txt
```

Tracked compatibility file:

```text
requirements-bo.txt
```

`requirements-bo.txt` remains as a focused installer for older checkouts or
repair installs, but the canonical dependency path is now `requirements.txt` and
`pyproject.toml` default dependencies. Installing BoTorch pulls in PyTorch and
CUDA-related wheels on this aarch64/Linux host, so expect a large download.

If BoTorch import or GP fitting fails at runtime, `botorch_optional` falls back to
`lightweight_pool` and records the reason in `benchmark.backend_warnings` and
`bo_result.benchmark.strategies.bo.backend_warnings`.

Implementation boundary:

- `learning/botorch_backend.py` uses BoTorch `SingleTaskGP` posterior scoring over
  the existing candidate pool.
- It does not bypass Design/Specimen/Guardian validation.
- It does not perform unconstrained continuous optimization over categorical or
  boolean manufacturing parameters.

## Terminal Launcher

The local `atr` command is installed from:

```bash
bash install/install_cli.sh
```

The installer creates a user-level launcher under `~/.local/bin/atr`. Reinstall
after moving or recloning the repository because the generated command stores the
checkout path.

## API-Key Inference and Backend Fallback

ATR now has an explicit API-key backend named `openai`.

Keep real keys out of Git. Use `.env.example` only as a blank variable list,
store real values in ignored `.env`, and see `docs/runtime/api_keys.md` for the
full key-handling policy.

Backend priority is controlled by:

```yaml
configs/models.yaml:
  backend:
    default: vllm
    fallback: openai
```

This means the active backend runs first, its model fallback runs second, and
OpenAI is tried last as the backend fallback. To skip local AI entirely on
Windows or any API-only machine, set:

```text
AUTONOMOUS_BACKEND=openai
```

To keep local-first behavior with OpenAI as the final fallback, keep the active
backend as `vllm`, `ollama`, or `nemoclaw` and still set `OPENAI_API_KEY`.

The current implementation uses the Chat Completions endpoint to preserve the
existing `BaseLLMBackend.complete(...)` contract shared by vLLM/Ollama/NemoClaw.
New OpenAI-native agent features can later move to the Responses API without
changing installation requirements.

## NemoClaw / vLLM Backend

Optional. Required only when using the local-first `vllm` backend:

- Docker-capable NemoClaw/k3s environment.
- A running cluster container named `openshell-cluster-nemoclaw`.
- `kubectl` available inside the cluster container.
- NVIDIA runtime class available to k3s as `runtimeClassName: nvidia`.
- vLLM image:
  - `vllm/vllm-openai:v0.21.0-cu129-ubuntu2404`

Tracked deployment manifest:

```bash
deploy/nemoclaw-vllm.yaml
```

Managed model checkpoints:

- `nvidia/Gemma-4-31B-IT-NVFP4`
- `bg-digitalservices/Gemma-4-E4B-it-NVFP4`

The current managed model surface is intentionally limited to two models:

- `gemma4:31b`
- `gemma4:e4b-it-nvfp4`

`gemma4:e2b-*` is not part of the active `/api/runtime/models` GUI/API
surface and should not be documented as a required local serving dependency.

MTP assistant checkpoint:

- `google/gemma-4-31B-it-assistant`

Current MTP policy:

- `gemma4:31b` uses Gemma4 MTP speculative decoding with
  `google/gemma-4-31B-it-assistant` and `num_speculative_tokens=4`.
- `gemma4:e4b-it-nvfp4` is served as a stable target-only NVFP4 deployment.
  MTP is disabled for this model in `configs/system.yaml` because the
  E4B+NVFP4+MTP path repeatedly triggered CUDA device-side asserts during local
  validation.

Important runtime setting:

- `VLLM_NVFP4_GEMM_BACKEND=marlin`

This is required on the current GB10/NVFP4 host to avoid incompatible automatic
FlashInfer/CUTLASS FP4 paths.

## Ollama / NemoClaw Compatibility Branch

Optional compatibility backend. OpenAI remains the final fallback when
`backend.fallback: openai` is configured and an API key is available:

- Ollama installed locally or managed by the operator.
- NemoClaw Ollama proxy files under the operator's local `~/.nemoclaw` directory
  when using the `nemoclaw` proxy branch.

The source tree does not commit proxy tokens or local Ollama runtime state.

## Bambu Lab X2D / Prusa MK4S 3DP Runtime

Required for physical 3D printing:

- Bambu Lab X2D is the default 3DP bridge profile. Store LAN-mode connection
  info locally in `memory/bambu_connection.json`; never commit the LAN access
  code.
- Bambu autoejection is not a Prusa-style appended G-code routine and is not a
  Manipulation Agent handoff in the primary path. It requires
  `memory/bambu_autoejection.json` with the native `bambu_gcode_patch` provider:
  source sliced artifact -> `.autoeject.*` artifact -> validator evidence ->
  transfer/start gate -> bed-clear gate.
- Bambu autoejection validation actions must keep `motion_started=false` unless
  the normal live publish gate is explicitly passed. Robot/Manipulation Agent
  motion is reserved for failed-ejection recovery or downstream specimen
  transfer, and still requires its own bridge config, Guardian approval, and
  operator confirmation.
- Prusa MK4S on the same reachable network.
- PrusaLink enabled.
- PrusaLink connection info stored locally in:
  - `memory/prusa_connection.json`

Do not commit PrusaLink username, password, API key, IP address, or storage
state. The file is intentionally ignored by Git.

### PrusaSlicer

The repository provides a Docker wrapper for PrusaSlicer:

```bash
docker build -t atr-prusa-slicer:ubuntu24.04 install/prusaslicer
install/prusaslicer/prusa-slicer-docker
```

The wrapper uses:

- `install/prusaslicer/Dockerfile`
- `install/prusaslicer/prusa-slicer-docker`

Docker must be installed and available to the user running the GUI/API.

## LeRobot Runtime

Required for real robot teleoperation, recording, training, and rollout:

- A separate LeRobot checkout, expected locally at:
  - Linux default: `/home/jin/lerobot`
  - Windows example: `C:\Users\user\Documents\lerobot`
- Conda environment:
  - `lerobot`
- LeRobot CLI entry points available inside that environment:
  - `lerobot-teleoperate`
  - `lerobot-record`
  - `lerobot-train`
  - `python -m lerobot.teleoperate`

The GUI expects local datasets under the standard LeRobot/Hugging Face cache by
default:

```text
~/.cache/huggingface/lerobot
```

On Windows, the same path resolves under the user's home directory. If you need a
different location, update `configs/lerobot.yaml` or the LeRobot GUI settings.

Robot/camera port memory is stored locally and ignored by Git:

```text
memory/lerobot_device_ports.json
```

The bridge must run LeRobot through conda, not through the main `.venv`:

```yaml
configs/lerobot.yaml:
  conda_executable: conda
  conda_env_name: lerobot
  pi05_conda_env_name: lerobot-pi05-torch211
```

Setup outline:

```powershell
$conda = "$env:USERPROFILE\miniconda3\Scripts\conda.exe"
winget install -e --id Anaconda.Miniconda3 --scope user
& $conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
& $conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
& $conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/msys2
& $conda create -y -n lerobot python=3.10
& $conda run -n lerobot python -m pip install --upgrade pip
```

On Linux or WSL, the same setup can use `conda create -y -n lerobot python=3.10`
when `conda` is already on PATH. ATR auto-detects common user installs when
`conda_executable: conda`, including `%USERPROFILE%\miniconda3\Scripts\conda.exe`
on Windows and `~/miniconda3/bin/conda` on Linux.

Use `conda run -n lerobot <command>` to verify entry points before enabling live
robot actions in the GUI.

Install the RealSense Python SDK into the LeRobot environment as well when robot
recording or rollout will use RealSense cameras:

```bash
/home/jin/miniconda3/envs/lerobot/bin/python -m pip install pyrealsense2==2.58.2.10647
```

Spark workstation camera smoke check, without writing ATR mapping files:

```bash
# Main ATR environment
.venv/bin/python - <<'PY'
import pyrealsense2 as rs
ctx = rs.context()
print("device_count", len(list(ctx.query_devices())))
for dev in ctx.query_devices():
    print(dev.get_info(rs.camera_info.name), dev.get_info(rs.camera_info.serial_number))
PY

# Kernel/UVC frame check when SDK CLI tools are not installed
ffmpeg -hide_banner -loglevel error -y \
  -f v4l2 -input_format gray16le -video_size 640x480 -i /dev/video2 \
  -frames:v 1 /tmp/realsense_depth_probe.png
```

If RealSense and webcam devices disappear from both `lsusb` and
`rs.context().query_devices()`, treat it as a USB bus/device reset rather than a
software mapping problem. Replug or power-cycle the camera hub before debugging
ATR camera code.

Spark workstation RealSense safety note:

- `pyrealsense2` installation only adds the Python SDK wheel; it does not install
  kernel drivers or rewrite camera mappings.
- Do not open arbitrary depth/RGB streams as a smoke test. First enumerate the
  device and advertised stream profiles through `RealSenseBridge.enumerate`.
- D405-class devices may expose only the Stereo Module even when a `color`
  profile is advertised. ATR must validate the advertised profile first and must
  reject any non-advertised stream before `rs.pipeline.start()`.
- If kernel logs contain `xHCI host controller not responding, assume dead` or
  `HC died; cleaning up`, the USB host controller dropped devices at bus level.
  Restarting ATR is not enough; replug/power-cycle the USB camera hub or reboot.

### Optional Pi0.5 Training Branch

Pi0.5 training uses an isolated LeRobot worktree and conda environment:

```bash
git -C /home/jin/lerobot worktree add /home/jin/lerobot_pi05 upstream/feat/add-pi05
conda create -y -n lerobot-pi05-torch211 --clone lerobot
conda run -n lerobot-pi05-torch211 pip install -e '/home/jin/lerobot_pi05[pi]'
conda run -n lerobot-pi05-torch211 python -m pip install --upgrade --force-reinstall torch==2.11.0 torchvision==0.26.0 torchcodec==0.13.0
conda run -n lerobot-pi05-torch211 python -m pip install --force-reinstall fsspec==2025.9.0 setuptools==80.10.2
```

Optional model download:

```bash
mkdir -p /home/jin/.cache/huggingface_pi05
HF_HOME=/home/jin/.cache/huggingface_pi05 \
HF_HUB_CACHE=/home/jin/.cache/huggingface_pi05/hub \
HF_HUB_DISABLE_XET=1 \
conda run -n lerobot-pi05-torch211 hf download lerobot/pi05_base --max-workers 1
```

Pi0.5 training uses local W&B offline logging by default. The GUI/bridge passes
`--wandb.enable=true --wandb.mode=offline` and `WANDB_MODE=offline`, so training
does not require a W&B cloud API key. Select `disabled` only when no W&B run
metadata should be created.

Pi0.5 training keeps `num_workers=12` as the current GUI default and allows up to
`num_workers=20` in the backend for faster local dataloader/video-decode
throughput. This matches the current `/lerobot` frontend defaults and bridge
normalization path; do not document `4` as the Pi0.5 GUI default unless the
code is changed again.
Pi0.5 training now runs in `lerobot-pi05-torch211` with `torch==2.11.0`, `torchvision==0.26.0`, and `torchcodec==0.13.0`; the bridge prefers `torchcodec` and falls back to `pyav` when the selected conda environment cannot import TorchCodec.

The bridge resolves `lerobot/pi05_base` to a compatible local snapshot under
`~/.cache/huggingface_pi05/hub/models--lerobot--pi05_base/snapshots` when one is
available. This avoids stale HF cache refs whose `policy_preprocessor.json` still
references the removed `relative_actions_processor` registry step.

For Pi0.5, live training datasets are converted to local LeRobot v3.0 copies under
`~/.cache/huggingface/lerobot/local-pi05-v30/`. The bridge also runs local
quantile-stat augmentation when `meta/stats.json` lacks `q01/q99`, because Pi0.5
uses QUANTILES normalization. This augmentation is local-only; Hub push/tag calls
are suppressed by the bridge.

The Pi0.5 worktree, conda env, datasets, model cache, and offline W&B run files
are not part of this Git repository.

## FEniCSx / DOLFINx FEM Runtime

Optional for Analysis Agent FEM/CAE enhancement and improvement 06.

FEniCSx is intentionally not installed into the main `.venv` and is not listed
in `requirements.txt`, because DOLFINx depends on MPI/PETSc/native solver
libraries. Use a dedicated conda environment or the official Docker image.

The main application registers FEniCSx through the device bridge layer, not by
importing DOLFINx directly into the FastAPI process:

```text
device_bridges/fenicsx_bridge.py
mcp_tools/fenicsx_tools.py
```

Registered tools:

```text
fenicsx.health
fenicsx.run_linear_elasticity
fenicsx.run_fem
```

The production execution path uses a fixed DOLFINx linear-elasticity template:

```text
scripts/fenicsx_linear_elasticity_template.py
```

This template is executed in the dedicated `fenicsx` conda environment or in the
configured Docker image. It performs a real DOLFINx solve on a homogenized
specimen envelope with bottom fixed support and top compression traction, then
returns displacement, stiffness, Von Mises stress, mesh metadata, and XDMF output.
The deterministic path is retained only as an explicit fallback/smoke mode.

Runtime configuration is stored in `configs/devices.yaml`:

```yaml
devices:
  fenicsx:
    enabled: true
    mode: test
    provider: dolfinx
    execution_backend: auto       # auto | deterministic | conda | docker
    runtime_solver_enabled: false # false: fast bridge mode, true: call conda/docker FEniCSx
    require_runtime_in_live: false
    conda_env: fenicsx
    docker_image: dolfinx/dolfinx:stable
    artifact_dir: artifacts/fenicsx
    solver_script_path: scripts/fenicsx_linear_elasticity_template.py
    timeout_sec: 120
    allow_deterministic_fallback: true
    template_version: atr_linear_elasticity_template_v1
```

Use `runtime_solver_enabled=false` for fast deterministic bridge mode during repeated TEST loops. Use `runtime_solver_enabled=true` with `execution_backend=auto|conda|docker` for real DOLFINx execution. The same setting can be changed at runtime through `fenicsx.set_runtime_solver` without editing code. Set `require_runtime_in_live=true` only when live Analysis must block unless the FEniCSx runtime probe succeeds.

Verified local conda environment:

```bash
conda run -n fenicsx python -c "import dolfinx, basix, ufl, ffcx"
conda run -n fenicsx python artifacts/external/fenicsx/examples/poisson_smoke.py
```

Verified local package versions:

```text
dolfinx=0.10.0
basix=0.10.0
ufl=2025.2.1
ffcx=0.10.0
```

Verified Docker runtime:

```bash
docker pull dolfinx/dolfinx:stable
docker run --rm --entrypoint python3 \
  -v "$PWD/artifacts/external/fenicsx/examples:/work/examples:ro" \
  -w /work \
  dolfinx/dolfinx:stable \
  examples/poisson_smoke.py
```

Downloaded source, tutorial, and documentation assets are stored locally under:

```text
artifacts/external/fenicsx/
```

Local bundle contents:

- `sources/dolfinx`
- `sources/basix`
- `sources/ffcx`
- `sources/ufl`
- `sources/fenics-docs`
- `sources/dolfinx-tutorial`
- `docs/html`
- `docs/pdf/dolfinx-tutorial-latest.pdf`
- `examples/poisson_smoke.py`
- `manifests/fenicsx_sources_manifest.txt`

These files are intentionally under `artifacts/` and should not be committed.
Recreate/update them with shallow official source checkouts and official docs
snapshots when needed.

Analysis Agent usage rule:

- Treat FEniCSx/FEM as `fem_low` simulation evidence.
- Treat physical UTM data as `utm_high` measured evidence.
- Do not insert FEM predictions into BO as measured observations.
- Use validated FEM templates, cache manifests, and UTM/FEM comparison artifacts
  before BO handoff.
- The LLM agentic FEM loop may plan tutorial-style steps, mesh sweeps, and
  acceptance criteria, but execution must stay inside registered `fenicsx.*`
  tools and validated payloads. Do not run arbitrary LLM-generated solver code.

LLM route used by the FEM planning loop:

```text
analysis_fem_planning -> e4b
```

Expected FEniCSx bridge artifacts:

```text
artifacts/fenicsx/<run_id>/<specimen_id>/*_fem_request.json
artifacts/fenicsx/<run_id>/<specimen_id>/*_fem_result.json
artifacts/fenicsx/<run_id>/<specimen_id>/*_fenicsx_solver_output.json
artifacts/fenicsx/<run_id>/<specimen_id>/*.xdmf
artifacts/fenicsx/<run_id>/<specimen_id>/*.h5
artifacts/fenicsx/<run_id>/<specimen_id>/*_fem_cache_manifest.json
```

Expected Analysis Agent improvement 06 artifacts:

```text
runs/<run_id>/analysis/<specimen_id>/raw_input_sidecar.json
runs/<run_id>/analysis/<specimen_id>/parse_report.json
runs/<run_id>/analysis/<specimen_id>/canonical_curve.csv
runs/<run_id>/analysis/<specimen_id>/preprocessing_report.json
runs/<run_id>/analysis/<specimen_id>/quality_report.json
runs/<run_id>/analysis/<specimen_id>/metrics.json
runs/<run_id>/analysis/<specimen_id>/fem_request.json
runs/<run_id>/analysis/<specimen_id>/fem_result.json
runs/<run_id>/analysis/<specimen_id>/fem_agentic_loop.json
runs/<run_id>/analysis/<specimen_id>/fem_utm_comparison.json
runs/<run_id>/analysis/<specimen_id>/comparison.json
runs/<run_id>/analysis/<specimen_id>/analysis_report.json
runs/<run_id>/analysis/<specimen_id>/experiment_evaluation.json
runs/<run_id>/analysis/<specimen_id>/bo_handoff.json
runs/<run_id>/analysis/<specimen_id>/analysis_trace.jsonl
```

Regression checks:

```bash
.venv/bin/python -m pytest tests/unit/test_fenicsx_bridge.py tests/unit/test_analysis_agent.py -q
.venv/bin/python -m pytest tests/unit/test_bo_agent.py tests/unit/test_langgraph_runtime.py tests/integration/test_controller_run.py -q
conda run -n fenicsx python scripts/fenicsx_linear_elasticity_template.py <request.json> <result.json>
```

Official references:

- `https://docs.fenicsproject.org/`
- `https://docs.fenicsproject.org/dolfinx/main/python/installation.html`
- `https://github.com/FEniCS/dolfinx`
- `https://github.com/FEniCS/basix`
- `https://github.com/FEniCS/ffcx`
- `https://github.com/FEniCS/ufl`
- `https://jsdokken.com/dolfinx-tutorial/`
- `https://github.com/jorgensd/dolfinx-tutorial`

## Windows PyAutoGUI Bridge

Required when controlling Windows GUI/macros from the Equipment Agent:

- Windows PC on a reachable local network.
- Python launcher on Windows (`py`).
- PyAutoGUI installed on Windows:

```powershell
py -m pip install pyautogui
```

Optional but recommended for UTM software that exposes Windows UI Automation selectors:

```powershell
py -m pip install pywinauto
```

When `pywinauto` is installed, UTM locators may use `locator_backend: uia` with `auto_id`, `title`/`name`, `control_type`, `class_name`, or `best_match`. The bridge tries UIA first, then falls back to PyAutoGUI image matching or explicit coordinates when configured.

Optional for OCR/text state checks used by `assert_text` and `wait_until_text`:

```powershell
py -m pip install pytesseract Pillow
```

`pytesseract` requires the Tesseract OCR executable on Windows. Without it, required text checks fail closed and the Equipment Agent will not promote the run to Analysis.

Run the tracked bridge server on Windows:

```powershell
py windows_pyautogui_bridge_server.py
```

Source file:

```text
install/windows_pyautogui_bridge_server.py
```

Set the bridge token through an environment variable on Windows. Do not commit
tokens or saved connection details:

```text
WINDOWS_PYAUTOGUI_BRIDGE_TOKEN
memory/windows_pyautogui_connection.json
```

## Optional Knowledge Graph Backend

The default Knowledge memory remains file-backed JSON/JSONL and requires no graph database.
Neo4j/Graphify support is optional and should be installed only when using the Knowledge graph mirror/index layer.

Install optional dependencies:

```bash
.venv/bin/pip install -r requirements-graph.txt
# or, from pyproject extras:
.venv/bin/pip install -e '.[graph]'
```

Optional packages:

```text
neo4j        # Neo4j Python driver for optional graph DB mirror
networkx     # local graph artifact/query fallback
graphifyy==0.4.4  # Graphify CLI/package; command name is graphify
```

Enable the graph backend through environment variables. If disabled or unavailable, ATR continues using JSONL memory.

```bash
export ATR_KNOWLEDGE_GRAPH_ENABLED=1
export ATR_KNOWLEDGE_GRAPH_BACKEND=json
```

For Neo4j:

```bash
export ATR_KNOWLEDGE_GRAPH_ENABLED=1
export ATR_KNOWLEDGE_GRAPH_BACKEND=neo4j
export ATR_NEO4J_URI=bolt://127.0.0.1:7687
export ATR_NEO4J_USERNAME=neo4j
export ATR_NEO4J_PASSWORD='<local-password>'
export ATR_NEO4J_DATABASE=neo4j
export ATR_KNOWLEDGE_GRAPH_FAIL_OPEN=1
```

Graph memory API endpoints:

```text
GET  /api/knowledge/graph/health
POST /api/knowledge/graph/import
GET  /api/knowledge/graph/query
POST /api/knowledge/graphify/scan
POST /api/knowledge/graphify/import
```

The CLI also supports `--json-path` for routing the local JSON graph fallback to a specific file during tests or audits.
The graph query endpoint supports `project_context` for project code/docs/module graph retrieval separate from runtime experiment memory.
The installed `graphify` command is also exposed through `/home/jin/.local/bin/graphify`; ATR uses the installed Graphify Python API when `atr knowledge graphify-scan --external-graphify` is used.
For `graphify query`, use the raw Graphify node-link file at `memory/knowledge/graphify/external_raw/graph.json`; use `memory/knowledge/graphify/project_graph.json` for ATR JSON/Neo4j import.

Operational CLI commands:

```bash
atr knowledge graphify-scan
ATR_KNOWLEDGE_GRAPH_ENABLED=1 ATR_KNOWLEDGE_GRAPH_BACKEND=json \
  atr knowledge graphify-import --no-runtime-memory

atr knowledge graph neo4j-start --wait
atr knowledge graph print-env
ATR_KNOWLEDGE_GRAPH_ENABLED=1 ATR_KNOWLEDGE_GRAPH_BACKEND=neo4j \
ATR_KNOWLEDGE_GRAPH_FAIL_OPEN=0 ATR_NEO4J_URI=bolt://127.0.0.1:7687 \
ATR_NEO4J_USERNAME=neo4j ATR_NEO4J_PASSWORD=atr-knowledge-graph ATR_NEO4J_DATABASE=neo4j \
  atr knowledge graph import --limit 500
ATR_KNOWLEDGE_GRAPH_ENABLED=1 ATR_KNOWLEDGE_GRAPH_BACKEND=neo4j \
ATR_KNOWLEDGE_GRAPH_FAIL_OPEN=0 ATR_NEO4J_URI=bolt://127.0.0.1:7687 \
ATR_NEO4J_USERNAME=neo4j ATR_NEO4J_PASSWORD=atr-knowledge-graph ATR_NEO4J_DATABASE=neo4j \
  atr knowledge graph query --kind target_context --target-type prompt --target-id analysis --limit 10
```

Stop local Neo4j when not needed:

```bash
atr knowledge graph neo4j-stop
```

Generated graph artifacts should stay local by default:

```text
memory/knowledge/graphify/
memory/knowledge/graph_backend/
```

Do not scan or import credentials, `.env`, device passwords, Windows bridge tokens, PrusaLink connection files, raw generated hardware logs, model caches, or user-private files into Graphify/Neo4j.

## Local User Files and Generated Outputs

The following directories are local/user-runtime areas and are ignored except for
their README files:

- `memory/`
- `runs/`
- `artifacts/`
- `outputs/`
- `user_files/`

Do not commit:

- `.env`
- PrusaLink credentials
- Windows bridge tokens
- local device IPs
- generated STL/G-code/3MF files
- LeRobot checkpoints and datasets
- vLLM/Ollama/Hugging Face model caches
- virtual environments

## GitHub Clone Bootstrap Checklist

After cloning on a new machine:

1. Install system tools: `git`, Python, Docker, and optional Conda/NVIDIA stack.
2. Create the main virtual environment and run `pip install -r requirements.txt`.
3. Install the launcher with `bash install/install_cli.sh`.
4. Configure local secrets in `.env` and `memory/*.json` files.
5. Build the PrusaSlicer Docker image if 3DP slicing is needed.
6. Prepare NemoClaw/k3s vLLM and model cache if using the default backend.
7. Clone/setup LeRobot separately if robot workflows are needed.
8. Install/run the Windows PyAutoGUI bridge on the Windows machine if GUI macro
   control is needed.

## Version-Control Workflow Requirement

Use branches when the operator requests branch work or when a change is risky.
Keep `main` as the latest known-good version. Avoid unnecessary branch
proliferation for small, safe edits. See `docs/repository/github_version_control.md`
for the exact workflow.
