/*
AX4-Lab Design live-report renderer.

This module owns Design-only report markup. The planning host supplies shared
formatting, chart serialization, and capture lookup helpers explicitly.
It performs no polling, subscriptions, DOM mutation, or hardware actions.
*/
(function installDesignLiveReport(global) {
  "use strict";

  function createLiveReportRenderer(dependencies) {
    const {
      escapeHtml,
      compactText,
      renderRuntimeValue,
      renderDashboardRows,
      dashboardList,
      orcChartPayloadAttr,
      designImageUrlFromSource,
      designCandidateDirectCaptureUrl,
    } = dependencies || {};

    const required = {
      escapeHtml,
      compactText,
      renderRuntimeValue,
      renderDashboardRows,
      dashboardList,
      orcChartPayloadAttr,
      designImageUrlFromSource,
      designCandidateDirectCaptureUrl,
    };
    Object.entries(required).forEach(([name, value]) => {
      if (typeof value !== "function") throw new TypeError(`AX4LABDesignUI requires ${name}`);
    });

    function finiteNumber(value) {
      if (value === null || value === undefined || value === "") return null;
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    }

    function scoreText(value, digits = 2) {
      const number = finiteNumber(value);
      return number === null ? "-" : String(Number(number.toFixed(digits)));
    }

    function firstPresent(...values) {
      return values.find((value) => value !== null && value !== undefined && value !== "");
    }

    function renderEmpty(message) {
      return `<div class="ar-design-empty">${escapeHtml(message || "Waiting for backend data.")}</div>`;
    }

    function scatterRows(points) {
      const clean = (points || []).map((point) => ({
        ...point,
        x: finiteNumber(point && point.x_mass_g),
        y: finiteNumber(point && point.y_predicted_objective),
        r: finiteNumber(point && point.radius_uncertainty),
      })).filter((point) => point.x !== null && point.y !== null).slice(0, 24);
      return clean.map((point) => ({
        candidate_id: point.candidate_id || "candidate",
        geometry_type: point.geometry_type || "",
        x: point.x,
        y: point.y,
        r: point.r || 0,
        score: finiteNumber(point.score),
        status: point.status || "",
      }));
    }

    function radarRows(source, fallbackMetrics = {}) {
      const explicit = Array.isArray(source) ? source.map((item) => ({
        label: item.axis || item.label || "metric",
        value: finiteNumber(item.value),
        max: finiteNumber(item.max) || 1,
      })).filter((item) => item.value !== null) : [];
      if (explicit.length) return explicit.slice(0, 6);
      return [
        ["objective", fallbackMetrics.selected_score],
        ["manufacturing", fallbackMetrics.manufacturability_score],
        ["info_gain", fallbackMetrics.information_gain_score],
        ["margin", fallbackMetrics.constraint_margin_score],
        ["risk_inv", (() => {
          const risk = finiteNumber(fallbackMetrics.risk_score);
          return risk === null ? null : Math.max(0, 1 - risk);
        })()],
      ].map(([label, value]) => ({ label, value: finiteNumber(value), max: 1 }))
        .filter((item) => item.value !== null);
    }

    function renderEvidence(evaluation, details = false) {
      const e = evaluation || {};
      const validity = e.validity || {};
      const performance = e.performance || {};
      const cost = e.cost || {};
      const quantity = (quantityValue) => quantityValue && quantityValue.value != null
        ? `${renderRuntimeValue(quantityValue.value)} ${quantityValue.unit || ""}` : "unavailable";
      const rows = [
        ["Validity", validity.status || "unknown"],
        ["Performance", performance.status === "unassessed" ? "unassessed" : quantity(performance)],
        ["Mass (estimated)", quantity(cost.mass)],
        ["Time (rough estimate)", quantity(cost.duration)],
      ];
      const margins = details && Array.isArray(e.constraint_margins) ? e.constraint_margins : [];
      const reasons = Array.isArray(validity.reasons) ? validity.reasons : [];
      return `<div class="ar-design-metric-strip">${rows.map(([label, value]) => `<span><b>${escapeHtml(label)}</b>${escapeHtml(value)}</span>`).join("")}</div>
    ${margins.length ? `<div class="ar-design-note-list">${margins.map((margin) => `<span>${escapeHtml(margin.constraint)}: ${escapeHtml(margin.margin)} ${escapeHtml(margin.unit)} margin · ${escapeHtml(margin.status)}</span>`).join("")}</div>` : ""}
    ${reasons.length ? `<div class="ar-design-note-list">${reasons.map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}</div>` : ""}`;
    }

    function renderExpectedPerformance(screenReport, designReport, selected = {}) {
      const evidence = (designReport && designReport.design_evaluation) || (screenReport && screenReport.design_evaluation) || selected.design_evaluation;
      if (evidence) return renderEvidence(evidence);
      const expected = screenReport && screenReport.expected_performance ? screenReport.expected_performance : {};
      const evaluation = designReport && designReport.candidate_evaluation ? designReport.candidate_evaluation : {};
      const rows = scatterRows(Array.isArray(expected.scatter_points) ? expected.scatter_points : []);
      const metricRows = [
        ["OBJ", evaluation.selected_score ?? selected.expected_objective_proxy_score ?? selected.predicted_objective ?? selected.score],
        ["PRINT", selected.manufacturability_score ?? selected.expected_manufacturability_score],
        ["INFO", selected.information_gain_score],
        ["RISK", evaluation.risk_score ?? selected.risk_score],
      ].map(([label, value]) => ({ label, value: scoreText(value, 2) }));
      return `
    <div class="ar-design-performance-map">
      ${rows.length
        ? `<div class="ar-design-echart ar-design-scatter-chart" data-orc-echart="dsn-scatter" data-orc-payload="${orcChartPayloadAttr({ rows })}" aria-label="Candidate mass versus predicted objective"></div>`
        : renderEmpty("Waiting for scatter.")}
      <div class="ar-design-metric-strip">
        ${metricRows.map((item) => `<span><b>${escapeHtml(item.label)}</b>${escapeHtml(item.value)}</span>`).join("")}
      </div>
    </div>
  `;
    }

    function renderArtifactLedger(items) {
      const rows = (Array.isArray(items) ? items : []).map((item) => {
        const status = item.status || "recorded";
        return `${item.artifact_type || "artifact"} / ${item.artifact_id || "-"} / ${status}`;
      });
      return dashboardList(rows, "No design artifact ledger recorded.", 8);
    }

    function renderBriefCard(brief, objective, hypothesis, spec, prior, material = {}, manufacturability = {}, selected = {}) {
      const constraints = Array.isArray(brief.success_criteria) ? brief.success_criteria.slice(0, 3) : [];
      const goal = brief.hypothesis || hypothesis.statement || objective.statement || spec.objective || "Objective pending.";
      return `
    <div class="ar-design-brief-layout">
      ${renderDashboardRows([
        ["Metric", brief.primary_metric || objective.primary_metric || spec.objective_type || "-"],
        ["Test", spec.specimen_type || spec.specimen_kind || "compression"],
        ["Standard", spec.standard || spec.test_standard || "-"],
        ["Material", material.material || brief.material || spec.material || spec.material_family || "-"],
        ["Printer", manufacturability.printer_model || spec.printer_model || "-"],
        ["Selected", selected.candidate_id || spec.candidate_id || "-"],
        ["Priors", prior.prior_count || 0],
      ])}
      ${constraints.length ? `<ul class="ar-design-check-list">${constraints.map((item) => `<li>${escapeHtml(compactText(item, 72))}</li>`).join("")}</ul>` : ""}
      <p>${escapeHtml(compactText(goal, 120))}</p>
    </div>
  `;
    }

    function renderManufacturabilityCard(screenReport, designReport, selected, spec, material = {}, candidateRows = []) {
      const evidence = (designReport && designReport.design_evaluation) || (screenReport && screenReport.design_evaluation) || spec.design_evaluation;
      if (evidence) return renderEvidence(evidence, true);
      const expected = screenReport && screenReport.expected_performance ? screenReport.expected_performance : {};
      const evaluation = designReport && designReport.candidate_evaluation ? designReport.candidate_evaluation : {};
      const manufacturability = (screenReport && screenReport.manufacturability) || (designReport && designReport.manufacturability) || {};
      const rows = radarRows(Array.isArray(expected.radar) ? expected.radar : [], {
        ...evaluation,
        manufacturability_score: firstPresent(manufacturability.manufacturability_score, selected.manufacturability_score, selected.expected_manufacturability_score),
      });
      const warnings = Array.isArray(manufacturability.warnings) ? manufacturability.warnings : [];
      const previewCount = candidateRows.filter((item) => designImageUrlFromSource(item) || designCandidateDirectCaptureUrl(item)).length;
      return `
    <div class="ar-design-manufacturing-layout">
      ${rows.length
        ? `<div class="ar-design-echart ar-design-radar-chart" data-orc-echart="dsn-radar" data-orc-payload="${orcChartPayloadAttr({ rows })}" aria-label="Manufacturability radar chart"></div>`
        : renderEmpty("Waiting for gate.")}
      <div class="ar-design-metric-strip">
        <span><b>Printer</b>${escapeHtml(compactText(manufacturability.printer_model || spec.printer_model || "-", 18))}</span>
        <span><b>Material</b>${escapeHtml(compactText(material.material || spec.material || "-", 18))}</span>
        <span><b>Mass</b>${escapeHtml(`${renderRuntimeValue(firstPresent(manufacturability.expected_mass_g, spec.expected_mass_g, "-"))} g`)}</span>
        <span><b>Time</b>${escapeHtml(`${renderRuntimeValue(firstPresent(manufacturability.expected_print_time_min, spec.expected_print_time_min, "-"))} min`)}</span>
        <span><b>Nozzle</b>${escapeHtml(renderRuntimeValue(firstPresent(material.nozzle_diameter_mm, spec.nozzle_diameter_mm, "-")))}</span>
        <span><b>Captures</b>${escapeHtml(`${previewCount || 0}/${candidateRows.length || 0}`)}</span>
      </div>
      ${warnings.length ? `<div class="ar-design-note-list">${warnings.slice(0, 2).map((item) => `<span>${escapeHtml(compactText(item, 72))}</span>`).join("")}</div>` : ""}
    </div>
  `;
    }

    function renderMaterialCard(material, spec) {
      const notes = Array.isArray(material.notes) ? material.notes.slice(0, 3) : [];
      return `
    <div class="ar-design-material-layout">
      <div class="ar-design-metric-strip">
        <span><b>Material</b>${escapeHtml(compactText(material.material || spec.material || "-", 22))}</span>
        <span><b>Layer</b>${escapeHtml(renderRuntimeValue(firstPresent(material.layer_height_mm, spec.layer_height_mm, "-")))}</span>
        <span><b>Nozzle</b>${escapeHtml(renderRuntimeValue(firstPresent(material.nozzle_diameter_mm, spec.nozzle_diameter_mm, "-")))}</span>
        <span><b>Bed</b>${escapeHtml(renderRuntimeValue(firstPresent(material.bed_temperature_c, spec.bed_temperature_c, "-")))}</span>
      </div>
      <div class="ar-design-note-list">
        ${(notes.length ? notes : ["Material notes pending."]).map((item) => `<span>${escapeHtml(compactText(item, 88))}</span>`).join("")}
      </div>
    </div>
  `;
    }

    function renderHandoffCard(handoff, selected, material, spec, artifactLedger = []) {
      const missing = Array.isArray(handoff.missing_required_fields) ? handoff.missing_required_fields : [];
      const ready = handoff.required_fields_present !== false && !missing.length;
      return `
    <div class="ar-design-handoff-layout">
      <div class="ar-design-handoff-main">
        <span class="tone-${ready ? "success" : "warning"}">${ready ? "Ready" : "Needs Input"}</span>
        <strong>${escapeHtml(compactText(handoff.authoritative_candidate_id || selected.candidate_id || spec.candidate_id || "-", 34))}</strong>
        <em>${escapeHtml(compactText(handoff.authoritative_specimen_id || selected.specimen_id || spec.specimen_id || "-", 44))}</em>
      </div>
      <div class="ar-design-metric-strip">
        <span><b>Next</b>SPC</span>
        <span><b>Status</b>${escapeHtml(handoff.packet_status || (ready ? "ready" : "blocked"))}</span>
        <span><b>Profile</b>${escapeHtml(compactText(material.printer_profile || spec.printer_profile || "-", 18))}</span>
        <span><b>Evidence</b>${escapeHtml(`${Array.isArray(artifactLedger) ? artifactLedger.length : 0} files`)}</span>
      </div>
      ${missing.length ? `<div class="ar-design-note-list">${missing.slice(0, 4).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
    </div>
  `;
    }

    function renderEvidenceCard(artifactLedger, rejected) {
      const artifacts = Array.isArray(artifactLedger) ? artifactLedger.slice(0, 5) : [];
      const repairs = Array.isArray(rejected) ? rejected.slice(0, 4) : [];
      return `
    <div class="ar-design-evidence-layout">
      <section>
        <h5>Artifacts</h5>
        ${renderArtifactLedger(artifacts)}
      </section>
      <section>
        <h5>Rejected / Repair</h5>
        ${dashboardList(repairs.map((item) => renderRuntimeValue(item)), "No rejected entries.", 4)}
      </section>
    </div>
  `;
    }

    return Object.freeze({
      scatterRows,
      radarRows,
      renderEvidence,
      renderExpectedPerformance,
      renderArtifactLedger,
      renderBriefCard,
      renderManufacturabilityCard,
      renderMaterialCard,
      renderHandoffCard,
      renderEvidenceCard,
    });
  }

  function createFrontend(hostServices) {
    const services = hostServices || {};
    const renderer = createLiveReportRenderer(services);
    const required = {
      latestDesignAgentReport: services.latestDesignAgentReport,
      latestDesignReport: services.latestDesignReport,
      designSelectedCandidate: services.designSelectedCandidate,
      designCandidateRows: services.designCandidateRows,
      designActualSpecimenRows: services.designActualSpecimenRows,
      renderDesignCandidateCards: services.renderDesignCandidateCards,
      renderDesignParameterSweep: services.renderDesignParameterSweep,
      renderDashboardCard: services.renderDashboardCard,
      runtimeRows: services.runtimeRows,
      renderReportList: services.renderReportList,
    };
    Object.entries(required).forEach(([name, value]) => {
      if (typeof value !== "function") throw new TypeError(`AX4LABDesignUI frontend requires ${name}`);
    });

    function renderDashboard(report, status, label, profile) {
      const spec = report && report.spec ? report.spec : {};
      const screenReport = services.latestDesignAgentReport(report) || {};
      const designReport = services.latestDesignReport(report) || {};
      const decision = designReport.design_decision;
      if (decision && ["returned", "failed"].includes(decision.status)) {
        return services.renderDashboardCard("Design Decision — Review Required", services.runtimeRows([
          ["status", decision.status], ["reason", decision.reason || decision.failure_code || "No accepted candidate"],
          ["handoff", "blocked — no specification emitted"],
        ]), { span: 12, tone: "warning", eyebrow: "dsn decision" });
      }
      const brief = screenReport.design_brief || {};
      const material = screenReport.material_notes || {};
      const artifactLedger = Array.isArray(screenReport.artifact_ledger) ? screenReport.artifact_ledger : [];
      const objective = designReport.objective || {};
      const hypothesis = designReport.hypothesis || {};
      const generation = designReport.candidate_generation || {};
      const evaluation = designReport.candidate_evaluation || {};
      const prior = designReport.prior_context || {};
      const manufacturability = screenReport.manufacturability || designReport.manufacturability || {};
      const handoff = screenReport.handoff_to_specimen || designReport.handoff_to_specimen || {};
      const rejected = Array.isArray(designReport.rejected_candidates) ? designReport.rejected_candidates
        : Array.isArray(generation.rejection_log) ? generation.rejection_log
          : Array.isArray(generation.rejected_candidates) ? generation.rejected_candidates
            : Array.isArray(evaluation.rejected_candidates) ? evaluation.rejected_candidates : [];
      const selected = services.designSelectedCandidate(screenReport, designReport, spec);
      const candidateRows = services.designCandidateRows(screenReport, designReport, report);
      const specimenRows = services.designActualSpecimenRows(screenReport, designReport, report);
      const generatedCount = specimenRows.length;
      const validCount = specimenRows.filter((item) => !/reject|fail|block|invalid/i.test(String(item.status || item.candidate_status || ""))).length;
      const previewCount = specimenRows.filter((item) => services.designImageUrlFromSource(item)).length;
      return `
    ${services.renderDashboardCard("Experiment Contract", renderer.renderBriefCard(brief, objective, hypothesis, spec, prior, material, manufacturability, selected), { span: 3, tone: "design", eyebrow: "mission input", className: "ar-design-reference-card ar-design-brief-card" })}
    ${services.renderDashboardCard("Generated Specimens", services.renderDesignCandidateCards(screenReport, designReport, report, { renderEvidence: renderer.renderEvidence }), { span: 9, tone: "design", eyebrow: "built specimen log", className: "ar-design-reference-card ar-design-candidates-card", meta: `${services.renderRuntimeValue(generatedCount)} built / ${services.renderRuntimeValue(validCount)} usable / ${services.renderRuntimeValue(previewCount)} previews` })}
    ${services.renderDashboardCard("DOE Map / Design Space", services.renderDesignParameterSweep(screenReport), { span: 4, tone: "metrics", eyebrow: "parameter sweep", className: "ar-design-reference-card ar-design-sweep-card" })}
    ${services.renderDashboardCard("Evaluation Matrix", renderer.renderExpectedPerformance(screenReport, designReport, selected), { span: 4, tone: "metrics", eyebrow: "objective vs mass", className: "ar-design-reference-card ar-design-performance-card" })}
    ${services.renderDashboardCard("Buildability Gate", renderer.renderManufacturabilityCard(screenReport, designReport, selected, spec, material, specimenRows.length ? specimenRows : candidateRows), { span: 4, tone: handoff.required_fields_present === false || (manufacturability.warnings || []).length ? "warning" : "success", eyebrow: "print path", className: "ar-design-reference-card ar-design-manufacturing-card" })}
    ${services.renderDashboardCard("Active Handoff", renderer.renderHandoffCard(handoff, selected, material, spec, artifactLedger), { span: 12, tone: handoff.required_fields_present === false || rejected.length ? "warning" : "success", eyebrow: "dsn -> spc", className: "ar-design-reference-card ar-design-handoff-card" })}
  `;
    }

    function renderReport(report) {
      const designReport = services.latestDesignReport(report);
      if (!designReport || typeof designReport !== "object") return "";
      const hypothesis = designReport.hypothesis || {};
      const objective = designReport.objective || {};
      const generation = designReport.candidate_generation || {};
      const evaluation = designReport.candidate_evaluation || {};
      const prior = designReport.prior_context || {};
      const handoff = designReport.handoff_to_specimen || {};
      const topCandidates = Array.isArray(generation.top_candidates) ? generation.top_candidates.slice(0, 5) : [];
      const rejected = Array.isArray(designReport.rejected_candidates) ? designReport.rejected_candidates.slice(0, 6) : [];
      const decisions = Array.isArray(designReport.decision_register) ? designReport.decision_register.slice(0, 6) : [];
      const evidenceBased = designReport.evaluation_semantics === "evidence_based_v1";
      const topList = topCandidates.map((item) => evidenceBased
        ? `${item.candidate_id || "candidate"} · ${item.geometry_type || "-"} · validity=${item.design_evaluation?.validity?.status || "unknown"} · performance=${item.design_evaluation?.performance?.status || "unassessed"}`
        : `${item.candidate_id || "candidate"} · ${item.geometry_type || "-"} · score=${services.renderRuntimeValue(item.expected_objective_proxy_score ?? item.predicted_objective)} · risk=${services.renderRuntimeValue(item.risk_score)}`);
      const rejectedList = rejected.map((item) => `${item.candidate_id || "candidate"} · ${item.reason || "rejected"}`);
      const decisionList = decisions.map((item) => `${item.decision_id || item.decision || "decision"} · ${item.status || "-"} · ${item.rationale || ""}`);
      return `
    <div class="live-agent-specific-design-details">
      ${services.runtimeRows([
        ["report_id", designReport.report_id || "-"],
        ["primary_metric", objective.primary_metric || "-"],
        ["direction", objective.direction || "-"],
        ["variables", hypothesis.variables_under_test || "-"],
        ["selected_candidate", evaluation.selected_candidate_id || "-"],
        evidenceBased ? ["validity", designReport.design_evaluation?.validity?.status || "unknown"] : ["manufacturability", evaluation.manufacturability_score ?? "-"],
        ["knowledge_prior", prior.knowledge_summary || "-"],
        ["bo_recommendation", prior.bo_recommendation || "-"],
        ["handoff_missing", handoff.missing_required_fields || []],
      ])}
      <h5>Candidate Board</h5>
      ${services.renderReportList(topList, "No candidate board recorded.")}
      <h5>Rejected / Repair Log</h5>
      ${services.renderReportList(rejectedList, "No rejected candidates recorded.")}
      <h5>Decision Register</h5>
      ${services.renderReportList(decisionList, "No design decisions recorded.")}
    </div>
  `;
    }

    function dispose() {}

    return Object.freeze({ renderDashboard, renderReport, dispose });
  }

  global.AX4LABDesignUI = Object.freeze({ createLiveReportRenderer, createFrontend });
})(window);
