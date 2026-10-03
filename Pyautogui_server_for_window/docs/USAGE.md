# Windows PyAutoGUI Bridge: Detailed Usage

## 1. Choose an installation method

### Portable

Run `START_EQUIPMENT_BRIDGE.cmd` from the built offline-ready release folder. On first launch, the bundled Python installer and wheelhouse prepare a folder-local runtime without changing system Python or the global PATH. The source-only package is not an offline-ready release.

### Standard installation

```text
INSTALL_WINDOWS_BRIDGE.cmd
```

The default installer requires Python 3.11 through `py -3.11`; pass `-PythonLauncher <path-to-python.exe>` to `scripts\install_bridge.ps1` to choose an interpreter explicitly. It creates `.venv` and shortcuts in the current package folder without copying the program elsewhere. The START launcher, supervisor, and remote updater all use that folder; logs, recordings, and artifacts use `%LOCALAPPDATA%\ATR\PyAutoGUIBridge`.

The START launcher and logon scheduled task invoke the current folder's `scripts\start_supervisor.ps1`, without a release number. The supervisor checks the Worker every five seconds through lightweight plain-text `/ping`; these requests do not accumulate in the UI or audit log. The version comes from `release_manifest.json`, not source code or startup commands. The supervisor does not repeatedly call the candidate-discovery endpoint `/discovery`. For compatibility with supervisors already running with older arguments, localhost `/discovery` requests return minimal version-check JSON without audit entries. During updates, the data root's `updates\update_in_progress.json` lock prevents duplicate startup.

### Source development

```powershell
cd <package-root>
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_bridge.ps1 -OpenBrowser
```

To change the port, set the environment variable before startup.

```powershell
$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8765"
```

## 2. Initial pairing

1. Find the four-digit code in Bridge Status in the Windows Console.
2. Open Device Workspace in the Linux ATR Main GUI.
3. Run the network Scan in Lab Equipment Workspace > Windows Bridge.
4. Select a discovered candidate and enter the four-digit code.
5. Click `Pair & Save`.
6. Specify a device alias to save.
7. Check Health for paired status and desktop readiness.

If the code expires, click `New Code` in the Windows Console. After five failed attempts, wait 30 seconds and issue a new code. A successful code is consumed; an identical exchange can be retried for 30 seconds to retrieve the same key (`paired_retry`). This does not create a second pairing. If Linux failed to save the connection and that retry window has expired, use `Reset Pairing` in the Windows Console and pair again.

Users do not need to view the internal key. Windows stores it in the active data root's `artifacts\pairing.json`; Linux stores it in protected fields in the Windows Bridge connection memory. Neither file belongs in Git.

## 3. Reconnect

Paired devices appear in the ATR Workspace's saved devices.

1. Select the device.
2. Health
3. Programs or Test selected bridge

If the IP changes, use Scan to rediscover the same Bridge and update the saved settings. A new code is not required while the internal key remains valid.

## 4. Program Manager

### Run the built-in demo

`program1` is built in for installation verification. It cannot be deleted or overwritten.

### Create a program

1. Add
2. Enter the program ID, name, target window, and actions in the JSON editor.
3. Validate
4. Save
5. Test

### Load a JSON file

1. Browse JSON
2. Select the file.
3. Validate
4. Save

Browse reads a file; Add creates a new draft.

### Template

The Template button downloads a JSON example in the supported program format. Edit the template and load it again with Browse JSON.

### Program ownership

- `builtin`: included with the Bridge, read-only
- `local_draft`: authored on Windows, for local testing only
- `deployed`: validated and hash-checked by Linux ATR before deployment, read-only
- `retired`: preserved for audit, unavailable for new execution

These are lifecycle categories; the Windows catalog labels ATR-managed entries `atr_skill`. The experiment loop executes only builtin/deployed programs allowed by the Linux catalog.

## 5. Recording

### Start recording

1. Enter Name, Target Program, and Target Window.
2. Choose whether to enable Image tracking; Coordinate fallback is a separate option.
3. START RECORDING
4. Switch to the target window during the five-second countdown.
5. Perform the workflow once the topmost `REC` overlay appears.
6. Use Checkpoint where needed.
7. Click `STOP` on the topmost recording overlay.
   - The overlay button is the sole operator stop control.
   - Bounded Evidence does not display another Stop button.
   - The button performs finalization in the background without blocking the UI thread; the Console automatically synchronizes to idle.

### Stored data

Each recording folder may contain:

- `recording.json`: version, target, state, and timeline information
- `events.jsonl`: keyboard/mouse events and monotonic timestamps
- `frames/periodic/`: original 2 FPS JPEG frames covering the recording
- `timeline.jsonl`: append-only chronological index of periodic/event/boundary frames
- `keyframes/`, `timeline/event_keyframes/`: PNG evidence at events/checkpoints
- locator/checkpoint metadata

Periodic frames are written immediately to disk throughout recording, at a default 2 FPS.

- Memory holds only a recent-frame cache for identifying pre-action evidence.
- Normal recordings have no arbitrary duration or total-frame cap.
- At a critical disk condition, recording stops while preserving saved data as a partial package with `evidence_complete=false`.

### After recording

Use Preview to move backward and forward through saved frames. The Linux Lab Equipment Workspace queries the selected Worker's Recording list directly; selecting an entry fills in the Recording ID and Worker ID. `Import & Build Draft` then fetches the authenticated package. Linux performs:

```text
transfer -> annotate -> build skill -> validate -> approve -> deploy
```

Linux transfers the package through authenticated `/recordings/{id}/package` and checks every file's size and SHA-256. Only verified files are written to the Linux artifact root.

The selected Local/API LLM runs only on Linux. Windows needs neither an LLM nor an API key.

When recording stops, the overlay is hidden and the final screen is added to the timeline evidence. Linux builds a 4x4 storyboard for every 16 frames, analyzes all chunks in order with the selected multimodal backend, then synthesizes the chunk results and session overview once.

- Completed chunk analyses are persisted to disk.
- Stop requests are handled at chunk boundaries.
- The Windows Worker neither performs this interpretation nor independently changes the meaning of stored Skills.

## 6. Linux Equipment Runtime integration

Experiment-loop execution path:

```text
LabEquipmentAgent
  -> EquipmentRuntimeService
  -> selected Equipment Profile / Skill
  -> Windows bridge /execute
  -> raw evidence collection
  -> one completion interpretation
  -> required post-test clearance / evidence gates (or explicit block)
  -> Analysis handoff only after those gates pass
```

All screens read the record for the same `execution_id`. Displayed states depend on the Profile, Skill, and provider contract; one fixed state sequence is not imposed on every device.

The Windows Worker does not decide:

- which Agent runs next
- Guardian approval
- experiment completion
- LLM recovery strategy
- Analysis handoff

## 7. Vision Link

Vision Link is optional and enabled by the Equipment Profile.

- Disabled: use screen locators, execution results, and file evidence only.
- Enabled: Linux Equipment Runtime requests observations from the Vision Agent Bridge.
- Existing Vision evidence may be reused if it is fresh and its identity matches.
- If neither evidence nor a Vision tool is available, block explicitly before execution.
- The Vision Agent returns observations only; it does not directly control Windows input.

## 8. Diagnostics

Expand Diagnostics below the main Console only when needed.

### Check local status

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_bridge.ps1
```

### Verify execution after pairing

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_bridge.ps1
```

For a nondefault port, set `WINDOWS_PYAUTOGUI_BRIDGE_URL` to the local Bridge URL before this test; the test script otherwise uses `http://127.0.0.1:8765`, regardless of the port variable.

### Checks

- server bind host/port
- PyAutoGUI import and failsafe
- data-root write access
- pairing status
- program catalog
- recording manager
- request audit

## 9. Firewall

Restrict access to the single Linux ATR machine on the private network. Run the firewall script from an elevated PowerShell session.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\firewall_allow_private.ps1 -RemoteAddress <linux-private-ip>
```

Use whole-subnet access only when an administrator explicitly chooses `-AllowPrivateSubnet`. The rule applies to the Windows Private network profile; pass `-Port` if the Bridge does not use 8765. Recording lifecycle and preview routes are pairing-optional, so pairing does not replace network access control.

## 10. Troubleshooting

### Bridge not discovered

- Check that the server is running on Windows.
- Check binding to `0.0.0.0:8765` (or your configured host/port).
- Check the Windows Firewall inbound rule.
- Check that Linux and Windows share a reachable private-network path.

### Pairing code invalid/expired

- Check that the code has four digits.
- Click New Code in the Windows Console.
- Wait 30 seconds after five failed attempts.

### PyAutoGUI unavailable

- Check for an interactive Windows desktop session.
- Check whether the screen is locked or the RDP session has ended.
- Check dependency installation.

```powershell
.\.venv\Scripts\python.exe -m pip check
```

For a portable release, use `.\runtime\python\python.exe -m pip check` instead.

### Program validation failed

Read the failure code in Latest Local Result. Correct unsupported actions, missing target windows, locator paths, or timeouts, then Validate again.

### Recording failed

- Check installation of `pynput`, Pillow, and PyAutoGUI.
- Activate the target desktop session.
- Stop any existing recording session.
- Check write access to `recordings\`.

## 11. Release verification

Before creating a release:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -InstallBuildDeps
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\native_acceptance.ps1
```

Native acceptance requires an already-running interactive Windows Bridge. By default it checks readiness without executing `program1`; `-RunProgram1` requests that additional demo. Current limitation: on a paired Bridge, the script also requests `/examples` without an authentication header, but that endpoint requires authentication. A resulting 401 is a script/authentication mismatch, not proof of hardware failure; do not count that run as accepted or weaken Bridge authentication to bypass it.

Packaging, unit, and integration tests in the Linux repository cover:

- source/install server parity
- absence of long-token entry UI/instructions
- four-digit pairing rules
- the Console's four main sections
- recording deletion and bounded in-memory frame buffering
- generic Profiles and Vision Link
- canonical Equipment Runtime projections

Automated verification does not run physical equipment. Perform that separately through the Profile's approved on-site procedure.
