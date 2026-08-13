"""Packaging smoke tests for fresh-install helper files."""

from __future__ import annotations

import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def test_doctor_core_only_json_runs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/doctor.py", "--core-only", "--json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    names = {item["name"] for item in payload["results"]}
    assert "core files" in names
    assert "python imports" in names
    assert "secret ignore policy" in names


def test_fresh_install_helpers_are_packaged_and_executable() -> None:
    executable_files = [
        ROOT / "install" / "bootstrap_linux.sh",
        ROOT / "install" / "install_cli.sh",
        ROOT / "install" / "apply_lerobot_d405_patch.sh",
        ROOT / "install" / "bambustudio" / "bambu-studio-wrapper",
        ROOT / "scripts" / "doctor.py",
    ]
    for path in executable_files:
        assert path.exists(), path
        assert os.access(path, os.X_OK), path

    assert (ROOT / "install" / "bootstrap_windows.ps1").exists()
    assert (ROOT / "patches" / "lerobot" / "spark_realsense_d405_rsusb.patch").exists()
    assert (ROOT / "patches" / "lerobot" / "README.md").exists()


def test_lerobot_patch_contains_expected_realsense_files() -> None:
    patch = (ROOT / "patches" / "lerobot" / "spark_realsense_d405_rsusb.patch").read_text(encoding="utf-8")
    assert "src/lerobot/cameras/realsense/camera_realsense.py" in patch
    assert "src/lerobot/cameras/realsense/configuration_realsense.py" in patch
    assert "tests/cameras/test_realsense.py" in patch


def test_windows_bridge_release_contains_reproducible_installer_and_runtime_dependencies() -> None:
    package = ROOT / "Pyautogui_server_for_window"
    requirements = (package / "requirements-windows.txt").read_text(encoding="utf-8").lower()

    for dependency in ("pyautogui", "pillow", "opencv-python", "pynput", "pywinauto", "pytesseract"):
        assert dependency in requirements
    for relative in (
        "scripts/install_bridge.ps1",
        "scripts/uninstall_bridge.ps1",
        "scripts/build_release.ps1",
        "scripts/native_acceptance.ps1",
    ):
        assert (package / relative).is_file(), relative


def test_windows_bridge_scripts_use_one_data_root_and_bundle_demo_assets() -> None:
    package = ROOT / "Pyautogui_server_for_window"
    run_script = (package / "scripts" / "run_bridge.ps1").read_text(encoding="utf-8")
    build_exe = (package / "scripts" / "build_exe.ps1").read_text(encoding="utf-8")
    env_example = (package / "examples" / "windows_bridge.env.example.ps1").read_text(encoding="utf-8")

    assert "WINDOWS_PYAUTOGUI_DATA_ROOT" in run_script
    for argument in ("--artifact-dir", "--reference-dir", "--utm-export-dir", "--program-dir", "--recording-dir", "--demo-dir"):
        assert argument in run_script
    assert "--add-data" in build_exe
    assert "demo" in build_exe
    assert "WINDOWS_PYAUTOGUI_BRIDGE_ARTIFACT_ROOT" in env_example
    assert "WINDOWS_PYAUTOGUI_LOCATOR_ROOT" in env_example
    assert "WINDOWS_PYAUTOGUI_ARTIFACT_DIR" not in env_example
    assert "WINDOWS_PYAUTOGUI_REFERENCE_DIR" not in env_example


def test_windows_bridge_install_lifecycle_is_interactive_secure_and_clean() -> None:
    scripts = ROOT / "Pyautogui_server_for_window" / "scripts"
    installer = (scripts / "install_bridge.ps1").read_text(encoding="utf-8")
    uninstaller = (scripts / "uninstall_bridge.ps1").read_text(encoding="utf-8")
    release_builder = (scripts / "build_release.ps1").read_text(encoding="utf-8")
    firewall = (scripts / "firewall_allow_private.ps1").read_text(encoding="utf-8")
    checker = (scripts / "check_bridge.ps1").read_text(encoding="utf-8")

    assert "New-ScheduledTaskPrincipal" in installer
    assert "-LogonType Interactive" in installer
    assert "stop_bridge.ps1" in uninstaller
    assert "__pycache__" in release_builder
    assert "*.pyc" in release_builder
    assert "-RemoteAddress" in firewall
    assert "explicitly opt in" in firewall
    assert 'Write-Host "Using token: $Token"' not in checker


def test_windows_bridge_has_self_locating_click_install_start_and_uninstall_launchers() -> None:
    package = ROOT / "Pyautogui_server_for_window"
    launchers = {
        "INSTALL_WINDOWS_BRIDGE.cmd": "install_bridge.ps1",
        "START_WINDOWS_BRIDGE.cmd": "run_bridge.ps1",
        "UNINSTALL_WINDOWS_BRIDGE.cmd": "uninstall_bridge.ps1",
    }

    for filename, target_script in launchers.items():
        content = (package / filename).read_text(encoding="utf-8")
        assert "%~dp0" in content
        assert target_script in content
        assert "if errorlevel 1" in content.lower()
        assert "pause" in content.lower()

    install_launcher = (package / "INSTALL_WINDOWS_BRIDGE.cmd").read_text(encoding="utf-8")
    assert "start" in install_launcher.lower()
    assert "-OpenBrowser" in install_launcher
    assert "-ShowToken" in install_launcher


def test_windows_bridge_installer_creates_shortcuts_and_release_includes_launchers() -> None:
    scripts = ROOT / "Pyautogui_server_for_window" / "scripts"
    installer = (scripts / "install_bridge.ps1").read_text(encoding="utf-8")
    release_builder = (scripts / "build_release.ps1").read_text(encoding="utf-8")

    assert "WScript.Shell" in installer
    assert 'GetFolderPath("Desktop")' in installer
    assert "Start Menu" in installer
    assert "START_WINDOWS_BRIDGE.cmd" in installer
    assert "UNINSTALL_WINDOWS_BRIDGE.cmd" in installer
    for launcher in ("INSTALL_WINDOWS_BRIDGE.cmd", "START_WINDOWS_BRIDGE.cmd", "UNINSTALL_WINDOWS_BRIDGE.cmd"):
        assert launcher in release_builder


def test_basic_ci_has_windows_bridge_job() -> None:
    workflow = (ROOT / ".github" / "workflows" / "basic-tests.yml").read_text(encoding="utf-8")

    assert "windows-latest" in workflow
    assert "windows-bridge" in workflow
    assert "native_acceptance.ps1" in workflow


def test_windows_bridge_portable_release_has_one_click_offline_contract() -> None:
    package = ROOT / "Pyautogui_server_for_window"
    launcher = (package / "portable" / "START_EQUIPMENT_BRIDGE.cmd").read_text(encoding="utf-8")
    bootstrap = (package / "portable" / "bootstrap_portable.ps1").read_text(encoding="utf-8")
    runtime_requirements = (package / "requirements-portable.txt").read_text(encoding="utf-8").lower()

    assert "%~dp0" in launcher
    assert "bootstrap_portable.ps1" in launcher
    assert "scripts\\run_bridge.ps1" in bootstrap
    assert "-DataRoot" in bootstrap
    assert "data" in bootstrap.lower()
    assert "-OpenBrowser" in bootstrap

    assert "runtime\\python" in bootstrap
    assert '"python.exe"' in bootstrap
    assert 'Join-Path $vendorRoot "python' in bootstrap
    assert 'Join-Path $vendorRoot "wheelhouse"' in bootstrap
    assert "--no-index" in bootstrap
    assert "--find-links" in bootstrap
    assert "requirements-portable.txt" in bootstrap
    assert "Start-Process" in bootstrap
    assert "RunAs" not in bootstrap

    assert "pyinstaller" not in runtime_requirements
    for dependency in ("pyautogui", "pillow", "opencv-python", "pynput", "pywinauto", "pytesseract"):
        assert dependency in runtime_requirements


def test_windows_bridge_portable_builder_emits_clean_single_folder_manifest() -> None:
    package = ROOT / "Pyautogui_server_for_window"
    builder_path = package / "scripts" / "build_portable_release.py"
    assert builder_path.is_file()

    with tempfile.TemporaryDirectory(prefix="atr_portable_release_contract_") as tmp:
        output_root = Path(tmp) / "release"
        result = subprocess.run(
            [
                sys.executable,
                str(builder_path),
                "--output",
                str(output_root),
                "--source-only",
            ],
            cwd=package,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        manifest = json.loads((output_root / "portable_manifest.json").read_text(encoding="utf-8"))

        assert manifest["schema"] == "atr.windows_equipment_bridge.portable.v1"
        assert manifest["offline_ready"] is False
        assert manifest["data_root"] == "data"
        for relative in (
            "START_EQUIPMENT_BRIDGE.cmd",
            "STOP_EQUIPMENT_BRIDGE.cmd",
            "bootstrap_portable.ps1",
            "bridge/windows_pyautogui_bridge_server.py",
            "scripts/run_bridge.ps1",
            "requirements-portable.txt",
            "PORTABLE_README_KO.txt",
        ):
            assert (output_root / relative).is_file(), relative

        env_example = (output_root / "examples" / "windows_bridge.env.example.ps1").read_text(encoding="utf-8")
        assert "WINDOWS_PYAUTOGUI_ATR_API_URL" in env_example
        assert "optional" in env_example.lower()
        packaged_server = (output_root / "bridge" / "windows_pyautogui_bridge_server.py").read_text(encoding="utf-8")
        assert "atr.windows_controller_connection.v1" in packaged_server
        assert "ATR_CONTROLLER_MULTIPLE_CANDIDATES" in packaged_server

        forbidden_names = {".bridge_token", "bridge_requests.jsonl", "controller_connection.json", "__pycache__"}
        assert not any(path.name in forbidden_names for path in output_root.rglob("*"))
