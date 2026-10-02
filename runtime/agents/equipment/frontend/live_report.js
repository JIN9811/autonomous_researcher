/* Equipment-owned composition; polling, runtime synchronization and actions remain in the shared host. */
(function installEquipmentLiveReport(global) {
  "use strict";

  function createFrontend(host) {
    const {
      latestEquipmentReport,
      latestEquipmentResult,
      latestEquipmentSkillExecution,
      latestEquipmentSkillException,
      latestUtmDataReadyPacket,
      latestEquipmentHandoffPacket,
      runtimeRows,
      renderReportList,
      renderRuntimeValue,
      renderDashboardRows,
      renderDashboardMetric,
      renderDashboardCard,
      renderVisionCardDetails,
      renderGateStatusBars,
      renderVizEmpty,
      escapeHtml,
      compactText,
      formatTime,
      numberText,
      dashboardPercent,
      visionProgressTone,
      equipmentAgenticTaskModel,
      equipmentRuntimeState,
      equipmentCycleContext,
    } = host;

    function renderReport(report) {
      const equipmentReport = latestEquipmentReport(report);
      if (!equipmentReport || typeof equipmentReport !== "object") return "";
      const equipmentResult = latestEquipmentResult(report) || {};
      const packet = latestUtmDataReadyPacket(report) || {};
      const handoff = latestEquipmentHandoffPacket(report) || {};
      const bridge = equipmentReport.bridge || {};
      const preconditions = equipmentReport.preconditions || {};
      const control = equipmentReport.control_plan || {};
      const profile = control.profile || {};
      const vision = equipmentReport.vision_cross_checks || {};
      const physical = equipmentReport.physical_checks || {};
      const data = equipmentReport.data_acquisition || {};
      const cross = equipmentReport.cross_checks || {};
      const decision = equipmentReport.decision || {};
      const screenChecks = Array.isArray(equipmentReport.screen_checks) ? equipmentReport.screen_checks : [];
      const artifactRecords = Array.isArray(equipmentReport.artifact_records) ? equipmentReport.artifact_records : [];
      const screenEvidenceRefs = Array.isArray(equipmentReport.screen_evidence_refs) ? equipmentReport.screen_evidence_refs : [];
      const dataEvidenceRefs = Array.isArray(equipmentReport.data_evidence_refs) ? equipmentReport.data_evidence_refs : [];
      const artifactRefs = Array.isArray(equipmentReport.artifact_refs) ? equipmentReport.artifact_refs : [];
      const failureRetryTable = Array.isArray(equipmentReport.failure_retry_table) ? equipmentReport.failure_retry_table : [];
      const recovery = equipmentReport.recovery && typeof equipmentReport.recovery === "object" ? equipmentReport.recovery : {};
      const liveAudit = equipmentReport.live_evidence_audit && typeof equipmentReport.live_evidence_audit === "object" ? equipmentReport.live_evidence_audit : {};
      const liveScreenAudit = liveAudit.screen_evidence && typeof liveAudit.screen_evidence === "object" ? liveAudit.screen_evidence : {};
      const livePullAudit = liveAudit.linux_artifact_pull && typeof liveAudit.linux_artifact_pull === "object" ? liveAudit.linux_artifact_pull : {};
      const liveVisionAudit = liveAudit.vision_evidence && typeof liveAudit.vision_evidence === "object" ? liveAudit.vision_evidence : {};
      const liveSaveAudit = liveAudit.save_export && typeof liveAudit.save_export === "object" ? liveAudit.save_export : {};
      const liveRequestAudit = liveAudit.request_audit_log && typeof liveAudit.request_audit_log === "object" ? liveAudit.request_audit_log : {};
      const hardwareAlert = equipmentReport.hardware_alert && typeof equipmentReport.hardware_alert === "object" ? equipmentReport.hardware_alert : packet.hardware_alert && typeof packet.hardware_alert === "object" ? packet.hardware_alert : equipmentResult.hardware_alert && typeof equipmentResult.hardware_alert === "object" ? equipmentResult.hardware_alert : {};
      const guardianDecision = hardwareAlert.guardian_decision && typeof hardwareAlert.guardian_decision === "object" ? hardwareAlert.guardian_decision : {};
      const guardianContract = hardwareAlert.guardian_contract && typeof hardwareAlert.guardian_contract === "object" ? hardwareAlert.guardian_contract : {};
      const incidentRecords = Array.isArray(equipmentReport.incident_records) ? equipmentReport.incident_records : hardwareAlert.incident_record ? [hardwareAlert.incident_record] : [];
      const screenItems = screenChecks.map((item) => `${item.checkpoint || "screen"} · ok=${renderRuntimeValue(item.ok)} · state=${item.state || "-"} · artifact=${item.screenshot_artifact || "-"}`);
      const artifactItems = artifactRecords.map((item) => {
        const kind = item.kind || "artifact";
        const artifactId = item.artifact_id || "-";
        const ref = item.local_path || item.linux_path || item.path || item.windows_path || "-";
        const rows = item.row_count_probe === undefined ? "" : ` · rows=${renderRuntimeValue(item.row_count_probe)}`;
        return `${kind} · id=${artifactId} · ref=${ref}${rows}`;
      });
      const retryItems = failureRetryTable.map((item) => {
        const fallback = item.fallback_macro ? ` · fallback=${item.fallback_macro}` : "";
        return `${item.step || "step"} · status=${item.status || "-"} · code=${item.failure_code || "-"}${fallback} · action=${item.recommended_action || "-"}`;
      });
      const visionChecks = vision.checks && typeof vision.checks === "object" ? Object.entries(vision.checks) : [];
      const visionItems = visionChecks.map(([checkId, item]) => {
        const check = item && typeof item === "object" ? item : {};
        return `${checkId} · ok=${renderRuntimeValue(check.ok)} · source=${check.source || "-"} · conf=${renderRuntimeValue(check.confidence)}`;
      });
      const blockingReasons = Array.isArray(decision.blocking_reasons) ? decision.blocking_reasons : Array.isArray(vision.blocking_reasons) ? vision.blocking_reasons : [];
      const riskFlags = Array.isArray(guardianContract.risk_flags) ? guardianContract.risk_flags : Array.isArray(hardwareAlert.risk_flags) ? hardwareAlert.risk_flags : [];
      const evidenceRefs = Array.isArray(packet.evidence_refs) ? packet.evidence_refs : [];
      return `
        <div class="live-agent-specific-equipment-details">
          <h5>Bridge / Protocol Profile</h5>
          ${runtimeRows([
            ["schema", equipmentReport.schema || "-"],
            ["report_version", equipmentReport.report_version || "-"],
            ["task_id", equipmentReport.task_id || "-"],
            ["provider", bridge.provider || "-"],
            ["connection_status", bridge.connection_status || "-"],
            ["bridge_host", bridge.bridge_url_host || bridge.host || "-"],
            ["remote_server_version", bridge.remote_server_version || "-"],
            ["remote_script_version", bridge.remote_script_version || "-"],
            ["client_latency_ms", bridge.client_latency_ms === undefined || bridge.client_latency_ms === "" ? "-" : bridge.client_latency_ms],
            ["pyautogui_available", bridge.pyautogui_available === undefined ? "-" : bridge.pyautogui_available],
            ["pyautogui_failsafe", bridge.pyautogui_failsafe === undefined || bridge.pyautogui_failsafe === "" ? "-" : bridge.pyautogui_failsafe],
            ["pyautogui_pause", bridge.pyautogui_pause === undefined || bridge.pyautogui_pause === "" ? "-" : bridge.pyautogui_pause],
            ["pyautogui_error", bridge.pyautogui_error || "-"],
            ["live_execute_enabled", bridge.live_execute_enabled === undefined ? "-" : bridge.live_execute_enabled],
            ["program_id", control.program_id || equipmentResult.program_id || handoff.program_id || "-"],
            ["macro_version", control.macro_version || "-"],
            ["locator_backend", control.locator_backend || "-"],
            ["profile_memory", profile.profile_memory_path || "-"],
            ["profile_applied", profile.profile_memory_applied === undefined ? "-" : profile.profile_memory_applied],
            ["locator_count", profile.locator_count === undefined ? "-" : profile.locator_count],
          ])}
          <h5>Preconditions</h5>
          ${runtimeRows(Object.entries(preconditions))}
          <h5>Screen-State Assertions</h5>
          ${renderReportList(screenItems, "No UTM screen checks recorded.", 24)}
          <h5>Vision Physical Cross-Checks</h5>
          ${runtimeRows([
            ["all_required_ok", vision.all_required_ok === undefined ? "-" : vision.all_required_ok],
            ["required", vision.required || []],
            ["vision_motion_confirmed", physical.vision_motion_confirmed === undefined ? "-" : physical.vision_motion_confirmed],
            ["specimen_alignment_ok", physical.specimen_alignment_ok === undefined ? "-" : physical.specimen_alignment_ok],
            ["fixture_safe_to_access", physical.fixture_safe_to_access === undefined ? "-" : physical.fixture_safe_to_access],
            ["evidence_frame_ids", physical.evidence_frame_ids || vision.evidence_frame_ids || []],
          ])}
          ${renderReportList(visionItems, "No Vision cross-check result recorded.", 24)}
          <h5>UTM Data Ledger</h5>
          ${runtimeRows([
            ["status", data.status || equipmentResult.status || "-"],
            ["save_method", data.save_method || "-"],
            ["save_attempted_by_agent", data.save_attempted_by_agent === undefined ? "-" : data.save_attempted_by_agent],
            ["save_confirmation_screen_ok", data.save_confirmation_screen_ok === undefined ? "-" : data.save_confirmation_screen_ok],
            ["save_export_responsibility_ok", cross.save_export_responsibility_ok === undefined ? (liveSaveAudit.ok === undefined ? "-" : liveSaveAudit.ok) : cross.save_export_responsibility_ok],
            ["recognized_save_method", liveSaveAudit.recognized_save_method === undefined ? "-" : liveSaveAudit.recognized_save_method],
            ["windows_path", data.windows_path || liveSaveAudit.windows_path || "-"],
            ["linux_path", data.linux_path || liveSaveAudit.linux_path || equipmentResult.result_file || equipmentResult.utm_csv_path || packet.result_file || handoff.result_file || "-"],
            ["sha256", data.sha256 || "-"],
            ["size_bytes", data.size_bytes === undefined ? "-" : data.size_bytes],
            ["row_count_probe", data.row_count_probe === undefined ? "-" : data.row_count_probe],
            ["columns_probe", data.columns_probe || []],
          ])}
          <h5>Save/Export Responsibility</h5>
          ${runtimeRows([
            ["responsibility_ok", cross.save_export_responsibility_ok === undefined ? (liveSaveAudit.ok === undefined ? "-" : liveSaveAudit.ok) : cross.save_export_responsibility_ok],
            ["save_method", data.save_method || liveSaveAudit.save_method || "-"],
            ["save_attempted_by_agent", data.save_attempted_by_agent === undefined ? (liveSaveAudit.save_attempted_by_agent === undefined ? "-" : liveSaveAudit.save_attempted_by_agent) : data.save_attempted_by_agent],
            ["save_confirmation_screen_ok", data.save_confirmation_screen_ok === undefined ? (liveSaveAudit.save_confirmation_screen_ok === undefined ? "-" : liveSaveAudit.save_confirmation_screen_ok) : data.save_confirmation_screen_ok],
            ["recognized_save_method", liveSaveAudit.recognized_save_method === undefined ? "-" : liveSaveAudit.recognized_save_method],
            ["windows_path", data.windows_path || liveSaveAudit.windows_path || "-"],
            ["linux_path", data.linux_path || liveSaveAudit.linux_path || equipmentResult.result_file || equipmentResult.utm_csv_path || packet.result_file || handoff.result_file || "-"],
          ])}
          <h5>Handoff Gate / Blocking Reasons</h5>
          ${runtimeRows([
            ["screen_started", cross.screen_started === undefined ? "-" : cross.screen_started],
            ["physical_motion_started", cross.physical_motion_started === undefined ? "-" : cross.physical_motion_started],
            ["save_completed", cross.save_completed === undefined ? "-" : cross.save_completed],
            ["data_file_created", cross.data_file_created === undefined ? "-" : cross.data_file_created],
            ["data_parse_probe_ok", cross.data_parse_probe_ok === undefined ? "-" : cross.data_parse_probe_ok],
            ["screen_evidence_complete", cross.screen_evidence_complete === undefined ? "-" : cross.screen_evidence_complete],
            ["linux_artifact_pulled", cross.linux_artifact_pulled === undefined ? "-" : cross.linux_artifact_pulled],
            ["save_export_responsibility_ok", cross.save_export_responsibility_ok === undefined ? (liveSaveAudit.ok === undefined ? "-" : liveSaveAudit.ok) : cross.save_export_responsibility_ok],
            ["vision_evidence_complete", cross.vision_evidence_complete === undefined ? "-" : cross.vision_evidence_complete],
            ["equipment_status", decision.equipment_status || equipmentResult.status || "-"],
            ["handoff_status", decision.handoff_status || handoff.status || packet.status || "-"],
            ["failure_code", decision.failure_code || equipmentResult.failure_code || handoff.failure_code || "-"],
            ["next_agent", decision.recommended_next_agent || packet.next_action || "-"],
          ])}
          ${renderReportList(blockingReasons, "No blocking reasons recorded.", 24)}
          <h5>Safety Gate / Guardian</h5>
          ${runtimeRows([
            ["guardian_status", packet.guardian_status || (hardwareAlert.failure_code ? "block" : "-")],
            ["blocks_workflow", hardwareAlert.blocks_workflow === undefined ? (guardianContract.ok_for_next_stage === false ? true : "-") : hardwareAlert.blocks_workflow],
            ["requires_human_approval", hardwareAlert.requires_ack === undefined ? (guardianDecision.requires_human_approval === undefined ? guardianContract.requires_human_approval ?? "-" : guardianDecision.requires_human_approval) : hardwareAlert.requires_ack],
            ["guardian_route_hint", hardwareAlert.guardian_route_hint || guardianDecision.recommended_action || "-"],
            ["guardian_decision", guardianDecision.decision || "-"],
            ["risk_score", hardwareAlert.risk_score === undefined ? guardianDecision.risk_score ?? "-" : hardwareAlert.risk_score],
            ["active_failure_code", hardwareAlert.failure_code || decision.failure_code || equipmentResult.failure_code || "-"],
            ["incident_count", incidentRecords.length],
          ])}
          ${renderReportList(riskFlags, "No Guardian risk flags recorded.", 16)}
          <h5>Live Evidence Audit</h5>
          ${runtimeRows([
            ["required_for_handoff", liveAudit.required_for_handoff === undefined ? "-" : liveAudit.required_for_handoff],
            ["screen_evidence_ok", liveScreenAudit.ok === undefined ? "-" : liveScreenAudit.ok],
            ["missing_screen_checkpoints", liveScreenAudit.missing_checkpoints || []],
            ["linux_artifact_pull_ok", livePullAudit.ok === undefined ? "-" : livePullAudit.ok],
            ["linux_pull_status", livePullAudit.status || "-"],
            ["linux_path", livePullAudit.linux_path || "-"],
            ["save_export_ok", liveSaveAudit.ok === undefined ? "-" : liveSaveAudit.ok],
            ["save_export_method", liveSaveAudit.save_method || "-"],
            ["save_export_windows_path", liveSaveAudit.windows_path || "-"],
            ["vision_evidence_ok", liveVisionAudit.ok === undefined ? "-" : liveVisionAudit.ok],
            ["vision_frame_ids", liveVisionAudit.evidence_frame_ids || []],
            ["request_log_ok", liveRequestAudit.ok === undefined ? "-" : liveRequestAudit.ok],
            ["request_log_path", liveRequestAudit.path || "-"],
            ["request_log_execute_seen", liveRequestAudit.execute_event_seen === undefined ? "-" : liveRequestAudit.execute_event_seen],
            ["request_log_execute_count", liveRequestAudit.execute_event_count === undefined ? "-" : liveRequestAudit.execute_event_count],
            ["request_log_last_execute_at", liveRequestAudit.last_execute_at || "-"],
          ])}
          <h5>Artifact / Evidence Ledger</h5>
          ${runtimeRows([
            ["artifact_refs", artifactRefs.length ? artifactRefs : evidenceRefs],
            ["screen_evidence_refs", screenEvidenceRefs],
            ["data_evidence_refs", dataEvidenceRefs],
          ])}
          ${renderReportList(artifactItems, "No bridge artifacts recorded.", 24)}
          <h5>Failure / Recovery</h5>
          ${runtimeRows([
            ["status", recovery.status || "-"],
            ["operator_intervention_required", recovery.operator_intervention_required === undefined ? "-" : recovery.operator_intervention_required],
            ["retry_count", recovery.retry_count === undefined ? "-" : recovery.retry_count],
            ["fallback_macros", recovery.fallback_macros || []],
            ["recommended_action", recovery.recommended_action || "-"],
          ])}
          ${renderReportList(retryItems, "No failure or retry table recorded.", 24)}
          <h5>Evidence Refs</h5>
          ${renderReportList(evidenceRefs, "No UTM data evidence refs recorded.", 12)}
        </div>
      `;
    }
    function reportBooleanTone(value) {
      const normalized = String(value ?? "").toLowerCase();
      if (value === true || ["ok", "ready", "pass", "passed", "success"].includes(normalized)) return "success";
      if (value === false || ["blocked", "block", "error", "failed", "fail"].includes(normalized)) return "danger";
      return "warning";
    }
    function reportBooleanLabel(value) {
      if (value === true) return "ok";
      if (value === false) return "block";
      return renderRuntimeValue(value, "-");
    }
    function renderEquipmentGauge(label, pct, status, meta = "") {
      const value = dashboardPercent(pct);
      const tone = reportBooleanTone(status);
      return `
        <article class="ar-eqp-gauge tone-${escapeHtml(tone)}" style="--score:${numberText(value, 2)}%;">
          <div class="ar-eqp-gauge-ring"><strong>${escapeHtml(numberText(value, 0))}%</strong><span>${escapeHtml(reportBooleanLabel(status))}</span></div>
          <div><b>${escapeHtml(label)}</b><small>${escapeHtml(compactText(meta || "-", 42))}</small></div>
        </article>
      `;
    }
    function renderEquipmentReadinessBoard(equipment, result, packet, handoff) {
      const bridge = equipment.bridge || {};
      const controlPlan = equipment.control_plan || {};
      const screenChecks = Array.isArray(equipment.screen_checks) ? equipment.screen_checks : [];
      const vision = equipment.vision_cross_checks || {};
      const physical = equipment.physical_checks || {};
      const data = equipment.data_acquisition || {};
      const cross = equipment.cross_checks || {};
      const screenTotal = Math.max(1, screenChecks.length);
      const screenPassed = screenChecks.filter((item) => item && item.ok).length;
      const physicalGates = [vision.all_required_ok, physical.vision_motion_confirmed, physical.alignment_confirmed, physical.specimen_loaded].filter((item) => item !== undefined);
      const physicalPassed = physicalGates.filter(Boolean).length;
      const dataGates = [cross.data_parse_probe_ok, cross.save_export_responsibility_ok, data.status === "ready" || result.status === "ok" || packet.status === "ready" || handoff.status === "ready_for_analysis"].filter((item) => item !== undefined);
      const dataPassed = dataGates.filter(Boolean).length;
      return `
        <div class="ar-eqp-readiness-board">
          ${renderEquipmentGauge("Bridge", bridge.connection_status === "connected" ? 96 : bridge.connection_status ? 64 : 22, bridge.connection_status === "connected", bridge.provider || controlPlan.locator_backend || "windows bridge")}
          ${renderEquipmentGauge("Screen", (screenPassed / screenTotal) * 100, screenPassed === screenChecks.length && screenChecks.length > 0, `${screenPassed}/${screenChecks.length || 0} checks`)}
          ${renderEquipmentGauge("Vision", physicalGates.length ? (physicalPassed / physicalGates.length) * 100 : 0, physicalGates.length ? physicalPassed === physicalGates.length : undefined, `${physicalPassed}/${physicalGates.length} gates`)}
          ${renderEquipmentGauge("Data", dataGates.length ? (dataPassed / dataGates.length) * 100 : 0, dataGates.length ? dataPassed === dataGates.length : undefined, data.linux_path || result.result_file || "csv ledger")}
        </div>
      `;
    }
    function renderEquipmentGatePanel(equipment) {
      const screenChecks = Array.isArray(equipment.screen_checks) ? equipment.screen_checks : [];
      const vision = equipment.vision_cross_checks || {};
      const physical = equipment.physical_checks || {};
      const cross = equipment.cross_checks || {};
      const gates = [
        ...screenChecks.map((item, index) => ({ label: item.name || item.assertion || `screen_${index + 1}`, status: item.ok })),
        { label: "vision_required", status: vision.all_required_ok },
        { label: "motion_confirmed", status: physical.vision_motion_confirmed },
        { label: "alignment", status: physical.alignment_confirmed || physical.specimen_alignment_ok },
        { label: "parse_ready", status: cross.data_parse_probe_ok },
        { label: "export_owner", status: cross.save_export_responsibility_ok },
      ].filter((item) => item.status !== undefined);
      return renderGateStatusBars(gates, { label: "equipment readiness gates", limit: 14, emptyText: "No equipment gates recorded." });
    }
    function renderEquipmentSensorTable(equipment) {
      const physical = equipment.physical_checks || {};
      const data = equipment.data_acquisition || {};
      const audit = equipment.live_evidence_audit || {};
      const rows = [
        ["specimen_loaded", physical.specimen_loaded],
        ["motion_confirmed", physical.vision_motion_confirmed],
        ["alignment_ok", physical.alignment_confirmed || physical.specimen_alignment_ok],
        ["fixture_safe", physical.fixture_safe_to_access],
        ["row_probe", data.row_count_probe],
        ["save_export", audit.save_export && typeof audit.save_export === "object" ? audit.save_export.ok : undefined],
        ["linux_pull", audit.linux_artifact_pull && typeof audit.linux_artifact_pull === "object" ? audit.linux_artifact_pull.ok : undefined],
      ].filter(([, value]) => value !== undefined && value !== null && value !== "");
      if (!rows.length) return renderVizEmpty("No sensor or evidence audit rows recorded.");
      return `
        <div class="ar-eqp-sensor-table" role="table" aria-label="equipment sensor and audit channels">
          ${rows.map(([label, value]) => `
            <div role="row" class="tone-${escapeHtml(reportBooleanTone(value))}">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(renderRuntimeValue(value))}</strong>
            </div>
          `).join("")}
        </div>
      `;
    }
    function renderEquipmentEventLog(report) {
      const events = (report.events || []).filter((event) => {
        const text = `${event.event_type || event.type || ""} ${event.node_id || ""} ${event.message || ""}`.toLowerCase();
        return /equipment|utm|windows|bridge|pyautogui|analysis/.test(text);
      }).slice(-7).reverse();
      if (!events.length) return renderVizEmpty("No equipment events recorded.");
      return `
        <div class="ar-eqp-event-log">
          ${events.slice(0, 4).map((event) => `
            <article>
              <span>${escapeHtml(formatTime(event.ts || event.timestamp))}</span>
              <strong>${escapeHtml(compactText(event.event_type || event.type || "event", 34))}</strong>
              <small>${escapeHtml(compactText(event.message || "", 52))}</small>
            </article>
          `).join("")}
        </div>
      `;
    }
    function renderEquipmentLiveHeaderActions() {
      const busy = equipmentRuntimeState().actionInFlight;
      return `
        <div class="ar-vis-runtime-actions ar-vis-runtime-actions-header" aria-label="Equipment bridge controls">
          <button type="button" class="ar-vis-runtime-action" data-equipment-live-action="test" ${busy === "test" ? "disabled" : ""}>TEST</button>
          <button type="button" class="ar-vis-runtime-action" data-equipment-live-action="open">OPEN</button>
          <button type="button" class="ar-vis-runtime-action" data-equipment-live-action="refresh" ${busy === "refresh" ? "disabled" : ""}>REFRESH</button>
        </div>
      `;
    }
    function equipmentRuntimeContext(report) {
      const equipment = latestEquipmentReport(report) || {};
      const result = latestEquipmentResult(report) || {};
      const packet = latestUtmDataReadyPacket(report) || {};
      const handoff = latestEquipmentHandoffPacket(report) || {};
      const skill = latestEquipmentSkillExecution(report) || {};
      const exception = latestEquipmentSkillException(report) || skill.exception || {};
      const runtime = equipmentRuntimeState();
      const snapshot = runtime.snapshot || {};
      const flowExecutionCandidate = snapshot.canonicalSkillFlowExecution || runtime.skillFlowSnapshot?.execution || null;
      const currentRunId = String(runtime.currentRunId || "");
      const skillFlowExecution = flowExecutionCandidate
        && currentRunId
        && String(flowExecutionCandidate.run_id || "") === currentRunId
        ? flowExecutionCandidate
        : null;
      return {
        report,
        equipment,
        result,
        packet,
        handoff,
        skill,
        exception,
        snapshot,
        canonicalExecution: snapshot.canonicalExecution || null,
        canonicalProjection: snapshot.canonicalProjection || null,
        skillFlow: snapshot.canonicalSkillFlow || runtime.skillFlowSnapshot?.flow || null,
        skillFlowExecution,
        visionTasks: snapshot.canonicalVisionTasks || runtime.skillFlowSnapshot?.vision_tasks || [],
        connection: snapshot.connection || {},
        readiness: snapshot.utm_readiness || {},
        evidenceAudit: snapshot.utm_evidence_audit || {},
        programs: Array.isArray(snapshot.programs) ? snapshot.programs : [],
        test: snapshot.last_test || {},
      };
    }
    function equipmentCanonicalProgressSteps(ctx) {
      const flow = ctx.skillFlow || {};
      const flowExecution = ctx.skillFlowExecution || {};
      const blocks = Array.isArray(flow.blocks) ? flow.blocks : [];
      if (blocks.length) {
        const transitions = Array.isArray(flowExecution.transitions) ? flowExecution.transitions : [];
        const transitionByNode = new Map(transitions.map((item) => [String(item?.node_id || ""), item]));
        const visionTasks = Array.isArray(ctx.visionTasks) ? ctx.visionTasks : [];
        const visionTaskById = new Map(visionTasks.map((item) => [String(item?.task_id || ""), item]));
        const activeNode = String(flowExecution.active_node || "");
        const terminal = String(flowExecution.terminal || "");
        const statusFor = (nodeId) => {
          const transition = transitionByNode.get(nodeId);
          if (transition) return transition.target === "__blocked__" || transition.success === false ? "blocked" : "complete";
          if (activeNode === nodeId) return "active";
          return terminal === "__blocked__" ? "blocked" : "waiting";
        };
        const steps = [];
        blocks.forEach((block) => {
          const skillNode = `${block.id}.skill`;
          const skillTransition = transitionByNode.get(skillNode) || {};
          const visionNode = `${block.id}.vision`;
          const visionTransition = transitionByNode.get(visionNode) || {};
          const visionTaskId = String(visionTransition.vision_task_id || block.vision?.task_id || "");
          const visionTask = visionTaskById.get(visionTaskId) || {};
          const visionEnabled = block.vision?.enabled === true;
          const visionOutcome = String(visionTransition.outcome || "waiting").toLowerCase();
          const visionStatus = !visionEnabled || !visionTransition.outcome
            ? "waiting"
            : ["detected", "completed", "complete", "success", "passed", "verified"].includes(visionOutcome)
              ? "success"
              : "failed";
          steps.push({
            blockId: String(block.id || ""),
            label: block.agentic?.task || block.label || block.id,
            status: statusFor(skillNode),
            detail: `${block.skill?.skill_id || "-"}@${block.skill?.skill_version || "-"} · ${skillTransition.outcome || "skill pending"}`,
            vision: {
              enabled: visionEnabled,
              blocking: block.vision?.blocking !== false,
              taskId: visionTaskId,
              label: String(visionTransition.verification_label || visionTransition.vision_task_label || block.vision?.result_label || visionTask.result_label || ""),
              status: visionStatus,
              outcome: String(visionTransition.outcome || "waiting"),
            },
          });
        });
        return steps;
      }
      // Keep the standard cycle visible until its configured profile arrives.
      // Internal skill lifecycle and bridge health are not completion evidence.
      return [
        ["prepare_next_specimen", "Move Jigs for Next Specimen"],
        ["start_test", "Start Test"],
        ["monitor_contact_and_run", "Monitor contact and compression"],
        ["await_auto_return", "Wait for automatic Height return"],
        ["save_raw_data", "Save Raw Data CSV"],
        ["validate_raw_data", "Validate Raw Data CSV"],
        ["advance_without_save", "Next Test without saving current test"],
        ["restore_robot_clearance", "Restore robot-entry clearance"],
      ].map(([blockId, label]) => ({blockId, label, status: "waiting", detail: ""}));
    }
    function equipmentBridgeState(ctx) {
      const bridge = ctx.equipment.bridge || {};
      const health = ctx.test.health || {};
      const explicit = bridge.connection_status || bridge.status || ctx.result.connection_status;
      if (explicit) return String(explicit);
      if (ctx.test.ok === true || health.ok === true) return "connected";
      if (ctx.test.ok === false || health.ok === false) return "unreachable";
      if (ctx.connection.last_status) return String(ctx.connection.last_status);
      return ctx.connection.selected ? "configured" : "not configured";
    }
    function equipmentActiveProgram(ctx) {
      const controlPlan = ctx.equipment.control_plan || {};
      const profile = controlPlan.profile || {};
      const decision = ctx.equipment.decision || {};
      const requested = controlPlan.program_id || ctx.result.program_id || ctx.handoff.program_id || ctx.skill.target_profile || "";
      const registered = ctx.programs.find((item) => item && (item.program_id === requested || item.id === requested || item.name === requested));
      return {
        programId: requested || registered?.program_id || registered?.id || "-",
        skillId: ctx.skill.skill_id || "-",
        version: ctx.skill.version || registered?.version || "-",
        profileId: profile.program_id || profile.id || ctx.skill.target_profile || "-",
        state: ctx.skill.state || ctx.result.status || decision.equipment_status || ctx.equipment.status || "idle",
      };
    }
    function equipmentEvidenceVerified(ctx) {
      const checks = Array.isArray(ctx.equipment.screen_checks) ? ctx.equipment.screen_checks : [];
      const cross = ctx.equipment.cross_checks || {};
      const audit = ctx.evidenceAudit || {};
      const checkOk = checks.length > 0 && checks.every((item) => item && item.ok === true);
      const parseOk = cross.data_parse_probe_ok === true || audit.data_parse_probe_ok === true || audit.ok === true;
      return checkOk && parseOk;
    }
    function equipmentProgressSteps(ctx) {
      const cycle = equipmentCycleContext(ctx);
      const cycleModel = equipmentAgenticTaskModel;
      if (cycle.available && cycleModel && typeof cycleModel.progressSteps === "function") {
        const blocks = Array.isArray(ctx.skillFlow?.blocks) ? ctx.skillFlow.blocks : [];
        const blockById = new Map(blocks.map((block) => [String(block?.id || ""), block]));
        const visionTasks = Array.isArray(ctx.visionTasks) ? ctx.visionTasks : [];
        const visionTaskById = new Map(visionTasks.map((task) => [String(task?.task_id || ""), task]));
        return cycleModel.progressSteps(cycle).map((step) => {
          const config = blockById.get(String(step.blockId || ""))?.vision || {};
          const enabled = config.enabled === true || step.vision.enabled === true;
          const taskId = String(step.vision.taskId || config.task_id || "");
          const task = visionTaskById.get(taskId) || {};
          return {
            blockId: step.blockId,
            label: step.label,
            status: step.status,
            detail: `${step.skill} · Vision ${enabled ? step.vision.outcome || "waiting" : "optional / off"}`,
            vision: {
              enabled,
              blocking: config.blocking !== false && step.vision.blocking !== false,
              taskId,
              label: String(step.vision.label || config.result_label || task.result_label || ""),
              status: enabled ? step.vision.status || "waiting" : "waiting",
              outcome: step.vision.outcome,
            },
          };
        });
      }
      return equipmentCanonicalProgressSteps(ctx);
    }
    function renderEquipmentAgenticProgress(ctx) {
      return `
        <div class="ar-vis-agentic-progress">
          ${equipmentProgressSteps(ctx).map((step, index) => `
            <div class="ar-vis-agentic-step is-${visionProgressTone(step.status)}">
              <div class="ar-vis-agentic-step-heading">
                <span class="ar-vis-agentic-step-index">${String(index + 1).padStart(2, "0")}</span>
                <strong>${escapeHtml(step.label)}</strong>
              </div>
              <em>${escapeHtml(step.status)}</em>
              <small>${escapeHtml(compactText(step.detail, 80))}</small>
              <div class="ar-equipment-vision-slot ar-equipment-agentic-vision-slot ${step.vision?.enabled ? `is-${escapeHtml(step.vision.status || "waiting")}` : "is-empty"}">
                ${step.vision?.enabled
                  ? `<span>Vision verification:</span><strong>${escapeHtml(step.vision.label || "WAITING")}</strong>`
                  : '<span aria-hidden="true">&nbsp;</span>'}
              </div>
              <span class="ar-vis-agentic-port ar-vis-agentic-port-in" aria-hidden="true"></span>
              <span class="ar-vis-agentic-port ar-vis-agentic-port-out" aria-hidden="true"></span>
            </div>
          `).join("")}
        </div>
      `;
    }
    function renderEquipmentBridgeRuntime(ctx) {
      const state = equipmentBridgeState(ctx);
      const provider = (ctx.equipment.bridge || {}).provider || ctx.connection.bridge || "windows_pyautogui";
      const health = ctx.test.health || {};
      const screen = health.screen || {};
      const pyautogui = health.pyautogui || {};
      const runtime = equipmentRuntimeState();
      const refreshed = runtime.refreshedAt ? new Date(runtime.refreshedAt).toLocaleTimeString() : "not checked";
      return `
        <div class="ar-vis-summary-stack">
          <div class="ar-report-metrics">
            ${renderDashboardMetric("Bridge", state, provider, /connected|ready|healthy|ok/i.test(state) ? "success" : "warning")}
            ${renderDashboardMetric("Target", ctx.connection.selected_candidate || "-", ctx.connection.scope || "saved", ctx.connection.selected ? "success" : "idle")}
            ${renderDashboardMetric("Token", ctx.connection.token_configured === undefined ? "-" : ctx.connection.token_configured, "configured", ctx.connection.token_configured ? "success" : "warning")}
          </div>
          ${renderDashboardRows([
            ["endpoint", ctx.connection.bridge_url || "-"],
            ["platform", ctx.connection.platform || "-"],
            ["desktop", screen.width && screen.height ? `${screen.width}x${screen.height}` : "-"],
            ["pyautogui", pyautogui.available === undefined ? "-" : pyautogui.available],
            ["server", health.server_version || health.script_version || "-"],
            ["programs", health.program_count ?? ctx.programs.length ?? "-"],
            ["last refresh", refreshed],
            ["diagnostic", runtime.error || "-"],
          ])}
        </div>
      `;
    }
    function renderEquipmentActiveExecution(ctx) {
      const active = equipmentActiveProgram(ctx);
      const model = ctx.skill.model_snapshot || {};
      const completedSegments = Array.isArray(ctx.skill.completed_segments) ? ctx.skill.completed_segments : [];
      return renderDashboardRows([
        ["program", active.programId],
        ["skill", active.skillId === "-" ? "-" : `${active.skillId}@${active.version}`],
        ["profile", active.profileId],
        ["state", active.state],
        ["completed_segments", completedSegments.length ? completedSegments.join(", ") : "-"],
        ["segment", ctx.skill.current_segment || ctx.skill.failed_segment || "-"],
        ["recovery model", [model.provider, model.model].filter(Boolean).join(" / ") || "not invoked"],
      ]);
    }
    function renderEquipmentRecoveryBoundary(ctx) {
      const allowed = Array.isArray(ctx.exception.allowed_recovery_operations) ? ctx.exception.allowed_recovery_operations : [];
      const history = Array.isArray(ctx.skill.recovery_history) ? ctx.skill.recovery_history : [];
      return renderDashboardRows([
        ["attempt", ctx.skill.attempt || 0],
        ["failure", ctx.exception.failure_code || ctx.skill.failure_code || ctx.result.failure_code || "none"],
        ["checkpoint", ctx.exception.checkpoint_id || "-"],
        ["allowed", allowed.length ? allowed.join(", ") : "none recorded"],
        ["last recovery", history.length ? `${history.at(-1).operation || "action"}:${history.at(-1).status || "recorded"}` : "-"],
      ]);
    }
    function renderEquipmentExecutionEvidence(ctx) {
      const checks = Array.isArray(ctx.equipment.screen_checks) ? ctx.equipment.screen_checks : [];
      const data = ctx.equipment.data_acquisition || {};
      const cross = ctx.equipment.cross_checks || {};
      const lastEvent = ((ctx.report && ctx.report.events) || []).filter((event) => {
        const text = `${event.event_type || event.type || ""} ${event.node_id || ""} ${event.message || ""}`.toLowerCase();
        return /equipment|utm|windows|bridge|pyautogui|analysis/.test(text);
      }).at(-1) || {};
      return `
        <div class="ar-vis-summary-stack">
          <div class="ar-report-metrics">
            ${renderDashboardMetric("Screen", `${checks.filter((item) => item && item.ok).length}/${checks.length}`, "verified", checks.length && checks.every((item) => item && item.ok) ? "success" : "warning")}
            ${renderDashboardMetric("Rows", data.row_count_probe || "-", "probe", data.row_count_probe ? "success" : "idle")}
            ${renderDashboardMetric("Parse", cross.data_parse_probe_ok === undefined ? "-" : cross.data_parse_probe_ok, "data", cross.data_parse_probe_ok ? "success" : "warning")}
            ${renderDashboardMetric("Event", lastEvent.event_type || lastEvent.type || "-", formatTime(lastEvent.ts || lastEvent.timestamp), lastEvent.level === "ERROR" ? "danger" : "info")}
          </div>
          ${renderVisionCardDetails("Inspection details", `${renderEquipmentGatePanel(ctx.equipment)}${renderEquipmentSensorTable(ctx.equipment)}${renderEquipmentEventLog(ctx.report || {})}`)}
        </div>
      `;
    }
    function renderEquipmentHandoff(ctx) {
      const decision = ctx.equipment.decision || {};
      const data = ctx.equipment.data_acquisition || {};
      return renderDashboardRows([
        ["status", decision.handoff_status || ctx.handoff.status || "waiting"],
        ["next agent", ctx.handoff.next_agent || decision.next_agent || "Analysis"],
        ["schema", ctx.packet.schema || ctx.handoff.schema || "-"],
        ["result", data.linux_path || ctx.result.result_file || ctx.packet.result_file || ctx.handoff.result_file || "-"],
        ["checksum", data.checksum || ctx.packet.checksum || "-"],
        ["guardian", decision.guardian_required === undefined ? "-" : decision.guardian_required],
      ]);
    }
    function renderEquipmentCycleHeader(ctx) {
      const cycle = equipmentCycleContext(ctx);
      if (!cycle.available) return "";
      const task = cycle.task || {};
      const gate = task.entry_gate || (ctx.equipment || {}).required_entry_gate || (ctx.result || {}).required_entry_gate || {};
      const gateOk = gate.ok === true || gate.status === "ready_for_equipment";
      return `
        <section class="ar-equipment-cycle-header" aria-label="Lab Equipment Agent cycle">
          <div>
            <small>LAB EQUIPMENT AGENT · WORKFLOW TASK</small>
            <strong>${escapeHtml(task.label || "UTM Compression Cycle")}</strong>
            <span>${escapeHtml(task.task_id || "-")} · ${escapeHtml(task.status || "waiting")}</span>
            <span>Profile ${escapeHtml(task.profile_id || "-")} · Flow ${escapeHtml(task.flow_id || "-")}@${escapeHtml(task.flow_version ?? "-")}</span>
            <span>Run ${escapeHtml(task.run_id || "-")} · Specimen ${escapeHtml(task.specimen_id || "-")}</span>
          </div>
          <div class="ar-equipment-cycle-gate is-${gateOk ? "ready" : "locked"}">
            <small>LOCKED ENTRY GATE</small>
            <strong>${escapeHtml(gate.status || (gateOk ? "ready_for_equipment" : "waiting"))}</strong>
            <span>${gate.locked === false ? "contract gate" : "mandatory upstream confirmation"}</span>
          </div>
        </section>
      `;
    }
    function equipmentCycleDisplayValue(value) {
      if (value === null || value === undefined || value === "") return "-";
      if (typeof value === "object") {
        const numeric = value.value ?? value.observed ?? value.target;
        const unit = value.unit || "";
        if (numeric !== null && numeric !== undefined) return `${numeric}${unit ? ` ${unit}` : ""}`;
        return compactText(JSON.stringify(value), 80);
      }
      return String(value);
    }
    function renderEquipmentMethodValues(ctx) {
      const cycle = equipmentCycleContext(ctx);
      const model = equipmentAgenticTaskModel;
      if (!cycle.available || !model || typeof model.methodRows !== "function") return renderDashboardRows([["status", "cycle evidence unavailable"]]);
      const rows = model.methodRows(cycle);
      return `
        <div class="ar-equipment-method-grid">
          ${rows.map((row) => `
            <article>
              <strong>${escapeHtml(row.label)}</strong>
              <span><small>Observed</small>${escapeHtml(equipmentCycleDisplayValue(row.observed))}</span>
              <span><small>Method target</small>${escapeHtml(equipmentCycleDisplayValue(row.target))}</span>
            </article>
          `).join("")}
        </div>
      `;
    }
    function renderEquipmentScreenTransitions(ctx) {
      const cycle = equipmentCycleContext(ctx);
      if (!cycle.available) return renderDashboardRows([["status", "cycle evidence unavailable"]]);
      const evidence = Array.isArray(cycle.screenTransitions) ? cycle.screenTransitions : [];
      if (!evidence.length) return renderDashboardRows([["status", "screen transition evidence pending"]]);
      return `
        <div class="ar-equipment-transition-list">
          ${evidence.slice(-8).map((item) => {
            const frames = [item.before_frame, item.after_frame].filter(Boolean).join(" → ") || "-";
            const locator = [item.locator_id, item.locator_version].filter(Boolean).join("@") || "-";
            const postcondition = item.postcondition && typeof item.postcondition === "object"
              ? JSON.stringify(item.postcondition)
              : item.postcondition || "-";
            return `
              <article>
                <strong>${escapeHtml(item.block_id || item.step || item.label || "transition")}</strong>
                <span>${escapeHtml(item.outcome || item.status || (item.ok === true ? "verified" : "recorded"))}</span>
                <small>frames · ${escapeHtml(compactText(frames, 96))}</small>
                <small>locator · ${escapeHtml(compactText(locator, 96))}</small>
                <small>postcondition · ${escapeHtml(compactText(postcondition, 120))}</small>
              </article>
            `;
          }).join("")}
        </div>
      `;
    }
    function equipmentArtifactUrl(path) {
      const targetPath = String(path || "").replace(/\\/g, "/");
      const artifacts = equipmentRuntimeState().runArtifacts;
      if (!targetPath || !Array.isArray(artifacts)) return "";
      const artifact = artifacts.find((item) => {
        const candidates = [item?.path, item?.local_path, item?.name]
          .map((value) => String(value || "").replace(/\\/g, "/"));
        return candidates.includes(targetPath);
      });
      const url = String(artifact?.url || artifact?.download_url || artifact?.compat_url || "").trim();
      return url.startsWith("/api/runs/") || url.startsWith("/api/artifacts/") ? url : "";
    }
    function renderEquipmentRawDataReadiness(ctx) {
      const cycle = equipmentCycleContext(ctx);
      const model = equipmentAgenticTaskModel;
      if (!cycle.available || !model) return renderDashboardRows([["status", "cycle evidence unavailable"]]);
      const raw = typeof model.rawData === "function" ? model.rawData(cycle) : {};
      const readiness = typeof model.readiness === "function" ? model.readiness(cycle) : {};
      const eligible = cycle.handoffEligibility || {};
      const artifactUrl = equipmentArtifactUrl(raw.path);
      return `
        <div class="ar-vis-summary-stack">
          <div class="ar-report-metrics">
            ${renderDashboardMetric("CSV", raw.validated === true ? "VALID" : raw.validated === false ? "INVALID" : "PENDING", raw.row_count === undefined ? "rows -" : `${raw.row_count} rows`, raw.validated === true ? "success" : "warning")}
            ${renderDashboardMetric("Next Test", readiness.next_test_completed === true ? "DONE" : "WAIT", readiness.save_current_test === false ? "current test not saved" : "pending", readiness.next_test_completed === true ? "success" : "idle")}
            ${renderDashboardMetric("Clearance", readiness.clearance_restored === true ? "READY" : "WAIT", "robot entry", readiness.clearance_restored === true ? "success" : "warning")}
          </div>
          <div class="ar-equipment-raw-artifact">
            <small>RAW CSV</small>
            ${artifactUrl
              ? `<a href="${escapeHtml(artifactUrl)}" target="_blank" rel="noreferrer">${escapeHtml(raw.path || "Open CSV artifact")}</a>`
              : `<span>${escapeHtml(raw.path || "artifact link pending")}</span>`}
          </div>
          ${renderDashboardRows([
            ["parse", raw.parse_ok === undefined ? "-" : raw.parse_ok],
            ["stable", raw.stable === undefined ? "-" : raw.stable],
            ["columns", Array.isArray(raw.columns) ? raw.columns.join(", ") : "-"],
            ["artifact identity", raw.same_artifact === true && raw.identity_ok === true ? "verified" : "pending"],
            ["next specimen ready", readiness.ready === undefined ? "-" : readiness.ready],
            ["handoff eligible", eligible.eligible === undefined ? "-" : eligible.eligible],
            ["failure", eligible.failure_code || "none"],
          ])}
        </div>
      `;
    }
    function renderDashboard(report, status, agentLabel, profile) {
      const ctx = equipmentRuntimeContext(report);
      const failed = Boolean(ctx.exception.failure_code || ctx.skill.failure_code || ctx.result.failure_code);
      const cycleAvailable = equipmentCycleContext(ctx).available;
      return `
        ${cycleAvailable ? renderEquipmentCycleHeader(ctx) : ""}
        ${renderDashboardCard("Bridge / Runtime", renderEquipmentBridgeRuntime(ctx), { span: 4, tone: /connected|ready|healthy|ok/i.test(equipmentBridgeState(ctx)) ? "success" : "equipment", eyebrow: "device bridge", action: renderEquipmentLiveHeaderActions() })}
        ${renderDashboardCard("Active Program / Skill", renderEquipmentActiveExecution(ctx), { span: 4, tone: "equipment", eyebrow: "Equipment Skill Execution" })}
        ${renderDashboardCard("Recovery Boundary", renderEquipmentRecoveryBoundary(ctx), { span: 4, tone: failed ? "warning" : "equipment", eyebrow: "exception only" })}
        ${renderDashboardCard("Agentic Progress", renderEquipmentAgenticProgress(ctx), { span: 12, tone: failed ? "warning" : "equipment", eyebrow: "resolve to handoff", className: "ar-equipment-agentic-card" })}
        ${cycleAvailable ? `
          ${renderDashboardCard("Method Values", renderEquipmentMethodValues(ctx), { span: 4, tone: "equipment", eyebrow: "observed / configured" })}
          ${renderDashboardCard("Screen Transitions", renderEquipmentScreenTransitions(ctx), { span: 4, tone: "equipment", eyebrow: "step completion evidence" })}
          ${renderDashboardCard("Raw Data / Next Specimen", renderEquipmentRawDataReadiness(ctx), { span: 4, tone: "equipment", eyebrow: "CSV + clearance" })}
        ` : ""}
        ${renderDashboardCard("Execution Evidence", renderEquipmentExecutionEvidence(ctx), { span: 8, tone: equipmentEvidenceVerified(ctx) ? "success" : "equipment", eyebrow: "screen + data" })}
        ${renderDashboardCard("Handoff", renderEquipmentHandoff(ctx), { span: 4, tone: ctx.result.failure_code ? "warning" : "equipment", eyebrow: "analysis contract" })}
      `;
    }

    function dispose() {}
    return Object.freeze({renderReport, renderDashboard, dispose});
  }

  global.AX4LABEquipmentUI = Object.freeze({createFrontend});
})(window);
