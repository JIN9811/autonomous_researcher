# Runtime IDE Reference Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish one code-backed Runtime IDE Reference with three editable/rendered architecture figures, complete operator workflow, repository navigation, and automated drift validation.

**Architecture:** Keep `docs/runtime/langgraph_runtime.md` as the executable-engine authority and add `docs/runtime/runtime_ide.md` as the canonical operator/UI boundary. Encode the stable 20-section outline, three figure stems, navigation links, and selected high-consequence source tokens in the existing Python documentation validator before writing the document.

**Tech Stack:** Markdown with YAML front matter, Graphviz DOT/SVG, Python documentation validator, pytest, git.

## Global Constraints

- Create one canonical Runtime IDE Reference at `docs/runtime/runtime_ide.md`.
- Create exactly three stable `.dot` sources and three same-stem `.svg` renderings under `docs/runtime/assets/figures/`.
- Preserve the approved 20-section order and include all five required implementation-backed tables.
- Cover the complete operator workflow from deep-link entry through recovery.
- Keep Runtime IDE, LangGraph runtime, Module Management, bridge descriptor, approval, and physical-effect authority boundaries explicit.
- Do not change Runtime IDE UI, API, graph, module, bridge, safety, or execution behavior.
- Browser and code inspection evidence must not be promoted into live reliability, safety-effectiveness, or scientific-validity claims.
- Do not modify or stage the user's pre-existing `.env.example` change.
- Full pytest is not a documentation completion gate; report unrelated failures separately from focused documentation and Runtime IDE results.
- Commit in reviewable groups and push `main` only after final scoped verification.

---

### Task 1: Encode the Runtime IDE Documentation Contract

**Files:**
- Modify: `tests/unit/test_documentation_validation.py`
- Modify: `scripts/validate_documentation.py`

**Interfaces:**
- Consumes: `validate_document(path: Path, root: Path) -> list[str]`, `validate_manifest(root: Path, manifest_path: Path) -> list[str]`, `_markdown_link_targets(body: str) -> list[str]`, and existing agent/device figure validation patterns.
- Produces: `RUNTIME_IDE_REFERENCE_PATH`, `RUNTIME_IDE_REQUIRED_SECTIONS`, `RUNTIME_IDE_REFERENCE_FIGURES`, `RUNTIME_IDE_SOURCE_CONTRACTS`, `_validate_runtime_ide_reference(...)`, and `_validate_runtime_ide_navigation(...)`.

- [x] **Step 1: Add a minimal Runtime IDE Reference fixture helper**

Add `TEST_RUNTIME_IDE_SECTIONS`, `TEST_RUNTIME_IDE_FIGURES`, and
`_write_runtime_ide_reference(root: Path) -> Path`. The helper writes the
selected source-contract tokens, all 20 H2 sections, and these three figure
pairs with captions:

```python
TEST_RUNTIME_IDE_FIGURES = (
    "runtime_ide_01_system_boundaries",
    "runtime_ide_02_config_activation_flow",
    "runtime_ide_03_observability_evidence_flow",
)
```

- [x] **Step 2: Add focused failing validator tests**

Add these exact tests:

```python
def test_runtime_ide_reference_requires_all_sections_in_order(tmp_path: Path) -> None: ...
def test_runtime_ide_reference_requires_figure_pairs_embeds_and_captions(tmp_path: Path) -> None: ...
def test_runtime_ide_reference_detects_high_consequence_source_drift(tmp_path: Path) -> None: ...
def test_manifest_requires_runtime_ide_navigation_links(tmp_path: Path) -> None: ...
```

The navigation test governs `README.md`, `README.ko.md`, `README.en.md`,
`docs/README.md`, `docs/runtime/langgraph_runtime.md`, and
`docs/runtime/runtime_ide.md`, then asserts one missing-link error per required
entry point.

- [x] **Step 3: Run the new tests and confirm failure**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_documentation_validation.py -k runtime_ide
```

Expected: FAIL because Runtime IDE constants and validation functions do not
exist yet or no errors are emitted for removed sections/assets/navigation.

- [x] **Step 4: Implement the minimal validator contract**

Use these stable source tokens:

```python
RUNTIME_IDE_SOURCE_CONTRACTS = (
    ("app/main.py", '@app.get("/ide", response_class=HTMLResponse)'),
    ("app/main.py", '@app.put("/api/graphs/{graph_id}")'),
    ("app/main.py", '@app.post("/api/graphs/{graph_id}/dry-run")'),
    ("app/main.py", '@app.post("/api/graphs/{graph_id}/run")'),
    ("app/main.py", '@app.post("/api/runs/{run_id}/approvals/{approval_id}/resolve")'),
    ("app/main.py", '@app.get("/api/runs/{run_id}/artifact-file/{artifact_path:path}")'),
    ("web/templates/runtime_ide.html", 'id="ide-run-live-confirm"'),
    ("web/static/runtime_ide.js", 'document.getElementById("ide-run-live-confirm")'),
)
```

Validate ordered sections, DOT/SVG existence, embeds, captions
`**Figure Runtime IDE-N.**`, and source tokens. Activate navigation checks only
when `docs/runtime/runtime_ide.md` is governed by the manifest.

- [x] **Step 5: Run focused validator tests**

```bash
.venv/bin/pytest -q tests/unit/test_documentation_validation.py -k 'runtime_ide or device_bridge or agent_reference'
```

Expected: PASS.

- [x] **Step 6: Commit the validator contract**

```bash
git add scripts/validate_documentation.py tests/unit/test_documentation_validation.py docs/superpowers/plans/2026-08-09-runtime-ide-reference-documentation.md
git commit -m "test: define Runtime IDE documentation contract"
```

### Task 2: Create the Runtime IDE Figures and Canonical Reference

**Files:**
- Create: `docs/runtime/runtime_ide.md`
- Create: `docs/runtime/assets/figures/runtime_ide_01_system_boundaries.dot`
- Create: `docs/runtime/assets/figures/runtime_ide_01_system_boundaries.svg`
- Create: `docs/runtime/assets/figures/runtime_ide_02_config_activation_flow.dot`
- Create: `docs/runtime/assets/figures/runtime_ide_02_config_activation_flow.svg`
- Create: `docs/runtime/assets/figures/runtime_ide_03_observability_evidence_flow.dot`
- Create: `docs/runtime/assets/figures/runtime_ide_03_observability_evidence_flow.svg`

**Interfaces:**
- Consumes: `app/main.py`, `web/templates/runtime_ide.html`, `web/static/runtime_ide.js`, `web/static/runtime_ide.css`, `web/static/runtime_graph_geometry.js`, graph/module stores and configs, `orchestrator/langgraph_runtime.py`, and Runtime IDE tests.
- Produces: the canonical 20-section Reference and the three stable figure pairs required by Task 1.

- [x] **Step 1: Draw the system-boundary figure**

Show browser `/ide`, FastAPI control APIs, graph/module/version stores,
LangGraph run loop, Module Management and bridge-workspace handoffs, approvals,
events/artifacts, and optional physical effects. Distinguish descriptor-only
and physical handoffs with dashed labeled edges.

- [x] **Step 2: Draw the configuration-activation figure**

Show draft edit, validation, compile summary, draft dry-run, version save,
optional activation, matching active dry-run digest, test/live preflight, and
run. Include failure loops for validation errors and stale digests.

- [x] **Step 3: Draw the observability-evidence figure**

Show run/controller actions producing structured events, approval records,
node state, JSONL logs, and artifacts; show IDE timeline, filters, inspector,
replay, artifact preview/download, and operator recovery actions as consumers.

- [x] **Step 4: Render all three figures**

```bash
for source in docs/runtime/assets/figures/runtime_ide_*.dot; do
  dot -Tsvg "$source" -o "${source%.dot}.svg"
done
```

Expected: three SVG files with the same stems.

- [x] **Step 5: Write the Reference front matter and first ten sections**

Use `doc_type: reference`, `subtype: runtime`, `status: active`,
`authority: descriptive`, `last_verified: 2026-08-09`, and the implementation
source paths from the approved Design. Cover the system boundary, surface map,
deep links, graph drafts, module/bridge descriptors, validation, compilation,
dry-run, and activation without describing draft state as active execution.

- [x] **Step 6: Write the operator workflow and final ten sections**

Cover run modes/effects, grouped API families, timeline/artifacts, approvals and
stop controls, persistence ownership, error recovery, verification evidence,
known gaps, and related documents. Include the five required tables and embed
all figures with exact captions.

- [x] **Step 7: Validate the Reference and figures**

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/pytest -q tests/unit/test_documentation_validation.py -k runtime_ide
```

Expected before manifest/navigation work: the document-level test passes; the
repository validator may not yet inspect the ungoverned new Reference.

- [x] **Step 8: Commit the Reference and figures**

```bash
git add docs/runtime/runtime_ide.md docs/runtime/assets/figures
git commit -m "docs: add illustrated Runtime IDE reference"
```

### Task 3: Connect Navigation and Governance

**Files:**
- Modify: `README.md`
- Modify: `README.ko.md`
- Modify: `README.en.md`
- Modify: `docs/README.md`
- Modify: `docs/runtime/langgraph_runtime.md`
- Modify: `docs/document_manifest.yaml`
- Modify: `docs/standards/documentation_standard.md`

**Interfaces:**
- Consumes: the governed Reference and figure inventory from Tasks 1-2.
- Produces: root/language/documentation/runtime entry points and a normative Runtime IDE figure contract.

- [x] **Step 1: Add root and language README links**

Link the existing Runtime IDE page rows to
`docs/runtime/runtime_ide.md`. Keep route, implementation files, and concise
capability summary; do not copy the detailed API table into root READMEs.

- [x] **Step 2: Add documentation-index navigation**

Add the Runtime IDE Reference to audience paths, the Reference row, the `/ide`
page map, and runtime folder navigation. Link figures only from the owning
Reference unless a concise figure entry materially improves discovery.

- [x] **Step 3: Link the engine companion**

Add `docs/runtime/runtime_ide.md` to `langgraph_runtime.md` `related_docs` and
the final Related Documents section with text identifying it as the operator/UI
companion.

- [x] **Step 4: Govern the Reference and figure contract**

Add `docs/runtime/runtime_ide.md` to `docs/document_manifest.yaml`. Add a
`Runtime IDE Reference Figures` section to the Documentation Standard naming
the document, three stems, DOT/SVG/caption requirements, edge semantics,
inspection boundary, and required root/index/runtime navigation.

- [x] **Step 5: Run governance and navigation validation**

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/pytest -q tests/unit/test_documentation_validation.py
```

Expected: PASS.

- [ ] **Step 6: Commit navigation and governance**

```bash
git add README.md README.ko.md README.en.md docs/README.md docs/runtime/langgraph_runtime.md docs/document_manifest.yaml docs/standards/documentation_standard.md
git commit -m "docs: govern Runtime IDE reference navigation"
```

### Task 4: Verify Runtime IDE Documentation and Publish

**Files:**
- Verify: all files changed in Tasks 1-3.

**Interfaces:**
- Consumes: the final Reference, figures, validator contract, navigation, and existing Runtime IDE implementation/tests.
- Produces: verified documentation commits pushed to `origin/main` with the unrelated `.env.example` change left local.

- [ ] **Step 1: Verify figure rendering determinism**

Render all `runtime_ide_*.dot` files to an explicit temporary directory and use
`cmp` against the checked-in SVG files. Expected: all three pairs are
byte-identical.

- [ ] **Step 2: Run documentation validation and tests**

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/pytest -q tests/unit/test_documentation_validation.py
```

Expected: PASS.

- [ ] **Step 3: Run focused Runtime IDE implementation tests**

```bash
.venv/bin/pytest -q tests/unit/test_langgraph_runtime.py -k 'validate or compile or dry_run or activated_graph or approval or artifact'
.venv/bin/python -m py_compile tests/ui/runtime_ide_browser_audit.py
```

Expected: PASS. Browser execution requires a running server and WebDriver and
is reported separately if unavailable.

- [ ] **Step 4: Verify all repository Markdown links and archive integrity**

Run the existing read-only repository link and oldversion manifest checks used
by the previous documentation cleanup. Expected: zero missing tracked local
links and eleven valid archived PNG entries.

- [ ] **Step 5: Review scope and commit state**

```bash
git diff --check HEAD
git status --short
git log --oneline -4
```

Expected: `.env.example` is the only unrelated working-tree change and is not
staged or committed.

- [ ] **Step 6: Push and verify remote synchronization**

```bash
git push origin main
git status -sb
git rev-parse HEAD
git rev-parse origin/main
```

Expected: local `HEAD` equals `origin/main`; `.env.example` remains local.
