#!/usr/bin/env python3
"""Audit whether Improvement 05 has real UTM completion evidence.

This script is intentionally strict: it does not execute hardware and it does not
mark a run complete from intent, preflight, or a successful macro string. It
verifies a persisted Windows UTM proof package and returns exit code 0 only when
all required proof gates are satisfied.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
if LOCAL_VENV_PYTHON.exists() and Path(sys.executable) != LOCAL_VENV_PYTHON and os.environ.get("VIRTUAL_ENV") != str(REPO_ROOT / ".venv") and os.environ.get("ATR_NO_VENV_REEXEC") != "1":
    os.environ["ATR_NO_VENV_REEXEC"] = "1"
    os.execv(str(LOCAL_VENV_PYTHON), [str(LOCAL_VENV_PYTHON), *sys.argv])
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _latest_proof_package(root: Path) -> Path | None:
    candidates = sorted(
        root.glob("artifacts/equipment/*/utm/windows_utm_proof_package_*.json"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0.0,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _json_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def audit(path_value: str = "", *, latest: bool = False) -> dict[str, Any]:
    """Return a strict completion audit for a persisted UTM proof package."""
    from app.main import _load_windows_utm_proof_package_for_verify, _verify_windows_utm_proof_package

    selected_path = str(path_value or "").strip()
    latest_path: Path | None = None
    if not selected_path and latest:
        latest_path = _latest_proof_package(REPO_ROOT)
        selected_path = str(latest_path or "")

    package, load_info = _load_windows_utm_proof_package_for_verify(selected_path, use_current=False)
    verification = _verify_windows_utm_proof_package(package, load_info=load_info)
    ok = bool(verification.get("ok") and verification.get("status") == "verified")
    blockers = [str(item) for item in verification.get("blockers", []) if str(item or "").strip()] if isinstance(verification.get("blockers"), list) else []
    result = {
        "ok": ok,
        "tool": "equipment.pyautogui.improvement05_completion_audit",
        "status": "complete_evidence_verified" if ok else "incomplete",
        "objective": "05_lab_equipment_agent_utm_visual_control_data_loop",
        "proof_package_path": selected_path,
        "latest_search_used": bool(latest and latest_path is not None),
        "completion_rule": "Only status=verified from equipment.pyautogui.live_proof_package.verify can satisfy Improvement 05 physical UTM proof.",
        "blockers": blockers,
        "verification": verification,
    }
    if not selected_path:
        result["blockers"] = [*blockers, "PROOF_PACKAGE_PATH_REQUIRED"]
        result["status"] = "incomplete"
        result["ok"] = False
        result["next_actions"] = [
            "Run /equipment/windows -> Run Physical Validation with real UTM hardware.",
            "Build /api/equipment/windows/proof-package after validation.",
            "Re-run this script with --latest or --proof-package <path>.",
        ]
    elif not ok:
        result["next_actions"] = [
            "Resolve verification.blockers.",
            "Rebuild the proof package from the completed run.",
            "Do not mark Improvement 05 complete until this audit exits 0.",
        ]
    else:
        result["next_actions"] = ["Improvement 05 physical UTM evidence is verified for this proof package."]
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof-package", default="", help="Path to artifacts/equipment/<run_id>/utm/windows_utm_proof_package_*.json")
    parser.add_argument("--latest", action="store_true", help="Use the newest proof package under artifacts/equipment/*/utm/")
    parser.add_argument("--out", default="", help="Optional JSON output path for the audit result")
    parser.add_argument("--quiet", action="store_true", help="Print only PASS/FAIL summary instead of JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = audit(args.proof_package, latest=bool(args.latest))
    if args.out:
        out_path = Path(args.out).expanduser()
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_json_dump(result) + "\n", encoding="utf-8")
        result["audit_artifact"] = str(out_path)
    if args.quiet:
        blockers = result.get("blockers") if isinstance(result.get("blockers"), list) else []
        print("PASS" if result.get("ok") else "FAIL", result.get("status"), ",".join(str(item) for item in blockers[:5]))
    else:
        print(_json_dump(result))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
