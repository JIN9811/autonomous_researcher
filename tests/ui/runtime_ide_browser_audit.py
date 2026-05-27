#!/usr/bin/env python3
"""Browser-level Runtime IDE audit using raw WebDriver HTTP.

This script intentionally avoids Selenium as a dependency. It expects:
- FastAPI server running, default http://127.0.0.1:7861
- geckodriver running, default http://127.0.0.1:4448

It verifies operator-facing behavior that unit tests cannot prove from static files.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


WEBDRIVER_HTTP_TIMEOUT_S = float(os.environ.get("ATR_WEBDRIVER_HTTP_TIMEOUT_S", "90"))


class WebDriverAudit:
    def __init__(self, webdriver_url: str, *, width: int, height: int) -> None:
        self.webdriver_url = webdriver_url.rstrip("/")
        self.width = width
        self.height = height
        self.session_id = ""

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.webdriver_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=WEBDRIVER_HTTP_TIMEOUT_S) as resp:
            data = resp.read().decode("utf-8")
        return json.loads(data)["value"]

    def start(self) -> None:
        value = self.request(
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "browserName": "firefox",
                        "moz:firefoxOptions": {"args": ["-headless"]},
                    }
                }
            },
        )
        self.session_id = value["sessionId"]
        self.request("POST", f"/session/{self.session_id}/window/rect", {"width": self.width, "height": self.height, "x": 0, "y": 0})

    def stop(self) -> None:
        if not self.session_id:
            return
        try:
            self.request("DELETE", f"/session/{self.session_id}")
        except Exception:
            pass
        self.session_id = ""

    def open(self, url: str, *, wait_s: float = 3.5) -> None:
        self.request("POST", f"/session/{self.session_id}/url", {"url": url})
        time.sleep(wait_s)

    def js(self, script: str, args: list[Any] | None = None) -> Any:
        return self.request("POST", f"/session/{self.session_id}/execute/sync", {"script": script, "args": args or []})

    def screenshot(self, path: Path) -> None:
        raw = self.request("GET", f"/session/{self.session_id}/screenshot")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(raw))


def assert_true(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def wait_for_js(driver: WebDriverAudit, script: str, *, args: list[Any] | None = None, timeout_s: float = 8.0, interval_s: float = 0.2) -> Any:
    deadline = time.time() + timeout_s
    last: Any = None
    while time.time() < deadline:
        last = driver.js(script, args=args)
        if last:
            return last
        time.sleep(interval_s)
    return last


def http_json(base_url: str, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout_s: float = 30.0) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code} {method} {path}: {detail}") from exc
    return json.loads(raw) if raw else {}


def wait_until_not_running(base_url: str, *, timeout_s: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    state: dict[str, Any] = {}
    while time.time() < deadline:
        state = http_json(base_url, "/api/state", timeout_s=10.0)
        if not state.get("is_running"):
            return state
        time.sleep(0.35)
    return state


def event_type_name(event: dict[str, Any]) -> str:
    return str(event.get("type") or event.get("event_type") or "")


def wait_for_run_events(base_url: str, run_id: str, required_types: set[str], *, timeout_s: float = 18.0) -> tuple[list[dict[str, Any]], set[str]]:
    deadline = time.time() + timeout_s
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    while time.time() < deadline:
        data = http_json(base_url, f"/api/runs/{run_id}/events", timeout_s=10.0)
        events = [item for item in data.get("events", []) if isinstance(item, dict)]
        seen = {event_type_name(event) for event in events}
        if required_types.issubset(seen):
            return events, seen
        time.sleep(0.35)
    return events, seen


def scenario_layout(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    driver.open(f"{base_url.rstrip('/')}/ide")
    result = driver.js(
        r'''
const ids = ['ide-graph-canvas', 'ide-minimap', 'ide-runtime-readiness'];
const boxes = {};
for (const id of ids) {
  const el = document.getElementById(id);
  const r = el?.getBoundingClientRect();
  boxes[id] = r ? {x:r.x, y:r.y, w:r.width, h:r.height, scrollW:el.scrollWidth, clientW:el.clientWidth} : null;
}
const safety = document.querySelector('.runtime-draft-safety-strip')?.getBoundingClientRect();
const drawers = document.querySelector('.runtime-ide-operator-drawers')?.getBoundingClientRect();
const version = document.getElementById('ide-version-panel')?.getBoundingClientRect();
const compat = document.querySelector('.runtime-ide-compat-module-config');
return {
  title: document.title,
  viewport: {w: window.innerWidth, h: window.innerHeight},
  body: {scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth},
  selected: window.atrRuntimeIdeState?.selectedNodeId || '',
  activeGraph: window.atrRuntimeIdeState?.activeGraphId || '',
  boxes,
  draftSafety: safety ? {y:safety.y, h:safety.height} : null,
  operatorDrawers: drawers ? {y:drawers.y, h:drawers.height} : null,
  versionPanel: version ? {y:version.y, h:version.height} : null,
  compatModuleConfig: compat ? {exists:true, hidden:Boolean(compat.hidden), display:getComputedStyle(compat).display, visibleText:(document.body.innerText || '').includes('Module Config Editor')} : {exists:false},
};
'''
    )
    failures: list[str] = []
    canvas = result["boxes"].get("ide-graph-canvas") or {}
    assert_true(result["title"] == "ATR Runtime IDE", "unexpected page title", failures)
    assert_true(result["activeGraph"] == "atr_closed_loop", "primary graph did not load", failures)
    viewport = result.get("viewport") or {}
    viewport_w = float(viewport.get("w") or 0)
    viewport_h = float(viewport.get("h") or 0)
    assert_true(float(canvas.get("y", 9999)) <= 520.0, f"graph canvas starts too low: y={canvas.get('y')}", failures)
    if viewport_w >= 1900:
        minimap = result["boxes"].get("ide-minimap") or {}
        assert_true(float(canvas.get("y", 9999)) <= 360.0, f"1920px workbench canvas should start near first-screen top: y={canvas.get('y')}", failures)
        assert_true(float(canvas.get("w", 0)) >= 1200.0, f"1920px workbench canvas is too narrow: w={canvas.get('w')}", failures)
        assert_true(float(minimap.get("y", 9999)) < viewport_h, f"minimap should be visible in first 1080px viewport: y={minimap.get('y')} viewport={viewport_h}", failures)
    if viewport_w >= 2400:
        assert_true(float(canvas.get("w", 0)) >= 1650.0, f"large-screen canvas did not expand: w={canvas.get('w')}", failures)
        assert_true(float(canvas.get("h", 0)) >= 720.0, f"large-screen canvas did not grow vertically: h={canvas.get('h')}", failures)
    assert_true(float((result.get("draftSafety") or {}).get("h", 9999)) <= 42.0, "draft safety strip is too tall", failures)
    assert_true(float((result.get("operatorDrawers") or {}).get("h", 9999)) <= 60.0, "closed operator drawers are too tall", failures)
    compat = result.get("compatModuleConfig") or {}
    assert_true(bool(compat.get("exists")), "Runtime IDE compatibility module config host is missing", failures)
    assert_true(bool(compat.get("hidden")) and compat.get("display") == "none", f"Runtime IDE duplicate module config editor is visible: {compat}", failures)
    assert_true(not bool(compat.get("visibleText")), "Runtime IDE still exposes Module Config Editor text in main view", failures)
    assert_true(result["body"]["scrollW"] <= result["body"]["clientW"] + 4, "page has horizontal overflow", failures)
    shot = out_dir / "runtime_ide_browser_audit_layout.png"
    driver.screenshot(shot)
    result["screenshot"] = str(shot)
    result["ok"] = not failures
    result["failures"] = failures
    return result


def scenario_evidence(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    driver.open(f"{base_url.rstrip('/')}/ide")

    def evidence_state() -> dict[str, Any]:
        return driver.js(
            r'''
const evidence = [...document.querySelectorAll('.runtime-readiness-kpi')].find((el) => el.innerText.includes('Evidence'));
return {
  evidence: evidence?.querySelector('strong')?.innerText || '',
  readinessText: document.getElementById('ide-runtime-readiness')?.innerText || '',
  dryRunText: document.getElementById('ide-dry-run-output')?.innerText.slice(0, 1600) || '',
  statusLabel: document.getElementById('ide-status-label')?.innerText || '',
};
'''
        )

    initial = evidence_state()
    driver.js("document.getElementById('ide-validate-btn')?.click(); return true;")
    time.sleep(1.5)
    after_validate = evidence_state()
    driver.js("document.getElementById('ide-dry-run-btn')?.click(); return true;")
    time.sleep(2.0)
    after_dry_run = evidence_state()

    failures: list[str] = []
    assert_true(initial.get("evidence") in {"---", "VCD", "VC-", "V-D"}, f"unexpected initial evidence: {initial.get('evidence')}", failures)
    assert_true(after_validate.get("evidence", "").startswith("VC"), f"validate did not produce compile evidence: {after_validate.get('evidence')}", failures)
    assert_true(after_dry_run.get("evidence") == "VCD", f"dry-run did not produce VCD evidence: {after_dry_run.get('evidence')}", failures)
    assert_true("Draft graph validated" in after_validate.get("dryRunText", "") or "Compiled Graph" in after_validate.get("dryRunText", "") or "compiled" in after_validate.get("dryRunText", "").lower(), "validate output does not show compiled graph evidence", failures)
    assert_true("Runtime Dispatch" in after_dry_run.get("dryRunText", "") or "dispatch" in after_dry_run.get("dryRunText", "").lower(), "dry-run output does not include runtime sequence", failures)
    shot = out_dir / "runtime_ide_browser_audit_evidence_vcd.png"
    driver.screenshot(shot)
    return {
        "ok": not failures,
        "failures": failures,
        "initial": initial,
        "after_validate": after_validate,
        "after_dry_run": after_dry_run,
        "screenshot": str(shot),
    }


def scenario_graph_switch(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    driver.open(f"{base_url.rstrip('/')}/ide")
    graph_ids = ["atr_closed_loop", "printer_pipeline", "lerobot_pick_place", "utm_test_flow"]
    records: list[dict[str, Any]] = []
    failures: list[str] = []

    for graph_id in graph_ids:
        driver.js(
            r'''
const graphId = arguments[0];
window.__atrGraphSwitchAudit = {done:false, error:null, graphId};
const select = document.getElementById('ide-graph-select');
if (select) select.value = graphId;
Promise.resolve(loadGraph(graphId))
  .then(() => { window.__atrGraphSwitchAudit.done = true; })
  .catch((err) => {
    window.__atrGraphSwitchAudit.error = String(err && err.message ? err.message : err);
    window.__atrGraphSwitchAudit.done = true;
  });
return true;
''',
            [graph_id],
        )
        done = wait_for_js(
            driver,
            "return window.__atrGraphSwitchAudit?.done ? window.__atrGraphSwitchAudit : null;",
            timeout_s=10.0,
        )
        assert_true(bool(done), f"{graph_id}: graph load did not finish", failures)
        assert_true(not (done or {}).get("error"), f"{graph_id}: graph load failed: {(done or {}).get('error')}", failures)
        time.sleep(0.4)
        snapshot = driver.js(
            r'''
const graph = JSON.parse(document.getElementById('ide-graph-json')?.value || '{}');
const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
const firstLabel = nodes[0]?.label || nodes[0]?.id || '';
const canvas = document.getElementById('ide-graph-canvas');
const minimap = document.getElementById('ide-minimap');
const canvasText = canvas?.innerText || '';
return {
  requestedGraphId: arguments[0],
  activeGraphId: window.atrRuntimeIdeState?.activeGraphId || '',
  graphJsonId: graph.id || '',
  graphName: graph.name || '',
  graphBadge: document.getElementById('ide-graph-id')?.innerText || '',
  graphSelectValue: document.getElementById('ide-graph-select')?.value || '',
  nodeCount: nodes.length,
  edgeCount: Array.isArray(graph.edges) ? graph.edges.length : 0,
  firstLabel,
  canvasNodes: document.querySelectorAll('#ide-graph-canvas .runtime-ide-node').length,
  minimapNodes: document.querySelectorAll('#ide-minimap .runtime-ide-minimap-node').length,
  canvasHasFirstLabel: firstLabel ? canvasText.includes(firstLabel) : false,
  canvasText: canvasText.slice(0, 1000),
  minimapWorld: Boolean(minimap?.querySelector('.runtime-ide-minimap-world')),
};
''',
            [graph_id],
        )
        records.append(snapshot)
        assert_true(snapshot.get("graphJsonId") == graph_id, f"{graph_id}: graph JSON did not switch", failures)
        assert_true(snapshot.get("activeGraphId") == graph_id, f"{graph_id}: activeGraphId did not switch", failures)
        assert_true(snapshot.get("graphSelectValue") == graph_id, f"{graph_id}: selector value did not switch", failures)
        assert_true(int(snapshot.get("nodeCount") or 0) > 0, f"{graph_id}: graph has no nodes", failures)
        assert_true(snapshot.get("canvasNodes") == snapshot.get("nodeCount"), f"{graph_id}: canvas node count does not match JSON", failures)
        assert_true(snapshot.get("minimapNodes") == snapshot.get("nodeCount"), f"{graph_id}: minimap node count does not match JSON", failures)
        assert_true(bool(snapshot.get("canvasHasFirstLabel")), f"{graph_id}: canvas does not show first graph node label", failures)
        assert_true(bool(snapshot.get("minimapWorld")), f"{graph_id}: minimap world did not render", failures)

    node_counts = {item.get("nodeCount") for item in records}
    assert_true(len(node_counts) >= 3, f"graph switch did not produce distinct templates: {sorted(node_counts)}", failures)
    shot = out_dir / "runtime_ide_browser_audit_graph_switch.png"
    driver.screenshot(shot)
    return {
        "ok": not failures,
        "failures": failures,
        "graphs": records,
        "screenshot": str(shot),
    }


def scenario_canvas_interactions(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    driver.open(f"{base_url.rstrip('/')}/ide")
    result = driver.js(
        r'''
function parseGraph() {
  return JSON.parse(document.getElementById('ide-graph-json')?.value || '{}');
}
function nodeById(id) {
  return document.querySelector(`[data-node-id="${CSS.escape(id)}"]`);
}
function centerOf(el) {
  const rect = el.getBoundingClientRect();
  return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, rect};
}
function dispatchPointer(target, type, x, y) {
  const event = new PointerEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: x,
    clientY: y,
    button: 0,
    buttons: type === 'pointerup' ? 0 : 1,
    pointerId: 1,
    pointerType: 'mouse',
    isPrimary: true,
  });
  target.dispatchEvent(event);
}
function dispatchWindowPointer(type, x, y) {
  dispatchPointer(window, type, x, y);
}
const canvas = document.getElementById('ide-graph-canvas');
const failures = [];
if (!canvas) failures.push('graph canvas missing');
canvas.scrollLeft = 620;
canvas.scrollTop = 0;
if (typeof updateMiniMapViewport === 'function') updateMiniMapViewport();

let graph = parseGraph();
const beforeDesign = graph.nodes.find((node) => node.id === 'design')?.position || {};
let designEl = nodeById('design');
if (!designEl) failures.push('design node missing before drag');
if (designEl) {
  const p = centerOf(designEl);
  dispatchPointer(designEl, 'pointerdown', p.x, p.y);
  dispatchWindowPointer('pointermove', p.x + 41, p.y + 27);
  dispatchWindowPointer('pointerup', p.x + 41, p.y + 27);
}
const afterDragGraph = parseGraph();
const afterDesign = afterDragGraph.nodes.find((node) => node.id === 'design')?.position || {};
const nodeDrag = {
  before: beforeDesign,
  after: afterDesign,
  changed: Number(afterDesign.x) !== Number(beforeDesign.x) || Number(afterDesign.y) !== Number(beforeDesign.y),
  snapped: Number(afterDesign.x) % 16 === 0 && Number(afterDesign.y) % 16 === 0,
  status: document.getElementById('ide-status-message')?.innerText || '',
  activeTabDirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
};

canvas.scrollLeft = 720;
canvas.scrollTop = 0;
if (typeof updateMiniMapViewport === 'function') updateMiniMapViewport();
const sourcePort = document.querySelector('[data-port-node="design"][data-port-side="right"]');
const targetNode = nodeById('vision');
if (!sourcePort) failures.push('design right port missing');
if (!targetNode) failures.push('vision target node missing');
if (sourcePort && targetNode) {
  const s = centerOf(sourcePort);
  const t = centerOf(targetNode);
  dispatchPointer(sourcePort, 'pointerdown', s.x, s.y);
  dispatchWindowPointer('pointermove', t.x, t.y);
  dispatchWindowPointer('pointerup', t.x, t.y);
}
const edgeGraph = parseGraph();
const edgeCandidate = (edgeGraph.edges || []).find((edge) => {
  const metadata = edge.metadata || {};
  const from = metadata.from_stage || edge.source;
  const to = metadata.to_stage || edge.target;
  const condition = metadata.transition_condition || metadata.condition || edge.condition || '';
  return metadata.runtime_edge === 'logical_transition' && from === 'design' && to === 'vision' && condition === 'next_stage:vision';
});
const edgeDrag = {
  defaultTarget: edgeGraph.transitions?.design || '',
  candidateExists: Boolean(edgeCandidate),
  candidateCondition: edgeCandidate?.metadata?.transition_condition || edgeCandidate?.metadata?.condition || edgeCandidate?.condition || '',
  status: document.getElementById('ide-edge-edit-status')?.innerText || '',
  dirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
};

const world = document.querySelector('#ide-minimap .runtime-ide-minimap-world');
const viewport = document.querySelector('#ide-minimap .runtime-ide-minimap-viewport');
const beforeScroll = {left: canvas.scrollLeft, top: canvas.scrollTop};
let viewportBefore = {left: viewport?.style.left || '', top: viewport?.style.top || ''};
if (!world) failures.push('minimap world missing');
if (world) {
  const r = world.getBoundingClientRect();
  const x = r.left + r.width * 0.86;
  const y = r.top + r.height * 0.82;
  dispatchPointer(world, 'pointerdown', x, y);
  dispatchWindowPointer('pointerup', x, y);
}
const viewportAfterEl = document.querySelector('#ide-minimap .runtime-ide-minimap-viewport');
const afterScroll = {left: canvas.scrollLeft, top: canvas.scrollTop};
const minimap = {
  beforeScroll,
  afterScroll,
  changed: beforeScroll.left !== afterScroll.left || beforeScroll.top !== afterScroll.top,
  viewportBefore,
  viewportAfter: {left: viewportAfterEl?.style.left || '', top: viewportAfterEl?.style.top || ''},
};

canvas.scrollLeft = 620;
canvas.scrollTop = 0;
if (typeof updateMiniMapViewport === 'function') updateMiniMapViewport();
designEl = nodeById('design');
if (!designEl) failures.push('design node missing before double-click');
if (designEl) {
  const d = centerOf(designEl);
  designEl.dispatchEvent(new MouseEvent('dblclick', {bubbles: true, cancelable: true, clientX: d.x, clientY: d.y, detail: 2}));
}
return {failures, nodeDrag, edgeDrag, minimap, moduleStart: {dblclickDispatched: Boolean(designEl)}};
'''
    )
    module_state = wait_for_js(
        driver,
        r'''
if (window.atrRuntimeIdeState?.activeGraphTabKind !== 'module' || window.atrRuntimeIdeState?.activeModuleId !== 'design') return null;
const graph = JSON.parse(document.getElementById('ide-graph-json')?.value || '{}');
const tabs = Array.from(document.querySelectorAll('#ide-graph-tabs .runtime-ide-tab')).map((tab) => ({
  text: tab.innerText,
  id: tab.getAttribute('data-graph-tab') || '',
  active: tab.getAttribute('data-tab-active') || '',
  kind: tab.getAttribute('data-tab-kind') || '',
}));
const edgePaths = Array.from(document.querySelectorAll('#ide-graph-canvas .runtime-ide-edge'));
const edgeLabels = Array.from(document.querySelectorAll('#ide-graph-canvas .runtime-ide-edge-label'));
const moduleFlowEdges = Array.from(document.querySelectorAll('#ide-graph-canvas .runtime-ide-edge.edge-module-flow'));
const moduleFlowLabels = Array.from(document.querySelectorAll('#ide-graph-canvas .runtime-ide-edge-label.edge-module-flow'));
const moduleFlowLabelRects = moduleFlowLabels.map((item) => item.querySelector('rect')).filter(Boolean);
const moduleFlowLabelWidths = moduleFlowLabelRects.map((rect) => Number.parseFloat(rect.getAttribute('width') || '0')).filter((width) => width > 0);
const moduleFlowVisibleEdges = moduleFlowEdges.filter((item) => {
  const style = getComputedStyle(item);
  const opacity = Number(style.opacity || '1');
  const strokeWidth = Number.parseFloat(style.strokeWidth || '0');
  const length = typeof item.getTotalLength === 'function' ? item.getTotalLength() : 0;
  return length > 24 && opacity >= 0.9 && strokeWidth >= 3;
});
const moduleFlowModuleMarkerEdges = moduleFlowEdges.filter((item) => String(getComputedStyle(item).markerEnd || item.style.markerEnd || '').includes('ide-arrow-module'));
const moduleNodeById = new Map((Array.isArray(graph.nodes) ? graph.nodes : []).map((node) => [node.id, node]));
const connectedDistances = (Array.isArray(graph.edges) ? graph.edges : []).map((edge) => {
  const source = moduleNodeById.get(edge.source);
  const target = moduleNodeById.get(edge.target);
  if (!source || !target) return 0;
  const sx = Number(source.position?.x || 0) + 92;
  const sy = Number(source.position?.y || 0) + 38;
  const tx = Number(target.position?.x || 0) + 92;
  const ty = Number(target.position?.y || 0) + 38;
  return Math.hypot(tx - sx, ty - sy);
}).filter((distance) => distance > 0);
return {
  activeGraphTabKind: window.atrRuntimeIdeState?.activeGraphTabKind || '',
  activeModuleId: window.atrRuntimeIdeState?.activeModuleId || '',
  activeGraphTabId: window.atrRuntimeIdeState?.activeGraphTabId || '',
  graphBadge: document.getElementById('ide-graph-id')?.innerText || '',
  graphJsonId: graph.id || '',
  graphMetadataKind: graph.metadata?.ide_tab_kind || '',
  graphMetadataModule: graph.metadata?.module_id || '',
  nodeCount: Array.isArray(graph.nodes) ? graph.nodes.length : 0,
  edgeCount: Array.isArray(graph.edges) ? graph.edges.length : 0,
  edgeDomCount: edgePaths.length,
  moduleFlowEdgeCount: moduleFlowEdges.length,
  moduleFlowVisibleEdgeCount: moduleFlowVisibleEdges.length,
  moduleFlowModuleMarkerCount: moduleFlowModuleMarkerEdges.length,
  edgeLabelCount: edgeLabels.length,
  moduleFlowLabelCount: moduleFlowLabels.length,
  moduleFlowLabelMinWidth: moduleFlowLabelWidths.length ? Math.min(...moduleFlowLabelWidths) : 0,
  nonEmptyPathCount: edgePaths.filter((item) => String(item.getAttribute('d') || '').startsWith('M ')).length,
  edgeLabelText: moduleFlowLabels.map((item) => item.textContent || '').join(' | '),
  sampleEdgeStyle: moduleFlowEdges.length ? {
    color: getComputedStyle(moduleFlowEdges[0]).color,
    opacity: getComputedStyle(moduleFlowEdges[0]).opacity,
    strokeWidth: getComputedStyle(moduleFlowEdges[0]).strokeWidth,
    markerEnd: getComputedStyle(moduleFlowEdges[0]).markerEnd || moduleFlowEdges[0].style.markerEnd || '',
  } : {},
  minConnectedCenterDistance: connectedDistances.length ? Math.min(...connectedDistances) : 0,
  tabs,
};
''',
        timeout_s=10.0,
    )
    failures = list(result.get("failures") or [])
    node_drag = result.get("nodeDrag") or {}
    edge_drag = result.get("edgeDrag") or {}
    minimap = result.get("minimap") or {}
    assert_true(bool(node_drag.get("changed")), "node drag did not update graph JSON position", failures)
    assert_true(bool(node_drag.get("snapped")), f"node drag did not snap to 16px grid: {node_drag.get('after')}", failures)
    assert_true(bool(node_drag.get("activeTabDirty")), "node drag did not mark main graph draft dirty", failures)
    assert_true(edge_drag.get("defaultTarget") == "specimen", f"edge drag changed design default unexpectedly: {edge_drag.get('defaultTarget')}", failures)
    assert_true(bool(edge_drag.get("candidateExists")), "edge drag did not add design -> vision candidate", failures)
    assert_true(edge_drag.get("candidateCondition") == "next_stage:vision", f"edge candidate condition mismatch: {edge_drag.get('candidateCondition')}", failures)
    assert_true(bool(edge_drag.get("dirty")), "edge drag did not keep graph draft dirty", failures)
    assert_true(bool(minimap.get("changed")), f"minimap pan did not change canvas scroll: {minimap}", failures)
    assert_true(bool(module_state), "double-click did not open design module tab", failures)
    if module_state:
        assert_true(module_state.get("activeGraphTabKind") == "module", "active tab kind is not module after double-click", failures)
        assert_true(module_state.get("activeModuleId") == "design", "active module id is not design after double-click", failures)
        assert_true(module_state.get("graphMetadataKind") == "module", "module graph metadata kind missing", failures)
        assert_true(module_state.get("graphMetadataModule") == "design", "module graph metadata module mismatch", failures)
        node_count = int(module_state.get("nodeCount") or 0)
        edge_count = int(module_state.get("edgeCount") or 0)
        assert_true(node_count > 0, "opened module graph has no nodes", failures)
        assert_true(edge_count == max(0, node_count - 1), f"module graph edge count mismatch: nodes={node_count}, edges={edge_count}", failures)
        assert_true(int(module_state.get("edgeDomCount") or 0) == edge_count, "module internal graph edge DOM count does not match JSON", failures)
        assert_true(int(module_state.get("moduleFlowEdgeCount") or 0) == edge_count, "module internal graph edges missing module-flow styling", failures)
        assert_true(int(module_state.get("nonEmptyPathCount") or 0) == edge_count, "module internal graph edge paths are empty", failures)
        assert_true(int(module_state.get("moduleFlowLabelCount") or 0) == edge_count, "module internal graph edge labels are not rendered", failures)
        assert_true(int(module_state.get("moduleFlowVisibleEdgeCount") or 0) == edge_count, f"module internal graph edges are not visibly styled: {module_state.get('sampleEdgeStyle')}", failures)
        assert_true(int(module_state.get("moduleFlowModuleMarkerCount") or 0) == edge_count, f"module internal graph arrows are not using the module-flow marker: {module_state.get('sampleEdgeStyle')}", failures)
        assert_true(float(module_state.get("minConnectedCenterDistance") or 0.0) >= 520.0, f"module internal graph node spacing is too tight for edge labels: {module_state.get('minConnectedCenterDistance')}", failures)
        assert_true(float(module_state.get("moduleFlowLabelMinWidth") or 0.0) >= 160.0, f"module internal graph labels are too narrow: {module_state.get('moduleFlowLabelMinWidth')}", failures)
        assert_true(bool(str(module_state.get("edgeLabelText") or "").strip()), "module internal graph edge label text is empty", failures)
        assert_true(any(tab.get("id") == "module:design" for tab in module_state.get("tabs") or []), "module:design tab not rendered", failures)
    shot = out_dir / "runtime_ide_browser_audit_canvas_interactions.png"
    driver.screenshot(shot)
    return {
        "ok": not failures,
        "failures": failures,
        "node_drag": node_drag,
        "edge_drag": edge_drag,
        "minimap": minimap,
        "module_tab": module_state,
        "screenshot": str(shot),
    }



def scenario_workspace_artifacts(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    """Verify direct BO/CAE workspace outputs appear in Runtime IDE artifact lineage."""
    failures: list[str] = []
    bo_response = http_json(
        base_url,
        "/api/bo/run",
        method="POST",
        payload={
            "strategy": "bo",
            "acquisition": "expected_improvement",
            "budget": 3,
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "relative_density": [0.22, 0.34],
                "wall_thickness_mm": [1.2, 1.6],
                "cell_size_mm": [5.0],
            },
        },
        timeout_s=30.0,
    )
    cae_response = http_json(
        base_url,
        "/api/cae/run",
        method="POST",
        payload={
            "mode": "test",
            "specimen_id": "browser-audit-cae",
            "specimen_size_mm": [20, 20, 20],
            "load_max_n": 420,
            "cycles": 9,
            "require_solver": False,
        },
        timeout_s=30.0,
    )
    state = http_json(base_url, "/api/state", timeout_s=10.0)
    run_id = str((state.get("state") or {}).get("run_id") or "")
    artifacts_payload = http_json(base_url, f"/api/runs/{run_id}/artifacts", timeout_s=10.0)
    events_payload = http_json(base_url, f"/api/runs/{run_id}/events", timeout_s=10.0)
    artifacts = [item for item in artifacts_payload.get("artifacts", []) if isinstance(item, dict)]
    artifact_paths = {str(item.get("path") or "") for item in artifacts}
    events = [item for item in events_payload.get("events", []) if isinstance(item, dict)]
    event_artifact_paths = {
        str(((event.get("payload") or {}).get("artifact") or {}).get("path") or "")
        for event in events
        if event_type_name(event) == "artifact.created"
    }
    assert_true(bool(bo_response.get("ok")), f"BO workspace run failed: {bo_response}", failures)
    assert_true(bool(cae_response.get("ok")), f"CAE workspace run failed: {cae_response}", failures)
    assert_true(any(path.startswith("workspace/bo/") and path.endswith("_result.json") for path in artifact_paths), "BO result JSON artifact missing", failures)
    assert_true(any(path.startswith("workspace/bo/") and path.endswith("_bo_progress.svg") for path in artifact_paths), "BO progress SVG artifact missing", failures)
    assert_true(any(path.startswith("workspace/cae/") and path.endswith("_result.json") for path in artifact_paths), "CAE result JSON artifact missing", failures)
    assert_true(any(path.startswith("workspace/cae/") and path.endswith(".contour.svg") for path in artifact_paths), "CAE contour SVG artifact missing", failures)
    assert_true(any(path.startswith("workspace/cae/") and path.endswith(".report.json") for path in artifact_paths), "CAE report JSON artifact missing", failures)
    assert_true(any(path in event_artifact_paths for path in artifact_paths if path.startswith("workspace/bo/") and path.endswith("_bo_progress.svg")), "BO progress artifact.created event missing", failures)
    assert_true(any(path in event_artifact_paths for path in artifact_paths if path.startswith("workspace/cae/") and path.endswith(".contour.svg")), "CAE contour artifact.created event missing", failures)

    driver.open(f"{base_url.rstrip('/')}/ide")
    dom_state = wait_for_js(
        driver,
        r'''
return (async () => {
  if (typeof loadRunContext === 'function') await loadRunContext();
  const lineage = document.getElementById('ide-artifact-lineage');
  const groups = [...document.querySelectorAll('#ide-artifact-lineage .runtime-artifact-group')].map((group) => ({
    title: group.querySelector('.runtime-artifact-group-title strong')?.innerText || '',
    text: group.innerText || '',
  }));
  const items = [...document.querySelectorAll('#ide-artifact-lineage .runtime-artifact-item')].map((item) => item.innerText || '');
  const boItem = [...document.querySelectorAll('#ide-artifact-lineage .runtime-artifact-item')]
    .find((item) => item.innerText.includes('_bo_progress.svg'));
  const boPreviewButton = boItem?.querySelector('[data-artifact-preview-index]');
  if (boPreviewButton) boPreviewButton.click();
  await new Promise((resolve) => setTimeout(resolve, 350));
  const preview = document.getElementById('ide-artifact-preview')?.innerText || '';
  const previewImage = document.querySelector('#ide-artifact-preview .runtime-artifact-preview-image');
  return {
    runId: document.getElementById('ide-run-id')?.innerText || '',
    lineageText: lineage?.innerText || '',
    groups,
    items,
    preview,
    previewImageSrc: previewImage?.getAttribute('src') || '',
    hasBoGroup: groups.some((group) => String(group.title || '').toLowerCase() === 'bo' && group.text.includes('_bo_progress.svg')),
    hasAnalysisGroup: groups.some((group) => String(group.title || '').toLowerCase() === 'analysis' && group.text.includes('.contour.svg')),
    boPreviewOpened: Boolean(previewImage && (previewImage.getAttribute('src') || '').includes('_bo_progress.svg')),
  };
})();
''',
        timeout_s=10.0,
    )
    assert_true(bool(dom_state and dom_state.get("hasBoGroup")), f"Runtime IDE did not group BO workspace artifact under bo: {dom_state}", failures)
    assert_true(bool(dom_state and dom_state.get("hasAnalysisGroup")), f"Runtime IDE did not group CAE workspace artifact under analysis: {dom_state}", failures)
    assert_true(bool(dom_state and dom_state.get("boPreviewOpened")), f"BO SVG preview did not open inline: {dom_state}", failures)
    shot = out_dir / "runtime_ide_browser_audit_workspace_artifacts.png"
    driver.screenshot(shot)
    return {
        "ok": not failures,
        "failures": failures,
        "run_id": run_id,
        "artifact_count": len(artifacts),
        "workspace_artifacts": sorted(path for path in artifact_paths if path.startswith("workspace/")),
        "event_artifact_paths": sorted(path for path in event_artifact_paths if path.startswith("workspace/")),
        "dom_state": dom_state,
        "screenshot": str(shot),
    }

def scenario_saved_test_run(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    """Start a saved active graph test run through the actual Runtime IDE button and clean it up."""
    driver.open(f"{base_url.rstrip('/')}/ide")
    failures: list[str] = []
    pre_state = http_json(base_url, "/api/state", timeout_s=10.0)
    if pre_state.get("is_running"):
        return {
            "ok": False,
            "failures": ["pre-existing active run is present; saved-test-run audit will not stop user work"],
            "pre_state": {
                "run_id": (pre_state.get("state") or {}).get("run_id", ""),
                "stage": (pre_state.get("state") or {}).get("stage", ""),
                "is_running": pre_state.get("is_running"),
            },
        }
    before_run_id = str((pre_state.get("state") or {}).get("run_id") or "")
    created_run_id = ""
    cleanup_result: dict[str, Any] = {}
    result_payload: dict[str, Any] = {}
    try:
        ready = wait_for_js(
            driver,
            r'''
const button = document.getElementById('ide-run-test-btn');
const graphId = window.atrRuntimeIdeState?.activeGraphId || '';
return button && graphId === 'atr_closed_loop' && !button.disabled ? {ok:true, graphId, title: button.title || ''} : null;
''',
            timeout_s=10.0,
        )
        assert_true(bool(ready and ready.get("ok")), f"Run Saved Test button is not ready: {ready}", failures)
        clicked = driver.js(
            r'''
const mode = document.getElementById('ide-run-mode');
if (mode) { mode.value = 'test'; mode.dispatchEvent(new Event('change', {bubbles:true})); }
const backend = document.getElementById('ide-run-backend');
if (backend) backend.value = '';
const goal = document.getElementById('ide-run-goal');
if (goal) goal.value = 'browser audit saved test run';
const button = document.getElementById('ide-run-test-btn');
const disabled = Boolean(button?.disabled);
if (button && !disabled) button.click();
return {clicked: Boolean(button && !disabled), disabled, title: button?.title || '', output: document.getElementById('ide-run-launch-output')?.innerText || ''};
'''
        )
        assert_true(bool(clicked.get("clicked")), f"Run Saved Test click was blocked: {clicked}", failures)
        run_state: dict[str, Any] = {}
        deadline = time.time() + 12.0
        while time.time() < deadline:
            state = http_json(base_url, "/api/state", timeout_s=10.0)
            run_id = str((state.get("state") or {}).get("run_id") or "")
            if run_id and run_id != before_run_id:
                created_run_id = run_id
                run_state = state
                break
            time.sleep(0.25)
        assert_true(bool(created_run_id), "Run Saved Test did not create a new run id", failures)
        events: list[dict[str, Any]] = []
        seen: set[str] = set()
        if created_run_id:
            events, seen = wait_for_run_events(base_url, created_run_id, {"run.created", "graph.compiled", "run.started", "node.started"}, timeout_s=18.0)
            assert_true("run.created" in seen, f"saved test run missing run.created event: {sorted(seen)}", failures)
            assert_true("graph.compiled" in seen, f"saved test run missing graph.compiled event: {sorted(seen)}", failures)
            assert_true("run.started" in seen, f"saved test run missing run.started event: {sorted(seen)}", failures)
            assert_true("node.started" in seen, f"saved test run missing node.started event: {sorted(seen)}", failures)
        dom_state = wait_for_js(
            driver,
            r'''
return (async () => {
  if (typeof loadRunContext === 'function') await loadRunContext();
  const timelineText = document.getElementById('ide-run-timeline')?.innerText || '';
  const runIdText = document.getElementById('ide-run-id')?.innerText || '';
  const statusText = document.getElementById('ide-run-status')?.innerText || '';
  const activeNodes = document.querySelectorAll('#ide-graph-canvas .runtime-ide-node.active').length;
  const visitedNodes = document.querySelectorAll('#ide-graph-canvas .runtime-ide-node.visited').length;
  return {
    ok: timelineText.includes('run.created') && timelineText.includes('run.started') && timelineText.includes('node.started'),
    timelineText,
    runIdText,
    statusText,
    activeNodes,
    visitedNodes,
    runLaunchText: document.getElementById('ide-run-launch-output')?.innerText || '',
  };
})();
''',
            timeout_s=8.0,
        )
        assert_true(bool(dom_state and dom_state.get("ok")), f"timeline did not render saved test run events: {dom_state}", failures)
        if dom_state:
            assert_true(created_run_id in str(dom_state.get("runIdText") or ""), f"run header did not show created run id: {dom_state.get('runIdText')}", failures)
            assert_true(int(dom_state.get("activeNodes") or 0) + int(dom_state.get("visitedNodes") or 0) >= 1, "canvas did not mark any runtime node active/visited", failures)
        shot = out_dir / "runtime_ide_browser_audit_saved_test_run.png"
        driver.screenshot(shot)
        result_payload = {
            "ok": not failures,
            "failures": failures,
            "before_run_id": before_run_id,
            "run_id": created_run_id,
            "event_types": sorted(seen),
            "event_count": len(events),
            "run_state": {
                "is_running": run_state.get("is_running"),
                "stage": (run_state.get("state") or {}).get("stage", ""),
                "loop_count": (run_state.get("state") or {}).get("loop_count", 0),
            },
            "dom_state": dom_state,
            "screenshot": str(shot),
        }
        return result_payload
    finally:
        if created_run_id:
            try:
                cleanup_result = http_json(base_url, f"/api/runs/{created_run_id}/stop", method="POST", timeout_s=15.0)
            except Exception as exc:
                cleanup_result = {"ok": False, "error": str(exc)}
            if result_payload:
                result_payload["cleanup_result"] = cleanup_result

def scenario_save_version_lifecycle(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    # Exercise the operator path: draft edit -> validate/dry-run -> save version -> run saved graph.
    failures: list[str] = []
    pre_state = http_json(base_url, "/api/state", timeout_s=10.0)
    if pre_state.get("is_running"):
        return {
            "ok": False,
            "failures": ["pre-existing active run is present; save-version-lifecycle audit will not stop user work"],
            "pre_state": {
                "run_id": (pre_state.get("state") or {}).get("run_id", ""),
                "stage": (pre_state.get("state") or {}).get("stage", ""),
                "is_running": pre_state.get("is_running"),
            },
        }

    graph_id = "atr_closed_loop"
    original_result = http_json(base_url, f"/api/graphs/{graph_id}", timeout_s=10.0)
    original_graph = original_result.get("graph") or {}
    if not original_graph:
        return {"ok": False, "failures": [f"failed to load original graph: {original_result}"]}
    before_versions = http_json(base_url, f"/api/graphs/{graph_id}/versions", timeout_s=10.0).get("versions", [])
    marker = f"save-version-lifecycle-{int(time.time() * 1000)}"
    created_run_id = ""
    restore_result: dict[str, Any] = {}
    stop_result: dict[str, Any] = {}
    saved_active = False
    result_payload: dict[str, Any] = {}

    try:
        driver.open(f"{base_url.rstrip('/')}/ide")
        ready = wait_for_js(
            driver,
            r'''
const testBtn = document.getElementById('ide-run-test-btn');
return window.atrRuntimeIdeState?.activeGraphId === 'atr_closed_loop' && testBtn ? {
  graphId: window.atrRuntimeIdeState?.activeGraphId || '',
  dirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
  testDisabled: Boolean(testBtn.disabled),
  title: testBtn.title || '',
} : null;
''',
            timeout_s=10.0,
        )
        assert_true(bool(ready and ready.get("graphId") == graph_id), f"primary graph not ready for save lifecycle: {ready}", failures)
        assert_true(not bool(ready and ready.get("dirty")), f"fresh graph tab is dirty before save lifecycle: {ready}", failures)

        injected = driver.js(
            r'''
const marker = arguments[0];
const ta = document.getElementById('ide-graph-json');
const graph = JSON.parse(ta.value || '{}');
if (!graph || graph.id !== 'atr_closed_loop') return {ok:false, graphId:graph?.id || ''};
graph.metadata = graph.metadata || {};
graph.metadata.browser_audit_save_marker = marker;
ta.value = JSON.stringify(graph, null, 2);
ta.dispatchEvent(new Event('change', {bubbles:true}));
return {ok:true, marker};
''',
            args=[marker],
        )
        assert_true(bool(injected.get("ok")), f"failed to inject save marker: {injected}", failures)

        driver.js("document.getElementById('ide-validate-btn')?.click(); return true;")
        time.sleep(1.2)
        driver.js("document.getElementById('ide-dry-run-btn')?.click(); return true;")
        checked = wait_for_js(
            driver,
            r'''
const readiness = document.getElementById('ide-runtime-readiness')?.innerText || '';
const output = document.getElementById('ide-dry-run-output')?.innerText || '';
return (readiness.includes('VCD') || output.toLowerCase().includes('dry-run')) ? {readiness, output: output.slice(0, 1200)} : null;
''',
            timeout_s=8.0,
        )
        assert_true(bool(checked), f"validate/dry-run evidence did not appear before save: {checked}", failures)

        save_click = driver.js(
            r'''
const button = document.getElementById('ide-save-btn');
if (button) button.click();
return {clicked:Boolean(button), text:button?.innerText || ''};
'''
        )
        assert_true(bool(save_click.get("clicked")), f"Save Version button click failed: {save_click}", failures)
        saved_dom = wait_for_js(
            driver,
            r'''
const testBtn = document.getElementById('ide-run-test-btn');
const summary = document.getElementById('ide-run-target-summary')?.innerText || '';
const preflight = document.getElementById('ide-live-preflight')?.innerText || '';
const checklist = document.getElementById('ide-activation-checklist')?.innerText || '';
const status = document.getElementById('ide-status-label')?.innerText || '';
const dirty = Boolean(window.atrRuntimeIdeState?.activeTabDirty);
const saved = checklist.toLowerCase().includes('saved version') && !dirty && testBtn && !testBtn.disabled;
return saved ? {
  dirty,
  testDisabled: Boolean(testBtn.disabled),
  testTitle: testBtn.title || '',
  summary,
  preflight,
  checklist,
  status,
} : null;
''',
            timeout_s=12.0,
        )
        assert_true(bool(saved_dom), f"save did not clear dirty state and re-enable saved test run: {saved_dom}", failures)

        active_after_save = http_json(base_url, f"/api/graphs/{graph_id}", timeout_s=10.0).get("graph") or {}
        saved_active = (active_after_save.get("metadata") or {}).get("browser_audit_save_marker") == marker
        assert_true(saved_active, f"active graph does not contain saved marker after Save Version: {(active_after_save.get('metadata') or {})}", failures)
        after_versions = http_json(base_url, f"/api/graphs/{graph_id}/versions", timeout_s=10.0).get("versions", [])
        assert_true(len(after_versions) >= len(before_versions) + 1, f"graph version count did not increase: before={len(before_versions)} after={len(after_versions)}", failures)

        clicked = driver.js(
            r'''
const goal = document.getElementById('ide-run-goal');
if (goal) goal.value = 'browser audit saved version lifecycle run';
const button = document.getElementById('ide-run-test-btn');
const disabled = Boolean(button?.disabled);
if (button && !disabled) button.click();
return {clicked: Boolean(button && !disabled), disabled, title: button?.title || '', output: document.getElementById('ide-run-launch-output')?.innerText || ''};
'''
        )
        assert_true(bool(clicked.get("clicked")), f"saved graph Run Saved Test click failed after save: {clicked}", failures)
        before_run_id = str((pre_state.get("state") or {}).get("run_id") or "")
        run_state: dict[str, Any] = {}
        deadline = time.time() + 12.0
        while time.time() < deadline:
            state = http_json(base_url, "/api/state", timeout_s=10.0)
            run_id = str((state.get("state") or {}).get("run_id") or "")
            if run_id and run_id != before_run_id:
                created_run_id = run_id
                run_state = state
                break
            time.sleep(0.25)
        assert_true(bool(created_run_id), "saved graph run did not create a new run id after Save Version", failures)
        events: list[dict[str, Any]] = []
        seen: set[str] = set()
        if created_run_id:
            events, seen = wait_for_run_events(base_url, created_run_id, {"run.created", "graph.compiled", "run.started", "node.started"}, timeout_s=18.0)
            assert_true("run.created" in seen, f"save lifecycle run missing run.created event: {sorted(seen)}", failures)
            assert_true("graph.compiled" in seen, f"save lifecycle run missing graph.compiled event: {sorted(seen)}", failures)
            assert_true("run.started" in seen, f"save lifecycle run missing run.started event: {sorted(seen)}", failures)
            assert_true("node.started" in seen, f"save lifecycle run missing node.started event: {sorted(seen)}", failures)

        shot = out_dir / "runtime_ide_browser_audit_save_version_lifecycle.png"
        driver.screenshot(shot)
        saved_dom_trimmed = dict(saved_dom or {})
        for key in ("summary", "preflight", "checklist"):
            if key in saved_dom_trimmed:
                saved_dom_trimmed[key] = str(saved_dom_trimmed.get(key) or "")[:1600]
        result_payload = {
            "ok": not failures,
            "failures": failures,
            "marker": marker,
            "injected": injected,
            "checked": {**(checked or {}), "readiness": str((checked or {}).get("readiness") or "")[:1600], "output": str((checked or {}).get("output") or "")[:1200]},
            "saved_dom": saved_dom_trimmed,
            "version_count_before": len(before_versions),
            "version_count_after": len(after_versions),
            "run_id": created_run_id,
            "event_types": sorted(seen),
            "event_count": len(events),
            "run_state": {
                "is_running": run_state.get("is_running"),
                "stage": (run_state.get("state") or {}).get("stage", ""),
                "loop_count": (run_state.get("state") or {}).get("loop_count", 0),
            },
            "screenshot": str(shot),
        }
        return result_payload
    finally:
        if created_run_id:
            try:
                stop_result = http_json(base_url, f"/api/runs/{created_run_id}/stop", method="POST", timeout_s=15.0)
            except Exception as exc:
                stop_result = {"ok": False, "error": str(exc)}
            wait_until_not_running(base_url, timeout_s=20.0)
        if saved_active or created_run_id:
            try:
                restore_result = http_json(
                    base_url,
                    f"/api/graphs/{graph_id}",
                    method="PUT",
                    payload={"graph": original_graph, "reason": "browser_audit_restore_original", "author": "runtime_ide_audit", "activate": True},
                    timeout_s=20.0,
                )
            except Exception as exc:
                restore_result = {"ok": False, "error": str(exc)}
        if result_payload:
            result_payload["stop_result"] = stop_result
            result_payload["restore_result"] = {
                "ok": restore_result.get("ok"),
                "graph_id": restore_result.get("graph_id"),
                "version_id": (restore_result.get("version") or {}).get("version_id"),
                "reason": (restore_result.get("version") or {}).get("reason"),
                "error": restore_result.get("error"),
            }
            if created_run_id and stop_result.get("ok") is False:
                result_payload.setdefault("failures", []).append(f"failed to stop lifecycle run: {stop_result}")
                result_payload["ok"] = False
            if (saved_active or created_run_id) and restore_result.get("ok") is False:
                result_payload.setdefault("failures", []).append(f"failed to restore active graph: {restore_result}")
                result_payload["ok"] = False

def scenario_discard_draft(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    # Verify explicit Discard Draft restores both main graph and module tab drafts.
    failures: list[str] = []
    driver.open(f"{base_url.rstrip('/')}/ide")
    main_ready = wait_for_js(
        driver,
        r'''
const testBtn = document.getElementById('ide-run-test-btn');
return window.atrRuntimeIdeState?.activeGraphId === 'atr_closed_loop' && testBtn ? {
  dirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
  testDisabled: Boolean(testBtn.disabled),
  graphId: window.atrRuntimeIdeState?.activeGraphId || '',
} : null;
''',
        timeout_s=10.0,
    )
    assert_true(bool(main_ready and main_ready.get("graphId") == "atr_closed_loop"), f"main graph not ready for discard audit: {main_ready}", failures)
    assert_true(not bool(main_ready and main_ready.get("dirty")), f"main graph starts dirty before discard audit: {main_ready}", failures)

    main_marker = f"discard-main-{int(time.time() * 1000)}"
    main_dirty = driver.js(
        r'''
const marker = arguments[0];
const ta = document.getElementById('ide-graph-json');
const graph = JSON.parse(ta.value || '{}');
graph.metadata = graph.metadata || {};
graph.metadata.browser_audit_discard_marker = marker;
ta.value = JSON.stringify(graph, null, 2);
ta.dispatchEvent(new Event('change', {bubbles:true}));
const discardBtn = document.querySelector('[data-draft-safety-action="discard-draft"]');
const testBtn = document.getElementById('ide-run-test-btn');
return {
  marker,
  dirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
  discardVisible: Boolean(discardBtn),
  discardText: discardBtn?.innerText || '',
  testDisabled: Boolean(testBtn?.disabled),
  safetyText: document.getElementById('ide-draft-safety-strip')?.innerText || '',
  graphHasMarker: JSON.parse(ta.value || '{}').metadata?.browser_audit_discard_marker === marker,
};
''',
        args=[main_marker],
    )
    assert_true(bool(main_dirty.get("dirty")), f"main graph marker edit did not mark draft dirty: {main_dirty}", failures)
    assert_true(bool(main_dirty.get("discardVisible")), f"Discard Draft action not visible for main graph: {main_dirty}", failures)
    assert_true(bool(main_dirty.get("testDisabled")), f"Run Saved Test not disabled before main discard: {main_dirty}", failures)
    assert_true(bool(main_dirty.get("graphHasMarker")), f"main graph editor marker was not inserted: {main_dirty}", failures)

    main_after = wait_for_js(
        driver,
        r'''
const button = document.querySelector('[data-draft-safety-action="discard-draft"]');
if (!button) return null;
button.click();
return new Promise((resolve) => setTimeout(() => {
  const graph = JSON.parse(document.getElementById('ide-graph-json')?.value || '{}');
  const testBtn = document.getElementById('ide-run-test-btn');
  resolve({
    dirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
    markerPresent: Boolean(graph.metadata?.browser_audit_discard_marker),
    testDisabled: Boolean(testBtn?.disabled),
    status: document.getElementById('ide-status-label')?.innerText || '',
    safetyText: document.getElementById('ide-draft-safety-strip')?.innerText || '',
  });
}, 650));
''',
        timeout_s=6.0,
    )
    assert_true(bool(main_after), f"main discard did not return state: {main_after}", failures)
    assert_true(not bool(main_after and main_after.get("dirty")), f"main discard left active tab dirty: {main_after}", failures)
    assert_true(not bool(main_after and main_after.get("markerPresent")), f"main discard left marker in graph JSON: {main_after}", failures)
    assert_true(not bool(main_after and main_after.get("testDisabled")), f"main discard did not re-enable saved test run: {main_after}", failures)
    active_graph = http_json(base_url, "/api/graphs/atr_closed_loop", timeout_s=10.0).get("graph") or {}
    assert_true("browser_audit_discard_marker" not in ((active_graph.get("metadata") or {})), "main discard leaked marker into active graph API", failures)

    module_open = wait_for_js(
        driver,
        r'''
return (async () => {
  if (typeof openModuleGraphTab === 'function') await openModuleGraphTab('design');
  await new Promise((resolve) => setTimeout(resolve, 350));
  const graph = JSON.parse(document.getElementById('ide-graph-json')?.value || '{}');
  return window.atrRuntimeIdeState?.activeGraphTabKind === 'module' && window.atrRuntimeIdeState?.activeModuleId === 'design' ? {
    kind: window.atrRuntimeIdeState?.activeGraphTabKind || '',
    moduleId: window.atrRuntimeIdeState?.activeModuleId || '',
    graphId: graph.id || '',
    nodeCount: Array.isArray(graph.nodes) ? graph.nodes.length : 0,
  } : null;
})();
''',
        timeout_s=10.0,
    )
    assert_true(bool(module_open and module_open.get("kind") == "module" and module_open.get("moduleId") == "design"), f"design module tab did not open: {module_open}", failures)

    module_dirty = driver.js(
        r'''
const ta = document.getElementById('ide-graph-json');
const graph = JSON.parse(ta.value || '{}');
const node = (graph.nodes || []).find((item) => item.metadata?.module_step_phase && item.metadata?.module_step_index !== undefined) || (graph.nodes || [])[0];
if (!node) return {ok:false, reason:'module node missing'};
const before = {x:Number(node.position?.x || 0), y:Number(node.position?.y || 0)};
const phase = node.metadata?.module_step_phase || '';
const index = Number(node.metadata?.module_step_index);
const beforePayload = JSON.parse(document.getElementById('ide-module-json')?.value || '{}');
const beforeModule = beforePayload.module || beforePayload || {};
const beforeStep = Array.isArray(beforeModule[phase]) ? beforeModule[phase][index] : null;
const beforeStepPos = beforeStep?.metadata?.position || {};
const beforeStepPosition = {x:Number(beforeStepPos.x || 0), y:Number(beforeStepPos.y || 0)};
node.position = {x: before.x + 64, y: before.y + 16};
ta.value = JSON.stringify(graph, null, 2);
ta.dispatchEvent(new Event('change', {bubbles:true}));
const payload = JSON.parse(document.getElementById('ide-module-json')?.value || '{}');
const module = payload.module || payload || {};
const step = Array.isArray(module[phase]) ? module[phase][index] : null;
const stepPos = step?.metadata?.position || {};
const discardBtn = document.querySelector('[data-draft-safety-action="discard-draft"]');
return {
  ok:true,
  nodeId: node.id,
  phase,
  index,
  before,
  beforeStepPosition,
  after: node.position,
  dirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
  discardVisible: Boolean(discardBtn),
  discardText: discardBtn?.innerText || '',
  moduleStepPosition: {x:Number(stepPos.x || 0), y:Number(stepPos.y || 0)},
  safetyText: document.getElementById('ide-draft-safety-strip')?.innerText || '',
};
'''
    )
    assert_true(bool(module_dirty.get("ok")), f"failed to edit module draft position: {module_dirty}", failures)
    assert_true(bool(module_dirty.get("dirty")), f"module position edit did not mark draft dirty: {module_dirty}", failures)
    assert_true(bool(module_dirty.get("discardVisible")), f"Discard Draft action not visible for module tab: {module_dirty}", failures)
    assert_true(module_dirty.get("moduleStepPosition") == module_dirty.get("after"), f"module JSON did not receive graph position edit: {module_dirty}", failures)

    module_after = wait_for_js(
        driver,
        r'''
const before = arguments[0];
const beforeStepPosition = arguments[1];
const nodeId = arguments[2];
const phase = arguments[3];
const index = Number(arguments[4]);
const button = document.querySelector('[data-draft-safety-action="discard-draft"]');
if (!button) return null;
button.click();
return new Promise((resolve) => setTimeout(() => {
  const graph = JSON.parse(document.getElementById('ide-graph-json')?.value || '{}');
  const node = (graph.nodes || []).find((item) => item.id === nodeId) || {};
  const payload = JSON.parse(document.getElementById('ide-module-json')?.value || '{}');
  const module = payload.module || payload || {};
  const step = Array.isArray(module[phase]) ? module[phase][index] : null;
  const stepPos = step?.metadata?.position || {};
  const nodePos = {x:Number(node.position?.x || 0), y:Number(node.position?.y || 0)};
  resolve({
    kind: window.atrRuntimeIdeState?.activeGraphTabKind || '',
    moduleId: window.atrRuntimeIdeState?.activeModuleId || '',
    dirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
    nodePosition: nodePos,
    moduleStepPosition: {x:Number(stepPos.x || 0), y:Number(stepPos.y || 0)},
    restoredNode: nodePos.x === Number(before.x) && nodePos.y === Number(before.y),
    restoredStep: Number(stepPos.x || 0) === Number(beforeStepPosition.x || 0) && Number(stepPos.y || 0) === Number(beforeStepPosition.y || 0),
    status: document.getElementById('ide-status-label')?.innerText || '',
    safetyText: document.getElementById('ide-draft-safety-strip')?.innerText || '',
  });
}, 650));
''',
        args=[module_dirty.get("before") or {}, module_dirty.get("beforeStepPosition") or {}, module_dirty.get("nodeId") or "", module_dirty.get("phase") or "", module_dirty.get("index") or 0],
        timeout_s=6.0,
    )
    assert_true(bool(module_after), f"module discard did not return state: {module_after}", failures)
    assert_true(module_after.get("kind") == "module" and module_after.get("moduleId") == "design", f"module discard changed active tab unexpectedly: {module_after}", failures)
    assert_true(not bool(module_after.get("dirty")), f"module discard left active tab dirty: {module_after}", failures)
    assert_true(bool(module_after.get("restoredNode")), f"module discard did not restore graph node position: before={module_dirty.get('before')} after={module_after}", failures)
    assert_true(bool(module_after.get("restoredStep")), f"module discard did not restore module JSON step position: beforeStep={module_dirty.get('beforeStepPosition')} after={module_after}", failures)

    shot = out_dir / "runtime_ide_browser_audit_discard_draft.png"
    driver.screenshot(shot)
    return {
        "ok": not failures,
        "failures": failures,
        "main_dirty": main_dirty,
        "main_after": main_after,
        "module_open": module_open,
        "module_dirty": module_dirty,
        "module_after": module_after,
        "screenshot": str(shot),
    }


def scenario_run_preflight(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    # Verify unsaved editor drafts cannot be launched or recorded as a live gate.
    driver.open(f"{base_url.rstrip('/')}/ide")
    failures: list[str] = []
    initial = wait_for_js(
        driver,
        r'''
const testBtn = document.getElementById('ide-run-test-btn');
const liveBtn = document.getElementById('ide-run-live-btn');
const gateBtn = document.getElementById('ide-record-live-gate-btn');
return window.atrRuntimeIdeState?.activeGraphId === 'atr_closed_loop' && testBtn && liveBtn && gateBtn ? {
  graphId: window.atrRuntimeIdeState?.activeGraphId || '',
  dirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
  testDisabled: Boolean(testBtn.disabled),
  liveDisabled: Boolean(liveBtn.disabled),
  gateDisabled: Boolean(gateBtn.disabled),
  testTitle: testBtn.title || '',
  liveTitle: liveBtn.title || '',
  gateTitle: gateBtn.title || '',
  summaryText: document.getElementById('ide-run-target-summary')?.innerText || '',
  preflightText: document.getElementById('ide-live-preflight')?.innerText || '',
} : null;
''',
        timeout_s=10.0,
    )
    assert_true(bool(initial and initial.get("graphId") == "atr_closed_loop"), f"primary graph did not load for preflight audit: {initial}", failures)
    assert_true(not bool(initial and initial.get("dirty")), f"fresh Runtime IDE tab is already dirty: {initial}", failures)
    assert_true(not bool(initial and initial.get("testDisabled")), f"clean saved graph test run button is unexpectedly disabled: {initial}", failures)

    injected = driver.js(
        r'''
const ta = document.getElementById('ide-graph-json');
const graph = JSON.parse(ta.value || '{}');
if (!graph || graph.id !== 'atr_closed_loop') return {ok:false, reason:'primary graph editor not loaded', graphId:graph?.id || ''};
graph.metadata = graph.metadata || {};
graph.metadata.browser_audit_unsaved_marker = `run-preflight-${Date.now()}`;
ta.value = JSON.stringify(graph, null, 2);
ta.dispatchEvent(new Event('change', {bubbles:true}));
return {ok:true, marker: graph.metadata.browser_audit_unsaved_marker};
'''
    )
    time.sleep(0.8)
    dirty_state = driver.js(
        r'''
const testBtn = document.getElementById('ide-run-test-btn');
const liveBtn = document.getElementById('ide-run-live-btn');
const gateBtn = document.getElementById('ide-record-live-gate-btn');
return {
  activeTabDirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
  tabStates: window.atrRuntimeIdeState?.tabs || [],
  testDisabled: Boolean(testBtn?.disabled),
  liveDisabled: Boolean(liveBtn?.disabled),
  gateDisabled: Boolean(gateBtn?.disabled),
  testTitle: testBtn?.title || '',
  liveTitle: liveBtn?.title || '',
  gateTitle: gateBtn?.title || '',
  summaryText: document.getElementById('ide-run-target-summary')?.innerText || '',
  preflightText: document.getElementById('ide-live-preflight')?.innerText || '',
  safetyText: document.getElementById('ide-draft-safety-strip')?.innerText || '',
  readinessText: document.getElementById('ide-runtime-readiness')?.innerText || '',
};
'''
    )
    assert_true(bool(injected.get("ok")), f"failed to inject unsaved graph marker: {injected}", failures)
    assert_true(bool(dirty_state.get("activeTabDirty")), f"textarea change did not mark active graph tab dirty: {dirty_state}", failures)
    assert_true(bool(dirty_state.get("testDisabled")), f"Run Saved Test remains enabled for unsaved draft: {dirty_state}", failures)
    assert_true(bool(dirty_state.get("liveDisabled")), f"Run Saved Live remains enabled for unsaved draft: {dirty_state}", failures)
    assert_true(bool(dirty_state.get("gateDisabled")), f"Record Active Dry-run Gate remains enabled for unsaved draft: {dirty_state}", failures)
    blocked_text = " ".join([dirty_state.get("summaryText", ""), dirty_state.get("preflightText", ""), dirty_state.get("testTitle", ""), dirty_state.get("gateTitle", ""), dirty_state.get("safetyText", "")]).lower()
    assert_true("unsaved" in blocked_text or "draft" in blocked_text, f"preflight does not explain unsaved draft block: {dirty_state}", failures)
    assert_true("save version" in blocked_text or "save or discard" in blocked_text, f"preflight does not show required save/discard action: {dirty_state}", failures)

    driver.js("document.getElementById('ide-validate-btn')?.click(); return true;")
    time.sleep(1.4)
    driver.js("document.getElementById('ide-dry-run-btn')?.click(); return true;")
    time.sleep(1.8)
    after_checks = driver.js(
        r'''
const testBtn = document.getElementById('ide-run-test-btn');
const liveBtn = document.getElementById('ide-run-live-btn');
const gateBtn = document.getElementById('ide-record-live-gate-btn');
const readiness = document.getElementById('ide-runtime-readiness')?.innerText || '';
return {
  activeTabDirty: Boolean(window.atrRuntimeIdeState?.activeTabDirty),
  testDisabled: Boolean(testBtn?.disabled),
  liveDisabled: Boolean(liveBtn?.disabled),
  gateDisabled: Boolean(gateBtn?.disabled),
  evidenceText: readiness,
  summaryText: document.getElementById('ide-run-target-summary')?.innerText || '',
  preflightText: document.getElementById('ide-live-preflight')?.innerText || '',
  outputText: document.getElementById('ide-dry-run-output')?.innerText || '',
};
'''
    )
    assert_true(bool(after_checks.get("activeTabDirty")), f"validate/dry-run cleared unsaved tab dirty without save: {after_checks}", failures)
    assert_true(bool(after_checks.get("testDisabled")), f"Run Saved Test became enabled after checking but before save: {after_checks}", failures)
    assert_true(bool(after_checks.get("liveDisabled")), f"Run Saved Live became enabled after checking but before save: {after_checks}", failures)
    assert_true(bool(after_checks.get("gateDisabled")), f"Record Active Dry-run Gate became enabled after checking but before save: {after_checks}", failures)
    assert_true("VCD" in after_checks.get("evidenceText", "") or "dry-run" in after_checks.get("outputText", "").lower(), f"validate/dry-run evidence did not render: {after_checks}", failures)
    after_blocked_text = " ".join([after_checks.get("evidenceText", ""), after_checks.get("summaryText", ""), after_checks.get("preflightText", "")]).lower()
    assert_true("unsaved" in after_blocked_text and ("save" in after_blocked_text or "discard" in after_blocked_text), f"readiness stopped warning about unsaved draft after checks: {after_checks}", failures)
    assert_true("executable graph is ready" not in after_blocked_text, f"readiness claims ready while unsaved draft is blocked: {after_checks}", failures)

    shot = out_dir / "runtime_ide_browser_audit_run_preflight.png"
    driver.screenshot(shot)
    return {
        "ok": not failures,
        "failures": failures,
        "initial": initial,
        "injected": injected,
        "dirty_state": dirty_state,
        "after_checks": {**after_checks, "outputText": str(after_checks.get("outputText") or "")[:1600]},
        "screenshot": str(shot),
    }


def scenario_approval_queue(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    # Verify the operator-facing Human Approval Queue can resolve approvals from the UI.
    failures: list[str] = []
    state = http_json(base_url, "/api/state", timeout_s=10.0)
    run_id = str((state.get("state") or {}).get("run_id") or "")
    assert_true(bool(run_id), f"no current run id for approval audit: {state}", failures)
    if not run_id:
        return {"ok": False, "failures": failures}

    def create_approval(label: str) -> tuple[str, dict[str, Any]]:
        payload = {
            "title": f"Browser audit approval {label}",
            "reason": "Runtime IDE approval queue browser audit",
            "stage": "guardian",
            "safety_class": "browser-audit",
            "payload": {"audit_label": label},
        }
        result = http_json(base_url, f"/api/runs/{run_id}/approvals", method="POST", payload=payload, timeout_s=10.0)
        return str(result.get("approval_id") or ""), result

    approve_id, approve_created = create_approval("approve")
    reject_id, reject_created = create_approval("reject")
    assert_true(bool(approve_created.get("ok") and approve_id), f"failed to create approve approval: {approve_created}", failures)
    assert_true(bool(reject_created.get("ok") and reject_id), f"failed to create reject approval: {reject_created}", failures)

    driver.open(f"{base_url.rstrip('/')}/ide")
    before = wait_for_js(
        driver,
        r'''
const approveId = arguments[0];
const rejectId = arguments[1];
return (async () => {
  if (typeof loadRunContext === 'function') await loadRunContext();
  await new Promise((resolve) => setTimeout(resolve, 350));
  const approveItem = document.querySelector(`[data-approval-item-id="${approveId}"]`);
  const rejectItem = document.querySelector(`[data-approval-item-id="${rejectId}"]`);
  return {
    queueText: document.getElementById('ide-approval-queue')?.innerText || '',
    approveVisible: Boolean(approveItem),
    rejectVisible: Boolean(rejectItem),
    approveButton: Boolean(approveItem?.querySelector('[data-approval-decision="approved"]')),
    rejectButton: Boolean(rejectItem?.querySelector('[data-approval-decision="rejected"]')),
  };
})();
''',
        args=[approve_id, reject_id],
        timeout_s=8.0,
    )
    assert_true(bool(before and before.get("approveVisible")), f"approve item not visible: {before}", failures)
    assert_true(bool(before and before.get("rejectVisible")), f"reject item not visible: {before}", failures)
    assert_true(bool(before and before.get("approveButton")), f"approve button missing: {before}", failures)
    assert_true(bool(before and before.get("rejectButton")), f"reject button missing: {before}", failures)

    click_result = driver.js(
        r'''
const approveId = arguments[0];
const rejectId = arguments[1];
const approveButton = document.querySelector(`[data-approval-item-id="${approveId}"] [data-approval-decision="approved"]`);
const rejectButton = document.querySelector(`[data-approval-item-id="${rejectId}"] [data-approval-decision="rejected"]`);
if (approveButton) approveButton.click();
setTimeout(() => { if (rejectButton) rejectButton.click(); }, 300);
return {approveClicked: Boolean(approveButton), rejectClicked: Boolean(rejectButton)};
''',
        args=[approve_id, reject_id],
    )
    assert_true(bool(click_result.get("approveClicked")), f"approve click failed: {click_result}", failures)
    assert_true(bool(click_result.get("rejectClicked")), f"reject click failed: {click_result}", failures)

    queues: dict[str, Any] = {}
    deadline = time.time() + 10.0
    while time.time() < deadline:
        queues = http_json(base_url, f"/api/runs/{run_id}/approvals", timeout_s=10.0)
        resolved = queues.get("resolved", [])
        approved = any(str(item.get("approval_id")) == approve_id and item.get("decision") == "approved" for item in resolved)
        rejected = any(str(item.get("approval_id")) == reject_id and item.get("decision") == "rejected" for item in resolved)
        if approved and rejected:
            break
        time.sleep(0.25)
    resolved = queues.get("resolved", [])
    assert_true(any(str(item.get("approval_id")) == approve_id and item.get("decision") == "approved" for item in resolved), f"approve item not resolved through API: {queues}", failures)
    assert_true(any(str(item.get("approval_id")) == reject_id and item.get("decision") == "rejected" for item in resolved), f"reject item not resolved through API: {queues}", failures)

    after = wait_for_js(
        driver,
        r'''
const approveId = arguments[0];
const rejectId = arguments[1];
return (async () => {
  if (typeof loadRunContext === 'function') await loadRunContext();
  await new Promise((resolve) => setTimeout(resolve, 350));
  return {
    queueText: document.getElementById('ide-approval-queue')?.innerText || '',
    approveStillPending: Boolean(document.querySelector(`[data-approval-item-id="${approveId}"]`)),
    rejectStillPending: Boolean(document.querySelector(`[data-approval-item-id="${rejectId}"]`)),
    eventLogText: document.getElementById('ide-event-log')?.innerText || '',
  };
})();
''',
        args=[approve_id, reject_id],
        timeout_s=8.0,
    )
    assert_true(not bool(after and after.get("approveStillPending")), f"approved item still pending in UI: {after}", failures)
    assert_true(not bool(after and after.get("rejectStillPending")), f"rejected item still pending in UI: {after}", failures)
    shot = out_dir / "runtime_ide_browser_audit_approval_queue.png"
    driver.screenshot(shot)
    return {
        "ok": not failures,
        "failures": failures,
        "run_id": run_id,
        "approve_id": approve_id,
        "reject_id": reject_id,
        "before": before,
        "after": after,
        "resolved_count": len(resolved),
        "screenshot": str(shot),
    }


def scenario_timeline_replay(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    # Verify selecting a timeline event fills operator detail and replay preview panels.
    failures: list[str] = []
    state = http_json(base_url, "/api/state", timeout_s=10.0)
    run_id = str((state.get("state") or {}).get("run_id") or "")
    events: list[dict[str, Any]] = []
    if run_id:
        events = [item for item in http_json(base_url, f"/api/runs/{run_id}/events", timeout_s=10.0).get("events", []) if isinstance(item, dict)]
    if not any(event_type_name(event) in {"node.started", "edge.traversed"} for event in events):
        seeded = scenario_saved_test_run(driver, base_url, out_dir)
        run_id = str(seeded.get("run_id") or run_id)
        assert_true(bool(seeded.get("ok")), f"failed to seed timeline replay run: {seeded}", failures)
        if run_id:
            events = [item for item in http_json(base_url, f"/api/runs/{run_id}/events", timeout_s=10.0).get("events", []) if isinstance(item, dict)]
    assert_true(any(event_type_name(event) in {"node.started", "edge.traversed"} for event in events), f"no replayable runtime events found for run={run_id}", failures)

    driver.open(f"{base_url.rstrip('/')}/ide")
    dom_state = wait_for_js(
        driver,
        r'''
return (async () => {
  if (typeof loadRunContext === 'function') await loadRunContext();
  await new Promise((resolve) => setTimeout(resolve, 450));
  const rows = [...document.querySelectorAll('#ide-run-timeline [data-event-index]')];
  const row = rows.find((el) => (el.innerText || '').includes('node.started')) || rows.find((el) => (el.innerText || '').includes('edge.traversed'));
  if (row) row.click();
  await new Promise((resolve) => setTimeout(resolve, 1800));
  const replayButton = document.querySelector('[data-event-detail-action="replay-stage"]');
  const replayButtonDisabled = Boolean(replayButton?.disabled);
  if (replayButton && !replayButtonDisabled) replayButton.click();
  await new Promise((resolve) => setTimeout(resolve, 1800));
  const detail = document.getElementById('ide-event-detail')?.innerText || '';
  const replay = document.getElementById('ide-replay-output')?.innerText || '';
  return {
    rowFound: Boolean(row),
    rowText: row?.innerText || '',
    detailText: detail,
    replayText: replay,
    selectedNode: window.atrRuntimeIdeState?.selectedNodeId || '',
    replayButtonDisabled,
    hasDecisionStrip: detail.toLowerCase().includes('replay basis') && detail.toLowerCase().includes('runtime target'),
    hasPayloadJson: detail.includes('Payload JSON'),
    hasReplayEvidence: replay.includes('Replay basis') && (replay.toLowerCase().includes('compiled') || replay.toLowerCase().includes('validation') || replay.toLowerCase().includes('dispatch')),
    markedNodes: document.querySelectorAll('#ide-graph-canvas .runtime-ide-node.active, #ide-graph-canvas .runtime-ide-node.visited, #ide-graph-canvas .runtime-ide-node.selected').length,
  };
})();
''',
        timeout_s=12.0,
    )
    assert_true(bool(dom_state and dom_state.get("rowFound")), f"timeline event row not found: {dom_state}", failures)
    assert_true(bool(dom_state and dom_state.get("hasDecisionStrip")), f"event detail decision strip missing: {dom_state}", failures)
    assert_true(bool(dom_state and dom_state.get("hasPayloadJson")), f"event detail payload JSON missing: {dom_state}", failures)
    assert_true(not bool(dom_state and dom_state.get("replayButtonDisabled")), f"Replay From Stage button disabled: {dom_state}", failures)
    assert_true(bool(dom_state and dom_state.get("hasReplayEvidence")), f"replay output missing dry-run evidence: {dom_state}", failures)
    assert_true(int((dom_state or {}).get("markedNodes") or 0) >= 1, f"timeline selection did not mark graph nodes: {dom_state}", failures)
    shot = out_dir / "runtime_ide_browser_audit_timeline_replay.png"
    driver.screenshot(shot)
    trimmed = dict(dom_state or {})
    trimmed["detailText"] = str(trimmed.get("detailText") or "")[:1800]
    trimmed["replayText"] = str(trimmed.get("replayText") or "")[:1800]
    return {
        "ok": not failures,
        "failures": failures,
        "run_id": run_id,
        "event_count": len(events),
        "dom_state": trimmed,
        "screenshot": str(shot),
    }


def scenario_invalid_handler(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    driver.open(f"{base_url.rstrip('/')}/ide")
    injected = driver.js(
        r'''
const ta = document.getElementById('ide-graph-json');
const graph = JSON.parse(ta.value || '{}');
const design = (graph.nodes || []).find((node) => node.id === 'design');
if (!design) return {ok:false, reason:'design node missing'};
design.handler = 'runtime.not_registered_for_negative_ui_test';
ta.value = JSON.stringify(graph, null, 2);
ta.dispatchEvent(new Event('change', {bubbles:true}));
return {ok:true, handler:design.handler};
'''
    )
    time.sleep(0.8)
    after = driver.js(
        r'''
const readiness = document.getElementById('ide-runtime-readiness');
const designNode = document.querySelector('[data-node-id="design"]');
const issue = [...document.querySelectorAll('.runtime-readiness-issue')].find((el) => el.innerText.includes('Unregistered graph handler'));
if (issue) issue.click();
return {
  readinessText: readiness?.innerText || '',
  readinessClass: readiness?.querySelector('.runtime-readiness-card')?.className || '',
  designClass: designNode?.className || '',
  designBadge: designNode?.querySelector('.runtime-node-readiness-badge')?.innerText || '',
  issueText: issue?.innerText || '',
  issueExists: Boolean(issue),
};
'''
    )
    time.sleep(1.0)
    focused = driver.js(
        r'''
return {
  selected: window.atrRuntimeIdeState?.selectedNodeId || '',
  selectedBadge: document.getElementById('ide-selected-node')?.innerText || '',
  inspectorText: document.getElementById('ide-node-inspector')?.innerText || '',
  designClass: document.querySelector('[data-node-id="design"]')?.className || '',
};
'''
    )
    failures: list[str] = []
    assert_true(bool(injected.get("ok")), "failed to inject invalid handler", failures)
    assert_true(bool(after.get("issueExists")), "readiness issue row not created", failures)
    assert_true("error" in after.get("readinessClass", ""), "readiness card is not error", failures)
    assert_true("readiness-error" in after.get("designClass", ""), "design node missing readiness-error class", failures)
    assert_true("handler" in after.get("designBadge", "").lower(), "design node badge does not mention handler", failures)
    assert_true(focused.get("selected") == "design", "readiness issue click did not select design node", failures)
    assert_true("runtime.not_registered_for_negative_ui_test" in focused.get("inspectorText", ""), "inspector does not show invalid handler", failures)
    shot = out_dir / "runtime_ide_browser_audit_invalid_handler.png"
    driver.screenshot(shot)
    return {
        "ok": not failures,
        "failures": failures,
        "injected": injected,
        "after": after,
        "focused": {**focused, "inspectorText": focused.get("inspectorText", "")[:1200]},
        "screenshot": str(shot),
    }


def scenario_invalid_module(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    driver.open(f"{base_url.rstrip('/')}/ide")
    injected = driver.js(
        r'''
const ta = document.getElementById('ide-graph-json');
const graph = JSON.parse(ta.value || '{}');
const design = (graph.nodes || []).find((node) => node.id === 'design');
if (!design) return {ok:false, reason:'design node missing'};
design.module_id = 'modules/not_real_negative_ui_test';
ta.value = JSON.stringify(graph, null, 2);
ta.dispatchEvent(new Event('change', {bubbles:true}));
return {ok:true, module_id:design.module_id};
'''
    )
    time.sleep(0.8)
    after = driver.js(
        r'''
const readiness = document.getElementById('ide-runtime-readiness');
const designNode = document.querySelector('[data-node-id="design"]');
const issue = [...document.querySelectorAll('.runtime-readiness-issue')].find((el) => el.innerText.includes('Missing module config'));
if (issue) issue.click();
return {
  readinessText: readiness?.innerText || '',
  readinessClass: readiness?.querySelector('.runtime-readiness-card')?.className || '',
  designClass: designNode?.className || '',
  designBadge: designNode?.querySelector('.runtime-node-readiness-badge')?.innerText || '',
  issueText: issue?.innerText || '',
  issueExists: Boolean(issue),
};
'''
    )
    time.sleep(1.0)
    focused = driver.js(
        r'''
return {
  selected: window.atrRuntimeIdeState?.selectedNodeId || '',
  selectedBadge: document.getElementById('ide-selected-node')?.innerText || '',
  inspectorText: document.getElementById('ide-node-inspector')?.innerText || '',
  moduleButtonFocused: document.querySelector('[data-open-module-management="1"]')?.className || '',
  designClass: document.querySelector('[data-node-id="design"]')?.className || '',
};
'''
    )
    failures: list[str] = []
    assert_true(bool(injected.get("ok")), "failed to inject invalid module", failures)
    assert_true(bool(after.get("issueExists")), "missing module issue row not created", failures)
    assert_true("error" in after.get("readinessClass", ""), "readiness card is not error", failures)
    assert_true("readiness-error" in after.get("designClass", ""), "design node missing readiness-error class", failures)
    assert_true("module" in after.get("designBadge", "").lower(), "design node badge does not mention module", failures)
    assert_true(focused.get("selected") == "design", "readiness issue click did not select design node", failures)
    assert_true("not_real_negative_ui_test" in focused.get("inspectorText", ""), "inspector does not show invalid module id", failures)
    shot = out_dir / "runtime_ide_browser_audit_invalid_module.png"
    driver.screenshot(shot)
    return {
        "ok": not failures,
        "failures": failures,
        "injected": injected,
        "after": after,
        "focused": {**focused, "inspectorText": focused.get("inspectorText", "")[:1200]},
        "screenshot": str(shot),
    }


def scenario_invalid_route(driver: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    driver.open(f"{base_url.rstrip('/')}/ide")
    injected = driver.js(
        r'''
const ta = document.getElementById('ide-graph-json');
const graph = JSON.parse(ta.value || '{}');
if (!graph.transitions || !graph.transitions.design) return {ok:false, reason:'design transition missing'};
delete graph.transitions.design;
graph.edges = (graph.edges || []).filter((edge) => !(edge?.metadata?.runtime_edge === 'logical_transition' && (edge.metadata.from_stage || edge.source) === 'design'));
ta.value = JSON.stringify(graph, null, 2);
ta.dispatchEvent(new Event('change', {bubbles:true}));
return {ok:true, transition_design: graph.transitions.design || null, edge_count: graph.edges.length};
'''
    )
    time.sleep(0.8)
    after = driver.js(
        r'''
const readiness = document.getElementById('ide-runtime-readiness');
const designNode = document.querySelector('[data-node-id="design"]');
const issue = [...document.querySelectorAll('.runtime-readiness-issue')].find((el) => el.innerText.includes('Route coverage gap') && el.innerText.includes('design'));
if (issue) issue.click();
return {
  readinessText: readiness?.innerText || '',
  readinessClass: readiness?.querySelector('.runtime-readiness-card')?.className || '',
  designClass: designNode?.className || '',
  designBadge: designNode?.querySelector('.runtime-node-readiness-badge')?.innerText || '',
  issueText: issue?.innerText || '',
  issueExists: Boolean(issue),
};
'''
    )
    time.sleep(1.0)
    focused = driver.js(
        r'''
return {
  selected: window.atrRuntimeIdeState?.selectedNodeId || '',
  selectedBadge: document.getElementById('ide-selected-node')?.innerText || '',
  transitionSource: document.getElementById('ide-transition-source')?.value || '',
  transitionStatus: document.getElementById('ide-edge-edit-status')?.innerText || '',
  designClass: document.querySelector('[data-node-id="design"]')?.className || '',
};
'''
    )
    failures: list[str] = []
    assert_true(bool(injected.get("ok")), "failed to inject route gap", failures)
    assert_true(bool(after.get("issueExists")), "route coverage issue row not created", failures)
    assert_true("error" in after.get("readinessClass", ""), "readiness card is not error", failures)
    assert_true("readiness-error" in after.get("designClass", ""), "design node missing readiness-error class", failures)
    assert_true("route" in after.get("designBadge", "").lower(), "design node badge does not mention route", failures)
    assert_true(focused.get("selected") == "design", "readiness issue click did not select design node", failures)
    assert_true(focused.get("transitionSource") == "design", "route issue did not focus transition source=design", failures)
    assert_true("fix route coverage" in focused.get("transitionStatus", "").lower(), "transition editor status does not explain route repair", failures)
    shot = out_dir / "runtime_ide_browser_audit_invalid_route.png"
    driver.screenshot(shot)
    return {
        "ok": not failures,
        "failures": failures,
        "injected": injected,
        "after": after,
        "focused": focused,
        "screenshot": str(shot),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Runtime IDE browser audit")
    parser.add_argument("--base-url", default="http://127.0.0.1:7861")
    parser.add_argument("--webdriver-url", default="http://127.0.0.1:4448")
    parser.add_argument("--scenario", choices=["layout", "evidence", "graph-switch", "canvas-interactions", "workspace-artifacts", "saved-test-run", "save-version-lifecycle", "run-preflight", "discard-draft", "approval-queue", "timeline-replay", "invalid-handler", "invalid-module", "invalid-route", "all"], default="all")
    parser.add_argument("--out-dir", default="artifacts/ui")
    parser.add_argument("--width", type=int, default=1366)
    parser.add_argument("--height", type=int, default=768)
    args = parser.parse_args()

    driver = WebDriverAudit(args.webdriver_url, width=args.width, height=args.height)
    try:
        driver.start()
    except (urllib.error.URLError, TimeoutError) as exc:
        print(json.dumps({"ok": False, "error": f"failed to connect to geckodriver: {exc}"}, indent=2), file=sys.stderr)
        return 2

    results: dict[str, Any] = {}
    try:
        out_dir = Path(args.out_dir)
        if args.scenario in {"layout", "all"}:
            results["layout"] = scenario_layout(driver, args.base_url, out_dir)
        if args.scenario in {"evidence", "all"}:
            results["evidence"] = scenario_evidence(driver, args.base_url, out_dir)
        if args.scenario in {"graph-switch", "all"}:
            results["graph_switch"] = scenario_graph_switch(driver, args.base_url, out_dir)
        if args.scenario in {"canvas-interactions", "all"}:
            results["canvas_interactions"] = scenario_canvas_interactions(driver, args.base_url, out_dir)
        if args.scenario in {"workspace-artifacts", "all"}:
            results["workspace_artifacts"] = scenario_workspace_artifacts(driver, args.base_url, out_dir)
        if args.scenario in {"run-preflight", "all"}:
            results["run_preflight"] = scenario_run_preflight(driver, args.base_url, out_dir)
        if args.scenario in {"discard-draft", "all"}:
            results["discard_draft"] = scenario_discard_draft(driver, args.base_url, out_dir)
        if args.scenario in {"save-version-lifecycle", "all"}:
            results["save_version_lifecycle"] = scenario_save_version_lifecycle(driver, args.base_url, out_dir)
        if args.scenario in {"saved-test-run", "all"}:
            results["saved_test_run"] = scenario_saved_test_run(driver, args.base_url, out_dir)
        if args.scenario in {"approval-queue", "all"}:
            results["approval_queue"] = scenario_approval_queue(driver, args.base_url, out_dir)
        if args.scenario in {"timeline-replay", "all"}:
            results["timeline_replay"] = scenario_timeline_replay(driver, args.base_url, out_dir)
        if args.scenario in {"invalid-handler", "all"}:
            results["invalid_handler"] = scenario_invalid_handler(driver, args.base_url, out_dir)
        if args.scenario in {"invalid-module", "all"}:
            results["invalid_module"] = scenario_invalid_module(driver, args.base_url, out_dir)
        if args.scenario in {"invalid-route", "all"}:
            results["invalid_route"] = scenario_invalid_route(driver, args.base_url, out_dir)
    finally:
        driver.stop()

    ok = all(item.get("ok") for item in results.values())
    print(json.dumps({"ok": ok, "results": results}, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
