/* BO-owned report and dashboard composition; numerical rendering stays shared. */
(function installBOLiveReport(global) {
  "use strict";

  function createFrontend(host) {
    const {
      latestReportBoResult,
      latestAnalysisPayload,
      latestKnowledgeReport,
      latestKnowledgeEvolutionProposal,
      latestReportPayload,
      resolveLiveBoVisualization,
      boOptimizationPhase,
      boInitialDesignStatus,
      boVisualization,
      renderBoInitialDesignBoard,
      renderBoGateState,
      renderBoRankingBoard,
      renderBoParameterChips,
      compactBoParams,
      renderRuntimeValue,
      runtimeRows,
      renderReportList,
      renderDashboardRows,
      renderDashboardCard,
      dashboardList,
    } = host;

    function renderReport(report) {
      const boResult = latestReportBoResult(report) || {};
      if (!boResult || typeof boResult !== "object" || !Object.keys(boResult).length) return "";
      const reasoning = boResult.reasoning || {};
      const strategy = reasoning.strategy_recommendation || {};
      const recommendation = boResult.recommendation || {};
      const nextDesign = boResult.next_design_request || {};
      const prior = boResult.prior_summary || {};
      const hypotheses = Array.isArray(reasoning.hypotheses) ? reasoning.hypotheses.slice(0, 6) : [];
      const ranking = Array.isArray(boResult.candidate_ranking)
        ? boResult.candidate_ranking.slice(0, 8)
        : Array.isArray(boResult.candidate_pool) ? boResult.candidate_pool.slice(0, 8) : [];
      const artifacts = boResult.artifacts || {};
      const hypothesisItems = hypotheses.map((item) => `${item.id || "h"} · conf=${renderRuntimeValue(item.confidence)} · ${item.claim || ""}`);
      const rankingItems = ranking.map((item) => {
        const constraints = item.constraints || {};
        const llm = item.llm || {};
        return `${item.candidate_id || "candidate"} · combined=${renderRuntimeValue(item.combined_score)} · acq=${renderRuntimeValue((item.numeric || {}).acquisition_value)} · llm=${renderRuntimeValue(llm.preference_score)} · risk=${renderRuntimeValue(constraints.risk_score)} · valid=${renderRuntimeValue(constraints.valid)} · ${compactBoParams(item.parameters || {})}`;
      });
      const artifactRows = Object.entries(artifacts).map(([key, value]) => `${key} · ${renderRuntimeValue(value)}`);
      if (boOptimizationPhase(boResult) === "initial_design") {
        const initial = boInitialDesignStatus(boResult);
        return `
          <div class="live-agent-specific-report-detail live-agent-specific-bo-details">
            <h5>Initial Design / LHS</h5>
            ${runtimeRows([
              ["sampler", initial.sampler],
              ["progress", `${initial.completed}/${initial.target}`],
              ["next_point", `${initial.nextIndex}/${initial.target}`],
              ["backend", boResult.backend_active || "lhs"],
              ["selection_method", recommendation.selection_method || "latin_hypercube"],
              ["candidate_id", recommendation.candidate_id || "-"],
              ["parameters", recommendation.parameters || {}],
            ])}
            <h5>Phase Contract</h5>
            ${renderReportList([
              "Candidate ranking is disabled during the LHS initial design.",
              "LLM review does not alter the selected LHS point.",
              `GP posterior and the configured acquisition activate after ${initial.target} measured designs.`,
            ], "No initial-design contract recorded.", 6)}
            <h5>Artifacts</h5>
            ${renderReportList(artifactRows, "No BO artifact paths recorded.", 8)}
          </div>
        `;
      }
      return `
        <div class="live-agent-specific-report-detail live-agent-specific-bo-details">
          <h5>Evidence / Prior Intake</h5>
          ${runtimeRows([
            ["run_id", boResult.run_id || "-"],
            ["prior_count", prior.prior_count ?? "-"],
            ["measured_count", prior.measured_count ?? "-"],
            ["failed_count", prior.failed_count ?? "-"],
            ["best_score", prior.best_score ?? "-"],
            ["knowledge_context", boResult.knowledge_context || {}],
          ])}
          <h5>Initial Design / Numerical Strategy</h5>
          ${runtimeRows([
            ["phase", boResult.optimization_phase || "-"],
            ["sampler", (boResult.initial_design || {}).sampler || "latin_hypercube"],
            ["strategy", boResult.strategy || "-"],
            ["acquisition", boResult.acquisition || strategy.acquisition || "-"],
            ["backend", boResult.backend_active || boResult.bo_backend || "-"],
            ["budget", boResult.budget ?? "-"],
          ])}
          <h5>Reasoning / Decision Audit</h5>
          ${runtimeRows([
            ["decision_status", (boResult.decision || {}).status || "-"],
            ["reasoning_schema", reasoning.schema_version || "-"],
            ["source", reasoning.source || "-"],
            ["strategy_recommendation", `${strategy.strategy || "-"} / ${strategy.acquisition || "-"}`],
            ["explore_exploit", `${renderRuntimeValue(strategy.exploration_weight)} / ${renderRuntimeValue(strategy.exploitation_weight)}`],
            ["operator_summary", reasoning.operator_summary || "-"],
          ])}
          ${renderReportList(hypothesisItems, "No BO hypotheses recorded.", 12)}
          <h5>Candidate Ranking</h5>
          ${renderReportList(rankingItems, "No candidate ranking recorded.", 16)}
          <h5>Recommendation / Handoff</h5>
          ${runtimeRows([
            ["candidate_id", recommendation.candidate_id || "-"],
            ["combined_score", recommendation.combined_score ?? "-"],
            ["why_this_candidate", recommendation.why_this_candidate || recommendation.reason || "-"],
            ["why_not_best_exploitation_only", recommendation.why_not_best_exploitation_only || "-"],
            ["next_design_schema", nextDesign.schema || "-"],
            ["next_design_status", nextDesign.status || "-"],
            ["consumer_agent", nextDesign.consumer_agent || nextDesign.target_agent || "design_agent"],
            ["constraints", nextDesign.constraints || recommendation.parameters || {}],
          ])}
          <h5>Artifacts</h5>
          ${renderReportList(artifactRows, "No BO artifact paths recorded.", 8)}
        </div>
      `;
    }

    function renderDashboard(report, status, agentLabel, profile) {
      const boResult = latestReportBoResult(report) || {};
      const renderer = boVisualization;
      const visualization = resolveLiveBoVisualization(report, boResult);
      const hasVisualization = Boolean(renderer && renderer.isValid(visualization));
      const objective = report.sections?.objective_display;
      const hasObjectiveReport = Object.prototype.hasOwnProperty.call(report.sections || {}, "objective_display");
      const equationPayload = objective
        ? {schema: "bo_visualization.v1", objective, design_space: visualization?.design_space || {}}
        : (hasObjectiveReport ? null : visualization);
      const equationBody = equationPayload && renderer
        ? renderer.renderEquationCard(equationPayload)
        : '<div class="bo-viz-empty">Objective not configured for this run.</div>';
      const posteriorBody = hasVisualization
        ? renderer.renderPlot(visualization, {preferArtifact: true, mode: "parameter_slice", parameter: visualization.view?.selected_parameter || ""})
        : '<div class="bo-viz-empty">Waiting for a completed BO step.</div>';
      const visualizationCards = `
        ${renderDashboardCard("Objective Equation", `<div data-live-bo-equation>${equationBody}</div>`, {span: 12, tone: "bo", eyebrow: "optimization objective", className: "bo-objective-summary-card"})}
        ${renderDashboardCard("Live Posterior", `<div data-live-bo-posterior>${posteriorBody}</div>`, {span: 6, tone: "bo", eyebrow: "uncertainty + acquisition", className: "bo-posterior-card"})}
        ${renderDashboardCard("Initial Design / LHS", renderBoInitialDesignBoard(report), {span: 6, tone: "bo", eyebrow: "experimental design space", className: "ar-bo-lhs-card"})}
      `;
      const recommendation = boResult.recommendation || boResult.selected || {};
      const reasoning = boResult.reasoning || {};
      const prior = boResult.prior_summary || {};
      const next = boResult.next_design_request || {};
      const ranking = Array.isArray(boResult.candidate_ranking) ? boResult.candidate_ranking
        : Array.isArray(boResult.candidate_pool) ? boResult.candidate_pool : [];
      const analysis = latestAnalysisPayload(report) || {};
      const quality = analysis.quality_gate || analysis.data_quality_gate || {};
      const decision = boResult.decision || {};
      const trace = Array.isArray(decision.trace) ? decision.trace : [];
      const esc = (value) => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
      const details = (label, body) => `<details class="bo-equation-details"><summary>${label}</summary>${body}</details>`;
      const optimizerCalls = trace.filter(item => item.request?.tool === "run_optimizer");
      const validCall = item => item.status === "valid" || item.result?.status === "completed";
      const terminalReview = ["accepted", "returned", "failed"].includes(decision.status);
      const stages = [
        {label:"Input Check", status: quality.ok_for_bo === false ? "blocked" : (trace.length || prior.measured_count !== undefined ? "done" : "waiting"), rows:[["Measured observations", prior.measured_count ?? "—"], ["Quality gate", quality.ok_for_bo ?? "Not recorded"]]},
        {label:"Strategy Decision", status: optimizerCalls.length && decision.llm_used ? "done" : "waiting", rows:[["Strategy", boResult.strategy || "—"], ["LLM used", decision.llm_used ?? "Not recorded"], ["Source", decision.provenance || reasoning.source || "—"]]},
        {label:"LHS / BoTorch", status: optimizerCalls.some(validCall) || recommendation.candidate_id ? "done" : "waiting", rows:[["Phase", boResult.optimization_phase || "—"], ["Backend", boResult.backend_active || "—"], ["Candidate", recommendation.candidate_id || "—"]]},
        {label:"Result Review", status: decision.status === "accepted" ? "done" : (terminalReview ? "blocked" : "waiting"), rows:[["Decision", decision.status || "Not recorded"], ["Reason", decision.reason || decision.failure_code || "—"]]},
        {label:"Design Handoff", status: next.status === "ready" ? "done" : (next.status === "blocked" ? "blocked" : "waiting"), rows:[["Target", next.consumer_agent || next.target_agent || "—"], ["Candidate", next.candidate_id || "—"], ["Status", next.status || "Not recorded"]]},
      ];
      const progress = `<div class="ar-spm-progress-steps"><div class="ar-spm-progress-node-rail bo-stage-rail" aria-label="BO workflow stages">${stages.map((step, index) => `
        <details class="bo-stage-detail">
          <summary class="ar-spm-progress-node tone-${step.status === "done" ? "success" : step.status === "blocked" ? "warning" : "info"} tone-${step.status === "done" ? "done" : step.status === "blocked" ? "blocked" : "idle"}">
            <i>${String(index + 1).padStart(2, "0")}</i><span>${esc(step.label)}</span><b class="ar-spm-progress-action">${step.status === "done" ? "Complete" : step.status === "blocked" ? "Blocked" : "Waiting"}</b>
          </summary><div class="bo-stage-evidence">${renderDashboardRows(step.rows)}</div>
        </details>${index < stages.length - 1 ? `<span class="ar-spm-progress-edge tone-${step.status === "done" ? "done" : "idle"}" aria-hidden="true"></span>` : ""}`).join("")}</div></div>`;
      return `
        ${visualizationCards}
        ${renderDashboardCard("Next Experiment", `
          ${renderDashboardRows([
            ["Candidate", recommendation.candidate_id || recommendation.id || "Not selected"],
            ["Objective value", recommendation.objective_score ?? recommendation.score ?? "—"],
            ["Uncertainty", recommendation.uncertainty ?? "—"],
            ["Handoff", next.status || "Not recorded"],
            ["Target", next.consumer_agent || next.target_agent || "—"],
          ])}
          ${renderBoParameterChips(recommendation)}
          ${details("Handoff details", renderDashboardRows([
            ["Schema", next.schema || "—"], ["Candidate", next.candidate_id || "—"],
            ["Priority", next.priority || "—"], ["Source", recommendation.source_strategy || "—"],
          ]))}
        `, {span:4, tone:"bo", eyebrow:"selected design"})}
        ${renderDashboardCard("Optimization Status", renderDashboardRows([
          ["Phase", boResult.optimization_phase || "Waiting"],
          ["Strategy", boResult.strategy || "—"],
          ["Acquisition", boResult.acquisition || "—"],
          ["Measured", prior.measured_count ?? "—"],
          ["Failed", prior.failed_count ?? "—"],
          ["Ready for BO", quality.ok_for_bo ?? "—"],
        ]) + details("Input details", renderDashboardRows([
          ["Budget", boResult.budget ?? "—"], ["Benchmark", boResult.benchmark_strategy || "—"],
          ["Constraints", boResult.constraints || "—"], ["Quality warnings", quality.warnings || []],
          ["Failure penalty", boResult.failure_penalty ?? "—"],
        ])), {span:4,tone:"bo",eyebrow:"inputs + optimizer"})}
        ${renderDashboardCard("Selection Evidence", `
          ${renderDashboardRows([
            ["Decision", decision.status || "Not recorded"], ["Candidates", ranking.length],
            ["Source", reasoning.source || "—"], ["Selection rule", boResult.selection_rule || "—"],
          ])}
          ${renderBoRankingBoard(boResult)}
          ${details("Decision details", renderDashboardRows([
            ["Reason", decision.reason || reasoning.summary || "Not recorded"],
            ["Combined score", recommendation.combined_score ?? "—"],
            ["Constraint count", prior.constraint_count ?? "—"],
          ]))}
        `, {span:4,tone:"bo",eyebrow:"ranking + reasoning"})}
        ${renderDashboardCard("Agentic Progress", progress +
          (decision.schema === "bo_decision.v1" && renderer?.renderDecision
            ? details("Tool call details", renderer.renderDecision(decision)) : ""),
          {span:12,tone:"bo",eyebrow:"workflow stages · click for details",className:"bo-agentic-progress-card"})}
      `;
    }

    function dispose() {}
    return Object.freeze({renderReport, renderDashboard, dispose});
  }

  global.AX4LABBOUI = Object.freeze({createFrontend});
})(typeof window !== "undefined" ? window : globalThis);
