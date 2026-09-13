/* Analysis-owned report and dashboard composition. FEM polling remains host-owned. */
(function installAnalysisLiveReport(global) {
  "use strict";

  function createFrontend(services) {
    const {
      latestAnalysisPayload,
      latestAnalysisBoHandoff,
      renderRuntimeValue,
      runtimeRows,
      renderReportList,
      renderDashboardRows,
      renderDashboardMetric,
      renderDashboardCard,
      renderAnalysisTrustScore,
      renderAnalysisCurveOverlay,
      renderAnalysisFieldLink,
      renderAnalysisMetricBars,
      renderAnalysisQualityDonut,
      renderAnalysisProvenance,
      renderAnalysisFemEvidence,
    } = services;

    function renderReport(report) {
      const analysis = latestAnalysisPayload(report) || {};
      if (!analysis || typeof analysis !== "object" || !Object.keys(analysis).length) return "";
      const source = analysis.source || {};
      const fingerprint = source.fingerprint || {};
      const columnMapping = source.column_mapping || {};
      const metrics = analysis.utm_metrics || {};
      const quality = analysis.quality_gate || analysis.data_quality_gate || {};
      const comparison = analysis.comparison || {};
      const femComparison = analysis.fem_utm_comparison || {};
      const multifidelityComparison = analysis.multifidelity_comparison || {};
      const trustScore = analysis.trust_score || {};
      const fidelityRecords = analysis.fidelity_records || {};
      const femResult = analysis.fem_result || {};
      const femMetrics = analysis.fem_metrics || {};
      const femLoop = analysis.fem_agentic_loop || {};
      const caeResult = analysis.cae_result || {};
      const artifacts = analysis.analysis_artifacts || {};
      const boHandoff = latestAnalysisBoHandoff(report) || {};
      const failureTags = Array.isArray(analysis.failure_tags) ? analysis.failure_tags : [];
      const closedLoopSources = Array.isArray(analysis.closed_loop_sources) ? analysis.closed_loop_sources : [];
      const artifactRows = Object.entries(artifacts).map(([key, value]) => `${key} · ${renderRuntimeValue(value)}`);
      return `
        <div class="live-agent-specific-report-detail live-agent-specific-analysis-details">
          <h5>Analysis Admissibility / Gate</h5>
          ${renderAnalysisTrustScore(analysis)}
          <h5>Measurement / Simulation Comparison</h5>
          ${renderAnalysisCurveOverlay(analysis)}
          <h5>Solver Field Results</h5>
          ${renderAnalysisFieldLink(analysis)}
          ${renderAnalysisProvenance(analysis)}
          <h5>Raw Data Ledger</h5>
          ${runtimeRows([
            ["source", source.source || "-"],
            ["parser_id", source.parser_id || source.format || "-"],
            ["path", source.path || "-"],
            ["sha256", fingerprint.sha256 || "-"],
            ["size_bytes", fingerprint.size_bytes === undefined ? "-" : fingerprint.size_bytes],
            ["column_mapping_confidence", columnMapping.column_mapping_confidence === undefined ? "-" : columnMapping.column_mapping_confidence],
            ["unit_mapping_confidence", columnMapping.unit_mapping_confidence === undefined ? "-" : columnMapping.unit_mapping_confidence],
          ])}
          <h5>UTM Metrics / Quality Gate</h5>
          ${runtimeRows([
            ["peak_force_N", metrics.peak_force_N ?? "-"],
            ["initial_stiffness_N_per_mm", metrics.initial_stiffness_N_per_mm ?? "-"],
            ["compressive_strength_MPa", metrics.compressive_strength_MPa ?? "-"],
            ["apparent_modulus_MPa", metrics.apparent_modulus_MPa ?? "-"],
            ["energy_absorption_mJ", metrics.energy_absorption_mJ ?? "-"],
            ["specific_energy_absorption_J_per_g", metrics.specific_energy_absorption_J_per_g ?? "-"],
            ["ok_for_metrics", quality.ok_for_metrics === undefined ? "-" : quality.ok_for_metrics],
            ["ok_for_bo", quality.ok_for_bo === undefined ? "-" : quality.ok_for_bo],
            ["quality_score", quality.score === undefined ? "-" : quality.score],
            ["quality_warnings", quality.warnings || []],
          ])}
          <h5>FEM / CAE / CalculiX Evidence</h5>
          ${runtimeRows([
            ["closed_loop_sources", closedLoopSources],
            ["trust_score", trustScore.score === undefined ? "-" : trustScore.score],
            ["trust_gate", trustScore.gate || "-"],
            ["multifidelity_comparison", multifidelityComparison.schema || "-"],
            ["fidelity_records", Object.keys(fidelityRecords)],
            ["cae_loop_status", femResult.status || "-"],
            ["cae_backend", femResult.solver || femResult.solver_backend || "-"],
            ["fem_cache", femResult.cache_status || "-"],
            ["predicted_peak_force_N", femMetrics.predicted_peak_force_N ?? "-"],
            ["predicted_stiffness_N_per_mm", femMetrics.predicted_initial_stiffness_N_per_mm ?? "-"],
            ["cae_status", caeResult.status || "-"],
            ["fem_utm_agreement", femComparison.agreement_score === undefined ? "-" : femComparison.agreement_score],
            ["fem_utm_tags", femComparison.discrepancy_tags || []],
          ])}
          <h5>LLM Agentic FEM Loop</h5>
          ${runtimeRows([
            ["loop_status", femLoop.status || "-"],
            ["llm_plan_source", femLoop.llm_plan && femLoop.llm_plan.source ? femLoop.llm_plan.source : "-"],
            ["selected_iteration", femLoop.selected_iteration === undefined ? "-" : femLoop.selected_iteration],
            ["acceptance_threshold", femLoop.acceptance_threshold === undefined ? "-" : femLoop.acceptance_threshold],
            ["tool_sequence", femLoop.tool_sequence || []],
            ["safety_rule", femLoop.safety_rule || "-"],
          ])}
          ${renderReportList((femLoop.iterations || []).map((item) => `iter=${item.iteration} · mesh=${item.mesh_size_mm} mm · agreement=${renderRuntimeValue(item.agreement_score)} · accepted=${renderRuntimeValue(item.accepted)} · cache=${item.cache_status || "-"}`), "No FEM agentic iterations recorded.", 12)}
          <h5>BO Handoff / Loop Comparison</h5>
          ${runtimeRows([
            ["bo_schema", boHandoff.schema_version || "analysis_bo_handoff_v2"],
            ["ok_for_bo", boHandoff.ok_for_bo === undefined ? "-" : boHandoff.ok_for_bo],
            ["trust_gate", boHandoff.trust_gate || (boHandoff.trust_score || {}).gate || "-"],
            ["objective", boHandoff.objective || {}],
            ["comparison_mode", comparison.mode || "-"],
            ["comparison_summary", comparison.summary || "-"],
            ["failure_tags", failureTags],
          ])}
          <h5>Analysis Artifact Ledger</h5>
          ${renderReportList(artifactRows, "No Analysis artifact paths recorded.", 28)}
        </div>
      `;
    }

    function renderDashboard(report, status, agentLabel, profile) {
      const analysis = latestAnalysisPayload(report) || {};
      const metrics = analysis.utm_metrics || {};
      const quality = analysis.quality_gate || analysis.data_quality_gate || {};
      const artifacts = analysis.analysis_artifacts || {};
      const boHandoff = latestAnalysisBoHandoff(report) || {};
      return `
        ${renderAnalysisFemEvidence(analysis)}
        ${renderDashboardCard("Result Summary", `<div class="ar-report-metrics">
          ${renderDashboardMetric("Peak", metrics.peak_force_N ?? "-", "N", "info")}
          ${renderDashboardMetric("Strength", metrics.compressive_strength_MPa ?? "-", "MPa", "success")}
          ${renderDashboardMetric("Score", analysis.objective_score ?? "-", "objective", "running")}
          ${renderDashboardMetric("Unc.", analysis.uncertainty ?? "-", "model", "warning")}
        </div>`, {span: 4, tone: "analysis", eyebrow: "result"})}
        ${renderDashboardCard("Analysis Admissibility / Gate", renderAnalysisTrustScore(analysis), {span: 4, tone: (analysis.trust_score || {}).gate === "block" ? "danger" : "analysis", eyebrow: "evidence"})}
        ${renderDashboardCard("Metric Bars", renderAnalysisMetricBars(analysis), {span: 4, tone: "metrics", eyebrow: "features"})}
        ${renderDashboardCard("Data Quality", renderAnalysisQualityDonut(quality), {span: 4, tone: quality.ok_for_bo === false ? "warning" : "analysis", eyebrow: "qa"})}
        ${renderDashboardCard("Provenance", renderAnalysisProvenance(analysis), {span: 4, tone: "analysis", eyebrow: "artifacts"})}
        ${renderDashboardCard("Raw Data Ledger", renderDashboardRows([
          ["raw_file", analysis.raw_file || analysis.source_file || "-"],
          ["fingerprint", analysis.file_fingerprint || analysis.checksum || "-"],
          ["row_count", analysis.row_count || metrics.row_count || "-"],
          ["unit_confidence", analysis.unit_confidence || "-"],
          ["canonical_curve", artifacts.canonical_curve || "-"],
        ]), {span: 4, tone: "analysis", eyebrow: "utm ingest"})}
        ${renderDashboardCard("BO Handoff", renderDashboardRows([
          ["schema", boHandoff.schema_version || "analysis_bo_handoff_v2"],
          ["ok_for_bo", boHandoff.ok_for_bo === undefined ? "-" : boHandoff.ok_for_bo],
          ["trust_gate", boHandoff.trust_gate || (boHandoff.trust_score || {}).gate || "-"],
          ["objective_score", boHandoff.objective_score ?? analysis.objective_score ?? "-"],
          ["uncertainty", boHandoff.uncertainty ?? analysis.uncertainty ?? "-"],
          ["experiment_evaluation", artifacts.experiment_evaluation || "-"],
          ["next_agent", boHandoff.next_agent || "BO"],
        ]), {span: 4, tone: "analysis", eyebrow: "optimization"})}
      `;
    }

    function dispose() {}
    return Object.freeze({renderReport, renderDashboard, dispose});
  }

  global.AX4LABAnalysisUI = Object.freeze({createFrontend});
})(typeof window !== "undefined" ? window : globalThis);
