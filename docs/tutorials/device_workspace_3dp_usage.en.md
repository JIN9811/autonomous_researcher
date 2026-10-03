<!-- atr-doc
doc_type: guide
subtype: tutorial
status: active
authority: procedural
audience: [user, operator, researcher]
scope: [gui_tutorial, operator_workflow]
summary: Printer profile persistence, slicing-only verification and guarded physical execution.
source_of_truth:
  - web/templates/printer.html
  - web/static/printer.js
  - device_bridges/printer_fleet/bridge.py
last_verified: 2026-09-29
verified_against: fcfba9f
related_docs:
  - docs/gui/visual_structure.md
  - docs/runtime/test_mode.md
supersedes: []
-->

# 3D Printer Tutorial — Save, Slice, Inspect, Then Print

[한국어](device_workspace_3dp_usage.ko.md) · [Tutorial index](first_autonomous_run.md)

## Goal and preparation

Save the intended print profile and produce an inspectable sliced artifact
**without starting a print**. Physical execution is a separate final step.
You need the selected printer/slicer profile and a local STL or supported 3MF input.
For device work, also prepare the correct printer connection and a supervised,
clear workspace.

Open **Main → Device Workspaces → 3D Printer**, or `/printer`.
Figures are 1920 × 1080 captures from 29 September 2026. Their values are saved
installation examples, not a recommended profile. No slicing, transfer, print or
configuration save was triggered for these screenshots.

## Step 1 — Select the intended printer

Scroll to **Bridge Connection**.

1. In **Printer Fleet Selection**, inspect **Active Printer Profile**.
2. If changing devices, select the intended printer and click **Set Active Printer**.
3. For Bambu, inspect **Bambu LAN Connection**. Enter the actual host, serial and
   access code only in your private installation.
4. Confirm LAN-only/developer-mode checkboxes only after checking the printer.
5. Click **Set Bridge Connection**, then **Reload Connection** to verify persistence.

![Printer selection and private connection fields](assets/screenshots/2026-09-29/printer-connection.png)

**Expected:** the selected printer and connection match your device. An empty access
code field keeps the saved code; it is not proof that no password is configured.
Bambu is the default provider; another printer is an explicit selection, not an
automatic fallback. Do not publish connection JSON or screenshots with credentials.

## Step 2 — Set geometry placement and base print settings

Scroll to **Print Defaults**.

1. Match material, printer/nozzle profile, layer height and bed temperature to the
   actual setup and validated experiment.
2. Choose **Specimen placement**. For **Custom center X / Y**, enter the intended
   center in millimetres. Do not substitute a specimen edge coordinate.
3. Check skirt/brim/raft and cap-skin choices against the specimen design.
4. Enter **Bambu Source STL / 3MF Path** for the model you will slice.

![Print Defaults and specimen-center placement](assets/screenshots/2026-09-29/printer-defaults.png)

**Expected:** units, printer profile and placement match the intended setup and fit
the bed and handling path. Changing X/Y requires re-slicing the original model;
saving defaults does not relocate existing G-code.

## Step 3 — Save start, speed and calibration options

In **Print Start & Early Layers**, adjust only the controls required by your test.

![Independent print-start options and their save button](assets/screenshots/2026-09-29/printer-start-options.png)

| Control | What to check |
|---|---|
| First-layer override | First-layer height, speed and bed temperature are separate inputs |
| XYZ speed scale (%) | Enter 1–100 inclusive; 100 means no scaling reduction |
| Start-point prime | Separate enable checkbox and extrusion amount in mm; not a Z lift |
| Layer 2–5 speed cap | Independent enable checkbox and speed in mm/s |
| Early-layer Z cap | Independent enable checkbox for the configured early-layer interval |
| Bed leveling / flow calibration | Separate requested options, not proof that a calibration ran |

The shared scale applies to **XYZ motion**. The configuration key retains its historical
name `xy_speed_scale_percent`.

1. Enter values even if a corresponding checkbox is currently off.
2. Check only the options you want applied.
3. Click **Save Print Defaults**.
4. Reload the page and verify both numbers and checkbox states.

**Expected:** saved values survive reload; disabled options may retain values without
applying them. Existing artifacts and active prints remain unchanged.
**Test Specimen Defaults** is a fallback specimen setup, not the BO search-space editor.

## Step 4 — Generate a sliced artifact without printing

1. Confirm the source path belongs to the intended specimen.
2. Click **Slice Bambu Artifact** near the top of the workspace.
3. Wait for the response in **Bridge Evidence Log**.
4. Check the returned sliced-artifact path, hash and placement evidence.
   On success, **Bambu Sliced Artifact Path** is populated.
5. Inspect the generated project/G-code and available slicer mass/time evidence.

![Top-level preparation and execution controls](../gui/assets/screenshots/2026-09-29/printer.png)

**Expected:** “sliced artifact ready” evidence with **no upload or MQTT publish**.
This is the stopping point for a slicing-only exercise. A nonempty path without a
successful response is insufficient. If slicing fails, inspect the source path,
slicer executable/profile and failure code before continuing.

## Step 5 — Inspect auto-ejection separately

For an approved auto-ejection setup, scroll to **Bambu G-code Autoejection**.

1. Inspect native provider, direction, push offset/lane and sweep settings.
2. If editing, save with **Save Autoejection Config**.
3. Use **Validate G-code Preview** to inspect the generated routine.
4. Use **Generate Patched Artifact** when creating an artifact that includes the
   configured routine. Verify the returned path and validation evidence before use.

![Auto-ejection configuration and artifact controls](assets/screenshots/2026-09-29/printer-ejection.png)

**Expected:** generated/validated file evidence, not a claim that ejection happened.
**Fill Native G-code Defaults** changes the local form; it still needs save/generation.
Ejection/sweep test artifacts are motion programs if later executed.
Do not run them simply to test a button.

## Step 6 — Understand physical proof and start gates

![Physical Proof Package and completion audit](assets/screenshots/2026-09-29/printer-proof.png)

**Build Fail-Closed Proof Template** prepares an evidence template for you to fill in;
**Run Completion Audit** checks it. Neither button demonstrates physical ejection
by itself. **Mark Bed Clear** is a statement about the actual bed, not an error-reset
shortcut. Use it only after the relevant physical inspection.

For a supervised physical run, prefer the existing Live loop and its SPC handoff.
Standalone preparation exposes **Pre-start Check**, **Print Command Draft**,
**Start Gate Check** and **Publish Start**. They are not interchangeable:

- A draft is not a printer command execution.
- Passing a gate is not printing.
- **Publish Start** can start the device and is outside the slicing-only exercise.
- Upload-path probing and transfer can contact/write to the printer.

Use the exact prepared artifact and current approvals; never substitute an older
success record. Refer to the [Bambu bridge](../device_bridges/bambu_x2d_bridge.md)
for transport, cleanup and completion contracts.

## Step 7 — Watch the run-owned SPC evidence

In Live, select **SPC → Report**. Check current job identity, transfer/start result,
telemetry freshness, remaining time, camera and post-print handoff evidence.

![Run-owned SPC monitoring](../gui/assets/screenshots/2026-09-29/live-specimen.png)

**Expected:** evidence belongs to this run/artifact, not merely a printer that says
“idle” or an old job that says “finished.” A frozen camera frame does not establish
whether the printer stopped; inspect telemetry and frame timestamps separately.

## Troubleshooting and completion

| Symptom | Check first |
|---|---|
| Saved checkbox comes back differently | Save Print Defaults response, then reload; distinguish defaults from old artifact settings |
| Placement or speed did not change | Re-slice the original model and use the new artifact/hash |
| Slicer cannot find input | Server-local source path and selected slicer profile |
| Upload succeeds but no start | Current start-gate reasons and explicit execution approval |
| FTPS/video/MQTT disagree | Each channel's status and freshness; one does not prove another |
| Ejection shown as configured | Validation/proof and actual completion are separate |
| Values differ from screenshots | Use your saved/validated profile, not the illustration |

Finish by recording source path, saved configuration, output path/hash and the
validation result. Keep a slicing-only test explicitly labeled as such.

## Further reading

- [Printer fleet](../device_bridges/printer_fleet_bridge.md)
- [Bambu settings and implementation](../device_bridges/bambu_x2d_bridge.md)
- [SPC agent evidence](../agents/specimen_agent.md)
- [Execution profiles](../runtime/test_mode.md)
- [Operator walkthroughs](user_manual.en.md)
