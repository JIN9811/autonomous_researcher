<!-- atr-doc
doc_type: guide
subtype: tutorial
status: active
authority: procedural
audience: [user, operator, researcher]
scope: [gui_tutorial, operator_workflow]
summary: Practical operator exercises for devices, evidence, recovery and read-only replay.
source_of_truth:
  - web/templates
  - web/static
  - app/main.py
  - app/run_review_routes.py
last_verified: 2026-09-29
verified_against: fcfba9f
related_docs:
  - docs/gui/visual_structure.md
  - docs/runtime/test_mode.md
supersedes: []
-->

# Operator Walkthroughs

[Korean](user_manual.ko.md) · [First run](first_autonomous_run.en.md) · [Tutorial index](first_autonomous_run.md)

## Before you start

After the first virtual run, follow each exercise's goal, controls and completion
check. Initial device setup requires a trained operator; this guide does not
authorize unattended robot or UTM motion.

Read [Requirements](../../REQUIREMENTS.md) for installation. For an already installed
system, `atr up` starts the server at `http://localhost:7860`.
Do not restart a running experiment for a documentation exercise.

Figures are 1920 × 1080 captures from 29 September 2026. Some show historical or idle
state; none is a new hardware test. Private paths/connection details are redacted.
Values shown are not universal settings.

## Exercise 1 — Find the right workspace

**Goal:** distinguish configuration from the run that consumes it.

1. Open Main and scroll to **Device Workspaces**.
2. Choose the device you intend to configure.
3. Keep Live GUI for run-bound commands, approvals and agent reports.

![Main workspace navigation](../gui/assets/screenshots/2026-09-29/main-workspaces.png)

| Task | Workspace | Tutorial/reference |
|---|---|---|
| Print defaults, slicing, transfer | 3D Printer, `/printer` | [Printer walkthrough](device_workspace_3dp_usage.en.md) |
| Robot devices, recording, rollout | Manipulation, `/lerobot` | Exercises 3–4 below |
| UTM camera and ROS | Vision, `/device-bridge/vision-utm` | [Vision walkthrough](device_workspace_vision_camera_bridge_usage.en.md) |
| Windows bridge and Skills | Windows Automation, `/equipment/windows` | Exercise 5 |
| BO configuration | Bayesian Optimization, `/bo` | Exercise 6 |
| Hardware interlocks | PLC Safety, `/plc` | [PLC bridge](../device_bridges/plc_safety_bridge.md) |
| Retained knowledge | Knowledge, `/knowledge` | Exercise 7 |

**Checkpoint:** you can return to the same run in Live without launching another
workspace operation. Opening a page is not a stage-completion action.

## Exercise 2 — Move from virtual testing to hardware

**Goal:** select the intended physical boundary before a new run.

1. Open **Test Mode Settings** from Main.
2. Compare **Installed Printer** and **Physical Print**.
3. Inspect each agent's boundary, print-body/cooling choices and auto-ejection.
4. Save only the profile you intend to use; reload to verify.
5. In Live, explicitly request the matching scenario. The supported Korean
   command aliases are `테스트 모드, 실제 프린터` for Installed Printer and
   `테스트 모드, 실제 출력` for Physical Print.

![Installed Printer: ejection path without printing the body](assets/screenshots/2026-09-29/profile-installed.png)

![Physical Print: printing and cooling enabled](assets/screenshots/2026-09-29/profile-physical.png)

**Checkpoint:** the admitted contract and selected profile agree.
Installed Printer is not a dry-run: it can eject and operate downstream real devices.
If supplying a specimen yourself, follow the current operator request; do not mark
a specimen present or removed before actually observing it. Physical Print uses the
full print path.

Passing the Installed Printer exercise does not validate first-layer adhesion,
full print duration or nozzle-cleaning performance. Validate physical printing
separately under supervision. Profile edits affect the next admitted run, not an
already running one. See [Test Mode](../runtime/test_mode.md).

## Exercise 3 — Configure robot ports and record one demonstration

**Goal:** create an identifiable local demonstration without confusing recording,
training and experiment execution.

1. Open **Manipulation → Profile** and select the intended robot profile.
2. Expand **2. Device Port Setup**. Read the saved follower, leader and camera entries.
3. If setup is needed, use **Baseline** then **ID Detect & Save** for the intended
   device, following the displayed detection guidance. Alternatively expand
   **Manual Port Override**, select the role/camera key and **Save Manual Port**.
   These controls save configuration and detect devices.
4. Check calibration and camera ownership using the
   [LeRobot bridge guide](../device_bridges/lerobot_bridge.md) before motion.

![Expanded follower, leader and camera setup](assets/screenshots/2026-09-29/robot-devices.png)

5. In **4. Local Paths**, set the dataset root and dataset repo ID/local name.
   For a new recording, choose a new dataset identity. Use **Resume dataset** only
   for an existing compatible dataset; deleting its folder is not a resume method.
6. In **6. Recording**, enter **Task Instruction**, **Episodes**, **Episode Time (s)**
   and **Reset Time (s)**. For a supervised first recording, use one episode.
7. Clear the robot workspace, then click **Start Record**.

![Recording inputs and live episode controls](assets/screenshots/2026-09-29/robot-recording.png)

8. Use **Save / Next →** to accept the episode, **Retry Current ←** to reject/retry it,
   and **Finish Gracefully (Esc)** to close normally. **Force Stop** is emergency
   cleanup, not the normal save button.
9. Inspect the action status/log and recorded dataset before training.

**Checkpoint:** a saved episode at the intended path, with the expected camera and
joint channels. A successful launch without saved frames/actions is not a recording.
If startup fails, inspect the session log, ports, calibration and dataset identity;
do not delete calibration or reconnect a device while another session owns it.

## Exercise 4 — Configure standalone inference and the experiment bridge

**Goal:** avoid saving a rollout option in the wrong place.

1. Open **10. Inference / Rollout** for a standalone supervised policy test.
2. Check the policy checkpoint, task and action rate.
3. Choose optional linear interpolation/RTC settings explicitly.
   Interpolation output Hz is distinct from policy/action FPS; the output must not
   be below the input rate and the GUI supports up to 100 Hz.
4. Click **Save Rollout Defaults**. Start only when the robot work area is clear.

![Standalone rollout options](../gui/assets/screenshots/2026-09-29/lerobot-inference.png)

5. Open **11. Manipulation Agent Bridge** for settings consumed by the loop.
6. Select the intended task, inspect its own policy/rates/options, and click
   **Save Task Defaults**. Do not assume saving standalone rollout defaults changed
   the selected agent task.

![Task-specific Manipulation Agent Bridge settings](../gui/assets/screenshots/2026-09-29/lerobot-agent-bridge.png)

**Checkpoint:** the task-specific saved configuration matches the intended next
session. Inspect MAN's live telemetry, policy tracking and artifacts during a real
run. A 3D robot display alone does not prove grasp or placement success.
Do not run a standalone rollout concurrently with a loop-owned manipulation.

## Exercise 5 — Prepare Windows/UTM automation

**Goal:** verify the actual target desktop and equipment sequence before admission.

1. Open **Windows Automation** and inspect the selected bridge/worker connection.
2. Check that the received desktop is the intended UTM application, not a login,
   update or unrelated window. Coordinate with the equipment operator.
3. Inspect the selected Skills and their evidence without executing them just to
   populate a screenshot.

![Windows automation workspace](../gui/assets/screenshots/2026-09-29/equipment-windows.png)

4. Open `/equipment/agent-manager` and inspect **Equipment Flow** and its profile.
5. Check the ordered Skills and Vision slots against the intended method.
   Follow [Equipment Agent](../agents/equipment_agent.md) and
   [Windows bridge](../device_bridges/windows_pyautogui_bridge.md) for configuration.
   Do not edit an active flow to skip a failed device action.

![Equipment Agent Manager and flow composition](../gui/assets/screenshots/2026-09-29/equipment-agent-manager.png)

**Checkpoint:** correct worker, desktop, method and flow; current observation evidence
belongs to the run before EQP executes. A green connection indicator does not prove
compression or height return completed.

## Exercise 6 — Inspect one candidate from design to optimization

**Goal:** follow one candidate rather than combining unrelated cycles.

1. In Live, select **DSN → Report**. Record candidate ID, cell size, wall thickness,
   geometry artifact and constraint result.
2. Select **ANL → Report**. Check the selected cycle, SS/FD axes and units, source CSV,
   mass used in SEA, and the actual integration/strain evidence.
3. Select **BO → Report**. Check objective identity/direction and observation count.
4. If a GP exists, inspect the 2D/3D mean, uncertainty, acquisition and next candidate.

![Analysis report with curve and performance evidence](../gui/assets/screenshots/2026-09-29/live-analysis.png)

![BO posterior and recommendation](../gui/assets/screenshots/2026-09-29/live-bo.png)

**Checkpoint:** design → source measurement → analyzed metric → BO observation are
linked to the same identity. Before slicing, absent mass is unknown; afterward use
the recorded mass used by analysis, not an unrelated geometry estimate.
A BO candidate is a recommendation, not an already tested specimen.
An initial LHS view without GP data can be correct.
See [Analysis](../agents/analysis_agent.md) and [BO](../agents/bo_agent.md).

## Exercise 7 — Find retained knowledge without changing run evidence

1. Open **Knowledge → Wiki**.
2. Select an article and read its source references and scope.
3. Use **Source Library** to inspect provenance. Memory and Agent Delivery are
   separate views, not additional physical sensors.

![Knowledge Wiki with source-backed content](../gui/assets/screenshots/2026-09-29/knowledge-wiki.png)

**Checkpoint:** you can identify the source and whether it is historical, procedural
or current run evidence. A wiki instruction cannot prove today's device action.
Some private views require authorized access; a 401 is not an invitation to bypass
authentication. See [Knowledge operations](../knowledge/markdown_memory_operations.ko.md).

## Exercise 8 — Diagnose and resume the same run

1. Note run ID, cycle, agent and the exact unresolved reason.
2. Open that agent's **Timeline**, **Artifacts**, and **Backend** as needed.
3. Correct the actual cause (connection, missing input or physical state), keeping
   the current run's evidence intact.
4. Use the existing **Resume** control if the runtime offers recovery.
5. Confirm the same run ID and intended continuation point; verify the new evidence.

![Timeline for locating a blocked step](../gui/assets/screenshots/2026-09-29/live-timeline.png)

**Checkpoint:** recovery belongs to the existing run, not a duplicate with copied
completion flags. Resume may repeat a step; it does not guarantee exactly-once
physical execution. Inspect the requested route and device state before approving
motion. Do not delete failure history, clear PLC latches
blindly, or use Start as a substitute for Resume.
See [Runtime flow and recovery](../runtime/closed_loop_and_pages_reference.md).

## Exercise 9 — Open a read-only replay

1. Return to Main; choose **Mode = replay**.
2. Select an **Experiment session** and click **Start**.
3. In the new window, use the Contract-area point selector.
4. Use Left/Right to move between recorded points and Up/Down between available
   cycles. Keyboard shortcuts do not take over text/select inputs.

![Replay session selector in Main](assets/screenshots/2026-09-29/main-replay.png)

![Replay window reusing the Live layout](../gui/assets/screenshots/2026-09-29/replay.png)

**Checkpoint:** the header says **REPLAY**, selected run/cycle/point changes, and no
hardware action is issued. Missing snapshots cannot be reconstructed by fetching a
new live camera frame. Artifact files may outlive their recorded point; distinguish
point-bound evidence from a general retained file.
See [Replay reference](../gui/run_replay.md).

## Exercise 10 — Inspect runtime composition without changing the loop

1. Open `/ide` and inspect the graph and node/module configuration.
2. Follow an edge to its contract and locate the associated runtime evidence.
3. For a separate development task, use draft validation/compile/dry-run before any
   saved-version activation. Do not activate edits during this tutorial.

![Runtime IDE graph and inspector](../gui/assets/screenshots/2026-09-29/ide-graph.png)

**Checkpoint:** distinguish a UI report, a module implementation, a package connection
contract and the executing graph. Changing display metadata does not grant device
permissions. See [Runtime IDE](../runtime/runtime_ide.md),
[Modularity](../modularity.md) and [Module Management screens](../gui/visual_structure.md).

## Completion checklist and further reference

- You can select the physical boundary before starting a new run.
- You know which save button owns printer, rollout and task settings.
- You can locate one candidate's source evidence and retained files.
- You can distinguish Resume, a new Start and read-only Replay.
- You have not treated historical screenshots as current physical proof.

Keep `runs/<run-id>/` and its referenced artifacts together when archiving.
Connection/configuration files under `memory/` can contain secrets; do not publish
them as tutorial attachments.

For developer installation, tests and contribution workflow, use
[CONTRIBUTING](../../CONTRIBUTING.md). For the complete screen map, use
[GUI Structure](../gui/visual_structure.md).
