"""
Deterministic Bambu Lab G-code autoejection artifact patching.

This module is intentionally pure-file logic: it never talks to a printer and
never starts motion. Live publish gates stay in the device bridge/API layer.
"""

from __future__ import annotations

import hashlib
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
_AXIS_RE = re.compile(r"\b([XYZ])\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_FEEDRATE_RE = re.compile(r"\bF\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_OBJECT_COUNT_RE = re.compile(r"^\s*;\s*total\s+object\s+count\s*:\s*(\d+)\s*$", re.IGNORECASE)
_OBJECT_MARKER_RE = re.compile(r"^\s*;\s*(?:object|start\s+printing\s+object)\s*:", re.IGNORECASE)
_RESIDUE_RE = re.compile(r"^\s*;\s*(?:FEATURE|TYPE)\s*:\s*(?:skirt|brim|raft)\b", re.IGNORECASE)
_COOLDOWN_WAIT_RE = re.compile(r"^\s*M190\b.*\b[RS]\s*-?\d+", re.IGNORECASE)
_COOLDOWN_POLICY_RE = re.compile(r"^\s*;\s*atr_(?:cooldown_wait_policy|bed_cooldown_c)\s*=", re.IGNORECASE)


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


def extract_object_bounds_mm(gcode_text: str) -> dict[str, float | None]:
    """Extract conservative XYZ bounds from G0/G1 lines in a sliced G-code body."""
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for line in gcode_text.splitlines():
        if not _MOTION_RE.search(line):
            continue
        coords = _extract_axis_positions(line)
        if "X" in coords:
            xs.append(coords["X"])
        if "Y" in coords:
            ys.append(coords["Y"])
        if "Z" in coords:
            zs.append(coords["Z"])
    return {
        "min_x": min(xs) if xs else None,
        "max_x": max(xs) if xs else None,
        "min_y": min(ys) if ys else None,
        "max_y": max(ys) if ys else None,
        "min_z": min(zs) if zs else None,
        "max_z": max(zs) if zs else None,
    }


@dataclass(slots=True)
class BambuGcodeAutoejectionValidator:
    """Validate Bambu autoejection-tail invariants before any publish path."""

    build_envelope_mm: tuple[float, float, float] = DEFAULT_BUILD_ENVELOPE_MM
    min_object_height_mm: float = 5.0
    max_object_height_mm: float = 200.0
    max_xy_ejection_feedrate_mm_min: float = 1000.0

    def validate(self, gcode_text: str, *, source_plate_path: str = "plain_gcode") -> dict[str, Any]:
        blockers: list[str] = []
        marker_count = gcode_text.count(SCHEMA_MARKER)
        print_body = self._print_body_before_tail(gcode_text)
        object_bounds = extract_object_bounds_mm(print_body)
        if marker_count == 0:
            blockers.append("BAMBU_AUTOEJECTION_TAIL_MISSING")
        if marker_count > 1:
            blockers.append("BAMBU_AUTOEJECTION_TAIL_DUPLICATED")
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
    z_push_offset_mm: float = 30.0
    front_y_mm: float = 8.0
    rear_y_mm: float = 245.0
    push_lane_offset_mm: float = 30.0
    sweep_feedrate_mm_min: int = 300
    enable_full_bed_sweep: bool = False
    sweep_z_mm: float = 1.0
    full_bed_sweep_feedrate_mm_min: int = 300

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
    ) -> dict[str, Any]:
        """Generate a validation-only Bambu ejection G-code job with no print body."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(specimen_id or "").strip())
        safe_id = safe_id.strip("._-") or "standalone-ejection-test"
        size = object_size_mm or [30.0, 30.0, 20.0]
        body = "\n".join(
            [
                "; ATR standalone Bambu autoejection validation job",
                "G90",
                f"; atr_assumed_object_size_mm={json.dumps([float(item) for item in size])}",
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
            archive.writestr("3D/3dmodel.model", "<model />")
        validation = self.validator.validate(patched, source_plate_path="standalone_gcode_job")
        result = {
            "ok": bool(validation.get("ok")),
            "tool": "printer.bambu.autoejection_standalone",
            "schema": "bambu_autoejection_standalone.v1",
            "status": "standalone_validated" if validation.get("ok") else "blocked",
            "patched_artifact_path": str(out_path),
            "startable_artifact_path": str(startable_path),
            "startable_plate_path": startable_plate_path,
            "source_plate_path": "standalone_gcode_job",
            "plate_id": 1,
            "loop_index": 1,
            "specimen_id": safe_id,
            "position": position,
            "object_size_mm": [float(item) for item in size],
            "patched_sha256": _sha256_bytes(out_path.read_bytes()),
            "startable_sha256": _sha256_bytes(startable_path.read_bytes()),
            "size_bytes": out_path.stat().st_size,
            "startable_size_bytes": startable_path.stat().st_size,
            "validation": validation,
            "blockers": validation.get("blockers", []),
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
        tail_lines = [
            f"; {SCHEMA_MARKER}",
            f"; atr_source_sha256={source_sha256}",
            f"; atr_source_plate_path={source_plate_path}",
            f"; atr_plate_id={plate_id if plate_id is not None else 'none'}",
            f"; atr_loop_index={int(loop_index)}",
            f"; atr_specimen_id={specimen_id or 'unknown'}",
            f"; atr_position={position}",
            f"; atr_object_bounds_mm={json.dumps(object_bounds, sort_keys=True)}",
            f"; atr_object_height_mm={float(object_height):.3f}" if isinstance(object_height, (int, float)) else "; atr_object_height_mm=unknown",
            "; atr_material_type=unknown",
            "; atr_bed_surface=unknown",
            f"; atr_bed_cooldown_c={int(self.bed_cooldown_c)}",
            "; atr_cooldown_wait_policy=M190",
            "; atr_purge_parking_strategy=preserve_slicer_end_gcode_then_eject",
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
            f"G0 Z{self.safe_z_mm:.3f} F1200",
        ]
        for fraction, sweep_z in self._sweep_heights(object_bounds):
            tail_lines.extend(
                [
                    f"; atr_sweep_height_fraction={fraction:.2f}",
                    f"G0 Z{sweep_z:.3f} F1200",
                    f"G0 X{sweep_x:.3f} Y{self.rear_y_mm:.3f} F{int(self.sweep_feedrate_mm_min)}",
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
        for index, line in enumerate(lines):
            if re.search(r"^\s*M84\b", line, re.IGNORECASE):
                insert_at = index
                break
        else:
            for index, line in enumerate(lines):
                if _END_COMMAND_RE.search(line):
                    insert_at = index
                    break
        patched_lines = [*lines[:insert_at], tail, *lines[insert_at:]]
        return "\n".join(patched_lines).rstrip() + "\n"

    def _sweep_x_for_position(self, position: str, object_bounds: dict[str, float | None]) -> float:
        clean = str(position or "center").strip().lower()
        min_x = object_bounds.get("min_x")
        max_x = object_bounds.get("max_x")
        if isinstance(min_x, (int, float)) and isinstance(max_x, (int, float)):
            center = (float(min_x) + float(max_x)) / 2.0
            if clean == "left":
                center -= float(self.push_lane_offset_mm)
            elif clean == "right":
                center += float(self.push_lane_offset_mm)
            return max(12.0, min(244.0, center))
        if clean == "left":
            return 48.0
        if clean == "right":
            return 208.0
        return 128.0

    def _sweep_heights(self, object_bounds: dict[str, float | None]) -> list[tuple[float, float]]:
        max_z = object_bounds.get("max_z")
        if not isinstance(max_z, (int, float)) or float(max_z) <= 0:
            return [(1.0, float(self.safe_z_mm))]
        object_height = float(max_z)
        offset_height = max(1.0, min(float(self.safe_z_mm), object_height - float(self.z_push_offset_mm)))
        heights = [(0.0, offset_height)]
        fractions = [0.9, 0.6, 0.4, 0.2]
        heights.extend(
            (fraction, max(1.0, min(float(self.safe_z_mm), object_height * fraction)))
            for fraction in fractions
        )
        deduped: list[tuple[float, float]] = []
        seen: set[float] = set()
        for fraction, height in heights:
            rounded = round(height, 3)
            if rounded in seen:
                continue
            seen.add(rounded)
            deduped.append((fraction, height))
        return deduped

    def _full_bed_sweep_lines(self) -> list[str]:
        xs = [32.0, 64.0, 96.0, 128.0, 160.0, 192.0, 224.0]
        feedrate = int(self.full_bed_sweep_feedrate_mm_min)
        lines = ["; atr_full_bed_sweep_start", f"G0 Z{float(self.sweep_z_mm):.3f} F1200"]
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
        validation = self.validator.validate(patched_gcode, source_plate_path=source_plate_path)
        result = {
            "ok": bool(validation.get("ok")),
            "tool": "printer.bambu.autoejection_patch",
            "schema": "bambu_autoejection_patch.v1",
            "status": "patched_validated" if validation.get("ok") else "blocked",
            "source_path": str(source_path),
            "patched_artifact_path": str(patched_path),
            "source_plate_path": source_plate_path,
            "plate_id": plate_id,
            "loop_index": int(loop_index),
            "specimen_id": specimen_id,
            "position": position,
            "source_sha256": _sha256_bytes(source_path.read_bytes()),
            "patched_sha256": _sha256_bytes(patched_path.read_bytes()),
            "size_bytes": patched_path.stat().st_size,
            "object_bounds_mm": extract_object_bounds_mm(original_gcode),
            "validation": validation,
            "blockers": validation.get("blockers", []),
            "created_at": _utc_now(),
            "will_publish": False,
            "start_enabled": False,
        }
        result["manifest_path"] = str(self._write_manifest(patched_path, result))
        return result

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
