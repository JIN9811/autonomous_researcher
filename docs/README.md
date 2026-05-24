# Documentation Index

Role-based documentation layout:

- `project/`
  - Project-level guide and repository structure.
- `runtime/`
  - Runtime architecture, agent/tool contracts, test mode, and logging contracts.
  - Autonomous Experiment Runtime standard interface, benchmark mode, and device job queue contract.
- `agents/`
  - Agent-specific implementation guidelines.
  - BO Agent runtime guideline for acquisition/BO/MBO optimization.
  - Vision pickup observation guideline for the 3DP output-area check before robot transfer.
  - Manipulation Pi0.5 transfer guideline for LeRobot policy rollout from 3DP to UTM.
  - Analysis UTM runtime guideline for force/displacement curve processing and objective scoring.
  - CAE Analysis runtime guideline for bottom-fixed/top-cyclic simulation and closed-loop scoring.
- `hardware/`
  - Device bridge and hardware-facing workflow guidelines.
  - Windows PyAutoGUI bridge guideline for internal-network Equipment Agent control.
  - Windows-side setup guide for the PyAutoGUI bridge host PC.
  - LeRobot / ROBOTIS Manipulation runtime guideline for robot profiles, LeRobot MCP tools, test mode, live gates, and SARM integration.
  - Prusa MK4S live validation record for PrusaLink/Docker PrusaSlicer behavior.
- `gui/`
  - Operator GUI, Live GUI behavior, and dedicated LeRobot GUI route behavior.
- `process/`
  - Codex implementation workflow and development process.
- `tutorials/`
  - Operator-facing first autonomous run guide.
- `strategy/`
  - Higher-level improvement roadmap and research-system guidance.
- `../install/`
  - User-level terminal launcher installer and `atr` command usage.

Primary entry points:

- `project/Project_guide.txt`
- `runtime/agent_program_baseline.md`
- `runtime/autonomous_experiment_runtime.md`
- `runtime/lerobot_dataset_policy_naming.md`
  - Includes the isolated Pi0.5 training runtime contract for `lerobot-pi05`, `/home/jin/lerobot_pi05`, and `/home/jin/.cache/huggingface_pi05`.
- `agents/specimen_design_existing_runtime_guideline.txt`
- `agents/bo_agent_runtime_guideline.txt`
- `agents/vision_pickup_observation_runtime_guideline.txt`
- `agents/manipulation_pi05_transfer_runtime_guideline.txt`
- `agents/analysis_utm_runtime_guideline.txt`
- `agents/cae_analysis_runtime_guideline.txt`
- `hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt`
- `hardware/prusa_mk4s_live_validation_20260506.md`
- `hardware/lerobot_robotis_manipulation_runtime_guideline.md`
- `codex_lerobot_robotis_gui_prompt.txt`
- `hardware/windows_pyautogui_equipment_agent_guideline.md`
- `hardware/windows_pyautogui_bridge_windows_setup.md`
- `../install/README.md`
- `tutorials/first_autonomous_run.md`
