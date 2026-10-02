/* Manipulation-owned composition; telemetry, polling and viewer lifecycle remain in the shared host. */
(function installManipulationLiveReport(global) {
  "use strict";
  function createFrontend(services) {
    const {latestManipulationReport, latestRobotTaskResult, runtimeRows, renderReportList, renderDashboardCard, escapeHtml} = services;
    function renderReport(report) {
      const manipulationReport = latestManipulationReport(report);
      if (!manipulationReport || typeof manipulationReport !== "object") return "";
      const packet = latestRobotTaskResult(report) || manipulationReport.handoff_packet || {};
      const task = manipulationReport.task || {};
      const policy = manipulationReport.policy_plan || {};
      const preflight = manipulationReport.preflight || {};
      const vision = manipulationReport.vision_context || {};
      const runtime = manipulationReport.rollout_runtime || {};
      const stage = manipulationReport.stage_machine || {};
      const decision = manipulationReport.decision || {};
      const knowledge = manipulationReport.knowledge_payload || {};
      const blockers = [...(preflight.blocking_reasons || []), ...(preflight.warnings || [])];
      const completedStages = Array.isArray(stage.completed_stages) ? stage.completed_stages : [];
      const taxonomy = Array.isArray(stage.stage_taxonomy) ? stage.stage_taxonomy : [];
      const runtimeEvents = Array.isArray(runtime.events) ? runtime.events.slice(-8).map((event) => `${event.step || event.event_type || "event"} · ${event.status || "-"}${event.detail ? ` · ${event.detail}` : ""}`) : [];
      const evidencePaths = Array.isArray(knowledge.evidence_paths) ? knowledge.evidence_paths : Array.isArray(packet.evidence_refs) ? packet.evidence_refs.map((ref) => ref.path || ref.type || JSON.stringify(ref)) : [];
      return `
        <div class="live-agent-specific-manipulation-details">
          <h5>Skill Episode Board</h5>
          ${runtimeRows([
            ["task_id", task.task_id || packet.task_id || "-"],
            ["skill_id", packet.skill_id || task.task_id || "-"],
            ["episode_id", packet.episode_id || manipulationReport.session_id || "-"],
            ["specimen_id", task.specimen_id || packet.specimen_id || "-"],
            ["route", `${task.source_location || "-"} -> ${task.target_location || "-"}`],
            ["terminal_pose", packet.terminal_pose || task.intended_terminal_pose || "-"],
          ])}
          <h5>Policy Runtime</h5>
          ${runtimeRows([
            ["policy_backend", policy.policy_backend || "-"],
            ["policy_type", policy.policy_type || "-"],
            ["policy_ref", policy.policy_ref || "-"],
            ["device", policy.device || "-"],
            ["inference", policy.inference_type || "-"],
            ["rtc_horizon", policy.rtc_execution_horizon === undefined ? "-" : policy.rtc_execution_horizon],
            ["rtc_guidance", policy.rtc_max_guidance_weight === undefined ? "-" : policy.rtc_max_guidance_weight],
            ["max_duration_s", policy.max_duration_s === undefined ? "-" : policy.max_duration_s],
          ])}
          <h5>Preflight / Vision Dependency</h5>
          ${runtimeRows([
            ["preflight_status", preflight.status || "-"],
            ["robot_ready", preflight.robot_ready === undefined ? "-" : preflight.robot_ready],
            ["camera_ready", preflight.camera_ready === undefined ? "-" : preflight.camera_ready],
            ["policy_ready", preflight.policy_ready === undefined ? "-" : preflight.policy_ready],
            ["operator_confirmed", preflight.operator_confirmed === undefined ? "-" : preflight.operator_confirmed],
            ["vision_observation", vision.observation_id || "-"],
            ["vision_freshness", vision.freshness && vision.freshness.reason ? vision.freshness.reason : "-"],
            ["pickup_ready", vision.pickup_target_ready === undefined ? "-" : vision.pickup_target_ready],
            ["fixture_visible", vision.fixture_visible === undefined ? "-" : vision.fixture_visible],
          ])}
          <h5>Blocking / Warning Signals</h5>
          ${renderReportList(blockers, "No Manipulation preflight blockers recorded.", 16)}
          <h5>Task Stages</h5>
          ${runtimeRows([
            ["current_stage", stage.current_stage || "-"],
            ["completed", `${completedStages.length}/${taxonomy.length || "?"}`],
          ])}
          <h5>Rollout Runtime / Evidence</h5>
          ${runtimeRows([
            ["tool", runtime.tool || "-"],
            ["status", runtime.status || "-"],
            ["session_id", runtime.session_id || "-"],
            ["duration_s", runtime.duration_s === undefined ? "-" : runtime.duration_s],
            ["handoff", packet.handoff_status || decision.handoff_status || "-"],
            ["next_agent", packet.next_action || decision.recommended_next_agent || "-"],
            ["reason", decision.reason || "-"],
          ])}
          ${renderReportList(runtimeEvents, "No rollout event trace recorded.", 12)}
          <h5>Knowledge / Dataset Evidence</h5>
          ${renderReportList(evidencePaths, "No rollout evidence path recorded.", 12)}
        </div>
      `;
    }

    function renderManipulationTelemetryCards() {
      const jointOptions = ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper"]
        .map((joint) => `<option value="${joint}"${joint === "Gripper" ? " selected" : ""}>${joint}</option>`)
        .join("");
      const motionStates = ["home", "moving", "grasping", "ungrasping"];
      const motionSummary = (channel, label) => `
        <div class="ar-man-motion-summary" data-atr-motion-summary="${channel}">
          <small><i aria-hidden="true"></i>${label}</small>
          <strong data-atr-motion-current>waiting</strong>
          <span data-atr-motion-confidence>0%</span>
        </div>
      `;
      const homeRanges = [
        ["Joint1"], ["Joint2"], ["Joint3"],
        ["Joint4"], ["Joint5"], ["Gripper"],
      ];
      const poseFitAction = `
        <button type="button" class="ar-man-pose-fit" data-atr-pose-fit aria-label="Zoom to fit" title="Zoom to fit">
          FIT
        </button>
      `;
      return `
        ${renderDashboardCard("Live Robot Pose", `
          <div class="ar-man-telemetry-head">
            <div>
              <strong>Follower joint state</strong>
              <small>Measured pose from the existing rollout action log</small>
              <div class="ar-man-robot-motion-label">
                <span>Robot motion state :</span>
                <strong data-atr-robot-motion-state data-state="waiting">waiting</strong>
              </div>
            </div>
            <span class="ar-man-telemetry-status" data-atr-robot-pose-status data-tone="idle">idle</span>
          </div>
          <div class="ar-man-pose-viewer" data-atr-robot-pose role="img" aria-label="Live OMX measured follower pose and translucent policy target pose">
            <span>Loading repository OMX model...</span>
          </div>
          <div class="ar-man-pose-legend" aria-label="robot pose legend">
            <span><i class="measured"></i>Measured follower</span>
            <span><i class="target"></i>Policy target ghost</span>
          </div>
        `, { span: 6, tone: "manipulation", eyebrow: "measured joints + policy target", action: poseFitAction, data: { "live-preserve": "manipulation-pose" } })}
        ${renderDashboardCard("Policy Tracking", `
          <div class="ar-man-telemetry-head">
            <label class="ar-man-joint-selector">Joint selector
              <select data-atr-joint-selector aria-label="Joint selector">${jointOptions}</select>
            </label>
            <span class="ar-man-telemetry-status" data-atr-policy-status data-tone="idle">idle</span>
          </div>
          <div class="ar-man-policy-chart" data-atr-policy-tracking role="img" aria-label="Measured follower and policy target joint position over elapsed time"></div>
          <footer class="ar-man-policy-artifacts" aria-label="Policy tracking artifacts">
            <strong>Policy tracking artifacts</strong>
            <a data-atr-policy-artifact="png" aria-disabled="true">PNG</a>
            <a data-atr-policy-artifact="csv" aria-disabled="true">CSV</a>
            <a data-atr-policy-artifact="jsonl" aria-disabled="true">JSONL</a>
            <a data-atr-policy-artifact="summary" aria-disabled="true">Summary</a>
          </footer>
        `, { span: 6, tone: "metrics", eyebrow: "actual versus requested action", data: { "live-preserve": "manipulation-policy" } })}
        ${renderDashboardCard("Motion & Grasp", `
          <div class="ar-man-motion-state" data-atr-motion-state>
            <section class="ar-man-motion-unified">
              <header class="ar-man-motion-legend">
                ${motionSummary("measured", "Measured follower")}
                ${motionSummary("policy", "Policy target")}
              </header>
              <div class="ar-man-motion-segments" role="list" aria-label="Measured follower and policy target motion states">
                ${motionStates.map((state) => `<span role="listitem" data-motion-state="${state}">${state}</span>`).join("")}
              </div>
              <div class="ar-man-motion-reasons">
                <p data-atr-motion-reason="measured">Waiting for measured joint telemetry.</p>
                <p data-atr-motion-reason="policy">Waiting for policy target telemetry.</p>
              </div>
            </section>
            <section class="ar-man-grasp-outcome" data-atr-grasp-outcome data-status="idle">
              <header>
                <div>
                  <small>Grasp Achievement · This Transfer</small>
                  <strong data-atr-grasp-status>idle</strong>
                </div>
                <p data-atr-grasp-reason>Waiting for a measured grasp attempt.</p>
              </header>
              <p data-atr-grasp-result-scope>No contact success recorded yet. Final transfer requires vision verification.</p>
              <div class="ar-man-visible-section"><h5>Grasp diagnostics</h5><div class="ar-man-grasp-evidence ar-man-grasp-single-column" role="list" aria-label="First successful grasp evidence, or latest attempt before success">
                <div role="listitem"><small>Measured</small><strong data-atr-grasp-measured>-</strong></div>
                <div role="listitem"><small>Policy target</small><strong data-atr-grasp-target>-</strong></div>
                <div role="listitem"><small>Contact gap</small><strong data-atr-grasp-gap>- / 2.00</strong></div>
                <div role="listitem"><small>Transport overlap</small><strong data-atr-grasp-overlap>no</strong></div>
                <div role="listitem"><small>Latest closing diagnostic</small><strong data-atr-grasp-latest-attempt>—</strong></div>
              </div></div>
            </section>
            <section class="ar-man-home-gate" data-atr-home-gate>
              <header>
                <div><small>Home Gate</small><strong>0.5 s stable dwell</strong></div>
                <span data-atr-home-status data-tone="waiting">waiting</span>
              </header>
              <div class="ar-man-visible-section"><h5>Home thresholds</h5><div class="ar-man-home-grid" role="list" aria-label="Home joint thresholds">
                ${homeRanges.map(([joint, minimum, maximum]) => `
                  <div role="listitem" data-home-joint="${joint}" data-pass="waiting">
                    <strong>${joint}</strong>
                    <span data-home-value>-</span>
                    <small data-home-range>Waiting for thresholds</small>
                  </div>
                `).join("")}
              </div></div>
            </section>
          </div>
        `, { span: 12, tone: "manipulation", eyebrow: "home / moving + grasping / ungrasping", data: { "live-preserve": "manipulation-motion" } })}
      `;
    }

    function renderManipulationRuntimeRow(label, field, section) {
      return `
        <div class="ar-man-runtime-row">
          <span>${escapeHtml(label)}</span>
          <strong data-atr-runtime-field="${escapeHtml(section)}.${escapeHtml(field)}">-</strong>
        </div>
      `;
    }

    function renderManipulationGroundedRuntimeCards() {
      const executionFields = [
        ["Run", "run_id"],
        ["Rollout", "rollout_session_id"],
        ["Task", "task_id"],
        ["Instruction", "task_instruction"],
        ["Specimen", "specimen_id"],
        ["Route", "source_location"],
        ["Target", "target_location"],
        ["Policy", "policy_type"],
        ["Checkpoint", "policy_checkpoint_path"],
        ["PID", "process_pid"],
        ["Runtime", "runtime_status"],
        ["Stage", "current_stage"],
        ["Started", "started_at"],
        ["Elapsed", "elapsed_s"],
      ];
      const interlocks = [
        ["follower_port_lease", "Follower port"],
        ["camera_lease", "Camera lease"],
        ["policy_process", "Policy process"],
        ["measured_home", "Measured home"],
        ["emergency_stop", "E-stop"],
        ["safe_stop", "Safe stop"],
        ["vision_pickup", "Vision pickup"],
        ["workspace_clear", "Workspace clear"],
      ];
      const completionSteps = [
        ["ungrasping_seen", "Release observed"],
        ["home_after_ungrasping", "Home after release"],
        ["utm_snapshot_requested", "UTM snapshot"],
        ["specimen_detected_at_utm", "Specimen detected"],
        ["ready_to_stop_rollout", "Stop authorized"],
        ["rollout_stop_confirmed", "Rollout stopped"],
        ["ready_for_equipment", "Equipment handoff"],
      ];
      const resultFields = [
        ["Status", "status"],
        ["Failure stage", "failure_stage"],
        ["Reason", "reason"],
        ["Failure code", "failure_code"],
        ["Rollout stop", "rollout_stop_status"],
        ["Vision verification", "vision_verification_status"],
        ["Home return", "home_return_status"],
        ["Next agent", "next_agent"],
        ["Artifact directory", "artifact_directory"],
      ];
      const metricCounts = (kind) => ["attempt_count", "completed_count", "success_count", "failed_count", "pending_count"]
        .map((field) => `<div><small>${escapeHtml(field.replaceAll("_", " "))}</small><strong data-atr-${kind}-${field.replaceAll("_", "-")}>0</strong></div>`)
        .join("");

      const execution = `          <div class="ar-man-runtime-fields" data-atr-runtime-execution>
            ${executionFields.filter(([,field])=>['task_instruction','source_location','target_location','policy_type','runtime_status','elapsed_s'].includes(field)).map(([label, field]) => renderManipulationRuntimeRow(label, field, "execution")).join("")}
          </div>
          <details class="ar-man-details"><summary>Execution details</summary><div class="ar-man-runtime-fields">${executionFields.filter(([,field])=>!['task_instruction','source_location','target_location','policy_type','runtime_status','elapsed_s'].includes(field)).map(([label,field])=>renderManipulationRuntimeRow(label,field,'execution')).join('')}</div></details>`;
      const interlocksBody = `          <div class="ar-man-runtime-gates" data-atr-runtime-interlocks role="list">
            ${interlocks.map(([id, label]) => `<div role="listitem" data-atr-runtime-gate="${id}" data-status="unknown"><i></i><span>${label}</span><strong>unknown</strong><details class="ar-man-details"><summary>Evidence</summary><small></small></details></div>`).join("")}
          </div>`;
      const completion = `          <div class="ar-man-runtime-completion" data-atr-runtime-completion>
            ${completionSteps.map(([id, label], index) => `<div data-atr-runtime-step="${id}" data-status="waiting"><b>${String(index + 1).padStart(2, "0")}</b><span>${label}</span><strong>waiting</strong><small></small></div>`).join("")}
            <div data-utm-clear-verification-step data-status="waiting"><b>08</b><span>UTM Clear &amp; Verification 2</span><strong>waiting</strong><small></small></div>
          </div>`;
      const result = `          <div class="ar-man-runtime-result" data-atr-runtime-result data-status="not_started">
            <div class="ar-man-runtime-result-banner"><strong data-atr-runtime-result-status>NOT STARTED</strong><span data-atr-runtime-result-terminal>live state</span></div>
            <div class="ar-man-runtime-fields">${resultFields.filter(([,field])=>['reason','next_agent'].includes(field)).map(([label, field]) => renderManipulationRuntimeRow(label, field, "result")).join("")}</div>
            <div class="ar-man-visible-section"><h5>Result evidence</h5><div class="ar-man-runtime-fields">${resultFields.filter(([,field])=>!['reason','next_agent'].includes(field)).map(([label, field]) => renderManipulationRuntimeRow(label, field, "result")).join("")}</div></div>
          </div>`;
      const metrics = `          <div class="ar-man-runtime-metrics ar-man-metrics-compact" data-atr-runtime-metrics>
            <section>
              <div class="ar-man-runtime-donut" data-atr-runtime-donut="task" style="--rate:0%;"><div><strong data-atr-task-success-rate>—</strong><span>Task Success Rate</span></div></div>
              <div class="ar-man-runtime-counts">${metricCounts("task")}</div>
            </section>
            <section>
              <div class="ar-man-runtime-donut" data-atr-runtime-donut="grasp" style="--rate:0%;"><div><strong data-atr-grasp-success-rate>—</strong><span>Grasp Attempt Success Rate</span></div></div>
              <div class="ar-man-runtime-counts">${metricCounts("grasp")}</div>
            </section>
            <div class="ar-man-runtime-measures">
              ${renderManipulationRuntimeRow("Samples", "sample_count", "metrics")}
              ${renderManipulationRuntimeRow("Duration", "duration_s", "metrics")}
              ${renderManipulationRuntimeRow("Action rate", "effective_action_rate_hz", "metrics")}
              ${renderManipulationRuntimeRow("Vision latency", "post_place_verification_latency_s", "metrics")}
              ${renderManipulationRuntimeRow("Stop latency", "stop_latency_s", "metrics")}
            </div>
          </div>`;
      return renderDashboardCard("Completion & Handoff", `
        <div class="ar-man-completion-summary">${completion}${result}</div>
      `, {span:12, tone:"manipulation", eyebrow:"verification + outcome", data:{"live-preserve":"manipulation-completion-summary"}})
      + renderDashboardCard("Run Metrics", metrics, {span:4, tone:"metrics", eyebrow:"run statistics", className:"ar-man-small-metrics", data:{"live-preserve":"manipulation-metrics"}})
      + renderDashboardCard("Runtime Execution", execution, {span:4, tone:"manipulation", eyebrow:"task + process", data:{"live-preserve":"manipulation-execution"}})
      + renderDashboardCard("Interlocks", interlocksBody, {span:4, tone:"manipulation", eyebrow:"readiness", data:{"live-preserve":"manipulation-interlocks"}});
    }

    function renderDashboard(report, status, agentLabel, profile) {
      return `${renderManipulationTelemetryCards()}${renderManipulationGroundedRuntimeCards()}`;
    }
    function dispose() {}
    return Object.freeze({renderReport, renderDashboard, dispose});
  }
  global.AX4LABManipulationUI = Object.freeze({createFrontend});
})(window);
