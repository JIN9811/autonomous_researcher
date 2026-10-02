/* Specimen-owned report markup. Shared camera, STL and live state stay in the host. */
(function installSpecimenLiveReport(global) {
  "use strict";
  function createFrontend(services) {
    const {
      latestSpecimenFabricationReport,
      latestSpecimenFabricatedPacket,
      renderRuntimeValue,
      runtimeRows,
      renderReportList,
      renderStepTrace,
      specimenRuntimeContext,
      specimenProgressPercent,
      specimenFirstValue,
      specimenStatusTone,
      renderDashboardCard,
      renderDashboardMetric,
      renderSpecimenProgressBar,
      renderSpecimenNowPrintingBody,
      renderSpecimenPrintMonitoringBody,
      renderSpecimenVideoHeaderControls,
      renderSpecimenPrinterStatusBody,
      renderSpecimenPrintConnectionBody,
      renderSpecimenConnectionTestHeaderAction,
      renderSpecimenAgenticProgressBody,
    } = services;

    function renderReport(report) {
      const fabricationReport = latestSpecimenFabricationReport(report);
      if (!fabricationReport || typeof fabricationReport !== "object") return "";
      const packet = latestSpecimenFabricatedPacket(report) || {};
      const intent = fabricationReport.fabrication_intent || {};
      const thread = fabricationReport.digital_thread || {};
      const plan = fabricationReport.process_plan || {};
      const cap = plan.cap_skin_policy || {};
      const adhesion = plan.adhesion_policy || {};
      const ejection = plan.ejection_policy || {};
      const monitoring = fabricationReport.monitoring_plan || {};
      const runtime = fabricationReport.printer_runtime || {};
      const selectedPrinter = runtime.selected_printer || {};
      const deviceScreen = runtime.device_screen || {};
      const deviceConnection = deviceScreen.connection || {};
      const deviceActions = deviceScreen.actions || {};
      const preprintGate = runtime.preprint_gate || {};
      const readinessLevels = Array.isArray(runtime.readiness_levels) ? runtime.readiness_levels : [];
      const operatorActions = Array.isArray(runtime.operator_actions) ? runtime.operator_actions : [];
      const autoejectionGate = runtime.autoejection || {};
      const autoejectionHandoff = runtime.autoejection_handoff || autoejectionGate.handoff || {};
      const outcome = fabricationReport.fabrication_outcome || {};
      const feedback = fabricationReport.feedback_to_design || {};
      const gates = Array.isArray(fabricationReport.quality_gates) ? fabricationReport.quality_gates : [];
      const wall = gates.find(g => g.gate === "manufacturability")?.evidence?.wall_thickness_verification || {};
      const gateItems = gates.map((gate) => `${gate.gate || "gate"} · ${gate.status || "unknown"}${gate.repair ? ` · repair=${renderRuntimeValue(gate.repair)}` : ""}`);
      const readinessItems = readinessLevels.map((item) => `${item.level_id || item.id || "readiness"} · ${item.status || "unknown"}${item.reason || item.summary ? ` · ${item.reason || item.summary}` : ""}`);
      const operatorActionItems = operatorActions.map((item) => `${item.action_id || item.id || "operator_action"} · ${item.status || "required"}${item.label || item.summary ? ` · ${item.label || item.summary}` : ""}`);
      const defectClasses = Array.isArray(monitoring.defect_classes) ? monitoring.defect_classes.join(", ") : "-";
      return `
        <div class="live-agent-specific-specimen-details">
          <h5>Fabrication Intent</h5>
          ${runtimeRows([
            ["mode", intent.mode || "-"],
            ["printer_path", intent.printer_path || "-"],
            ["physical_intent", intent.physical_intent === undefined ? "-" : intent.physical_intent],
            ["specimen_purpose", intent.specimen_purpose || "-"],
            ["live_gui_test_spec", intent.live_gui_test_spec === undefined ? "-" : intent.live_gui_test_spec],
          ])}
          <h5>Digital Thread</h5>
          ${runtimeRows([
            ["candidate_id", thread.candidate_id || "-"],
            ["specimen_id", thread.specimen_id || "-"],
            ["design_hash", thread.design_hash || "-"],
            ["geometry_hash", thread.geometry_hash || "-"],
            ["stl_path", thread.stl_path || "-"],
            ["gcode_path", thread.gcode_path || "-"],
            ["handoff_package_path", thread.handoff_package_path || "-"],
            ["printer_job_id", thread.printer_job_id || "-"],
          ])}
          <h5>Process Plan</h5>
          ${runtimeRows([
            ["material", thread.material || "-"],
            ["printer_profile", thread.printer_profile || "-"],
            ["slicer_profile_hint", thread.slicer_profile_hint || "-"],
            ["layer_height_mm", plan.layer_height_mm || "-"],
            ["first_layer_height_mm", plan.first_layer_height_mm || "-"],
            ["nozzle_diameter_mm", plan.nozzle_diameter_mm || "-"],
            ["bed_temperature_c", plan.bed_temperature_c || "-"],
            ["first_layer_bed_temperature_c", plan.first_layer_bed_temperature_c || "-"],
            ["slow_first_layer", adhesion.slow_first_layer_enabled === undefined ? "-" : adhesion.slow_first_layer_enabled],
            ["first_layer_speed_mm_s", adhesion.first_layer_speed_mm_s || "-"],
            ["cap_skin", `top=${renderRuntimeValue(cap.top_cap_enabled)} bottom=${renderRuntimeValue(cap.bottom_cap_enabled)} thickness=${renderRuntimeValue(cap.skin_thickness_mm)}`],
            ["ejection_policy", `${ejection.status || "-"} requested=${renderRuntimeValue(ejection.requested)}`],
            ["estimated_mass_g", plan.estimated_mass_g || "-"],
            ["slicer_print_time_min", plan.duration_evidence?.source === 'slicer' ? plan.duration_evidence.duration_min : "Not available"],
          ])}
          <h5>Quality Gates</h5>
          ${renderReportList(gateItems, "No manufacturing quality gates recorded.")}
          ${runtimeRows([
            ["Actual mesh wall check", wall.status || "Not measured"],
            ["Required minimum (mm)", wall.required_minimum_mm ?? "-"],
            ["Sampled minimum (mm)", wall.minimum_sampled_mm ?? "-"],
            ["Samples", wall.sample_count ?? "-"],
          ])}
          <h5>Printer Runtime</h5>
          ${runtimeRows([
            ["provider", runtime.provider || thread.printer_provider || selectedPrinter.provider || "-"],
            ["selected_printer", selectedPrinter.label || selectedPrinter.profile_id || "-"],
            ["device_mqtt", deviceConnection.mqtt || "-"],
            ["device_transfer", deviceConnection.transfer || "-"],
            ["device_video", deviceConnection.video || "-"],
            ["can_upload", deviceActions.can_upload === undefined ? "-" : deviceActions.can_upload],
            ["can_start_print", deviceActions.can_start_print === undefined ? "-" : deviceActions.can_start_print],
            ["preprint_state", preprintGate.state || "-"],
            ["technical_ready_for_start", preprintGate.technical_ready_for_start === undefined ? "-" : preprintGate.technical_ready_for_start],
            ["approval_ready_for_start", preprintGate.approval_ready_for_start === undefined ? "-" : preprintGate.approval_ready_for_start],
            ["ready_for_live_print", preprintGate.ready_for_live_print === undefined ? "-" : preprintGate.ready_for_live_print],
            ["preprint_blockers", preprintGate.blockers || []],
            ["autoejection_status", autoejectionGate.status || "-"],
            ["autoejection_blockers", autoejectionGate.blockers || []],
            ["autoejection_handoff", autoejectionHandoff.schema || autoejectionHandoff.status || "-"],
            ["recommended_consumer_agent", autoejectionHandoff.recommended_consumer_agent || autoejectionHandoff.next_owner || "-"],
            ["next_tool", autoejectionHandoff.next_tool || "-"],
            ["requires_guardian_approval", autoejectionHandoff.requires_guardian_approval === undefined ? "-" : autoejectionHandoff.requires_guardian_approval],
            ["requires_operator_confirmation", autoejectionHandoff.requires_operator_confirmation === undefined ? "-" : autoejectionHandoff.requires_operator_confirmation],
            ["motion_started", autoejectionHandoff.motion_started === undefined ? "-" : autoejectionHandoff.motion_started],
            ["prepare_status", runtime.prepare_status || "-"],
            ["mode", runtime.mode || "-"],
            ["path", runtime.path || "-"],
            ["upload", runtime.upload && (runtime.upload.status || runtime.upload.failure_code || (runtime.upload.ok ? "ok" : "-"))],
            ["transfer_wait", runtime.transfer_wait && (runtime.transfer_wait.status || runtime.transfer_wait.failure_code || (runtime.transfer_wait.ok ? "ok" : "-"))],
            ["start", runtime.start && (runtime.start.status || runtime.start.failure_code || (runtime.start.ok ? "ok" : "-"))],
            ["ejection", runtime.ejection && (runtime.ejection.status || runtime.ejection.failure_code || "-")],
          ])}
          ${renderReportList(readinessItems, "No SPC readiness levels recorded.", 12)}
          ${renderReportList(operatorActionItems, "No operator action contract recorded.", 8)}
          ${Array.isArray(runtime.step_trace) && runtime.step_trace.length ? renderStepTrace(runtime.step_trace) : ""}
          <h5>Monitoring / Feedback</h5>
          ${runtimeRows([
            ["observe_printer_bridge_status", monitoring.observe_printer_bridge_status === undefined ? monitoring.observe_prusalink_status : monitoring.observe_printer_bridge_status],
            ["observe_transfer_idle", monitoring.observe_transfer_idle],
            ["observe_camera_after_print", monitoring.observe_camera_after_print],
            ["layerwise_monitoring_available", monitoring.layerwise_monitoring_available],
            ["defect_classes", defectClasses],
            ["outcome", outcome.status || "-"],
            ["location", outcome.location || "-"],
            ["failure_code", outcome.failure_code || "-"],
            ["quality_score", feedback.quality_score === undefined ? "-" : feedback.quality_score],
            ["uncertainty", feedback.uncertainty === undefined ? "-" : feedback.uncertainty],
            ["packet", packet.schema || "-"],
            ["next_action", packet.next_action || "-"],
          ])}
        </div>
      `;
    }

    function renderDashboard(report, status, agentLabel, profile) {
      const ctx = specimenRuntimeContext(report);
      const progressPanel = ctx.progressPanel || {};
      const progress = specimenProgressPercent(progressPanel.progress_percent, ctx.printerStatus.progress_percent, ctx.outcome.progress_percent, ctx.packet.progress_percent);
      return `
        ${renderDashboardCard("Now printing", renderSpecimenNowPrintingBody(ctx, report), { span: 3, tone: "specimen", eyebrow: "DSN STL preview", className: "ar-spm-panel-card ar-spm-now-printing-card" })}
        ${renderDashboardCard("Printing Progress", `
          ${renderSpecimenProgressBar(progress, "live job monitor")}
          <div class="ar-report-metrics">
            ${renderDashboardMetric("State", specimenFirstValue(progressPanel.state, ctx.monitor.snapshot.status, status, "-"), "job", specimenStatusTone(specimenFirstValue(progressPanel.state, ctx.monitor.snapshot.status, status)))}
            ${renderDashboardMetric("Layer", `${renderRuntimeValue(specimenFirstValue(progressPanel.current_layer, "-"))} / ${renderRuntimeValue(specimenFirstValue(progressPanel.total_layers, "-"))}`, "current / total", "info")}
            ${renderDashboardMetric("Remain", specimenFirstValue(progressPanel.remaining_min, ctx.printerStatus.remaining_time_min, "-"), "min", "metrics")}
          </div>
        `, { span: 9, tone: "specimen", eyebrow: "live job monitor", className: "ar-spm-panel-card ar-spm-progress-card" })}
        ${renderDashboardCard("Print Monitoring", renderSpecimenPrintMonitoringBody(ctx), { span: 4, tone: "activity", eyebrow: "3DP video", className: "ar-spm-panel-card ar-spm-monitoring-card", action: renderSpecimenVideoHeaderControls(ctx) })}
        ${renderDashboardCard("Printer Status", renderSpecimenPrinterStatusBody(ctx), { span: 4, tone: "metrics", eyebrow: "thermal + material", className: "ar-spm-panel-card ar-spm-status-card" })}
        ${renderDashboardCard("Print Connection", renderSpecimenPrintConnectionBody(ctx), { span: 4, tone: "info", eyebrow: "bridge state", className: "ar-spm-panel-card ar-spm-connection-card", action: renderSpecimenConnectionTestHeaderAction(ctx), data: { "spm-progress-step": "print_connection" } })}
        ${renderDashboardCard("Agentic Progress", renderSpecimenAgenticProgressBody(ctx), { span: 12, tone: "specimen", eyebrow: "click for details", className: "ar-spm-panel-card ar-spm-agentic-card" })}
      `;
    }

    function dispose() {}
    return Object.freeze({ renderReport, renderDashboard, dispose });
  }
  global.AX4LABSpecimenUI = Object.freeze({ createFrontend });
})(window);
