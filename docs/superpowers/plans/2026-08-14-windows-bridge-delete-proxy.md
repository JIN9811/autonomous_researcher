# Windows Bridge GUI DELETE Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the ATR-hosted Windows PyAutoGUI bridge console to delete custom programs and eligible Equipment Skills through the existing token-safe proxy.

**Architecture:** Add `DELETE` to the existing FastAPI bridge-UI route and to the bridge adapter's narrow HTTP-method allowlist. Keep URL selection, path validation, live precheck, token injection, body/query forwarding, and upstream response propagation unchanged.

**Tech Stack:** Python 3.12, FastAPI/Starlette `TestClient`, `httpx`, pytest.

## Global Constraints

- Accept exactly `GET`, `POST`, and `DELETE`; continue rejecting `PUT` and `PATCH`.
- Keep the Windows bridge URL and token server-side.
- Continue targeting only the selected saved Windows bridge candidate.
- Preserve traversal, embedded-scheme, and protocol-relative path rejection.
- Preserve upstream status, content type, and response bytes.
- Do not change the Windows bridge server API or UTM readiness behavior.
- Do not run physical UTM hardware.
- Do not commit or push until the user explicitly requests it.

## File Map

- Modify `device_bridges/windows_pyautogui_bridge.py`: permit `DELETE` in `WindowsPyAutoGUIBridge.proxy_ui_request()` and update its rejection message.
- Modify `app/main.py`: register `DELETE` on the existing bridge-UI proxy route.
- Modify `tests/unit/test_equipment_pyautogui_bridge.py`: prove adapter-level DELETE forwarding, server-side token injection, and unsupported-method rejection.
- Modify `tests/integration/test_live_gui_runtime_layout.py`: prove FastAPI accepts and offloads DELETE with the original path/query/body contract.
- Use `docs/superpowers/specs/2026-08-14-windows-bridge-delete-proxy-design.md` as the behavioral specification; no additional user-facing documentation is required.

---

### Task 1: Bridge Adapter DELETE Forwarding

**Files:**
- Modify: `tests/unit/test_equipment_pyautogui_bridge.py` near `test_bridge_ui_proxy_injects_saved_token_without_accepting_browser_token`
- Modify: `device_bridges/windows_pyautogui_bridge.py` in `WindowsPyAutoGUIBridge.proxy_ui_request`

**Interfaces:**
- Consumes: `WindowsPyAutoGUIBridge.proxy_ui_request(method: str, resource_path: str, query_string: str = "", body: bytes = b"", content_type: str = "") -> dict[str, Any]`
- Produces: the same method signature, accepting `DELETE` while preserving the existing proxy response schema.

- [ ] **Step 1: Add the failing adapter DELETE test**

Add this test after the existing GET proxy test:

```python
def test_bridge_ui_proxy_forwards_delete_with_saved_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(tmp_path, mode="live")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://192.168.50.58:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "server-only-token")

    class _Reply:
        status_code = 200
        headers = {"content-type": "application/json; charset=utf-8"}
        content = b'{"ok":true,"status":"deleted"}'

    class _Client:
        def __init__(self, timeout: float, follow_redirects: bool) -> None:
            assert timeout == bridge.config.request_timeout_sec
            assert follow_redirects is False

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def request(self, method: str, url: str, headers: dict[str, str], content: bytes) -> _Reply:
            assert method == "DELETE"
            assert url == "http://192.168.50.58:8765/programs/custom-probe?source=atr"
            assert headers["X-Bridge-Token"] == "server-only-token"
            assert content == b""
            return _Reply()

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)

    response = bridge.proxy_ui_request(
        method="DELETE",
        resource_path="programs/custom-probe",
        query_string="source=atr",
    )

    assert response["ok"] is True
    assert response["status_code"] == 200
    assert response["content"] == b'{"ok":true,"status":"deleted"}'
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_equipment_pyautogui_bridge.py::test_bridge_ui_proxy_forwards_delete_with_saved_token
```

Expected: FAIL because the response is the local 405 `PYAUTOGUI_UI_METHOD_NOT_ALLOWED` payload and the fake upstream client is never called.

- [ ] **Step 3: Add an unsupported-method regression test**

```python
def test_bridge_ui_proxy_still_rejects_methods_outside_allowlist(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, mode="live")

    response = bridge.proxy_ui_request(method="PATCH", resource_path="programs/custom-probe")
    payload = json.loads(response["content"])

    assert response["status_code"] == 405
    assert payload["failure_code"] == "PYAUTOGUI_UI_METHOD_NOT_ALLOWED"
    assert payload["message"] == "Only GET, POST, and DELETE are supported."
```

- [ ] **Step 4: Implement the minimal adapter change**

Change only the allowlist and message:

```python
if normalized_method not in {"GET", "POST", "DELETE"}:
    return self._proxy_ui_failure(
        405,
        "PYAUTOGUI_UI_METHOD_NOT_ALLOWED",
        "Only GET, POST, and DELETE are supported.",
    )
```

- [ ] **Step 5: Run adapter tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_equipment_pyautogui_bridge.py -k 'bridge_ui_proxy'
```

Expected: all selected proxy tests pass with no failures.

---

### Task 2: FastAPI DELETE Route

**Files:**
- Modify: `tests/integration/test_live_gui_runtime_layout.py` near `test_windows_equipment_bridge_ui_proxy_offloads_bridge_request`
- Modify: `app/main.py` at the `/equipment/windows/bridge-ui/{resource_path:path}` route

**Interfaces:**
- Consumes: `proxy_windows_equipment_bridge_ui(resource_path: str, request: Request) -> Response`
- Produces: the same route handler matched for `DELETE` in addition to `GET` and `POST`.

- [ ] **Step 1: Add the failing FastAPI DELETE test**

```python
def test_windows_equipment_bridge_ui_proxy_forwards_delete(monkeypatch) -> None:
    forwarded: list[dict[str, object]] = []

    class FakeBridge:
        def proxy_ui_request(self, **kwargs):
            forwarded.append(dict(kwargs))
            return {
                "ok": True,
                "status_code": 200,
                "content_type": "application/json; charset=utf-8",
                "content": b'{"ok":true,"status":"deleted"}',
            }

    monkeypatch.setattr("app.main._equipment_bridge", lambda: FakeBridge())
    client = TestClient(app)

    response = client.delete(
        "/equipment/windows/bridge-ui/programs/custom-probe?source=atr",
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "deleted"}
    assert forwarded == [
        {
            "method": "DELETE",
            "resource_path": "programs/custom-probe",
            "query_string": "source=atr",
            "body": b"",
            "content_type": "",
        }
    ]
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/integration/test_live_gui_runtime_layout.py::test_windows_equipment_bridge_ui_proxy_forwards_delete
```

Expected: FAIL with HTTP 405 because FastAPI does not currently match DELETE for this route.

- [ ] **Step 3: Implement the minimal route change**

Change the existing decorator only:

```python
@app.api_route(
    "/equipment/windows/bridge-ui/{resource_path:path}",
    methods=["GET", "POST", "DELETE"],
    response_class=Response,
)
```

- [ ] **Step 4: Run FastAPI proxy tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'windows_equipment_bridge_ui_proxy'
```

Expected: token-safe HTML, offload, and DELETE proxy tests all pass.

---

### Task 3: Focused and Live Nextpc Verification

**Files:**
- Verify: `device_bridges/windows_pyautogui_bridge.py`
- Verify: `app/main.py`
- Verify: `tests/unit/test_equipment_pyautogui_bridge.py`
- Verify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: the modified FastAPI route and `WindowsPyAutoGUIBridge.proxy_ui_request()`.
- Produces: test evidence that a temporary custom program can be registered, listed, deleted, and confirmed absent through the ATR proxy while using the saved Nextpc token.

- [ ] **Step 1: Run the complete focused automated set**

```bash
.venv/bin/pytest -q \
  tests/unit/test_equipment_pyautogui_bridge.py \
  tests/integration/test_live_gui_runtime_layout.py -k 'pyautogui or windows_equipment_bridge_ui_proxy'
```

Expected: zero failures.

- [ ] **Step 2: Run the Windows bridge packaging and helper regression set**

```bash
.venv/bin/pytest -q \
  tests/unit/test_install_packaging.py \
  tests/unit/test_windows_pyautogui_bridge_server_helper.py \
  tests/unit/test_windows_pyautogui_demo_assets.py
```

Expected: zero failures.

- [ ] **Step 3: Run a live Nextpc register/delete regression through FastAPI `TestClient`**

Run this from the repository root. It uses the selected `windows_192.168.50.40_nextpc` connection and its saved server-side token. It creates a log-only program and deletes it in `finally` if an assertion fails.

```bash
.venv/bin/python - <<'PY'
import time
from fastapi.testclient import TestClient

from app.main import _equipment_bridge, app

program_id = f"atr_proxy_delete_probe_{int(time.time())}"
definition = {
    "schema": "atr.pyautogui_program.v1",
    "program_id": program_id,
    "name": "ATR proxy DELETE probe",
    "enabled": True,
    "program_type": "macro",
    "safe_test": True,
    "sequence": [{"action": "log", "message": "proxy delete probe"}],
}
bridge = _equipment_bridge()

try:
    with TestClient(app) as client:
        registered = client.post(
            "/equipment/windows/bridge-ui/programs/register",
            json=definition,
        )
        assert registered.status_code == 200, registered.text
        assert registered.json()["ok"] is True

        deleted = client.delete(
            f"/equipment/windows/bridge-ui/programs/{program_id}",
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["ok"] is True

        programs = client.get("/equipment/windows/bridge-ui/programs")
        assert programs.status_code == 200, programs.text
        ids = {item["program_id"] for item in programs.json()["programs"]}
        assert program_id not in ids
finally:
    bridge.delete_program(
        {
            "program_id": program_id,
            "runtime_mode": "live",
            "force_live_bridge": True,
        }
    )

print("live Nextpc proxy DELETE: PASS")
PY
```

Expected: `live Nextpc proxy DELETE: PASS` and no temporary program in the remote program list.

- [ ] **Step 4: Verify no unrelated edits or leftover test registrations**

```bash
git diff --check -- \
  app/main.py \
  device_bridges/windows_pyautogui_bridge.py \
  tests/unit/test_equipment_pyautogui_bridge.py \
  tests/integration/test_live_gui_runtime_layout.py

git status --short -- \
  app/main.py \
  device_bridges/windows_pyautogui_bridge.py \
  tests/unit/test_equipment_pyautogui_bridge.py \
  tests/integration/test_live_gui_runtime_layout.py \
  docs/superpowers/specs/2026-08-14-windows-bridge-delete-proxy-design.md \
  docs/superpowers/plans/2026-08-14-windows-bridge-delete-proxy.md
```

Expected: no whitespace errors; only the planned files appear in the scoped status. Do not commit or push.
