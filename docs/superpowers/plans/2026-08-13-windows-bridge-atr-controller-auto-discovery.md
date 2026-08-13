# Windows Bridge ATR Controller Auto-Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make installed and portable Windows bridge packages automatically discover, verify, and remember the Linux ATR controller so `/skills` works without a hard-coded IP or manual environment variable.

**Architecture:** Keep the deployed bridge self-contained by implementing a bounded `ATRControllerResolver` in the existing single-file Windows server and mirroring that server to the legacy install copy. The resolver applies explicit/saved/authenticated-peer/subnet/local precedence, persists only redacted non-secret state under the active data root, and becomes the sole source of controller URLs for Skill proxy calls. The HTTP handler adds authenticated peer learning and bounded controller-management endpoints; package launchers continue supplying the existing data root.

**Tech Stack:** Python 3.11+ standard library (`ipaddress`, `socket`, `concurrent.futures`, `urllib`, atomic `pathlib` writes), PowerShell launch/install scripts, built-in `http.server`, pytest, Selenium GUI audit.

## Global Constraints

- Do not embed `192.168.50.146` or any deployment-specific controller IP in source or release artifacts.
- Preserve `WINDOWS_PYAUTOGUI_ATR_API_URL` as the highest-priority explicit override.
- Unauthenticated bridge requests must never learn or persist a controller address.
- Discovery may read ATR identity endpoints only; it must never call equipment execution endpoints.
- Automatic scanning is limited to private IPv4 `/24` networks and TCP port `7860` with bounded concurrency and deadline.
- Multiple verified ATR controllers require operator selection; probe completion order must not choose one.
- Existing bridge tokens, programs, locators, recordings, artifacts, and PyAutoGUI execution behavior must remain unchanged.
- Keep `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py` and `install/windows_pyautogui_bridge_server.py` byte-identical.
- Do not commit or push implementation changes unless the user requests it after verification.

---

### Task 1: Controller Candidate Validation And Persistent Resolution

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Produces: `ATRControllerResolver(data_root: Path, explicit_url: str = "", verifier: Callable | None = None, scanner: Callable | None = None)`.
- Produces: `resolve(*, allow_scan: bool = False) -> dict[str, Any]`, `observe_authenticated_peer(peer_ip: str) -> dict[str, Any]`, `discover() -> dict[str, Any]`, `select(candidate_url: str) -> dict[str, Any]`, and `status() -> dict[str, Any]`.
- Produces: persisted schema `atr.windows_controller_connection.v1` at `<data_root>/controller_connection.json`.

- [ ] **Step 1: Write failing resolver precedence and verification tests**

Add tests using a local `ThreadingHTTPServer` that serves either a valid ATR payload or malformed/non-ATR payload. Cover explicit override, saved record, private candidate acceptance, public/self/redirect/non-JSON rejection, and invalid explicit override diagnostics.

```python
def test_controller_resolver_prefers_verified_explicit_url(tmp_path: Path, atr_identity_server: str) -> None:
    module = _load_packaged_helper_module()
    resolver = module.ATRControllerResolver(tmp_path, explicit_url=atr_identity_server)
    result = resolver.resolve()
    assert result["ok"] is True
    assert result["source"] == "environment"
    assert result["controller_url"] == atr_identity_server


def test_controller_resolver_does_not_fallback_from_invalid_explicit_override(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    resolver = module.ATRControllerResolver(tmp_path, explicit_url="http://127.0.0.1:1")
    result = resolver.resolve()
    assert result["ok"] is False
    assert result["failure_code"] == "ATR_CONTROLLER_EXPLICIT_URL_INVALID"
```

- [ ] **Step 2: Run the resolver tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'controller_resolver'
```

Expected: FAIL because `ATRControllerResolver` does not exist.

- [ ] **Step 3: Implement minimal resolver, validation, and atomic record persistence**

Add URL normalization, identity verification, record load/save, freshness timestamps, explicit/saved precedence, normalized failures, and a secret-key rejection check. Use a same-directory temporary file and `Path.replace()` for atomic persistence. An explicit override must be verified but never written as an automatically discovered source.

- [ ] **Step 4: Mirror the server and verify GREEN**

Apply the same changes to the legacy install server, then run:

```bash
cmp Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py
.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'controller_resolver'
```

Expected: byte comparison succeeds and resolver tests pass.

### Task 2: Authenticated Peer Learning And Safe Subnet Discovery

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Consumes: `ATRControllerResolver` from Task 1.
- Produces: `_private_ipv4_probe_candidates(local_addresses: Iterable[str]) -> list[str]`.
- Produces: peer observation that only runs after `_require_auth()` succeeds.

- [ ] **Step 1: Write failing authenticated-peer and scan-bound tests**

Cover valid authenticated peer persistence, unauthenticated non-persistence, self/loopback/public rejection, deduplicated `/24` candidates, port `7860` only, total candidate cap, negative-result cache, and multiple-controller ambiguity.

```python
def test_authenticated_request_offers_peer_to_controller_resolver(module, bridge_server, monkeypatch) -> None:
    observed = []
    monkeypatch.setattr(module.CONTROLLER_RESOLVER, "observe_authenticated_peer", observed.append)
    response = authenticated_get(bridge_server, "/health")
    assert response.status == 200
    assert observed == [bridge_server.client_ip]


def test_discovery_does_not_choose_between_multiple_verified_controllers(tmp_path: Path) -> None:
    resolver = module.ATRControllerResolver(tmp_path, scanner=lambda: [first_url, second_url])
    result = resolver.discover()
    assert result["ok"] is False
    assert result["failure_code"] == "ATR_CONTROLLER_MULTIPLE_CANDIDATES"
    assert result["candidates"] == sorted([first_url, second_url])
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'authenticated_peer or controller_discovery or private_ipv4_probe'
```

Expected: FAIL because peer learning and bounded scanning are absent.

- [ ] **Step 3: Implement peer learning and bounded subnet probing**

Call peer observation only after token authentication succeeds. Enumerate active private IPv4 addresses, reduce broader masks to a maximum `/24`, exclude self/broadcast/loopback/link-local addresses, and probe with a bounded `ThreadPoolExecutor`. Cache negative scans and return sorted verified candidates.

- [ ] **Step 4: Verify GREEN and legacy-copy equality**

Run:

```bash
cmp Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py
.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'authenticated_peer or controller_discovery or private_ipv4_probe'
```

Expected: all focused tests pass.

### Task 3: Skill Proxy, Health, And Controller Management API Integration

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `Pyautogui_server_for_window/tests/smoke_test.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Consumes: resolver APIs from Tasks 1–2.
- Produces: `GET /controller`, `POST /controller/discover`, and `POST /controller/select`.
- Changes: `_atr_api_request()` obtains the verified base URL from the resolver rather than module constant `ATR_API_URL`.
- Changes: `_health()` adds a redacted `atr_controller` object.

- [ ] **Step 1: Write failing HTTP integration tests**

Start a local bridge and fake ATR server. Prove `/health` teaches the peer, `/skills` forwards to the learned controller, an unauthenticated request cannot mutate state, controller endpoints require auth, selection rejects non-ATR targets, and health never exposes bridge tokens or response bodies.

- [ ] **Step 2: Run HTTP tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'controller_http or skills_uses_resolved_controller'
```

Expected: FAIL because controller endpoints and resolver-backed forwarding do not exist.

- [ ] **Step 3: Integrate the resolver with HTTP handling**

Initialize the resolver from `WINDOWS_PYAUTOGUI_DATA_ROOT`, falling back to the artifact root's parent only for direct legacy execution. Replace the module-level localhost concatenation in `_atr_api_request()`. Add authenticated controller endpoints and the health summary. Keep bridge startup and local program execution available when the controller is unresolved.

- [ ] **Step 4: Extend smoke coverage and verify GREEN**

Update the smoke server configuration to use a temporary data root and assert controller status without external scanning. Run:

```bash
.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'controller_http or skills_uses_resolved_controller'
.venv/bin/python Pyautogui_server_for_window/tests/smoke_test.py
```

Expected: focused tests and smoke test pass.

### Task 4: Operator Console Discovery And Selection Surface

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `tests/ui/windows_bridge_gui_browser_audit.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Consumes: controller endpoints from Task 3.
- Produces: visible controller status, `Discover ATR` action, manual verified URL input, and deterministic multiple-candidate selection in the existing Bridge Connection panel.

- [ ] **Step 1: Write failing static and browser assertions**

Require stable DOM IDs `controllerStatus`, `controllerUrl`, `discoverController`, `controllerCandidates`, and `saveController`. Extend the Selenium audit to assert the controls exist, retain the Device Bridge layout, and do not expose secrets.

- [ ] **Step 2: Run the focused UI tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'controller_console'
```

Expected: FAIL because the controller UI is absent.

- [ ] **Step 3: Implement the minimal console controls**

Render redacted status from `/controller`, call `/controller/discover` on demand, render all verified candidates without auto-selecting multiple matches, and submit manual/candidate selection through `/controller/select`. Preserve the existing token and program-manager behavior.

- [ ] **Step 4: Verify static and browser behavior**

Run the static tests and authenticated browser audit against a local smoke server. Expected: no missing IDs, no horizontal overflow, controller controls operate, and no recording or equipment action begins.

### Task 5: Installed And Portable Package Contracts

**Files:**
- Modify: `tests/unit/test_install_packaging.py`
- Modify: `Pyautogui_server_for_window/examples/windows_bridge.env.example.ps1`
- Modify: `Pyautogui_server_for_window/README.md`
- Modify: `Pyautogui_server_for_window/docs/USAGE.md`
- Modify: `docs/hardware/windows_pyautogui_bridge_windows_setup.md`
- Modify: `docs/device_bridges/windows_pyautogui_bridge.md`

**Interfaces:**
- Consumes: `WINDOWS_PYAUTOGUI_DATA_ROOT` and resolver behavior from Tasks 1–4.
- Produces: release contract that contains discovery-capable server/docs but excludes runtime controller state.

- [ ] **Step 1: Write failing packaging tests**

Require the environment example to document the optional override, require both server copies to contain the persisted schema and discovery failure codes, and forbid `controller_connection.json` from source-only portable output and standard release inputs.

- [ ] **Step 2: Run packaging tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_install_packaging.py -k 'windows_bridge'
```

Expected: at least the optional override/discovery documentation assertion fails.

- [ ] **Step 3: Update package guidance without embedding an IP**

Document zero-configuration peer learning, bounded fallback discovery, multiple-candidate selection, state-file location, optional explicit override, and upgrade behavior. Do not add a generated controller record to either package.

- [ ] **Step 4: Verify installed and portable release contracts**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_install_packaging.py -k 'windows_bridge'
release_dir=$(mktemp -d /tmp/atr-windows-package.XXXXXX)
.venv/bin/python Pyautogui_server_for_window/scripts/build_portable_release.py --output "$release_dir/release" --source-only
test ! -e "$release_dir/release/controller_connection.json"
```

Expected: package tests pass, the source-only release builds, and no runtime discovery record is bundled.

### Task 6: Regression, Package Build, And Cross-Host Acceptance

**Files:**
- Verify only unless a regression requires a scoped correction.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: distributable package and acceptance evidence.

- [ ] **Step 1: Run static and complete bridge regression tests**

```bash
.venv/bin/python -m py_compile \
  Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py \
  install/windows_pyautogui_bridge_server.py \
  device_bridges/windows_pyautogui_bridge.py \
  mcp_tools/equipment_tools.py \
  agents/equipment_agent.py
cmp Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py
.venv/bin/pytest -q \
  tests/unit/test_windows_pyautogui_bridge_server_helper.py \
  tests/unit/test_equipment_pyautogui_bridge.py \
  tests/integration/test_equipment_skill_api.py \
  tests/unit/test_install_packaging.py
.venv/bin/python Pyautogui_server_for_window/tests/smoke_test.py
```

Expected: zero failures; existing deprecation warnings may remain but no new discovery warnings appear.

- [ ] **Step 2: Build a fresh release artifact**

Use the available builder for the target distribution. If PowerShell is unavailable on Linux, build and validate the source-only portable ZIP with the Python builder and record that native PowerShell packaging still requires Windows CI or a Windows host.

- [ ] **Step 3: Redeploy to the Windows test host**

Replace only the installed package code. Preserve `<data-root>/.bridge_token`, programs, locators, recordings, artifacts, and any existing verified controller record. Restart the bridge in the interactive Windows desktop session.

- [ ] **Step 4: Verify zero-configuration cross-host communication**

Ensure `WINDOWS_PYAUTOGUI_ATR_API_URL` is unset. From ATR, call `/api/equipment/windows/test`, then verify the Windows `/controller` status learned the ATR source IP and `/skills` returns HTTP 200 with 13 Skills. Restart the bridge and prove the saved controller is reused.

- [ ] **Step 5: Re-run safe end-to-end acceptance**

Verify ATR-proxied `/health`, `/programs`, `/skills`, screenshot capture with SHA-256 round trip, request-log confirmation guard, and safe `program1`. Do not start UTM motion or recording. Report any remaining locator-readiness warning separately from controller discovery.

- [ ] **Step 6: Inspect repository state and hand off without committing**

Run `git status --short --branch` and `git diff --check`. Summarize modified files, exact test counts, generated packages, Windows-side diagnostic artifacts, and any environment limitation. Do not commit or push implementation changes unless explicitly requested.
