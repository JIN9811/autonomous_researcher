"""Inventory committed objects without opening working-tree or private files."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import subprocess

SCHEMA = "atr.repository_layout.v1"
MANIFEST_PATH = "docs/maintenance/repository_layout_manifest.json"
CHANGE_CATEGORIES = {
    "path_reference": "Reviewed physical references only; logical identities unchanged",
    "document_metadata": "Reviewed links/source keys; effective guide bytes unchanged",
    "packaging": "Build roots, license inclusion and launch metadata",
    "generated_output": "Rebuild generated ROS output, never patch embedded host prefixes",
    "manifest_self_update": "Generated inventory updates have a new baseline and recorded generator",
}
GUI_INTERNALS = {
    "compute_workers.md", "monitoring_workers.md", "read_path_performance.md",
    "serialized_mesh_validation.md", "visual_structure.md",
}
SYSTEM_DOMAINS = {"agents", "runtime", "device_bridges", "hardware", "knowledge", "standards",
                  "templates", "maintenance", "repository", "process"}


def _public_expression(value: str) -> str:
    return re.sub(r"(?:/home/|/Users/|[A-Za-z]:[/\\]Users[/\\])[^\s'\"\)\],}]+", "<external-personal-path>", value)


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def git_entries(root: Path, revision: str):
    for record in _git(root, "ls-tree", "-rz", revision).split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        yield name.decode(), mode, kind, blob


def disposition(path: str) -> tuple[str, str, str]:
    p = PurePosixPath(path)
    if path == "README.md" or p.parts[0].startswith("."):
        return path, "keep", "Outer navigation or hidden repository tooling"
    special = {"README.ko.md": "docs/README.ko.md", "SECURITY.md": ".github/SECURITY.md",
               "LICENSE": "runtime/LICENSE", "CITATION.cff": "docs/paper/CITATION.cff",
               "docs/modularity.md": "system/modularity.md",
               "docs/document_manifest.yaml": "system/document_manifest.yaml",
               "docs/project/Project_guide.txt": "system/project/Project_guide.txt"}
    if path in special:
        return special[path], "move", "Explicit approved placement; preserve effective content"
    if path in {"REQUIREMENTS.md", "CHANGELOG.md", "CONTRIBUTING.md"}:
        return "docs/project/" + path, "move", "Human-facing project documentation"
    if path.startswith(("ros/install/", "ros/log/", "ros/build/")):
        return "runtime/" + path, "regenerated_build_output", "Generated ROS output; rebuild separately"
    if p.parts[0] in {"references", "image"}:
        prefix = "system/references/" if p.parts[0] == "references" else "system/assets/presentation/"
        return prefix + "/".join(p.parts[1:]), "move", "Preserve independent reference/asset bundle intact"
    if path.startswith("docs/oldversion/"):
        return path.replace("docs/oldversion/", "system/retained-history/", 1), "move", "Retained bundle/evidence; no new deletion approval"
    if path.startswith("docs/superpowers/"):
        return path.replace("docs/superpowers/", "system/", 1), "move", "Approved plans/specs and owned assets"
    if len(p.parts) > 2 and p.parts[0] == "docs" and p.parts[1] in SYSTEM_DOMAINS:
        return "system/" + path[5:], "move", "Technical owner reference domain"
    if path.startswith("docs/gui/") and p.name in GUI_INTERNALS:
        return "system/runtime/gui/" + p.name, "move", "Explicit technical GUI internal mapping"
    if path.startswith("docs/"):
        return path, "keep", "Human-facing navigation/procedures or self-contained human asset bundle"
    return "runtime/" + path, "move", "Executable peer tree or adjacent owned resource; preserve topology"


def _consumers(path: str, data: bytes) -> list[dict]:
    if not path.endswith(".py"):
        return []
    try:
        tree = ast.parse(data)
    except (SyntaxError, UnicodeDecodeError):
        return []
    rows = []
    interesting = {"resolve_path", "project_root", "getcwd", "chdir", "Popen", "run",
                   "getenv", "from_file", "load_all_configs"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if name not in interesting:
            continue
        expression = ast.unparse(node)
        kind = "repository_root"
        if any(part in expression for part in ("memory/", "runs/", "artifacts/", "outputs/", "run_root")):
            kind = "named_data_root"
        elif "docs/" in expression:
            kind = "system_root"
        elif any(part in expression for part in ("configs", "web/", "graphs/", "sim/", "scripts/")):
            kind = "runtime_root"
        elif name == "getenv":
            kind = "external_configuration"
        rows.append({"file": path, "symbol": name, "expression": _public_expression(expression),
                     "expression_sha256": hashlib.sha256(expression.encode()).hexdigest(),
                     "line": node.lineno, "root_kind": kind,
                     "review": "static_candidate; owning task must verify semantics"})
    return rows


def build_manifest(repository_root: Path, revision: str) -> dict:
    baseline = _git(repository_root, "rev-parse", f"{revision}^{{commit}}").decode().strip()
    entries, consumers = {}, []
    for path, mode, kind, blob in git_entries(repository_root, baseline):
        if kind != "blob":
            raise ValueError(f"Unsupported Git entry {kind}: {path}")
        data = _git(repository_root, "cat-file", "blob", blob)
        destination, action, reason = disposition(path)
        entry = {"destination": destination, "disposition": action, "reason": reason,
                 "mode": mode, "git_blob": blob, "sha256": hashlib.sha256(data).hexdigest(),
                 "size": len(data), "approved_content_changes": []}
        if mode == "120000":
            entry["symlink_target"] = _public_expression(data.decode())
            entry["symlink_target_class"] = ("external_personal_path" if entry["symlink_target"] != data.decode()
                                               else "absolute_external" if data.startswith(b"/") else "relative")
        if action == "regenerated_build_output":
            entry["approved_content_changes"] = ["generated_output"]
        if path == MANIFEST_PATH:
            entry["approved_content_changes"] = ["manifest_self_update"]
        entries[path] = entry
        consumers.extend(_consumers(path, data))
    return {"schema": SCHEMA, "baseline_commit": baseline, "tracked_paths": sorted(entries),
            "entries": entries, "approved_content_change_categories": CHANGE_CATEGORIES,
            "consumers": consumers,
            "generated_artifacts": [{"path": MANIFEST_PATH, "category": "manifest_self_update",
                                     "generator": "python -m tools.repository_layout.manifest"}],
            "privacy": "Committed public objects only; no private store inventory"}


def _safe_relative(value: object) -> bool:
    return isinstance(value, str) and bool(value) and "\\" not in value and not value.startswith("/") and all(
        part not in {"", ".", ".."} for part in value.split("/"))


def validate_manifest(manifest: dict) -> list[str]:
    errors = []
    if manifest.get("schema") != SCHEMA:
        errors.append("Unsupported schema")
    paths = manifest.get("tracked_paths", [])
    entries = manifest.get("entries", {})
    if len(paths) != len(set(paths)) or set(paths) != set(entries):
        errors.append("Missing or duplicate tracked disposition")
    destinations = {}
    for source, entry in entries.items():
        dest = entry.get("destination")
        if not _safe_relative(source) or not _safe_relative(dest):
            errors.append(f"Unsafe source/destination: {source}")
            continue
        if entry.get("disposition") not in {"move", "keep", "approved_deletion", "regenerated_build_output"}:
            errors.append(f"Unknown disposition: {source}")
        if dest in destinations:
            errors.append(f"Duplicate destination: {dest}")
        destinations[dest] = source
        for key in ("reason", "mode", "git_blob", "sha256"):
            if not entry.get(key):
                errors.append(f"Missing {key}: {source}")
        if entry.get("mode") == "120000" and "symlink_target" not in entry:
            errors.append(f"Missing symlink target: {source}")
        if any(category not in CHANGE_CATEGORIES for category in entry.get("approved_content_changes", [])):
            errors.append(f"Unapproved content category: {source}")
    for destination in destinations:
        if any(str(parent) in destinations for parent in PurePosixPath(destination).parents if str(parent) != "."):
            errors.append(f"Parent/file destination collision: {destination}")
    for row in manifest.get("consumers", []):
        if not all(row.get(key) for key in ("file", "symbol", "expression", "root_kind")):
            errors.append("Incomplete typed consumer")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--output", type=Path, help="Write the generated public inventory")
    args = parser.parse_args()
    result = build_manifest(args.root, args.revision)
    failures = validate_manifest(result)
    if failures:
        raise SystemExit("\n".join(failures))
    serialized = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    else:
        print(serialized, end="")
