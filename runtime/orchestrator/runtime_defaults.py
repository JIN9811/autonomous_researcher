"""Shared runtime settings that must stay consistent across control layers."""

from pathlib import Path

import yaml


def _configured_test_mode_loop_cycles() -> int:
    """Load the test-loop budget from the operator-editable mode config."""
    config_path = Path(__file__).resolve().parents[1] / "configs" / "test_modes.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    test_modes = raw.get("test_modes") if isinstance(raw.get("test_modes"), dict) else {}
    dry_run = test_modes.get("dry_run") if isinstance(test_modes.get("dry_run"), dict) else {}
    value = int(dry_run.get("max_cycles") or 0)
    if value < 1:
        raise RuntimeError(f"Invalid test_modes.dry_run.max_cycles in {config_path}")
    return value


TEST_MODE_LOOP_CYCLES = _configured_test_mode_loop_cycles()
