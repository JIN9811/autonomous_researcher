"""Bounded, verbatim last-complete-frame selection from large ASCII FRD files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from utils.calculix_fields import _FieldError, _parse_frd_header


def select_last_complete_frame(source: Path, destination: Path, *, max_bytes: int) -> dict[str, Any]:
    """Scan with constant-size records; retain offsets, never whole field histories.

    A selectable frame has closed DISP/STRESS blocks at the same step/increment/
    time, with their declared node counts. The normal strict field converter
    still validates node identities, components, topology, and finite values.
    """
    digest = hashlib.sha256()
    prefix_end = None
    pending_start = None
    pending_step = None
    active = None
    current_key = None
    blocks: dict[str, tuple[int, int]] = {}
    last: dict[str, tuple[int, int]] = {}
    last_key = None
    complete_count = 0

    def finish_frame() -> None:
        nonlocal last, last_key, complete_count
        if {"DISP", "STRESS"} <= blocks.keys():
            last, last_key = dict(blocks), current_key
            complete_count += 1

    with source.open("rb") as stream:
        while True:
            start = stream.tell()
            raw = stream.readline(1024 * 1024 + 1)
            if not raw:
                break
            if len(raw) > 1024 * 1024:
                raise _FieldError("CALCULIX_FIELD_BUDGET_EXCEEDED", {"record_byte_limit": 1024 * 1024})
            digest.update(raw)
            try:
                line = raw.decode("ascii")
            except UnicodeDecodeError as exc:
                raise _FieldError("CALCULIX_FIELD_FRD_NOT_ASCII", {}) from exc
            if "\x00" in line:
                raise _FieldError("CALCULIX_FIELD_BINARY_FRD_UNSUPPORTED", {})
            tokens = line.split()
            if not tokens:
                continue
            if tokens[0] == "1PSTEP":
                if prefix_end is None:
                    prefix_end = start
                pending_start = start
                try:
                    pending_step = (int(tokens[2]), int(tokens[3]))
                except (ValueError, IndexError):
                    pending_step = None
                active = None
            elif len(line) >= 6 and line[2:6] == "100C":
                try:
                    value, _, nodes = _parse_frd_header(line.rstrip("\r\n"))
                except _FieldError:
                    active = None
                    continue  # An interrupted trailing dataset is not a complete frame.
                if pending_start is None or pending_step is None:
                    active = None
                    continue
                key = (value, *pending_step)
                if key != current_key:
                    finish_frame()
                    blocks = {}
                    current_key = key
                active = {"start": pending_start, "name": "", "nodes": nodes, "rows": 0}
                pending_start = None
            elif active is not None:
                if tokens[0] == "-4" and len(tokens) > 1:
                    active["name"] = tokens[1].upper()
                elif tokens[0] == "-1":
                    active["rows"] += 1
                elif tokens[0] == "-3":
                    if active["name"] in {"DISP", "STRESS", "PE", "PEEQ"} and active["rows"] == active["nodes"]:
                        blocks[active["name"]] = (active["start"], stream.tell())
                    active = None
        finish_frame()
        if not last or last_key is None or prefix_end is None:
            raise _FieldError("CALCULIX_FIELD_COMPLETE_FRAME_REQUIRED", {})
        spans = [(0, prefix_end), *sorted(last.values())]
        selected_bytes = sum(end - start for start, end in spans) + len(b" 9999\n")
        if selected_bytes > max_bytes:
            raise _FieldError("CALCULIX_FIELD_BUDGET_EXCEEDED", {"selected_frame_bytes": selected_bytes, "byte_limit": max_bytes})
        with destination.open("wb") as output:
            for start, end in spans:
                stream.seek(start)
                remaining = end - start
                while remaining:
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise _FieldError("CALCULIX_FIELD_IO_FAILED", {"reason": "source_changed_during_selection"})
                    output.write(chunk)
                    remaining -= len(chunk)
            output.write(b" 9999\n")
    metadata = {"schema": "cae_field_selection.v1", "source": str(source),
                "source_sha256": digest.hexdigest(), "selected_frd_path": str(destination),
                "method": "verbatim_last_complete_displacement_stress_frame", "full_history": False,
                "selected_value": last_key[0], "selected_increment": last_key[1], "selected_step": last_key[2],
                "complete_frame_count": complete_count, "selected_bytes": selected_bytes,
                "selected_datasets": sorted(last), "byte_limit": max_bytes}
    metadata_path = destination.with_suffix(".selection.json")
    metadata["selection_path"] = str(metadata_path)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata
