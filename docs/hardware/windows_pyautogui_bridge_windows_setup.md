# Windows PyAutoGUI Bridge Installation and Operations Guide

The current reference documents are the [Windows Bridge README](../../Pyautogui_server_for_window/README.md) and
[Windows Bridge USAGE](../../Pyautogui_server_for_window/docs/USAGE.md). This guide summarizes installation from the ATR system perspective.

## Installation

The recommended distribution is the Windows x64 portable folder.

1. Copy the entire built offline-ready release folder to a local Windows disk.
2. Run `START_EQUIPMENT_BRIDGE.cmd`.
3. On first launch, wait for folder-local runtime setup to finish.
4. Check the browser Console.
5. In Linux ATR, use the four-digit code to Pair & Save.

For standard installation, copy the complete package to its permanent folder, then run
`INSTALL_WINDOWS_BRIDGE.cmd`. The default installer requires Python 3.11 through `py -3.11`;
it creates `.venv` there and registers supervisor startup through a logon task and shortcuts.
To choose an interpreter explicitly, run `scripts\install_bridge.ps1 -PythonLauncher <path-to-python.exe>`.

No separate installation is created under `%LOCALAPPDATA%\Programs`. The default data path is
`%LOCALAPPDATA%\ATR\PyAutoGUIBridge`. Because PyAutoGUI needs desktop access, run it in
a logged-in user's interactive session, not as a Windows service.

When migrating from an older release, copy the latest package once and run
`INSTALL_WINDOWS_BRIDGE.cmd`. Subsequent updates use `Check Update` and `Update` in Linux
`Lab Equipment Workspace > Saved Worker`. Remote updates apply the server, launchers, updater,
and changed Python dependencies to the same installation folder.

## Console layout

- Bridge Status
- Program Manager
- Recording
- Latest Local Result
- Collapsed Diagnostics

The Windows Console does not perform UTM proof, Skill compilation/deployment, Analysis handoff, or ATR Controller discovery.

## Four-digit pairing

Enter the one-time four-digit code from Bridge Status into the Linux ATR Equipment Workspace
during initial setup. Successful pairing stores the internal authentication key in protected files
on both sides. Server and GUI restarts automatically reuse it without code entry.
Existing worker secrets remain valid.

- Code lifetime: five minutes
- Attempt limit: five
- Lockout: 30 seconds
- Successful exchange: the same code can retrieve the same key for a 30-second retry window, then becomes unusable.

If Linux did not save the connection before that retry window expired, use Windows Console
`Reset Pairing` and pair again. Reset invalidates the previous paired key.

## Firewall

Restrict TCP 8765 to the Linux ATR machine's private IP. Run from an elevated PowerShell session.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\firewall_allow_private.ps1 -RemoteAddress <linux-private-ip>
```

The rule applies to the Windows Private network profile. For a different Bridge port, pass `-Port`.
Recording lifecycle/preview routes are pairing-optional, so restrict network access before pairing too.

## Installation checks

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_bridge.ps1
```

The first command checks local Health and pairing state; the second executes `program1` after pairing.
For a nondefault port, set `WINDOWS_PYAUTOGUI_BRIDGE_URL` before the test script; it otherwise uses port 8765.

## ATR connection

1. Device Workspace > Lab Equipment
2. Windows Bridge Scan (no code required)
3. Select a connection candidate.
4. Enter the four-digit code on the selected Candidate card.
5. Pair & Save to pair and save an alias.
6. Select > Health > Programs > Test

The experiment loop runs only through `LabEquipmentAgent -> EquipmentRuntimeService -> equipment.pyautogui.run`.

## Data and backups

Default data root for standard installations:

```text
%LOCALAPPDATA%\ATR\PyAutoGUIBridge
```

Portable releases use the package's `data\` folder. Before reinstalling, back up `programs`, `locators`, and `recordings` as needed, but do not clone `pairing.json` to another PC.

## Troubleshooting

- Discovery failure: check bind address, port, firewall, and private-network reachability.
- Pairing failure: issue a new code and check expiration/lockout.
- Desktop control failure: check screen lock, interactive session, DPI, and target window.
- Locator failure: recheck the current screenshot against the reference.
- Execution timeout: inspect the request log and actual equipment state before retrying; do not duplicate execution.

## Detailed documentation

- [Windows Bridge README](../../Pyautogui_server_for_window/README.md)
- [Windows Bridge USAGE](../../Pyautogui_server_for_window/docs/USAGE.md)
- [Windows PyAutoGUI Bridge contract](../device_bridges/windows_pyautogui_bridge.md)
- [Equipment Agent](../agents/equipment_agent.md)
