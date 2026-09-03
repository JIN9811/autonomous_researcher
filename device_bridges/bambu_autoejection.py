"""
Deterministic Bambu Lab G-code autoejection artifact patching.

This module is intentionally pure-file logic: it never talks to a printer and
never starts motion. Live publish gates stay in the device bridge/API layer.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_MARKER = "atr.bambu.autoejection.v1"
DEFAULT_BUILD_ENVELOPE_MM = (256.0, 256.0, 260.0)
_END_COMMAND_RE = re.compile(r"^\s*(M84|M104\s+S0|M140\s+S0|M107)\b", re.IGNORECASE)
_MOTION_RE = re.compile(r"^\s*G(?:0|1)\b", re.IGNORECASE)
_HOME_RE = re.compile(r"^\s*G28\b", re.IGNORECASE)
_GCODE_NUMBER = r"-?(?:\d+(?:\.\d*)?|\.\d+)"
_AXIS_RE = re.compile(rf"\b([XYZ])\s*({_GCODE_NUMBER})", re.IGNORECASE)
_FEEDRATE_RE = re.compile(rf"\bF\s*({_GCODE_NUMBER})", re.IGNORECASE)
_OBJECT_COUNT_RE = re.compile(r"^\s*;\s*total\s+object\s+count\s*:\s*(\d+)\s*$", re.IGNORECASE)
_OBJECT_MARKER_RE = re.compile(r"^\s*;\s*(?:object|start\s+printing\s+object)\s*:", re.IGNORECASE)
_RESIDUE_RE = re.compile(r"^\s*;\s*(?:FEATURE|TYPE)\s*:\s*(?:skirt|brim|raft)\b", re.IGNORECASE)
_COOLDOWN_WAIT_RE = re.compile(r"^\s*M190\b.*\b[RS]\s*-?\d+", re.IGNORECASE)
_COOLDOWN_POLICY_RE = re.compile(r"^\s*;\s*atr_(?:cooldown_wait_policy|bed_cooldown_c)\s*=", re.IGNORECASE)
_COMMENT_JSON_RE = re.compile(r"^\s*;\s*([a-zA-Z0-9_]+)\s*=\s*(.+?)\s*$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_stem_for_autoeject(path: Path) -> str:
    lower_name = path.name.lower()
    if lower_name.endswith(".gcode.3mf"):
        return path.name[: -len(".gcode.3mf")]
    if lower_name.endswith(".gcode"):
        return path.name[: -len(".gcode")]
    return path.stem


def _extract_axis_positions(line: str) -> dict[str, float]:
    return {axis.upper(): float(value) for axis, value in _AXIS_RE.findall(line)}


def _last_extrusion_line_index(lines: list[str]) -> int | None:
    absolute_e = True
    last_absolute_e = 0.0
    last_extrusion: int | None = None
    for index, raw_line in enumerate(lines):
        line = str(raw_line or "").split(";", 1)[0].strip()
        if not line:
            continue
        command = line.split()[0].upper()
        if command == "M82":
            absolute_e = True
            continue
        if command == "M83":
            absolute_e = False
            continue
        e_match = re.search(rf"\bE\s*({_GCODE_NUMBER})", line, flags=re.IGNORECASE)
        if command == "G92":
            if e_match:
                last_absolute_e = float(e_match.group(1))
            continue
        if command not in {"G0", "G1"} or not e_match:
            continue
        e_value = float(e_match.group(1))
        extruding = e_value > last_absolute_e + 1e-7 if absolute_e else e_value > 1e-7
        if absolute_e:
            last_absolute_e = e_value
        if extruding:
            last_extrusion = index
    return last_extrusion


def _bounds_payload(
    *,
    min_x: float | None,
    max_x: float | None,
    min_y: float | None,
    max_y: float | None,
    min_z: float | None,
    max_z: float | None,
    source: str,
    extrusion_move_count: int = 0,
) -> dict[str, float | int | str | None]:
    center_x = (float(min_x) + float(max_x)) / 2.0 if isinstance(min_x, (int, float)) and isinstance(max_x, (int, float)) else None
    center_y = (float(min_y) + float(max_y)) / 2.0 if isinstance(min_y, (int, float)) and isinstance(max_y, (int, float)) else None
    center_z = (float(min_z) + float(max_z)) / 2.0 if isinstance(min_z, (int, float)) and isinstance(max_z, (int, float)) else None
    return {
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
        "min_z": min_z,
        "max_z": max_z,
        "center_x_mm": round(center_x, 4) if center_x is not None else None,
        "center_y_mm": round(center_y, 4) if center_y is not None else None,
        "center_z_mm": round(center_z, 4) if center_z is not None else None,
        "source": source,
        "extrusion_move_count": int(extrusion_move_count),
    }


def _bounds_from_comment_payload(payload: Any, *, source: str = "assumed_object_bounds") -> dict[str, float | int | str | None] | None:
    if not isinstance(payload, dict):
        return None
    aliases = {
        "min_x": ("min_x", "x_min", "x_min_mm"),
        "max_x": ("max_x", "x_max", "x_max_mm"),
        "min_y": ("min_y", "y_min", "y_min_mm"),
        "max_y": ("max_y", "y_max", "y_max_mm"),
        "min_z": ("min_z", "z_min", "z_min_mm"),
        "max_z": ("max_z", "z_max", "z_max_mm"),
    }
    values: dict[str, float | None] = {}
    for key, names in aliases.items():
        value = None
        for name in names:
            if name in payload:
                value = payload[name]
                break
        try:
            values[key] = None if value is None else float(value)
        except (TypeError, ValueError):
            values[key] = None
    if values["min_x"] is None or values["max_x"] is None or values["min_y"] is None or values["max_y"] is None or values["max_z"] is None:
        return None
    if values["min_z"] is None:
        values["min_z"] = 0.0
    return _bounds_payload(**values, source=source, extrusion_move_count=0)


def _explicit_object_bounds_from_comments(gcode_text: str) -> dict[str, float | int | str | None] | None:
    assumed_size: list[float] | None = None
    assumed_center: list[float] | None = None
    for line in str(gcode_text or "").splitlines():
        match = _COMMENT_JSON_RE.search(line)
        if not match:
            continue
        key = match.group(1).strip().lower()
        value_text = match.group(2).strip()
        try:
            value = json.loads(value_text)
        except json.JSONDecodeError:
            continue
        if key == "atr_actual_object_bounds_mm":
            parsed = _bounds_from_comment_payload(value, source="actual_source_extrusion_bounds")
            if parsed is not None:
                return parsed
        if key == "atr_assumed_object_bounds_mm":
            parsed = _bounds_from_comment_payload(value)
            if parsed is not None:
                return parsed
        if key == "atr_assumed_object_size_mm" and isinstance(value, list) and len(value) >= 3:
            try:
                assumed_size = [float(value[0]), float(value[1]), float(value[2])]
            except (TypeError, ValueError):
                assumed_size = None
        if key in {"atr_assumed_object_center_mm", "atr_assumed_object_center_xy_mm"} and isinstance(value, list) and len(value) >= 2:
            try:
                assumed_center = [float(value[0]), float(value[1]), float(value[2]) if len(value) >= 3 else 0.0]
            except (TypeError, ValueError):
                assumed_center = None
    if assumed_size is None:
        return None
    sx, sy, sz = [max(0.0, float(item)) for item in assumed_size[:3]]
    cx = float(assumed_center[0]) if assumed_center else DEFAULT_BUILD_ENVELOPE_MM[0] / 2.0
    cy = float(assumed_center[1]) if assumed_center else DEFAULT_BUILD_ENVELOPE_MM[1] / 2.0
    return _bounds_payload(
        min_x=cx - sx / 2.0,
        max_x=cx + sx / 2.0,
        min_y=cy - sy / 2.0,
        max_y=cy + sy / 2.0,
        min_z=0.0,
        max_z=sz,
        source="assumed_object_size",
        extrusion_move_count=0,
    )


def extract_object_bounds_mm(gcode_text: str) -> dict[str, float | int | str | None]:
    """Extract printed object bounds from explicit metadata or extrusion moves.

    Travel and parking moves are intentionally ignored when extrusion evidence
    exists, so the ejection contact point follows the generated object instead
    of the slicer/toolhead cleanup path.
    """
    explicit = _explicit_object_bounds_from_comments(gcode_text)
    if explicit is not None:
        return explicit

    absolute_xyz = True
    absolute_e = True
    current: dict[str, float | None] = {"X": None, "Y": None, "Z": None}
    last_abs_e = 0.0
    extrusion_points: list[tuple[float, float, float]] = []
    all_xs: list[float] = []
    all_ys: list[float] = []
    all_zs: list[float] = []
    extrusion_moves = 0

    for raw_line in str(gcode_text or "").splitlines():
        line = raw_line.split(";", 1)[0].strip()
        if not line:
            continue
        command = line.split()[0].upper()
        if command == "G90":
            absolute_xyz = True
            continue
        if command == "G91":
            absolute_xyz = False
            continue
        if command == "M82":
            absolute_e = True
            continue
        if command == "M83":
            absolute_e = False
            continue
        values = {axis.upper(): float(value) for axis, value in re.findall(rf"\b([XYZE])\s*({_GCODE_NUMBER})", line, flags=re.IGNORECASE)}
        if command == "G92":
            if "E" in values:
                last_abs_e = values["E"]
            for axis in ("X", "Y", "Z"):
                if axis in values:
                    current[axis] = values[axis]
            continue
        if command not in {"G0", "G1"}:
            continue
        previous = dict(current)
        for axis in ("X", "Y", "Z"):
            if axis not in values:
                continue
            if absolute_xyz or current[axis] is None:
                current[axis] = values[axis]
            else:
                current[axis] = float(current[axis] or 0.0) + values[axis]
        if current["X"] is not None:
            all_xs.append(float(current["X"]))
        if current["Y"] is not None:
            all_ys.append(float(current["Y"]))
        if current["Z"] is not None:
            all_zs.append(float(current["Z"]))

        extruding = False
        if "E" in values:
            if absolute_e:
                extruding = values["E"] > last_abs_e + 1e-7
                last_abs_e = values["E"]
            else:
                extruding = values["E"] > 1e-7
        if not extruding or current["X"] is None or current["Y"] is None:
            continue
        z_value = float(current["Z"] if current["Z"] is not None else previous.get("Z") or 0.0)
        for item in (previous, current):
            if item.get("X") is None or item.get("Y") is None:
                continue
            extrusion_points.append((float(item["X"]), float(item["Y"]), z_value))
        extrusion_moves += 1

    if extrusion_points:
        xs = [point[0] for point in extrusion_points]
        ys = [point[1] for point in extrusion_points]
        zs = [point[2] for point in extrusion_points]
        return _bounds_payload(
            min_x=min(xs),
            max_x=max(xs),
            min_y=min(ys),
            max_y=max(ys),
            min_z=min(zs),
            max_z=max(zs),
            source="extrusion_moves",
            extrusion_move_count=extrusion_moves,
        )
    return _bounds_payload(
        min_x=min(all_xs) if all_xs else None,
        max_x=max(all_xs) if all_xs else None,
        min_y=min(all_ys) if all_ys else None,
        max_y=max(all_ys) if all_ys else None,
        min_z=min(all_zs) if all_zs else None,
        max_z=max(all_zs) if all_zs else None,
        source="all_motion_fallback" if all_xs or all_ys or all_zs else "unknown",
        extrusion_move_count=0,
    )


@dataclass(slots=True)
class BambuGcodeAutoejectionValidator:
    """Validate Bambu autoejection-tail invariants before any publish path."""

    build_envelope_mm: tuple[float, float, float] = DEFAULT_BUILD_ENVELOPE_MM
    min_object_height_mm: float = 5.0
    max_object_height_mm: float = 200.0
    max_xy_ejection_feedrate_mm_min: float = 12000.0

    def validate(self, gcode_text: str, *, source_plate_path: str = "plain_gcode") -> dict[str, Any]:
        blockers: list[str] = []
        marker_count = gcode_text.count(SCHEMA_MARKER)
        lines = str(gcode_text or "").splitlines()
        marker_line_index = next((index for index, line in enumerate(lines) if SCHEMA_MARKER in line), None)
        last_extrusion_line_index = _last_extrusion_line_index(lines)
        tail_after_last_extrusion = bool(
            marker_line_index is not None
            and (last_extrusion_line_index is None or marker_line_index > last_extrusion_line_index)
        )
        print_body = self._print_body_before_tail(gcode_text)
        object_bounds = extract_object_bounds_mm(print_body)
        if marker_count == 0:
            blockers.append("BAMBU_AUTOEJECTION_TAIL_MISSING")
        if marker_count > 1:
            blockers.append("BAMBU_AUTOEJECTION_TAIL_DUPLICATED")
        if marker_count > 0 and not tail_after_last_extrusion:
            blockers.append("BAMBU_AUTOEJECTION_TAIL_BEFORE_LAST_EXTRUSION")
        if marker_count > 0 and not self._has_cooldown_wait(gcode_text):
            blockers.append("BAMBU_AUTOEJECTION_COOLDOWN_WAIT_MISSING")
        if self._contains_unexpected_home(gcode_text):
            blockers.append("BAMBU_AUTOEJECTION_UNEXPECTED_HOME")
        if self._contains_unsafe_motion(gcode_text):
            blockers.append("BAMBU_AUTOEJECTION_UNSAFE_MOTION")
        if self._contains_unsafe_xy_feedrate(gcode_text):
            blockers.append("BAMBU_AUTOEJECTION_UNSAFE_FEEDRATE")
        if self._object_too_low(object_bounds):
            blockers.append("BAMBU_AUTOEJECTION_OBJECT_TOO_LOW")
        if self._object_too_tall(object_bounds):
            blockers.append("BAMBU_AUTOEJECTION_OBJECT_TOO_TALL")
        if self._looks_like_multi_object_plate(print_body):
            blockers.append("BAMBU_AUTOEJECTION_MULTI_OBJECT_UNSUPPORTED")
        if self._contains_residual_skirt_brim_or_raft(print_body):
            blockers.append("BAMBU_AUTOEJECTION_RESIDUAL_PRIME_OR_SKIRT_RISK")
        return {
            "ok": not blockers,
            "schema": "bambu_autoejection_validation.v1",
            "source_plate_path": source_plate_path,
            "marker_count": marker_count,
            "marker_line_index": marker_line_index,
            "last_extrusion_line_index": last_extrusion_line_index,
            "tail_after_last_extrusion": tail_after_last_extrusion,
            "blockers": blockers,
            "object_bounds_mm": object_bounds,
            "build_envelope_mm": list(self.build_envelope_mm),
            "min_object_height_mm": self.min_object_height_mm,
            "max_object_height_mm": self.max_object_height_mm,
            "max_xy_ejection_feedrate_mm_min": self.max_xy_ejection_feedrate_mm_min,
            "cooldown_wait_present": self._has_cooldown_wait(gcode_text),
            "validated_at": _utc_now(),
        }

    def _print_body_before_tail(self, gcode_text: str) -> str:
        return str(gcode_text or "").split(f"; {SCHEMA_MARKER}", 1)[0].split(SCHEMA_MARKER, 1)[0]

    def _contains_unexpected_home(self, gcode_text: str) -> bool:
        marker_seen = False
        for line in gcode_text.splitlines():
            if SCHEMA_MARKER in line:
                marker_seen = True
            if marker_seen and _HOME_RE.search(line):
                return True
        return False

    def _has_cooldown_wait(self, gcode_text: str) -> bool:
        marker_seen = False
        for line in str(gcode_text or "").splitlines():
            if SCHEMA_MARKER in line:
                marker_seen = True
            if not marker_seen:
                continue
            if _COOLDOWN_WAIT_RE.search(line) or _COOLDOWN_POLICY_RE.search(line):
                return True
        return False

    def _object_too_low(self, object_bounds: dict[str, float | None]) -> bool:
        max_z = object_bounds.get("max_z")
        if not isinstance(max_z, (int, float)):
            return False
        return float(max_z) < float(self.min_object_height_mm)

    def _object_too_tall(self, object_bounds: dict[str, float | None]) -> bool:
        max_z = object_bounds.get("max_z")
        if not isinstance(max_z, (int, float)):
            return False
        return float(max_z) > float(self.max_object_height_mm)

    def _looks_like_multi_object_plate(self, print_body: str) -> bool:
        explicit_counts = []
        object_markers = 0
        for line in str(print_body or "").splitlines():
            count_match = _OBJECT_COUNT_RE.search(line)
            if count_match:
                explicit_counts.append(int(count_match.group(1)))
            if _OBJECT_MARKER_RE.search(line):
                object_markers += 1
        if any(count > 1 for count in explicit_counts):
            return True
        return object_markers > 1

    def _contains_residual_skirt_brim_or_raft(self, print_body: str) -> bool:
        return any(_RESIDUE_RE.search(line) for line in str(print_body or "").splitlines())

    def _contains_unsafe_motion(self, gcode_text: str) -> bool:
        max_x, max_y, max_z = self.build_envelope_mm
        marker_seen = False
        for line in gcode_text.splitlines():
            if SCHEMA_MARKER in line:
                marker_seen = True
            if not marker_seen or not _MOTION_RE.search(line):
                continue
            coords = _extract_axis_positions(line)
            if "X" in coords and not 0.0 <= coords["X"] <= max_x:
                return True
            if "Y" in coords and not 0.0 <= coords["Y"] <= max_y:
                return True
            if "Z" in coords and not 0.0 <= coords["Z"] <= max_z:
                return True
        return False

    def _contains_unsafe_xy_feedrate(self, gcode_text: str) -> bool:
        marker_seen = False
        for line in str(gcode_text or "").splitlines():
            if SCHEMA_MARKER in line:
                marker_seen = True
            if not marker_seen or not _MOTION_RE.search(line):
                continue
            coords = _extract_axis_positions(line)
            if "X" not in coords and "Y" not in coords:
                continue
            feedrate_match = _FEEDRATE_RE.search(line)
            if not feedrate_match:
                continue
            if float(feedrate_match.group(1)) > float(self.max_xy_ejection_feedrate_mm_min):
                return True
        return False


@dataclass(slots=True)
class BambuGcodeAutoejectionPatcher:
    """Create patched Bambu artifacts with a validated autoejection tail."""

    output_dir: Path
    validator: BambuGcodeAutoejectionValidator = field(default_factory=BambuGcodeAutoejectionValidator)
    bed_cooldown_c: int = 40
    safe_z_mm: float = 20.0
    min_absolute_push_z_mm: float = 10.0
    z_push_offset_mm: float = 15.0
    front_y_mm: float = 8.0
    rear_y_mm: float = 245.0
    push_lane_offset_mm: float = 30.0
    sweep_feedrate_mm_min: int = 6000
    enable_full_bed_sweep: bool = False
    sweep_z_mm: float = 1.0
    full_bed_sweep_feedrate_mm_min: int = 6000
    z_feedrate_mm_min: int = 3000

    def patch_artifact(
        self,
        source_path: str | Path,
        *,
        specimen_id: str = "",
        position: str = "center",
        plate_id: int = 1,
        loop_index: int = 1,
    ) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not source.exists() or not source.is_file():
            return self._blocked("BAMBU_AUTOEJECTION_SOURCE_NOT_FOUND", source_path=str(source))
        lower_name = source.name.lower()
        if lower_name.endswith(".gcode.3mf"):
            return self._patch_gcode_3mf(
                source,
                specimen_id=specimen_id,
                position=position,
                plate_id=plate_id,
                loop_index=loop_index,
            )
        if lower_name.endswith(".gcode"):
            return self._patch_plain_gcode(source, specimen_id=specimen_id, position=position, loop_index=loop_index)
        return self._blocked("BAMBU_AUTOEJECTION_SOURCE_EXTENSION_UNSUPPORTED", source_path=str(source))

    def validate_artifact(
        self,
        source_path: str | Path,
        *,
        specimen_id: str = "",
        position: str = "center",
        plate_id: int = 1,
        loop_index: int = 1,
    ) -> dict[str, Any]:
        """Validate the would-be patched artifact without writing an output file."""
        source = Path(source_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            return self._blocked(
                "BAMBU_AUTOEJECTION_SOURCE_NOT_FOUND",
                tool="printer.bambu.autoejection_validate",
                source_path=str(source),
            )
        lower_name = source.name.lower()
        try:
            if lower_name.endswith(".gcode.3mf"):
                original, source_plate_path, source_bytes = self._read_gcode_3mf_plate(source, plate_id=plate_id)
            elif lower_name.endswith(".gcode"):
                source_bytes = source.read_bytes()
                original = source_bytes.decode("utf-8")
                source_plate_path = "plain_gcode"
            else:
                return self._blocked(
                    "BAMBU_AUTOEJECTION_SOURCE_EXTENSION_UNSUPPORTED",
                    tool="printer.bambu.autoejection_validate",
                    source_path=str(source),
                )
        except KeyError:
            return self._blocked(
                "BAMBU_3MF_PLATE_GCODE_NOT_FOUND",
                tool="printer.bambu.autoejection_validate",
                source_path=str(source),
                plate_id=plate_id,
            )
        patched = self._insert_tail(
            original,
            source_sha256=_sha256_bytes(source_bytes),
            specimen_id=specimen_id,
            position=position,
            source_plate_path=source_plate_path,
            plate_id=plate_id if source_plate_path.startswith("Metadata/plate_") else None,
            loop_index=loop_index,
        )
        validation = self.validator.validate(patched, source_plate_path=source_plate_path)
        return {
            "ok": bool(validation.get("ok")),
            "tool": "printer.bambu.autoejection_validate",
            "schema": "bambu_autoejection_validate.v1",
            "status": "validated" if validation.get("ok") else "blocked",
            "source_path": str(source),
            "patched_artifact_path": "",
            "source_plate_path": source_plate_path,
            "plate_id": plate_id if source_plate_path.startswith("Metadata/plate_") else None,
            "loop_index": int(loop_index),
            "specimen_id": specimen_id,
            "position": position,
            "source_sha256": _sha256_bytes(source_bytes),
            "candidate_patched_sha256": _sha256_bytes(patched.encode("utf-8")),
            "size_bytes": len(patched.encode("utf-8")),
            "object_bounds_mm": extract_object_bounds_mm(original),
            "validation": validation,
            "blockers": validation.get("blockers", []),
            "created_at": _utc_now(),
            "manifest_path": "",
            "will_publish": False,
            "start_enabled": False,
        }

    def build_standalone_ejection_artifact(
        self,
        *,
        position: str = "center",
        specimen_id: str = "standalone-ejection-test",
        object_size_mm: list[float] | None = None,
        object_bounds_mm: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a validation-only Bambu ejection G-code job with no print body."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(specimen_id or "").strip())
        safe_id = safe_id.strip("._-") or "standalone-ejection-test"
        size = object_size_mm or [30.0, 30.0, 20.0]
        source_bounds = _bounds_from_comment_payload(object_bounds_mm) if isinstance(object_bounds_mm, dict) else None
        bounds = self._comment_bounds_payload(source_bounds) if source_bounds is not None else self._standalone_bounds_for_position(position, size)
        body = "\n".join(
            [
                "; ATR standalone Bambu autoejection validation job",
                "G90",
                f"; atr_assumed_object_size_mm={json.dumps([float(item) for item in size])}",
                f"; atr_assumed_object_bounds_mm={json.dumps(bounds, sort_keys=True)}",
                "M84",
            ]
        )
        patched = self._insert_tail(
            body,
            source_sha256=_sha256_bytes(body.encode("utf-8")),
            specimen_id=safe_id,
            position=position,
            source_plate_path="standalone_gcode_job",
            plate_id=None,
            loop_index=1,
        )
        out_path = self.output_dir / f"{safe_id}.{str(position or 'center').lower()}.autoeject.gcode"
        out_path.write_text(patched, encoding="utf-8")
        startable_path = self.output_dir / f"{safe_id}.{str(position or 'center').lower()}.autoeject.gcode.3mf"
        startable_plate_path = "Metadata/plate_1.gcode"
        with zipfile.ZipFile(startable_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(startable_plate_path, patched)
            archive.writestr(
                f"{startable_plate_path}.md5",
                hashlib.md5(patched.encode("utf-8")).hexdigest(),
            )
            archive.writestr("3D/3dmodel.model", "<model />")
        post_write_validation = self._validate_written_artifact(
            out_path,
            source_plate_path="standalone_gcode_job",
        )
        startable_post_write_validation = self._validate_written_artifact(
            startable_path,
            source_plate_path=startable_plate_path,
        )
        validation = startable_post_write_validation.get("tail_validation", {})
        post_write_ok = bool(post_write_validation.get("ok") and startable_post_write_validation.get("ok"))
        result = {
            "ok": bool(validation.get("ok") and post_write_ok),
            "tool": "printer.bambu.autoejection_standalone",
            "schema": "bambu_autoejection_standalone.v1",
            "status": "standalone_validated" if validation.get("ok") and post_write_ok else "blocked",
            "patched_artifact_path": str(out_path),
            "startable_artifact_path": str(startable_path),
            "startable_plate_path": startable_plate_path,
            "source_plate_path": "standalone_gcode_job",
            "plate_id": 1,
            "loop_index": 1,
            "specimen_id": safe_id,
            "position": position,
            "object_size_mm": [float(item) for item in size],
            "object_bounds_mm": extract_object_bounds_mm(body),
            "source_object_bounds_mm": source_bounds,
            "patched_sha256": str(post_write_validation.get("artifact_sha256") or ""),
            "startable_sha256": str(startable_post_write_validation.get("artifact_sha256") or ""),
            "size_bytes": out_path.stat().st_size,
            "startable_size_bytes": startable_path.stat().st_size,
            "validation": validation,
            "post_write_validation": post_write_validation,
            "startable_post_write_validation": startable_post_write_validation,
            "blockers": [
                *list(validation.get("blockers", [])),
                *([] if post_write_ok else ["BAMBU_AUTOEJECTION_POST_WRITE_VALIDATION_FAILED"]),
            ],
            "created_at": _utc_now(),
            "will_publish": False,
            "start_enabled": False,
        }
        result["manifest_path"] = str(self._write_manifest(out_path, result))
        return result

    def build_ejection_only_from_sliced_artifact(
        self,
        source_path: str | Path,
        *,
        specimen_id: str = "",
        position: str = "center",
        plate_id: int = 1,
        loop_index: int = 1,
    ) -> dict[str, Any]:
        """Build a project-file ejection test derived from the real sliced artifact.

        This keeps the slicer's initial coordinate setup but removes the print
        body/extrusion path. The ejection tail is still generated from object
        bounds extracted from the original extrusion moves.
        """
        source = Path(source_path).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not source.exists() or not source.is_file():
            return self._blocked("BAMBU_AUTOEJECTION_SOURCE_NOT_FOUND", source_path=str(source))
        lower_name = source.name.lower()
        try:
            if lower_name.endswith(".gcode.3mf"):
                original, source_plate_path, source_bytes = self._read_gcode_3mf_plate(source, plate_id=plate_id)
            elif lower_name.endswith(".gcode"):
                source_bytes = source.read_bytes()
                original = source_bytes.decode("utf-8", errors="replace")
                source_plate_path = "plain_gcode"
            else:
                return self._blocked("BAMBU_AUTOEJECTION_SOURCE_EXTENSION_UNSUPPORTED", source_path=str(source))
        except KeyError:
            return self._blocked("BAMBU_3MF_PLATE_GCODE_NOT_FOUND", source_path=str(source), plate_id=plate_id)

        source_bounds = extract_object_bounds_mm(original)
        if source_bounds.get("source") != "extrusion_moves" or not all(
            isinstance(source_bounds.get(key), (int, float)) for key in ("center_x_mm", "center_y_mm", "max_z")
        ):
            return self._blocked(
                "BAMBU_AUTOEJECTION_SOURCE_EXTRUSION_BOUNDS_REQUIRED",
                source_path=str(source),
                source_plate_path=source_plate_path,
                object_bounds_mm=source_bounds,
            )
        ejection_only_body = self._ejection_only_startup_gcode(original, source_bounds)
        patched = self._insert_tail(
            ejection_only_body,
            source_sha256=_sha256_bytes(source_bytes),
            specimen_id=specimen_id,
            position=position,
            source_plate_path=source_plate_path,
            plate_id=plate_id if source_plate_path.startswith("Metadata/plate_") else None,
            loop_index=loop_index,
        )
        if lower_name.endswith(".gcode.3mf"):
            out_path = self.output_dir / f"{_safe_stem_for_autoeject(source)}.ejection-test.gcode.3mf"
            patched_md5 = hashlib.md5(patched.encode("utf-8")).hexdigest()
            md5_path = f"{source_plate_path}.md5"
            wrote_md5 = False
            wrote_slice_info = False
            with zipfile.ZipFile(source) as src_zip:
                with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as dst_zip:
                    for info in src_zip.infolist():
                        data = src_zip.read(info.filename)
                        if info.filename == source_plate_path:
                            data = patched.encode("utf-8")
                        elif info.filename == md5_path:
                            data = patched_md5.encode("utf-8")
                            wrote_md5 = True
                        elif info.filename == "Metadata/slice_info.config":
                            data = self._ejection_only_slice_info_config(
                                source_bounds,
                                source_name=source.name,
                            ).encode("utf-8")
                            wrote_slice_info = True
                        dst_zip.writestr(info, data)
                    if not wrote_md5:
                        dst_zip.writestr(md5_path, patched_md5)
                    if not wrote_slice_info:
                        dst_zip.writestr(
                            "Metadata/slice_info.config",
                            self._ejection_only_slice_info_config(source_bounds, source_name=source.name),
                        )
        else:
            out_path = self.output_dir / f"{_safe_stem_for_autoeject(source)}.ejection-test.gcode"
            out_path.write_text(patched, encoding="utf-8")

        post_write_validation = self._validate_written_artifact(
            out_path,
            source_plate_path=source_plate_path,
        )
        validation = post_write_validation.get("tail_validation", {})
        post_write_ok = bool(post_write_validation.get("ok"))
        result = {
            "ok": bool(validation.get("ok") and post_write_ok),
            "tool": "printer.bambu.ejection_only_patch",
            "schema": "bambu_ejection_only_project_file.v1",
            "status": "ejection_only_validated" if validation.get("ok") and post_write_ok else "blocked",
            "source_path": str(source),
            "patched_artifact_path": str(out_path),
            "source_plate_path": source_plate_path,
            "plate_id": plate_id if source_plate_path.startswith("Metadata/plate_") else None,
            "loop_index": int(loop_index),
            "specimen_id": specimen_id,
            "position": position,
            "source_sha256": _sha256_bytes(source_bytes),
            "patched_sha256": str(post_write_validation.get("artifact_sha256") or ""),
            "size_bytes": out_path.stat().st_size,
            "object_bounds_mm": source_bounds,
            "source_object_bounds_mm": source_bounds,
            "print_body_policy": "removed_for_installed_printer_test",
            "validation": validation,
            "post_write_validation": post_write_validation,
            "blockers": [
                *list(validation.get("blockers", [])),
                *([] if post_write_ok else ["BAMBU_AUTOEJECTION_POST_WRITE_VALIDATION_FAILED"]),
            ],
            "created_at": _utc_now(),
            "will_publish": False,
            "start_enabled": False,
        }
        result["manifest_path"] = str(self._write_manifest(out_path, result))
        return result

    def build_sweep_test_artifact(self, *, specimen_id: str = "sweep-test") -> dict[str, Any]:
        """Generate a full-bed sweep validation artifact without print body or publish intent."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(specimen_id or "").strip())
        safe_id = safe_id.strip("._-") or "sweep-test"
        body = "\n".join(
            [
                "; ATR standalone Bambu full-bed sweep validation job",
                "G90",
                "; atr_test_artifact=sweep_only",
                "M84",
            ]
        )
        original_full_bed_sweep = self.enable_full_bed_sweep
        self.enable_full_bed_sweep = True
        try:
            patched = self._insert_tail(
                body,
                source_sha256=_sha256_bytes(body.encode("utf-8")),
                specimen_id=safe_id,
                position="center",
                source_plate_path="sweep_test_gcode_job",
                plate_id=None,
                loop_index=1,
            )
        finally:
            self.enable_full_bed_sweep = original_full_bed_sweep
        out_path = self.output_dir / f"{safe_id}.sweep.autoeject.gcode"
        out_path.write_text(patched, encoding="utf-8")
        validation = self.validator.validate(patched, source_plate_path="sweep_test_gcode_job")
        result = {
            "ok": bool(validation.get("ok")),
            "tool": "printer.bambu.autoejection_sweep_test",
            "schema": "bambu_autoejection_sweep_test.v1",
            "status": "sweep_test_validated" if validation.get("ok") else "blocked",
            "patched_artifact_path": str(out_path),
            "source_plate_path": "sweep_test_gcode_job",
            "plate_id": None,
            "loop_index": 1,
            "specimen_id": safe_id,
            "position": "center",
            "patched_sha256": _sha256_bytes(out_path.read_bytes()),
            "size_bytes": out_path.stat().st_size,
            "validation": validation,
            "blockers": validation.get("blockers", []),
            "created_at": _utc_now(),
            "will_publish": False,
            "start_enabled": False,
        }
        result["manifest_path"] = str(self._write_manifest(out_path, result))
        return result

    def _patch_plain_gcode(self, source: Path, *, specimen_id: str, position: str, loop_index: int) -> dict[str, Any]:
        source_bytes = source.read_bytes()
        original = source_bytes.decode("utf-8")
        if SCHEMA_MARKER in original:
            return self._result(
                source_path=source,
                patched_path=source,
                original_gcode=original,
                patched_gcode=original,
                source_plate_path="plain_gcode",
                plate_id=None,
                loop_index=loop_index,
                specimen_id=specimen_id,
                position=position,
            )
        patched = self._insert_tail(
            original,
            source_sha256=_sha256_bytes(source_bytes),
            specimen_id=specimen_id,
            position=position,
            source_plate_path="plain_gcode",
            plate_id=None,
            loop_index=loop_index,
        )
        out_path = self.output_dir / f"{_safe_stem_for_autoeject(source)}.autoeject.gcode"
        out_path.write_text(patched, encoding="utf-8")
        return self._result(
            source_path=source,
            patched_path=out_path,
            original_gcode=original,
            patched_gcode=patched,
            source_plate_path="plain_gcode",
            plate_id=None,
            loop_index=loop_index,
            specimen_id=specimen_id,
            position=position,
        )

    def _ejection_only_startup_gcode(self, original_gcode: str, source_bounds: dict[str, Any]) -> str:
        lines = str(original_gcode or "").splitlines()
        kept: list[str] = []
        in_executable = False
        saw_machine_start_end = False
        header_inserted = False
        skipping_header = False
        has_executable_block = any(line.strip().lower().startswith("; executable_block_start") for line in lines)
        header_lines = self._ejection_only_header_lines(source_bounds)

        def insert_header_once() -> None:
            nonlocal header_inserted
            if not header_inserted:
                kept.extend(header_lines)
                header_inserted = True

        if not has_executable_block:
            insert_header_once()
            for line in lines:
                lower = line.strip().lower()
                if lower.startswith("; header_block_start"):
                    skipping_header = True
                    continue
                if skipping_header:
                    if lower.startswith("; header_block_end"):
                        skipping_header = False
                    continue
                if lower.startswith("; machine_end_gcode_start") or self._is_extrusion_motion_line(line):
                    break
                if self._keep_ejection_only_start_line(line):
                    kept.append(line)
            return self._finish_ejection_only_startup_gcode(kept, source_bounds)
        for line in lines:
            stripped = line.strip()
            lower = stripped.lower()
            if not in_executable:
                if lower.startswith("; header_block_start"):
                    insert_header_once()
                    skipping_header = True
                    continue
                if skipping_header:
                    if lower.startswith("; header_block_end"):
                        skipping_header = False
                    continue
                if lower.startswith("; executable_block_start"):
                    insert_header_once()
                    kept.append(line)
                    in_executable = True
                    continue
                kept.append(line)
                continue
            if lower.startswith("; machine_start_gcode_end"):
                kept.append(line)
                saw_machine_start_end = True
                break
            if self._keep_ejection_only_start_line(line):
                kept.append(line)
        if not saw_machine_start_end and not any("G28" in line.upper() for line in kept):
            for line in lines:
                if re.match(r"^\s*G28\b", line, re.IGNORECASE):
                    kept.append(line)
                    break
        return self._finish_ejection_only_startup_gcode(kept, source_bounds)

    def _ejection_only_header_lines(self, source_bounds: dict[str, Any]) -> list[str]:
        max_z = source_bounds.get("max_z") if isinstance(source_bounds, dict) else None
        max_z_height = float(max_z) if isinstance(max_z, (int, float)) else 0.0
        return [
            "; HEADER_BLOCK_START",
            "; BambuStudio 02.07.01.57",
            "; ATR installed-printer ejection-only validation",
            "; estimated printing time (normal mode) = 2m 0s",
            "; total layer number: 1",
            "; total filament length [mm] : 0.00",
            "; total filament volume [cm^3] : 0.00",
            "; total filament weight [g] : 0.00",
            "; filament_density: 0",
            "; filament_diameter: 1.75",
            f"; max_z_height: {max_z_height:.2f}",
            "; filament: 1",
            "; HEADER_BLOCK_END",
        ]

    @staticmethod
    def _ejection_only_slice_info_config(source_bounds: dict[str, Any], *, source_name: str = "specimen") -> str:
        name = html.escape(str(source_name or "specimen"))
        max_z = source_bounds.get("max_z") if isinstance(source_bounds, dict) else None
        height = float(max_z) if isinstance(max_z, (int, float)) else 0.0
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<config>\n'
            '  <header>\n'
            '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
            '    <header_item key="X-BBL-Client-Version" value="02.07.01.57"/>\n'
            '  </header>\n'
            '  <plate>\n'
            '    <metadata key="index" value="1"/>\n'
            '    <metadata key="prediction" value="120"/>\n'
            '    <metadata key="support_used" value="false"/>\n'
            '    <metadata key="label_object_enabled" value="false"/>\n'
            f'    <metadata key="max_z_height" value="{height:.2f}"/>\n'
            f'    <object identify_id="15" name="{name}" skipped="false" />\n'
            '    <filament id="1" tray_info_idx="" type="PLA" color="#00AE42" used_m="0.00" used_g="0.00" group_id="0" nozzle_diameter="0.40" volume_type="Standard" used_for_object="true" used_for_support="false"/>\n'
            '    <layer_filament_lists>\n'
            '      <layer_filament_list filament_list="0" layer_ranges="0 0" />\n'
            '    </layer_filament_lists>\n'
            '  </plate>\n'
            '</config>\n'
        )

    def _finish_ejection_only_startup_gcode(self, kept: list[str], source_bounds: dict[str, Any]) -> str:
        bounds_comment = self._comment_bounds_payload(source_bounds)
        kept.extend(
            [
                "; ATR installed-printer ejection-only validation body",
                "; atr_print_body_omitted=true",
                "; atr_print_body_policy=removed_for_installed_printer_test",
                f"; atr_actual_object_bounds_mm={json.dumps(source_bounds, sort_keys=True)}",
                f"; atr_assumed_object_bounds_mm={json.dumps(bounds_comment, sort_keys=True)}",
                "G90",
                "G21",
                "M83 ; use relative distances for extrusion",
                "M104 S0 ; turn off temperature",
                "M84     ; disable motors",
                "M73 P100 R0",
                "; EXECUTABLE_BLOCK_END",
            ]
        )
        return "\n".join(kept).rstrip() + "\n"

    @staticmethod
    def _is_extrusion_motion_line(line: str) -> bool:
        code = str(line or "").split(";", 1)[0].strip()
        if not code:
            return False
        command = code.split()[0].upper()
        if command not in {"G0", "G1"}:
            return False
        return bool(re.search(rf"\bE\s*({_GCODE_NUMBER})", code, flags=re.IGNORECASE))

    @staticmethod
    def _keep_ejection_only_start_line(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return True
        if stripped.startswith(";"):
            return not _RESIDUE_RE.search(stripped)
        code = stripped.split(";", 1)[0].strip()
        if not code:
            return True
        command = code.split()[0].upper()
        if command in {"M104", "M109", "M140", "M190"}:
            return False
        if command in {"M201", "M203", "M204", "M205", "M106", "G90", "G21", "M82", "M83", "G28"}:
            return True
        if command in {"G0", "G1"}:
            values = {axis.upper(): float(value) for axis, value in re.findall(rf"\b([XYZE])\s*({_GCODE_NUMBER})", code, flags=re.IGNORECASE)}
            return "E" not in values and "X" not in values and "Y" not in values and "Z" in values
        return False

    def _patch_gcode_3mf(
        self,
        source: Path,
        *,
        specimen_id: str,
        position: str,
        plate_id: int,
        loop_index: int,
    ) -> dict[str, Any]:
        source_bytes = source.read_bytes()
        try:
            original, plate_path, _source_bytes = self._read_gcode_3mf_plate(source, plate_id=plate_id)
        except KeyError:
            return self._blocked("BAMBU_3MF_PLATE_GCODE_NOT_FOUND", source_path=str(source), plate_id=plate_id)
        if SCHEMA_MARKER in original:
            return self._result(
                source_path=source,
                patched_path=source,
                original_gcode=original,
                patched_gcode=original,
                source_plate_path=plate_path,
                plate_id=plate_id,
                loop_index=loop_index,
                specimen_id=specimen_id,
                position=position,
            )
        out_path = self.output_dir / f"{_safe_stem_for_autoeject(source)}.autoeject.gcode.3mf"
        with zipfile.ZipFile(source) as src_zip:
            patched = self._insert_tail(
                original,
                source_sha256=_sha256_bytes(source_bytes),
                specimen_id=specimen_id,
                position=position,
                source_plate_path=plate_path,
                plate_id=plate_id,
                loop_index=loop_index,
            )
            patched_md5 = hashlib.md5(patched.encode("utf-8")).hexdigest()
            md5_path = f"{plate_path}.md5"
            wrote_md5 = False
            with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as dst_zip:
                for info in src_zip.infolist():
                    data = src_zip.read(info.filename)
                    if info.filename == plate_path:
                        data = patched.encode("utf-8")
                    elif info.filename == md5_path:
                        data = patched_md5.encode("utf-8")
                        wrote_md5 = True
                    dst_zip.writestr(info, data)
                if not wrote_md5:
                    dst_zip.writestr(md5_path, patched_md5)
        return self._result(
            source_path=source,
            patched_path=out_path,
            original_gcode=original,
            patched_gcode=patched,
            source_plate_path=plate_path,
            plate_id=plate_id,
            loop_index=loop_index,
            specimen_id=specimen_id,
            position=position,
        )

    def _read_gcode_3mf_plate(self, source: Path, *, plate_id: int) -> tuple[str, str, bytes]:
        source_bytes = source.read_bytes()
        plate_path = f"Metadata/plate_{int(plate_id)}.gcode"
        with zipfile.ZipFile(source) as src_zip:
            names = src_zip.namelist()
            if plate_path not in names:
                raise KeyError(plate_path)
            return src_zip.read(plate_path).decode("utf-8"), plate_path, source_bytes

    def _insert_tail(
        self,
        gcode_text: str,
        *,
        source_sha256: str,
        specimen_id: str,
        position: str,
        source_plate_path: str,
        plate_id: int | None,
        loop_index: int,
    ) -> str:
        if SCHEMA_MARKER in gcode_text:
            return gcode_text
        object_bounds = extract_object_bounds_mm(gcode_text)
        object_height = object_bounds.get("max_z")
        sweep_x = self._sweep_x_for_position(position, object_bounds)
        center = self._object_center_from_bounds(object_bounds)
        sweep_heights = self._sweep_heights(object_bounds)
        safe_approach_z = self._safe_approach_z(object_bounds)
        tail_lines = [
            f"; {SCHEMA_MARKER}",
            f"; atr_source_sha256={source_sha256}",
            f"; atr_source_plate_path={source_plate_path}",
            f"; atr_plate_id={plate_id if plate_id is not None else 'none'}",
            f"; atr_loop_index={int(loop_index)}",
            f"; atr_specimen_id={specimen_id or 'unknown'}",
            f"; atr_position={position}",
            f"; atr_object_bounds_mm={json.dumps(object_bounds, sort_keys=True)}",
            f"; atr_object_center_mm={json.dumps(center)}",
            f"; atr_object_height_mm={float(object_height):.3f}" if isinstance(object_height, (int, float)) else "; atr_object_height_mm=unknown",
            "; atr_material_type=unknown",
            "; atr_bed_surface=unknown",
            f"; atr_bed_cooldown_c={int(self.bed_cooldown_c)}",
            "; atr_cooldown_wait_policy=M190",
            "; atr_purge_parking_strategy=preserve_slicer_end_gcode_then_eject",
            "; atr_home_initialization=preserve_print_job_coordinates",
            f"; atr_safe_approach_z_mm={safe_approach_z:.3f}",
            f"; atr_min_absolute_push_z_mm={float(self.min_absolute_push_z_mm):.1f}",
            f"; atr_z_push_offset_mm={float(self.z_push_offset_mm):.1f}",
            f"; atr_push_lane_offset_mm={float(self.push_lane_offset_mm):.1f}",
            f"; atr_push_speed_mm_min={int(self.sweep_feedrate_mm_min)}",
            f"; atr_full_bed_sweep_enabled={str(bool(self.enable_full_bed_sweep)).lower()}",
            f"; atr_sweep_z_mm={float(self.sweep_z_mm):.3f}",
            f"; atr_sweep_speed_mm_min={int(self.full_bed_sweep_feedrate_mm_min)}",
            "; atr_door_or_front_path_assumption=operator_confirmed_before_publish",
            "; atr_toolhead_cover_risk_note=operator_confirms_cover_secured_before_publish",
            "; atr_validation_result=stored_in_manifest",
            "; atr_patched_artifact_sha256=stored_in_manifest",
            "M400",
            f"M190 R{int(self.bed_cooldown_c)}",
            "G90",
            f"G0 Z{safe_approach_z:.3f} F{int(self.z_feedrate_mm_min)}",
            f"G0 X{sweep_x:.3f} Y{self.rear_y_mm:.3f} F{int(self.sweep_feedrate_mm_min)}",
        ]
        for fraction, sweep_z in sweep_heights:
            tail_lines.extend(
                [
                    f"; atr_sweep_height_fraction={fraction:.2f}",
                    f"G0 Z{sweep_z:.3f} F{int(self.z_feedrate_mm_min)}",
                    f"G0 X{sweep_x:.3f} Y{self.front_y_mm:.3f} F{int(self.sweep_feedrate_mm_min)}",
                    f"G0 Y{self.rear_y_mm:.3f} F{int(self.sweep_feedrate_mm_min)}",
                ]
            )
        if self.enable_full_bed_sweep:
            tail_lines.extend(self._full_bed_sweep_lines())
        tail_lines.extend(["M400", "; atr.bambu.autoejection.end"])
        tail = "\n".join(tail_lines)
        return self._insert_before_end_commands(gcode_text, tail)

    def _insert_before_end_commands(self, gcode_text: str, tail: str) -> str:
        lines = gcode_text.splitlines()
        insert_at = len(lines)
        last_extrusion = _last_extrusion_line_index(lines)
        search_start = last_extrusion + 1 if last_extrusion is not None else 0
        for index, line in enumerate(lines[search_start:], start=search_start):
            if re.search(r"^\s*M84\b", line, re.IGNORECASE):
                insert_at = index
                break
        else:
            for index, line in enumerate(lines[search_start:], start=search_start):
                if _END_COMMAND_RE.search(line):
                    insert_at = index
                    break
        patched_lines = [*lines[:insert_at], tail, *lines[insert_at:]]
        return "\n".join(patched_lines).rstrip() + "\n"

    def _safe_approach_z(self, object_bounds: dict[str, float | None]) -> float:
        object_top = object_bounds.get("max_z")
        collision_clear_z = float(object_top) + 2.0 if isinstance(object_top, (int, float)) else 0.0
        return min(float(self.validator.build_envelope_mm[2]), max(float(self.safe_z_mm), collision_clear_z))

    def _sweep_x_for_position(self, position: str, object_bounds: dict[str, float | None]) -> float:
        clean = str(position or "center").strip().lower()
        center_x = object_bounds.get("center_x_mm")
        if isinstance(center_x, (int, float)):
            return max(12.0, min(244.0, float(center_x)))
        min_x = object_bounds.get("min_x")
        max_x = object_bounds.get("max_x")
        if isinstance(min_x, (int, float)) and isinstance(max_x, (int, float)):
            center = (float(min_x) + float(max_x)) / 2.0
            return max(12.0, min(244.0, center))
        if clean == "left":
            return 48.0
        if clean == "right":
            return 208.0
        return 128.0

    def _sweep_heights(self, object_bounds: dict[str, float | None]) -> list[tuple[float, float]]:
        max_z = object_bounds.get("max_z")
        if not isinstance(max_z, (int, float)) or float(max_z) <= 0:
            return [(1.0, float(self.min_absolute_push_z_mm))]
        object_height = float(max_z)
        offset_height = max(float(self.min_absolute_push_z_mm), object_height - float(self.z_push_offset_mm))
        return [(1.0, offset_height)]

    def _full_bed_sweep_lines(self) -> list[str]:
        xs = [32.0, 64.0, 96.0, 128.0, 160.0, 192.0, 224.0]
        feedrate = int(self.full_bed_sweep_feedrate_mm_min)
        lines = ["; atr_full_bed_sweep_start", f"G0 Z{float(self.sweep_z_mm):.3f} F{int(self.z_feedrate_mm_min)}"]
        for index, x in enumerate(xs, start=1):
            lines.extend(
                [
                    f"; atr_full_bed_sweep_pass={index}",
                    f"G0 X{x:.3f} Y{self.rear_y_mm:.3f} F{feedrate}",
                    f"G0 X{x:.3f} Y{self.front_y_mm:.3f} F{feedrate}",
                    f"G0 Y{self.rear_y_mm:.3f} F{feedrate}",
                ]
            )
        lines.append("; atr_full_bed_sweep_end")
        return lines

    def _standalone_bounds_for_position(self, position: str, size: list[float]) -> dict[str, float]:
        sx = max(1.0, min(float(size[0]) if len(size) > 0 else 30.0, 120.0))
        sy = max(1.0, min(float(size[1]) if len(size) > 1 else 30.0, 120.0))
        sz = max(1.0, min(float(size[2]) if len(size) > 2 else 20.0, 200.0))
        clean = str(position or "center").strip().lower()
        centers = {
            "left": 48.0,
            "center": DEFAULT_BUILD_ENVELOPE_MM[0] / 2.0,
            "right": 208.0,
        }
        cx = centers.get(clean, DEFAULT_BUILD_ENVELOPE_MM[0] / 2.0)
        cy = (float(self.front_y_mm) + float(self.rear_y_mm)) / 2.0
        cx = max(12.0 + sx / 2.0, min(DEFAULT_BUILD_ENVELOPE_MM[0] - 12.0 - sx / 2.0, cx))
        cy = max(12.0 + sy / 2.0, min(DEFAULT_BUILD_ENVELOPE_MM[1] - 12.0 - sy / 2.0, cy))
        return {
            "x_min_mm": round(cx - sx / 2.0, 4),
            "x_max_mm": round(cx + sx / 2.0, 4),
            "y_min_mm": round(cy - sy / 2.0, 4),
            "y_max_mm": round(cy + sy / 2.0, 4),
            "z_min_mm": 0.0,
            "z_max_mm": round(sz, 4),
        }

    @staticmethod
    def _comment_bounds_payload(bounds: dict[str, Any]) -> dict[str, float]:
        return {
            "x_min_mm": round(float(bounds["min_x"]), 4),
            "x_max_mm": round(float(bounds["max_x"]), 4),
            "y_min_mm": round(float(bounds["min_y"]), 4),
            "y_max_mm": round(float(bounds["max_y"]), 4),
            "z_min_mm": round(float(bounds.get("min_z") or 0.0), 4),
            "z_max_mm": round(float(bounds["max_z"]), 4),
        }

    def _object_center_from_bounds(self, object_bounds: dict[str, Any]) -> list[float | None]:
        center_x = object_bounds.get("center_x_mm")
        center_y = object_bounds.get("center_y_mm")
        center_z = object_bounds.get("center_z_mm")
        return [
            round(float(center_x), 4) if isinstance(center_x, (int, float)) else None,
            round(float(center_y), 4) if isinstance(center_y, (int, float)) else None,
            round(float(center_z), 4) if isinstance(center_z, (int, float)) else None,
        ]

    def _result(
        self,
        *,
        source_path: Path,
        patched_path: Path,
        original_gcode: str,
        patched_gcode: str,
        source_plate_path: str,
        plate_id: int | None,
        loop_index: int,
        specimen_id: str,
        position: str,
    ) -> dict[str, Any]:
        post_write_validation = self._validate_written_artifact(
            patched_path,
            source_plate_path=source_plate_path,
        )
        validation = post_write_validation.get("tail_validation", {})
        post_write_ok = bool(post_write_validation.get("ok"))
        result = {
            "ok": bool(validation.get("ok") and post_write_ok),
            "tool": "printer.bambu.autoejection_patch",
            "schema": "bambu_autoejection_patch.v1",
            "status": "patched_validated" if validation.get("ok") and post_write_ok else "blocked",
            "source_path": str(source_path),
            "patched_artifact_path": str(patched_path),
            "source_plate_path": source_plate_path,
            "plate_id": plate_id,
            "loop_index": int(loop_index),
            "specimen_id": specimen_id,
            "position": position,
            "source_sha256": _sha256_bytes(source_path.read_bytes()),
            "patched_sha256": str(post_write_validation.get("artifact_sha256") or ""),
            "size_bytes": patched_path.stat().st_size,
            "object_bounds_mm": extract_object_bounds_mm(original_gcode),
            "validation": validation,
            "post_write_validation": post_write_validation,
            "blockers": [
                *list(validation.get("blockers", [])),
                *([] if post_write_ok else [str(post_write_validation.get("failure_code") or "BAMBU_AUTOEJECTION_POST_WRITE_VALIDATION_FAILED")]),
            ],
            "created_at": _utc_now(),
            "will_publish": False,
            "start_enabled": False,
        }
        result["manifest_path"] = str(self._write_manifest(patched_path, result))
        return result

    def _validate_written_artifact(self, artifact_path: Path, *, source_plate_path: str) -> dict[str, Any]:
        base: dict[str, Any] = {
            "schema": "bambu_autoejection_post_write_validation.v1",
            "artifact_path": str(artifact_path),
            "source_plate_path": source_plate_path,
            "reopened": False,
            "plate_path_matches": False,
            "md5_matches": None,
            "artifact_sha256": "",
        }
        try:
            artifact_bytes = artifact_path.read_bytes()
            if source_plate_path.startswith("Metadata/plate_"):
                md5_path = f"{source_plate_path}.md5"
                with zipfile.ZipFile(artifact_path) as archive:
                    names = set(archive.namelist())
                    if source_plate_path not in names:
                        return {
                            **base,
                            "failure_code": "BAMBU_AUTOEJECTION_POST_WRITE_PLATE_MISSING",
                            "available_plate_paths": sorted(
                                name for name in names if re.fullmatch(r"Metadata/plate_\d+\.gcode", name)
                            ),
                        }
                    written_gcode_bytes = archive.read(source_plate_path)
                    written_gcode = written_gcode_bytes.decode("utf-8")
                    md5_matches = bool(
                        md5_path in names
                        and archive.read(md5_path).decode("utf-8", errors="replace").strip().lower()
                        == hashlib.md5(written_gcode_bytes).hexdigest()
                    )
                plate_path_matches = True
            else:
                written_gcode = artifact_bytes.decode("utf-8")
                md5_matches = None
                plate_path_matches = True
            tail_validation = self.validator.validate(written_gcode, source_plate_path=source_plate_path)
            md5_ok = md5_matches is not False
            ok = bool(plate_path_matches and md5_ok and tail_validation.get("ok"))
            return {
                **base,
                "ok": ok,
                "failure_code": "" if ok else "BAMBU_AUTOEJECTION_POST_WRITE_VALIDATION_FAILED",
                "reopened": True,
                "plate_path_matches": plate_path_matches,
                "md5_matches": md5_matches,
                "artifact_sha256": _sha256_bytes(artifact_bytes),
                "tail_validation": tail_validation,
            }
        except (OSError, UnicodeDecodeError, zipfile.BadZipFile, KeyError) as exc:
            return {
                **base,
                "ok": False,
                "failure_code": "BAMBU_AUTOEJECTION_POST_WRITE_READ_FAILED",
                "message": str(exc),
            }

    def _write_manifest(self, artifact_path: Path, payload: dict[str, Any]) -> Path:
        manifest_path = Path(f"{artifact_path}.manifest.json")
        manifest = {
            **payload,
            "schema": "bambu_autoejection_artifact_manifest.v1",
            "artifact_schema": payload.get("schema", ""),
            "manifest_created_at": _utc_now(),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return manifest_path

    def _blocked(self, failure_code: str, **extra: Any) -> dict[str, Any]:
        tool = str(extra.pop("tool", "printer.bambu.autoejection_patch"))
        return {
            "ok": False,
            "tool": tool,
            "status": "blocked",
            "failure_code": failure_code,
            "blockers": [failure_code],
            "will_publish": False,
            "start_enabled": False,
            **extra,
        }
