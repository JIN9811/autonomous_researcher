<!-- atr-doc
doc_type: reference
subtype: runtime
status: active
authority: descriptive
audience: [researcher, operator, developer, integrator]
scope: [windows_pyautogui, equipment_worker, pairing, recording]
summary: Lightweight Windows worker contract for paired bounded PyAutoGUI programs and recording evidence.
source_of_truth:
  - Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py
  - install/windows_pyautogui_bridge_server.py
  - device_bridges/windows_pyautogui/bridge.py
  - device_bridges/windows_pyautogui/tools.py
  - device_bridges/windows_pyautogui/module.py
  - device_bridges/windows_pyautogui/README.md
  - packages/agents/equipment/package.yaml
last_verified: 2026-09-29
verified_against: dd0d772
related_docs:
  - docs/agents/equipment_agent.md
  - docs/hardware/windows_pyautogui_bridge_windows_setup.md
  - Pyautogui_server_for_window/README.md
supersedes: []
-->

Verification scope: full-document read and static source/configuration inspection
at `dd0d772`; no hardware, model-provider or service execution. Dated test and
physical-evidence entries below retain their original scope and are not rerun claims.

# Windows PyAutoGUI Bridge Reference

<img src="../../web/static/workspace_icons/windows.webp" width="96" alt="Windows Automation Workspace icon">

Main GUI: **Windows Automation · Workspace** opens the Windows bridge workspace in a separate window.

## Status at a Glance

| At a glance | Details |
|---|---|
| Purpose | Paired desktop programs, recording and execution evidence |
| Connects | Lab Equipment / workspace ↔ Windows worker |
| Effect | GUI input can operate equipment through the selected application |
| Implementation | [Installed bridge module](../../device_bridges/windows_pyautogui/module.py) · [Windows bridge](../../device_bridges/windows_pyautogui/bridge.py) |
| Package | `windows_pyautogui@1.0.0`, referenced once by `equipment@1.0.0` |
| Verification | Guarded software/API checks through 2026-09-13; no new hardware validation implied |

## Summary

The Windows PyAutoGUI Bridge is the low-level worker for the Linux Equipment
Runtime. It executes validated desktop programs and returns screens, locators,
recordings, files, and request logs.

It does not own LLM or Guardian decisions, the Skill lifecycle, UTM experiment
semantics, completion assessment, the Analysis handoff, or ATR Controller discovery.

## Scope

Paired Windows and explicit Local workers, bounded desktop programs, recordings,
locator evidence and file export. Equipment owns experiment decisions and completion;
this low-level worker does not start a loop or grant device approval.

## Source of Truth

- `device_bridges/windows_pyautogui/bridge.py`, `tools.py`, `module.py`
- `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- `packages/agents/equipment/package.yaml`

Main-code contract inspected at `e70daa1` on 2026-09-28. The dated migration
verification below is retained with its original no-device scope.

## Actual Role

`device_bridges/windows_pyautogui/module.py` declares the installed
`windows_pyautogui@1.0.0` Bridge Module and runtime identity
`windows_pyautogui_bridge`. The Equipment Agent Package references that bridge
once; the package is a composition contract, not a device or a second worker.
All 18 existing registered tool IDs and the `equipment:windows_pyautogui` queue
remain unchanged. The flat bridge and tool imports are exact compatibility
aliases, so existing imports and monkeypatch targets resolve to the canonical
module objects.

Package and Runtime IDE views show `Equipment Package → Windows/PyAutoGUI →`
the existing bridge, transport, local/Windows worker, profiles, Skills, Flow,
runtime and evidence components. These are source-bound inspection links. They
do not install, pair, select, start, stop, update or execute a worker. The
existing `/equipment/windows` workspace remains the only declared bridge
workspace for both explicit Windows and Local provider selections.

## System Position and Agent Handoffs

![Windows worker handoffs](assets/figures/windows_pyautogui_01_system_handoffs.svg)

**Figure Windows PyAutoGUI-1.** Existing Equipment/bridge/worker boundaries;
inspection diagram, not a physical execution certificate.

## Inputs, Commands, and Outputs

A program declares bounded actions, a target window, timeouts, and
locators/checkpoints.

- Built-in `program1` is a non-deletable demonstration.
- A local draft can be tested only on the Windows worker.
- A deployed program is a read-only cache validated by Linux.
- A retired program cannot start a new execution.

Windows validates action allowlists and bounds; it does not reinterpret the
program's experimental meaning.

## Internal Execution

Recording captures keyboard/mouse events with monotonic timestamps and writes
full-screen frames directly to disk at a fixed **2 FPS** from start to stop.
An append-only `timeline.jsonl` connects periodic JPEGs and event/boundary PNGs
through `pre_frame_id`, `event_frame_id`, and `post_frame_id`. Only a small
recent-frame cache for pre-action assessment remains in RAM.

One topmost overlay provides the user's Stop control.
`RecordingManager.stop()` closes the listener and overlay, saves a clean final
frame, and releases frame memory. Bounded Evidence exposes no separate Stop
while active and synchronizes terminal state through `/recordings/status`.
Preview returns only browser-ready frames in the requested cursor/limit page,
never absolute Windows paths.

Declare private screen regions when starting recording. `mask_regions`
accepts at most **32** `{x, y, width, height}` entries. Masks apply to frame
buffers, event/exception evidence, visual-locator source images, and checkpoints.
A masking failure returns a recording error rather than silently saving the
unmasked evidence.

Linux imports evidence through `GET /recordings/{id}/package`. This endpoint
requires internal-key authentication even on localhost and returns each file's
relative path, size, and SHA-256. Linux verifies and saves the package under
`artifacts/equipment/recording_imports/{recording_id}`, replacing Windows
absolute-path references with Linux artifact paths.

Recording analysis and Skill generation happen on Linux. The annotator builds
**4 × 4 storyboards from 16 source frames** and processes every chunk sequentially
through the selected shared multimodal backend. Each chunk must return all
source-frame IDs in order; missing or reordered IDs fail validation. Completed
chunk JSON survives a safe stop. A final synthesis combines the session overview
and chunk analyses. The model interprets initial state → action → state change →
completion/failure evidence and saves `workflow_summary` and
`step_transitions`. Normal execution uses the compiled deterministic program;
it does not repeat this model interpretation.

The workspace lists recordings for the selected worker through
`GET /api/equipment/workers/{bridge_id}/recordings`. It queries that live worker
only, with no simulator or other-worker fallback. Package verification and import
begin only after the user selects a recording.

![Execution boundary](assets/figures/windows_pyautogui_02_execution_effect_boundary.svg)

**Figure Windows PyAutoGUI-2.** Bounded worker execution and evidence return;
inspection scope. The recording behavior is described above.

## API Surface

| API | Authentication and scope |
|---|---|
| `GET /health` | Local access before pairing; internal key for remote access |
| `GET /pairing/status` | Local setup |
| `POST /pairing/new-code` | Local setup |
| `POST /pairing/complete` | One-time code exchange |
| `GET /programs` | Local setup or paired remote access |
| `POST /programs/validate` | Local setup |
| `POST /programs/register` | Local setup or paired deployment |
| `DELETE /programs/{id}` | Deletable local drafts |
| `POST /execute` | Paired, bounded action with possible physical effects |
| `POST /screenshot` | Paired evidence capture |
| `POST /locators/capture` | Paired locator capture |
| `/recordings/...` | Recording management without mandatory pairing |
| `GET /recordings/{id}/package` | Paired recording-evidence transfer |
| `GET /artifacts`, `/request-log` | Paired evidence/audit access |
| `GET /update/status` | Paired worker version/update state |
| `POST /update/stage` | Paired, bounded release staging |
| `POST /update/apply` | Paired process replacement while recording is idle |
| `POST /update/rollback` | Paired latest-backup restoration while recording is idle |

![API connections](assets/figures/windows_pyautogui_03_api_connection_architecture.svg)

**Figure Windows PyAutoGUI-3.** Existing transport and API connections;
inspection scope, not permission to operate an instrument.

## Tools and Registry Integration

The installed module declares the existing registered tool IDs and queue;
see [bridge tools](../../device_bridges/windows_pyautogui/tools.py) and the
[connection matrix](bridge_api_connection_matrix.md). The owning package does
not create a second execution worker.

## Connections and Protocols

`WindowsPyAutoGUIBridge` reads the URL, internal key, timeout, and candidate
alias from connection memory. **Scan** identifies candidates from the public
`/discovery` endpoint's minimal metadata, without a pairing code. Discovery
runs only on an actual scan. Periodic supervision instead uses the
`text/plain` `/ping` every **5 seconds**, without adding request-audit entries.

Enter the **four-digit code** in the discovered Candidate card and choose
**Pair & Save** to exchange an internal key. Public discovery does not grant
access to health, execution, file transfer, or updates. A request with
`bridge_id` must match that saved candidate exactly; a missing candidate blocks
the request rather than falling back to the currently selected worker.
Select, Health, Programs, Test, Run, and recording import/deploy/delete retain
the same worker identity. Local and Windows are explicit provider choices,
not automatic fallbacks.

<a id="saved-worker-업데이트"></a>

### Update a saved worker

A Saved Worker card supplies its candidate alias in both the URL path and bridge
payload. Check, Update, and Rollback therefore target that card's worker without
changing the selected worker. An unregistered alias is rejected.

Linux builds release packages from
`Pyautogui_server_for_window/release_manifest.json`, the authority for version
and file inventory. Source files and startup commands do not hard-code the
release number. Windows stages only paths allowed by **both** that manifest and
`UPDATE_ALLOWED_PATHS`, after checking per-file size/SHA-256 and the package
digest.

The installed `ATR_WINDOWS_BRIDGE_INSTALL_ROOT` defines the canonical package
root. Normal startup and the logon task call only
`scripts/start_supervisor.ps1`, which supervises that worker. Applying an update
creates `updates/update_in_progress.json` to prevent duplicate startup and keeps
the current files in `updates/backups/<backup-id>`.

The self-updater stops the old server, atomically replaces canonical files,
synchronizes dependencies, restarts the canonical server, and checks that local
`/ping` reports the target manifest version. Unchanged
`requirements-windows.txt` skips pip. If the old worker survives its graceful
shutdown allowance, only that worker's process tree is terminated. A subsequent
error restores the backup; if updater recovery also fails, the independent
supervisor releases the lock and restarts the canonical worker. Results are in
`updates/status.json`; supervisor state is in `supervisor/status.json`.
Frozen EXEs are recorded as bundled runtimes.

Active recording blocks apply/rollback with
`PYAUTOGUI_UPDATE_RECORDING_ACTIVE`. User data, pairing keys, recordings,
programs, locators, and artifacts are excluded from the release manifest.

Older workers, or workers without a saved canonical root, need one manual
installation using the new package's `INSTALL_WINDOWS_BRIDGE.cmd`. Afterward,
use the Saved Worker controls without moving the package folder again.

## Configuration and Secrets

| Deployment | Location or requirement |
|---|---|
| Installed | The copied package folder containing `INSTALL_WINDOWS_BRIDGE.cmd`; the installer creates `.venv` there |
| Portable | Bundled `runtime\python` and `data\` inside the folder |
| Development | Explicit Local Bridge using the same server on Linux X11 |

Installed and portable deployments use the same API and program format.
PyAutoGUI requires an interactive desktop; it does not run as a Windows service.
The installer keeps the program in that package folder rather than creating a
second `%LOCALAPPDATA%\Programs` copy. Its default data root is
`%LOCALAPPDATA%\ATR\PyAutoGUIBridge`; see the
[installation guide](../hardware/windows_pyautogui_bridge_windows_setup.md).

### Pairing and authentication

Initial pairing uses a four-digit, one-time code:

- Valid for **300 seconds**, with at most **5 attempts**.
- Discarded immediately on success; **30-second lockout** after the failure limit.
- Exchanges an automatically generated long-term internal key, saved in
  protected Windows and Linux connection memory.

Users do not repeatedly copy the long-term key. Later requests use the saved
worker secret or exchanged internal key. Neither pairing codes nor internal
keys are written to URLs, browser storage, or the request audit.

Before pairing, the local Console permits its GUI and Health, pairing
status/new-code functions, Program Manager, and Recording. Remote execution,
screenshots, locators, artifacts, request logs, and updates require saved
connection authentication. Pairing status does not invalidate a previously
stored worker secret.

Recording start/status/list/preview/checkpoint/stop/save/delete do not require
pairing. Exporting evidence through `GET /recordings/{id}/package` still
requires saved connection authentication. Every POST request requires
`Content-Type: application/json`.

### Data locations

```text
<data-root>/
  artifacts/bridge_requests.jsonl
  artifacts/pairing.json
  locators/
  programs/
  recordings/
  utm_exports/
```

Do not commit `pairing.json`, connection memory, or user programs/recordings.
The module reuses existing Linux storage:
`memory/windows_pyautogui_connection.json`, `memory/equipment_runtime/`,
`memory/equipment_skills/`, current workspace templates/assets, and run-scoped
artifacts. Windows program, locator, recording, request-log, and export data
remain under the selected worker's `<data-root>`. No second store is created.

## State, Events, Artifacts, and Evidence

Acceptance by `/execute` is not physical completion. The worker returns raw
step traces, screenshots, locators, file metadata, and request identity.
Linux Equipment Runtime assesses completion once using the Profile's completion
policy. A deterministic Skill segment ending means `execution_complete`;
it is not promoted to `ready_for_analysis` before the policy verifies evidence.

A timeout after dispatch leaves the effect unknown. Inspect the desktop, request
log, actual instrument, and result files before repeating the operation.

<a id="순차-skill-편집과-배포"></a>

### Edit and deploy a sequential Skill

Select the exact Skill version and open its Workflow Editor in a separate
window. The editor changes the order and action fields in `workflow.json`,
not Windows `programs/*.json` directly. It supports moving, duplicating, and
deleting steps; replacing locator PNGs; fixed waits; and image/text/file
condition waits. Condition waits require a timeout and polling interval.

For an image action, **Edit Crop** reads the hash-verified pre-action full frame
retained by Linux and changes only Target ROI. Context ROI and auxiliary
candidates remain intact. The crop is saved as a PNG with a longest side of at
most **512 pixels**. **Reset to AI** restores the initial annotation ROI.
**Replace Locator** instead uses a user-selected PNG. Neither action deploys
changes before the editor's **Save**.

Save uses an optimistic workflow hash. If another window changed the same
version, the editor retains local edits and reports a conflict. A successful
save invalidates the previous compile/validation outputs. One **Deploy** runs
compile → validate → package → register → verify on Linux. Deployment does
**not** call `/execute`. Separate Compile/Validate GUI buttons are hidden, but
their APIs remain for automation and CLI compatibility.

## Runtime Modes and Fallbacks

Windows and Local providers are explicit selections. Neither silently replaces
the other. Virtual-device tests do not establish Windows desktop or physical
UTM readiness; current run identity and selected worker remain authoritative.

## Safety, Approval, and Effect Boundary

- Keep the PyAutoGUI failsafe enabled.
- Enforce allowed actions, hotkeys, step counts, and time bounds.
- Do not accept arbitrary Python or shell payloads.
- Exclude credentials from programs and recordings.
- Do not switch providers automatically on Windows.
- Validate physical equipment separately through the Profile's on-site procedure.

## Errors, Timeouts, and Recovery

A transport timeout after dispatch may have an unknown desktop/device effect.
Inspect current worker execution and fresh evidence through Equipment's existing
recovery route; do not infer no motion or repeat a command from an HTTP error.
See [Equipment selection recovery](../gui/equipment_selection_recovery.md) and
[Resume](../gui/run_resume.md). Stale screenshots and historical completion do
not satisfy a new acquisition.

## Operator and GUI Surfaces

### GUI Screen Reference

![Windows equipment connection workspace](../gui/assets/screenshots/2026-09-29/equipment-windows.png)

*Windows equipment connection workspace.*

![Equipment Agent Manager: deployed Skill and Vision sequence](../gui/assets/screenshots/2026-09-29/equipment-agent-manager.png)

*Equipment Agent Manager: deployed Skill and Vision sequence.*

The Windows workspace owns worker/profile setup; Agent Manager displays the profile-bound Flow. Displaying a saved worker or Flow does not execute its actions.
Captured on 2026-09-29 at 1920 × 1080; private values are redacted.
See the [GUI structure guide](../gui/visual_structure.md) for navigation and capture conditions.


### Windows Console

The default Console has four areas: **Bridge Status**, **Program Manager**,
**Recording**, and **Latest Local Result**. Collapsed Diagnostics loads raw
Health and request logs only when requested. The Console does not expose UTM
proof assessment, Skill compile/deploy, Analysis handoff, model controls, or
closed-loop control.

### Linux Lab Equipment Workspace

`/equipment/windows` is the Linux-owned equipment workspace, not a copy of the
Windows Console. Its sections follow the setup-to-evidence workflow:

1. **Profile & Worker** selects the exact Equipment Profile and saved worker.
2. **Connection & Profile** handles scan/pair/select and Local Bridge development targets.
3. **Agentic Progress** shows Record, Transfer, Annotate, Build Skill, Preflight,
   Execute, Verify, and Handoff from the canonical execution snapshot.
4. **Skill Recording** imports the Windows package, analyzes its 2 FPS timeline,
   and produces a Skill draft. Completed or interrupted chunk storyboards are paginated.
5. **Skill Management** reviews and saves the exact version in Workflow Editor,
   then uses one Deploy for build/check/transfer.
6. **Main Progress** executes the bounded macro for the selected Profile and Skill/program.
7. **Vision Link** requests optional, Profile-specific Middle-Level verification.
8. **Error Recovery** uses the selected model only for exceptions, not normal execution.
9. **Evidence & Data Transfer** exposes screen/data/Vision/request evidence and the Analysis handoff audit.

The frontend reads `/api/equipment/runtime/current` and
`/api/equipment/skills`; Profile actions use
`/api/equipment/profiles/{profile_id}/preflight|test`. The Vision checkbox sends
`vision_link_enabled`, and the response distinguishes `requested`,
`profile_enabled`, `required`, and `effective`. Clearing the checkbox cannot
weaken Vision required by the Profile for that mode.

Each toggle immediately saves the Profile-specific preference in
`memory/equipment_workspace_settings.json`. It survives page closure, refresh,
and server restart. Only a new Profile without a saved preference uses its
default. Screenshot and physical-equipment safety confirmations are deliberately
not persisted: they approve an individual operation.

Device-specific locators, exports, and physical-validation settings remain in
**Selected Profile settings and diagnostics**, separate from the common
workflow. They belong to the Profile/Skill, not hard-coded agent or worker logic.

## Current Verification

The 2026-09-13 package migration passed the guarded Equipment owner/module/bridge
selection (285 tests) and the focused frontend/API/control-view selections. The
checks observed zero physical calls and no denied effects. An unchanged second
registered-model attempt completed through the next Design with 34 actual calls;
the first stopped on a later Knowledge tool-contract rejection before BO. This
records one guarded virtual success plus the observed stochastic failure and
says nothing about physical bridge readiness. No worker pairing,
update, restart, desktop input or instrument action was performed. The earlier
physical proof remains linked from the Equipment Reference and is not replaced
or expanded by this migration.

The [2026-09-28 campaign archive audit](../paper/evidence/2026-09-28-campaign-archive-audit.md)
adds recorded multi-cycle Equipment/Analysis evidence. It is not a new worker
pairing test, complete hardware certification or a change to the migration result.

## Limitations and Known Gaps

Interactive desktop/session availability and actual instrument state remain
installation-specific. No physical action was performed by this documentation
audit. A successful program receipt is not by itself experiment completion.

## Related Documents

- [Equipment Agent](../agents/equipment_agent.md)
- [Windows setup](../hardware/windows_pyautogui_bridge_windows_setup.md)
- [Worker README](../../Pyautogui_server_for_window/README.md)
