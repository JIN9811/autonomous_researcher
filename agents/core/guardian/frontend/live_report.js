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
      liveApprovalSnapshot, liveRunEvidenceCounts, escapeHtml,
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
          ["latest_decision", decision.decision || "-"],
          ["latest_reason", decision.reason_code || contract.failure_code || "-"],
          ["ok_for_next_stage", contract.ok_for_next_stage === undefined ? "-" : contract.ok_for_next_stage],
          ["ok_for_bo", contract.ok_for_bo === undefined ? "-" : contract.ok_for_bo],
        ])}
        <h5>Safety Budget</h5>${renderGuardianSafetyBudget(status)}
        <h5>Live Device Heartbeat</h5>${renderGuardianLiveHeartbeat(status)}
        <h5>Safe-Stop Verification</h5>${renderGuardianSafeStopVerification(status)}
        <h5>Evidence Completeness</h5>${renderGuardianEvidenceCompleteness(status)}
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
      const status = liveGuardianStatusPayload(report) || {};
      const summary = status.summary || {};
      const decisionRaw = latestReportPayload(report, ["latest_guardian_decision", "guardian_decision", "data.guardian_decision"]);
      const handoff = status.handoff_packet || {};
      const decision = handoff.latest_guardian_decision || (decisionRaw && typeof decisionRaw === "object" ? decisionRaw : {});
      const contract = handoff.latest_guardian_contract || {};
      const array = value => Array.isArray(value) ? value : [];
      const gates = array(status.gate_timeline).length ? status.gate_timeline : array(status.gates);
      const incidents = array(status.incident_ledger?.records).length ? status.incident_ledger.records : array(status.incidents);
      const devices = array(status.device_data_integrity?.live_device_heartbeat);
      const approvalSnapshot = liveApprovalSnapshot() || {};
      const pending = Array.isArray(status.approval_queue?.pending) ? status.approval_queue.pending : array(approvalSnapshot.pending);
      const stop = status.safe_stop_verification || {};
      const evidence = status.evidence_completeness || {};
      const tone = value => /block|deny|stop|critical|fail|stale/.test(String(value).toLowerCase()) ? 'blocked'
        : /hold|review|pending|warn|approval/.test(String(value).toLowerCase()) ? 'review'
        : /^(allow|pass|verified|ok|healthy|connected|success)$/.test(String(value).toLowerCase()) ? 'clear' : 'unknown';
      const text = value => escapeHtml(value === undefined || value === null || value === '' ? '—' : value);
      const badge = value => `<span class="grd-status grd-${tone(value)}">${text(value)}</span>`;
      const metric = (label, value) => `<div><small>${text(label)}</small><strong>${text(value)}</strong></div>`;
      const table = (headers, rows, empty) => rows.length ? `<div class="grd-table-scroll"><table class="grd-table"><thead><tr>${headers.map(h=>`<th scope="col">${text(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : `<p class="grd-empty">${text(empty)}</p>`;
      const card = (title, body, span=6) => renderDashboardCard(title, body, {span,tone:'guardian',className:'grd-card',eyebrow:'Guardian'});
      const currentDecision = decision.decision || 'Not evaluated';
      const reason = decision.reason || decision.reason_code || contract.failure_code || 'No decision evidence recorded.';
      const nextAction = decision.next_action || decision.recommended_action || 'No Guardian action recorded.';
      const risk = summary.risk_score;
      const counters = metric('Gate checks', summary.gate_count ?? gates.length) + metric('Awaiting approval', pending.length)
        + metric('Blocked actions', summary.blocked_action_count) + metric('Incidents', summary.incident_count ?? incidents.length)
        + metric('Risk score', typeof risk === 'number' && Number.isFinite(risk) ? risk : undefined);
      const gateRows = [...gates].reverse().map(item=>[
        text(item.stage || item.name || item.gate), text(item.phase || item.tool), badge(item.decision || item.status || 'unknown'),
        text(item.reason || item.reason_code), text(item.timestamp || item.created_at || item.at),
      ]);
      const deviceRows = devices.map(item=>[text(item.device_id),badge(item.heartbeat_status || 'unknown'),text(item.bridge_state),text(item.last_command)]);
      const approvalRows = pending.map(item=>[text(item.title || item.stage || 'Approval required'),text(item.reason || item.reason_code),badge(item.status || 'pending')]);
      const incidentRows = [...incidents].reverse().map(item=>[badge(item.severity || 'unknown'),text(item.stage),text(item.message || item.summary || item.reason_code),text(item.corrective_action || item.recommended_action)]);
      return card('Current Decision', `<div class="grd-decision"><div><small>Recorded decision</small>${badge(currentDecision)}<p>Monitor status: ${text(status.status || 'unavailable')}</p></div><div><small>Reason</small><p>${text(reason)}</p></div><div><small>Next action</small><p>${text(nextAction)}</p></div></div><div class="grd-counters">${counters}</div>`,12)
        + card('Gate Checks',table(['Stage','Phase / Tool','Decision','Reason','Time'],gateRows,'No gate evaluations recorded.'))
        + card('Device & Stop Verification', `${table(['Device','Heartbeat','Bridge','Last command'],deviceRows,'No device heartbeat evidence recorded.')}<div class="grd-verification"><div><small>Safe stop</small>${badge(stop.status || 'not_requested')}</div>${metric('Requested',stop.requested === undefined ? undefined : stop.requested ? 'Yes' : 'No')}${metric('Verified',stop.verified === undefined ? undefined : stop.verified ? 'Yes' : 'No')}<div><small>Evidence</small>${badge(evidence.status || 'unavailable')}</div></div><p class="grd-note">Verification basis: ${text(stop.verification_basis)}</p>`)
        + card('Approval Queue',table(['Request','Reason','Status'],approvalRows,'No pending approvals.'))
        + card('Incident History',table(['Severity','Stage','Observation','Corrective action'],incidentRows,'No incidents recorded.'));
    }

    function dispose() {}
    return Object.freeze({renderReport, renderDashboard, dispose});
  }

  global.AX4LABGuardianUI = Object.freeze({createFrontend});
})(typeof window !== "undefined" ? window : globalThis);
