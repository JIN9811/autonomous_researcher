# Autonomous Researcher Framework

Local-first multi-agent autonomous research framework designed for DGX Spark-style lab orchestration with:
- NemoClaw/k3s vLLM as default inference backend
- OpenShell/NemoClaw-aligned secure runtime assumptions
- LangGraph-style explicit state graph
- MCP-style tool abstraction
- Full test-mode dry-run support
- Real-time web GUI for loop visualization

## Quick Start

See `REQUIREMENTS.md` for OS tools, Docker/NemoClaw, vLLM model checkpoints,
LeRobot, PrusaSlicer, and Windows bridge setup requirements.

1. Create environment and install dependencies:

```bash
cd /home/jin/autonomous_researcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. (Optional) Copy `.env.example` to `.env` and edit values.

3. Install the terminal launcher:

```bash
bash install/install_cli.sh
```

If this is the first time `~/.local/bin` was added to PATH, open a new terminal or run:

```bash
source ~/.bashrc
```

4. Run the web app from any terminal:

```bash
atr up
```

Stop the installed GUI server from any terminal:

```bash
atr down
```

During clean shutdown, the server releases LeRobot live subprocesses tied to this checkout so stale teleoperation/recording jobs do not keep cameras or serial ports open.

Alternative without installing the launcher:

```bash
.venv/bin/python -m app.serve
```

5. Open:
- `http://localhost:7860` for the GUI
- `http://localhost:7860/docs` for API docs

Full terminal command usage is documented in `./install/README.md`.

## LeRobot Pi0.5 Training

Pi0.5 training uses a separate LeRobot checkout and conda environment so the ROBOTIS OMX live robot runtime stays on `/home/jin/lerobot` + `lerobot`.

Current Pi0.5 setup:

```bash
cd /home/jin
git -C /home/jin/lerobot worktree add /home/jin/lerobot_pi05 upstream/feat/add-pi05
conda create -y -n lerobot-pi05 --clone lerobot
conda run -n lerobot-pi05 pip install -e '/home/jin/lerobot_pi05[pi]'
```

Prefetch the Pi0.5 base model into the GUI training cache:

```bash
mkdir -p /home/jin/.cache/huggingface_pi05
HF_HOME=/home/jin/.cache/huggingface_pi05 HF_HUB_CACHE=/home/jin/.cache/huggingface_pi05/hub HF_HUB_DISABLE_XET=1 conda run -n lerobot-pi05 hf download lerobot/pi05_base --max-workers 1
```

Verify:

```bash
conda run -n lerobot-pi05 python -c "from lerobot.policies.pi05.configuration_pi05 import PI05Config; print(PI05Config().type)"
```

In the GUI, open `/lerobot`, set Training `Policy Type` to `pi05 (Pi0.5)`, keep `Train Source Policy / HF Base` as `lerobot/pi05_base`, then start training. The bridge runs Pi0.5 training through `conda run -n lerobot-pi05 lerobot-train`, adds `--policy.pretrained_path=lerobot/pi05_base`, and sets `HF_HOME=/home/jin/.cache/huggingface_pi05` plus `HF_HUB_DISABLE_XET=1` for the live train process.

Pi0.5 requires LeRobot dataset format `v3.0`. ROBOTIS/LeRobot 0.3 recordings are usually `v2.1`, so the GUI bridge keeps the original recording untouched and creates a Pi0.5-only converted copy under:

```text
/home/jin/.cache/huggingface/lerobot/local-pi05-v30/<dataset-slug>
```

For the current local recording, the converted dataset is:

```text
repo_id: local-pi05-v30/jin-record-test-20260512t063639z
path:    /home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-record-test-20260512t063639z
```

Manual conversion command shape, if needed:

```bash
conda run --no-capture-output -n lerobot-pi05 python -m lerobot.datasets.v30.convert_dataset_v21_to_v30 \
  --repo-id=local-pi05-v30/jin-record-test-20260512t063639z \
  --root=/home/jin/.cache/huggingface/lerobot \
  --push-to-hub=false \
  --force-conversion
```

Training defaults follow Hugging Face LeRobot docs:

- ACT default GUI values: `batch_size=8`, `steps=100000`, `num_workers=4`, `eval_freq=20000`, `log_freq=200`, `save_freq=20000`, `policy.n_obs_steps=1`, `policy.chunk_size=100`, `policy.n_action_steps=100`.
- Pi0.5 default GUI values: `batch_size=32`, `steps=3000`, `policy.n_obs_steps=1`, `policy.chunk_size=50`, `policy.n_action_steps=50`, `policy.compile_model=true`, `policy.gradient_checkpointing=true`, `policy.dtype=bfloat16`, `policy.freeze_vision_encoder=false`, `policy.train_expert_only=false`.
- References: https://huggingface.co/docs/lerobot/act and https://huggingface.co/docs/lerobot/pi05.

## Current Scope

This repository currently implements Phase 1 plus foundational parts of Phase 2:
- modular project skeleton
- YAML config loader
- structured logging subsystem
- NemoClaw/k3s vLLM backend, Ollama proxy backend, local Ollama backend, and mock backend
- model router
- LangGraph-style orchestrator loop
- local RAG over `docs/project/Project_guide.txt` + optional web RAG fallback
- mock MCP tools and simulated device mode
- modern real-time web GUI
- unit/integration tests for core flow

## Notes

- Default guide path is `./docs/project/Project_guide.txt`.
- If internet RAG is needed, set `TAVILY_API_KEY` or `SERPER_API_KEY`.
- NemoClaw-aligned vLLM inference is the default backend (`AUTONOMOUS_BACKEND=vllm`) and serves the Gemma4 aliases from NVFP4 ModelOpt FP4 deployments with Gemma4 MTP speculative decoding. On the GB10 host, the deployments force `VLLM_NVFP4_GEMM_BACKEND=marlin` to avoid incompatible FlashInfer/CUTLASS FP4 kernels.
- Hardware bridges are currently simulation-first and can be extended per bridge module.

## Agent Program Baseline

- Baseline markdown for integrating real programs into agents:
  - `./docs/runtime/agent_program_baseline.md`
- API docs exposure (`http://localhost:7860/docs`):
  - `GET /api/docs/agent-baseline` (JSON + markdown content)
  - `GET /api/docs/agent-baseline.md` (raw markdown)
