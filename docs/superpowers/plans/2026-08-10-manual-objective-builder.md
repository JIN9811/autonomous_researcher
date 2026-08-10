# Manual Objective Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a template-free visual expression-tree builder and synchronized advanced JSON editor that create human-authored `objective_spec.v1` drafts through the existing Objective Compiler lifecycle.

**Architecture:** A new server-side authoring manifest exposes the compiler's bounded operators, units, child slots, and limits. `ObjectiveService.create_manual_draft()` normalizes identity, provenance, registry version, lifecycle, and immutable version before reusing `create_draft()`. A standalone browser module owns the canonical manual spec and JSON buffer; `bo.js` connects that module to the BO Workspace and the existing Validate, Preview, Approve, and Activate controls.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest, vanilla JavaScript, Node.js `node:test`, HTML/CSS, Selenium/Firefox browser audit.

## Global Constraints

- Preserve the existing deterministic compiler, evaluator, Analysis, Knowledge, BO, Guardian, and Live GUI execution paths.
- Manual input must never execute Python, JavaScript, shell, Cypher, filesystem, or network operations.
- Visual and JSON authoring must converge on one canonical `objective_spec.v1` draft.
- Invalid JSON must not replace the last valid visual tree.
- The server must assign lifecycle, author provenance, Metric Registry version, timestamps, and immutable version.
- Manual drafts must pass the existing Validate, Preview, Approve, and Activate gates.
- The visual builder must support every enabled operator in the server authoring manifest without fixed objective templates.
- Keep the user-owned `.env.example` modification unstaged and unchanged.
- Do not push to GitHub unless the user explicitly requests it.

---

## File Map

- Create `objectives/authoring.py`: server-owned authoring manifest and manual draft normalization inputs.
- Modify `objectives/service.py`: manual draft creation and immutable revision rules.
- Modify `app/main.py`: authoring-contract and manual-draft request/response routes.
- Create `web/static/objective_builder.js`: pure AST state operations, JSON synchronization, browser persistence, and DOM tree editor.
- Modify `web/templates/bo.html`: authoring mode switcher, metadata controls, tree workspace, JSON editor, and manual draft action.
- Modify `web/static/bo.js`: fetch authoring manifest, connect builder callbacks, submit manual drafts, and load saved versions for revision.
- Modify `web/static/styles.css`: compact responsive builder, tree hierarchy, validation, focus, and drag states.
- Modify `tests/unit/test_objective_service.py`: manual provenance, version, conflict, and semantic validation behavior.
- Modify `tests/integration/test_objective_api.py`: authoring manifest and manual lifecycle API coverage.
- Modify `tests/integration/test_bo_gui_api.py`: required manual builder surfaces and script loading.
- Create `tests/js/objective_builder.test.js`: canonical-state, tree mutation, JSON recovery, and persistence-key tests.
- Modify `tests/ui/bo_objective_compiler_browser_audit.py`: real manual authoring interactions and responsive overflow checks.
- Modify `docs/agents/bo_agent.md`: operator-authored objective workflow.
- Modify `docs/agents/bo_agent_runtime_guideline.txt`: runtime gate and provenance rules.
- Modify `docs/runtime/architecture.md`: add manual and LLM authoring convergence.

---

### Task 1: Server-Owned Authoring Contract

**Files:**
- Create: `objectives/authoring.py`
- Modify: `app/main.py`
- Test: `tests/integration/test_objective_api.py`

**Interfaces:**
- Produces: `objective_authoring_manifest() -> dict[str, object]`
- Produces: `GET /api/objectives/authoring-contract`
- Consumes: `objectives.compiler.OPERATOR_KEYS`, `MAX_AST_DEPTH`, `MAX_AST_NODES`, `UNIT_DIMENSIONS`

- [ ] **Step 1: Write the failing authoring-contract API test**

Add a test that asserts the endpoint returns the compiler limits, supported units,
and one descriptor per compiler operator. It must mark `reference` disabled and
must describe child slots for representative variadic, unary, binary, weighted,
and comparison operators.

```python
def test_objective_api_exposes_server_owned_authoring_contract(tmp_path, monkeypatch) -> None:
    client, _ = client_for(tmp_path, monkeypatch)

    response = client.get("/api/objectives/authoring-contract")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["limits"] == {"max_depth": 16, "max_nodes": 256}
    assert "MPa" in payload["units"]
    operators = {item["op"]: item for item in payload["operators"]}
    assert operators["metric"]["kind"] == "leaf"
    assert operators["add"]["children"] == {"mode": "args", "minimum": 2}
    assert operators["weighted_sum"]["children"]["mode"] == "terms"
    assert operators["divide"]["children"]["slots"] == ["numerator", "denominator"]
    assert operators["reference"]["enabled"] is False
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
pytest -q tests/integration/test_objective_api.py::test_objective_api_exposes_server_owned_authoring_contract
```

Expected: fail with `404 Not Found` for `/api/objectives/authoring-contract`.

- [ ] **Step 3: Implement the authoring manifest**

Create a focused module that imports compiler constants and returns JSON-safe
descriptors. The descriptor must include `op`, `label`, `category`, `kind`,
`enabled`, `children`, and `fields`. Use explicit descriptors for operator-specific
controls, then assert at import/test time that descriptor keys equal
`OPERATOR_KEYS` so the UI contract cannot silently drift.

```python
def objective_authoring_manifest() -> dict[str, object]:
    return {
        "schema_version": "objective_authoring_manifest.v1",
        "operators": [OPERATOR_DESCRIPTORS[name] for name in sorted(OPERATOR_KEYS)],
        "units": sorted(UNIT_DIMENSIONS),
        "limits": {"max_depth": MAX_AST_DEPTH, "max_nodes": MAX_AST_NODES},
    }
```

Add a read-only FastAPI route returning `{"ok": True, **manifest}`. The route
must not inspect or mutate objective state.

- [ ] **Step 4: Run authoring-contract and compiler tests**

Run:

```bash
pytest -q tests/integration/test_objective_api.py::test_objective_api_exposes_server_owned_authoring_contract tests/unit/test_objective_evaluator.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add objectives/authoring.py app/main.py tests/integration/test_objective_api.py
git commit -m "feat: expose objective authoring contract"
```

---

### Task 2: Manual Draft Lifecycle and API

**Files:**
- Modify: `objectives/service.py`
- Modify: `app/main.py`
- Test: `tests/unit/test_objective_service.py`
- Test: `tests/integration/test_objective_api.py`

**Interfaces:**
- Produces: `ObjectiveService.create_manual_draft(spec: dict[str, Any], *, operator: str, revision_of: str | None = None) -> tuple[ObjectiveSpec, ObjectiveValidation]`
- Produces: `POST /api/objectives/manual`
- Consumes: `ObjectiveStore.latest_version()`, `ObjectiveService.create_draft()`, `validate_objective()`

- [ ] **Step 1: Write failing service tests for normalization and immutable versions**

Add focused tests covering a new objective, a revision, an accidental overwrite,
and an invalid unit combination.

```python
def test_manual_draft_normalizes_server_owned_fields(tmp_path) -> None:
    service = objective_service(tmp_path)
    draft, validation = service.create_manual_draft(
        manual_spec(objective_id="manual-strength", version=99),
        operator="JIN",
    )
    assert draft.version == 1
    assert draft.lifecycle == "draft"
    assert draft.created_by == "operator:JIN"
    assert draft.metric_registry_version == service.registry.version
    assert draft.metadata["authoring_mode"] == "manual"
    assert validation.valid is True


def test_manual_revision_uses_next_version_without_overwrite(tmp_path) -> None:
    service = objective_service(tmp_path)
    first, _ = service.create_manual_draft(manual_spec(), operator="JIN")
    revised, _ = service.create_manual_draft(
        manual_spec(version=1, expression={"op": "square", "arg": metric_node()}),
        operator="JIN",
        revision_of=first.objective_id,
    )
    assert revised.version == 2
    assert service.store.load_spec(first.objective_id, 1).expression == first.expression
    assert revised.metadata["parent_version"] == 1
```

Also assert that calling without `revision_of` for an existing id raises
`ObjectiveConflict`, and that a structurally valid mixed-unit draft is saved but
returns `validation.valid is False`.

- [ ] **Step 2: Run service tests and verify RED**

Run:

```bash
pytest -q tests/unit/test_objective_service.py -k manual
```

Expected: fail because `create_manual_draft` does not exist.

- [ ] **Step 3: Implement `create_manual_draft`**

Normalize a copied payload before Pydantic parsing. Ignore client values for
`version`, `lifecycle`, `created_by`, `created_at`, and
`metric_registry_version`. For a new id, reject an existing store id. For a
revision, require the same id and assign `latest + 1`. Add manual provenance and
parent identity to metadata, call `create_draft()`, compute validation, persist
the validation, and return both objects.

```python
def create_manual_draft(self, spec, *, operator, revision_of=None):
    payload = dict(spec)
    objective_id = str(payload.get("objective_id") or "").strip()
    # Resolve new/revision version against ObjectiveStore; never trust client version.
    payload.update({
        "version": resolved_version,
        "lifecycle": "draft",
        "created_by": f"operator:{operator.strip()}",
        "metric_registry_version": self.registry.version,
        "created_at": now_iso(),
        "metadata": normalized_metadata,
    })
    draft = self.create_draft(payload)
    validation = validate_objective(draft, self.registry)
    self.store.save_validation(validation)
    return draft, validation
```

- [ ] **Step 4: Write failing manual endpoint tests**

Add `ObjectiveManualDraftRequest` coverage for a new draft and a revision. Assert
the response contains `source=manual`, normalized objective fields, validation,
and `409` for immutable id conflicts. Assert a payload with an unexpected `code`
field maps to `422` and does not create a spec file.

- [ ] **Step 5: Run endpoint tests and verify RED**

Run:

```bash
pytest -q tests/integration/test_objective_api.py -k manual
```

Expected: fail with `404 Not Found` for `/api/objectives/manual`.

- [ ] **Step 6: Implement the request model and route**

```python
class ObjectiveManualDraftRequest(BaseModel):
    spec: dict[str, object]
    operator: str = Field(..., min_length=1, max_length=160)
    revision_of: str | None = Field(default=None, min_length=1)
```

The route delegates to `create_manual_draft()` and returns model-dumped draft and
validation objects. Reuse existing Objective error mapping: malformed/prohibited
contracts become `422`, conflicts become `409`, and paths are not exposed.

- [ ] **Step 7: Run service and API regression tests**

Run:

```bash
pytest -q tests/unit/test_objective_service.py tests/integration/test_objective_api.py tests/integration/test_objective_compiler_closed_loop.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add objectives/service.py app/main.py tests/unit/test_objective_service.py tests/integration/test_objective_api.py
git commit -m "feat: create operator-authored objective drafts"
```

---

### Task 3: Canonical Browser AST State Engine

**Files:**
- Create: `web/static/objective_builder.js`
- Create: `tests/js/objective_builder.test.js`

**Interfaces:**
- Produces: `ObjectiveBuilder.createState(options)`
- Produces: `state.snapshot()`, `state.setMetadata()`, `state.replaceNode()`, `state.addChild()`, `state.duplicateNode()`, `state.moveNode()`, `state.removeNode()`, `state.applyJson()`, `state.restoreLastValid()`, `state.markSaved()`
- Consumes: server authoring manifest and Metric Registry payload

- [ ] **Step 1: Write failing Node tests for canonical state**

Use `node:test` and `node:assert/strict`. Tests must demonstrate behavior rather
than DOM implementation.

```javascript
test("visual mutation updates canonical JSON without mutating the prior snapshot", () => {
  const state = createState({ manifest, metrics, storage: memoryStorage });
  const before = state.snapshot();
  state.replaceNode("expression", { op: "metric", metric_id: "compressive_strength_mpa" });
  assert.equal(JSON.parse(state.snapshot().jsonBuffer).expression.metric_id, "compressive_strength_mpa");
  assert.notDeepEqual(state.snapshot().lastValidSpec, before.lastValidSpec);
  assert.equal(before.lastValidSpec.expression.op, "literal");
});

test("invalid JSON preserves the last valid visual tree", () => {
  const state = createState({ manifest, metrics, storage: memoryStorage });
  const before = state.snapshot().lastValidSpec;
  const result = state.applyJson('{"expression":');
  assert.equal(result.ok, false);
  assert.deepEqual(state.snapshot().lastValidSpec, before);
});
```

Cover nested add/move/delete, weighted terms, Boolean constraint roots, metric
allowlisting, disabled operators, max depth/node limits, revision identity, dirty
state, and browser-storage restoration.

- [ ] **Step 2: Run Node tests and verify RED**

Run:

```bash
node --test tests/js/objective_builder.test.js
```

Expected: fail because `web/static/objective_builder.js` does not exist.

- [ ] **Step 3: Implement pure immutable tree operations**

Use stable paths such as `expression.args.0` and `constraints.0.args.1`.
Operations clone only through JSON-safe structured cloning, enforce manifest
child modes, and reject unknown metrics/operators. Provide default node factories
from manifest descriptors rather than objective templates.

`applyJson(text)` must return:

```javascript
{ ok: true, spec }
// or
{ ok: false, errors: [{ path: "$", message: "Unexpected end of JSON input" }] }
```

The module must support both environments:

```javascript
if (typeof module !== "undefined" && module.exports) module.exports = api;
if (typeof window !== "undefined") window.ObjectiveBuilder = api;
```

- [ ] **Step 4: Add browser persistence and save normalization tests**

Assert that storage is scoped to one key, malformed stored content is ignored,
`markSaved(serverSpec)` clears dirty state, and a newer server version is not
silently replaced by stored browser content.

- [ ] **Step 5: Run Node tests and verify GREEN**

Run:

```bash
node --test tests/js/objective_builder.test.js
```

Expected: all tests pass without warnings.

- [ ] **Step 6: Commit Task 3**

```bash
git add web/static/objective_builder.js tests/js/objective_builder.test.js
git commit -m "feat: add objective builder state engine"
```

---

### Task 4: BO Workspace Manual Builder UI

**Files:**
- Modify: `web/templates/bo.html`
- Modify: `web/static/objective_builder.js`
- Modify: `web/static/bo.js`
- Modify: `web/static/styles.css`
- Modify: `tests/integration/test_bo_gui_api.py`

**Interfaces:**
- Consumes: `GET /api/objectives/authoring-contract`, `GET /api/objectives/metrics`, `POST /api/objectives/manual`
- Produces DOM IDs: `objective-author-mode`, `objective-manual-builder`, `objective-manual-metadata`, `objective-expression-builder`, `objective-constraints-builder`, `objective-json-editor`, `objective-json-errors`, `btn-objective-json-apply`, `btn-objective-json-restore`, `btn-objective-json-format`, `btn-objective-manual-save`
- Integrates: existing selected objective, validation, preview, approval, activation, version diff, and status rendering

- [ ] **Step 1: Extend the BO HTML integration test and verify RED**

Assert all manual builder IDs exist, the new script is loaded before `bo.js`, and
there is no raw `eval`, function-body, or objective-template input.

```python
def test_bo_workspace_contains_manual_visual_and_json_authoring() -> None:
    html = TestClient(app).get("/bo").text
    for element_id in (
        "objective-author-mode",
        "objective-manual-builder",
        "objective-expression-builder",
        "objective-constraints-builder",
        "objective-json-editor",
        "btn-objective-json-apply",
        "btn-objective-manual-save",
    ):
        assert f'id="{element_id}"' in html
    assert html.index("/static/objective_builder.js") < html.index("/static/bo.js")
```

Run:

```bash
pytest -q tests/integration/test_bo_gui_api.py::test_bo_workspace_contains_manual_visual_and_json_authoring
```

Expected: fail because manual surfaces are absent.

- [ ] **Step 2: Add mode switcher and authoring surfaces**

Preserve the current BO visual system. Put `AI Compose`, `Visual Builder`, and
`Advanced JSON` in a compact segmented control below the Objective Compiler
header. Keep lifecycle controls outside mode panels so all authoring modes use
the same gates.

The Visual panel contains metadata, Expression, Constraints, and one `Create
Manual Draft` action. The JSON panel contains the complete spec editor, inline
errors, `Format JSON`, `Apply to Builder`, and `Restore Last Valid`.

- [ ] **Step 3: Implement accessible recursive tree rendering**

Add DOM rendering to `objective_builder.js`. Each node row must contain an
operator selector, operator-specific fields, inferred validation message slot,
and icon/text buttons for add, duplicate, move up/down, and delete. Render child
containers recursively with indentation. Implement drag-and-drop as an optional
shortcut calling the same `moveNode()` operation used by buttons.

Use `textContent` or escaped values for operator, metric, name, unit, and error
output. Do not inject operator-authored strings as HTML.

- [ ] **Step 4: Connect manifest, metrics, lifecycle, and revision loading**

During BO initialization, fetch the authoring manifest and Metric Registry,
create the builder state, then mount it. `Create Manual Draft` posts the
canonical spec and selected operator. If an existing objective is selected and
loaded for manual revision, send `revision_of` with that same id.

On success:

1. call `markSaved(response.objective)`;
2. refresh Objective status;
3. select the returned id/version;
4. render returned validation;
5. enable only lifecycle actions permitted by persisted server state.

Unsaved browser edits must never change `objectiveInput`, BO execution settings,
or active objective binding until the server creates a draft.

- [ ] **Step 5: Add responsive and state styling**

Implement a two-column builder at wide widths and one column below 1100 px.
Constrain deep tree scrolling inside the builder, not the whole page. Include
distinct styles for dirty, saved, invalid, drag target, disabled operator,
keyboard focus, constraint roots, and inferred units. Preserve readable focus
contrast in the existing dark theme.

- [ ] **Step 6: Run static, Node, and integration tests**

Run:

```bash
node --test tests/js/objective_builder.test.js
pytest -q tests/integration/test_bo_gui_api.py tests/integration/test_objective_api.py
python -m py_compile app/main.py objectives/authoring.py objectives/service.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add web/templates/bo.html web/static/objective_builder.js web/static/bo.js web/static/styles.css tests/integration/test_bo_gui_api.py
git commit -m "feat: add manual objective builder workspace"
```

---

### Task 5: Browser-Level Lifecycle Verification

**Files:**
- Modify: `tests/ui/bo_objective_compiler_browser_audit.py`
- Test: `tests/ui/bo_objective_compiler_browser_audit.py`

**Interfaces:**
- Consumes: running ATR FastAPI server on a temporary local port
- Produces: screenshots and JSON audit data under `artifacts/ui/objective_compiler/`

- [ ] **Step 1: Extend the browser audit before changing runtime code**

Automate this operator path:

1. open `/bo` at 1920 x 1080;
2. switch to Visual Builder;
3. replace the root with `weighted_sum`;
4. add two metric terms and edit weights;
5. add a `greater_equal` constraint using a metric and literal;
6. switch to Advanced JSON and verify synchronized content;
7. introduce invalid JSON and verify the visual tree remains unchanged;
8. restore and apply valid JSON;
9. save a manual draft and verify lifecycle identity/version;
10. refresh and verify unsaved/saved state restoration;
11. capture desktop and mobile-width screenshots;
12. assert no horizontal overflow and no lifecycle gate opens prematurely.

- [ ] **Step 2: Run the audit and verify the first failure**

Start a temporary server without touching the user's port `7860`:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8799 > /tmp/atr-objective-builder-ui.log 2>&1 &
ATR_UI_PID=$!
python tests/ui/bo_objective_compiler_browser_audit.py --base-url http://127.0.0.1:8799
kill "$ATR_UI_PID"
```

Expected before final UI fixes: audit identifies the first missing interaction,
state, or layout condition rather than silently passing.

- [ ] **Step 3: Fix only observed browser defects**

Correct DOM event wiring, focus, scrolling, responsive layout, or state recovery
reported by the audit. Do not alter Objective evaluation or BO behavior to fix a
presentation issue.

- [ ] **Step 4: Re-run audit and inspect screenshots visually**

Run the same command and inspect:

- `artifacts/ui/objective_compiler/bo_objective_builder_1920x1080.png`
- `artifacts/ui/objective_compiler/bo_objective_builder_mobile.png`
- the existing Live objective runtime screenshot.

Confirm tree controls do not overlap, JSON remains legible, nested nodes remain
traceable, lifecycle controls remain visible, and the existing BO workspace is
not pushed into an unusable layout.

- [ ] **Step 5: Commit Task 5**

```bash
git add tests/ui/bo_objective_compiler_browser_audit.py web/templates/bo.html web/static/objective_builder.js web/static/bo.js web/static/styles.css
git commit -m "test: verify manual objective builder in browser"
```

---

### Task 6: Documentation and Final Regression

**Files:**
- Modify: `docs/agents/bo_agent.md`
- Modify: `docs/agents/bo_agent_runtime_guideline.txt`
- Modify: `docs/runtime/architecture.md`
- Modify: `tests/unit/test_documentation_validation.py`
- Verify: `docs/superpowers/specs/2026-08-10-manual-objective-builder-design.md`

**Interfaces:**
- Documents: manual and LLM authoring convergence, version/provenance behavior, operator workflow, recovery, and safety boundaries

- [ ] **Step 1: Write documentation assertions or validator expectations first**

Add a focused test to `tests/unit/test_documentation_validation.py` that reads
the BO agent reference, BO runtime guideline, and runtime architecture and
requires these terms:

```text
Visual Builder
Advanced JSON
objective_spec.v1
authoring_mode=manual
Draft -> Validate -> Preview -> Approve -> Activate
```

- [ ] **Step 2: Run the documentation test and verify RED**

Run:

```bash
pytest -q tests/unit/test_documentation_validation.py -k manual_objective_authoring
```

Expected: fail because the manual workflow is not yet documented.

- [ ] **Step 3: Update operator and architecture documentation**

Document:

- when to use AI Compose, Visual Builder, and Advanced JSON;
- how visual and JSON state synchronization works;
- how to create a new objective versus a revision;
- why manual authoring cannot bypass lifecycle gates;
- how to recover invalid JSON and unsaved browser state;
- how manual provenance appears in Knowledge and BO lineage;
- that downstream runtime behavior is identical after activation.

- [ ] **Step 4: Run the complete relevant regression suite**

Run:

```bash
node --test tests/js/objective_builder.test.js
pytest -q \
  tests/unit/test_objective_service.py \
  tests/unit/test_objective_evaluator.py \
  tests/integration/test_objective_api.py \
  tests/integration/test_objective_compiler_closed_loop.py \
  tests/integration/test_bo_gui_api.py \
  tests/unit/test_analysis_agent.py \
  tests/unit/test_knowledge_agent.py \
  tests/unit/test_bo_agent.py
python scripts/validate_documentation.py
git diff --check
```

Expected: all targeted tests and validators pass. If unrelated pre-existing tests
fail, record the exact test names and demonstrate they also fail at the starting
commit before classifying them as unrelated.

- [ ] **Step 5: Verify the worktree scope**

Run:

```bash
git status --short
git diff --stat HEAD~5..HEAD
git diff --check
```

Confirm `.env.example` remains unstaged and no device, printer, manipulation,
Vision, Live GUI, or LLM serving files changed outside the listed scope.

- [ ] **Step 6: Commit Task 6**

```bash
git add docs/agents/bo_agent.md docs/agents/bo_agent_runtime_guideline.txt docs/runtime/architecture.md tests/unit/test_documentation_validation.py
git commit -m "docs: explain manual objective authoring"
```

---

## Completion Evidence

The final report must include:

- the exact manual objective used for browser verification;
- its objective id, version, hash, and `created_by` provenance;
- validation and preview outcome;
- confirmation that approval and activation used existing lifecycle routes;
- Node, Python, documentation, and browser-audit command results;
- screenshot paths;
- worktree status showing `.env.example` was not included;
- any unrelated residual test failures with baseline evidence.
