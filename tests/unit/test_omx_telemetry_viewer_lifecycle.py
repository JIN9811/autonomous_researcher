from pathlib import Path


SOURCE_PATH = Path("web/frontend/omx_telemetry_viewer/src/index.js")
PLANNING_PATH = Path("web/static/planning.js")


def test_viewer_initialization_is_single_flight_across_report_remounts() -> None:
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert "viewerPromise: null" in source
    assert "async function ensureViewer()" in source
    assert "runtime.viewerPromise = createViewer()" in source
    assert "const viewer = await ensureViewer();" in source
    assert "runtime.viewer = await createViewer()" not in source


def test_live_report_updates_in_place_and_preserves_telemetry_surfaces() -> None:
    source = PLANNING_PATH.read_text(encoding="utf-8")

    assert "function patchLiveReportNode(" in source
    assert "function updateLiveReportPanel(" in source
    assert "updateLiveReportPanel(reportHtml, reportContextKey)" in source
    assert '"live-preserve": "manipulation-pose"' in source
    assert '"live-preserve": "manipulation-policy"' in source
    assert '"live-preserve": "manipulation-motion"' in source
    assert "liveReportPanel.innerHTML = reportHtml" not in source


def test_terminal_grasp_artifact_hydration_does_not_rewrite_unchanged_dom_text() -> None:
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert "function setNodeTextIfChanged(node, value)" in source
    assert "if (node.textContent === text) return false;" in source
    assert "setNodeTextIfChanged(statusNode, status);" in source
    assert "setNodeTextIfChanged(reasonNode, reason);" in source
    assert "setNodeTextIfChanged(measuredNode, formatNativeValue(value.measured_gripper));" in source
    assert "setNodeTextIfChanged(targetNode, formatNativeValue(value.policy_target_gripper));" in source
    assert "setNodeTextIfChanged(gapNode, `${gap} / ${threshold}`);" in source
    assert 'setNodeTextIfChanged(overlapNode, value.transport_overlap ? "yes" : "no");' in source


def test_held_specimen_follows_gripper_with_world_yaw_only() -> None:
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert "function syncHeldSpecimenPose(viewer = runtime.viewer)" in source
    assert 'setFromQuaternion(anchorWorldQuaternion, "ZYX").z' in source
    assert "desiredWorldQuaternion.setFromAxisAngle(WORLD_UP_AXIS, yaw);" in source
    assert "viewer.environmentGroup.worldToLocal(anchorWorldPosition);" in source
    assert "syncHeldSpecimenPose();" in source


def test_new_pending_grasp_attempt_reacquires_released_specimen() -> None:
    source = SOURCE_PATH.read_text(encoding="utf-8")

    pending_branch = source.split('if (status === "pending" && attemptIndex !== state.attemptIndex) {', 1)[1]
    pending_branch = pending_branch.split("return true;", 1)[0]
    assert "attachSpecimenToGripper(viewer);" in pending_branch
