"""Contract tests for shared BO visualization cards in Live GUI."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLANNING_JS = PROJECT_ROOT / "web" / "static" / "planning.js"
BO_OWNER_JS = PROJECT_ROOT / "agents" / "bo" / "frontend" / "live_report.js"
DESIGN_OWNER_JS = PROJECT_ROOT / "agents" / "design" / "frontend" / "live_report.js"


def _inspect_source() -> dict[str, object]:
    node = shutil.which("node")
    assert node, "node is required for Live GUI BO source-contract tests"
    script = f"""
const fs = require("fs");
const source = fs.readFileSync({json.dumps(str(PLANNING_JS))}, "utf8");
const boOwner = fs.readFileSync({json.dumps(str(BO_OWNER_JS))}, "utf8");
const designOwner = fs.readFileSync({json.dumps(str(DESIGN_OWNER_JS))}, "utf8");
const start = boOwner.indexOf("function renderDashboard");
const end = boOwner.indexOf("function dispose", start);
const body = boOwner.slice(start, end);
const renderKeyStart = source.indexOf("function liveCenterRenderKey");
const renderKeyEnd = source.indexOf("function invalidateLiveCenterRender", renderKeyStart);
const renderKeyBody = source.slice(renderKeyStart, renderKeyEnd);
const updateStart = source.indexOf("function updateLiveBoVisualizationCards");
const updateEnd = source.indexOf("async function hydrateLiveBoVisualization", updateStart);
const updateBody = source.slice(updateStart, updateEnd);
const preferenceStart = source.indexOf("function preferredLiveBoVisualization");
const preferenceEnd = source.indexOf("function clearLiveBoVisualization", preferenceStart);
const preferenceBody = source.slice(preferenceStart, preferenceEnd);
const hydrateStart = source.indexOf("async function hydrateLiveBoVisualization");
const hydrateEnd = source.indexOf("function connectPlanningEventStream", hydrateStart);
const hydrateBody = source.slice(hydrateStart, hydrateEnd);
const applyStart = source.indexOf("function applyPlanningSession");
const applyEnd = source.indexOf("async function refreshLiveGraphPayload", applyStart);
const applyBody = source.slice(applyStart, applyEnd);
const chatStart = source.indexOf("function renderBoExpandedBody");
const chatEnd = source.indexOf("function renderBoCollapsedBody", chatStart);
const chatBody = source.slice(chatStart, chatEnd);
const resultStart = source.indexOf("function renderBoResultCard");
const resultEnd = source.indexOf("function renderRuntimeValue", resultStart);
const resultBody = source.slice(resultStart, resultEnd);
const detailsStart = boOwner.indexOf("function renderReport");
const detailsEnd = boOwner.indexOf("function renderDashboard", detailsStart);
const detailsBody = boOwner.slice(detailsStart, detailsEnd);
const specializedStart = source.indexOf("function renderAgentSpecializedDashboardSections");
const specializedEnd = source.indexOf("function renderLiveDashboardReportSections", specializedStart);
const specializedBody = source.slice(specializedStart, specializedEnd);
const designStart = designOwner.indexOf("function renderDashboard");
const designEnd = designOwner.indexOf("function renderReport", designStart);
const designBody = designOwner.slice(designStart, designEnd);
console.log(JSON.stringify({{
  sharedEquation: body.includes("renderer.renderEquationCard"),
  sharedPlot: body.includes("renderer.renderPlot"),
  waiting: body.includes("Waiting for a completed BO step"),
  equationBeforeRanking: body.indexOf("Objective Equation") >= 0 && body.indexOf("Objective Equation") < body.indexOf("Selection Evidence"),
  posteriorBeforeRanking: body.indexOf("Live Posterior") >= 0 && body.indexOf("Live Posterior") < body.indexOf("Selection Evidence"),
  duplicateTrace: body.includes("renderBoTraceSvg"),
  sharedChatPlot: chatBody.includes("BOVisualization.renderPlot"),
  legacyChatPlot: chatBody.includes("renderBoTraceSvg"),
	  restoresMetadata: source.includes("metadata.bo_visualization"),
	  validatesReportVisualizationBeforeFallback: body.includes("resolveLiveBoVisualization")
    && source.includes("preferredLiveBoVisualization")
    && source.includes("liveBoVisualization"),
	  scopesVisualizationToRun: source.includes("function currentRunBoVisualization")
	    && source.includes("visualization.run_id")
	    && updateBody.includes("liveCurrentRunId()"),
	  preservesGraphOnTransientEmptyHydration: !hydrateBody.includes("clearLiveBoVisualization()")
	    && hydrateBody.includes("currentRunBoVisualization(liveBoVisualization, runId)"),
	  syncsVisualizationFromServerState: applyBody.includes("syncLiveBoVisualizationFromState(state)"),
	  ranksVisualizationCompleteness: preferenceBody.includes("boVisualizationPointCount")
	    && preferenceBody.includes("incomingStep > cachedStep")
	    && preferenceBody.includes("incomingPoints < cachedPoints"),
	  reportPrefersCompleteVisualization: body.includes("resolveLiveBoVisualization")
    && source.includes("preferredLiveBoVisualization"),
	  preservesVisualizationForCompactSameRunState: source.includes('Object.prototype.hasOwnProperty.call(metadata, "bo_visualization")')
	    && source.includes("currentRunBoVisualization(liveBoVisualization, state.run_id)"),
	  ignoresCompactSameRunVisualizationEvent: updateBody.includes("preferredLiveBoVisualization")
	    && updateBody.includes("scheduleLiveBoVisualizationHydration"),
	  rehydratesNewerCompactVisualization: source.includes("function scheduleLiveBoVisualizationHydration")
	    && source.includes("incomingStep > cachedStep")
	    && source.includes("scheduleLiveBoVisualizationHydration()"),
	  lhsFixedInBoDashboard: body.includes('renderDashboardCard("Initial Design / LHS", historyBody(')
	    && body.indexOf('renderDashboardCard("Initial Design / LHS"') < body.indexOf("const ranking ="),
	  keepsOriginalBoCards: body.includes("Next Experiment")
	    && body.includes("Optimization Status")
	    && body.includes("Selection Evidence")
	    && body.includes("Agentic Progress"),
	  noInitialDesignGateCard: !body.includes("BO Initialization Gate")
	    && !body.includes("Waiting for initial design data"),
	  lhsRemovedFromDesignDashboard: !designBody.includes("Initial Design / LHS")
	    && !designBody.includes("renderDesignInitialDesignBoard"),
	  designDashboardAlwaysShowsDesignSpace: designBody.includes('services.renderDashboardCard("Design Space", renderer.renderDesignSpace(screenReport')
	    && !designBody.includes("const initialDesign")
	    && !designBody.includes("initialDesign ?"),
	  lhsUsesDedicatedRenderer: source.includes("function renderBoInitialDesignBoard(report)")
	    && source.includes("function latestBoInitialDesign(report)")
	    && source.includes("LHSDesignVisualization"),
	  lhsRendererHasSingleOwner: source.split("function renderBoInitialDesignBoard(").length - 1 === 1,
	  lhsRestoresLegacyTrace: source.includes("function boLatestTrace")
	    && source.includes("boLatestTrace(boResult)")
	    && source.includes("trace.initial_design")
	    && source.includes("visualizationBackend.active"),
	  lhsChatCard: resultBody.includes("Latin Hypercube Initial Design") && resultBody.includes("acquisition inactive"),
	  lhsReportDetails: detailsBody.includes("Initial Design / LHS") && detailsBody.includes("Candidate ranking is disabled"),
	  noDuplicateGenericBoVisualization: specializedBody.includes('"analysis", "knowledge", "bo"'),
	  hydratesLatestVisualization: source.includes('fetchJsonOrThrowWithTimeout("/api/bo/config?visualization_only=true"')
    && !source.slice(source.indexOf("async function initializeLiveGuiRuntime()")).includes("hydrateLiveBoVisualization()"),
	  hydratesOnVisualizationEvent: source.includes('if (eventType === "bo.visualization.updated")')
	    && source.includes("hydrateLiveBoVisualization();"),
	  renderKeyTracksLoop: renderKeyBody.includes("state.loop_count"),
	  renderKeyTracksBoStep: renderKeyBody.includes("boVisualization.step"),
	  renderKeyTracksBoGeneration: renderKeyBody.includes("boVisualization.generated_at"),
}}));
"""
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_live_startup_does_not_restore_bo_before_chat() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    startup = source.split("async function initializeLiveGuiRuntime()", 1)[1]
    assert "hydrateLiveBoVisualization()" not in startup
    assert ".then(bootstrapLiveOrchestrator)" in startup
    assert _inspect_source()["hydratesOnVisualizationEvent"]
    icon = source.split("function renderChatGroupIcon(", 1)[1].split("function renderPlanningChatMessageDetail", 1)[0]
    assert 'loading="eager"' in icon
    assert 'loading="lazy"' not in icon


def test_live_gui_bo_dashboard_uses_shared_equation_and_posterior_renderer() -> None:
    assert _inspect_source() == {
        "sharedEquation": True,
        "sharedPlot": True,
        "waiting": True,
        "equationBeforeRanking": True,
        "posteriorBeforeRanking": True,
        "duplicateTrace": False,
        "sharedChatPlot": True,
        "legacyChatPlot": False,
	        "restoresMetadata": True,
	        "validatesReportVisualizationBeforeFallback": True,
	        "scopesVisualizationToRun": True,
	        "preservesGraphOnTransientEmptyHydration": True,
	        "syncsVisualizationFromServerState": True,
	        "ranksVisualizationCompleteness": True,
	        "reportPrefersCompleteVisualization": True,
	        "preservesVisualizationForCompactSameRunState": True,
	        "ignoresCompactSameRunVisualizationEvent": True,
	        "rehydratesNewerCompactVisualization": True,
	        "lhsFixedInBoDashboard": True,
	        "keepsOriginalBoCards": True,
	        "noInitialDesignGateCard": True,
	        "lhsRemovedFromDesignDashboard": True,
	        "designDashboardAlwaysShowsDesignSpace": True,
	        "lhsUsesDedicatedRenderer": True,
	        "lhsRendererHasSingleOwner": True,
	        "lhsRestoresLegacyTrace": True,
	        "lhsChatCard": True,
	        "lhsReportDetails": True,
	        "noDuplicateGenericBoVisualization": True,
	        "hydratesLatestVisualization": True,
	        "hydratesOnVisualizationEvent": True,
	        "renderKeyTracksLoop": True,
	        "renderKeyTracksBoStep": True,
	        "renderKeyTracksBoGeneration": True,
    }


def test_live_gui_bo_report_prefers_newer_runtime_visualization() -> None:
    node = shutil.which("node")
    assert node
    source = PLANNING_JS.read_text(encoding="utf-8")
    payload_start = source.index("function latestReportPayload")
    payload_end = source.index("function latestDesignReport", payload_start)
    start = source.index("function latestReportBoResult")
    end = source.index("function latestReportArtifacts", start)
    function_source = source[payload_start:payload_end] + source[start:end]
    script = f"""
{function_source}
const report = {{
  sections: {{ bo_result: {{ visualization: {{ schema: "bo_visualization.v1", step: 1 }} }} }},
  state: {{ run_metadata: {{
    bo_agent: {{ visualization: {{ schema: "bo_visualization.v1", step: 1 }} }},
    bo_visualization: {{
      schema: "bo_visualization.v1",
      step: 8,
      artifacts: {{ png_url: "/api/runs/run-1/artifact-file/runtime/bo/step-008.png" }},
    }},
  }} }},
  messages: [],
}};
const selected = latestReportBoResult(report);
console.log(JSON.stringify({{ step: selected.visualization.step, png: selected.visualization.artifacts.png_url }}));
"""
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    assert json.loads(result.stdout) == {
        "step": 8,
        "png": "/api/runs/run-1/artifact-file/runtime/bo/step-008.png",
    }


def test_live_gui_bo_report_prefers_current_metadata_over_historical_evidence() -> None:
    node = shutil.which("node")
    assert node
    source = PLANNING_JS.read_text(encoding="utf-8")
    payload_start = source.index("function latestReportPayload")
    payload_end = source.index("function latestDesignReport", payload_start)
    result_start = source.index("function latestReportBoResult")
    result_end = source.index("function resolveLiveBoVisualization", result_start)
    backend_start = source.index("function backendField")
    backend_end = source.index("function eventRunId", backend_start)
    function_source = (
        source[backend_start:backend_end]
        + source[payload_start:payload_end]
        + source[result_start:result_end]
    )
    script = f"""
{function_source}
const historical = {{ recommendation: {{ candidate_id: "prior-candidate" }} }};
const report = {{
  state: {{ run_metadata: {{
    bo_agent: {{ recommendation: {{ candidate_id: "current-candidate" }} }},
    bo_agent_payload: {{ bo_result: historical }},
    bo_visualization: {{ schema: "bo_visualization.v1", step: 9 }},
  }} }},
  messages: [{{ bo_result: historical }}],
  events: [],
}};
const selected = latestReportBoResult(report);
console.log(JSON.stringify({{
  candidate: selected.recommendation.candidate_id,
  visualizationStep: selected.visualization.step,
}}));
"""
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    assert json.loads(result.stdout) == {
        "candidate": "current-candidate",
        "visualizationStep": 9,
    }


def test_live_gui_bo_visualization_keeps_complete_curve_until_new_complete_step_arrives() -> None:
    node = shutil.which("node")
    assert node
    source = PLANNING_JS.read_text(encoding="utf-8")
    current_start = source.index("function currentRunBoVisualization")
    current_end = source.index("function clearLiveBoVisualization", current_start)
    function_source = source[current_start:current_end]
    script = f"""
const window = {{ BOVisualization: {{ isValid: (value) => Boolean(value && value.valid) }} }};
function liveCurrentRunId() {{ return "run-1"; }}
{function_source}
const full20 = {{ valid: true, run_id: "run-1", step: 20, posterior: {{ x: Array(96).fill(0) }}, objective_trace: {{ rows: Array(384).fill({{}}) }} }};
const compact21 = {{ valid: true, run_id: "run-1", step: 21, posterior: {{ x: Array(8).fill(0) }}, objective_trace: {{ rows: [] }} }};
const full21 = {{ valid: true, run_id: "run-1", step: 21, posterior: {{ x: Array(96).fill(0) }}, objective_trace: {{ rows: Array(384).fill({{}}) }} }};
const stale = preferredLiveBoVisualization(compact21, full20, "run-1");
const refreshed = preferredLiveBoVisualization(full21, stale, "run-1");
console.log(JSON.stringify({{ staleStep: stale.step, stalePoints: boVisualizationPointCount(stale), refreshedStep: refreshed.step, refreshedPoints: boVisualizationPointCount(refreshed) }}));
"""
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    assert json.loads(result.stdout) == {
        "staleStep": 20,
        "stalePoints": 480,
        "refreshedStep": 21,
        "refreshedPoints": 480,
    }
