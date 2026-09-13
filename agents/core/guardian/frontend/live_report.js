/* Guardian-owned report/card composition. Status polling and approval events stay host-owned. */
(function installGuardianLiveReport(global) {
  "use strict";

  function createFrontend(services) {
    const {
      liveGuardianStatusPayload, latestReportPayload, renderRuntimeValue, runtimeRows,
      renderReportList, renderDashboardRows, dashboardList, renderDashboardCard,
      renderGuardianRiskMap, renderGuardianApprovalQueue, renderGuardianBlockedActions,
      renderGuardianIncidentLedger, renderGuardianSafetyBudget, renderGuardianLiveHeartbeat,
      renderGuardianSafeStopVerification, renderGuardianEvidenceCompleteness,
      renderGuardianSelfEvolutionGate, liveApprovalSnapshot, liveRunEvidenceCounts,
    } = services;

    function renderReport(report) {
      const status = liveGuardianStatusPayload(report);
      if (!status) return `<p class="hint">Guardian status report is not available yet. Refresh the active run state after a run starts.</p>`;
      const summary = status.summary || {};
      const deviceData = status.device_data_integrity || {};
      const handoff = status.handoff_packet || {};
      const decision = handoff.latest_guardian_decision || {};
      const contract = handoff.latest_guardian_contract || {};
      const policy = status.policy_version_panel || {};
      const corrective = Array.isArray(handoff.corrective_actions) ? handoff.corrective_actions : [];
      const correctiveItems = corrective.slice(-8).reverse().map((item) => `${item.action_id || item.action || "corrective_action"} · ${item.status || "open"} · ${item.description || item.message || item.owner || "-"}`);
      return `<div class="live-agent-specific-guardian-details">
        <h5>Graph-Wide Risk Map</h5>${renderGuardianRiskMap(status)}
        <h5>Guardian Status Summary</h5>${runtimeRows([
          ["schema", status.schema || "guardian_status_report.v1"], ["run_id", status.run_id || "-"],
          ["stage", status.stage || "-"], ["status", status.status || "-"], ["risk_score", summary.risk_score ?? "-"],
          ["dominant_risks", summary.dominant_risks || []], ["gate_count", summary.gate_count ?? "-"],
          ["incident_count", summary.incident_count ?? "-"], ["blocked_action_count", summary.blocked_action_count ?? "-"],
          ["pending_approval_count", summary.pending_approval_count ?? "-"], ["safety_budget_status", summary.safety_budget_status || "-"],
          ["safe_stop_status", summary.safe_stop_status || "-"], ["evidence_completeness_status", summary.evidence_completeness_status || "-"],
          ["self_evolution_gate_status", summary.self_evolution_gate_status || "-"], ["latest_decision", decision.decision || "-"],
          ["latest_reason", decision.reason_code || contract.failure_code || "-"],
          ["ok_for_next_stage", contract.ok_for_next_stage === undefined ? "-" : contract.ok_for_next_stage],
          ["ok_for_bo", contract.ok_for_bo === undefined ? "-" : contract.ok_for_bo],
        ])}
        <h5>Safety Budget</h5>${renderGuardianSafetyBudget(status)}
        <h5>Live Device Heartbeat</h5>${renderGuardianLiveHeartbeat(status)}
        <h5>Safe-Stop Verification</h5>${renderGuardianSafeStopVerification(status)}
        <h5>Evidence Completeness</h5>${renderGuardianEvidenceCompleteness(status)}
        <h5>Self-Evolution Gate</h5>${renderGuardianSelfEvolutionGate(status)}
        <h5>Gate Timeline</h5>${renderReportList((Array.isArray(status.gate_timeline) ? status.gate_timeline : []).slice(-14).reverse().map((item) => `${item.stage || "stage"}.${item.phase || "gate"}${item.tool ? `/${item.tool}` : ""} · ${item.decision || "allow"} · ${item.reason_code || "OK"} · risk=${renderRuntimeValue(item.risk_score)}`), "No Guardian gate timeline recorded.", 14)}
        <h5>Blocked Actions</h5>${renderGuardianBlockedActions(status)}
        <h5>Approval Queue</h5>${renderGuardianApprovalQueue(status)}
        <h5>Incident / Near-Miss Ledger</h5>${renderGuardianIncidentLedger(status)}
        <h5>Policy / Version Panel</h5>${runtimeRows([["guardian_gate_schema", policy.guardian_gate_schema || "-"], ["contract_schema", policy.contract_schema || "-"], ["decision_schema", policy.decision_schema || "-"], ["incident_schema", policy.incident_schema || "-"], ["tool_call_schema", policy.tool_call_schema || "-"], ["source_doc", policy.source_doc || "-"]])}
        <h5>Device / Data Integrity</h5>${runtimeRows([["device_health", deviceData.device_health || {}], ["live_device_heartbeat", deviceData.live_device_heartbeat || []], ["hardware_alert_count", deviceData.hardware_alert_count ?? "-"], ["tool_call_counts", deviceData.tool_call_counts || {}], ["data_related_incident_count", deviceData.data_related_incident_count ?? "-"]])}
        <h5>Corrective Actions</h5>${renderReportList(correctiveItems, "No corrective actions recorded.", 8)}
      </div>`;
    }

    function renderDashboard(report) {
      const status = liveGuardianStatusPayload(report);
      const summary = status && status.summary ? status.summary : {};
      const decisionRaw = latestReportPayload(report, ["latest_guardian_decision", "guardian_decision", "data.guardian_decision"]);
      const decision = decisionRaw && typeof decisionRaw === "object" ? decisionRaw : {};
      const incidents = Array.isArray(status && status.incidents) ? status.incidents : Array.isArray(summary.incidents) ? summary.incidents : [];
      const gates = Array.isArray(status && status.gates) ? status.gates : Array.isArray(summary.gates) ? summary.gates : [];
      const gateItems = gates.map((item) => `${item.name || item.gate || "gate"} / ${item.status || "unknown"} / ${item.reason || ""}`);
      const incidentItems = incidents.map((item) => `${item.severity || "incident"} / ${item.type || item.code || "event"} / ${item.summary || item.reason || ""}`);
      const approvals = liveApprovalSnapshot();
      const evidence = liveRunEvidenceCounts(report);
      return `
        ${renderDashboardCard("Safety Summary", renderDashboardRows([["guardian_status", status ? status.status || "-" : "not_loaded"], ["risk_score", summary.risk_score ?? "-"], ["dominant_risks", summary.dominant_risks || []], ["blocked_actions", summary.blocked_action_count ?? "-"], ["incidents", summary.incident_count ?? incidents.length]]), {span:4,tone:summary.risk_score > .6 ? "warning" : "guardian",eyebrow:"global risk"})}
        ${renderDashboardCard("Gate Queue", `${renderDashboardRows([["gate_count", summary.gate_count ?? gates.length ?? "-"], ["pending_approvals", summary.pending_approval_count ?? approvals.pending.length], ["approval_api_pending", approvals.pending.length], ["resolved", approvals.resolved.length]])}${dashboardList(gateItems, "No guardian gate queue recorded.", 8)}`, {span:4,tone:"guardian",eyebrow:"approval interrupts"})}
        ${renderDashboardCard("Stop / Continue Decision", renderDashboardRows([["decision", decision.decision || latestReportPayload(report, ["guardian_decision", "decision", "next_stage"]) || report.nextAction], ["reason_code", decision.reason_code || "-"], ["latest_warning", report.warnings[report.warnings.length - 1] || "-"], ["policy_schema", decision.policy_schema || "-"], ["next_action", decision.next_action || report.nextAction]]), {span:4,tone:"guardian",eyebrow:"authority"})}
        ${renderDashboardCard("Incidents", dashboardList(incidentItems, "No active incidents recorded.", 8), {span:6,tone:incidents.length ? "danger" : "success",eyebrow:"runtime safety"})}
        ${renderDashboardCard("Device / Data Integrity", renderDashboardRows([["artifact_refs", evidence.artifacts], ["validation_items", evidence.validationItems], ["warnings", evidence.warnings], ["run_events", evidence.events], ["integrity_status", summary.integrity_status || "-"]]), {span:6,tone:"guardian",eyebrow:"audit trail"})}`;
    }

    function dispose() {}
    return Object.freeze({renderReport, renderDashboard, dispose});
  }

  global.AX4LABGuardianUI = Object.freeze({createFrontend});
})(typeof window !== "undefined" ? window : globalThis);
