# Windows PyAutoGUI Bridge Standalone Deployment Plan

1. Add failing tests for dependency readiness, recorder fail-closed behavior, canonical environment variables, complete data-root wiring, bundled demo assets, and Windows CI.
2. Add dependency/readiness reporting and make recording startup fail closed when pynput cannot create listeners.
3. Add a dedicated Windows dependency set and per-user venv installer with update, uninstall, token ACL, and optional interactive-logon startup.
4. Make source and EXE release builders include all runtime assets.
5. Add Windows CI and a native acceptance script that produces machine-readable evidence.
6. Update standalone setup, usage, installation, and requirement documentation.
7. Run focused tests, full bridge tests, source/install parity checks, and static PowerShell verification available on the Linux host.

## Click Installer Extension

### Task 1: Self-locating launchers

**Files:**
- Create: `Pyautogui_server_for_window/INSTALL_WINDOWS_BRIDGE.cmd`
- Create: `Pyautogui_server_for_window/START_WINDOWS_BRIDGE.cmd`
- Create: `Pyautogui_server_for_window/UNINSTALL_WINDOWS_BRIDGE.cmd`
- Test: `tests/unit/test_install_packaging.py`

- [ ] Add a failing packaging test requiring `%~dp0`, visible failure handling,
      installed-path startup, and all three click launchers.
- [ ] Run the focused test and confirm it fails because the launchers are absent.
- [ ] Add the three self-locating command launchers without changing bridge API behavior.
- [ ] Run the focused test and confirm it passes.

### Task 2: Installed shortcuts and release contents

**Files:**
- Modify: `Pyautogui_server_for_window/scripts/install_bridge.ps1`
- Modify: `Pyautogui_server_for_window/scripts/build_release.ps1`
- Modify: `Pyautogui_server_for_window/README.md`
- Modify: `Pyautogui_server_for_window/docs/USAGE.md`
- Test: `tests/unit/test_install_packaging.py`

- [ ] Add a failing test requiring Desktop and Start Menu shortcut creation and
      inclusion of root click launchers in the ZIP release.
- [ ] Implement per-user shortcuts targeting the installed package.
- [ ] Include the launchers in release ZIP staging and document double-click use.
- [ ] Run packaging tests, bridge regression tests, compile/parity checks, and diff checks.
