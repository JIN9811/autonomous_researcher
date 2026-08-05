# Common Equipment Workspace and UTM Test Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Windows-only UTM setup page into a reusable Lab Equipment Workspace where UTM is the first selectable profile and test/live execution share the existing Windows PyAutoGUI bridge contract.

**Architecture:** Add a small, explicit equipment profile registry that owns bridge selection, allowed programs, readiness requirements, and evidence expectations. The FastAPI workspace and Equipment Agent consume this registry; test mode sends `simulate_utm_protocol=true` to the existing Windows package while live mode sends the same registered program through the same selected bridge with simulation disabled.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, existing Windows PyAutoGUI bridge package, vanilla HTML/CSS/JavaScript, pytest, Selenium browser audit.

## Global Constraints

- Reuse `Pyautogui_server_for_window`; do not create a second virtual HTTP server or Windows package.
- Never expose bridge token values in API responses, artifacts, HTML, JavaScript state, or logs.
- Equipment execution may invoke only registered `program_id` values through existing `equipment.pyautogui.*` tools.
- Test and live must use the same selected profile, endpoints, program IDs, locators, evidence schema, and Analysis handoff schema.
- Test mode uses `simulate_utm_protocol=true`; live mode uses `simulate_utm_protocol=false` and may not silently simulate.
- No physical UTM command is issued by automated tests.
- Preserve current `/equipment/windows` URL as a compatibility redirect or alias while adding the common workspace route.

---

## File Structure

- Create: `utils/equipment_profiles.py`
  - Typed profile registry, UTM default profile, mode-specific execution payload creation, token-safe profile summary.
- Modify: `app/main.py`
  - Common Equipment Workspace route, profile-aware API endpoints, and a
    token-safe reverse proxy for the original selected Windows bridge console.
- Modify: `agents/equipment_agent.py`
  - Resolve the selected profile once, pass its registered program and simulation mode to the existing tool calls, and enforce evidence before Analysis handoff.
- Modify: `graphs/modules/equipment/module.yaml`
  - Rename internal nodes to profile-oriented contract steps without changing the graph stage identity.
- Modify: `graphs/modules/equipment/ui.yaml`
  - Descriptor metadata for the common Equipment Workspace handoff.
- Modify: `web/templates/windows_equipment.html`
  - Add an action that opens the original selected Windows bridge console in a
    separate tab; retain the
    common equipment list, connection, test/runtime, and evidence regions as
    supporting ATR state rather than a second control implementation.
- Modify: `web/static/windows_equipment.js`
  - Fetch profile state, send selected `profile_id`, show mode-specific test/live state, and prevent duplicate button submission.
- Modify: `web/static/styles.css`
  - Add compact profile-list and workspace status styles that follow existing Device Workspace styling.
- Modify: `tests/unit/test_equipment_profiles.py`
  - New registry unit tests.
- Modify: `tests/unit/test_equipment_agent.py`
  - Profile resolution and handoff-gating tests.
- Modify: `tests/integration/test_live_gui_runtime_layout.py`
  - FastAPI and HTML/API compatibility tests for the common workspace.
- Modify: `tests/ui/windows_equipment_browser_audit.py`
  - Browser path verification for profile selection and test result rendering.
- Modify: `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`
  - Document the common profile contract, test/live semantics, and UTM as first profile.
- Modify: `docs/hardware/windows_pyautogui_bridge_windows_setup.md`
  - Document how the existing package participates in setup test, protocol test, and live operation.
- Modify: `README.ko.md`, `README.en.md`
  - Update workspace name and entry path documentation.

## Task 1: Create the Equipment Profile Registry

**Files:**
- Create: `utils/equipment_profiles.py`
- Test: `tests/unit/test_equipment_profiles.py`

**Interfaces:**
- Produces `EquipmentProfile`, `EquipmentProfileRegistry`, `DEFAULT_UTM_PROFILE_ID`, and `build_execution_contract(profile, runtime_mode, bridge_config)`.
- Consumes saved Windows bridge settings from existing connection memory through the caller; the registry never reads or returns a token value itself.
- Later tasks use `registry.get(profile_id)` and `contract.to_safe_dict()`.

- [ ] **Step 1: Write the failing registry tests**

```python
from utils.equipment_profiles import (
    DEFAULT_UTM_PROFILE_ID,
    EquipmentProfileRegistry,
    build_execution_contract,
)


def test_default_registry_exposes_utm_as_first_profile() -> None:
    profile = EquipmentProfileRegistry.default().get(DEFAULT_UTM_PROFILE_ID)

    assert profile.label == "UTM"
    assert profile.bridge_provider == "windows_pyautogui"
    assert profile.allowed_program_ids == (
        "utm_compression_start_v1",
        "utm_export_csv_v1",
        "utm_manual_save_csv_v1",
        "utm_stop_or_abort_v1",
    )


def test_test_contract_uses_same_utm_program_with_simulation_enabled() -> None:
    profile = EquipmentProfileRegistry.default().get(DEFAULT_UTM_PROFILE_ID)

    contract = build_execution_contract(
        profile,
        runtime_mode="test",
        bridge_config={"selected_candidate": "utm-pc", "token": "secret"},
    )

    assert contract.program_id == "utm_compression_start_v1"
    assert contract.simulate_utm_protocol is True
    assert "secret" not in contract.to_safe_dict().values()


def test_live_contract_disables_simulation_for_the_same_profile() -> None:
    profile = EquipmentProfileRegistry.default().get(DEFAULT_UTM_PROFILE_ID)

    contract = build_execution_contract(profile, runtime_mode="live", bridge_config={})

    assert contract.program_id == "utm_compression_start_v1"
    assert contract.simulate_utm_protocol is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_equipment_profiles.py -v`

Expected: FAIL because `utils.equipment_profiles` does not exist.

- [ ] **Step 3: Implement the minimal typed registry**

```python
@dataclass(frozen=True)
class EquipmentProfile:
    profile_id: str
    label: str
    bridge_provider: str
    default_program_id: str
    allowed_program_ids: tuple[str, ...]
    required_locators: tuple[str, ...]
    required_evidence: tuple[str, ...]


@dataclass(frozen=True)
class EquipmentExecutionContract:
    profile_id: str
    program_id: str
    simulate_utm_protocol: bool
    required_evidence: tuple[str, ...]

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "program_id": self.program_id,
            "simulate_utm_protocol": self.simulate_utm_protocol,
            "required_evidence": list(self.required_evidence),
        }
```

Implement `EquipmentProfileRegistry.default()` with only `utm_windows_v1` and reject unknown modes or programs with `ValueError`.

- [ ] **Step 4: Run the registry tests to verify they pass**

Run: `pytest tests/unit/test_equipment_profiles.py -v`

Expected: PASS with three tests.

- [ ] **Step 5: Commit the registry unit**

```bash
git add utils/equipment_profiles.py tests/unit/test_equipment_profiles.py
git commit -m "feat: add common equipment profile registry"
```

## Task 2: Add Profile-aware Equipment APIs

**Files:**
- Modify: `app/main.py`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes `EquipmentProfileRegistry` and existing selected Windows bridge memory helpers.
- Produces:
  - `GET /api/equipment/profiles`
  - `GET /api/equipment/profiles/{profile_id}/state`
  - `POST /api/equipment/profiles/{profile_id}/test`
  - `POST /api/equipment/profiles/{profile_id}/preflight`
- Existing `/api/equipment/windows/*` endpoints remain and delegate to `utm_windows_v1`.
  - Provides `GET|POST /equipment/windows/bridge-ui/{path}` as a constrained
  proxy to the selected Windows bridge console. The proxy rejects arbitrary
  hosts and path traversal, injects the saved token server-side, and rewrites
  the console's absolute `fetch()` paths into the proxy namespace.

- [ ] **Step 1: Write failing API tests**

```python
def test_equipment_profiles_returns_token_safe_utm_profile(client) -> None:
    response = client.get("/api/equipment/profiles")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_profile_id"] == "utm_windows_v1"
    assert payload["profiles"][0]["profile_id"] == "utm_windows_v1"
    assert "token" not in str(payload).lower()


def test_profile_test_forces_simulated_utm_contract(client, monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(main_module, "run_windows_pyautogui_program", lambda **kwargs: captured.update(kwargs) or {"ok": True})
    response = client.post(
        "/api/equipment/profiles/utm_windows_v1/test",
        json={"confirm_execute": True},
    )

    assert response.status_code == 200
    assert captured["simulate_utm_protocol"] is True
    assert captured["program_id"] == "utm_compression_start_v1"


def test_profile_preflight_rejects_unknown_profile(client) -> None:
    response = client.post("/api/equipment/profiles/not-registered/preflight", json={})

    assert response.status_code == 404
```

- [ ] **Step 2: Run the targeted API tests to verify they fail**

Run: `pytest tests/integration/test_live_gui_runtime_layout.py -k 'equipment_profiles or profile_test or profile_preflight' -v`

Expected: FAIL because the common profile routes do not exist.

- [ ] **Step 3: Add the shared API adapters**

Add Pydantic request types that accept `confirm_execute`, `include_screenshot`, and `program_id` but validate program IDs through `build_execution_contract`. Implement a token-safe state response with this shape:

```python
{
    "profile": contract.to_safe_dict(),
    "connection": {"selected_candidate": "...", "status": "ready"},
    "readiness": {"status": "ready", "blockers": [], "warnings": []},
    "evidence": {"screenshot": None, "request_log": None, "csv": None},
}
```

For `/test`, invoke the existing registered UTM program with `simulate_utm_protocol=True`; for `/preflight`, perform only non-actuating health/program/locator checks with `simulate_utm_protocol=False`.

- [ ] **Step 4: Run the targeted API tests to verify they pass**

Run: `pytest tests/integration/test_live_gui_runtime_layout.py -k 'equipment_profiles or profile_test or profile_preflight' -v`

Expected: PASS.

- [ ] **Step 5: Commit the API unit**

```bash
git add app/main.py tests/integration/test_live_gui_runtime_layout.py
git commit -m "feat: add profile-aware equipment APIs"
```

## Task 3: Bind the Equipment Agent and Graph Module to the Selected Profile

**Files:**
- Modify: `agents/equipment_agent.py`
- Modify: `graphs/modules/equipment/module.yaml`
- Modify: `graphs/modules/equipment/ui.yaml`
- Modify: `tests/unit/test_equipment_agent.py`

**Interfaces:**
- Consumes `state.current_experiment_spec["equipment_profile_id"]`, defaulting to `utm_windows_v1`.
- Produces `equipment_result["profile_id"]`, `equipment_result["execution_mode"]`, `equipment_result["evidence"]`, and `equipment_handoff` only after the profile contract validates.
- Analysis consumes the existing `utm_data_ready` and CSV keys; their shapes remain backward-compatible.

- [ ] **Step 1: Write failing Equipment Agent tests**

```python
@pytest.mark.asyncio
async def test_agent_uses_selected_utm_profile_in_test_mode(agent_context, test_state) -> None:
    test_state.current_experiment_spec["equipment_profile_id"] = "utm_windows_v1"
    result = await LabEquipmentAgent().run(test_state, agent_context)

    run_call = next(call for call in agent_context.tools.calls if call[0] == "equipment.pyautogui.run")
    assert run_call[1]["program_id"] == "utm_compression_start_v1"
    assert run_call[1]["simulate_utm_protocol"] is True
    assert result.data["equipment_result"]["profile_id"] == "utm_windows_v1"


@pytest.mark.asyncio
async def test_agent_blocks_analysis_handoff_when_profile_evidence_is_incomplete(agent_context, live_state) -> None:
    agent_context.tools.set_result("equipment.pyautogui.run", {"ok": True, "csv_path": ""})
    result = await LabEquipmentAgent().run(live_state, agent_context)

    assert result.data["equipment_handoff"]["status"] == "blocked"
    assert result.data["equipment_result"]["status"] != "complete"
```

- [ ] **Step 2: Run the targeted agent tests to verify they fail**

Run: `pytest tests/unit/test_equipment_agent.py -k 'selected_utm_profile or incomplete' -v`

Expected: FAIL because profile selection and evidence-gated handoff are not represented.

- [ ] **Step 3: Implement bounded profile resolution and evidence gating**

Resolve `equipment_profile_id` before tool planning. Inject only the registry-approved `program_id` and `simulate_utm_protocol` into the existing run payload. Preserve existing explicit sequence support only when its `program_id` is allowed by the selected profile.

Use this handoff predicate:

```python
def profile_evidence_complete(result: dict[str, object], required: tuple[str, ...]) -> bool:
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    return all(bool(evidence.get(key)) for key in required)
```

Map existing screenshot/request-log/CSV result fields into `evidence` before evaluating the predicate. Do not change existing Analysis key names.

Update internal module labels to:

```yaml
internal_graph:
  - id: 01_resolve_equipment_profile
    label: Resolve Equipment Profile
  - id: 02_validate_bridge_contract
    label: Validate Bridge Contract
  - id: 03_execute_registered_protocol
    label: Execute Registered Protocol
  - id: 04_validate_evidence_handoff
    label: Validate Evidence and Handoff
```

- [ ] **Step 4: Run the targeted agent tests to verify they pass**

Run: `pytest tests/unit/test_equipment_agent.py -k 'selected_utm_profile or incomplete' -v`

Expected: PASS.

- [ ] **Step 5: Commit the Agent/graph unit**

```bash
git add agents/equipment_agent.py graphs/modules/equipment/module.yaml graphs/modules/equipment/ui.yaml tests/unit/test_equipment_agent.py
git commit -m "feat: bind equipment agent to profile contracts"
```

## Task 4: Convert the Windows Page into the Common Equipment Workspace

**Files:**
- Modify: `web/templates/windows_equipment.html`
- Modify: `web/static/windows_equipment.js`
- Modify: `web/static/styles.css`
- Modify: `tests/ui/windows_equipment_browser_audit.py`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes `GET /api/equipment/profiles` and profile state/test/preflight endpoints.
- Produces a selected `profile_id` for every action and shows only safe state/evidence metadata.
- Keeps existing Windows bridge controls reachable through the selected UTM profile.

- [ ] **Step 1: Write failing browser/audit tests**

```python
def test_common_equipment_workspace_renders_utm_profile_and_sections(driver, base_url) -> None:
    driver.get(f"{base_url}/equipment/windows")

    assert driver.find_element(By.ID, "equipment-profile-list").is_displayed()
    assert driver.find_element(By.CSS_SELECTOR, "[data-profile-id='utm_windows_v1']").is_displayed()
    assert driver.find_element(By.ID, "equipment-profile-connection").is_displayed()
    assert driver.find_element(By.ID, "equipment-profile-runtime").is_displayed()
    assert driver.find_element(By.ID, "equipment-profile-evidence").is_displayed()


def test_common_equipment_workspace_test_button_disables_until_request_finishes(driver, base_url) -> None:
    driver.get(f"{base_url}/equipment/windows")
    button = driver.find_element(By.ID, "btn-equipment-profile-test")
    button.click()

    assert button.get_attribute("disabled") is not None
```

- [ ] **Step 2: Run the browser/audit tests to verify they fail**

Run: `pytest tests/ui/windows_equipment_browser_audit.py -k 'common_equipment_workspace' -v`

Expected: FAIL because the common workspace IDs are absent.

- [ ] **Step 3: Implement the common workspace layout and behavior**

Keep the `/equipment/windows` page path but change its title to `Lab Equipment Workspace`. Add persistent regions with exact IDs:

```html
<aside id="equipment-profile-list"></aside>
<section id="equipment-profile-connection"></section>
<section id="equipment-profile-runtime"></section>
<section id="equipment-profile-evidence"></section>
```

Use `data-profile-id="utm_windows_v1"` for the initial list card. Button actions must fetch their current selected profile, set their own disabled state before `fetch`, and restore state in `finally`. Render test/live mode and simulation state explicitly; do not display tokens.

- [ ] **Step 4: Run browser and static route tests to verify they pass**

Run: `pytest tests/ui/windows_equipment_browser_audit.py -k 'common_equipment_workspace' -v && pytest tests/integration/test_live_gui_runtime_layout.py -k 'equipment_workspace' -v`

Expected: PASS.

- [ ] **Step 5: Commit the Workspace UI unit**

```bash
git add web/templates/windows_equipment.html web/static/windows_equipment.js web/static/styles.css tests/ui/windows_equipment_browser_audit.py tests/integration/test_live_gui_runtime_layout.py
git commit -m "feat: build common equipment workspace"
```

## Task 5: Verify the Complete Test Bridge Path and Update Documentation

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `tests/unit/test_equipment_agent.py`
- Modify: `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`
- Modify: `docs/hardware/windows_pyautogui_bridge_windows_setup.md`
- Modify: `README.ko.md`
- Modify: `README.en.md`

**Interfaces:**
- Consumes the profile test endpoint and existing packaged bridge helper.
- Produces a recorded test proof that includes simulation mode, registered program ID, screen evidence reference, request-log identity, parseable CSV, and Analysis-ready handoff payload.

- [ ] **Step 1: Write the failing complete-contract tests**

```python
def test_packaged_bridge_simulated_utm_protocol_produces_profile_evidence(tmp_path) -> None:
    module = _load_packaged_helper_module()

    result = module.execute_registered_program(
        program_id="utm_compression_start_v1",
        payload={"simulate_utm_protocol": True, "run_id": "run-profile-test"},
        artifact_root=tmp_path,
    )

    assert result["ok"] is True
    assert result["simulate_utm_protocol"] is True
    assert Path(result["csv_path"]).is_file()
    assert Path(result["screenshot_path"]).is_file()


def test_profile_test_result_is_analysis_ready_only_with_all_evidence(client) -> None:
    response = client.post(
        "/api/equipment/profiles/utm_windows_v1/test",
        json={"confirm_execute": True},
    )

    assert response.status_code == 200
    assert response.json()["analysis_handoff"]["status"] == "ready"
```

- [ ] **Step 2: Run the complete-contract tests to verify they fail**

Run: `pytest tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'profile_evidence' -v && pytest tests/integration/test_live_gui_runtime_layout.py -k 'analysis_ready_only' -v`

Expected: FAIL until profile-linked evidence and handoff fields are emitted.

- [ ] **Step 3: Implement only the missing evidence normalization**

Make the profile test API normalize existing bridge response fields to:

```python
{
    "profile_id": "utm_windows_v1",
    "mode": "test",
    "simulation": True,
    "evidence": {
        "screenshot": "...",
        "request_log": "...",
        "csv": "...",
    },
    "analysis_handoff": {"status": "ready"},
}
```

Return `analysis_handoff.status="blocked"` with an explicit missing-evidence list whenever one required artifact is absent.

- [ ] **Step 4: Run focused and regression tests**

Run:

```bash
pytest tests/unit/test_equipment_profiles.py tests/unit/test_equipment_agent.py tests/unit/test_windows_pyautogui_bridge_server_helper.py -v
pytest tests/integration/test_live_gui_runtime_layout.py -k 'equipment or windows' -v
pytest tests/ui/windows_equipment_browser_audit.py -v
```

Expected: PASS. No automated command contacts the physical UTM.

- [ ] **Step 5: Update documentation**

Document:

- UTM as `utm_windows_v1`, the first common equipment profile;
- exact difference between test simulation and live execution;
- retained use of `Pyautogui_server_for_window`;
- required bridge reachability, token, locators, request-log, screenshot, and CSV evidence;
- common workspace URL and the compatibility purpose of `/equipment/windows`.

- [ ] **Step 6: Commit the verification and documentation unit**

```bash
git add tests/unit/test_windows_pyautogui_bridge_server_helper.py tests/unit/test_equipment_agent.py docs/hardware/windows_pyautogui_equipment_agent_guideline.md docs/hardware/windows_pyautogui_bridge_windows_setup.md README.ko.md README.en.md
git commit -m "docs: document common equipment UTM workflow"
```

## Plan Self-review

- Spec coverage: Tasks 1-3 implement the profile contract and Agent/LangGraph behavior; Task 4 implements the common Workspace; Task 5 verifies test/live evidence semantics and updates all required documentation.
- Placeholder scan: no incomplete implementation markers or generic test instructions remain.
- Type consistency: `profile_id`, `program_id`, `simulate_utm_protocol`, `evidence`, and `analysis_handoff` use the same names across registry, API, Agent, UI, and tests.
- Scope: the plan intentionally registers UTM only; future equipment profiles use the same registry without copying UTM execution code.
