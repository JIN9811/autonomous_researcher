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
      const equationBody = hasVisualization
        ? renderer.renderEquationCard(visualization)
        : '<div class="bo-viz-empty">Waiting for a completed BO step.</div>';
      const posteriorBody = hasVisualization
        ? renderer.renderPlot(visualization, {mode: "parameter_slice", parameter: visualization.view?.selected_parameter || ""})
        : '<div class="bo-viz-empty">Waiting for a completed BO step.</div>';
      const visualizationCards = `
        ${renderDashboardCard("BO Objective Equation", `<div data-live-bo-equation>${equationBody}</div>`, {span: 4, tone: "bo", eyebrow: "active objective", className: "bo-objective-summary-card"})}
        ${renderDashboardCard("Live Posterior", `<div data-live-bo-posterior>${posteriorBody}</div>`, {span: 8, tone: "bo", eyebrow: "uncertainty + acquisition"})}
        ${renderDashboardCard("Initial Design / LHS", renderBoInitialDesignBoard(report), {span: 12, tone: "bo", eyebrow: "declared experimental design space", className: "ar-bo-lhs-card"})}
      `;
      const recommendation = boResult.recommendation || boResult.selected || {};
      const reasoning = boResult.reasoning || {};
      const priorSummary = boResult.prior_summary || {};
      const ranking = Array.isArray(boResult.candidate_ranking)
        ? boResult.candidate_ranking
        : Array.isArray(boResult.candidate_pool) ? boResult.candidate_pool.slice(0, 8) : [];
      const rankingItems = ranking.map((item, index) => `${index + 1}. ${item.candidate_id || item.id || "candidate"} / acq=${renderRuntimeValue(item.acquisition_score || item.acquisition || "-")} / score=${renderRuntimeValue(item.combined_score || item.objective_score || item.score || "-")}`);
      if (!ranking.length && !Object.keys(boResult).length) {
        const analysis = latestAnalysisPayload(report) || {};
        const quality = analysis.quality_gate || analysis.data_quality_gate || {};
        const knowledgeReport = latestKnowledgeReport(report) || {};
        const evolution = latestKnowledgeEvolutionProposal(report) || {};
        const packs = Array.isArray(evolution.evidence_packs) ? evolution.evidence_packs : [];
        return `
          ${visualizationCards}
          ${renderDashboardCard("BO Gate Status", renderBoGateState(report), {span: 8, tone: "bo", eyebrow: "route state"})}
          ${renderDashboardCard("Optimization Input", renderDashboardRows([
            ["objective_score", analysis.objective_score ?? "-"],
            ["uncertainty", analysis.uncertainty ?? "-"],
            ["ok_for_bo", quality.ok_for_bo === undefined ? "-" : quality.ok_for_bo],
            ["quality_warnings", quality.warnings || []],
            ["knowledge_packs", packs.length],
          ]), {span: 4, tone: quality.ok_for_bo === false ? "warning" : "bo", eyebrow: "ready check"})}
          ${renderDashboardCard("Expected BO Payload", renderDashboardRows([
            ["candidate_ranking", "waiting"], ["recommendation", "waiting"], ["next_design_request", "waiting"],
            ["memory_failures", Array.isArray(knowledgeReport.failure_patterns) ? knowledgeReport.failure_patterns.length : 0],
          ]), {span: 4, tone: "bo", eyebrow: "contract"})}
        `;
      }
      return `
        ${visualizationCards}
        ${boResult.decision?.schema === "bo_decision.v1" && renderer?.renderDecision ? renderDashboardCard("BO Decision / Tool Audit", renderer.renderDecision(boResult.decision), {span: 12, tone: boResult.decision.status === "accepted" ? "bo" : "warning", eyebrow: "strategy + result review"}) : ""}
        ${renderDashboardCard("Candidate Ranking", renderBoRankingBoard(boResult), {span: 8, tone: "bo", eyebrow: "numeric audit"})}
        ${renderDashboardCard("Recommendation", renderDashboardRows([
          ["candidate_id", recommendation.candidate_id || recommendation.id || "-"],
          ["combined_score", recommendation.combined_score || "-"],
          ["objective_score", recommendation.objective_score || recommendation.score || "-"],
          ["uncertainty", recommendation.uncertainty || "-"],
          ["source", recommendation.source_strategy || "-"],
        ]), {span: 4, tone: "bo", eyebrow: "selected"})}
        ${renderDashboardCard("Selected Parameters", renderBoParameterChips(recommendation), {span: 4, tone: "bo", eyebrow: "design vector"})}
        ${renderDashboardCard("Acquisition Strategy", renderDashboardRows([
          ["strategy", boResult.strategy || "-"], ["benchmark_strategy", boResult.benchmark_strategy || "-"],
          ["acquisition", boResult.acquisition || latestReportPayload(report, ["acquisition", "acquisition_function"]) || "-"],
          ["budget", boResult.budget || "-"], ["constraints", boResult.constraints || "-"],
        ]), {span: 4, tone: "bo", eyebrow: "optimizer"})}
        ${renderDashboardCard("Prior Memory", renderDashboardRows([
          ["measured_count", priorSummary.measured_count ?? "-"], ["failed_count", priorSummary.failed_count ?? "-"],
          ["constraint_count", priorSummary.constraint_count ?? "-"], ["reasoning_source", reasoning.source || "-"],
          ["failure_penalty", boResult.failure_penalty || "-"],
        ]), {span: 4, tone: "bo", eyebrow: "knowledge input"})}
        ${renderDashboardCard("Ranking Audit", `${renderDashboardRows([
          ["ranked_candidates", ranking.length], ["top_candidate", ranking[0] ? ranking[0].candidate_id || ranking[0].id || "-" : "-"],
          ["selection_rule", boResult.selection_rule || "-"], ["llm_decision", boResult.decision?.status || reasoning.summary || "-"],
        ])}${dashboardList(rankingItems, "No BO candidate ranking recorded.", 5)}`, {span: 4, tone: "bo", eyebrow: "audit"})}
        ${renderDashboardCard("Next Design Request", renderDashboardRows([
          ["schema", (boResult.next_design_request || {}).schema || "-"],
          ["target_agent", (boResult.next_design_request || {}).consumer_agent || (boResult.next_design_request || {}).target_agent || "Design"],
          ["candidate_id", (boResult.next_design_request || {}).candidate_id || recommendation.candidate_id || "-"],
          ["priority", (boResult.next_design_request || {}).priority || "-"],
          ["status", (boResult.next_design_request || {}).status || "-"],
        ]), {span: 4, tone: "bo", eyebrow: "handoff"})}
      `;
    }

    function dispose() {}
    return Object.freeze({renderReport, renderDashboard, dispose});
  }

  global.AX4LABBOUI = Object.freeze({createFrontend});
})(typeof window !== "undefined" ? window : globalThis);
