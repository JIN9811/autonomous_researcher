# Windows PyAutoGUI Bridge Standalone Deployment Design

## Scope

Package only `Pyautogui_server_for_window` as a reproducible Windows desktop bridge. The ATR Linux runtime, equipment-agent protocol, program schema, and Skill runtime contracts remain unchanged.

## Deployment Contract

- Install into a dedicated per-user directory and Python virtual environment.
- Keep mutable state below one data root: artifacts, locators, UTM exports, programs, recordings, and the bridge token.
- Refuse to report recording startup success when global input listeners are unavailable.
- Report runtime dependency readiness through `/health` without making optional OCR or UI Automation packages mandatory for basic macro execution.
- Include the demo UI and JSON examples in both ZIP and PyInstaller EXE releases.
- Start at interactive user logon through an optional Scheduled Task; never run desktop automation as a Windows service.
- Restrict firewall access to an explicitly supplied controller address or private subnet.
- Never print the token during routine health checks. Protect the token file with a user-only ACL where Windows supports it.
- Validate source, install-copy, PowerShell syntax, bridge API, asset packaging, and Windows-native acceptance separately.

## Readiness Levels

- `core_ready`: PyAutoGUI, Pillow, OpenCV, and pynput are available and demo assets are present.
- `desktop_ready`: core readiness plus a controllable interactive desktop.
- Optional capabilities: pywinauto window automation and pytesseract OCR.

The bridge may remain reachable in `degraded` state so setup diagnostics can be read. Recording requests fail closed with a stable failure code when pynput is missing.

## Release Forms

1. Source ZIP: preferred for development and auditability. Installs a dedicated `.venv`.
2. One-file EXE: convenience release with demo assets bundled through PyInstaller data collection.

Both forms use the same HTTP API and per-user data layout.

## Click Installation

The source ZIP exposes `INSTALL_WINDOWS_BRIDGE.cmd` at its root. A user may
double-click it from any extracted location; the launcher resolves its own
directory through `%~dp0`, invokes `scripts/install_bridge.ps1`, and starts the
installed bridge in a separate PowerShell window with the browser open. The
launcher pauses on failure so the error remains visible.

Installation creates per-user desktop and Start Menu shortcuts for starting
and uninstalling the bridge. The shortcuts target the installed package, not
the extraction directory. No administrator elevation is required unless the
operator separately chooses to create a firewall rule.

## Native Acceptance

Linux/Xvfb tests prove protocol and deterministic UI behavior only. A release is Windows-accepted only after `native_acceptance.ps1` records health, dependencies, screen metadata, demo assets, and an explicitly approved bounded Program 1 execution on a real interactive Windows session.
