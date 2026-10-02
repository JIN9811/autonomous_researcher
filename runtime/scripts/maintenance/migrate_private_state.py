"""Offline, explicit-root copy/verify/proposal tooling; never activate or resume.

All manifests are private operator inputs, not authenticated authorization. Copy
requires an explicit quiescence assertion. Failed copies are retained, never
merged, overwritten, or automatically rolled back. Only an owned temporary
hard-link name is removed after exclusive publication; source records and newer
destination records are never deleted. Use a fresh empty destination to retry.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from uuid import uuid4


SCHEMA = "atr.private_state_migration.v1"
STORES = ("run_root", "memory_root", "artifact_root", "output_root",
          "source_inbox_root", "user_file_root", "log_root")
_OVERRIDES = [
    {"field": "devices.printer.connection_memory_path", "value": "memory/printer_fleet.json",
     "repository_root": None, "decision": None},
    {"field": "devices.printer.profiles.prusa_mk4s_lab_01.connection_memory_path",
     "value": "memory/prusa_connection.json", "repository_root": None, "decision": None},
]
_DEFERRALS = [
    {"source": "docs/knowledge/manuals/sources/Indicator Manual.pdf",
     "frozen_destination": "system/knowledge/manuals/sources/Indicator Manual.pdf",
     "registry_reference": "../../../docs/knowledge/manuals/sources/Indicator Manual.pdf",
     "size": 5895087, "sha256": "2b4553da1de359681117c0a56be74d7f41db8324407f024979867bb38dd2ffaf",
     "decision": None},
    {"source": "docs/knowledge/manuals/sources/Software Manual.pdf",
     "frozen_destination": "system/knowledge/manuals/sources/Software Manual.pdf",
     "registry_reference": "../../../docs/knowledge/manuals/sources/Software Manual.pdf",
     "size": 4602565, "sha256": "d5389a0df3273d88f8f99b2449119baa93f2d194bc0f8ea8a97197b252390ad4",
     "decision": None},
]


def _canonical(value):
    if (not isinstance(value, str) or not value.startswith("/") or value == "/"
            or "\\" in value or ":" in value or any(ord(c) < 32 for c in value)
            or any(p in {"", ".", ".."} for p in value.split("/")[1:])):
        raise ValueError("Expected canonical absolute path")
    return Path(value)


@contextmanager
def _directory(path):
    """Open every component without following links, including ancestors."""
    path = Path(path)
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            info = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise ValueError(f"Symlink directory rejected: {path}")
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_fd
        yield descriptor
    finally:
        os.close(descriptor)


def _identity(info):
    return {"device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode),
            "size": info.st_size, "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
            "uid": info.st_uid, "gid": info.st_gid, "links": info.st_nlink}


@contextmanager
def _file(path):
    with _directory(path.parent) as parent:
        info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"Symlink file rejected: {path}")
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Special file rejected: {path}")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or _identity(info) != _identity(opened):
                raise ValueError(f"File changed while opening: {path}")
            yield descriptor
        finally:
            os.close(descriptor)


def _read_file(path):
    digest = hashlib.sha256()
    with _file(path) as descriptor:
        before = _identity(os.fstat(descriptor))
        while data := os.read(descriptor, 1024 * 1024):
            digest.update(data)
        if _identity(os.fstat(descriptor)) != before:
            raise ValueError(f"File changed while hashing: {path}")
    return digest.hexdigest(), before


def _scan(root, *, absent=False):
    # The selected root's parent must already exist. Never invent authority by
    # recursively creating unselected ancestors outside a named store.
    with _directory(root.parent) as parent:
        try:
            info = os.stat(root.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            if absent:
                return None
            raise
    rows = []

    def visit(path, relative, info):
        mode = info.st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlink entry rejected: {path}")
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError(f"Special file rejected: {path}")
        digest, identity = (_read_file(path) if stat.S_ISREG(mode) else (None, _identity(info)))
        rows.append({"relative_path": relative, "kind": "directory" if stat.S_ISDIR(mode) else "file",
                     "size": info.st_size if stat.S_ISREG(mode) else 0,
                     "sha256": digest, "mode": stat.S_IMODE(mode), "identity": identity})
        if stat.S_ISDIR(mode):
            with _directory(path) as descriptor:
                if _identity(os.fstat(descriptor)) != identity:
                    raise ValueError(f"Directory changed while opening: {path}")
                for name in sorted(os.listdir(descriptor)):
                    child = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    visit(path / name, name if relative == "." else relative + "/" + name, child)
                if _identity(os.fstat(descriptor)) != identity:
                    raise ValueError(f"Directory changed while reading: {path}")

    visit(root, ".", info)
    return rows


def _bindings(source, destination):
    roots = []
    for document in (source, destination):
        if (not isinstance(document, dict) or set(document) != {"schema", "stores"}
                or document["schema"] != "atr.path_bindings.v1"
                or not isinstance(document["stores"], dict) or set(document["stores"]) != set(STORES)):
            raise ValueError("Tool bindings require exactly all seven named stores")
        roots.extend(_canonical(document["stores"][name]) for name in STORES)
    for index, path in enumerate(roots):
        if any(path.is_relative_to(other) or other.is_relative_to(path) for other in roots[:index]):
            raise ValueError("Duplicate, overlapping or equal source/destination roots")
    return roots


def _entries(source, destination, snapshots):
    return [dict(store=name, relative_path=row["relative_path"],
                 source=str(Path(source["stores"][name]) / row["relative_path"]),
                 destination=str(Path(destination["stores"][name]) / row["relative_path"]),
                 kind=row["kind"], size=row["size"], sha256=row["sha256"],
                 source_mode=row["mode"], destination_mode=None, source_identity=row["identity"])
            for name in sorted(STORES) for row in snapshots[name]]


def plan_copy(source_bindings: dict, destination_bindings: dict) -> dict:
    """Inspect only explicit named stores, without writing or selecting authority."""
    _bindings(source_bindings, destination_bindings)
    source, destination, collisions = {}, {}, []
    for name in STORES:
        source[name] = _scan(Path(source_bindings["stores"][name]))
        if source[name][0]["kind"] != "directory":
            raise ValueError(f"Source store must be a directory: {name}")
        destination[name] = _scan(Path(destination_bindings["stores"][name]), absent=True)
        records = destination[name]
        if records and (len(records) > 1 or records[0]["kind"] != "directory"):
            collisions.append({"store": name, "path": destination_bindings["stores"][name],
                               "reason": "destination is populated or not a directory"})
    return dict(schema=SCHEMA, status="planned", activated=False, writers_quiescent=False,
        source_bindings=deepcopy(source_bindings), destination_bindings=deepcopy(destination_bindings),
        entries=_entries(source_bindings, destination_bindings, source), source_snapshot=source,
        destination_snapshot=destination, verified_destination_snapshot=None,
        errors=[], collisions=collisions, rollback_conflicts=[], retained_paths=[],
        reference_requests=[], compatibility_map=None, selected_bindings=None,
        selected_overrides=deepcopy(_OVERRIDES), phase_deferrals=deepcopy(_DEFERRALS),
        unresolved_authorities=[], ready_for_activation=False, resume_certified=False,
        historical_coverage="explicit-requests-only")


def _requests(manifest):
    # Reuse Task 6's schema/field/run/kind and canonical-path validator without
    # importing recovery/controllers, discovering checkpoints, or inferring IDs.
    from utils.persisted_references import resolve_persisted_reference
    rows = manifest["reference_requests"]
    if not isinstance(rows, list):
        raise ValueError("reference_requests must be a list")
    lookup = {e["source"]: e for e in manifest["entries"] if e["kind"] == "file"}
    source_run = Path(manifest["source_bindings"]["stores"]["run_root"])
    allowed = tuple(Path(p) for p in manifest["source_bindings"]["stores"].values())
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid reference request")
        relative = row.get("reference_kind") == "run-relative"
        keys = {"schema", "field", "run_id", "reference_kind", "source"}
        if set(row) != keys | ({"source_base"} if relative else set()):
            raise ValueError("Unknown or missing reference request keys")
        identity = {key: row[key] for key in ("schema", "field", "run_id", "reference_kind")}
        # Validator runs before constructing paths with possibly malformed IDs.
        roots = (source_run,) if relative else allowed
        resolve_persisted_reference(row["source"], **identity, allowed_roots=roots, relocation_map={})
        if relative:
            base = source_run / row["run_id"]
            if row["source_base"] != str(base):
                raise ValueError("Run-relative source_base must be the selected run directory")
            physical = str(base / row["source"])
        else:
            physical = row["source"]
        entry = lookup.get(physical)
        if entry is None:
            raise ValueError("Reference must name an exact copied regular file")
        # CSV and planning sessions can legitimately be outside the run's own
        # directory. Other run-scoped evidence cannot silently alias another run.
        if (entry["store"] == "run_root" and row["field"] not in {"csv_path", "planning.transcript_path"}
                and not Path(physical).is_relative_to(source_run / row["run_id"])):
            raise ValueError("Historical reference belongs to a different run")
        record = dict(identity, source=row["source"], target=entry["destination"])
        key = json.dumps(record, sort_keys=True)
        if key in seen:
            raise ValueError("Duplicate reference request")
        seen.add(key)
        result.append(record)
    return {"schema": "atr.persisted_reference_map.v1", "entries": sorted(result, key=lambda r: json.dumps(r, sort_keys=True))}


def _authority(manifest):
    overrides = manifest["selected_overrides"]
    if not isinstance(overrides, list) or len(overrides) < len(_OVERRIDES):
        raise ValueError("Known retained explicit overrides must be accounted")
    seen, unresolved = set(), []
    for row in overrides:
        if (not isinstance(row, dict) or set(row) != {"field", "value", "repository_root", "decision"}
                or not isinstance(row["field"], str) or row["field"] in seen
                or not isinstance(row["value"], str) or not row["value"]
                or row["decision"] not in (None, "retain")):
            raise ValueError("Invalid explicit override accounting")
        seen.add(row["field"])
        if row["repository_root"] is not None:
            _canonical(row["repository_root"])
        if row["value"].startswith("/"):
            _canonical(row["value"])
        elif any(part in {"", ".", ".."} for part in row["value"].split("/")):
            raise ValueError("Noncanonical explicit override")
        if row["decision"] is None:
            unresolved.append({"field": row["field"], "reason": "explicit authority requires operator decision"})
    if not {r["field"] for r in _OVERRIDES}.issubset(seen):
        raise ValueError("Known retained explicit overrides omitted")
    deferrals = manifest["phase_deferrals"]
    if not isinstance(deferrals, list) or len(deferrals) != len(_DEFERRALS):
        raise ValueError("Both deferred registry authorities must be accounted")
    for row, expected in zip(deferrals, _DEFERRALS):
        if (not isinstance(row, dict) or set(row) != set(expected)
                or {k: v for k, v in row.items() if k != "decision"} != {k: v for k, v in expected.items() if k != "decision"}
                or row["decision"] not in (None, "retain")):
            raise ValueError("Frozen registry deferral accounting changed")
        for entry in manifest["entries"]:
            if (entry["store"] == "source_inbox_root"
                    and entry["relative_path"] == Path(row["source"]).name
                    and (entry["kind"] != "file" or entry["size"] != row["size"]
                         or entry["sha256"] != row["sha256"])):
                raise ValueError("Deferred PDF differs from its frozen size/hash identity")
        if row["decision"] is None:
            unresolved.append({"field": row["source"], "reason": "registry authority and source-move disposition remain separate"})
    return unresolved


def _validate(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError("Expected private migration manifest")
    required = {"schema", "status", "activated", "writers_quiescent", "source_bindings", "destination_bindings",
        "entries", "source_snapshot", "destination_snapshot", "verified_destination_snapshot", "errors", "collisions",
        "rollback_conflicts", "retained_paths", "reference_requests", "compatibility_map", "selected_bindings",
        "selected_overrides", "phase_deferrals", "unresolved_authorities", "ready_for_activation", "resume_certified",
        "historical_coverage"}
    if set(manifest) != required or manifest["activated"] is not False:
        raise ValueError("Unknown, missing or active migration manifest fields")
    _bindings(manifest["source_bindings"], manifest["destination_bindings"])
    try:
        expected = _entries(manifest["source_bindings"], manifest["destination_bindings"], manifest["source_snapshot"])
        actual = deepcopy(manifest["entries"])
        for row in actual:
            row["destination_mode"] = None
        if actual != expected:
            raise ValueError("Manifest entries differ from selected snapshot paths")
        for row in expected:
            relative = row["relative_path"]
            if (relative != "." and (not isinstance(relative, str) or relative.startswith("/")
                    or any(p in {"", ".", ".."} for p in relative.split("/")))):
                raise ValueError("Unsafe manifest entry path")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed source snapshot") from exc
    _authority(manifest)
    return _requests(manifest)


def _incomplete(result, error):
    result.update(status="copy_incomplete", activated=False, compatibility_map=None,
                  selected_bindings=None, ready_for_activation=False, resume_certified=False)
    result["errors"].append(str(error) or type(error).__name__)
    return result


def _content(rows):
    return [{k: v for k, v in row.items() if k != "identity"} for row in rows or []]


def verify(manifest: dict) -> dict:
    """Read-only rehash of both stores. A status string alone is not evidence."""
    mapping = _validate(manifest)
    result = deepcopy(manifest)
    result["errors"] = []
    try:
        if manifest["writers_quiescent"] is not True:
            raise ValueError("No quiescent copy assertion recorded")
        if manifest["collisions"] or any(rows and (len(rows) > 1 or rows[0]["kind"] != "directory")
                                         for rows in manifest["destination_snapshot"].values()):
            raise ValueError("Initial destination collision remains unresolved")
        observed = {}
        for name in STORES:
            old = _scan(Path(manifest["source_bindings"]["stores"][name]))
            new = _scan(Path(manifest["destination_bindings"]["stores"][name]))
            if old != manifest["source_snapshot"][name]:
                raise ValueError(f"Source snapshot changed: {name}")
            if _content(old) != _content(new):
                raise ValueError(f"Destination hash, mode, kind or membership mismatch: {name}")
            prior = manifest["verified_destination_snapshot"]
            if prior is not None and new != prior[name]:
                raise ValueError(f"Verified destination identity changed: {name}")
            observed[name] = new
        result.update(status="verified", compatibility_map=mapping, verified_destination_snapshot=observed,
            unresolved_authorities=_authority(manifest), selected_bindings=None,
            ready_for_activation=False, activated=False, resume_certified=False)
        for row in result["entries"]:
            row["destination_mode"] = row["source_mode"]
        return result
    except (OSError, ValueError) as exc:
        return _incomplete(result, exc)


def _make_directory(path, retained):
    with _directory(path.parent) as parent:
        os.mkdir(path.name, 0o700, dir_fd=parent)
        retained.append(str(path))
        os.fsync(parent)


def _copy_file(entry, retained, owned):
    source, destination = Path(entry["source"]), Path(entry["destination"])
    temporary = ".atr-copy-" + uuid4().hex + ".tmp"
    with _file(source) as reader, _directory(destination.parent) as parent:
        if _identity(os.fstat(reader)) != entry["source_identity"]:
            raise ValueError(f"Source changed before copy: {source}")
        writer = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        retained.append(str(destination.parent / temporary))
        try:
            while data := os.read(reader, 1024 * 1024):
                pending = memoryview(data)
                while pending:
                    written = os.write(writer, pending)
                    if written <= 0:
                        raise OSError("Short destination write")
                    pending = pending[written:]
            os.fchmod(writer, entry["source_mode"])
            os.fsync(writer)
            if _identity(os.fstat(reader)) != entry["source_identity"]:
                raise ValueError(f"Source changed during copy: {source}")
            # link, unlike replace/rename, cannot overwrite an existing record.
            os.link(temporary, destination.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            owned.append((destination, entry, os.fstat(writer).st_ino))
            retained.append(str(destination))
            # This name is an owned temporary link to the same published bytes,
            # never an original or a rollback target. Do not remove a replacement.
            if os.stat(temporary, dir_fd=parent, follow_symlinks=False).st_ino != os.fstat(writer).st_ino:
                raise ValueError("Owned temporary path was replaced")
            os.unlink(temporary, dir_fd=parent)
            retained.remove(str(destination.parent / temporary))
            os.fsync(parent)
        finally:
            os.close(writer)


def copy_and_verify(plan: dict, *, writers_quiescent: bool) -> dict:
    """Copy exclusively to empty selected stores; retain partial copies on error."""
    if writers_quiescent is not True:
        raise ValueError("Writers must be explicitly quiescent before copy")
    _validate(plan)
    if plan["status"] != "planned":
        raise ValueError("Copy requires a fresh planned manifest")
    result = deepcopy(plan)
    result["writers_quiescent"] = True
    owned = []
    try:
        fresh = plan_copy(plan["source_bindings"], plan["destination_bindings"])
        if fresh["collisions"]:
            result["collisions"] = fresh["collisions"]
            raise ValueError("Destination collision; no merge or overwrite permitted")
        for key in ("source_snapshot", "destination_snapshot"):
            if fresh[key] != plan[key]:
                raise ValueError(f"Planned {key} changed before copy")
        for entry in result["entries"]:
            if entry["kind"] == "directory":
                path = Path(entry["destination"])
                if entry["relative_path"] != "." or plan["destination_snapshot"][entry["store"]] is None:
                    _make_directory(path, result["retained_paths"])
            else:
                _copy_file(entry, result["retained_paths"], owned)
        for entry in reversed(result["entries"]):
            if entry["kind"] == "directory":
                with _directory(Path(entry["destination"])) as descriptor:
                    os.fchmod(descriptor, entry["source_mode"])
                    os.fsync(descriptor)
        return verify(result)
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        for path, entry, inode in owned:
            try:
                digest, identity = _read_file(path)
                unchanged = digest == entry["sha256"] and identity["inode"] == inode and identity["mode"] == entry["source_mode"]
            except (OSError, ValueError):
                unchanged = False
            if not unchanged:
                result["rollback_conflicts"].append({"path": str(path), "reason": "destination changed; retained without rollback"})
        return _incomplete(result, exc)


def propose_bindings(verified_manifest: dict) -> dict:
    """Return inert destination bindings only after fresh read-only verification."""
    expected_map = _validate(verified_manifest)
    if (verified_manifest["status"] != "verified" or verified_manifest["verified_destination_snapshot"] is None
            or verified_manifest["compatibility_map"] != expected_map):
        raise ValueError("Only a fully verified copy can propose bindings")
    result = verify(verified_manifest)
    if result["status"] != "verified":
        raise ValueError("Copy no longer verifies; no binding proposal")
    result["selected_bindings"] = deepcopy(result["destination_bindings"])
    return result


def _load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    with _file(_canonical(path)) as descriptor:
        with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as stream:
            return json.load(stream, object_pairs_hook=unique)


def _write_manifest(path, document):
    path = _canonical(path)
    data = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    with _directory(path.parent) as parent:
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(os.dup(descriptor), "wb") as stream:
                stream.write(data)
                stream.flush()
            os.fsync(descriptor)
            os.fsync(parent)
        finally:
            os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    for name in ("plan", "copy", "verify", "propose-bindings"):
        mode = modes.add_parser(name)
        mode.add_argument("--output", required=True, help="new private manifest path (never overwritten)")
        if name == "plan":
            mode.add_argument("--source-bindings", required=True)
            mode.add_argument("--destination-bindings", required=True)
        else:
            mode.add_argument("--manifest", required=True)
        if name == "copy":
            mode.add_argument("--writers-quiescent", action="store_true")
    args = parser.parse_args(argv)
    try:
        output = _canonical(args.output)
        with _directory(output.parent) as parent:
            try:
                os.stat(output.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("Output already exists; never overwrite a private manifest")
        if args.mode == "plan":
            result = plan_copy(_load(args.source_bindings), _load(args.destination_bindings))
            for binding in (result["source_bindings"], result["destination_bindings"]):
                if any(output.is_relative_to(Path(root)) for root in binding["stores"].values()):
                    raise ValueError("Manifest output must be outside copied stores")
        else:
            document = _load(args.manifest)
            # A durable manifest within either store would invalidate snapshots
            # or expose authority as ordinary copied data. Require separation.
            for binding in (document["source_bindings"], document["destination_bindings"]):
                if any(output.is_relative_to(Path(root)) for root in binding["stores"].values()):
                    raise ValueError("Manifest output must be outside copied stores")
            if args.mode == "copy":
                result = copy_and_verify(document, writers_quiescent=args.writers_quiescent)
            elif args.mode == "verify":
                result = verify(document)
            else:
                result = propose_bindings(document)
        _write_manifest(args.output, result)
        return 0 if result["status"] != "copy_incomplete" else 1
    except (OSError, ValueError, KeyError) as exc:
        print(f"Private-state operation refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Select this source container only; do not load runtime bindings or apps.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main())
