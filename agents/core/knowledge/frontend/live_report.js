/* Knowledge-owned report/card composition. Shared polling and delivery stay host-owned. */
(function installKnowledgeLiveReport(global) {
  "use strict";

  function createFrontend(services) {
    const {
      latestKnowledgePayload, latestKnowledgeReport, latestKnowledgeContext,
      latestKnowledgeEvolutionProposal, renderRuntimeValue, compactText, runtimeRows,
      renderReportList, renderDashboardRows, dashboardList, dashboardObjectList,
      renderDashboardCard, renderKnowledgeActivityCard, renderLiveKnowledgeSummary,
      renderKnowledgeMemoryBoard, renderKnowledgePatternBoard,
    } = services;

    function renderReport(report) {
      const payload = latestKnowledgePayload(report) || {};
      const knowledgeReport = latestKnowledgeReport(report) || {};
      const context = latestKnowledgeContext(report) || {};
      const evolution = latestKnowledgeEvolutionProposal(report) || {};
      const intake = knowledgeReport.memory_intake || {};
      const quality = knowledgeReport.evidence_quality || context.evidence_quality || {};
      const dataQuality = knowledgeReport.data_quality_map || {};
      const failures = Array.isArray(knowledgeReport.failure_patterns) ? knowledgeReport.failure_patterns : [];
      const successes = Array.isArray(knowledgeReport.success_patterns) ? knowledgeReport.success_patterns : [];
      const performance = Array.isArray(knowledgeReport.agent_performance_records) ? knowledgeReport.agent_performance_records : [];
      const packs = Array.isArray(evolution.evidence_packs) ? evolution.evidence_packs : [];
      const outcomes = Array.isArray(evolution.outcomes) ? evolution.outcomes : Array.isArray(knowledgeReport.evolution_outcomes) ? knowledgeReport.evolution_outcomes : [];
      const graphStatus = knowledgeReport.graph_backend_status || context.graph_backend_status || payload.graph_backend_status || {};
      const memoryRows = runtimeRows([
          ["experiment_record_id", intake.experiment_record_id || "-"],
          ["agent_performance_count", intake.agent_performance_count ?? performance.length ?? 0],
          ["failure_pattern_count", intake.failure_pattern_count ?? failures.length ?? 0],
          ["success_pattern_count", intake.success_pattern_count ?? successes.length ?? 0],
          ["evolution_pack_count", intake.evolution_pack_count ?? packs.length ?? 0],
          ["retrieval_coverage", payload.retrieval_coverage ?? context.retrieval?.coverage ?? "-"],
          ["artifact_link_coverage", quality.artifact_link_coverage ?? "-"],
          ["agent_report_coverage", quality.agent_report_coverage ?? "-"],
      ]);
      const failureItems = failures.map((item) => `${item.pattern_id || item.failure_type || "failure"} · recurrence=${renderRuntimeValue(item.recurrence_count, "1")} · ${compactText(item.root_cause_hypothesis || item.failure_type || "", 160)}`);
      const successItems = successes.map((item) => `${item.skill_id || item.scope || "success"} · agent=${item.agent_id || "-"} · ${compactText(item.procedure_summary || item.scope || "", 160)}`);
      const performanceItems = performance.map((item) => `${item.agent_id || item.stage || "agent"} · status=${item.status || "-"} · score=${renderRuntimeValue(item.score)} · missing=${renderRuntimeValue((item.signals || {}).missing_required_fields || [])}`);
      const packItems = packs.map((pack) => `${pack.pack_id || "pack"} · ${pack.target_type || "target"}:${pack.target_id || "-"} · priority=${renderRuntimeValue(pack.priority)} · ${compactText(pack.objective || (pack.why_this_target || []).join("; "), 180)}`);
      const outcomeItems = outcomes.map((item) => `${item.variant_id || item.outcome_id || "variant"} · ${item.target_type || "target"}:${item.target_id || "-"} · verdict=${item.verdict || "observe"} · rollback=${renderRuntimeValue(item.rollback_recommended)}`);
      const missingArtifacts = Array.isArray(dataQuality.missing_artifacts) ? dataQuality.missing_artifacts : [];
      return `
        <div class="live-agent-specific-report-detail live-agent-specific-knowledge-details">
          <h5>Memory Ledger</h5>
          ${memoryRows}
          <h5>Failure Pattern Memory</h5>
          ${renderReportList(failureItems, "No failure pattern recorded.", 12)}
          <h5>Success / Skill Library</h5>
          ${renderReportList(successItems, "No reusable success pattern recorded.", 12)}
          <h5>Agent Performance Ledger</h5>
          ${renderReportList(performanceItems, "No agent performance record available.", 16)}
          <h5>Improvement Evidence Packs</h5>
          ${renderReportList(packItems, "No evidence pack prepared.", 10)}
          <h5>Historical Variant Outcome Attribution</h5>
          ${renderReportList(outcomeItems, "No historical variant outcome attribution recorded.", 8)}
          <h5>Optional Graph Backend</h5>
          ${runtimeRows([
            ["enabled", graphStatus.enabled === undefined ? false : graphStatus.enabled],
            ["backend", graphStatus.backend || "disabled"],
            ["ok", graphStatus.ok === undefined ? "-" : graphStatus.ok],
            ["nodes_written", graphStatus.nodes_written ?? graphStatus.node_count ?? "-"],
            ["edges_written", graphStatus.edges_written ?? graphStatus.edge_count ?? "-"],
            ["error", graphStatus.error || ""],
          ])}
          <h5>Data Quality / Missing Evidence</h5>
          ${renderReportList(missingArtifacts.map((item) => renderRuntimeValue(item)), "No missing artifact recorded.", 12)}
        </div>
      `;
    }

    function renderDashboard(report) {
      const payload = latestKnowledgePayload(report) || {};
      const knowledgeReport = latestKnowledgeReport(report) || {};
      const context = latestKnowledgeContext(report) || {};
      const evolution = latestKnowledgeEvolutionProposal(report) || {};
      const intake = knowledgeReport.memory_intake || {};
      const evidenceQuality = knowledgeReport.evidence_quality || context.evidence_quality || {};
      const failures = Array.isArray(knowledgeReport.failure_patterns) ? knowledgeReport.failure_patterns : [];
      const successes = Array.isArray(knowledgeReport.success_patterns) ? knowledgeReport.success_patterns : [];
      const performance = Array.isArray(knowledgeReport.agent_performance_records) ? knowledgeReport.agent_performance_records : [];
      const packs = Array.isArray(evolution.evidence_packs) ? evolution.evidence_packs : [];
      const outcomes = Array.isArray(evolution.outcomes) ? evolution.outcomes : Array.isArray(knowledgeReport.evolution_outcomes) ? knowledgeReport.evolution_outcomes : [];
      const packItems = packs.map((item) => `${item.target_type || "target"}:${item.target_id || "unknown"} / ${item.status || "proposed"} / ${item.summary || ""}`);
      return `
        ${renderKnowledgeActivityCard()}
        ${renderDashboardCard("Reference Library", `<div data-live-knowledge-body="wiki">${renderLiveKnowledgeSummary("wiki")}</div>`, {span:4,tone:"knowledge",eyebrow:"accessible inventory"})}
        ${renderDashboardCard("Agent Knowledge Supply", `<div data-live-knowledge-body="delivery">${renderLiveKnowledgeSummary("delivery")}</div>`, {span:12,tone:"knowledge",eyebrow:"current run · retrieval is not use"})}
        ${renderDashboardCard("Recorded Knowledge Outcomes", renderDashboardRows([
          ["Archived experiment", intake.experiment_record_id || "No record"],
          ["Agent performance records", intake.agent_performance_count ?? (Array.isArray(knowledgeReport.agent_performance_records) ? performance.length : "No record")],
          ["Failure patterns", intake.failure_pattern_count ?? (Array.isArray(knowledgeReport.failure_patterns) ? failures.length : "No record")],
          ["Success patterns", intake.success_pattern_count ?? (Array.isArray(knowledgeReport.success_patterns) ? successes.length : "No record")],
          ["Evidence packs", intake.evolution_pack_count ?? (Array.isArray(evolution.evidence_packs) ? packs.length : "No record")],
          ["Evolution outcomes", Array.isArray(evolution.outcomes) || Array.isArray(knowledgeReport.evolution_outcomes) ? outcomes.length : "No record"],
          ["Artifact coverage", evidenceQuality.artifact_link_coverage ?? "No record"],
          ["Agent report coverage", evidenceQuality.agent_report_coverage ?? "No record"],
        ]), {span:4,tone:"knowledge",eyebrow:"recorded report"})}
        ${renderDashboardCard("Learned Patterns", window.AX4LABKnowledgePanels.patterns(knowledgeReport), {span:4,tone:"knowledge",eyebrow:"failure / success"})}
        ${renderDashboardCard("Improvement Evidence", window.AX4LABKnowledgePanels.findings(packs, outcomes), {span:4,tone:"knowledge",eyebrow:"proposals and outcomes"})}`;
    }

    function dispose() {}
    return Object.freeze({renderReport, renderDashboard, dispose});
  }

  global.AX4LABKnowledgeUI = Object.freeze({createFrontend});
})(typeof window !== "undefined" ? window : globalThis);
