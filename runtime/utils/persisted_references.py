"""Typed, external historical path lookups; never edit or authenticate records.

Callers authenticate original envelopes and identities before calling here, then
verify the bytes opened through the returned physical path. No lookup probes old
or new files, and no map grants authority outside the caller's explicit roots.
Source Library's inbox/extraction paths have separate native, source-ID bases;
they are deliberately not run-reference fields.
"""
from pathlib import Path, PurePosixPath
import re


_FIELDS = {
    "atr.error_run_checkpoint.v1": {
        "csv_path": "absolute", "result_path": "absolute", "planning.transcript_path": "absolute"},
    "equipment_tail_recovery.v1": {"source_path": "absolute", "evidence_hashes.keys": "absolute"},
    # These are external discriminators for known files, not new payload fields.
    "atr.bo_budget_checkpoint.v1": {"planning.transcript_path": "absolute"},
    "atr.clearance_recovery.v1": {
        "source_result": "absolute", "record.evidence.raw_frame_path": "absolute",
        "record.evidence.vision_decision.images[].path": "absolute",
        "source_result_relative": "run-relative", "bo_result_relative": "run-relative"},
}


def _identity(schema, field, run_id, kind):
    if (not all(isinstance(value, str) for value in (schema, field, run_id, kind))
            or schema not in _FIELDS or _FIELDS[schema].get(field) != kind
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,191}", run_id)):
        raise ValueError("Unsupported historical schema, field, kind or run identity")


def _path(value, *, absolute):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(ord(c) < 32 for c in value)):
        raise ValueError("Invalid persisted reference path")
    path = PurePosixPath(value)
    parts = value.split("/")[1:] if absolute else value.split("/")
    if (path.is_absolute() != absolute or any(p in {"", ".", ".."} for p in parts)
            or path.as_posix() != value):
        raise ValueError("Persisted reference must be a canonical typed path")
    return Path(value)


def resolve_persisted_reference(value: str, *, schema: str, field: str, run_id: str,
                                reference_kind: str, allowed_roots: tuple[Path, ...],
                                relocation_map: dict) -> Path:
    """Resolve component prefixes scoped to this exact record/field/run/kind.

    Map format: {schema: 'atr.persisted_reference_map.v1', entries: [
      {schema, field, run_id, reference_kind, source, target}]}. Targets are
    absolute physical paths. Relative fields use exactly one supplied base.
    Empty {} is identity. Duplicate/overlapping matching entries fail closed.
    """
    _identity(schema, field, run_id, reference_kind)
    relative = reference_kind != "absolute"
    source = _path(value, absolute=not relative)
    if not isinstance(allowed_roots, tuple) or not allowed_roots or (relative and len(allowed_roots) != 1):
        raise ValueError("Explicit physical roots (one base for relative fields) required")
    roots = tuple(_path(str(root), absolute=True).resolve() for root in allowed_roots)
    if not isinstance(relocation_map, dict):
        raise ValueError("Historical relocation map must be an object")
    if relocation_map:
        if (set(relocation_map) != {"schema", "entries"}
                or relocation_map["schema"] != "atr.persisted_reference_map.v1"
                or not isinstance(relocation_map["entries"], list)):
            raise ValueError("Invalid historical relocation map")
    matches = []
    for entry in relocation_map.get("entries", []):
        if not isinstance(entry, dict) or set(entry) != {"schema", "field", "run_id", "reference_kind", "source", "target"}:
            raise ValueError("Invalid historical relocation entry")
        _identity(entry["schema"], entry["field"], entry["run_id"], entry["reference_kind"])
        prefix = _path(entry["source"], absolute=entry["reference_kind"] == "absolute")
        target = _path(entry["target"], absolute=True)
        if ((entry["schema"], entry["field"], entry["run_id"], entry["reference_kind"])
                == (schema, field, run_id, reference_kind) and source.is_relative_to(prefix)):
            matches.append(target / source.relative_to(prefix))
    if len(matches) > 1:
        raise ValueError("Ambiguous historical relocation map")
    physical = (matches[0] if matches else roots[0] / source if relative else source).resolve()
    if not any(physical.is_relative_to(root) for root in roots):
        raise ValueError("Historical reference escapes allowed physical roots")
    return physical


def reference_options(*, reference_roots=None, relocation_map=None):
    """Omit unset keywords to retain legacy no-context reader call contracts."""
    return {k: v for k, v in {"reference_roots": reference_roots, "relocation_map": relocation_map}.items()
            if v is not None}


def historical_reference(value, *, schema, field, run_id, reference_kind="absolute",
                         reference_roots=None, relocation_map=None, base=None):
    """Legacy identity unless context is explicitly supplied; never infer roots.

    Existing readers retain their checks for external pinned evidence. Explicit
    compatibility context opts into typed roots; a map alone is not authority.
    """
    if reference_roots is None and relocation_map is None:
        return ((Path(base) / value) if base is not None else Path(value)).resolve()
    if base is not None:
        physical_base = Path(base).resolve()
        if (not isinstance(reference_roots, tuple) or not reference_roots
                or not any(physical_base.is_relative_to(_path(str(root), absolute=True).resolve())
                           for root in reference_roots)):
            raise ValueError("Relative reference base outside explicit authority")
        reference_roots = (physical_base,)
    return resolve_persisted_reference(value, schema=schema, field=field, run_id=run_id,
        reference_kind=reference_kind, allowed_roots=reference_roots,
        relocation_map={} if relocation_map is None else relocation_map)
