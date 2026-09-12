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

PRIVATE_ROOTS = {"memory", "runs", "artifacts", "output", "outputs", "user_files", "logs", "test-results"}
MAX_BLOB = 5_000_000
CREDENTIALS = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
PERSONAL_PATH = re.compile(r"(?:/home/[A-Za-z0-9_.-]+/|[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+\\)")
ALLOWLIST = "docs/knowledge/publication_allowlist.json"
WIKI_ROOT = "docs/knowledge/wiki/"
EVIDENCE_DIRECTORY = "evidence"
EVIDENCE_DOC_TYPE = "evidence"
FRONT_MATTER_DOC_TYPE = re.compile(r"(?mi)^\s*doc_type\s*:\s*['\"]?evidence['\"]?\s*$")
ATR_DOC_HEADER = re.compile(r"\A<!--\s*atr-doc\s*\n(.*?)-->", re.DOTALL)


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def private_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts:
        return True
    if parts[0] in PRIVATE_ROOTS:
        if len(parts) == 2 and parts[1] in {"README.md", ".gitkeep"}:
            return False
        if parts[0] == "memory" and len(parts) == 2 and parts[1].endswith(".py"):
            return False
        return True
    if path.startswith("docs/knowledge/manuals/sources/"):
        return path not in {"docs/knowledge/manuals/sources/README.md", "docs/knowledge/manuals/sources/.gitkeep"}
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
    return any(path.startswith(corpus) for corpus in approved_corpora)


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
    manifest_ref = f"{head}:{ALLOWLIST}" if head else f":{ALLOWLIST}"
    try:
        manifest = json.loads(_git(root, "show", manifest_ref))
    except subprocess.CalledProcessError:
        manifest = {"schema": "knowledge_publication.v1", "approved_assets": {}, "approved_corpora": []}
    if (not isinstance(manifest, dict) or manifest.get("schema") != "knowledge_publication.v1"
            or not isinstance(manifest.get("approved_assets"), dict)
            or not isinstance(manifest.get("approved_corpora"), list)
            or not all(isinstance(corpus, str) and corpus.endswith("/") and not corpus.startswith("/")
                       and ".." not in PurePosixPath(corpus).parts
                       for corpus in manifest["approved_corpora"])):
        raise ValueError("Invalid publication review manifest")
    approved = manifest["approved_assets"]
    approved_corpora = manifest["approved_corpora"]
    for index, path in enumerate(files, 1):
        reasons = []
        if private_path(path):
            reasons.append("private_path")
        else:
            ref = f"{head}:{path}" if head else f":{path}"
            size = int(_git(root, "cat-file", "-s", ref))
            if size > MAX_BLOB:
                reasons.append("oversized_blob_requires_publication_review")
            else:
                blob = _git(root, "show", ref)
                if CREDENTIALS.search(blob):
                    reasons.append("credential_pattern")
                if b"\0" not in blob and PERSONAL_PATH.search(blob.decode("utf-8", "replace")):
                    reasons.append("personal_path")
                review = approved.get(path, {})
                reviewed = (isinstance(review, dict) and bool(review.get("review"))
                            and review.get("sha256") == hashlib.sha256(blob).hexdigest())
                if b"\0" in blob and not reviewed:
                    reasons.append("binary_requires_publication_review")
                if requires_evidence_review(path, blob) and not reviewed:
                    reasons.append("evidence_requires_publication_review")
                if path.startswith(WIKI_ROOT) and not requires_evidence_review(path, blob) and not reviewed \
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
