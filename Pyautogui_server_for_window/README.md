# Windows PyAutoGUI Bridge

Windows PyAutoGUI Bridge is the executor used by Linux ATR's `LabEquipmentAgent` to control equipment through Windows GUIs. Windows only executes validated programs, collects screen evidence, records input, and manages local programs; it does not make decisions or determine experiment completion.

## Responsibility boundaries

| Layer | Responsibilities |
|---|---|
| Linux ATR | Equipment Profile/Skill selection, execution IDs, evidence validation, recovery decisions, Analysis handoff |
| Equipment Runtime Service | Execution contracts, Worker selection, execution records, completion decisions, per-screen state projections |
| Windows Bridge | PyAutoGUI execution, screenshots, locators, program cache, recording, raw results |
| Browser | Displays server state; it is not the source of truth and reloads state from the server on refresh |

UTM is the first Equipment Profile, not a limitation of the Windows Bridge. Equipment-specific window names, button locators, and save procedures belong in Linux Profiles/Skills and deployed programs.

## Recommended installation

### Copy-and-run portable package

1. Copy the entire built portable package folder to the Windows PC.
2. Run `START_EQUIPMENT_BRIDGE.cmd`.
3. On first launch, it prepares the folder-local Python runtime and offline wheels, then opens the browser.
4. Find the temporary four-digit code in the Windows Console.
5. In Linux ATR, open Device Workspace > Lab Equipment > Windows Bridge, run Scan, and select the device.
6. Enter the four-digit code and choose Pair & Save.

Portable data is stored under the package's `data\` directory. The runtime is designed to install without administrator privileges. Use a built offline-ready release, not the source-only folder: the portable release builder assembles the launcher and bundled runtime assets.

### Standard installation

On Windows with Python 3.11 available through `py -3.11`, run:

```text
INSTALL_WINDOWS_BRIDGE.cmd
```

The installer uses the current package folder containing `INSTALL_WINDOWS_BRIDGE.cmd`:

```text
<copied-package-folder>\Pyautogui_server_for_window
```

After installation, use the Desktop or Start Menu shortcut. To select another interpreter explicitly, invoke `scripts\install_bridge.ps1 -PythonLauncher <path-to-python.exe>`.

Installation and updates use the current package folder.

- The installer creates `.venv` inside the package folder without copying the program elsewhere.
- Shortcuts launch `START_WINDOWS_BRIDGE.cmd`, which invokes `scripts\start_supervisor.ps1` in the same folder; the logon task invokes that script directly.
- The remote updater applies releases only to the running package folder and restarts it.
- Logs, recordings, programs, and artifacts are stored separately under `%LOCALAPPDATA%\ATR\PyAutoGUIBridge`.

Normal startup uses `scripts\start_supervisor.ps1`. Startup commands and scheduled tasks contain no release number; the supervisor monitors the Worker in the current package folder and restarts it after an unexpected exit. `release_manifest.json` is the single source for the current version and remote-update file list. Installation registers an interactive-user logon task by default; it does not use a Windows service.

### Development startup

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_bridge.ps1 -OpenBrowser
```

Use `-LocalOnly` for a development session that must be accessible only from the local PC.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_bridge.ps1 -LocalOnly -OpenBrowser
```

The default local address is `http://127.0.0.1:8765/`.

## Four-digit pairing

Users do not enter or copy a long-lived authentication key.

- The code has four digits and is valid for five minutes.
- Up to five attempts are allowed.
- Success consumes the code. For 30 seconds, retrying the same exchange returns the existing key (`paired_retry`); it does not create another pairing. After that window, the code cannot be reused.
- Five failures trigger a 30-second lockout.
- After success, both sides store the internal long-lived key in protected configuration files.
- Codes and internal keys are not written to URLs, browser storage, or request audits.
- Subsequent restarts use the saved key and reconnect without another prompt.

The four-digit code is only for the initial key exchange. Subsequent authentication uses the saved worker secret or exchanged internal key.

- Recording start, status, preview, stop, save, and delete are available regardless of pairing state.
- Recording package transfer, remote execution, and updates require saved connection authentication.

## Windows Console

The main screen has four sections.

### Bridge Status

Shows server, PyAutoGUI, data path, and pairing state. Controls are `Health`, `Refresh`, `New Code`, and `Reset Pairing`. Use Reset Pairing only to clear an existing or half-completed pairing and issue a fresh code; Linux must then pair again.

### Program Manager

- `program1`: the built-in demo; it cannot be deleted
- Add: create a local program in an empty editor
- Browse JSON: load an existing program JSON file
- Template: download a program template
- Validate: validate the execution contract
- Save: save a local draft
- Test: execute the selected local program
- Delete: remove a deletable local draft

Programs deployed by ATR are read-only cache entries and are not edited directly on Windows.

### Recording

`START RECORDING` starts input recording after five seconds. A topmost overlay shows elapsed time and the sole operator stop control, `STOP`. The Bounded Evidence card shows recording state and Checkpoint, without another Stop button. Overlay `STOP` closes the UI immediately and calls `RecordingManager.stop()` once in the background. The Console polls `/recordings/status` only while recording is active, automatically returning to idle and refreshing the list after the overlay closes. The STOP click remains in the raw timeline as provenance evidence, marked `recording_control=overlay_stop`; Linux Skill compilation and capability counts exclude it from equipment actions.

- Keyboard and mouse input use monotonic timestamps.
- Full-screen frames are written immediately to disk at a default 2 FPS throughout recording.
- Periodic frames use `frames/periodic/frame-XXXXXXXX.jpg`; event and boundary frames use PNG. `timeline.jsonl` links them chronologically.
- RAM holds only a bounded cache of recent frames for pre-action evidence; disk, not a RAM ring buffer, owns the full session evidence.
- At the disk warning threshold, recording continues with a status warning. At the critical threshold or on a write failure, it stops safely and preserves existing evidence as an incomplete package.
- Supports overlay Stop and Console Checkpoint, Preview, Export, and Delete. Preview pages backward and forward through saved frames without exposing Windows absolute paths to the browser.

Windows produces only the raw recording. Linux ATR arranges 16 frames into each 4x4 temporal storyboard, analyzes every chunk in order with the selected multimodal model, and synthesizes the complete workflow. Linux owns LLM annotation and Skill compilation, validation, versioning, and deployment. Individual replay actions in compiled Skills do not call the LLM again. However, the normal Linux Equipment Flow may include LLM decisions for pre-execution selection and terminal evidence review; the entire experiment path is not necessarily LLM-free.

### Latest Local Result

Shows recent Health, program validation/test, recording results, and failure codes. Raw result JSON is collapsed under `Raw JSON` in this section. The separate collapsed `Diagnostics` section loads Health JSON and the request log on demand.

## Saved Worker remote updates

Linux `Lab Equipment Workspace > Connection & Profile > Saved Worker` provides these per-Worker actions:

- `Check Update`: compare the current Worker version with the latest Linux package version.
- `Update`: stage only the bounded release manifest's files, then restart the Worker.
- `Rollback`: restore the most recent verified backup and restart the Worker.

Older Workers without remote-update support need a one-time manual installation or folder replacement with this package. Subsequent versions can be updated through Saved Worker.

Updates automatically use the worker secret saved during initial connection or the internal key exchanged through four-digit pairing. There is no separate public-key signature, but each file's SHA-256, the package digest, relative-path allowlist, and size limits are validated. Updates target one canonical installation directory and include the server, supervisor, updater, start/run launchers, installer, and `requirements-windows.txt`. During application, `updates\update_in_progress.json` prevents the supervisor from starting a duplicate Worker while files are replaced; existing files are preserved in `updates\backups`. If the new Worker's lightweight plain-text `/ping` does not return **the manifest's target release version** within 30 seconds, the updater restores the previous backup. If updater recovery itself fails, the independent supervisor restarts the canonical Worker once the lock clears. Script-based Python installations synchronize dependencies with the same interpreter only when `requirements-windows.txt` changes; frozen EXE distributions use bundled dependencies.

Updates do not replace:

- pairing/internal keys
- recordings, programs, locators, artifacts, or UTM exports
- per-user data roots or runtime evidence

Update and Rollback are blocked while a recording session is active. Stop/save the recording first, then retry.

## Data directories

Standard installation defaults:

```text
%LOCALAPPDATA%\ATR\PyAutoGUIBridge
  artifacts\     Screenshots, request logs, execution results
  locators\      Reference images for locators
  programs\      Local drafts and ATR deployment cache
  recordings\    Recording manifests, events, keyframes
  utm_exports\   Result files used by the UTM Profile
```

The Skill source of truth is Linux `memory/equipment_skills/`. Windows `programs\` contains local drafts or validated deployment cache entries.

## Operational checks

On Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_bridge.ps1
```

`check_bridge.ps1` checks local Health and pairing state only. `test_bridge.ps1` also executes `program1` when paired. For a nondefault port, set `WINDOWS_PYAUTOGUI_BRIDGE_URL` before running the test script; it does not read the port variable directly.

In the Linux ATR Device Workspace:

1. Scan (discover candidates without a code).
2. Enter the four-digit code on the Candidate card and choose Pair & Save, or Select a saved device.
3. Health
4. Programs
5. Test selected bridge

The experiment loop uses `LabEquipmentAgent -> EquipmentRuntimeService -> equipment.pyautogui.run`, not Windows Console buttons. It does not automatically switch to `utm.run_protocol`.

## Main APIs

| Method | Path | Purpose |
|---|---|---|
| GET | `/ping` | Lightweight plain-text liveness check for supervisor/updater; not audited |
| GET | `/discovery` | Minimal metadata for discovery before authentication |
| GET | `/health` | Bridge/PyAutoGUI/path status |
| GET | `/pairing/status` | Local pairing state |
| POST | `/pairing/new-code` | Issue a new four-digit code from local setup |
| POST | `/pairing/reset` | Clear pairing and issue a fresh code from local setup |
| POST | `/pairing/complete` | Exchange the one-time code from Linux |
| GET | `/programs` | List programs |
| POST | `/programs/validate` | Validate a program |
| POST | `/programs/register` | Register a local/deployed program |
| DELETE | `/programs/{id}` | Remove a deletable local program |
| POST | `/execute` | Execute a validated program |
| POST | `/screenshot` | Capture screen evidence |
| POST | `/locators/capture` | Save a locator reference image |
| GET/POST/DELETE | `/recordings/...` | Manage recording lifecycle and artifacts |
| GET | `/recordings/{id}/package` | Transfer an authenticated recording evidence package |
| GET | `/artifacts` | List raw artifacts |
| GET | `/request-log` | Request audit log |
| GET | `/update/status` | Current, staged, and rollback version status |
| POST | `/update/stage` | Stage a release after allowlist and SHA-256 validation |
| POST | `/update/apply` | Replace, restart, and verify liveness/version through a separate updater |
| POST | `/update/rollback` | Restore the latest backup and restart |

Remote execution, screenshot, and artifact routes require the exchanged internal key or configured worker secret. Recording lifecycle/preview routes are pairing-optional; package transfer is authenticated. Restrict network access with the firewall even before pairing.

## Safety boundaries

- Keep `pyautogui.FAILSAFE` enabled.
- Programs must contain only allowed, bounded actions.
- Do not put passwords, API keys, pairing codes, or internal keys in program payloads.
- Windows Bridge does not perform Guardian decisions, LLM recovery, experiment-stage transitions, or Analysis handoff.
- Physical equipment validation follows the Profile's separate approval procedure.

See [docs/USAGE.md](docs/USAGE.md) for detailed procedures.
