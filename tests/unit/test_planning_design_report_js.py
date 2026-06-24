"""Regression tests for Design Agent report helpers in planning.js."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLANNING_JS = PROJECT_ROOT / "web" / "static" / "planning.js"


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    assert start >= 0, f"{name} helper is missing from planning.js"
    paren_depth = 0
    body_search_start = -1
    for index in range(start + len(f"function {name}"), len(source)):
        char = source[index]
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
            if paren_depth == 0:
                body_search_start = index + 1
                break
    assert body_search_start >= 0, f"{name} helper signature is incomplete"
    brace = source.find("{", body_search_start)
    assert brace >= 0, f"{name} helper has no body"
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"{name} helper body is incomplete")


def _node_eval(script: str) -> str:
    node = shutil.which("node")
    assert node, "node is required for planning.js helper tests"
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_design_heatmap_groups_duplicate_coordinates_and_keeps_selected_cell() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    helper = _extract_function(source, "groupDesignHeatmapCells")
    script = f"""
const dashboardFiniteNumber = (value) => {{
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}};
const numberText = (value, digits = 2) => {{
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return String(Number(number.toFixed(digits)));
}};
{helper}
const rows = groupDesignHeatmapCells([
  {{ candidate_id: "cand-5-03", x: 0.2, y: 2.0, value: 0.9004, status: "selected" }},
  {{ candidate_id: "cand-5-10", x: 0.2, y: 2.0, value: 0.8619, status: "valid" }},
  {{ candidate_id: "cand-5-01", x: 0.18, y: 1.2, value: 0.6854, status: "valid" }},
]);
console.log(JSON.stringify(rows));
"""
    rows = json.loads(_node_eval(script))

    grouped = [row for row in rows if row["x"] == 0.2 and row["y"] == 2]
    assert len(grouped) == 1
    assert grouped[0]["candidate_id"] == "cand-5-03"
    assert grouped[0]["value"] == 0.9004
    assert grouped[0]["member_count"] == 2
    assert [member["candidate_id"] for member in grouped[0]["members"]] == ["cand-5-03", "cand-5-10"]


def test_design_capture_mode_labels_actual_render_source() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    helper = _extract_function(source, "designCandidateCaptureMode")
    script = f"""
{helper}
console.log(JSON.stringify([
  designCandidateCaptureMode({{}}, "/api/runs/run/artifact-file/design_candidates/cand-1/viewer_capture.png"),
  designCandidateCaptureMode({{}}, "/api/runs/run/artifact-file/specimens/specimen-1/specimen_preview.svg"),
  designCandidateCaptureMode({{}}, ""),
]));
"""
    labels = json.loads(_node_eval(script))

    assert labels == ["STL VIEWER PNG", "SVG PREVIEW", "CANVAS FALLBACK"]


def test_live_agent_events_are_scoped_to_current_run() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    helpers = "\n".join(
        _extract_function(source, name)
        for name in ("eventRunId", "eventMatchesCurrentRun", "currentRunEventSources")
    )
    script = f"""
function eventPayload(event) {{ return event && typeof event.payload === "object" ? event.payload : {{}}; }}
function liveCurrentRunId() {{ return "run-current"; }}
let liveRunEvents = [];
let liveRecentEvents = [
  {{ event_id: "old-spc", run_id: "run-old", event_type: "artifact.created", payload: {{ agent: "specimen" }} }},
  {{ event_id: "current-design", run_id: "run-current", event_type: "module_step_completed", payload: {{ agent: "design" }} }},
  {{ event_id: "global-no-run", event_type: "artifact.created", payload: {{ agent: "specimen" }} }},
];
{helpers}
console.log(JSON.stringify(currentRunEventSources().map((event) => event.event_id)));
"""
    event_ids = json.loads(_node_eval(script))

    assert event_ids == ["current-design"]


def test_normal_artifact_events_do_not_raise_agent_unread_alarm() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    helper = _extract_function(source, "isAgentNotificationEvent")
    script = f"""
function eventPayload(event) {{ return event && typeof event.payload === "object" ? event.payload : {{}}; }}
function eventTimelineKind(event) {{
  const type = String(event.event_type || event.type || "").toLowerCase();
  if (type.includes("warning")) return "warning";
  if (type.includes("artifact")) return "artifact";
  return "info";
}}
function isAgentQuestionEvent(event) {{
  const payload = eventPayload(event);
  return Boolean(payload.question || payload.requires_operator_input);
}}
{helper}
console.log(JSON.stringify([
  isAgentNotificationEvent({{ event_type: "artifact.created", payload: {{ agent: "specimen" }} }}),
  isAgentNotificationEvent({{ event_type: "runtime.warning", payload: {{ agent: "specimen" }} }}),
  isAgentNotificationEvent({{ event_type: "agent_question", payload: {{ agent: "specimen", question: "Printer path?" }} }}),
]));
"""
    values = json.loads(_node_eval(script))

    assert values == [False, True, True]


def test_design_capture_image_renders_clickable_gallery_trigger() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    helpers = "\n".join(
        _extract_function(source, name)
        for name in ("designCaptureImageUrl", "renderDesignCaptureImage")
    )
    script = f"""
function escapeHtml(value) {{
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\\"": "&quot;", "'": "&#39;" }}[ch]));
}}
function numberText(value, digits = 2) {{
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return String(Number(number.toFixed(digits)));
}}
function renderDesignCaptureSnapshot() {{ return "<canvas></canvas>"; }}
{helpers}
const html = renderDesignCaptureImage(
  "/api/runs/run/artifact-file/design_candidates/cand-1/viewer_capture.png",
  {{ geometry: "gyroid", score: 0.8421 }},
  "cand-1",
  1,
  {{ mode: "STL VIEWER PNG" }}
);
console.log(JSON.stringify({{
  hasButton: html.includes("ar-design-capture-open"),
  hasCacheBuster: html.includes("render=solid-stl-v3"),
  hasCandidate: html.includes('data-design-candidate-id="cand-1"'),
  hasMeta: html.includes("gyroid · obj 0.842 · STL VIEWER PNG"),
}}));
"""
    result = json.loads(_node_eval(script))

    assert result == {
        "hasButton": True,
        "hasCacheBuster": True,
        "hasCandidate": True,
        "hasMeta": True,
    }


def test_planning_js_mentions_specimen_pose_and_d455f_return() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")

    assert "specimen_pose" in source
    assert "camera_returned_to_vla" in source
    assert "VLA camera" in source
    assert "D455F" in source
