"""Static checks for the UTM Runtime Device Workspace UI wiring."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_main_gui_declares_utm_runtime_workspace_card() -> None:
    html = (ROOT / "web/templates/index.html").read_text(encoding="utf-8")

    assert "/device-bridge/vision-utm" in html
    assert 'id="btn-open-vision-utm-bridge"' in html
    # The launcher is a workspace card now; it still owns the same target page.
    assert ('id="btn-open-vision-utm-bridge" class="workspace-launch" '
            'href="/device-bridge/vision-utm" target="_blank"') in html
    assert "<strong>Vision</strong><small>Workspace</small>" in html
    assert "utm-runtime-workspace-dot" not in html
    assert "btn-utm-runtime-load" not in html
    assert "btn-utm-runtime-stop" not in html
    assert "UTM ROS System" not in html
    assert "RQT flow from cloned UTM program" not in html


def test_main_gui_js_does_not_own_utm_runtime_controls() -> None:
    js = (ROOT / "web/static/app.js").read_text(encoding="utf-8")

    assert "safeBootstrapStep" in js
    assert "refreshUtmRuntimeWorkspaceStatus" not in js
    assert "postUtmRuntimeAction" not in js
    assert "btnUtmRuntimeLoad" not in js
    assert "refreshUtmRuntimeWorkspaceStatus({ includeGraph" not in js
    assert "renderUtmRuntimeFrameSummary" not in js
    assert "utm-rqt-flow" not in js


def test_live_gui_js_renders_utm_runtime_device_card() -> None:
    js = (ROOT / "web/static/planning.js").read_text(encoding="utf-8")
    vision_module = (ROOT / "agents/vision/frontend/live_report.js").read_text(encoding="utf-8")
    js += "\n" + vision_module

    assert "renderUtmRuntimeDeviceCard" in js
    assert "refreshLiveUtmRuntimeStatus" in js
    assert "/api/equipment/utm-runtime/status" in js
    assert "/api/equipment/utm-runtime/camera-config" in js
    assert "/api/equipment/utm-runtime/graph" in js
    assert "/api/equipment/utm-runtime/frame" in js
    assert "/api/equipment/utm-runtime/frame-stream.mjpeg" in js
    assert "cloned UTM program" in js
    assert "live-utm-rqt-flow" in js
    assert "green_dot" in js
    assert "renderVisionLiveFrameEvidence" in js
    assert 'renderDashboardCard("Live Observation"' in js
    assert 'renderDashboardCard("Specimen Pose"' not in js
    assert 'renderDashboardCard("Active Cam Ejection"' in js
    assert 'renderDashboardCard("UTM Verification"' in js
    assert 'renderDashboardCard("Camera / Runtime"' in js
    assert 'renderDashboardCard("Handoff Signal"' in js
    assert 'renderDashboardCard("Agentic Progress"' in js
    vision_dashboard_source = vision_module[vision_module.index("function renderDashboard("):]
    assert "function renderVisionActiveCamEjectionCheck(" in js
    assert "function latestActiveCamArtifact(report)" in js
    assert "metadata.latest_active_cam_artifact" in js
    assert "function canonicalActiveCamEvidence(" in js
    assert "function renderVisionActiveCamEjectionCheck(screenReport, persistedArtifact" in js
    active_cam_source = js[js.index("function renderVisionActiveCamEjectionCheck("):js.index("function renderVisionDashboardCards")]
    assert 'const failed = /failed|blocked|error/i.test(String(status));' in active_cam_source
    assert "let evidence = canonicalActiveCamEvidence(active, persistedArtifact, intervention);" in active_cam_source
    assert 'evidence.status === "confirmed"' in active_cam_source
    assert "const detected = !failed && evidence.specimen_detected === true;" in active_cam_source
    assert "evidence.confidence" in active_cam_source
    assert "function visionSpecimenPlacementLabel(" in js
    assert 'renderDashboardMetric("Placement", placementLabel' in active_cam_source
    assert 'const capturePath = evidence.path || evidence.capture_path || "";' in active_cam_source
    assert 'const captureUrl = evidence.url || evidence.capture_url' in active_cam_source
    assert 'const capturePath = failed ? ""' not in active_cam_source
    assert 'const captureUrl = failed' not in active_cam_source
    # A fourth argument carries the pending capture preview into the card.
    assert ('renderVisionActiveCamEjectionCheck(screenReport, latestActiveCamArtifact(report), '
            'activeCamIntervention, utmScope.previews?.active_cam)') in js
    assert 'const activeCamConfirmed = activeCamCheck.status === "confirmed"' in vision_dashboard_source
    assert "function latestUtmCompletionArtifact(report)" in js
    assert "metadata.latest_utm_completion_artifact" in js
    utm_artifact_source = js[js.index("function latestUtmCompletionArtifact(report)"):js.index("function latestVisionSignalPacket(report)")]
    assert "artifact.run_id" in utm_artifact_source
    assert "artifact.session_id" in utm_artifact_source
    assert "artifact.specimen_id" in utm_artifact_source
    assert "return {};" in utm_artifact_source
    assert "function renderVisionUtmPlacementConfirmation(" in js
    assert "utmVerificationScope(report)" in vision_dashboard_source
    assert "selectVerification(utmScope, utmSelection.index)" in vision_dashboard_source
    assert 'id: "utm_confirmation"' in js
    assert 'renderVisionCardDetails("Inspection details"' in active_cam_source
    assert 'class="ar-vis-active-cam-details"' not in active_cam_source
    assert "<h5>Inspection details</h5>" not in active_cam_source
    assert '["status", status]' in active_cam_source
    assert '["capture_path", capturePath || "-"]' in active_cam_source
    assert 'id: "active_cam"' in js
    assert 'data-vision-runtime-action="start"' in js
    assert 'data-vision-runtime-action="stop"' in js
    assert "runLiveUtmRuntimeAction(visionRuntimeAction.dataset.visionRuntimeAction || \"\", visionRuntimeAction)" in js
    assert 'fetchJsonOrThrow("/api/equipment/utm-runtime/start", { method: "POST" })' in js
    assert 'fetchJsonOrThrow("/api/equipment/utm-runtime/stop", { method: "POST" })' in js
    assert 'span: 4, tone: liveFrameReady ? "success" : "warning", eyebrow: "camera frame"' in js
    assert 'span: 4, tone: activeCamConfirmed ? "success" : "warning", eyebrow: "SPC confirmation"' in js
    assert 'span: 4, tone: "vision", eyebrow: "pose gate"' not in js
    assert 'span: 4, tone: (visionRuntimeStatus() && visionRuntimeStatus().status) === "running" ? "success" : "vision", eyebrow: "device bridge"' in js
    assert 'span: 4, tone: defectSummary.anomaly || !quality.transfer_ready ? "warning" : "success", eyebrow: "runtime steps"' in js
    assert vision_dashboard_source.index('renderDashboardCard("UTM Verification"') < vision_dashboard_source.index('renderDashboardCard("Camera / Runtime"')
    assert vision_dashboard_source.index('renderDashboardCard("Camera / Runtime"') < vision_dashboard_source.index('renderDashboardCard("Handoff Signal"')
    assert vision_dashboard_source.index('renderDashboardCard("Handoff Signal"') < vision_dashboard_source.index('renderDashboardCard("Agentic Progress"')
    for cluttered_card in [
        'renderDashboardCard("Perception Bus"',
        'renderDashboardCard("Scene Understanding"',
        'renderDashboardCard("Quality Gate"',
        'renderDashboardCard("Operator Review / Evidence"',
        'renderDashboardCard("Evidence Ledger"',
    ]:
        assert cluttered_card not in js
    assert "LIVE_UTM_GRAPH_REFRESH_INTERVAL_MS" in js
    assert "refreshLiveUtmRuntimeFrame" in js
    assert "utmRuntimeFrameStreamUrl" in js
    assert "utmRuntimeLiveStreamTopic" in js
    assert 'const liveFrameReady = Boolean(liveFrame.data_url) || ((visionRuntimeStatus() && visionRuntimeStatus().status) === "running")' in js
    assert "profile.ros_output_topic || profile.ros_rect_topic || profile.ros_image_topic" in js
    assert "liveUtmRuntimeStreamUrlCache" in js
    assert "liveUtmRuntimeStreamUrlKey" in js
    assert "LIVE_UTM_PREVIEW_FPS = 30" in js
    assert "/api/equipment/utm-runtime/frame-stream/status" in js
    assert "function liveUtmRuntimeStreamVisible()" in js
    assert "if (liveUtmRuntimeStreamVisible()) return;" in js
    assert "const shouldFetchFrame = !liveUtmRuntimeStreamVisible()" in js
    assert "Date.now()" not in js[js.index("function utmRuntimeFrameStreamUrl"):js.index("function renderVisionLiveFrameEvidence")]
    assert "refreshLiveUtmRuntimeStatus({ render: true })" in js
    assert "await Promise.allSettled([refreshLiveGraphPayload(), refreshLiveUtmRuntimeStatus()])" not in js

    css = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")
    active_cam_css = css[css.index("body.planning-live-body .ar-vis-active-cam-frame {"):css.index("body.planning-live-body .ar-vis-active-cam-frame > div")]
    assert "aspect-ratio: 4 / 3" in active_cam_css
    assert "object-fit: contain" in active_cam_css
    assert "object-fit: cover" not in active_cam_css
    assert ".ar-vis-active-cam-details" not in css

    html = (ROOT / "web/templates/planning.html").read_text(encoding="utf-8")
    assert "/static/styles.css?v=" in html
    assert "/static/planning.js?v=" in html
    assert "const detected = artifact.detected === true;" in js
    assert "artifact.detected === true || signal.detected === true" not in js


def test_live_gui_vision_specimen_intervention_actions_are_run_scoped() -> None:
    js = (ROOT / "web/static/planning.js").read_text(encoding="utf-8")

    assert "function renderVisionSpecimenIntervention(" in js
    assert "Place the specimen into the working area" in js
    assert "Checking specimen..." in js
    assert "data-vision-specimen-retry" in js
    assert "data-vision-specimen-deadline" in js
    assert "/vision/specimen-placement-retry" in js
    assert 'checkpoint: "active_cam_ejection"' in js
    assert 'checkpoint: "utm_post_place"' in js
    assert "renderVisionSpecimenIntervention(intervention, \"active_cam_ejection\")" in js
    assert "renderVisionSpecimenIntervention(intervention, \"utm_post_place\")" in js


def test_utm_confirmation_card_uses_report_artifact_when_metadata_merge_is_delayed() -> None:
    js = Path("web/static/planning.js").read_text(encoding="utf-8")

    assert "signal.run_artifact" in js
    assert "persistedArtifact : reportArtifact" in js
    assert "artifact.url" in js
    assert "artifact.path" in js


def test_live_gui_utm_runtime_actions_force_fresh_status_after_click() -> None:
    js = (ROOT / "web/static/planning.js").read_text(encoding="utf-8")

    assert "if (!options.force && liveUtmRuntimeRefreshInFlight) return liveUtmRuntimeRefreshInFlight;" in js
    assert "await refreshLiveUtmRuntimeStatus({ render: false, force: true });" in js


def test_live_gui_vision_load_unload_buttons_live_in_observation_header() -> None:
    js = (ROOT / "web/static/planning.js").read_text(encoding="utf-8")
    js += "\n" + (ROOT / "agents/vision/frontend/live_report.js").read_text(encoding="utf-8")
    controls_source = js[js.index("function renderVisionRuntimeControls"):js.index("function renderVisionCameraHealthBoard")]
    live_observation_source = js[js.index('renderDashboardCard("Live Observation"'):js.index('renderDashboardCard("Active Cam Ejection"')]

    assert "function renderVisionRuntimeHeaderActions(" in js
    assert 'class="ar-vis-runtime-actions ar-vis-runtime-actions-header"' in js
    assert "ar-vis-runtime-actions" not in controls_source
    assert "ar-vis-runtime-controls" not in controls_source
    assert "ROS Runtime" not in controls_source
    assert 'action: renderVisionRuntimeHeaderActions()' in live_observation_source


def test_vision_utm_device_bridge_page_wires_camera_api() -> None:
    html = (ROOT / "web/templates/vision_utm_device_bridge.html").read_text(encoding="utf-8")
    js = (ROOT / "web/static/vision_utm_device_bridge.js").read_text(encoding="utf-8")

    assert "<title>Vision Workspace</title>" in html
    assert "<h1>Vision Workspace</h1>" in html
    assert "btn-vision-camera-page-runtime" in html
    assert "btn-vision-camera-page-test" in html
    assert 'data-vision-camera-page-panel="runtime"' in html
    assert 'data-vision-camera-page-panel="test"' in html
    assert "RQT flow from cloned UTM program" in html
    assert "vision-camera-device-path" in html
    assert "btn-vision-camera-precheck" in html
    assert "btn-vision-camera-frame-play" in html
    assert "btn-vision-camera-frame-stop" in html
    assert "vision-camera-frame-stream-status" in html
    assert 'id="vision-camera-preview-fps"' in html
    assert 'value="30"' in html
    assert "Camera FPS" in html
    assert "btn-vision-camera-calibrate" in html
    assert "Specimen Pose Test" in html
    assert "btn-vision-pose-status" in html
    assert "btn-vision-pose-virtual" in html
    assert "btn-vision-pose-d455f" in html
    assert "btn-vision-pose-d405" in html
    assert "btn-vision-pose-release" in html
    assert "vision-pose-result-log" in html
    assert "/static/vision_utm_device_bridge.js" in html
    assert "/api/equipment/utm-runtime/camera-config" in js
    assert "/api/equipment/utm-runtime/camera/devices" in js
    assert "/api/equipment/utm-runtime/camera/probe" in js
    assert "/api/equipment/utm-runtime/camera/calibrate/start" in js
    assert "/api/equipment/utm-runtime/graph" in js
    assert "/api/equipment/utm-runtime/frame" in js
    assert "/api/equipment/utm-runtime/frame-stream.mjpeg" in js
    assert "/api/equipment/utm-runtime/camera/cleanup" in js
    assert "frameStreamTopicLabel" in js
    assert "profile.ros_output_topic || profile.ros_rect_topic || profile.ros_image_topic" in js
    assert "startFrameStream" in js
    assert "stopFrameStream" in js
    assert "selectVisionCameraPage" in js
    assert "atrVisionCameraBridgePage" in js
    assert "/api/vision/specimen-pose/status" in js
    assert "/api/vision/specimen-pose/snapshot" in js
    assert "/api/vision/specimen-pose/release" in js
    assert "/camera/d405/color/image_raw" in js
    assert "/camera/d455f/color/image_raw" in js
    assert "frameStreamUrlCache" in js
    assert "frameStreamUrlKey" in js
    assert "Date.now()" not in js[js.index("function utmRuntimeFrameStreamUrl"):js.index("function frameStreamTopicLabel")]
    assert 'el("vision-camera-preview-fps")' in js
    assert "/api/equipment/utm-runtime/frame-stream/status" in js
    assert "measured_fps" in js
    assert "estimated_dropped_frames" in js
    assert "frameStreamTimer" not in js
    assert "refreshFrameStreamFrame" not in js
    assert "scheduleFrameStreamTick" not in js
    assert "green_dot_monitor" in js
    assert 'document.readyState === "loading"' in js
    assert "BRIO" not in html


def test_utm_runtime_api_offloads_slow_ros_calls_from_event_loop() -> None:
    main_py = (ROOT / "app/main.py").read_text(encoding="utf-8")

    assert "return await asyncio.to_thread(_utm_runtime_bridge().graph" in main_py
    assert "return await asyncio.to_thread(_utm_runtime_bridge().frame" in main_py
    assert '"/api/equipment/utm-runtime/frame-stream.mjpeg"' in main_py
    assert "StreamingResponse(" in main_py
    assert "_utm_runtime_bridge().frame_stream(topic=topic, fps=fps)" in main_py
    assert "request.is_disconnected()" in main_py
    assert "except asyncio.CancelledError:" in main_py
    assert "next_task = asyncio.create_task(asyncio.to_thread(next_chunk))" in main_py
    assert "chunk = await asyncio.shield(next_task)" in main_py
    assert "await next_task" in main_py
    assert '"/api/equipment/utm-runtime/frame-stream/status"' in main_py
    assert "close = getattr(source, \"close\", None)" in main_py
    assert '"X-Accel-Buffering": "no"' in main_py
    assert '"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"' in main_py
    assert '"/api/equipment/utm-runtime/camera/cleanup"' in main_py
    assert "return _utm_runtime_bridge().cleanup_ports" in main_py


def test_utm_runtime_mjpeg_stream_passes_source_frames_without_second_rate_limit() -> None:
    """The worker forwards every source frame; usb_cam already caps the rate.

    A second emit gate here dropped frames the camera had already paced, so the
    requested fps is carried to the worker and the drop logic stays removed.
    """
    bridge_py = (ROOT / "device_bridges/camera_vision/utm_runtime_bridge.py").read_text(encoding="utf-8")
    script = bridge_py[bridge_py.index("ROS_IMAGE_MJPEG_STREAM_SCRIPT"):bridge_py.index("class MjpegStreamSubscriber")]

    assert "fps = max(float(sys.argv[2]), 1.0)" in script
    for dropped in ("emit_interval_tolerance", "should_emit", "emit_tokens", "now - self.last_emit"):
        assert dropped not in script
    assert "self.target_fps = max(float(target_fps), 1.0)" in bridge_py
    assert '"requested_fps": round(self.target_fps, 2)' in bridge_py
    assert '"measured_fps": round(measured_fps, 2)' in bridge_py
