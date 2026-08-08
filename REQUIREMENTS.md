# Autonomous Researcher Requirements

This file lists non-Python installation requirements, external checkouts, local
services, model downloads, and device-side programs required by this repository.

Use `requirements.txt` only for Python packages installed into the main
`autonomous_researcher` virtual environment.

## Fresh Install Entry Points

Linux/WSL default install:

```bash
git clone <private-repo-url> autonomous_researcher
cd autonomous_researcher
bash install/bootstrap_linux.sh
atr doctor
atr up
```

Windows supported install:

```powershell
git clone <private-repo-url> autonomous_researcher
cd autonomous_researcher
powershell -ExecutionPolicy Bypass -File .\install\bootstrap_windows.ps1
python -m app.serve
```

Windows limitations:

- Native Windows is supported for API-key GUI/API use and the standalone
  Windows PyAutoGUI bridge server.
- Linux-only runtime pieces such as NemoClaw/vLLM Kubernetes control,
  RealSense RSUSB builds, Dockerized solver/slicer paths, and Linux device
  permissions require Linux/WSL or equivalent manual setup.
- Real robot LeRobot workflows require a separate conda environment and
  LeRobot checkout on that PC.

Run the non-actuating installer check at any time:

```bash
atr doctor
.venv/bin/python scripts/doctor.py --core-only
.venv/bin/python scripts/doctor.py --json
```

`doctor` does not start printers, robots, model servers, or camera streams. It
checks core files, Python imports, `.env`, CLI binding, secret ignore policy,
slicer executables, LeRobot patch packaging, RealSense SDK import, and model
config presence.

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
- Docker for PrusaSlicer, CalculiX, local Neo4j, or local vLLM/NemoClaw paths.
- Local Ubuntu PyAutoGUI bridge development requires an X11 desktop session,
  `PyAutoGUI` and `python3-xlib` from `requirements.txt`, plus `python3-tk`,
  `scrot`, `wmctrl`, and `xdotool`. Install the complete local-control option:
  ```bash
  bash install/bootstrap_linux.sh --with-local-pyautogui
  ```
  The managed bridge binds only to `127.0.0.1:8767`; port `8766` remains
  reserved for the Isaac Sim OMX mirror receiver. Wayland sessions are reported
  as unsupported instead of silently running degraded control.
- Recording Equipment Skills requires `pynput>=1.7.7,<2` on the bridge host.
  Browser-level validation of the Capability Lab and Program Manager examples
  uses Selenium, Firefox, and geckodriver. The Python packages are declared in
  `requirements.txt`; install Firefox/geckodriver through the host package or
  Snap channel used by the workstation. These browser tools are validation-only
  and are not required to execute an already registered Skill.
- `ffmpeg` for the Bambu Lab live camera browser proxy. Without it, the Bambu
  video status API can still report that the printer's LAN video port is
  reachable, but `/api/printer/video-stream.mjpeg` stays unavailable.
- Intel RealSense Python SDK (`pyrealsense2==2.58.2.10647`) plus the local
  librealsense RSUSB build for live D405/D455F depth/RGB capture. The Spark
  workstation uses Ubuntu 24.04 on `aarch64`; the default wheel can import but
  may hit Linux V4L/UVC `UVCIOC_CTRL_QUERY` protocol errors on D405. The tested
  runtime therefore prefers a local `FORCE_RSUSB_BACKEND=ON` librealsense build
  in Python 3.12 for the main `.venv` and Python 3.10 for the `lerobot` conda
  environment. This is an SDK-path fix, not an OpenCV/V4L fallback.
- UTM ROS Vision Runtime for live UTM equipment evidence. On Ubuntu 24.04
  (`noble`), use ROS 2 Jazzy as the system ROS target. This is not a Python-only
  dependency: it requires ROS apt packages, a built UTM ROS workspace, a built
  `yolo_ros` workspace, `uv`, and the runtime launcher configured in
  `configs/devices.yaml`. The runtime flow follows the cloned UTM program under
  `/home/jin/external_repos/UTM`; the browser RQT-like view is `usb_cam ->
  rectify_node -> green_dot_monitor -> yolov8`, with live `ros2 node/topic`
  introspection overlaid. Detailed setup and verification are documented in
  `docs/hardware/utm_ros_vision_runtime_bridge.md` and
  `개선안/16_utm_ros_runtime_bridge_live_gui_plan.md`. Camera bridge setup,
  V4L2 device mapping, frame probe, and checkerboard calibration are tracked in
  `개선안/17_vision_agent_camera_device_bridge_live_gui_plan.md`. The stable
  BRIO-class UVC profile on this workstation is `640x480 @ 15fps`,
  `pixel_format=yuyv2rgb`; ATR pins
  `exposure_dynamic_framerate=0` with `v4l2-ctl` before runtime start and
  records the result in `startup_camera_controls`. ATR image snapshot/MJPEG,
  UTM green-dot image input/output, and YOLO image subscribers are configured as live
  evidence streams with Best Effort, Keep Last, depth 1. The system ROS
  `usb_cam` publisher may still report RELIABLE QoS; if raw ROS camera FPS drops
  below target, patch or replace the camera publisher rather than increasing GUI
  queues. OpenCV CUDA color conversion was tested and removed because the ROS
  Python OpenCV runtime on this workstation reports zero CUDA devices; keep the
  MJPEG worker on the CPU path unless a real CUDA-enabled OpenCV runtime is
  installed and re-benchmarked.
  Expected install baseline:
  ```bash
  sudo apt update
  sudo apt install -y software-properties-common curl ca-certificates git
  sudo add-apt-repository -y universe
  curl -L -o /tmp/ros2-apt-source_noble.deb \
    https://repo.ros2.org/ubuntu/main/pool/main/r/ros-apt-source/ros2-apt-source_1.2.0~noble_all.deb
  sudo dpkg -i /tmp/ros2-apt-source_noble.deb
  sudo apt update
  sudo apt install -y \
    v4l-utils \
    ros-jazzy-ros-base \
    ros-dev-tools \
    python3-colcon-common-extensions \
    python3-rosdep \
    ros-jazzy-cv-bridge \
    ros-jazzy-image-transport \
    ros-jazzy-image-proc \
    ros-jazzy-vision-msgs \
    ros-jazzy-usb-cam \
    ros-jazzy-camera-calibration \
    ros-jazzy-camera-calibration-parsers \
    ros-jazzy-rqt-gui \
    ros-jazzy-rqt-image-view \
    ros-jazzy-rqt-graph
  sudo rosdep init  # only once
  rosdep update
  cd /home/jin/external_repos/UTM
  source /opt/ros/jazzy/setup.bash
  rosdep check --from-paths src --ignore-src
  colcon build --symlink-install
  source /home/jin/external_repos/UTM/install/setup.bash
  cd /home/jin/external_repos
  git clone https://github.com/mgonzs13/yolo_ros.git yolo_ros
  cd /home/jin/external_repos/yolo_ros
  source /opt/ros/jazzy/setup.bash
  rosdep check --from-paths . --ignore-src
  colcon build --symlink-install
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  uv sync --project /home/jin/external_repos/yolo_ros/install/yolo_ros/share/yolo_ros
  mkdir -p /home/jin/external_repos/yolo_ros/models
  curl -L -o /home/jin/external_repos/yolo_ros/models/yolov8m.pt \
    https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m.pt
  ```
  The runtime should expose `ros2`, `colcon`, and the UTM stack topics such as
  `/compression_tester/summary`. Test mode should use the real ROS observer when
  camera/topic evidence is available and otherwise continue through the virtual
  UTM bridge. Live mode should auto-load and diagnose the ROS stack, but must not
  mark physical UTM completion from virtual evidence. The ATR GUI should render
  browser-native RQT-like panels from live ROS state: image topics (`/image_utm`,
  `/camera/image_rect`, `/yolo/dbg_image`) and a node/topic graph derived from
  `ros2 node/topic` introspection. The graph panel should use a stable graph hash
  so unchanged node/topic topology refreshes status timestamps without
  re-rendering the canvas/SVG. `rqt_image_view` and `rqt_graph` remain operator
  debugging helpers, not the primary GUI rendering path.
  Live camera FPS troubleshooting should start at `/camera/image_raw`. If
  `/camera/image_raw` is already below target, the problem is camera/V4L2/USB
  input, not browser rendering. The accepted local fix is `yuyv2rgb` plus
  `v4l2-ctl --device=<camera> --set-ctrl=exposure_dynamic_framerate=0`.
  Local disk note: `/home/jin/external_repos/yolo_ros` is about 5 GB after
  `uv sync` because it contains PyTorch/CUDA wheels.
- NVIDIA Isaac Sim for ROBOTIS OMX real-to-sim mirror mode. The Spark
  workstation path is `/home/jin/IsaacSim/`. The ATR mirror receiver production
  path launches:
  ```bash
  /home/jin/IsaacSim/isaac-sim.sh \
    --ext-folder /home/jin/autonomous_researcher/sim/robotis_omx/extensions \
    --enable atr.omx.mirror
  ```
  The receiver extension opens
  `sim/robotis_omx/scene/omx_table_layout.usda`, serves
  `http://127.0.0.1:8766/joints`, and starts the Isaac timeline from a delayed
  Kit update callback instead of immediately during extension startup. This
  avoids startup-time Kit crashes while still making the visible stage enter
  Play mode automatically. Scene generation must use Isaac Sim Python because
  system Python does not provide `pxr`:
  ```bash
  /home/jin/IsaacSim/python.sh sim/robotis_omx/tools/build_table_layout_scene.py
  ```
  The generated table scene includes a physics-lite contract: `PhysicsScene`,
  static colliders for table/A4/disk objects, and a dynamic red specimen block
  rigid body. Receiver `/state.last_apply_result.stage_summary.physics_ready`
  should be `true` before using mirror evidence as synchronized real/sim
  recording proof. In live LeRobot teleoperation/recording with Isaac mirror
  enabled, ATR runs `scripts/lerobot_isaac_mirror_runtime_wrapper.py` inside
  the LeRobot conda environment so Isaac samples are published from the same
  `send_action()` process that owns the follower bus. Standalone mirror checks
  still use `lerobot.mirror.loop_start` with one persistent follower reader.
- Bambu Studio CLI for Bambu Lab X2D slicing/pre-start validation. The 3DP
  GUI/backend resolves the executable in this order: `BAMBU_STUDIO_EXECUTABLE`,
  configured wrapper path (`install/bambustudio/bambu-studio-wrapper`), then a
  `PATH` executable such as `bambu-studio`. Without a resolved CLI, the bridge
  can still run MQTT/FTPS/status checks, but it cannot honestly claim a new
  Bambu-native sliced artifact was generated.
  The repository ships `install/bambustudio/bambu-studio-wrapper` as a stable
  resolver/forwarder. It does not install Bambu Studio. On a new PC, install
  Bambu Studio separately or set:
  ```bash
  export BAMBU_STUDIO_EXECUTABLE=/absolute/path/to/bambu-studio
  install/bambustudio/bambu-studio-wrapper --help
  atr doctor
  ```
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
  - Linux default: `~/lerobot`
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
  xvla_conda_env_name: lerobot-pi05-torch211
  smolvla_conda_env_name: lerobot-pi05-torch211
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

Apply the ATR-packaged Spark RealSense D405/RSUSB LeRobot patch when this PC
will run D405/D455F live robot workflows:

```bash
bash install/apply_lerobot_d405_patch.sh ~/lerobot
```

Patch source:

```text
patches/lerobot/spark_realsense_d405_rsusb.patch
```

The patch is intentionally outside the ATR runtime code. It makes the external
LeRobot checkout reproducible without vendoring LeRobot into this repository.
It also adds the ATR RGB-D observation contract for OMX RealSense recording:
`observation.images.top_depth` and `observation.images.wrist_depth` are emitted
as 8-bit 3-channel depth videos alongside the RGB camera streams. ATR keeps
that compatibility path, and live recording additionally writes metric raw
depth sidecars when RealSense depth is enabled:

```text
<dataset>/sidecar/depth_raw/top/frame_000000.png
<dataset>/sidecar/depth_raw/wrist/frame_000000.png
```

Those sidecar PNG files are 16-bit `uint16` RealSense Z16 depth maps. The
bridge passes `ATR_LEROBOT_RAW_DEPTH_DIR`, `ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS`,
and `ATR_LEROBOT_RAW_DEPTH_FORMAT=png16` to the LeRobot subprocess. It also
passes the RGB-D transform contract:

```text
ATR_LEROBOT_DEPTH_ALIGNED_TO=color
ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT=0.001
ATR_LEROBOT_DEPTH_CLIP_MIN_MM=0.0
ATR_LEROBOT_DEPTH_CLIP_MAX_MM=2000.0
```

The patched LeRobot runtime writes
`<dataset>/sidecar/depth_raw/transform_manifest.json` beside the raw PNG files.
That manifest is the source of truth for aligned depth, metric scale, and the
visual-depth clipping range. When the GUI/bridge selects `raw_depth_adapter`,
the patched LeRobot dataset loader consumes this manifest and the 16-bit PNG
sidecar during training. It replaces the existing LeRobot depth observations
such as `observation.images.top_depth` and `observation.images.wrist_depth`
with tensors reconstructed from raw `uint16` metric depth, resized to the
policy feature shape and normalized with the recorded clip/scale contract.
`rgbd_sidecar` keeps the compatibility path only: policies still see the normal
LeRobot RGB-D video features while raw depth is stored as evidence.

ATR stores the selected observation contract beside each locally recorded
dataset:

```text
<dataset>/meta/atr_pipeline.json
```

The `/lerobot` Profile panel exposes the same contract as an `Observation
Pipeline` selector:

- `legacy_lerobot`: standard LeRobot RGB/depth visual features only; ATR raw
  16-bit sidecar is disabled.
- `rgbd_sidecar`: current default for ROBOTIS OMX-AI RealSense runs; standard
  LeRobot RGB-D features plus ATR 16-bit raw-depth sidecar and transform
  metadata.
- `raw_depth_adapter`: training-time adapter mode that requires the raw sidecar
  manifest and sets `ATR_LEROBOT_RAW_DEPTH_ADAPTER=1` plus
  `ATR_LEROBOT_RAW_DEPTH_SOURCE_DIR=<dataset>/sidecar/depth_raw`. The patched
  LeRobot loader then replaces the standard `*_depth` feature tensors with
  tensors loaded from the raw 16-bit sidecar. This is not only a metadata
  contract.

The bridge passes `ATR_LEROBOT_OBSERVATION_PIPELINE_ID=<pipeline>` to LeRobot
record/train/rollout subprocesses. Training refuses to start when a selected
pipeline conflicts with `<dataset>/meta/atr_pipeline.json`, returning
`LEROBOT_OBSERVATION_PIPELINE_MISMATCH` instead of silently falling back.
Browsing or inspecting a dataset from the GUI reads this metadata and restores
the matching robot profile and observation pipeline when possible.

The same patch also retries Dynamixel calibration writes and torque-disable
commands during OMX follower startup. This is required on the Spark workstation
because live recording/rollout can otherwise abort on a transient
`There is no status packet` response even though the same motor still
successfully pings and reads position.

Config keys to keep in `configs/lerobot.yaml` for reproducible RGB-D runs:

```yaml
realsense_depth_align_to_color: true
realsense_depth_scale_m_per_unit: 0.001
realsense_depth_clip_min_mm: 0.0
realsense_depth_clip_max_mm: 2000.0
default_observation_pipeline_id: rgbd_sidecar
```

Install the RealSense Python SDK into the LeRobot environment as well when robot
teleoperation, recording, or rollout will use RealSense cameras:

```bash
/home/jin/miniconda3/envs/lerobot/bin/python -m pip install pyrealsense2==2.58.2.10647
```

Spark workstation D405 fix:

```bash
sudo apt install -y git cmake ninja-build build-essential pkg-config \
  libssl-dev libusb-1.0-0-dev libudev-dev \
  libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev \
  libxinerama-dev libxcursor-dev libxi-dev libxrandr-dev \
  python3-dev python3-pip python3-setuptools python3-numpy \
  v4l-utils udev libcurl4-openssl-dev curl
git clone https://github.com/realsenseai/librealsense /home/jin/librealsense-rsusb
cd /home/jin/librealsense-rsusb
git checkout v2.58.2

# Host udev rule, then reload.
sudo cp config/99-realsense-libusb.rules /etc/udev/rules.d/99-realsense-libusb.rules
sudo udevadm control --reload-rules
sudo udevadm trigger

# Main ATR Python 3.12 build.
cmake -S . -B build-rsusb -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DFORCE_RSUSB_BACKEND=ON \
  -DBUILD_PYTHON_BINDINGS=ON \
  -DPYTHON_EXECUTABLE=/home/jin/autonomous_researcher/.venv/bin/python \
  -DPython_EXECUTABLE=/home/jin/autonomous_researcher/.venv/bin/python \
  -DBUILD_EXAMPLES=OFF \
  -DBUILD_GRAPHICAL_EXAMPLES=OFF \
  -DBUILD_TOOLS=ON \
  -DBUILD_UNIT_TESTS=OFF \
  -DBUILD_WITH_CUDA=OFF
cmake --build build-rsusb -j 8

# LeRobot Python 3.10 build.
cmake -S . -B build-rsusb-py310 -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DFORCE_RSUSB_BACKEND=ON \
  -DBUILD_PYTHON_BINDINGS=ON \
  -DPYTHON_EXECUTABLE=/home/jin/miniconda3/envs/lerobot/bin/python \
  -DPython_EXECUTABLE=/home/jin/miniconda3/envs/lerobot/bin/python \
  -DBUILD_EXAMPLES=OFF \
  -DBUILD_GRAPHICAL_EXAMPLES=OFF \
  -DBUILD_TOOLS=ON \
  -DBUILD_UNIT_TESTS=OFF \
  -DBUILD_WITH_CUDA=OFF
cmake --build build-rsusb-py310 -j 8
```

Host-wide RealSense tools for system diagnosis:

```bash
cd /home/jin/librealsense-rsusb
cmake -S . -B build-rsusb-system -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=/usr/local \
  -DFORCE_RSUSB_BACKEND=ON \
  -DBUILD_EXAMPLES=ON \
  -DBUILD_GRAPHICAL_EXAMPLES=ON \
  -DBUILD_PYTHON_BINDINGS=ON \
  -DCHECK_FOR_UPDATES=OFF \
  -DPYTHON_EXECUTABLE=/usr/bin/python3
cmake --build build-rsusb-system --parallel "$(nproc)"
sudo cmake --install build-rsusb-system
sudo ldconfig
sudo ./scripts/setup_udev_rules.sh
sudo udevadm control --reload-rules
sudo udevadm trigger
```

`CHECK_FOR_UPDATES=OFF` is intentional for the Spark workstation build. It keeps
`realsense-viewer` available while avoiding the bundled update-check curl target
that can fail during source builds. ATR does not need RealSense viewer
self-update checks.

The system install provides:

```bash
rs-enumerate-devices
rs-fw-update
realsense-viewer
rs-depth-quality
rs-multicam
python3 -c 'import pyrealsense2 as rs; print(rs.__file__)'
```

Verified on this Spark workstation after reboot on 2026-06-20:

- system commands resolve from `/usr/local/bin`
- system Python imports `pyrealsense2` from
  `/usr/local/lib/python3.12/dist-packages/pyrealsense2`
- `rs-enumerate-devices` sees D455F serial `341522300873` and D405 serial
  `352122273019`
- `rs-fw-update -l` sees both devices
- a short system-Python stream probe opened `640x480 RGB+depth @15 FPS` for
  each device and wrote:
  `runs/camera_tests/realsense_global_stream_probe_latest.json`

Current USB negotiation can still vary by hub/cable/port. In the 2026-06-20
post-reboot recheck, both D455F and D405 reported SDK USB `3.2` / sysfs
`5000M`. If either device reports SDK USB `2.1` or sysfs `480M`, treat it as a
hub/cable/port negotiation problem before debugging ATR camera code.

If D455F or D405 is visible in `rs-enumerate-devices` but a non-root stream
probe raises `RS2_USB_STATUS_BUSY`, `failed to set power state`, or
`Frame didn't arrive within ...`, first confirm no camera process owns the
device:

```bash
fuser -v /dev/video* 2>/dev/null || true
```

Then run one controlled root smoke test or replug/power-cycle the camera hub.
On 2026-06-20, D455F initially showed a transient libusb power-state busy
condition; a root stream open succeeded, and the next normal user stream open
succeeded without changing ATR mapping files.

Pin the built RSUSB bindings ahead of the pip wheel:

```bash
cat > /home/jin/autonomous_researcher/.venv/lib/python3.12/site-packages/atr_realsense_rsusb.pth <<'PTH'
import os, sys; p='/home/jin/librealsense-rsusb/build-rsusb/Release'; os.path.isdir(p) and p not in sys.path and sys.path.insert(0, p)
PTH

cat > /home/jin/miniconda3/envs/lerobot/lib/python3.10/site-packages/atr_realsense_rsusb.pth <<'PTH'
import os, sys; p='/home/jin/librealsense-rsusb/build-rsusb-py310/Release'; os.path.isdir(p) and p not in sys.path and sys.path.insert(0, p)
PTH
```

Spark workstation camera smoke check, without writing ATR mapping files:

```bash
# Main ATR environment
.venv/bin/python - <<'PY'
import pyrealsense2 as rs
print("pyrealsense2", rs.__file__)
ctx = rs.context()
print("device_count", len(list(ctx.query_devices())))
for dev in ctx.query_devices():
    print(dev.get_info(rs.camera_info.name), dev.get_info(rs.camera_info.serial_number))
PY

# LeRobot execution environment. This is the environment used by live
# teleoperate/record/rollout subprocesses.
/home/jin/miniconda3/condabin/conda run --no-capture-output -n lerobot python - <<'PY'
import pyrealsense2 as rs
print("pyrealsense2", rs.__file__)
ctx = rs.context()
print("device_count", len(list(ctx.query_devices())))
for dev in ctx.query_devices():
    print(dev.get_info(rs.camera_info.name), dev.get_info(rs.camera_info.serial_number))
PY

# Cross-check through LeRobot's own camera discovery command.
/home/jin/miniconda3/condabin/conda run --no-capture-output -n lerobot lerobot-find-cameras realsense

# Host-wide system tools. These do not write ATR camera mappings.
rs-enumerate-devices
rs-fw-update -l
python3 - <<'PY'
import pyrealsense2 as rs
print("pyrealsense2", rs.__file__)
ctx = rs.context()
print("device_count", len(list(ctx.query_devices())))
for dev in ctx.query_devices():
    print(
        dev.get_info(rs.camera_info.name),
        dev.get_info(rs.camera_info.serial_number),
        dev.get_info(rs.camera_info.usb_type_descriptor),
    )
PY

# USB bus-level check. RealSense devices must appear here before ATR can use them.
# Use timeout because `lsusb -t` can hang on a sick USB bus/controller.
timeout 5 lsusb -t || true
for d in /sys/bus/usb/devices/*; do
  product=$(timeout 1 cat "$d/product" 2>/dev/null || true)
  if printf '%s' "$product" | grep -qi 'RealSense'; then
    printf '%s product=%s speed=%s bcdUSB=%s serial=%s\n' \
      "${d##*/}" "$product" \
      "$(timeout 1 cat "$d/speed" 2>/dev/null || echo '?')" \
      "$(timeout 1 cat "$d/bcdUSB" 2>/dev/null || echo '?')" \
      "$(timeout 1 cat "$d/serial" 2>/dev/null || echo '?')"
  fi
done
```

If RealSense and webcam devices disappear from both `lsusb` and
`rs.context().query_devices()`, treat it as a USB bus/device reset rather than a
software mapping problem. Replug or power-cycle the camera hub before debugging
ATR camera code.

Expected Spark workstation RealSense serials:

- `top`: Intel RealSense D455F, serial `341522300873`
- `wrist`: Intel RealSense D405, serial `352122273019`

The LeRobot bridge uses the saved SDK serials when building
`--robot.cameras`. In live `teleoperate`, `record`, and `rollout`, ATR now runs
a pre-start camera visibility check before launching the LeRobot subprocess. If
`camera_enabled=true` and a saved RealSense serial is not visible in the
LeRobot conda environment, the request is blocked before robot motion with:

```text
LEROBOT_REALSENSE_CAMERA_UNAVAILABLE
```

Example operator meaning:

```text
Saved LeRobot cameras are not available: wrist=352122273019;
visible RealSense devices: 341522300873.
```

This means the D405 is missing at SDK/USB level or not visible to the `lerobot`
conda environment. Do not remap it to `/dev/video*`; restore SDK visibility by
replugging/power-cycling the camera hub, then rerun Device Port Setup
`Detect & Save` if the serial changed.

LeRobot D405 issue-cleaning rules:

- D405 must be passed to LeRobot as `type=intelrealsense`,
  `serial_number_or_name=352122273019`, `color_format=bgr8`,
  `use_depth=true`, `warmup_s>=20`.
- D455F/top remains `color_format=rgb8`.
- After recording with RealSense depth enabled, inspect `meta/info.json`.
  A valid ATR RGB-D LeRobotDataset contains `observation.images.top_depth` and
  `observation.images.wrist_depth`. If these are missing, the ATR bridge returns
  `LEROBOT_REALSENSE_DEPTH_FEATURE_MISSING`; do not train an RGB-D policy on
  that dataset.
- For metric depth evidence, also inspect
  `sidecar/depth_raw/<camera_key>/frame_*.png`. These files must load as
  `uint16` and preserve the RealSense Z16 millimeter-scale depth values. They
  are not a replacement for the 8-bit LeRobot video features used by existing
  ACT/Pi0.5/SmolVLA/X-VLA training paths.
- Do not use short or disabled RealSense warmup. LeRobot issue reports show
  `warmup=False` / disabled warmup can produce `read failed (status=False)`
  even when RealSense metadata discovery works.
- Do not let `Detect & Save` assign visible D455F serial `341522300873` to the
  `wrist` role when D405 is absent. A missing D405 must remain a blocked
  hardware state, not a camera fallback.
- If `wrist=352122273019` disappears after a failed session, first run:

```bash
cd /home/jin/autonomous_researcher
.venv/bin/python scripts/realsense_usb_stabilize.py --include-brio
```

If visible RealSense/BRIO devices report `power_control=auto`, apply the
runtime power fix:

```bash
sudo .venv/bin/python scripts/realsense_usb_stabilize.py --apply --include-brio
```

This changes currently enumerated USB device `power/control` to `on`. It does
not remap cameras and does not open streams. Re-run it after reconnecting D405
because sysfs entries are recreated on USB re-enumeration.

Spark workstation RealSense safety note:

- `pyrealsense2` installation only adds the Python SDK wheel; it does not install
  kernel drivers or rewrite camera mappings. On this Spark workstation, D405
  live use must import the RSUSB build from `/home/jin/librealsense-rsusb/...`
  instead of the pip wheel package path.
- Do not open arbitrary depth/RGB streams as a smoke test. First enumerate the
  device and advertised stream profiles through `RealSenseBridge.enumerate`.
- Do not silently substitute `/dev/v4l/by-id` or OpenCV when RealSense SDK
  enumeration fails. D405/D455F LeRobot recording and rollout require the
  official `intelrealsense` camera backend.
- D405-class devices may expose only the Stereo Module even when a `color`
  profile is advertised. ATR must validate the advertised profile first and must
  reject any non-advertised stream before `rs.pipeline.start()`.
- If kernel logs contain `xHCI host controller not responding, assume dead` or
  `HC died; cleaning up`, the USB host controller dropped devices at bus level.
  Restarting ATR is not enough; replug/power-cycle the USB camera hub or reboot.

### Optional Pi0.5 Training Branch

Pi0.5 training uses an isolated LeRobot worktree and conda environment:

```bash
git -C ~/lerobot worktree add ~/lerobot_pi05 upstream/feat/add-pi05
conda create -y -n lerobot-pi05-torch211 --clone lerobot
conda run -n lerobot-pi05-torch211 pip install -e "$HOME/lerobot_pi05[pi]"
conda run -n lerobot-pi05-torch211 python -m pip install --upgrade --force-reinstall torch==2.11.0 torchvision==0.26.0 torchcodec==0.13.0
conda run -n lerobot-pi05-torch211 python -m pip install --force-reinstall fsspec==2025.9.0 setuptools==80.10.2
conda run -n lerobot-pi05-torch211 python -m pip install "wandb>=0.20.0"
```

Optional model download:

```bash
mkdir -p ~/.cache/huggingface_pi05
HF_HOME=~/.cache/huggingface_pi05 \
HF_HUB_CACHE=~/.cache/huggingface_pi05/hub \
HF_HUB_DISABLE_XET=1 \
conda run -n lerobot-pi05-torch211 hf download lerobot/pi05_base --max-workers 1
```

### Optional X-VLA Training Branch

X-VLA is integrated as an additive LeRobot policy backend for lower-data
experiments. It uses the normal `lerobot` conda environment and does not require
the isolated Pi0.5 worktree/environment.

Optional model download:

```bash
conda run -n lerobot hf download lerobot/xvla-base --max-workers 1
```

When `policy_type=xvla` is selected, the GUI/bridge passes
`--policy.type=xvla --policy.path=lerobot/xvla-base` and seeds the X-VLA
soft-prompt fine-tuning flags. Keep Pi0.5 as the default transfer policy until
X-VLA is benchmarked on the same ROBOTIS OMX-AI datasets and real rollout tasks.

### Optional SmolVLA Training Branch

SmolVLA is integrated as an additive LeRobot VLA backend. Training runs through
the TorchCodec-ready `lerobot-pi05-torch211` conda environment so video decoding
uses the same TorchCodec stack as Pi0.5. The editable source checkout for that
environment is `/home/jin/lerobot_pi05`.

Install the LeRobot extra and prefetch the required model resources:

```bash
cd /home/jin/lerobot_pi05
conda run --no-capture-output -n lerobot-pi05-torch211 python -m pip install -e ".[smolvla]"
conda run --no-capture-output -n lerobot-pi05-torch211 hf download lerobot/smolvla_base --max-workers 1
conda run --no-capture-output -n lerobot-pi05-torch211 hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct --exclude "onnx/*" --max-workers 1
```

When `policy_type=smolvla` is selected, the GUI/bridge passes
`--policy.type=smolvla --policy.path=lerobot/smolvla_base`. Default train shape:
`batch_size=8`, `steps=20000`, `num_workers=4`, `policy.n_obs_steps=1`,
`policy.chunk_size=50`, and `policy.n_action_steps=50`. The bridge/GUI seed
the SmolVLA fine-tuning flags `--policy.freeze_vision_encoder=true`,
`--policy.train_expert_only=true`, and `--policy.train_state_proj=true`.
SmolVLA rollout uses the generic LeRobot rollout path and intentionally omits
ACT temporal-ensemble flags.

Pi0.5 training uses local W&B offline logging by default. The GUI/bridge passes
`--wandb.enable=true --wandb.mode=offline` and `WANDB_MODE=offline`, so training
does not require a W&B cloud API key. Select `disabled` only when no W&B run
metadata should be created.

The LeRobot GUI can also start a local W&B Server dashboard from the Training
panel. Use the `WandB Local Server` controls to run
`conda run --no-capture-output -n lerobot-pi05-torch211 wandb server start
--port 8081 --no-daemon`, then keep `wandb.enable=true` and
select `wandb.mode=local server` in the GUI. The bridge maps that operator-facing
local mode to the W&B CLI's `--wandb.mode=online` and passes
`WANDB_BASE_URL=http://127.0.0.1:8081` to the LeRobot training subprocess.
Port `8081` is the project default because
port `8080` is commonly occupied by Docker services on the Spark workstation.
On the DGX Spark `aarch64` host, W&B Local currently uses an amd64 Docker image;
enable Docker binfmt/QEMU before first use:
`docker run --privileged --rm tonistiigi/binfmt --install amd64`.

Pi0.5 training uses `batch_size=16`, `num_workers=12`, `eval_freq=500`,
`log_freq=50`, and `save_freq=500` as the current GUI/bridge defaults. The
backend allows up to `num_workers=20` for faster local dataloader/video-decode
throughput. This matches the current `/lerobot` frontend defaults and bridge
normalization path; do not document `4` as the Pi0.5 GUI default unless the code
is changed again.
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

## CAE / CalculiX Runtime

The current CAE plan uses the project CAE bridge and a CalculiX-oriented runtime path. A separate Python FEM solver stack is no longer part of the documented new-machine install path. CalculiX integration remains optional until the CAE runner is explicitly enabled.

Required CAE documentation lives in:

```text
docs/agents/cae_analysis_runtime_guideline.txt
개선안/15_utm_calculix_pinn_multifidelity_code_first_plan.md
```

Keep physical UTM data as the measured source of truth. CAE output is simulation evidence only and must not be inserted into BO as a measured observation.

## Windows PyAutoGUI Bridge

Required when controlling Windows GUI/macros from the Equipment Agent:

- Use `Pyautogui_server_for_window/requirements-windows.txt` in the bridge's
  dedicated `.venv`. It installs PyAutoGUI, Pillow, OpenCV, pynput, pywinauto,
  pytesseract, and the release builder. `pynput` is required for demonstration
  recording; missing listeners fail closed instead of creating an empty
  successful recording.
- Image-first demonstration recording uses Pillow through PyAutoGUI to capture
  bounded target crops. Install `opencv-python` to use confidence-based image
  matching during replay.
- Configure `WINDOWS_PYAUTOGUI_RECORDING_DIR` for persisted recordings and
  `WINDOWS_PYAUTOGUI_ATR_API_URL` for Linux-authoritative Skill lifecycle
  operations. Do not store ATR API/model credentials on Windows.

- Windows PC on a reachable local network.
- Python launcher on Windows (`py`).
- Reproducible standalone installation on Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Pyautogui_server_for_window\scripts\install_bridge.ps1
```

Optional but recommended for UTM software that exposes Windows UI Automation selectors:

```powershell
py -m pip install pywinauto
```

When `pywinauto` is installed, UTM locators may use `locator_backend: uia` with `auto_id`, `title`/`name`, `control_type`, `class_name`, or `best_match`. The bridge tries UIA first, then falls back to PyAutoGUI image matching or explicit coordinates when configured.

New recordings use `atr.equipment_recording.v2` with image tracking enabled and
coordinate fallback disabled. Clicks record tight and contextual PNG targets;
drags record source and destination targets. Replay searches the images first
and returns `UI_LOCATOR_NOT_FOUND` with screen evidence instead of silently
clicking the old coordinate. Legacy v1 coordinate recordings remain readable.

Optional for OCR/text state checks used by `assert_text` and `wait_until_text`:

```powershell
py -m pip install pytesseract Pillow
```

`pytesseract` requires the Tesseract OCR executable on Windows. Without it, required text checks fail closed and the Equipment Agent will not promote the run to Analysis.

Run the installed bridge on Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Programs\ATR\PyAutoGUIBridge\scripts\run_bridge.ps1"
```

Source package:

```text
Pyautogui_server_for_window/
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
export ATR_KNOWLEDGE_EVENT_PIPELINE_ENABLED=1
export ATR_KNOWLEDGE_GRAPH_MAX_ATTEMPTS=5
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

The operational Knowledge write path is ontology validation -> append-only JSONL/fsync -> durable outbox -> Neo4j -> acknowledgement. When Neo4j is selected but unavailable, ATR reports degraded state and retains pending outbox events; it does not silently switch operational writes to the JSON graph backend. See `docs/knowledge/knowledge_graph_operations.ko.md`.
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

## Long Training Stability Tools

Long LeRobot/Pi0.5 training should be run with unrelated broken services stopped
and a passive monitor writing to disk.

Recommended host packages:

```bash
sudo apt-get install -y sysstat
```

ATR includes a passive monitor. LeRobot training started from the ATR GUI bridge
in `live` mode starts this monitor automatically; the command below is for
manual CLI-only training or one-off diagnosis:

```bash
python scripts/training_stability_monitor.py --once
python scripts/training_stability_monitor.py --interval-seconds 30 \
  --train-log runs/lerobot_sessions/<training-log>.log \
  --checkpoint-dir outputs/train/<run>/checkpoints/<step>
```

The monitor records RAM, disk, GPU, recent kernel/system errors, recent
`ollama.service` state, checkpoint step metadata, and the training log tail under
`runs/training_watch/`. It is passive and does not start, stop, or control
training.

If the local systemd Ollama unit is not intentionally used, keep it disabled
before long training. A broken `ollama.service` restart loop can create system
noise during training:

```bash
systemctl is-active ollama.service || true
sudo systemctl stop ollama.service || true
sudo systemctl disable ollama.service || true
sudo systemctl reset-failed ollama.service || true
```

See `docs/runtime/training_stability.md` for the 2026-06-19 Pi0.5 crash analysis
and resume policy.

## ROS Specimen Pose Tracking

Required for live D455F one-shot pose tracking:

```bash
sudo apt install -y ros-jazzy-realsense2-camera ros-jazzy-cv-bridge ros-jazzy-image-transport python3-opencv python3-numpy
```

The Spark RealSense runtime should prefer the local RSUSB build when Python imports
`pyrealsense2` directly:

```bash
export PYTHONPATH=/home/jin/librealsense-rsusb/build-rsusb-system/Release:$PYTHONPATH
export LD_LIBRARY_PATH=/home/jin/librealsense-rsusb/build-rsusb-system/Release:$LD_LIBRARY_PATH
```

Build the local ROS package:

```bash
cd /home/jin/autonomous_researcher/ros
colcon build --packages-select atr_specimen_pose_tracker
```

Live validation requires the D455F to enumerate as a USB3 RealSense device. If it is not visible to `rs-enumerate-devices` or appears only on a USB2/high-speed path, fix the physical cable/hub/port before using `vision.specimen_pose_snapshot` in live mode.

The ROS driver publishes the current default D455F topics under the camera name:

```text
/camera/d455f/color/image_raw
/camera/d455f/color/camera_info
/camera/d455f/aligned_depth_to_color/image_raw
```

If kernel logs show `xHCI host controller not responding, assume dead` for
`NVDA8000:00`, the D455F bus has died below ROS/librealsense. Stop the ROS node,
power-cycle/replug the camera or reboot before retrying; the software bridge can
only validate up to the live-camera boundary while the device is absent.
