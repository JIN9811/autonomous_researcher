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


def test_evidence_cards_show_units_and_unassessed_performance_without_proxy_scores():
    source = PLANNING_JS.read_text(encoding="utf-8")
    functions = "\n".join(_extract_function(source, name) for name in (
        "renderDesignEvidence", "renderDesignExpectedPerformance", "renderDesignSpecimenMetricStrip"))
    evaluation = {"schema":"design_evaluation.v1", "validity":{"status":"pass", "reasons":[]},
                  "performance":{"status":"unassessed", "value":None},
                  "cost":{"mass":{"value":0,"unit":"g","status":"estimated"},
                          "duration":{"value":32,"unit":"min","status":"rough_heuristic"}},
                  "constraint_margins":[{"constraint":"minimum_wall", "margin":0.2,"unit":"mm","status":"pass"}]}
    script = f"""
const escapeHtml = s => String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');
const renderRuntimeValue = v => v == null ? '-' : String(v);
{functions}
const e = {json.dumps(evaluation)};
const report = {{design_evaluation:e, candidate_evaluation:{{selected_score:0.9988}}}};
console.log(JSON.stringify([
 renderDesignExpectedPerformance({{}}, report, {{expected_objective_proxy_score:0.9988}}),
 renderDesignSpecimenMetricStrip({{design_evaluation:e, expected_objective_proxy_score:0.9988}}),
 renderDesignEvidence(e, true)
]));
"""
    html = " ".join(json.loads(_node_eval(script)))
    assert "unassessed" in html
    assert "0 g" in html
    assert "32 min" in html
    assert "0.2 mm" in html
    assert "0.9988" not in html


def test_blocked_decision_dashboard_does_not_render_previous_ready_spec():
    function = _extract_function(PLANNING_JS.read_text(), "renderDesignDashboardCards")
    script = f"""
const latestDesignAgentReport = () => ({{}});
const latestDesignReport = () => ({{design_decision:{{status:'returned', reason:'Review evidence'}}}});
const runtimeRows = rows => JSON.stringify(rows);
const renderDashboardCard = (title, body) => title + body;
{function}
console.log(renderDesignDashboardCards({{spec:{{candidate_id:'previous',expected_objective_proxy_score:0.9988}}}}));
"""
    html = _node_eval(script)
    assert "blocked" in html
    assert "Review evidence" in html
    assert "previous" not in html
    assert "0.9988" not in html


def test_actual_specimen_card_prefers_exact_specimen_evidence_not_candidate_ledger():
    source = PLANNING_JS.read_text()
    helpers = "\n".join(_extract_function(source, name) for name in (
        "designActualSpecimenRows", "mergeDesignActualSpecimenRecord"))
    script = f"""
const designCandidateRows = () => [{{candidate_id:'c1', design_evaluation:{{validity:{{status:'pass'}}}}}}];
const liveRunArtifacts = [{{path:'current/specimen.stl'}}, {{path:'old/specimen.stl'}}];
const designSpecimenIdFromPath = path => path.split('/')[0];
const designCandidateIdFromSpecimenId = () => 'c1';
const designLoopIndexFromIds = () => 1;
const dashboardFiniteNumber = Number;
const latestSpecimenAgentReport = () => ({{}});
const latestSpecimenFabricationReport = () => ({{}});
const latestSpecimenFabricatedPacket = () => ({{}});
{helpers}
console.log(JSON.stringify(designActualSpecimenRows({{}}, {{}}, {{spec:{{specimen_id:'current',
 candidate_fingerprint:'adapted', design_evaluation:{{scope:'adapted_spec_unassessed',validity:{{status:'unassessed'}}}}}}}})));
"""
    rows = json.loads(_node_eval(script))
    current = next(row for row in rows if row["specimen_id"] == "current")
    old = next(row for row in rows if row["specimen_id"] == "old")
    assert current["candidate_fingerprint"] == "adapted"
    assert current["design_evaluation"]["scope"] == "adapted_spec_unassessed"
    assert old["design_evaluation"]["validity"]["status"] == "unassessed"
    assert "scope" not in old["design_evaluation"]


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


def test_spc_preview_selects_exact_dsn_specimen_one_at_a_time() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    helper = _extract_function(source, "selectSpecimenDesignPreviewRecord")
    script = f"""
{helper}
const rows = [
  {{ specimen_id: "specimen-cand-1-01", candidate_id: "cand-1-01", loop_index: 1 }},
  {{ specimen_id: "specimen-cand-2-04", candidate_id: "cand-2-04", loop_index: 2 }},
  {{ specimen_id: "specimen-cand-3-02", candidate_id: "cand-3-02", loop_index: 3 }},
];
console.log(JSON.stringify({{
  exactSpecimen: selectSpecimenDesignPreviewRecord(rows, {{ specimenId: "specimen-cand-2-04" }}),
  exactCandidate: selectSpecimenDesignPreviewRecord(rows, {{ candidateId: "cand-1-01" }}),
  exactLoop: selectSpecimenDesignPreviewRecord(rows, {{ loopIndex: 3 }}),
  latestFallback: selectSpecimenDesignPreviewRecord(rows, {{}}),
}}));
"""
    selected = json.loads(_node_eval(script))

    assert selected["exactSpecimen"]["specimen_id"] == "specimen-cand-2-04"
    assert selected["exactCandidate"]["candidate_id"] == "cand-1-01"
    assert selected["exactLoop"]["loop_index"] == 3
    assert selected["latestFallback"]["specimen_id"] == "specimen-cand-3-02"


def test_spc_now_printing_preview_uses_dsn_capture_contract() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    body = _extract_function(source, "renderSpecimenNowPrintingBody")

    assert "specimenDesignPreviewRecord(ctx, report)" in body
    assert "designCandidateCaptureUrl" in body
    assert "ctx.layerPreview.viewer_capture_url" not in body
    assert "ctx.thread.viewer_capture_url" not in body


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
