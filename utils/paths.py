"""
File purpose:
- Resolve project-relative paths in a consistent way for runtime modules.

Key classes/functions:
- project_root
- resolve_path

Inputs/outputs:
- Input: optional relative path and root override
- Output: absolute resolved Path object

Dependencies:
- pathlib.Path

Modification guide:
- Safe places to edit: root detection and default conventions
- Risky places to edit: assumptions used in app bootstrap
- Related files: app/bootstrap.py, knowledge/rag.py
"""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Return repository root based on this file location."""
    return Path(__file__).resolve().parent.parent


def resolve_path(path: str | Path) -> Path:
    """Resolve path relative to project root when not absolute."""
    p = Path(path)
    if p.is_absolute():
        return p
    return (project_root() / p).resolve()
