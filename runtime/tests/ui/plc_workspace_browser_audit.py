#!/usr/bin/env python3
"""Non-actuating browser audit for the PLC device workspace and dashboard card.

The audit hosts static templates with deterministic API responses.  It never
starts the application or contacts a PLC, so lifecycle and virtual-input checks
remain browser-only.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = PROJECT_ROOT / "web" / "static"
TEMPLATE_ROOT = PROJECT_ROOT / "web" / "templates"
AUDIT_CAPTURE = """
<script>
window.__plcAuditErrors = [];
window.addEventListener('error', (event) => window.__plcAuditErrors.push(String(event.message || event.error || 'window error')));
const originalConsoleError = console.error.bind(console);
console.error = (...args) => { window.__plcAuditErrors.push(args.map(String).join(' ')); originalConsoleError(...args); };
</script>
"""


class MockPLCWorkspaceServer(ThreadingHTTPServer):
    """Static server whose PLC responses are safe, complete, and deterministic."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), MockPLCWorkspaceHandler)
        self.status_mode = "online"
        self.virtual_transport = True
        self.snapshot_sequence = 42
        self.snapshot_received_monotonic = 101.25
        self.event_revision = 3
        self.virtual_inputs: list[str] = []
        self.request_counts: dict[str, int] = {}

    def status_payload(self) -> dict[str, object]:
        offline = self.status_mode == "offline"
        stale = self.status_mode == "stale"
        return {
            "plc_layer_active": not offline,
            "connection_state": "offline" if offline else "stale" if stale else "online",
            "monitor_state": "stopped" if offline else "running",
            "transport": "virtual" if self.virtual_transport else "pymcprotocol_type3e",
            "safety_state": "estop_latched" if not offline and not stale else "normal",
            "active_estop_sources": ["plc_pb2"] if not offline and not stale else [],
            "failure_code": "PLC_STATE_STALE" if stale else None,
            "last_error": "PLC sample exceeded stale_after_s" if stale else None,
            "register_snapshot": {
                "d100": 1,
                "d101": 1,
                "d102": 0,
                "sequence": self.snapshot_sequence,
                "received_monotonic": self.snapshot_received_monotonic,
            },
            "last_latency_ms": 18,
            "sample_age_s": 0.032,
            "event_revision": self.event_revision,
            "pending_command": "resume",
            "transaction": {
                "transaction_id": "plc-audit-42",
                "phase": "acknowledged",
                "source": "plc_pb2",
            },
            "reconnect_attempt": 0,
            "poll_worker_starts": 1,
            "legacy_controls_available": False,
        }


class MockPLCWorkspaceHandler(BaseHTTPRequestHandler):
    server: MockPLCWorkspaceServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        self.server.request_counts[path] = self.server.request_counts.get(path, 0) + 1
        if path in {"/", "/plc"}:
            name = "index.html" if path == "/" else "plc.html"
            self._html(TEMPLATE_ROOT / name)
            return
        if path.startswith("/static/"):
            self._static(path.removeprefix("/static/"))
            return
        if path == "/api/plc/status":
            self._json(self.server.status_payload())
            return
        if path == "/api/plc/config":
            self._json(
                {
                    "transport": "pymcprotocol_type3e",
                    "host": "127.0.0.1",
                    "port": 4999,
                    "poll_interval_s": 0.2,
                    "stale_after_s": 1.0,
                    "handshake_timeout_s": 5.0,
                }
            )
            return
        if path == "/api/plc/events":
            self._json(
                {
                    "count": 2,
                    "events": [
                        {"event": "plc.snapshot.received", "at": 1_700_000_000, "details": {"sequence": 42}},
                        {"event": "plc.handshake.asserted", "at": 1_700_000_001, "details": {"command": "resume"}},
                    ],
                }
            )
            return
        if path == "/api/state":
            self._json({"is_running": False, "state": {"stage": "idle", "mode": "test", "loop_count": 0, "agent_status": {}, "device_health": {}}})
            return
        if path == "/api/graphs/atr_closed_loop":
            self._json({"graph": {"nodes": [], "edges": []}})
            return
        if path == "/api/runtime/models":
            self._json({"ok": True, "enabled": False, "models": []})
            return
        if path == "/api/runtime/api-key":
            self._json({"ok": True, "enabled": False, "has_key": False, "source": "none"})
            return
        if path == "/api/printer/status":
            self._json({"ok": True, "health": {"reachable": True, "state": "ready"}, "live_gates": {}, "connection": {}, "selected_printer": {}})
            return
        if path == "/api/equipment/windows/config":
            self._json({"connection": {"candidates": []}})
            return
        if path == "/api/lerobot/config":
            self._json({"ok": True, "profiles": [], "sessions": []})
            return
        if path == "/api/bo/config":
            self._json({"ok": True, "defaults": {}, "recent": {}})
            return
        if path == "/api/cae/config":
            self._json({"ok": True, "health": {}, "recent": {}})
            return
        if path == "/api/knowledge/graph/stats":
            self._json({"ok": True, "graph": {"ok": True, "backend": "mock", "node_count": 0, "edge_count": 0}, "outbox": {"pending": 0}})
            return
        if path == "/api/events/recent":
            self._json({"events": []})
            return
        if path == "/api/events/stream":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(b": audit stream\n\n")
            self.wfile.flush()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        self.server.request_counts[path] = self.server.request_counts.get(path, 0) + 1
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(content_length) or b"{}")
        if path == "/api/plc/virtual/input":
            self.server.virtual_inputs.append(str(payload.get("action")))
            self._json({"ok": True, "message": f"Virtual PLC {payload.get('action')} input applied."})
            return
        if path in {"/api/plc/connect", "/api/plc/disconnect", "/api/plc/preflight", "/api/plc/config"}:
            self._json({"ok": True, "message": "PLC audit operation completed."})
            return
        self._json({"ok": True})

    def _html(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, f"Missing template: {path.name}")
            return
        body = path.read_text(encoding="utf-8").replace("<head>", f"<head>{AUDIT_CAPTURE}", 1)
        self._bytes(body.encode("utf-8"), "text/html; charset=utf-8")

    def _static(self, relative: str) -> None:
        path = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT not in path.parents or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        media_type = "text/javascript; charset=utf-8" if path.suffix == ".js" else "text/css; charset=utf-8"
        self._bytes(path.read_bytes(), media_type)

    def _json(self, payload: dict[str, object]) -> None:
        self._bytes(json.dumps(payload).encode("utf-8"), "application/json")

    def _bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_server() -> tuple[MockPLCWorkspaceServer, threading.Thread, str]:
    server = MockPLCWorkspaceServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def _audit_layout(driver: webdriver.Firefox) -> dict[str, object]:
    return driver.execute_script(
        """
        const rect = (item) => {
          const value = item.getBoundingClientRect();
          return {left: value.left, right: value.right, top: value.top, bottom: value.bottom, width: value.width, height: value.height};
        };
        const visible = (item) => {
          const style = window.getComputedStyle(item);
          const value = item.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && value.width > 0 && value.height > 0;
        };
        const panels = Array.from(document.querySelectorAll('[data-plc-panel]')).filter(visible).map((item) => ({id: item.id, ...rect(item)}));
        const buttons = Array.from(document.querySelectorAll('#plc-workspace button')).filter(visible).map((item) => ({id: item.id, ...rect(item)}));
        return {
          bodyText: document.body.innerText,
          errors: window.__plcAuditErrors || [],
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
          panels,
          buttons,
          inputs: Array.from(document.querySelectorAll('#plc-workspace input')).map((item) => ({id: item.id, disabled: item.disabled})),
          virtualVisible: Array.from(document.querySelectorAll('[data-plc-virtual-control]')).filter(visible).map((item) => item.id),
        };
        """
    )


def run_audit(*, geckodriver: str, width: int = 1920, height: int = 1080) -> dict[str, object]:
    server, _thread, base_url = _start_server()
    options = Options()
    options.add_argument("-headless")
    driver = webdriver.Firefox(service=Service(executable_path=geckodriver), options=options)
    driver.set_window_size(width, height)
    try:
        wait = WebDriverWait(driver, 12)
        dashboard_handle = driver.current_window_handle
        driver.get(base_url)
        wait.until(lambda item: item.find_element(By.ID, "btn-open-plc").is_displayed())
        workspace_link = driver.find_element(By.ID, "btn-open-plc")
        navigation = {
            "link_id": workspace_link.get_attribute("id"),
            "link_text": workspace_link.text,
            "workspace_path": urlparse(workspace_link.get_attribute("href")).path,
        }
        workspace_link.click()
        wait.until(lambda item: len(item.window_handles) == 2)
        workspace_handle = next(
            handle for handle in driver.window_handles if handle != dashboard_handle
        )
        driver.switch_to.window(workspace_handle)
        wait.until(lambda item: urlparse(item.current_url).path == "/plc")
        wait.until(lambda item: item.find_element(By.ID, "plc-workspace"))
        wait.until(lambda item: "D100" in item.find_element(By.ID, "plc-register-state").text)
        wait.until(lambda item: item.find_element(By.ID, "plc-config-host").is_enabled() is False)
        wait.until(lambda item: item.find_element(By.ID, "plc-config-host").get_attribute("value") == "127.0.0.1")
        wait.until(lambda item: len(item.find_elements(By.CSS_SELECTOR, "[data-plc-virtual-control]")) == 3)
        driver.execute_async_script(
            """
            const done = arguments[arguments.length - 1];
            refreshPLCStatus().then(done, done);
            """
        )
        if driver.find_element(By.ID, "plc-config-host").get_attribute("value") != "127.0.0.1":
            raise AssertionError("cached status refresh must not clear offline configuration values")

        required_text = ("Connection", "Register State", "Safety State", "Transport Health", "Event History")
        layout = _audit_layout(driver)
        missing_text = [label for label in required_text if label not in str(layout["bodyText"])]
        if missing_text:
            raise AssertionError(f"PLC workspace missing required sections: {missing_text}")
        if "Source set" not in str(layout["bodyText"]) or "Transaction phase" not in str(layout["bodyText"]):
            raise AssertionError("PLC workspace is missing bounded safety diagnostics")
        if "Latency" not in str(layout["bodyText"]) or "Freshness" not in str(layout["bodyText"]):
            raise AssertionError("PLC workspace is missing transport timing diagnostics")
        if "18 ms" not in str(layout["bodyText"]) or "32 ms" not in str(layout["bodyText"]):
            raise AssertionError("PLC workspace did not render authoritative cached timing")
        if layout["scrollWidth"] > layout["clientWidth"] + 2:
            raise AssertionError(f"PLC workspace horizontally overflows {width}x{height}: {layout}")
        panels = list(layout["panels"])
        for index, first in enumerate(panels):
            for second in panels[index + 1 :]:
                overlap = (
                    first["left"] < second["right"]
                    and first["right"] > second["left"]
                    and first["top"] < second["bottom"]
                    and first["bottom"] > second["top"]
                )
                if overlap:
                    raise AssertionError(f"PLC workspace panels overlap: {first['id']} and {second['id']}")
        if any(item["disabled"] is False for item in layout["inputs"]):
            raise AssertionError(f"PLC config must be disabled while connected: {layout['inputs']}")
        if len(layout["virtualVisible"]) != 3:
            raise AssertionError(f"virtual pushbuttons were not rendered for virtual transport: {layout['virtualVisible']}")
        if layout["errors"]:
            raise AssertionError(f"PLC workspace emitted console errors: {layout['errors']}")

        allowed_inputs = {"plc-config-host", "plc-config-port", "plc-config-poll-interval", "plc-config-stale-after", "plc-config-handshake-timeout"}
        input_ids = {str(item["id"]) for item in layout["inputs"]}
        if input_ids != allowed_inputs:
            raise AssertionError(f"PLC workspace exposes an unbounded write field: {input_ids - allowed_inputs}")
        if driver.find_elements(By.CSS_SELECTOR, "[data-plc-register-write], [data-plc-arbitrary-write]"):
            raise AssertionError("PLC workspace exposes an arbitrary register write control")

        driver.find_element(By.ID, "plc-virtual-estop").click()
        wait.until(lambda _item: server.virtual_inputs == ["estop"])
        event_requests_before = server.request_counts.get("/api/plc/events", 0)
        server.snapshot_sequence += 1
        server.snapshot_received_monotonic += 4.0
        mutation_count = driver.execute_async_script(
            """
            const done = arguments[arguments.length - 1];
            const registerState = document.getElementById('plc-register-state');
            let mutations = 0;
            const observer = new MutationObserver((records) => { mutations += records.length; });
            observer.observe(registerState, {childList: true, characterData: true, subtree: true});
            refreshPLCStatus().then(() => {
              observer.disconnect();
              done(mutations);
            }, done);
            """
        )
        if mutation_count:
            raise AssertionError("unchanged PLC material state was re-rendered")
        if server.request_counts.get("/api/plc/events", 0) != event_requests_before:
            raise AssertionError("new sequence/timestamp reloaded bounded PLC event history")
        server.virtual_transport = False
        driver.execute_async_script(
            """
            const done = arguments[arguments.length - 1];
            refreshPLCStatus().then(done, done);
            """
        )
        if driver.find_element(By.ID, "plc-virtual-controls").is_displayed():
            raise AssertionError("virtual pushbuttons remain visible for a non-virtual transport")

        server.status_mode = "stale"
        driver.execute_async_script(
            """
            const done = arguments[arguments.length - 1];
            refreshPLCStatus().then(done, done);
            """
        )
        wait.until(lambda item: item.find_element(By.ID, "plc-connection-state").text == "STALE")
        if driver.find_element(By.ID, "plc-status-label").text != "STALE":
            raise AssertionError("PLC workspace did not project configured stale state")

        server.status_mode = "online"
        driver.switch_to.window(dashboard_handle)
        wait.until(lambda item: item.find_element(By.ID, "plc-workspace-status").text == "E-STOP")
        server.status_mode = "stale"
        driver.execute_script("return refreshPlcWorkspaceStatus()")
        wait.until(lambda item: item.find_element(By.ID, "plc-workspace-status").text == "STALE")
        server.status_mode = "offline"
        driver.execute_script("return refreshPlcWorkspaceStatus()")
        wait.until(lambda item: item.find_element(By.ID, "plc-workspace-status").text == "OFFLINE")
        dashboard = driver.execute_script(
            """
            return {
              errors: window.__plcAuditErrors || [],
              runLabel: document.getElementById('run-indicator')?.textContent,
              runClass: document.getElementById('run-indicator')?.className,
              plcHref: document.getElementById('btn-open-plc')?.getAttribute('href'),
              detail: document.getElementById('plc-workspace-detail')?.textContent,
            };
            """
        )
        if dashboard["plcHref"] != "/plc" or "manual setup" not in str(dashboard["detail"]).lower():
            raise AssertionError(f"Main GUI PLC card is incomplete: {dashboard}")
        if dashboard["runLabel"] != "IDLE" or "warning" in str(dashboard["runClass"]):
            raise AssertionError(f"optional PLC offline state changed global run state: {dashboard}")
        if dashboard["errors"]:
            raise AssertionError(f"Main GUI emitted console errors: {dashboard['errors']}")

        before = server.request_counts.get("/api/plc/status", 0)
        time.sleep(0.4)
        after = server.request_counts.get("/api/plc/status", 0)
        if after != before:
            raise AssertionError("Main GUI PLC status refresh is unbounded while the dashboard is idle")
        return {
            "ok": True,
            "navigation": navigation,
            "status_requests": after,
            "virtual_inputs": server.virtual_inputs,
            "layout": layout,
        }
    finally:
        driver.quit()
        server.shutdown()
        server.server_close()


def test_plc_workspace_browser_audit() -> None:
    result = run_audit(geckodriver="/snap/bin/geckodriver")
    assert result["ok"] is True
    assert result["navigation"] == {
        "link_id": "btn-open-plc",
        "link_text": "Open PLC Workspace",
        "workspace_path": "/plc",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geckodriver", default="/snap/bin/geckodriver")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()
    result = run_audit(geckodriver=args.geckodriver, width=args.width, height=args.height)
    print("plc_workspace_browser_audit: PASS")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
