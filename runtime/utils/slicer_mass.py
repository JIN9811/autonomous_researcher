"""Read slicer-reported mass for the selected plate, without operating a printer."""
import math
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree


def positive_mass(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def _header_mass(stream):
    header = stream.read(256 * 1024).decode("utf-8", errors="replace")
    match = re.search(r";\s*(?:total\s+)?filament (?:weight|used)\s*\[g\]\s*[:=]\s*([^\r\n]+)", header, re.I)
    if not match:
        return None
    values = [positive_mass(part.strip()) for part in match[1].split(",")]
    return sum(values) if values and all(value is not None for value in values) else None


def sliced_mass_grams(path, plate_index=1):
    """Prefer selected-plate metadata; support bounded G-code header fallback."""
    try:
        path = Path(path)
        plate_index = int(plate_index)
        if plate_index < 1:
            return None
        if path.suffix.lower() == ".3mf":
            with zipfile.ZipFile(path) as archive:
                try:
                    with archive.open("Metadata/slice_info.config") as stream:
                        data = stream.read(1024 * 1024 + 1)
                    if len(data) <= 1024 * 1024:
                        root = ElementTree.fromstring(data)
                        for plate in root.findall("plate"):
                            metadata = {item.get("key"): item.get("value") for item in plate.findall("metadata")}
                            if str(metadata.get("index")) == str(plate_index):
                                mass = positive_mass(metadata.get("weight"))
                                if mass is not None:
                                    return mass
                except (KeyError, ElementTree.ParseError):
                    pass
                with archive.open(f"Metadata/plate_{plate_index}.gcode") as stream:
                    return _header_mass(stream)
        if path.suffix.lower() in {".gcode", ".gco"}:
            with path.open("rb") as stream:
                return _header_mass(stream)
    except (OSError, TypeError, ValueError, KeyError, zipfile.BadZipFile):
        pass
    return None


def slicer_mass_evidence(payload):
    """Resolve mass only from the caller-selected specimen's slicer evidence."""
    payload = payload if isinstance(payload, dict) else {}
    tool = payload.get("tool_result")
    tool = tool if isinstance(tool, dict) else {}
    slicer = payload.get("slicer_result") or tool.get("slicer_result") or {}
    slicer = slicer if isinstance(slicer, dict) else {}
    path = slicer.get("sliced_artifact_path") or payload.get("sliced_path") or tool.get("sliced_path")
    mass = positive_mass(slicer.get("estimated_mass_g")) if slicer.get("ok") is not False else None
    plate = slicer.get("plate_index") or payload.get("plate_index") or tool.get("plate_index") or 1
    if mass is None and path and slicer.get("ok") is not False:
        mass = sliced_mass_grams(path, plate)
    return {"mass_g": mass, "source": "slicer" if mass is not None else "unavailable",
            "artifact_path": str(path or ""), "plate_index": plate, "estimated": True}
