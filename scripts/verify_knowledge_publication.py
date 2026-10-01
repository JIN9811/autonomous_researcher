#!/usr/bin/env python3
"""Check staged (or outgoing revision) blobs without printing sensitive content.

Run before committing: python scripts/verify_knowledge_publication.py
CI: --base BASE_SHA --head HEAD_SHA. This is a guard, not a complete DLP system.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tomllib

PRIVATE_ROOTS = {"memory", "runs", "artifacts", "output", "outputs", "user_files", "logs", "test-results", "oldversion"}
MAX_BLOB = 5_000_000
CREDENTIALS = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
PERSONAL_PATH = re.compile(r"(?:/home/[A-Za-z0-9_.-]+/|[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+\\)")
ALLOWLIST = "docs/knowledge/publication_allowlist.json"
ALLOWLIST_PATHS = (ALLOWLIST, "system/knowledge/publication_allowlist.json")
WIKI_ROOTS = ("docs/knowledge/wiki/", "system/knowledge/wiki/")
# Exact public source/sentinel rows from the ba273dd relocation inventory.
# Deliberately not inferred from filenames or a mutable review manifest.
PUBLIC_STORE_SOURCES = frozenset({
    "memory/__init__.py", "memory/experiment_db.py", "memory/failure_memory.py",
    "memory/retrieval.py", "memory/schemas.py", "memory/README.md",
    "runs/README.md", "artifacts/README.md", "outputs/README.md", "user_files/README.md",
})
PUBLIC_STORE_PATHS = PUBLIC_STORE_SOURCES | {"runtime/" + path for path in PUBLIC_STORE_SOURCES}
RELOCATION_ASSET = {
    "source": "models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx",
    "destination": "runtime/models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx",
    "baseline": "ba273ddb0fc2bf8795630d51d93d3932748e0a51",
    "size": 63201294,
    "sha256": "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
}
EVIDENCE_DIRECTORY = "evidence"
EVIDENCE_DOC_TYPE = "evidence"
FRONT_MATTER_DOC_TYPE = re.compile(r"(?mi)^\s*doc_type\s*:\s*['\"]?evidence['\"]?\s*$")
ATR_DOC_HEADER = re.compile(r"\A<!--\s*atr-doc\s*\n(.*?)-->", re.DOTALL)


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def _parts(path: str) -> tuple[str, ...] | None:
    """Accept canonical repository-relative POSIX paths; never repair input."""
    if (not isinstance(path, str) or not path or "\\" in path or "\0" in path
            or re.match(r"^[A-Za-z]:", path)):
        return None
    parts = tuple(path.split("/"))
    return None if any(part in {"", ".", ".."} for part in parts) else parts


def private_path(path: str) -> bool:
    parts = _parts(path)
    if parts is None:
        return True
    if parts[0] == "workspace":
        return True
    if parts[0] in PRIVATE_ROOTS or (len(parts) > 1 and parts[0] == "runtime" and parts[1] in PRIVATE_ROOTS):
        return path not in PUBLIC_STORE_PATHS
    if parts[:4] in {("docs", "knowledge", "manuals", "sources"),
                     ("system", "knowledge", "manuals", "sources")}:
        return True
    return any(part == ".env" or (part.startswith(".env.") and part != ".env.example") for part in parts)


def has_evidence_doc_type(path: str, blob: bytes) -> bool:
    suffix = PurePosixPath(path).suffix.lower()
    try:
        if suffix == ".json":
            return json.loads(blob).get("doc_type") == EVIDENCE_DOC_TYPE
        if suffix == ".toml":
            return tomllib.loads(blob.decode("utf-8")).get("doc_type") == EVIDENCE_DOC_TYPE
    except (UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError, AttributeError):
        return False
    text = blob.decode("utf-8", "replace")
    if suffix == ".md":
        if text.startswith("---\n"):
            text = text[4:].split("\n---", 1)[0]
        else:
            atr_doc = ATR_DOC_HEADER.match(text)
            if not atr_doc:
                return False
            text = atr_doc.group(1)
    elif suffix not in {".yaml", ".yml"}:
        return False
    return bool(FRONT_MATTER_DOC_TYPE.search(text))


def requires_evidence_review(path: str, blob: bytes) -> bool:
    return EVIDENCE_DIRECTORY in PurePosixPath(path).parts or has_evidence_doc_type(path, blob)


def in_approved_corpus(path: str, approved_corpora: list[str]) -> bool:
    parts = _parts(path)
    if parts is None:
        return False
    for corpus in approved_corpora:
        prefix = _parts(corpus[:-1]) if isinstance(corpus, str) and corpus.endswith("/") else None
        if prefix and len(parts) > len(prefix) and parts[:len(prefix)] == prefix:
            return True
    return False


def _entry(root: Path, path: str, revision: str | None) -> tuple[str, str] | None:
    """Return exact Git mode/object, never dereferencing working-tree links."""
    if _parts(path) is None:
        return None
    rows = (_git(root, "ls-tree", "-z", revision, "--", path) if revision else
            _git(root, "ls-files", "--stage", "-z", "--", path))
    for row in rows.split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        if name.decode("utf-8", "surrogateescape") != path:
            continue
        fields = metadata.decode().split()
        if revision:
            return fields[0], fields[2]
        if fields[2] == "0":
            return fields[0], fields[1]
    return None


def _valid_relocation_record(record: dict) -> bool:
    return (isinstance(record, dict) and record == RELOCATION_ASSET
            and set(record) == set(RELOCATION_ASSET)
            and type(record.get("size")) is int
            and all(isinstance(record.get(key), str) for key in ("source", "destination", "baseline", "sha256"))
            and bool(re.fullmatch(r"[0-9a-f]{40}", record["baseline"]))
            and not private_path(record["source"]) and not private_path(record["destination"]))


def validate_relocation_asset(root: Path, record: dict, *, base: str, head: str | None) -> bool:
    """Prove the single reviewed byte-identical move against immutable Git objects."""
    if not _valid_relocation_record(record):
        return False
    try:
        baseline = _git(root, "rev-parse", "--verify", "--end-of-options",
                        record["baseline"] + "^{commit}").decode().strip()
        if baseline != record["baseline"]:
            return False
        original = _entry(root, record["source"], baseline)
        source = _entry(root, record["source"], base)
        destination = _entry(root, record["destination"], head)
        if (not original or original[0] not in {"100644", "100755"} or source != original
                or destination != original or _entry(root, record["source"], head) is not None
                or _entry(root, record["destination"], base) is not None):
            return False
        blob = _git(root, "cat-file", "blob", original[1])
        return (len(blob) == record["size"] and hashlib.sha256(blob).hexdigest() == record["sha256"]
                and not CREDENTIALS.search(blob)
                and not (b"\0" not in blob and PERSONAL_PATH.search(blob.decode("utf-8", "replace"))))
    except (OSError, subprocess.CalledProcessError, ValueError):
        return False


def inspect(root: Path, base: str | None = None, head: str | None = None) -> dict:
    if (base is None) != (head is None):
        raise ValueError("base and head must be supplied together")
    if base:
        # A tree base also supports first-push scans against the empty Git tree.
        base = _git(root, "rev-parse", "--verify", "--end-of-options", f"{base}^{{tree}}").decode().strip()
        head = _git(root, "rev-parse", "--verify", "--end-of-options", f"{head}^{{commit}}").decode().strip()
        paths = _git(root, "diff", "--name-only", "-z", "--diff-filter=ACMRT", base, head, "--")
    else:
        paths = _git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT", "--")
    failures = []
    files = [p.decode("utf-8", "surrogateescape") for p in paths.split(b"\0") if p]
    manifests = []
    for path in ALLOWLIST_PATHS:
        entry = _entry(root, path, head)
        if entry:
            if entry[0] not in {"100644", "100755"}:
                raise ValueError("Invalid publication review manifest")
            manifests.append(json.loads(_git(root, "cat-file", "blob", entry[1])))
    if len(manifests) > 1:
        raise ValueError("Ambiguous publication review manifest")
    manifest = manifests[0] if manifests else {"schema": "knowledge_publication.v1", "approved_assets": {}, "approved_corpora": []}
    if (not isinstance(manifest, dict) or manifest.get("schema") != "knowledge_publication.v1"
            or not isinstance(manifest.get("approved_assets"), dict)
            or not isinstance(manifest.get("approved_corpora"), list)
            or not all(_parts(path) for path in manifest["approved_assets"])
            or not all(isinstance(corpus, str) and corpus.endswith("/") and _parts(corpus[:-1])
                       for corpus in manifest["approved_corpora"])
            or not isinstance(manifest.get("relocation_assets", []), list)
            or len(manifest.get("relocation_assets", [])) > 1
            or not all(_valid_relocation_record(record) for record in manifest.get("relocation_assets", []))):
        raise ValueError("Invalid publication review manifest")
    approved = manifest["approved_assets"]
    approved_corpora = manifest["approved_corpora"]
    relocations = {record["destination"]: record for record in manifest.get("relocation_assets", [])}
    for index, path in enumerate(files, 1):
        reasons = []
        if private_path(path):
            reasons.append("private_path")
        else:
            ref = f"{head}:{path}" if head else f":{path}"
            size = int(_git(root, "cat-file", "-s", ref))
            blob = _git(root, "show", ref)
            if CREDENTIALS.search(blob):
                reasons.append("credential_pattern")
            if b"\0" not in blob and PERSONAL_PATH.search(blob.decode("utf-8", "replace")):
                reasons.append("personal_path")
            relocated = False
            if path in relocations and not reasons:
                relocated = validate_relocation_asset(root, relocations[path], base=base or "HEAD", head=head)
                if not relocated:
                    reasons.append("invalid_asset_relocation")
            if size > MAX_BLOB and not relocated:
                reasons.append("oversized_blob_requires_publication_review")
            elif not relocated:
                review = approved.get(path, {})
                reviewed = (isinstance(review, dict) and bool(review.get("review"))
                            and review.get("sha256") == hashlib.sha256(blob).hexdigest())
                if b"\0" in blob and not reviewed:
                    reasons.append("binary_requires_publication_review")
                if requires_evidence_review(path, blob) and not reviewed:
                    reasons.append("evidence_requires_publication_review")
                if in_approved_corpus(path, WIKI_ROOTS) and not requires_evidence_review(path, blob) and not reviewed \
                        and not in_approved_corpus(path, approved_corpora):
                    reasons.append("wiki_requires_corpus_approval")
        if reasons:
            # IDs avoid leaking user names which may occur in filenames themselves.
            failures.append({"file_index": index, "reasons": reasons})
    return {"ok": not failures, "checked": len(files), "failures": failures,
            "note": "Indexes refer to git diff --name-only order; matching content is never printed."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--head")
    args = parser.parse_args()
    try:
        result = inspect(args.repo, args.base, args.head)
    except (ValueError, OSError, subprocess.CalledProcessError):
        print(json.dumps({"ok": False, "status": "inspection_failed"}))
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
