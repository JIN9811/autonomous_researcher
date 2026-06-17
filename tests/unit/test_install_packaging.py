"""Packaging smoke tests for fresh-install helper files."""

from __future__ import annotations

import json
from pathlib import Path
import os
import subprocess
import sys


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
