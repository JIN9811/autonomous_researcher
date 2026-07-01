"""Browser-level smoke checks for the LeRobot synthetic GUI panel."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_lerobot_gui_synthetic_browser_smoke_renders_mocked_section_7() -> None:
    script = Path("scripts/lerobot_gui_synthetic_browser_smoke.sh")

    result = subprocess.run(
        ["bash", str(script)],
        check=False,
        cwd=Path.cwd(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=90,
    )

    assert result.returncode == 0, result.stdout
    assert "SYNTHETIC_BROWSER_SMOKE_OK" in result.stdout
