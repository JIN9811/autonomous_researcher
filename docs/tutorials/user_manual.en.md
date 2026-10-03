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

<a id="operator-walkthroughs"></a>

# AX4LAB Operator Manual

[한국어](user_manual.ko.md) · [First run](first_autonomous_run.en.md) · [Tutorial index](first_autonomous_run.md)

## Before you start

Use this manual to prepare the next experiment, perform a supervised device task,
or inspect and recover an existing run. You do not need to complete every section
in order. If you have not yet followed a candidate from planning to saved output,
complete the [first virtual run](first_autonomous_run.en.md) first.

Start with [Install](../../install/README.md) on a new workstation. On an installed
Linux/WSL system, use `atr up` and open `http://localhost:7860`; native Windows uses
`python -m app.serve` from its prepared environment. Use an existing server if a run
is active. First-time device setup requires a trained operator, and these procedures
do not authorize unattended robot or UTM motion.

Figures are 1920 × 1080 captures from 29 September 2026. Some show historical or idle
state; none is a new hardware test. Private paths/connection details are redacted.
Values shown are not universal settings.

<a id="exercise-1--find-the-right-workspace"></a>

## Choose a workspace for the task

Workspaces prepare devices and defaults; Live contains the commands, approvals and
reports for a particular experiment. Keep that distinction when deciding where to
work: a successful standalone action does not complete a waiting Live step.

1. Open Main and scroll to **Device Workspaces**.
2. Choose the device you intend to configure.
3. Keep Live GUI for run-bound commands, approvals and agent reports.

![Main workspace navigation](../gui/assets/screenshots/2026-09-29/main-workspaces.png)

| Task | Workspace | Tutorial/reference |
|---|---|---|
| Print defaults, slicing, transfer | 3D Printer, `/printer` | [Printer walkthrough](device_workspace_3dp_usage.en.md) |
| Robot devices and demonstration recording | Manipulation, `/lerobot` | [Record one demonstration](#record-one-robot-demonstration) |
| Policy rollout and loop task defaults | Manipulation, `/lerobot` | [Configure the correct execution path](#configure-a-policy-for-standalone-or-loop-use) |
| UTM camera and ROS | Vision, `/device-bridge/vision-utm` | [Vision walkthrough](device_workspace_vision_camera_bridge_usage.en.md) |
| Windows bridge and Skills | Windows Automation, `/equipment/windows` | [Prepare equipment automation](#prepare-windowsutm-automation) |
| BO configuration | Bayesian Optimization, `/bo` | [Trace a candidate's result](#trace-a-result-from-design-to-optimization) |
| Hardware interlocks | PLC Safety, `/plc` | [PLC bridge](../device_bridges/plc_safety_bridge.md) |
| Retained knowledge | Knowledge, `/knowledge` | [Check a knowledge source](#check-the-source-of-retained-knowledge) |
| Blocked experiment | Live | [Diagnose and resume](#diagnose-and-resume-the-same-run) |
| Saved session | Main → replay | [Review without device actions](#review-a-saved-session-without-device-actions) |
| Workflow structure and runtime evidence | Runtime IDE, `/ide` | [Inspect the workflow](#inspect-the-workflow-in-runtime-ide) |

The Main figure locates the workspace launchers. After inspecting a workspace,
return to the same Live run and check its ID before giving a run-bound instruction.
Opening the workspace does not start or complete an agent stage.

<a id="exercise-2--move-from-virtual-testing-to-hardware"></a>

## Prepare a new run to use hardware

Move beyond Virtual Bridge only when the selected devices are commissioned, the
work area is ready and an operator can supervise. **Test** is not a safety boundary
by itself. Choose the intended physical effects before submitting a new request:

1. Open **Test Mode Settings** from Main.
2. Compare **Installed Printer** and **Physical Print**.
3. Inspect each agent's boundary, print-body/cooling choices and auto-ejection.
4. Save only the profile you intend to use; reload to verify.
5. In Live, explicitly request the matching scenario:
   `테스트 모드, 실제 프린터` or `테스트 모드, 실제 출력`.

![Installed Printer: ejection path without printing the body](assets/screenshots/2026-09-29/profile-installed.png)

![Physical Print: printing and cooling enabled](assets/screenshots/2026-09-29/profile-physical.png)

Use the two figures to compare print-body and cooling choices, not to copy their
saved values. Confirm that the reviewed experiment contract names the profile you
selected. **Installed Printer** skips the print body and cooling but can send an
ejection-only artifact and operate downstream real devices. **Physical Print** uses
the full print path. If you supply a specimen yourself, respond to the current
operator request only after observing that it is actually present or removed.

Passing the installed-printer exercise does not validate first-layer adhesion,
full print duration or nozzle-cleaning performance. Validate physical printing
separately under supervision. Profile edits affect the next admitted run, not an
already running one. See [Test Mode](../runtime/test_mode.md).

<a id="exercise-3--configure-robot-ports-and-record-one-demonstration"></a>

## Record one robot demonstration

A demonstration records camera and joint/action data for later training. Recording
is a supervised robot operation, not a training run or an autonomous experiment.
Prepare calibrated devices, available cameras and a new local dataset identity
before starting; stop if another session owns the same hardware.

1. Open **Manipulation → Profile** and select the intended robot profile.
2. Expand **2. Device Port Setup**. Read the saved follower, leader and camera entries.
3. If setup is needed, use **Baseline** then **ID Detect & Save** for the intended
   device, following the displayed detection guidance. Alternatively expand
   **Manual Port Override**, select the role/camera key and **Save Manual Port**.
   These are configuration actions, not harmless inspection buttons.
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

In the figures, port setup is separate from episode controls. After normal closure,
open the intended dataset and verify that the accepted episode contains the expected
camera frames and joint/action channels. Keep the dataset identity and session log
with that result; a process that launched but saved no data is not a recording.

If startup fails, use the session log to distinguish a port, calibration, camera
ownership or dataset-compatibility problem before retrying. Do not erase calibration
or reconnect an owned device as a generic repair. The
[LeRobot bridge](../device_bridges/lerobot_bridge.md) gives the detailed setup and
recording contract for the selected profile.

<a id="exercise-4--configure-standalone-inference-and-the-experiment-bridge"></a>

## Configure a policy for standalone or loop use

A standalone rollout tests a policy directly; the experiment loop reads a separate
task configuration. Decide which path you are preparing, then save in that path's
section. Both can move the robot, so check calibration, hardware ownership and the
clear work area before execution.

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

The first figure is the standalone form; the second is the task-specific bridge.
Recheck the saved policy, task, rates and options in the section you will actually
use. **Save Rollout Defaults** does not update **Save Task Defaults**, or vice versa.
During a loop-owned run, inspect MAN's measured telemetry, policy tracking and
artifacts. A rendered robot does not establish grasp or placement success. Never
start a standalone rollout while the loop owns manipulation.

<a id="exercise-5--prepare-windowsutm-automation"></a>

## Prepare Windows/UTM automation

A connected worker can still show the wrong application or method. Before approving
equipment execution, coordinate with the equipment operator and inspect both the
target desktop and the sequence that will act on it. For a new worker, complete
[bridge installation and pairing](../../Pyautogui_server_for_window/README.md) first.

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

The workspace figure locates the desktop view; the Agent Manager figure shows where
to inspect the ordered flow. Check worker identity, application, method and Skills
together. Before EQP executes, the required current observations must belong to that
run. A green connection indicator proves neither compression nor height return;
those need their own completion evidence. If the desktop or method is wrong, resolve
that with the equipment operator rather than editing an active flow to skip the step.

<a id="exercise-6--inspect-one-candidate-from-design-to-optimization"></a>

## Trace a result from design to optimization

Use this check before interpreting or sharing a result. The
[first-run walkthrough](first_autonomous_run.en.md#step-7--read-analysis-and-bo)
explains basic navigation; here the task is to establish which measurement produced
which optimization observation. Start with one run, cycle and candidate identity.

1. In Live, select **DSN → Report**. Record candidate ID, cell size, wall thickness,
   geometry artifact and constraint result.
2. Select **ANL → Report**. Check the selected cycle, stress–strain (SS) and
   force–displacement (FD) axes and units, source CSV, mass used for specific energy
   absorption (SEA), and the actual integration/strain evidence.
3. Select **BO → Report**. Check objective identity/direction and observation count.
4. If a Gaussian-process (GP) model exists, inspect its 2D/3D mean, uncertainty,
   acquisition and next candidate. For cell size and wall thickness, an old 1D
   display is not the full design space.

![Analysis report with curve and performance evidence](../gui/assets/screenshots/2026-09-29/live-analysis.png)

![BO posterior and recommendation](../gui/assets/screenshots/2026-09-29/live-bo.png)

Keep a small evidence bundle: candidate identity and geometry path, source CSV,
analyzed metric with units and mass source, and the BO observation that consumed it.
Before slicing, absent mass is unknown; afterward use the recorded analysis mass,
not an unrelated geometry estimate. If the identities or sources do not agree, do
not combine the values into a result.

The figures show historical analysis and optimization, not a fresh measurement.
A proposed BO candidate has not yet been tested. An initial Latin-hypercube
sampling (LHS) view may correctly lack GP data. See
[Analysis](../agents/analysis_agent.md) and [BO](../agents/bo_agent.md) for metric and
model interpretation, and [artifact preservation](../gui/artifact_preservation.md)
for retaining the complete source chain.

<a id="exercise-7--find-retained-knowledge-without-changing-run-evidence"></a>

## Check the source of retained knowledge

Use Knowledge to understand prior procedures and observations, then decide whether
they apply to the current task. It is not a substitute for today's camera image or
device completion record.

1. Open **Knowledge → Wiki**.
2. Select an article and read its source references and scope.
3. Use **Source Library** to inspect provenance. Memory and Agent Delivery are
   separate views, not additional physical sensors.

![Knowledge Wiki with source-backed content](../gui/assets/screenshots/2026-09-29/knowledge-wiki.png)

The article view in the figure should lead you back to a source and its scope.
Before using a statement, distinguish historical evidence, procedural instructions
and current run evidence. Private views require authorization: request access if
you receive a 401 rather than bypassing it. For source and memory operations, see
[Knowledge operations](../knowledge/markdown_memory_operations.en.md).

<a id="exercise-8--diagnose-and-resume-the-same-run"></a>

## Diagnose and resume the same run

When a run pauses, preserve its identity and evidence before changing anything.
The Timeline figure locates the sequence of events that explains where it stopped.
Do not assume that clearing a device warning also resumes the experiment.

1. Note run ID, cycle, agent and the exact unresolved reason.
2. Open that agent's **Timeline**, **Artifacts**, and **Backend** as needed.
3. Correct the actual cause (connection, missing input or physical state), keeping
   the current run's evidence intact.
4. Use the existing **Resume** control if the runtime offers recovery.
5. Confirm the same run ID and intended continuation point; verify the new evidence.

![Timeline for locating a blocked step](../gui/assets/screenshots/2026-09-29/live-timeline.png)

Recovery should add evidence to the same run. **Resume** may repeat a recoverable
step, so inspect the requested continuation and actual device state before approving
motion; it does not guarantee exactly-once physical execution. Do not copy completion
flags to a new run, delete failure history, clear PLC latches blindly or use **Start**
as Resume.

Use [Resume](../gui/run_resume.md) for the continuation rules,
[printer wait recovery](../gui/printer_wait_recovery.md) if printing is still pending,
and [Vision review recovery](../gui/vision_review_recovery.md) for a failed review.
If no eligible Resume is offered, retain the run ID and failure details for support
instead of trying an administrator checkpoint operation on your own.

<a id="exercise-9--open-a-read-only-replay"></a>

## Review a saved session without device actions

Use Main's Replay to inspect recorded states after a run or during a handover.
It reads retained evidence; it is not LeRobot motion replay and does not recreate
missing observations by querying live devices.

1. Return to Main; choose **Mode = replay**.
2. Select an **Experiment session** and click **Start**.
3. In the new window, use the Contract-area point selector.
4. Use Left/Right to move between recorded points and Up/Down between available
   cycles. Keyboard shortcuts do not take over text/select inputs.

![Replay session selector in Main](assets/screenshots/2026-09-29/main-replay.png)

![Replay window reusing the Live layout](../gui/assets/screenshots/2026-09-29/replay.png)

Look for **REPLAY** in the header and verify that the selected run/cycle/point changes
as you navigate. The Main figure shows the session selector; the second figure shows
the resulting read-only window. A missing snapshot must stay identifiable as missing.
An artifact can remain available without a corresponding recorded point, so distinguish
point-bound evidence from a general retained file. See [Replay](../gui/run_replay.md).

<a id="exercise-10--inspect-runtime-composition-without-changing-the-loop"></a>

## Inspect the workflow in Runtime IDE

Runtime IDE is also an operating tool: use it to understand which module comes next,
how a connection is defined and where its runtime evidence appears. Observation
does not require editing or activating a workflow.

1. Open `/ide` and inspect the graph and node/module configuration.
2. Follow an edge to its contract and locate the associated runtime evidence.
3. For a separate development task, use draft validation/compile/dry-run before any
   saved-version activation. Do not activate edits during this tutorial.

![Runtime IDE graph and inspector](../gui/assets/screenshots/2026-09-29/ide-graph.png)

Use the graph and inspector in the figure to relate a visible report to a module,
its connection contract and the executing graph. Display metadata does not grant
device permissions. For normal inspection, continue with [Runtime IDE](../runtime/runtime_ide.md).
If you intend to extend the system, treat that as a separate development task:
read [Modularity](../modularity.md), [Module Management screens](../gui/visual_structure.md)
and [CONTRIBUTING](../../CONTRIBUTING.md) before validating, compiling, dry-running or
activating an edited version.

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
