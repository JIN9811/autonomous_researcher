/* Vision-owned markup; camera resources, verification selection and event handlers remain in the host. */
(function installVisionLiveReport(global) {
  "use strict";
  function createFrontend(services) {
    const { latestVisionReport, latestVisionSignalPacket, renderRuntimeValue, renderReportList, latestVisionAgentReport, visionSpecimenInterventionFor, latestActiveCamArtifact, utmVerificationScope, updateUtmVerificationSelection, selectVerification, escapeHtml, renderVisionUtmPlacementConfirmation, renderVisionSpecimenIntervention, renderVisionUtmVerification, visionLiveCameraProfile, visionLiveFrameEvidence, renderDashboardCard, renderVisionRuntimeControls, renderVisionLiveFrameEvidence, renderVisionCardDetails, renderVisionInspectionFeed, renderVisionSegmentationPanels, renderVisionRuntimeHeaderActions, renderVisionActiveCamEjectionCheck, renderVisionUtmVerificationTabs, renderVisionCameraRuntimeSummary, renderVisionCameraHealthBoard, renderVisionRuntimeNodeFlow, renderVisionHandoffSignal, renderVisionEvidenceReviewBoard, dashboardList, renderVisionAgenticProgress, renderDashboardMetric, renderDashboardRows, renderVisionConfusionMatrix, renderMiniBarChart, visionRuntimeStatus, runtimeRows } = services;
    function renderReport(report) {
      const visionReport = latestVisionReport(report);
      if (!visionReport || typeof visionReport !== "object") return "";
      const packet = latestVisionSignalPacket(report) || {};
      const camera = visionReport.camera_source || {};
      const backend = visionReport.model_backend || {};
      const zones = visionReport.scene_map || visionReport.zones || {};
      const zoneItems = Object.entries(zones).map(([zoneId, zone]) => {
        const item = zone && typeof zone === "object" ? zone : {};
        const state = item.state || (item.specimen_present ? "present" : item.clear ? "clear" : "unknown");
        return `${zoneId} · ${state} · conf=${renderRuntimeValue(item.confidence)}`;
      });
      const signals = Array.isArray(visionReport.signal_board) ? visionReport.signal_board : Array.isArray(visionReport.agent_signals) ? visionReport.agent_signals : [];
      const signalItems = signals.map((signal) => `${signal.signal || "signal"} · ${signal.status || "-"} · ${signal.zone_id || "-"} · conf=${renderRuntimeValue(signal.confidence)} · expires=${renderRuntimeValue(signal.expires_at)}${signal.blocking_reason ? ` · ${signal.blocking_reason}` : ""}`);
      const events = Array.isArray(visionReport.events) ? visionReport.events : [];
      const eventItems = events.map((event) => `${event.event_type || "event"} · ${event.status || "-"} · conf=${renderRuntimeValue(event.confidence)}${event.blocking ? " · blocking" : ""}`);
      const detections = Array.isArray(visionReport.detections) ? visionReport.detections : [];
      const detectionItems = detections.map((det) => `${det.label || "object"} · ${det.zone || "-"} · conf=${renderRuntimeValue(det.confidence)} · bbox=${renderRuntimeValue(det.bbox_xyxy || [])}`);
      const artifacts = visionReport.artifacts || {};
      const safety = visionReport.safety_anomaly || {};
      const dataset = visionReport.dataset_ledger || {};
      const knowledge = visionReport.knowledge_payload || {};
      return `
        <div class="live-agent-specific-vision-details">
          <h5>Scene Task / Camera Source</h5>
          ${runtimeRows([
            ["task", visionReport.task || "-"],
            ["camera_key", camera.camera_key || "-"],
            ["source", camera.source || "-"],
            ["frame_id", camera.frame_id || "-"],
            ["timestamp", camera.timestamp || "-"],
            ["calibration_id", camera.calibration_id || "-"],
            ["model_backend", `${backend.mode || "-"} / detector=${backend.detector || "-"} / pose=${backend.pose_backend || "-"}`],
          ])}
          <h5>Zone State</h5>
          ${renderReportList(zoneItems, "No zone states recorded.")}
          <h5>Detection / Tracking</h5>
          ${renderReportList(detectionItems, "No detections recorded.")}
          <h5>Agent Signal Board</h5>
          ${renderReportList(signalItems, "No agent signals recorded.", 32)}
          <h5>Evidence Timeline</h5>
          ${renderReportList(eventItems, "No visual events recorded.")}
          <h5>Evidence Artifacts / Dataset Ledger</h5>
          ${runtimeRows([
            ["annotated_frame_path", artifacts.annotated_frame_path || "-"],
            ["detection_json_path", artifacts.detection_json_path || "-"],
            ["episode_id", dataset.episode_id || "-"],
            ["candidate_for_lerobot_dataset", dataset.candidate_for_lerobot_dataset === undefined ? "-" : dataset.candidate_for_lerobot_dataset],
            ["success_labels", knowledge.success_labels || []],
            ["failure_labels", knowledge.failure_labels || []],
          ])}
          <h5>Safety / Handoff</h5>
          ${runtimeRows([
            ["anomaly", safety.anomaly === undefined ? "-" : safety.anomaly],
            ["low_confidence", safety.low_confidence === undefined ? "-" : safety.low_confidence],
            ["blocking_reason", safety.blocking_reason || "-"],
            ["packet", packet.schema || "-"],
            ["primary_signal", packet.signal_id || "-"],
            ["next_action", packet.next_action || "-"],
          ])}
        </div>
      `;
    }

    function renderDashboard(report, status, agentLabel, profile) {
      const screenReport = latestVisionAgentReport(report) || {};
      const activeCamIntervention = visionSpecimenInterventionFor(report, "active_cam_ejection");
      const utmIntervention = visionSpecimenInterventionFor(report, "utm_post_place");
      const activeCamArtifact = latestActiveCamArtifact(report);
      const activeCamCheck = screenReport.active_cam_ejection_check || {};
      const activeCamConfirmed = activeCamCheck.status === "confirmed"
        && activeCamCheck.spc_autoejection_confirmed === true
        && activeCamCheck.specimen_detected === true;
      const utmScope = utmVerificationScope(report);
      const utmSelection = updateUtmVerificationSelection(utmScope);
      const selectedUtmVerification = selectVerification(utmScope, utmSelection.index);
      const utmVerificationBody = selectedUtmVerification.index === 1
        ? `<div class="ar-vis-utm-selected-title"><strong>${escapeHtml(selectedUtmVerification.title)}</strong><span>${escapeHtml(selectedUtmVerification.capturedAt || "Pending")}</span></div>${renderVisionUtmPlacementConfirmation(
          screenReport,
          { ...selectedUtmVerification.evidence, status: selectedUtmVerification.status, detected: selectedUtmVerification.confirmed },
          { ...selectedUtmVerification.artifact, detected: selectedUtmVerification.confirmed },
          {},
        )}${renderVisionSpecimenIntervention(utmIntervention, "utm_post_place")}`
        : renderVisionUtmVerification(selectedUtmVerification);
      const visionReport = latestVisionReport(report) || {};
      const packet = latestVisionSignalPacket(report) || {};
      const liveProfile = visionLiveCameraProfile();
      const liveFrame = visionLiveFrameEvidence(report, screenReport, visionReport);
      const calibration = screenReport.calibration_summary || {};
      const confidenceDistribution = screenReport.confidence_distribution || {};
      const inspectionFeed = screenReport.inspection_feed || {};
      const segmentation = screenReport.segmentation || {};
      const defectSummary = screenReport.defect_summary || {};
      const pose = screenReport.pose_estimation || {};
      const confusion = screenReport.confusion_matrix || {};
      const quality = screenReport.quality_metrics || {};
      const evidence = screenReport.evidence_review || {};
      const signals = Array.isArray(visionReport.signal_board) ? visionReport.signal_board : Array.isArray(visionReport.agent_signals) ? visionReport.agent_signals : [];
      const zones = visionReport.scene_map || visionReport.zones || {};
      const anomaly = visionReport.safety_anomaly || {};
      const calibrationRows = Array.isArray(calibration.line_chart) ? calibration.line_chart.map((item) => ({ label: item.x || "metric", value: item.value, tone: "info", meta: renderRuntimeValue(item.value, "-") })) : [];
      const signalItems = signals.map((signal) => `${signal.signal || signal.name || "signal"} / ${signal.status || "unknown"} / conf=${renderRuntimeValue(signal.confidence)} / ttl=${renderRuntimeValue(signal.expires_at)}`);
      const artifactRows = evidence.artifacts && typeof evidence.artifacts === "object" ? Object.entries(evidence.artifacts).map(([key, value]) => `${key} / ${renderRuntimeValue(value)}`) : [];
      const liveFrameReady = Boolean(liveFrame.data_url) || ((visionRuntimeStatus() && visionRuntimeStatus().status) === "running");
      return `
        ${renderDashboardCard("Live Observation", `
          ${renderVisionRuntimeControls(liveFrame, liveProfile)}
          ${renderVisionLiveFrameEvidence(liveFrame, liveProfile)}
          ${renderVisionCardDetails("Inspection details", `
            <div class="ar-vis-two-up">
              <section>${renderVisionInspectionFeed(inspectionFeed)}</section>
              <section>${renderVisionSegmentationPanels(segmentation)}</section>
            </div>
          `)}
        `, { span: 4, tone: liveFrameReady ? "success" : "warning", eyebrow: "camera frame", action: renderVisionRuntimeHeaderActions() })}
        ${renderDashboardCard("Active Cam Ejection", renderVisionActiveCamEjectionCheck(screenReport, latestActiveCamArtifact(report), activeCamIntervention, utmScope.previews?.active_cam), { span: 4, tone: activeCamConfirmed ? "success" : "warning", eyebrow: "SPC confirmation" })}
        ${renderDashboardCard("UTM Verification", utmVerificationBody, { span: 4, tone: selectedUtmVerification.confirmed ? "success" : "warning", eyebrow: selectedUtmVerification.title, action: renderVisionUtmVerificationTabs(utmScope, selectedUtmVerification.index), className: "ar-vis-utm-verification-card" })}
        ${renderDashboardCard("Camera / Runtime", `
          ${renderVisionCameraRuntimeSummary(screenReport, visionReport, liveFrame, liveProfile)}
          ${renderVisionCardDetails("Runtime graph details", `${renderVisionCameraHealthBoard(screenReport, visionReport, liveFrame, liveProfile)}${renderVisionRuntimeNodeFlow()}`)}
        `, { span: 4, tone: (visionRuntimeStatus() && visionRuntimeStatus().status) === "running" ? "success" : "vision", eyebrow: "device bridge" })}
        ${renderDashboardCard("Handoff Signal", `
          ${renderVisionHandoffSignal(screenReport, packet)}
          ${renderVisionCardDetails("Evidence and signal details", `${renderVisionEvidenceReviewBoard(evidence, liveFrame, packet)}${dashboardList(signalItems, "No bounded vision signals recorded.", 5)}`)}
        `, { span: 4, tone: /ready/i.test(String((screenReport.handoff_recommendations || {}).status || packet.status || "")) ? "success" : "warning", eyebrow: "bounded signal" })}
        ${renderDashboardCard("Agentic Progress", `
          ${renderVisionAgenticProgress(screenReport, visionReport, packet, liveFrame)}
          ${renderVisionCardDetails("Quality and evidence details", `
          <div class="ar-report-metrics">
            ${renderDashboardMetric("Transfer", quality.transfer_ready === undefined ? "-" : quality.transfer_ready, "ready", quality.transfer_ready ? "success" : "warning")}
            ${renderDashboardMetric("Anomaly", defectSummary.anomaly === undefined ? anomaly.anomaly : defectSummary.anomaly, "vision", defectSummary.anomaly ? "warning" : "success")}
            ${renderDashboardMetric("TTL", quality.freshness_ttl_ms || "-", "ms", "info")}
          </div>
          <div class="ar-vis-two-up">
            <section>
              <h5>Defects</h5>
              ${renderDashboardRows([
                ["low_confidence", defectSummary.low_confidence === undefined ? anomaly.low_confidence || "-" : defectSummary.low_confidence],
                ["occlusion", defectSummary.occlusion === undefined ? anomaly.occlusion || "-" : defectSummary.occlusion],
                ["blocking_reason", defectSummary.blocking_reason || anomaly.blocking_reason || quality.blocking_reason || "-"],
                ["failure_labels", defectSummary.failure_labels || []],
              ])}
            </section>
            <section>
              <h5>Confusion</h5>
              ${renderVisionConfusionMatrix(confusion)}
            </section>
          </div>
          ${renderDashboardRows([
            ["x_mm", pose.x_mm || "-"],
            ["y_mm", pose.y_mm || "-"],
            ["z_mm", pose.z_mm || "-"],
            ["evidence_refs", Array.isArray(evidence.evidence_refs) ? evidence.evidence_refs.length : 0],
            ["zone_count", zones && typeof zones === "object" ? Object.keys(zones).length : 0],
          ])}
          ${dashboardList(artifactRows, "No visual evidence artifacts recorded.", 6)}
          ${calibrationRows.length ? renderMiniBarChart(calibrationRows, { label: "vision calibration trend", compact: true, emptyText: "No calibration trend data recorded." }) : ""}
          `)}
        `, { span: 4, tone: defectSummary.anomaly || !quality.transfer_ready ? "warning" : "success", eyebrow: "runtime steps" })}
      `;
    }
    function dispose() {}
    return Object.freeze({renderReport, renderDashboard, dispose});
  }
  global.AX4LABVisionUI = Object.freeze({createFrontend});
})(window);
