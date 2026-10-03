<!-- atr-doc
doc_type: guide
subtype: tutorial
status: active
authority: procedural
audience: [user, operator, researcher]
scope: [gui_tutorial, operator_workflow]
summary: Camera configuration, frame freshness, pose diagnostics and run-bound verification walkthrough.
source_of_truth:
  - web/templates/vision_utm_device_bridge.html
  - web/static/vision_utm_device_bridge.js
  - app/main.py
last_verified: 2026-09-29
verified_against: fcfba9f
related_docs:
  - docs/gui/visual_structure.md
  - docs/runtime/test_mode.md
supersedes: []
-->

# Vision Tutorial — Camera Setup and Evidence Checks

[한국어](device_workspace_vision_camera_bridge_usage.ko.md) · [Tutorial index](first_autonomous_run.md)

## Goal and preparation

Prepare a UTM camera that keeps its saved configuration and delivers a fresh frame.
That is the core setup task in Steps 1–4. Afterward, inspect a run's actual Vision
decision, or choose the optional pose diagnostic and calibration sections only
when you need them. A successful workspace test is not a completed run verification.

You need the intended camera and a configured ROS/UTM installation. Check with the
operator before starting or stopping ROS, or releasing a camera used by an active
robot session. If another session owns the device, coordinate access rather than
using a release button to force a new capture.

Open **Main → Device Workspaces → Vision**, or `/device-bridge/vision-utm`.
The 1920 × 1080 figures were captured read-only on 29 September 2026; camera capture,
ROS commands and configuration saves were not executed for documentation.
Blank fields/panels are real unqueried state, not a successful setup example.

## Step 1 — Read the current camera configuration

Read the saved state before deciding whether setup needs changing. UTM camera
settings are separate from LeRobot's top/wrist camera settings.

1. Select **Runtime Bridge**.
2. Click **Load Config** to read the stored settings.
3. Inspect **Camera Profile**, device path, dimensions, camera FPS and pixel format.
4. Check the runtime/status banner before changing anything.

![Runtime Bridge controls and camera profile](../gui/assets/screenshots/2026-09-29/device-bridge-vision-utm.png)

The figure locates **Runtime Bridge** and the camera form. After loading, you should
be able to identify the saved device and capture settings. An empty form or an old
image cannot establish which camera will be used. If the saved configuration is
already correct, leave it unchanged and proceed to the runtime check.

## Step 2 — Select and save the actual device

Only change the configuration when it does not describe the camera you intend
to use. A detected device still needs to be matched to the physical installation.

1. If configuration is needed, click **Detect Devices**.
2. Select the intended entry in **Detected Cameras**, then check **Device path**.
3. Set width/height, camera FPS and a pixel format supported by this device.
4. Click **Apply Camera**, then **Load Config** to verify persistence.

After **Load Config**, compare the device, dimensions, FPS and format with what
you saved. They are stored locally in `memory/device_bridge/utm_camera_config.json`.
This establishes persistence, not frame delivery. Do not copy a path from another
computer or private serials from a screenshot. The
[UTM Vision Bridge](../device_bridges/utm_vision_bridge.md) lists supported settings
and dependencies if detection or saving fails.

## Step 3 — Start or check the UTM ROS runtime

Now check whether the saved camera can supply the required runtime evidence.
Reading configuration alone does not open a working stream.

1. Confirm no active experiment depends on the runtime you intend to change.
2. Use **ROS Loading** when startup is required.
3. Run **Pre Start Check** and read **Bridge Result**.
4. Verify the selected camera, ROS/frame evidence and any failure details.

![Live Frame Evidence and ROS graph area](assets/screenshots/2026-09-29/vision-frame.png)

Read **Bridge Result** for the camera source, fresh frame/runtime evidence and any
failure details. A loaded-process label or ROS graph picture alone is insufficient.
The figure deliberately contains no captured frame: use it to locate the evidence
area, not as an example of success. **ROS Unloading** and **Release Camera Ports**
change resource ownership; they are not browser refresh controls and must not be
used during a working run merely to update the picture.

## Step 4 — Check the preview without confusing rates

Observe the stream long enough to distinguish a current preview from a retained
still image:

1. In **Live Frame Evidence**, set **Preview FPS**.
2. Click **Play Live**.
3. Verify that the image changes and its status/evidence is current.
4. Click **Stop Live** when you finish observing.

Check the configured topic and frame freshness, not just whether pixels are visible.
**Preview FPS** requests a browser delivery rate; it cannot raise camera acquisition
rate. If the preview is slow, compare frame timestamps with the source stream before
increasing the preview setting. A slow source needs a camera/USB/ROS check, described
in the [UTM ROS bridge](../hardware/utm_ros_vision_runtime_bridge.md).

The setup task is complete when the intended configuration survives reload and a
fresh authorized frame is visible in your environment. Keep the selected device,
source/topic and check result for later diagnosis. To assess an experiment, continue
to [run verification](#inspect-the-runs-actual-verification); neither a pose test nor
calibration is required merely to finish camera setup.

<a id="step-5--use-pose-diagnostics-for-their-stated-purpose"></a>

## Optional: diagnose a pose source

Open **Specimen Pose Test** when you need to isolate a pose-source problem. Select
the diagnostic by its source rather than trying every button until one passes.

![Pose test modes and their distinct sources](assets/screenshots/2026-09-29/vision-pose.png)

1. Use **Load Pose Status** to inspect the tracker and camera ownership/lease.
2. Choose the intended diagnostic from the table below.
3. Inspect **Snapshot Payload**, **Pose Summary** and **Pose API Result** together.

| Diagnostic | What it checks | What it cannot establish |
|---|---|---|
| Virtual Pose Test | The pose contract without a physical camera | Detection in a real scene |
| Live D455F Snapshot | The configured D455F topics under supervision | Completion of a separate run's verification |
| D405 Smoke Snapshot | A separate D405 hardware path | A substitute for the loop's selected camera |

The figure groups diagnostics that use different sources. Read the result's source,
mode and specimen identity before interpreting it. Preserve a virtual result as
virtual even if it passes. **Release VLA Camera** can disrupt the owning session;
an empty panel is not a reason to press it while inference is active.

<a id="step-6--inspect-the-runs-actual-verification"></a>

## Inspect the run's actual verification

For an active experiment, return to Live and select **VIS → Report**. This is where
you determine whether the required observation and decision belong to that run.

![Vision Agent observation and verification report](../gui/assets/screenshots/2026-09-29/live-vision.png)

1. Match the run and cycle to the experiment being reviewed.
2. Check the selected observation (**Active Cam** or verification slot), image and
   region of interest (ROI).
3. Read the associated decision evidence. Image delivery and completion of the LLM
   decision occur at different times, so a new picture alone is not a pass.

Use the historical figure to locate the observation and verification report, then
look for a current capture and matching decision for the required step in your run.
Workspace diagnostics do not mark that step complete. If the camera moved, realign
the physical view to the configured ROI or use an explicitly reviewed calibration
change; do not alter thresholds merely to obtain a pass. The
[Vision Agent](../agents/vision_agent.md) explains observation roles. If review fails,
preserve the image, decision and exact reason, then consult
[Vision review recovery](../gui/vision_review_recovery.md) before resuming the run.

<a id="step-7--calibrate-only-when-required"></a>

## Maintenance only: calibrate the camera

Calibration changes the camera model and requires an available camera in a maintenance
window. Do not include it in ordinary page navigation or interrupt a working experiment
to reproduce this guide.

1. Prepare the actual checkerboard and measure its square size in metres.
2. Enter **Checkerboard size**, **Square size m** and the intended calibration file.
3. Use **Calibrate** only in a maintenance window with the camera available.
4. Inspect the calibration output; **Stop Calibrate** closes that calibration session.

Inspect the produced calibration evidence and confirm that it describes the actual
camera and target. A filled output path does not prove that calibration succeeded.
A placeholder such as 9×6 is an input example, not a reason to use a different board.
Keep the calibration result with the configuration it supports.

## Troubleshooting and completion

| Symptom | First check |
|---|---|
| No device found | OS/USB connection, permissions and Detect Devices result |
| Empty frame | Camera selection, runtime, topic and Pre Start Check details |
| Old image | Capture/frame timestamp and source, not only visible pixels |
| Busy camera | Active owner/lease; coordinate before releasing it |
| Slow preview | Actual acquisition/ROS rate versus preview delivery rate |
| Pose test passes but VIS waits | Test mode/source versus the required run-bound verification |

Report the outcome of the task you actually performed: saved configuration and fresh
frame for setup, source-specific evidence for a diagnostic, or a run-bound image and
decision for verification. The documentation captures satisfy none of those checks
for today's session. Keep results and failures distinguishable, and return to the
[operator manual](user_manual.en.md) for run recovery or other device tasks.
