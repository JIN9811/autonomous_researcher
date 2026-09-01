"""Canonical parsing and signal validation for UTM CSV artifacts."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import Path
from typing import Any


_REQUIRED_ROLES = ("time_s", "force_N", "displacement_mm")


def _decode_csv(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding), "utf-8" if encoding == "utf-8-sig" else encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replacement"


def _clean(value: Any) -> str:
    return str(value or "").strip().strip("\ufeff")


def _canonical_role(name: str, unit: str) -> str:
    compact = re.sub(r"[\s_()\[\]-]+", "", name).casefold()
    unit_compact = re.sub(r"\s+", "", unit).casefold()
    if compact in {"times", "time", "elapsedtime", "시간"} and unit_compact in {"", "s", "sec", "second", "seconds"}:
        return "time_s"
    if compact in {"forcen", "force", "load", "하중"} and unit_compact in {"", "n", "newton", "newtons"}:
        return "force_N"
    if compact in {"displacementmm", "displacement", "stroke", "스트로크"} and unit_compact in {"", "mm"}:
        return "displacement_mm"
    if compact in {"heightmm", "height", "높이"} and unit_compact in {"", "mm"}:
        return "height_mm"
    return ""


def _find_header(rows: list[list[str]]) -> tuple[int, list[str], list[str], dict[str, int], str]:
    for row_index, row in enumerate(rows[:8]):
        headers = [_clean(item) for item in row]
        if all(role in headers for role in _REQUIRED_ROLES):
            indexes = {role: headers.index(role) for role in _REQUIRED_ROLES}
            if "height_mm" in headers:
                indexes["height_mm"] = headers.index("height_mm")
            return row_index + 1, headers, [], indexes, "canonical"
        if row_index == 0 and any(role in headers for role in _REQUIRED_ROLES):
            indexes = {role: headers.index(role) for role in (*_REQUIRED_ROLES, "height_mm") if role in headers}
            return 1, headers, [], indexes, "canonical"
        units = [_clean(item) for item in rows[row_index + 1]] if row_index + 1 < len(rows) else []
        role_indexes: dict[str, int] = {}
        for index, header in enumerate(headers):
            unit = units[index] if index < len(units) else ""
            role = _canonical_role(header, unit)
            if role and role not in role_indexes:
                role_indexes[role] = index
        if all(role in role_indexes for role in _REQUIRED_ROLES):
            return row_index + 2, headers, units, role_indexes, "trapeziumx_raw"
    return 0, [_clean(item) for item in rows[0]] if rows else [], [], {}, "unknown"


def probe_utm_csv_bytes(data: bytes) -> dict[str, Any]:
    """Parse canonical or TRAPEZIUM CSV bytes without modifying the source."""
    text, encoding = _decode_csv(data)
    rows = [[_clean(cell) for cell in row] for row in csv.reader(io.StringIO(text)) if any(_clean(cell) for cell in row)]
    data_start, source_columns, units, indexes, source_format = _find_header(rows)
    missing = sorted(role for role in _REQUIRED_ROLES if role not in indexes)
    canonical_columns = [role for role, _ in sorted(indexes.items(), key=lambda item: item[1])]
    numeric_rows: list[dict[str, float]] = []
    invalid_numeric_rows = 0
    if not missing:
        for row in rows[data_start:]:
            try:
                numeric_rows.append({role: float(row[indexes[role]]) for role in indexes})
            except (IndexError, TypeError, ValueError):
                invalid_numeric_rows += 1

    quality: dict[str, Any] = {
        "numeric_row_count": len(numeric_rows),
        "invalid_numeric_row_count": invalid_numeric_rows,
        "raw_csv_preserved": True,
        "required_columns_present": not missing,
    }
    failure_code: str | None = None
    message = ""
    if missing:
        failure_code = "UTM_DATA_PARSE_FAILED"
        message = f"Missing UTM columns: {', '.join(missing)}"
    elif len(numeric_rows) < 2:
        failure_code = "UTM_DATA_PARSE_FAILED"
        message = "UTM export must contain at least two numeric data rows."
    else:
        eps = 1e-9
        times = [row["time_s"] for row in numeric_rows]
        displacements = [row["displacement_mm"] for row in numeric_rows]
        forces = [row["force_N"] for row in numeric_rows]
        time_monotonic = all((right - left) >= -eps for left, right in zip(times, times[1:]))
        displacement_increasing = all((right - left) >= -eps for left, right in zip(displacements, displacements[1:]))
        displacement_decreasing = all((right - left) <= eps for left, right in zip(displacements, displacements[1:]))
        displacement_monotonic = displacement_increasing or displacement_decreasing
        displacement_range = max(displacements) - min(displacements)
        force_range = max(forces) - min(forces)
        force_nonzero = any(abs(value) > eps for value in forces)
        quality.update(
            {
                "time_monotonic_non_decreasing": time_monotonic,
                "time_monotonic": time_monotonic,
                "time_min_s": min(times),
                "time_max_s": max(times),
                "displacement_changes": displacement_range > eps,
                "displacement_signal_present": displacement_range > eps,
                "displacement_monotonic": displacement_monotonic,
                "displacement_direction": "increasing" if displacement_increasing else "decreasing" if displacement_decreasing else "mixed",
                "displacement_range_mm": displacement_range,
                "displacement_min_mm": min(displacements),
                "displacement_max_mm": max(displacements),
                "force_nonzero": force_nonzero,
                "force_changes": force_range > eps,
                "force_signal_present": force_nonzero and force_range > eps,
                "force_range_N": force_range,
                "force_min_N": min(forces),
                "force_max_N": max(forces),
            }
        )
        if not time_monotonic:
            failure_code = "UTM_DATA_NON_MONOTONIC_TIME"
            message = "UTM time_s values are not monotonic non-decreasing."
        elif displacement_range <= eps:
            failure_code = "UTM_DATA_NO_DISPLACEMENT_SIGNAL"
            message = "UTM displacement_mm does not change across samples."
        elif not displacement_monotonic:
            failure_code = "UTM_DATA_NON_MONOTONIC_DISPLACEMENT"
            message = "UTM displacement_mm is not monotonic in either direction."
        elif not force_nonzero or force_range <= eps:
            failure_code = "UTM_DATA_NO_FORCE_SIGNAL"
            message = "UTM force_N has no nonzero changing load signal."

    result: dict[str, Any] = {
        "ok": failure_code is None,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "source_format": source_format,
        "encoding": encoding,
        "row_count_probe": len(numeric_rows) if not missing else max(0, len(rows) - 1),
        "columns_probe": canonical_columns,
        "source_columns": source_columns,
        "units": units,
        "column_mapping": {source_columns[index]: role for role, index in indexes.items() if index < len(source_columns)},
        "missing_columns": missing,
        "data_quality": quality,
        "failure_code": failure_code,
        "message": message,
    }
    return result


def probe_utm_csv(path: Path) -> dict[str, Any]:
    """Probe a UTM CSV file and include its resolved path in the result."""
    if not path.exists() or not path.is_file():
        return {"ok": False, "failure_code": "UTM_EXPORT_FILE_MISSING", "path": str(path)}
    result = probe_utm_csv_bytes(path.read_bytes())
    result["path"] = str(path)
    return result
