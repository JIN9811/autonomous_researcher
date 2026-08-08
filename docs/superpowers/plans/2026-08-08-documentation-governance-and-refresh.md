# ATR Documentation Governance and Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish enforceable documentation roles and templates, migrate the primary entry points and runtime/Knowledge documents, and refresh every measured claim against commit `09bbe32` without changing runtime behavior.

**Architecture:** Keep the existing domain-oriented document paths and add a manifest-backed governance layer over them. A small PyYAML validator owns metadata, path, relationship, and snapshot-consistency checks; prose remains human-authored. The first manifest covers only the documents migrated in this rollout so legacy material remains visible without blocking adoption.

**Tech Stack:** Markdown, YAML front matter, Python 3.11+, PyYAML 6+, pytest, FastAPI route introspection, Git.

## Global Constraints

- The seven canonical document types are exactly `index`, `standard`, `reference`, `guide`, `design`, `plan`, and `evidence`.
- Shared lifecycle values are exactly `draft`, `review`, `active`, `superseded`, and `archived`.
- Existing domain folders remain in place; this rollout MUST NOT bulk-move documents or break links for taxonomy cleanup.
- Executable code and checked-in configuration remain the source of truth for current behavior.
- Active Reference and Guide documents MUST identify reproducible source paths and a verification baseline.
- The validator checks metadata and reproducible facts; it MUST NOT generate or rewrite prose.
- The first manifest validates only migrated documents and records unmigrated documents as migration debt.
- Runtime code, API behavior, GUI behavior, and physical-device behavior MUST NOT change.
- The committed code baseline for current facts is `09bbe32` (`feat: expand knowledge graph runtime and workspace`).

---

## File and Interface Map

| File | Responsibility |
|---|---|
| `docs/document_manifest.yaml` | Declares the migrated document set, governance version, and explicitly deferred legacy scope. |
| `scripts/validate_documentation.py` | Parses front matter and validates metadata, local paths, relationships, and snapshot facts. |
| `tests/unit/test_documentation_validation.py` | Locks validator behavior with isolated temporary repositories plus a real-manifest test. |
| `docs/standards/documentation_standard.md` | Normative document types, lifecycle, authority, metadata, verification, and change rules. |
| `docs/templates/document_types.md` | Copy-ready metadata and body templates for all seven types. |
| `README.md`, `README.ko.md`, `README.en.md` | Language entry points and high-level current-code facts. |
| `docs/README.md` | Audience/type/domain navigation, authority order, Knowledge page mapping, and migration state. |
| `docs/runtime/current_code_snapshot.md` | Reproducible current implementation counts and contracts for commit `09bbe32`. |
| `docs/runtime/langgraph_runtime.md` | Current LangGraph runtime Reference metadata and verification boundary. |
| `docs/runtime/closed_loop_and_pages_reference.md` | Current system/page/agent Reference metadata and Knowledge workspace coverage. |
| `docs/knowledge/knowledge_graph_operations.ko.md` | Operator Guide metadata, safety boundaries, success/recovery criteria, and current endpoints. |

### Validator interfaces

| Function | Contract |
|---|---|
| `split_front_matter(text: str) -> tuple[dict[str, object], str]` | Return parsed YAML metadata and the Markdown body; raise `ValueError` for a missing, unterminated, or non-mapping front matter block. |
| `validate_document(path: Path, root: Path) -> list[str]` | Return every metadata and repository-relative path defect for one document. |
| `validate_manifest(root: Path, manifest_path: Path) -> list[str]` | Return manifest schema, membership, document, and snapshot consistency defects. |
| `main(argv: Sequence[str] \| None = None) -> int` | Print validation results and return `0` for success or `1` for any defect. |

The manifest schema is:

```yaml
version: 1
documents:
  - README.md
  - docs/README.md
legacy_scope:
  status: migration_debt
  note: Existing Markdown outside documents is classified in later batches.
snapshot:
  document: docs/runtime/current_code_snapshot.md
  expected:
    api_routes: 332
    app_routes: 339
    graph_nodes: 19
    graph_edges: 68
    stage_dispatch_edges: 12
```

## Task 1: Add the manifest validator with tests

**Files:**
- Create: `tests/unit/test_documentation_validation.py`
- Create: `scripts/validate_documentation.py`
- Create: `docs/document_manifest.yaml`

**Interfaces:**
- Consumes: PyYAML from the existing project dependencies and repository-relative paths.
- Produces: `split_front_matter`, `validate_document`, `validate_manifest`, and a zero/non-zero CLI exit contract used by Task 5.

- [ ] **Step 1: Write failing parser and metadata tests**

Create tests that import the validator by file path and assert the exact contracts below:

```python
def test_split_front_matter_returns_metadata_and_body():
    metadata, body = module.split_front_matter(
        "---\ndoc_type: index\nstatus: active\n---\n# Index\n"
    )
    assert metadata["doc_type"] == "index"
    assert body == "# Index\n"

def test_active_reference_requires_verification_fields(tmp_path):
    path = write_document(tmp_path, "docs/runtime.md", REFERENCE_WITHOUT_VERIFICATION)
    errors = module.validate_document(path, tmp_path)
    assert any("source_of_truth" in error for error in errors)
    assert any("last_verified" in error for error in errors)
    assert any("verified_against" in error for error in errors)

def test_source_and_related_paths_must_exist(tmp_path):
    path = write_document(tmp_path, "docs/runtime.md", REFERENCE_WITH_MISSING_PATHS)
    errors = module.validate_document(path, tmp_path)
    assert any("missing source_of_truth path" in error for error in errors)
    assert any("missing related_docs path" in error for error in errors)
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `.venv/bin/pytest tests/unit/test_documentation_validation.py -q`

Expected: collection fails because `scripts/validate_documentation.py` does not exist.

- [ ] **Step 3: Implement the minimal metadata and path validator**

Implement allowlists as immutable sets, parse only a leading `---` YAML block with `yaml.safe_load`, and return path-prefixed error strings instead of raising for document defects. Enforce:

```text
all documents: doc_type, subtype, status, authority, audience, scope,
               summary, related_docs, supersedes
active reference/guide: non-empty source_of_truth, last_verified,
                        verified_against
design: decision_status in proposed/approved/rejected/superseded
plan: execution_status in planned/in_progress/blocked/completed/cancelled
evidence: evidence_date and method
superseded: supersedes or superseded_by
```

Resolve `source_of_truth`, `related_docs`, `supersedes`, and `superseded_by` from repository root. Reject absolute paths and any relative path that escapes the root.

- [ ] **Step 4: Add manifest and snapshot tests**

Add tests proving that duplicate manifest paths, missing manifest documents, invalid `version`, and stale snapshot numbers are errors. Snapshot validation reads the five labeled count fields from `docs/runtime/current_code_snapshot.md`; it does not import the application in unit tests.

```python
def test_manifest_rejects_duplicate_documents(tmp_path):
    write_document(tmp_path, "README.md", VALID_INDEX)
    manifest = write_manifest(tmp_path, ["README.md", "README.md"])
    errors = module.validate_manifest(tmp_path, manifest)
    assert any("duplicate document" in error for error in errors)


def test_manifest_rejects_missing_documents(tmp_path):
    manifest = write_manifest(tmp_path, ["docs/missing.md"])
    errors = module.validate_manifest(tmp_path, manifest)
    assert any("missing manifest document" in error for error in errors)


def test_manifest_rejects_stale_snapshot_values(tmp_path):
    write_document(tmp_path, "README.md", VALID_INDEX)
    write_document(
        tmp_path,
        "docs/runtime/current_code_snapshot.md",
        VALID_SNAPSHOT.replace("Graph nodes: 19", "Graph nodes: 18"),
    )
    manifest = write_manifest(
        tmp_path,
        ["README.md", "docs/runtime/current_code_snapshot.md"],
        snapshot_expected={
            "api_routes": 332,
            "app_routes": 339,
            "graph_nodes": 19,
            "graph_edges": 68,
            "stage_dispatch_edges": 12,
        },
    )
    errors = module.validate_manifest(tmp_path, manifest)
    assert any("Graph nodes: expected 19, found 18" in error for error in errors)
```

- [ ] **Step 5: Implement manifest and CLI validation**

`validate_manifest(root, manifest_path)` MUST validate every unique listed document and compare these labels with `snapshot.expected`:

```text
FastAPI APIRoute count
Total app.routes count
Graph nodes
Graph edges
stage_dispatch edges
```

`main()` accepts `--root` and `--manifest`, prints `documentation validation passed` on success, prints one error per line on failure, and returns `0` or `1`.

- [ ] **Step 6: Run focused tests and commit**

Run:

```bash
.venv/bin/pytest tests/unit/test_documentation_validation.py -q
.venv/bin/python scripts/validate_documentation.py
```

The unit tests should pass. The CLI is allowed to fail until Tasks 2-4 create and migrate every manifest document.

Commit:

```bash
git add scripts/validate_documentation.py tests/unit/test_documentation_validation.py docs/document_manifest.yaml
git commit -m "test: add documentation governance validator"
```

## Task 2: Publish the Documentation Standard and templates

**Files:**
- Create: `docs/standards/documentation_standard.md`
- Create: `docs/templates/document_types.md`
- Modify: `docs/document_manifest.yaml`

**Interfaces:**
- Consumes: validator metadata rules from Task 1 and the approved Design at `docs/superpowers/specs/2026-08-08-documentation-governance-design.md`.
- Produces: normative authoring rules and copy-ready templates used by every later migration task.

- [ ] **Step 1: Add both paths to the manifest and confirm the validator fails**

Add the two files under `documents`, run `.venv/bin/python scripts/validate_documentation.py`, and expect missing-document errors for both paths.

- [ ] **Step 2: Write the active Documentation Standard**

Use `doc_type: standard`, `subtype: documentation`, `status: active`, and `authority: normative`. Cover exactly:

```text
Summary
Normative Scope
Source of Truth
Canonical Types and Subtypes
Lifecycle
Authority Order
Required Metadata
Type-specific Rules
Body Structure
Verification and Freshness
Link and Path Rules
Manifest and Migration Debt
Required Checks
Exceptions
Compliance Examples
Change Process
Limitations and Known Gaps
Verification
Related Documents
```

State that uppercase `MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative. Record the agent-plan header exception: files created under `docs/superpowers/plans/` by the planning workflow may remain outside the first manifest until a future compatible metadata carrier is adopted.

- [ ] **Step 3: Write all seven copy-ready templates**

Each template includes complete YAML front matter and the exact body headings from the Design. Use obvious example values that are valid paths only when copied and replaced; explain that placeholders are instructional and MUST be replaced before `active` status.

- [ ] **Step 4: Validate and commit**

Run:

```bash
.venv/bin/python scripts/validate_documentation.py
git diff --check
```

Commit:

```bash
git add docs/standards/documentation_standard.md docs/templates/document_types.md docs/document_manifest.yaml
git commit -m "docs: define documentation standard and templates"
```

## Task 3: Migrate and refresh documentation entry points

**Files:**
- Modify: `README.md`
- Modify: `README.ko.md`
- Modify: `README.en.md`
- Modify: `docs/README.md`
- Modify: `docs/document_manifest.yaml`

**Interfaces:**
- Consumes: Index metadata and structure from Task 2; committed route measurements for `09bbe32`.
- Produces: authoritative navigation to current Reference, Guide, Design, Plan, and Evidence documents.

- [ ] **Step 1: Add the four Index paths to the manifest and confirm RED**

Run `.venv/bin/python scripts/validate_documentation.py` and expect missing-front-matter errors for all four existing files.

- [ ] **Step 2: Add Index metadata without changing product semantics**

Use `doc_type: index`, `subtype: index`, `status: active`, `authority: navigation`, and repository-relative links. The root Indexes link to `docs/README.md`, the Documentation Standard, current snapshot, runtime references, Knowledge operations Guide, and the approved governance Design.

- [ ] **Step 3: Refresh current-code claims**

Replace stale `224 APIRoute / 229 app.routes` values in both language guides with:

```text
332 FastAPI APIRoute objects
339 total app.routes entries
```

Explain that these are measured from commit `09bbe32`, not decorator grep counts.

- [ ] **Step 4: Restructure the docs Index around type and audience**

Preserve useful existing domain links, then add:

```text
Summary
Scope
Evidence Basis
Audience Paths
Documents by Type
Documents by Domain
Authority and Conflict Resolution
Migration Status
Limitations and Known Gaps
Index Verification
Related Documents
```

Add the `/knowledge` page row with `web/templates/knowledge.html`, `web/static/knowledge.js`, `web/static/knowledge.css`, and `docs/knowledge/knowledge_graph_operations.ko.md`.

- [ ] **Step 5: Validate navigation and commit**

Run:

```bash
.venv/bin/python scripts/validate_documentation.py
rg -n "224 FastAPI|229.*app\.routes|APIRoute.*224|app\.routes.*229" README*.md docs/README.md
git diff --check
```

Expected: validator passes for migrated documents and `rg` finds no stale route count.

Commit:

```bash
git add README.md README.ko.md README.en.md docs/README.md docs/document_manifest.yaml
git commit -m "docs: refresh documentation entry points"
```

## Task 4: Migrate core References and the Knowledge operations Guide

**Files:**
- Modify: `docs/runtime/current_code_snapshot.md`
- Modify: `docs/runtime/langgraph_runtime.md`
- Modify: `docs/runtime/closed_loop_and_pages_reference.md`
- Modify: `docs/knowledge/knowledge_graph_operations.ko.md`
- Modify: `docs/document_manifest.yaml`

**Interfaces:**
- Consumes: Reference/Guide rules from Task 2 and source measurements from commit `09bbe32`.
- Produces: validator-covered current runtime facts and an operator-safe Knowledge runbook.

- [ ] **Step 1: Add the four paths to the manifest and confirm RED**

Run `.venv/bin/python scripts/validate_documentation.py` and expect missing-front-matter errors before editing the documents.

- [ ] **Step 2: Add active Reference metadata and required sections**

Use these primary classifications:

```text
current_code_snapshot.md             reference/current_snapshot
langgraph_runtime.md                 reference/runtime
closed_loop_and_pages_reference.md   reference/system
```

Use `authority: descriptive`, `last_verified: 2026-08-08`, and `verified_against: 09bbe32`. Add concise `Summary`, `Scope`, `Source of Truth`, `Limitations and Known Gaps`, `Verification`, and `Related Documents` sections where absent; do not duplicate the existing detailed content.

- [ ] **Step 3: Correct and reproduce snapshot counts**

The snapshot MUST contain these labeled values:

```text
FastAPI APIRoute count: 332
Total app.routes count: 339
Graph nodes: 19
Graph edges: 68
stage_dispatch edges: 12
```

Record the Python/FastAPI introspection command, graph YAML count command, collection date `2026-08-08`, and baseline `09bbe32`. Replace the stale `18 nodes / 64 edges` statement.

- [ ] **Step 4: Convert the Knowledge document into an operations runbook**

Use `doc_type: guide`, `subtype: operations_runbook`, `authority: procedural`, `last_verified: 2026-08-08`, and `verified_against: 09bbe32`. Ensure it contains:

```text
Summary
Audience and Outcome
Scope
Source of Truth
Prerequisites
Safety Boundary
Procedure
Success Criteria
Failure Recovery
Rollback or Stop Procedure
Limitations and Known Gaps
Verification
Related Reference
```

Keep all current operational facts for `/knowledge`, `/api/knowledge/graph/stats`, outbox replay, dead-letter handling, and Neo4j optionality. Distinguish read-only inspection from mutations and physical-device effects.

- [ ] **Step 5: Run the validator and focused repository checks**

Run:

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/pytest tests/unit/test_documentation_validation.py -q
rg -n "18 nodes|64 edges|graph_nodes[^0-9]*18|graph_edges[^0-9]*64" docs/runtime/current_code_snapshot.md
git diff --check
```

Expected: all commands pass and stale graph counts are absent.

- [ ] **Step 6: Commit the migration**

```bash
git add docs/runtime/current_code_snapshot.md docs/runtime/langgraph_runtime.md docs/runtime/closed_loop_and_pages_reference.md docs/knowledge/knowledge_graph_operations.ko.md docs/document_manifest.yaml
git commit -m "docs: align runtime references with current code"
```

## Task 5: Verify the completed documentation rollout

**Files:**
- Modify only if verification exposes a documentation defect in a file already listed above.

**Interfaces:**
- Consumes: every artifact from Tasks 1-4.
- Produces: a clean validation report and explicit record of unrelated pre-existing test failures.

- [ ] **Step 1: Re-measure runtime facts read-only**

Use the project virtual environment to import `app.main:app`, count `fastapi.routing.APIRoute`, group routes with the existing snapshot classification, load `graphs/configs/atr_closed_loop.yaml`, and count nodes, all edges, and `type: stage_dispatch` edges. Remove only an empty run directory proven to have been created by this import.

Expected values are `332`, `339`, `19`, `68`, and `12` respectively.

- [ ] **Step 2: Run documentation validation and syntax checks**

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/pytest tests/unit/test_documentation_validation.py -q
.venv/bin/python -m py_compile scripts/validate_documentation.py
git diff --check
```

- [ ] **Step 3: Run relevant integration checks**

Run the Knowledge/runtime-focused tests already used for the committed baseline. If `tests/integration/test_live_gui_runtime_layout.py::test_live_gui_runtime_shell_contains_operational_panels` still fails only because it expects the older `styles.css` cache query string, record it as the pre-existing baseline failure and do not alter GUI code in this documentation-only rollout.

- [ ] **Step 4: Review scope and history**

```bash
git status --short
git diff --stat 09bbe32..HEAD
git log --oneline -5
```

Confirm no runtime, GUI, graph, bridge, or physical-device implementation file changed after `09bbe32`.

- [ ] **Step 5: Commit any verification-only correction**

Only if Step 1-4 required a correction to an in-scope documentation file:

```bash
git add README.md README.ko.md README.en.md docs/README.md \
  docs/document_manifest.yaml docs/standards/documentation_standard.md \
  docs/templates/document_types.md docs/runtime/current_code_snapshot.md \
  docs/runtime/langgraph_runtime.md \
  docs/runtime/closed_loop_and_pages_reference.md \
  docs/knowledge/knowledge_graph_operations.ko.md
git commit -m "docs: correct documentation verification findings"
```

## Completion Criteria

- `docs/document_manifest.yaml` lists every document migrated in this rollout exactly once.
- The validator exits zero and its unit tests pass.
- All active migrated documents satisfy their type-specific metadata rules.
- Entry points explain type, audience, authority, and migration status.
- Root route counts are `332/339`; the runtime graph is `19 nodes / 68 edges / 12 stage_dispatch edges`.
- `/knowledge` appears in the page map and the operations Guide reflects the committed Knowledge workspace and runtime.
- No post-`09bbe32` commit changes runtime or physical-device behavior.
- Any unrelated baseline test failure is reported with its exact test name and reason.
