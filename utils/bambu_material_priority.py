"""Saved AMS start-time preference; never changes a running printer's material."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import zipfile
from urllib.parse import urlparse, unquote

from pydantic import BaseModel, ConfigDict, Field, model_validator
from utils.paths import resolve_path


class MaterialPriority(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    slots: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def valid_order(self):
        if len(set(self.slots)) != len(self.slots) or any(not re.fullmatch(r"[0-3]:[0-3]", slot) for slot in self.slots):
            raise ValueError("Unique standard AMS slot IDs are required")
        if self.enabled and not self.slots:
            raise ValueError("Select at least one AMS slot")
        return self


def priority_path(repo_root=None) -> Path:
    return (Path(repo_root) if repo_root is not None else resolve_path(".")) / "memory/bambu_material_priority.json"


def load_priority(*, path=None) -> dict:
    target = Path(path) if path is not None else priority_path()
    if not target.exists():
        return MaterialPriority().model_dump()
    # A corrupt enabled policy must not quietly become an external-spool print.
    return MaterialPriority.model_validate(json.loads(target.read_text(encoding="utf-8"))).model_dump()


def save_priority(value, *, path=None) -> dict:
    policy = MaterialPriority.model_validate(value).model_dump()
    target = Path(path) if path is not None else priority_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, prefix=".ams-priority-", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(policy, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return policy


def select_material(policy, report, material) -> dict:
    policy = MaterialPriority.model_validate(policy).model_dump()
    if not policy["enabled"]:
        return {"ok": True, "enabled": False}
    base = {"ok": False, "enabled": True, "required_material": str(material).strip().upper(), "skipped": []}
    try:
        received = datetime.fromisoformat(str(report.get("received_at", "")).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - received).total_seconds()
        if not -5 <= age <= 30:
            raise ValueError("stale telemetry")
        materials = report.get("materials") or {}
        raw_bits = materials["tray_exist_bits"]
        bits = int(raw_bits, 16) if isinstance(raw_bits, str) else int(raw_bits)
        if bits < 0:
            raise ValueError("invalid presence bits")
    except (ValueError, TypeError, KeyError, OverflowError):
        return {**base, "failure_code": "BAMBU_MATERIAL_TELEMETRY_REQUIRED"}
    slots = {f"{s.get('ams_id')}:{s.get('tray_id')}": s for s in materials.get("slots", []) if isinstance(s, dict)}
    for identity in policy["slots"]:
        ams_id, tray_id = map(int, identity.split(":"))
        mapping_id = ams_id * 4 + tray_id
        slot = slots.get(identity, {})
        reason = ""
        if not slot or not bits & (1 << mapping_id):
            reason = "empty_or_absent"
        elif not base["required_material"] or str(slot.get("tray_type") or "").strip().upper() != base["required_material"]:
            reason = "material_mismatch"
        elif slot.get("remain_percent") is not None:
            try:
                remaining = float(slot["remain_percent"])
                if not math.isfinite(remaining) or remaining <= 0:
                    reason = "empty_or_unknown_remaining"
            except (TypeError, ValueError):
                reason = "invalid_remaining"
        if reason:
            base["skipped"].append({"slot_id": identity, "reason": reason})
            continue
        return {**base, "ok": True, "slot_id": identity, "use_ams": True,
                "ams_mapping": [mapping_id], "selected_slot": slot, "failure_code": ""}
    return {**base, "failure_code": "BAMBU_MATERIAL_NO_COMPATIBLE_SLOT"}


def bind_artifact(selection, path, plate_id=1) -> dict:
    """Bind a single-material specimen to its actual 1-based sliced filament ID."""
    if not selection.get("enabled"):
        return selection
    if path is None:
        return {**selection, "ok": False, "failure_code": "BAMBU_MATERIAL_ARTIFACT_EVIDENCE_REQUIRED"}
    try:
        with zipfile.ZipFile(path) as archive:
            code = archive.read(f"Metadata/plate_{int(plate_id)}.gcode").decode("utf-8")
        commands = "\n".join(line.split(";", 1)[0] for line in code.splitlines())
        movements = [line for line in commands.splitlines() if re.match(r"\s*G0?[0123](?=[^0-9]|$)", line, re.I)]
        # Accept compact G1X..E.. too; unsupported/empty programs are not proof of motion-only.
        # Absolute E can extrude even at a negative/zero coordinate. Only an
        # E-free program is eligible for the motion-only exemption.
        has_extrusion = bool(re.search(r"E\s*[-+]?(?:\d|\.)", commands, re.I))
        if movements and not has_extrusion and not re.search(r"\b(?:M701|M702)\b", commands, re.I):
            return {"ok": True, "enabled": False, "reason": "motion_only_artifact"}
        if not selection.get("ok"):
            return selection
        used = re.search(r"^;\s*filament:\s*([0-9, ]+)\s*$", code, re.M)
        types = re.search(r"^;\s*filament_type\s*=\s*(.+)$", code, re.M)
        if not used or not types:
            raise ValueError("missing filament evidence")
        ids = [int(value.strip()) for value in used.group(1).split(",")]
        materials = [value.strip().strip('"').upper() for value in types.group(1).split(";")]
        if len(ids) != 1 or not 1 <= ids[0] <= len(materials) <= 64:
            raise ValueError("single-material specimen required")
        if materials[ids[0] - 1] != selection["required_material"]:
            return {**selection, "ok": False, "failure_code": "BAMBU_MATERIAL_ARTIFACT_MISMATCH"}
        mapping = [-1] * len(materials)
        ams_id, tray_id = map(int, selection["slot_id"].split(":"))
        mapping[ids[0] - 1] = ams_id * 4 + tray_id
        return {**selection, "ams_mapping": mapping, "artifact_material_verified": True}
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, zipfile.BadZipFile):
        return {**selection, "ok": False, "failure_code": "BAMBU_MATERIAL_ARTIFACT_EVIDENCE_REQUIRED"}


def material_artifact_path(value, repo_root):
    parsed = urlparse(str(value or ""))
    if parsed.scheme in {"http", "https"}:
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) != 4 or parts[:2] != ["printer-artifacts", "bambu"]:
            return None
        root = (Path(repo_root) / "artifacts/bambu_http_exports").resolve()
        path = (root / parts[2] / parts[3]).resolve()
        return path if path.is_relative_to(root) else None
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(repo_root) / path
