"""
File purpose:
- Load and merge YAML configuration files used by the framework.

Key classes/functions:
- load_yaml
- load_all_configs

Inputs/outputs:
- Input: YAML file paths
- Output: dictionary-based configuration bundle

Dependencies:
- pathlib.Path
- yaml.safe_load

Modification guide:
- Safe places to edit: new config files and default-merging behavior
- Risky places to edit: return schema consumed across modules
- Related files: app/bootstrap.py, configs/*.yaml
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML file and return an empty dict if the file is empty."""
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML root must be an object: {path}")
    return loaded


def load_all_configs(config_dir: Path) -> dict[str, Any]:
    """Load all first-level YAML files from config_dir into one dictionary."""
    merged: dict[str, Any] = {}
    for path in sorted(config_dir.glob("*.yaml")):
        merged[path.stem] = load_yaml(path)
    return merged
