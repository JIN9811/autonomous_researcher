"""Read the selected sliced artifact's duration; never use a design proxy as a slicer estimate."""
import math
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def sliced_duration_seconds(path, plate_index=1):
    """Bounded reads of Bambu plate metadata or a plain G-code header."""
    try:
        path = Path(path)
        if path.suffix.lower() == ".3mf":
            with zipfile.ZipFile(path) as archive:
                with archive.open("Metadata/slice_info.config") as stream:
                    data = stream.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    return None
                root = ElementTree.fromstring(data)
                for plate in root.findall("plate"):
                    values = {item.get("key"): item.get("value") for item in plate.findall("metadata")}
                    if str(values.get("index")) == str(plate_index):
                        return positive(values.get("prediction"))
            return None
        if path.suffix.lower() in {".gcode", ".gco"}:
            with path.open("rb") as stream:
                header = stream.read(256 * 1024).decode("utf-8", errors="replace")
            match = re.search(r";\s*estimated printing time \(normal mode\)\s*=\s*([^\r\n]+)", header)
            if match:
                units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
                return positive(sum(float(n) * units[u] for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", match[1])))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        pass
    return None


def slicer_duration_evidence(payload):
    """Read duration only from this specimen's slicer result, never design proxies."""
    payload = payload if isinstance(payload, dict) else {}
    tool = payload.get("tool_result")
    tool = tool if isinstance(tool, dict) else {}
    slicer = payload.get("slicer_result") or tool.get("slicer_result") or {}
    slicer = slicer if isinstance(slicer, dict) else {}
    path = slicer.get("sliced_artifact_path") or payload.get("sliced_path") or tool.get("sliced_path")
    plate = slicer.get("plate_index") or payload.get("plate_index") or tool.get("plate_index") or 1
    duration = None
    if slicer.get("ok") is not False:
        value = slicer.get("estimated_print_time_sec")
        duration = None if isinstance(value, bool) else positive(value)
        if duration is None and isinstance(path, (str, Path)) and path:
            duration = sliced_duration_seconds(path, plate)
    return {"duration_sec": duration, "duration_min": duration / 60 if duration is not None else None,
            "source": "slicer" if duration is not None else "unavailable",
            "artifact_path": str(path or ""), "plate_index": plate}


def completion_wait_timing(spec, payload):
    request = spec.get("print") or {}
    timeout = next((positive(source.get("printer_completion_timeout_sec")) for source in
                    (spec, request, payload) if positive(source.get("printer_completion_timeout_sec"))), None)
    # Keep explicit zero deadlines for tests/operator-requested immediate checks.
    if any(source.get("printer_completion_timeout_sec") == 0 for source in (spec, request, payload)):
        timeout = 0.0
    poll = next((source.get("printer_completion_poll_sec") for source in (spec, request, payload)
                 if source.get("printer_completion_poll_sec") is not None), 2.0)
    try:
        poll = min(10.0, max(0.0, float(poll)))
        if not math.isfinite(poll):
            poll = 2.0
    except (TypeError, ValueError):
        poll = 2.0
    if timeout is not None:
        return timeout, poll
    slicer = payload.get("slicer_result") or (payload.get("tool_result") or {}).get("slicer_result") or {}
    duration = positive(slicer.get("estimated_print_time_sec"))
    if duration is None:
        path = slicer.get("sliced_artifact_path") or payload.get("sliced_path")
        if path:
            duration = sliced_duration_seconds(path, request.get("plate_index") or 1)
    # Current printer ETA can exceed a slicer's estimate (preparation/speed changes).
    remaining = positive(((payload.get("device_screen") or {}).get("job") or {}).get("remaining_min"))
    if duration is not None:
        duration = max(duration, (remaining or 0) * 60)
        return duration + max(900.0, duration * 0.25), poll
    if remaining:
        return remaining * 60 + max(900.0, remaining * 60 * 0.25), poll
    # Unknown duration is not the old geometry-derived 30-minute guess.
    return 6 * 3600.0, poll
