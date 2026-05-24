# Autonomous Researcher Requirements

This file lists non-Python installation requirements, external checkouts, local
services, model downloads, and device-side programs required by this repository.

Use `requirements.txt` only for Python packages installed into the main
`autonomous_researcher` virtual environment.

## Core Workstation

Required for the main GUI/API:

- Linux workstation with Bash.
- Python 3.10 or newer.
- `git`.
- `curl`.
- Python virtual environment support:
  - `python3 -m venv .venv`
  - `pip install -r requirements.txt`

Optional but commonly used:

- `conda` or Miniconda for LeRobot-specific environments.
- `nvidia-smi` and NVIDIA driver stack for local GPU runtime checks.

## Main Python Environment

Install the tracked Python dependencies from:

```bash
pip install -r requirements.txt
```

The main dependency file covers FastAPI, HTTP clients, YAML parsing, testing, and
the TPMS/STL geometry stack (`numpy`, `scikit-image`, `trimesh`).

## Terminal Launcher

The local `atr` command is installed from:

```bash
bash install/install_cli.sh
```

The installer creates a user-level launcher under `~/.local/bin/atr`. Reinstall
after moving or recloning the repository because the generated command stores the
checkout path.

## NemoClaw / vLLM Backend

Required when using the default `vllm` backend:

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
- `bg-digitalservices/Gemma-4-E2B-it-NVFP4`

MTP assistant checkpoints:

- `google/gemma-4-31B-it-assistant`
- `google/gemma-4-E4B-it-assistant`
- `google/gemma-4-E2B-it-assistant`

Important runtime setting:

- `VLLM_NVFP4_GEMM_BACKEND=marlin`

This is required on the current GB10/NVFP4 host to avoid incompatible automatic
FlashInfer/CUTLASS FP4 paths.

## Ollama / NemoClaw Compatibility Branch

Optional compatibility backend:

- Ollama installed locally or managed by the operator.
- NemoClaw Ollama proxy files under the operator's local `~/.nemoclaw` directory
  when using the `nemoclaw` proxy branch.

The source tree does not commit proxy tokens or local Ollama runtime state.

## Prusa MK4S / 3DP Runtime

Required for physical 3D printing:

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
  - `/home/jin/lerobot`
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

Robot/camera port memory is stored locally and ignored by Git:

```text
memory/lerobot_device_ports.json
```

### Optional Pi0.5 Training Branch

Pi0.5 training uses an isolated LeRobot worktree and conda environment:

```bash
git -C /home/jin/lerobot worktree add /home/jin/lerobot_pi05 upstream/feat/add-pi05
conda create -y -n lerobot-pi05 --clone lerobot
conda run -n lerobot-pi05 pip install -e '/home/jin/lerobot_pi05[pi]'
```

Optional model download:

```bash
mkdir -p /home/jin/.cache/huggingface_pi05
HF_HOME=/home/jin/.cache/huggingface_pi05 \
HF_HUB_CACHE=/home/jin/.cache/huggingface_pi05/hub \
HF_HUB_DISABLE_XET=1 \
conda run -n lerobot-pi05 hf download lerobot/pi05_base --max-workers 1
```

The Pi0.5 worktree, conda env, datasets, and model cache are not part of this
Git repository.

## Windows PyAutoGUI Bridge

Required when controlling Windows GUI/macros from the Equipment Agent:

- Windows PC on a reachable local network.
- Python launcher on Windows (`py`).
- PyAutoGUI installed on Windows:

```powershell
py -m pip install pyautogui
```

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
