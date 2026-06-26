"""Static checks for the UTM Runtime Device Workspace UI wiring."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_main_gui_declares_utm_runtime_workspace_card() -> None:
    html = (ROOT / "web/templates/index.html").read_text(encoding="utf-8")

    assert "/device-bridge/vision-utm" in html
    assert "Vision / UTM Camera Bridge" in html
    assert 'id="btn-open-vision-utm-bridge"' in html
    assert 'id="btn-open-vision-utm-bridge" class="btn primary" href="/device-bridge/vision-utm" target="_blank"' in html
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
    assert "Operator Review / Evidence" in js
    assert "Camera Health" in js
    assert "LIVE_UTM_GRAPH_REFRESH_INTERVAL_MS" in js
    assert "refreshLiveUtmRuntimeFrame" in js
    assert "utmRuntimeFrameStreamUrl" in js
    assert "utmRuntimeLiveStreamTopic" in js
    assert "profile.ros_output_topic || profile.ros_rect_topic || profile.ros_image_topic" in js
    assert "liveUtmRuntimeStreamUrlCache" in js
    assert "liveUtmRuntimeStreamUrlKey" in js
    assert "function liveUtmRuntimeStreamVisible()" in js
    assert "if (liveUtmRuntimeStreamVisible()) return;" in js
    assert "const shouldFetchFrame = !liveUtmRuntimeStreamVisible()" in js
    assert "Date.now()" not in js[js.index("function utmRuntimeFrameStreamUrl"):js.index("function renderVisionLiveFrameEvidence")]
    assert "refreshLiveUtmRuntimeStatus({ render: true })" in js
    assert "await Promise.allSettled([refreshLiveGraphPayload(), refreshLiveUtmRuntimeStatus()])" not in js


def test_vision_utm_device_bridge_page_wires_camera_api() -> None:
    html = (ROOT / "web/templates/vision_utm_device_bridge.html").read_text(encoding="utf-8")
    js = (ROOT / "web/static/vision_utm_device_bridge.js").read_text(encoding="utf-8")

    assert "Vision Camera Device Bridge" in html
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
    assert "frameStreamTimer" in js
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
    assert "await asyncio.to_thread(next_chunk)" in main_py
    assert "close = getattr(source, \"close\", None)" in main_py
    assert '"X-Accel-Buffering": "no"' in main_py
    assert '"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"' in main_py
    assert '"/api/equipment/utm-runtime/camera/cleanup"' in main_py
    assert "return _utm_runtime_bridge().cleanup_ports" in main_py


def test_utm_runtime_mjpeg_stream_allows_camera_timer_jitter() -> None:
    bridge_py = (ROOT / "device_bridges/utm_runtime_bridge.py").read_text(encoding="utf-8")

    assert "emit_interval_tolerance = 0.80" in bridge_py
    assert "rate_limit_enabled = fps < 15.0" in bridge_py
    assert "min_interval * emit_interval_tolerance" in bridge_py
