"""Static checks for the LeRobot GUI surface."""

from __future__ import annotations

from pathlib import Path


def test_lerobot_camera_usb_link_badge_is_rendered_from_saved_device_metadata() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")
    styles = Path("web/static/styles.css").read_text(encoding="utf-8")

    assert "function cameraUsbLinkBadge" in script
    assert 'camera.usb_link_label || "USB link unknown"' in script
    assert 'camera.usb_link_status' in script
    assert 'lerobot-camera-usb-link ${status}' in script
    assert "cameraUsbLinkBadge(camera, realsense)" in script
    assert ".lerobot-camera-usb-link.ok" in styles
    assert ".lerobot-camera-usb-link.warning" in styles
    assert ".lerobot-camera-usb-link.unknown" in styles
    assert "/static/styles.css?v=20260715-camera-usb-link-1" in template
    assert "/static/lerobot.js?v=20260903-background-train-1" in template


def test_lerobot_active_robot_cam_controls_and_payload_are_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "Active Robot-Cam specimen tracking" in template
    assert "D405 wrist primary" in template
    assert "D455F top fallback" in template
    assert "lerobot-active-robot-cam-enabled-input" in template
    assert "lerobot-active-robot-cam-record-start-input" in template
    assert 'const activeRobotCamEnabledInput = $("lerobot-active-robot-cam-enabled-input");' in script
    assert "active_robot_cam_enabled: boolValue(activeRobotCamEnabledInput)" in script
    assert "active_robot_cam_record_start_enabled: boolValue(activeRobotCamRecordStartInput)" in script
    assert 'active_robot_cam_camera_priority: "d405,d455f"' in script
    assert 'active_robot_cam_primary_camera_key: "wrist"' in script
    assert 'active_robot_cam_fallback_camera_key: "top"' in script


def test_lerobot_rollout_action_clamp_defaults_off_in_gui() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="lerobot-rollout-action-clamp-input" type="checkbox" checked' not in template
    assert 'id="lerobot-rollout-action-clamp-input" type="checkbox"' in template
    assert "payload.rollout_action_clamp = rolloutActionClampInput ? boolValue(rolloutActionClampInput) : false;" in script


def test_lerobot_rollout_shoulder_lift_backstop_defaults_on_in_gui() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="lerobot-rollout-shoulder-lift-backstop-input" type="checkbox" checked' in template
    assert 'const rolloutShoulderLiftBackstopInput = $("lerobot-rollout-shoulder-lift-backstop-input");' in script
    assert (
        "payload.rollout_shoulder_lift_backstop = rolloutShoulderLiftBackstopInput ? "
        "boolValue(rolloutShoulderLiftBackstopInput) : true;"
    ) in script


def test_lerobot_plc_rollout_stop_checkbox_requires_live_plc_status() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="lerobot-plc-rollout-stop-input" type="checkbox" disabled' in template
    assert 'id="lerobot-plc-rollout-stop-status"' in template
    assert 'const plcRolloutStopInput = $("lerobot-plc-rollout-stop-input");' in script
    assert 'fetch("/api/plc/status"' in script
    assert 'status.connection_state === "online"' in script
    assert "status.plc_layer_active === true" in script
    assert "status.fast_stop_monitor?.running === true" in script
    assert "plcRolloutStopInput.disabled = !available;" in script
    assert "if (!available) plcRolloutStopInput.checked = false;" in script
    assert "payload.plc_rollout_stop_enabled = boolValue(plcRolloutStopInput);" in script


def test_lerobot_rollout_restores_saved_profile_instead_of_selecting_latest() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="btn-rollout-save"' in template
    assert "Save Rollout Defaults" in template
    assert "function applyRolloutProfile" in script
    assert "async function refreshRolloutProfile" in script
    assert 'fetch("/api/lerobot/rollout/config")' in script
    assert 'postJson("/api/lerobot/rollout/config", currentRolloutProfile())' in script
    assert "await refreshPolicies();\n    await refreshRolloutProfile();" in script
    assert "savedPolicyOptionLabel" in script


def test_lerobot_training_progress_uses_sample_count_when_step_is_abbreviated() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "function parseTrainingSampleStep" in script
    assert "(?:smpl|samples|sample)" in script
    assert "parseTrainingEffectiveBatchSize(log, training)" in script
    assert "sampleStep > current" in script


def test_lerobot_background_training_checkbox_defaults_on_and_is_submitted() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="lerobot-train-background-input" type="checkbox" checked' in template
    assert 'const trainBackgroundInput = $("lerobot-train-background-input");' in script
    assert "train_background: trainBackgroundInput ? boolValue(trainBackgroundInput) : true" in script


def test_lerobot_isaac_augmentation_recipe_controls_and_payload_are_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    for element_id in [
        "lerobot-isaac-augment-profile-input",
        "lerobot-isaac-augment-photometric-input",
        "lerobot-isaac-augment-sensor-noise-input",
        "lerobot-isaac-augment-depth-noise-input",
        "lerobot-isaac-augment-render-domain-input",
        "lerobot-isaac-augment-rgb-strength-input",
        "lerobot-isaac-augment-depth-strength-input",
        "lerobot-isaac-augment-render-domain-strength-input",
        "lerobot-isaac-augment-camera-pose-strength-input",
        "lerobot-isaac-augment-exclude-flagged-episodes-input",
    ]:
        assert element_id in template
        assert element_id in script

    assert "standard_sim2real_v2" in template
    assert "isaac_data_augmentation_profile:" in script
    assert "isaac_data_augmentation_photometric_enabled: boolValue(isaacAugmentPhotometricInput)" in script
    assert "isaac_data_augmentation_sensor_noise_enabled: boolValue(isaacAugmentSensorNoiseInput)" in script
    assert "isaac_data_augmentation_depth_noise_enabled: boolValue(isaacAugmentDepthNoiseInput)" in script
    assert "isaac_data_augmentation_render_domain_enabled: boolValue(isaacAugmentRenderDomainInput)" in script
    assert "isaac_data_augmentation_rgb_strength: numberValue(isaacAugmentRgbStrengthInput, 1)" in script
    assert "isaac_data_augmentation_depth_strength: numberValue(isaacAugmentDepthStrengthInput, 1)" in script
    assert "isaac_data_augmentation_render_domain_strength: numberValue(isaacAugmentRenderDomainStrengthInput, 1)" in script
    assert "isaac_data_augmentation_camera_pose_strength: numberValue(isaacAugmentCameraPoseStrengthInput, 1)" in script
    assert "dataset_exclude_flagged_episodes: excludeFlaggedEpisodesValue()" in script
    assert "syncExcludeFlaggedEpisodesCheckboxes" in script


def test_lerobot_isaac_lab_synthetic_controls_and_payload_are_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    for element_id in [
        "isaac-lab-advanced-settings",
        "isaac-synthetic-pipeline-mode",
        "isaac-synthetic-fallback-policy",
        "isaac-synthetic-source-intent",
        "isaac-synthetic-isaac-sim-python",
        "isaac-synthetic-mimic-trials",
        "isaac-synthetic-mimic-num-envs",
        "isaac-synthetic-mimic-backend",
        "isaac-lab-domain-randomization-profile",
        "isaac-synthetic-rl-teacher-steps",
        "isaac-synthetic-check-digital-twin",
        "isaac-synthetic-build",
        "isaac-synthetic-run-replicator-worker",
        "isaac-synthetic-run-replicator-smoke",
        "isaac-synthetic-preview",
        "isaac-synthetic-export-hdf5",
        "isaac-lab-annotate-source",
        "isaac-lab-generate-mimic",
        "isaac-lab-train-il",
        "isaac-lab-eval-il",
        "isaac-lab-run-e2e",
        "isaac-synthetic-run-mimic",
        "isaac-synthetic-run-mimic-smoke",
        "isaac-synthetic-mimic-status",
        "isaac-synthetic-mimic-stop",
        "isaac-synthetic-run-rl-teacher",
        "isaac-synthetic-run-rl-teacher-smoke",
        "isaac-synthetic-rl-teacher-status",
        "isaac-synthetic-rl-teacher-stop",
        "isaac-synthetic-e2e-smoke",
        "isaac-synthetic-status",
        "isaac-synthetic-status-compatibility",
        "isaac-synthetic-status-training-exposure",
        "isaac-synthetic-status-hdf5",
        "isaac-lab-e2e-status-card",
    ]:
        assert element_id in template
        assert element_id in script

    for status_label in [
        "Version Gate",
        "HDF5 Source",
        "Annotation",
        "Mimic Generation",
        "Domain Randomization Profile",
        "Generated Success Import",
        "Isaac Lab IL Training",
        "Isaac Lab IL Evaluation",
        "LeRobot Training Exposure",
    ]:
        assert status_label in script

    assert "Isaac Lab Synthetic Intelligence" in template
    assert "stress eval only" in template
    assert '<option value="official" selected>official Isaac Lab Mimic' in template
    assert '<option value="joint_replay">joint replay</option>' in template
    assert "function isaacSyntheticPayload" in script
    assert 'const isaacSyntheticMimicBackendInput = $("isaac-synthetic-mimic-backend");' in script
    assert 'const isaacSyntheticIsaacSimPythonInput = $("isaac-synthetic-isaac-sim-python");' in script
    assert 'pipeline_mode: isaacSyntheticPipelineModeInput' in script
    assert 'isaac_sim_python: isaacSyntheticIsaacSimPythonInput ? isaacSyntheticIsaacSimPythonInput.value.trim() : ""' in script
    assert "mimic_trials: numberValue(isaacSyntheticMimicTrialsInput, 3)" in script
    assert "mimic_num_envs: numberValue(isaacSyntheticMimicNumEnvsInput, 3)" in script
    assert "mimic_generation_backend: isaacSyntheticMimicBackendInput" in script
    assert "domain_randomization_profile: isaacLabDomainRandomizationProfileInput" in script
    assert "rl_teacher_steps: numberValue(isaacSyntheticRlTeacherStepsInput, 0)" in script
    assert 'postJson(endpoint, payload, timeoutMs)' in script
    assert '"/api/lerobot/isaac-lab/prepare"' in script
    assert '"/api/lerobot/isaac-lab/build-synthetic"' in script
    assert '"/api/lerobot/isaac-lab/run-replicator-worker"' in script
    assert "Isaac Lab Replicator smoke" in script
    assert "max_source_frames: 1" in script
    assert 'cameras: ["top"]' in script
    assert '"/api/lerobot/isaac-lab/preview"' in script
    assert '"/api/lerobot/isaac-lab/export-hdf5"' in script
    assert '"/api/lerobot/isaac-lab/annotate"' in script
    assert '"/api/lerobot/isaac-lab/generate-mimic"' in script
    assert '"/api/lerobot/isaac-lab/train-il"' in script
    assert '"/api/lerobot/isaac-lab/eval-il"' in script
    assert '"/api/lerobot/isaac-lab/run-e2e"' in script
    assert '"/api/lerobot/isaac-lab/run-mimic"' in script
    assert '"/api/lerobot/isaac-lab/run-mimic-smoke"' in script
    assert '"/api/lerobot/isaac-lab/mimic/status"' in script
    assert '"/api/lerobot/isaac-lab/mimic/stop"' in script
    assert '"/api/lerobot/isaac-lab/run-rl-teacher"' in script
    assert '"/api/lerobot/isaac-lab/run-rl-teacher-smoke"' in script
    assert '"/api/lerobot/isaac-lab/rl-teacher/status"' in script
    assert '"/api/lerobot/isaac-lab/rl-teacher/stop"' in script
    assert '"/api/lerobot/isaac-lab/e2e-smoke"' in script
    assert "e2e_create_fixture: true" in script
    assert "e2e_episodes: 5" in script
    assert "e2e_episode_s: 10" in script
    assert "mimic_camera_width: 320" in script
    assert "mimic_camera_height: 240" in script
    assert '"/api/lerobot/isaac-lab/status"' in script
    assert '["job", data?.job?.status || "-"]' in script
    assert 'setSyntheticCard(isaacSyntheticHdf5El, "HDF5 Export"' in script
    assert "function syntheticCameraPrimLabel(cameraPrims)" in script
    assert "syntheticCameraPrimLabel(digitalTwin.camera_prims)" in script
    assert "function sourceWeightLabel(sourceType)" in script
    assert '["real weights", sourceWeightLabel("real_lerobot")]' in script
    assert '["synthetic weights", sourceWeightLabel("isaac_lab_synthetic")]' in script


def test_lerobot_isaac_lab_gui_tab_shell_is_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")
    styles = Path("web/static/styles.css").read_text(encoding="utf-8")

    assert 'id="lerobot-main-tab"' in template
    assert 'id="isaac-lab-tab"' in template
    assert "/static/lerobot.js?v=20260903-background-train-1" in template
    assert "/static/styles.css?v=20260715-camera-usb-link-1" in template
    assert 'data-lerobot-tab-target="isaac-lab-tab"' in template
    assert "function activateLeRobotGuiTab" in script
    assert 'target.scrollIntoView({ block: "start" })' in script
    assert "scroll-margin-top: 86px" in styles
    assert "--lerobot-page-max-width: 1500px" in styles
    assert "--lerobot-lab-launcher-action-min" in styles
    assert "--lerobot-lab-episode-input-width" in styles
    assert "grid-template-columns: minmax(0, 1fr)" in styles
    assert "grid-template-columns: minmax(0, var(--lerobot-lab-launcher-main-width)) minmax(var(--lerobot-lab-launcher-side-min), auto)" not in styles
    assert "justify-content: flex-start" in styles


def test_lerobot_section_7_exposes_single_standard_domain_randomization_mimic_action() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert '<section id="isaac-augmentation-card"' in template
    assert '<details id="isaac-augmentation-card"' not in template

    section_start = template.index('id="isaac-augmentation-card"')
    lab_tab_start = template.index('id="isaac-lab-tab"')
    section_7 = template[section_start:lab_tab_start]

    assert 'id="isaac-lab-domain-mimic-pipeline"' in section_7
    assert 'id="isaac-lab-domain-mimic-check"' in section_7
    assert 'id="isaac-lab-domain-mimic-stop"' in section_7
    assert "Domain randomization + mimic pipeline" in section_7
    assert "recommended domain randomization + official Isaac Lab Mimic path" in section_7
    assert 'id="isaac-lab-domain-mimic-rgbd-input" type="checkbox" checked' in section_7
    assert "RGB-D cameras" in section_7
    assert 'id="isaac-lab-visualize-generation-input" type="checkbox" checked' in section_7
    assert "Render Mimic RGB-D after generation" in section_7
    assert 'id="isaac-lab-domain-mimic-overwrite-input" type="checkbox" checked' not in section_7
    assert 'id="isaac-lab-domain-mimic-overwrite-all-input" type="checkbox" checked' not in section_7
    assert 'id="isaac-lab-domain-mimic-episodes-input"' in section_7
    assert 'id="isaac-lab-domain-mimic-episodes-input" type="text" value="" placeholder="all or 0,1,2"' in section_7
    assert 'id="isaac-lab-launcher-failure-list"' in section_7
    assert 'id="isaac-lab-launcher-action-status"' in section_7
    assert "lerobot-action-status" in section_7
    assert 'id="isaac-lab-launcher-progress"' in section_7
    assert 'id="isaac-lab-launcher-progress-label"' in section_7
    assert 'id="isaac-lab-launcher-progress-bar"' in section_7
    assert "Open Isaac Lab GUI" not in section_7
    assert "lerobot-isaac-augment-profile-input" not in section_7
    assert "btn-isaac-augment-run" not in section_7
    assert "isaac-synthetic-pipeline-mode" not in section_7
    assert "isaac-synthetic-run-mimic" not in section_7
    assert "isaac-synthetic-status-training-exposure" not in section_7
    assert 'bind("isaac-lab-domain-mimic-pipeline"' in script
    assert "runIsaacDomainMimicPipeline(actionStatusFromEvent(event))" in script
    assert 'bind("isaac-lab-domain-mimic-check", (event) => checkIsaacDomainMimicOutputs(actionStatusFromEvent(event)))' in script
    assert 'bind("isaac-lab-domain-mimic-stop", (event) => stopIsaacDomainMimicPipeline(actionStatusFromEvent(event)))' in script
    assert '"/api/lerobot/isaac-lab/run-e2e"' in script
    domain_runner = script[
        script.index("async function runIsaacDomainMimicPipeline") : script.index("async function stopIsaacDomainMimicPipeline")
    ]
    assert '"/api/lerobot/isaac-lab/domain-mimic/run"' in domain_runner
    assert '"/api/lerobot/isaac-lab/run-e2e"' not in domain_runner
    assert '"/api/lerobot/isaac-lab/mimic/status"' in script
    assert '"/api/lerobot/isaac-lab/mimic/stop"' in script
    assert 'bind("isaac-synthetic-mimic-stop", (event) => stopIsaacDomainMimicPipeline(actionStatusFromEvent(event)))' in script
    assert script.count('bind("isaac-synthetic-mimic-stop"') == 1
    assert 'typeof data.mimic === "object"' in script
    assert "mimic.candidate_count ?? progressTotal ?? mimic.mimic_trials" in script
    assert "const total = Math.max(" in script
    assert "progressTotal > 0 ? progressTotal : configuredTotal > 0 ? configuredTotal : 100" in script
    assert '"/api/lerobot/isaac-lab/build-synthetic"' in script
    assert '"/api/lerobot/isaac-lab/check-outputs"' in script
    assert "shouldRenderIsaacLabMimicRgbdAfterGeneration" in domain_runner
    assert "renderMissingIsaacLabMimicRgbd(statusTarget, followupPayload)" in domain_runner
    poller = script[
        script.index("async function pollIsaacDomainMimicJob") : script.index("async function runIsaacDomainMimicPipeline")
    ]
    assert "function isaacLabMimicStatusIsRgbdRender" in script
    assert "&& !isaacLabMimicStatusIsRgbdRender(latest)" in poller
    assert "restoreIsaacDomainMimicPipelineStatus()" in script
    assert "renderIsaacDomainMimicLauncherProgress" in script
    assert 'const isaacLabDomainMimicOverwriteInput = $("isaac-lab-domain-mimic-overwrite-input");' in script
    assert 'const isaacLabDomainMimicOverwriteAllInput = $("isaac-lab-domain-mimic-overwrite-all-input");' in script
    assert 'const isaacLabDomainMimicEpisodesInput = $("isaac-lab-domain-mimic-episodes-input");' in script
    assert "const domainMimicOverwrite = boolValue(isaacLabDomainMimicOverwriteInput) || boolValue(isaacLabDomainMimicOverwriteAllInput);" in script
    assert 'const domainMimicEpisodeIndices = boolValue(isaacLabDomainMimicOverwriteAllInput) ? "" : (isaacLabDomainMimicEpisodesInput ? isaacLabDomainMimicEpisodesInput.value.trim() : "");' in script
    assert "isaac_lab_episode_indices: domainMimicEpisodeIndices" in script
    assert "force_rebuild: domainMimicOverwrite" in script
    assert "resume: !domainMimicOverwrite" in script


def test_lerobot_section_7_has_separate_lab_rgbd_render_missing_action() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")
    app_main = Path("app/main.py").read_text(encoding="utf-8")

    section_start = template.index('id="isaac-augmentation-card"')
    lab_tab_start = template.index('id="isaac-lab-tab"')
    section_7 = template[section_start:lab_tab_start]

    assert 'id="isaac-lab-domain-mimic-render-missing-rgbd"' in section_7
    assert "Render Missing Mirror RGB-D" in section_7
    assert 'id="btn-isaac-rgbd-render-start"' not in section_7

    assert 'const isaacLabDomainMimicRenderMissingRgbdInput = $("isaac-lab-domain-mimic-render-missing-rgbd");' in script
    assert 'bind("isaac-lab-domain-mimic-render-missing-rgbd", (event) => renderMissingIsaacLabMimicRgbd(actionStatusFromEvent(event)))' in script
    assert '"/api/lerobot/isaac-lab/mimic-rgbd/render-missing"' in script

    render_missing_start = script.index("async function renderMissingIsaacLabMimicRgbd")
    render_missing_end = script.index("async function stopIsaacDomainMimicPipeline")
    render_missing_fn = script[render_missing_start:render_missing_end]
    assert "basePayload = null" in render_missing_fn
    assert "runIsaacRgbdRender" not in render_missing_fn
    assert "lerobot-isaac-rgbd-render" not in render_missing_fn
    assert "isaac_lab_visualize_generation: true" in render_missing_fn
    assert "mimic_enable_cameras: true" in render_missing_fn

    assert '@app.post("/api/lerobot/isaac-lab/mimic-rgbd/render-missing")' in app_main
    assert "overwrite_latest: domainMimicOverwrite" in script
    assert "renderIsaacLabOutputCheckList" in script
    assert "Isaac Lab output check passed" in script
    assert "Mimic candidate mismatch" in script
    assert "function syncIsaacDomainMimicEpisodeOverride()" in script
    assert "isaacLabDomainMimicEpisodesInput.disabled = boolValue(isaacLabDomainMimicOverwriteAllInput);" in script
    assert 'mode: "live"' in script
    assert 'runtime_mode: "live"' in script
    assert "dry_run: false" in script
    assert 'mimic_annotation_mode: "auto"' in script
    assert "enable_mimic: true" in script


def test_lerobot_isaac_lab_synthetic_training_exposure_counts_are_visible() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "candidate_row_count" in script
    assert "exposed_row_count" in script
    assert "blocked_row_count" in script
    assert "candidate_source_counts" in script
    assert "trainable_count" in script
    assert "replicator_import_probe" in script
    assert "data?.worker?.status" in script


def test_lerobot_isaac_lab_synthetic_trajectory_metrics_are_visible() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "synthetic_trajectory_metrics" in script
    assert "function syntheticTrajectoryMetricLabel" in script
    assert '["mimic trajectories", syntheticTrajectoryMetricLabel("mimic")]' in script
    assert '["rl trajectories", syntheticTrajectoryMetricLabel("rl_teacher")]' in script
    assert '["synthetic effective", syntheticTrajectoryTotal.effective_training_samples ?? "-"]' in script
    assert '["synthetic training rows", syntheticTrajectoryTotal.training_row_count ?? 0]' in script


def test_lerobot_isaac_lab_synthetic_health_metrics_are_visible() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "function syntheticSourceTypeSummary" in script
    assert "function syntheticEffectiveSampleLabel" in script
    assert '["Lab tag", compatibility.isaac_lab_git_tag || compatibility.lab?.git_tag || "-"]' in script
    assert '["Lab commit", compatibility.isaac_lab_git_commit || compatibility.lab?.git_commit || "-"]' in script
    assert '["Sim", compatibility.isaac_sim_version || compatibility.sim?.version || "-"]' in script
    assert '["Replicator", compatibility.replicator?.status || replicatorProbe.status || "-"]' in script
    assert '["source types", syntheticSourceTypeSummary()]' in script
    assert '["effective samples", syntheticEffectiveSampleLabel()]' in script


def test_lerobot_isaac_lab_preview_cards_and_visual_generation_are_visible() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="isaac-lab-visualize-generation-input"' in template
    assert 'id="isaac-lab-mimic-cameras-input"' in template
    assert "Open Visual Replicator" in template
    assert "isaac_lab_visualize_generation: checkboxValue(isaacLabVisualizeGenerationInput)" in script
    assert "mimic_enable_cameras: checkboxValue(isaacLabMimicCamerasInput)" in script
    assert "function renderIsaacLabPreviewCards(sourceLabels)" in script
    assert "isaacLabPreviewMediaHtml" in script
    assert "sourceLabels.cards" in script
    assert 'bind("isaac-synthetic-run-replicator-visual"' in script
    assert 'isaac_lab_visualize_generation: true' in script


def test_isaac_lab_gui_has_basic_defaults_and_collapsed_advanced_settings() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")
    styles = Path("web/static/styles.css").read_text(encoding="utf-8")

    assert "isaac-lab-quick-start-grid" not in template
    assert 'id="isaac-lab-basic-settings" class="lerobot-details isaac-lab-basic-settings" open' in template
    assert '<summary>Basic settings</summary>' in template
    assert 'id="isaac-lab-apply-standard-defaults"' in template
    assert 'id="isaac-synthetic-isaac-lab-path" type="text" value="/home/jin/IsaacLab"' in template
    assert 'id="isaac-synthetic-stage-path" type="text" value="/home/jin/autonomous_researcher/sim/robotis_omx/scene/omx_table_layout.usda"' in template
    assert 'id="isaac-lab-advanced-settings" class="lerobot-details isaac-lab-advanced-settings"' in template
    assert '<summary>Advanced settings</summary>' in template
    assert 'id="isaac-synthetic-mimic-trials" type="number" min="1" max="5000" step="1" value="3"' in template
    assert 'id="isaac-synthetic-mimic-num-envs" type="number" min="1" max="256" step="1" value="3"' in template
    assert '<option value="standard" selected>standard</option>' in template
    assert 'id="isaac-synthetic-enable-mimic" type="checkbox" checked' in template
    assert 'id="isaac-synthetic-enable-replicator" type="checkbox" /> Replicator output' in template
    assert 'id="isaac-lab-visualize-generation-input" type="checkbox" checked' in template
    assert 'id="isaac-lab-mimic-cameras-input" type="checkbox" checked /> Include Lab RGB-D cameras' in template
    assert "function applyIsaacLabStandardDefaults" in script
    assert 'bind("isaac-lab-apply-standard-defaults"' in script
    assert "mimic_trials: numberValue(isaacSyntheticMimicTrialsInput, 3)" in script
    assert "mimic_num_envs: numberValue(isaacSyntheticMimicNumEnvsInput, 3)" in script
    assert 'setInputValue(isaacSyntheticIsaacLabPathInput, "/home/jin/IsaacLab")' in script
    assert 'setInputValue(isaacSyntheticStagePathInput, "/home/jin/autonomous_researcher/sim/robotis_omx/scene/omx_table_layout.usda")' in script
    assert 'isaacLabDomainRandomizationProfileInput.value = "standard"' in script
    assert 'isaacSyntheticMimicBackendInput.value = "official"' in script
    assert "syncIsaacLabMimicRgbdInputs(true)" in script
    assert "rgbd_cameras: true" in script
    assert ".isaac-lab-basic-layout" in styles
    assert ".isaac-lab-basic-actions-panel" in styles
    assert ".isaac-lab-basic-actions" in styles
    assert ".isaac-lab-advanced-actions" in styles


def test_lerobot_isaac_lab_tab_does_not_mix_live_recording_check_controls() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="isaac-synthetic-run-live-e2e-check"' not in template
    assert "Run 10s x 3 Live Check" not in template
    assert 'id="isaac-synthetic-live-e2e-status"' not in template
    assert 'id="isaac-synthetic-live-e2e-stop"' not in template
    assert '"/api/lerobot/isaac-lab/run-live-e2e-check"' in script
    assert '"/api/lerobot/isaac-lab/live-e2e/status"' in script
    assert '"/api/lerobot/isaac-lab/live-e2e/stop"' in script
    assert "function isaacSyntheticLiveE2ePayload" in script
    assert "e2e_episodes: 3" in script
    assert "e2e_episode_s: 10" in script
    assert "mimic_trials: 3" in script
    assert "mimic_enable_cameras: checkboxValue(isaacLabMimicCamerasInput)" in script
    assert "isaac_lab_visualize_generation: checkboxValue(isaacLabVisualizeGenerationInput)" in script


def test_lerobot_isaac_lab_tab_separates_settings_from_user_actions() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")

    expected_order = [
        'id="isaac-lab-basic-settings"',
        'id="isaac-lab-basic-actions"',
        'id="isaac-lab-advanced-settings"',
        'id="isaac-lab-advanced-actions"',
        "<summary>Domain Randomization / Augmentation</summary>",
        "<summary>Run output and reports</summary>",
    ]
    positions = [template.index(marker) for marker in expected_order]
    assert positions == sorted(positions)

    basic_settings = template[
        template.index('id="isaac-lab-basic-settings"') : template.index('id="isaac-lab-basic-actions"')
    ]
    basic_actions = template[
        template.index('id="isaac-lab-basic-actions"') : template.index('id="isaac-lab-advanced-settings"')
    ]
    advanced_settings = template[
        template.index('id="isaac-lab-advanced-settings"') : template.index('id="isaac-lab-advanced-actions"')
    ]
    advanced_actions = template[
        template.index('id="isaac-lab-advanced-actions"') : template.index("<summary>Domain Randomization / Augmentation</summary>")
    ]

    assert 'id="isaac-lab-run-e2e"' not in basic_settings
    assert 'id="isaac-lab-generate-mimic"' in basic_actions
    assert 'id="isaac-lab-train-il"' in basic_actions
    assert 'id="isaac-lab-eval-il"' in basic_actions
    assert 'id="isaac-synthetic-mimic-stop"' in basic_actions
    assert 'id="isaac-synthetic-action-status"' in basic_actions
    assert 'id="isaac-synthetic-check-digital-twin"' not in advanced_settings
    assert 'id="isaac-synthetic-build"' in advanced_actions
    assert 'id="isaac-synthetic-run-rl-teacher"' in advanced_actions


def test_lerobot_isaac_rgbd_render_progress_bar_is_smoothed() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="btn-isaac-rgbd-render-stop"' in template
    assert 'id="btn-isaac-rgbd-render-check"' in template
    assert "Check Rendered RGB-D" in template
    assert "Rerender All + Check" not in template
    assert 'bind("btn-isaac-rgbd-render-stop"' in script
    assert 'bind("btn-isaac-rgbd-render-start", (event) => runIsaacRgbdRender(actionStatusFromEvent(event), { validateAfterCompletion: true }))' in script
    assert 'bind("btn-isaac-rgbd-render-check", (event) => checkIsaacRgbdRenderContact(actionStatusFromEvent(event)))' in script
    assert 'bind("btn-isaac-rgbd-rerender-all"' not in script
    assert "function stopIsaacRgbdRender" in script
    assert "function isaacRgbdRenderStopPayload" in script
    assert 'const renderDatasetPath = String((lastIsaacRgbdRenderJob && lastIsaacRgbdRenderJob.dataset_path) || "").trim();' in script
    assert 'return basePayload({ session_id: sessionId, dataset_path: renderDatasetPath, dataset_repo_id: "" });' in script
    assert "const payload = isaacRgbdRenderStopPayload();" in script
    assert 'const payload = basePayload({ session_id: sessionId });' not in script
    assert "function checkIsaacRgbdRenderContact" in script
    assert "Incomplete RGB-D coverage" in script
    assert "RGB-D warnings remain" in script
    assert "RGB-D check passed" in script
    assert '"/api/lerobot/isaac-rgbd/render/stop"' in script
    assert "validateIsaacRgbdRenderContactAfterCompletion" in script
    assert "isaac_rgbd_post_render_overwrite = options.forceAll ? true" in script
    assert "ISAAC_RGBD_RENDER_PROGRESS_EASE" in script
    assert "isaacRgbdRenderDisplayedPercent" in script
    assert "updateIsaacRgbdRenderProgressBar(clampedPercent)" in script
    assert "isaacRgbdRenderProgressBarEl.style.width" in script


def test_lerobot_isaac_rgbd_manual_render_can_override_to_latest_record_session() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="lerobot-isaac-rgbd-render-overwrite-input" type="checkbox" checked' not in template
    assert 'id="lerobot-isaac-rgbd-render-session-override-input"' in template
    assert 'id="lerobot-isaac-rgbd-render-session-override-input" type="checkbox" checked' in template
    assert 'id="lerobot-isaac-rgbd-render-override-all-input"' in template
    assert 'id="lerobot-isaac-rgbd-render-override-all-input" type="checkbox" checked' not in template
    render_options = template[
        template.index('id="btn-isaac-rgbd-render-start"') : template.index(
            'id="lerobot-isaac-rgbd-render-action-status"'
        )
    ]
    option_order = [
        'id="lerobot-isaac-rgbd-render-session-override-input"',
        'id="lerobot-isaac-rgbd-render-overwrite-input"',
        'id="lerobot-isaac-rgbd-render-episodes-input"',
        'id="lerobot-isaac-rgbd-render-override-all-input"',
    ]
    assert [render_options.index(marker) for marker in option_order] == sorted(
        render_options.index(marker) for marker in option_order
    )
    assert 'const isaacRgbdRenderSessionOverrideInput = $("lerobot-isaac-rgbd-render-session-override-input");' in script
    assert 'const isaacRgbdRenderOverrideAllInput = $("lerobot-isaac-rgbd-render-override-all-input");' in script
    assert 'const renderSessionId = boolValue(isaacRgbdRenderSessionOverrideInput) ? (lastSessionByWorkflow.record || "") : "";' in script
    assert "basePayload({ session_id: renderSessionId, isaac_rgbd_post_render_inline: false })" in script
    assert 'payload.isaac_rgbd_post_render_execution_mode = "headless_preplay_replay";' in script
    assert 'const renderEpisodeIndices = options.forceAll || boolValue(isaacRgbdRenderOverrideAllInput) ? "" : (isaacRgbdRenderEpisodesInput ? isaacRgbdRenderEpisodesInput.value.trim() : "");' in script
    assert "payload.isaac_rgbd_post_render_episode_indices = renderEpisodeIndices;" in script
    assert "function syncIsaacRgbdRenderEpisodeOverride()" in script
    assert "isaacRgbdRenderEpisodesInput.disabled = boolValue(isaacRgbdRenderOverrideAllInput);" in script
    assert "function handleIsaacRgbdRenderOverrideAllChange()" in script
    assert "if (boolValue(isaacRgbdRenderOverrideAllInput) && isaacRgbdRenderOverwriteInput) isaacRgbdRenderOverwriteInput.checked = true;" in script
    assert 'isaacRgbdRenderOverrideAllInput.addEventListener("change", handleIsaacRgbdRenderOverrideAllChange);' in script
    assert 'basePayload({ session_id: pollingSessionId })' in script
    assert 'lastIsaacRgbdRenderSessionId = String(responseSessionId ?? "");' in script


def test_lerobot_domain_mimic_launcher_uses_three_by_three_defaults() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")
    app_main = Path("app/main.py").read_text(encoding="utf-8")

    assert "function isaacDomainMimicPayload" in script
    assert '@app.post("/api/lerobot/isaac-lab/domain-mimic/run")' in app_main
    assert "max_source_frames: 0" in script
    assert "attempts_per_source_frame: 3" in script
    assert "mimic_trials: 3" in script
    assert "mimic_num_envs: 3" in script
    assert "mimic_camera_width: 320" in script
    assert "mimic_camera_height: 240" in script
    function_body = script[script.index("function isaacDomainMimicPayload") : script.index("function isaacDomainMimicFollowupPayload")]
    assert 'mimic_generation_backend: "official"' in function_body
    assert "require_digital_twin_pass: false" in function_body
    assert "require_depth_pass: false" in function_body
    assert "require_physics_pass: false" in function_body
    assert "require_articulation_pass: false" in function_body
    assert "isaac_lab_visualize_generation: checkboxValue(isaacLabVisualizeGenerationInput)" in function_body
    assert "isaac_lab_visualize_generation: false" not in function_body
    assert 'const stage = String(progress.stage || status || "waiting").toUpperCase();' in script
    assert 'bind("isaac-lab-domain-mimic-pipeline", (event) => runIsaacDomainMimicPipeline(actionStatusFromEvent(event)))' in script


def test_lerobot_domain_mimic_running_progress_uses_job_progress() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")
    styles = Path("web/static/styles.css").read_text(encoding="utf-8")

    function_body = script[
        script.index("function isaacDomainMimicProgressPayload") : script.index(
            "function renderIsaacDomainMimicLauncherProgress"
        )
    ]
    assert 'const jobProgress = data && data.job && typeof data.job.progress === "object" ? data.job.progress : {};' in function_body
    assert "const progress = Object.keys(jobProgress).length ? jobProgress : responseProgress;" in function_body
    assert 'const useBackendProgressOnly = status === "RUNNING" && (stage.includes("RGBD_RENDER") || progressTotal > 0);' in function_body
    assert "const done = useBackendProgressOnly ? progressDone : success + failure;" in function_body
    assert "const countPercent = total > 0 && done > 0 ? (done / total) * 100 : 0;" in function_body
    assert "function formatElapsedFromIso" in script
    assert "function isaacDomainMimicProgressMessage" in script
    assert "target=${configuredTotal}" in function_body
    assert "elapsed=${elapsed}" in function_body
    assert "indeterminate: useBackendProgressOnly && backendPercent <= 5 && done <= 0" in function_body
    assert "barEl.classList.toggle(\"is-indeterminate\"" in script
    assert ".training-progress-track span.is-indeterminate" in styles


def test_lerobot_record_restart_auto_resumes_stopped_latest_dataset() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "function latestRecordSession()" in script
    assert "function recordRestartShouldResume()" in script
    assert 'String(latest.status || "").toUpperCase() !== "STOPPED"' in script
    assert "currentDataset && latestDataset && currentDataset === latestDataset" in script
    assert "function recordResumeValue()" in script
    assert "return boolValue(resumeInput) || recordRestartShouldResume();" in script
    assert "return basePayload({ dataset_repo_id: recordDatasetRepoValue(), resume: recordResumeValue(), ...overrides });" in script


def test_lerobot_fresh_dataset_repo_is_limited_to_record_start_and_non_resume_train_start() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "function currentDatasetRepoValue()" in script
    assert "function freshDatasetRepoValue()" in script
    assert "function recordDatasetRepoValue()" in script
    assert "function trainDatasetRepoValue()" in script
    assert "return boolValue(trainResumeInput) ? currentDatasetRepoValue() : freshDatasetRepoValue();" in script
    assert 'dataset_repo_id: datasetSplit.repo || lastWorkflowDefaults.dataset_repo_id || "",' in script
    assert "dataset_repo_id: datasetSplit.repo || lastWorkflowDefaults.dataset_repo_id || `jin/${todayRunNameFallback()}`" not in script
    assert "return basePayload({ dataset_repo_id: recordDatasetRepoValue(), resume: recordResumeValue(), ...overrides });" in script
    assert "return basePayload({ dataset_repo_id: trainDatasetRepoValue(), resume: boolValue(trainResumeInput), ...overrides });" in script


def test_lerobot_local_policy_selection_resumes_training_run_instead_of_replacing_source_policy() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "function applyLocalPolicyTrainingResume(policy)" in script
    assert 'if (policy && policy.source === "local") {' in script
    assert "if (trainResumeInput) trainResumeInput.checked = true;" in script
    assert "if (outputDirInput && policy.output_dir) outputDirInput.value = policy.output_dir;" in script
    assert "if (jobNameInput && policy.job_name) jobNameInput.value = policy.job_name;" in script
    assert "applyTrainConfigDefaults(policy.train_config || {});" in script
    assert 'if (trainSourcePolicyInput && policy.source !== "local") trainSourcePolicyInput.value = clean;' in script
    assert 'const trainingPolicies = displayPolicies.filter((p) => p.source === "local");' in script
    assert "policyListEl.innerHTML = trainingPolicies.slice(0, 12).map((p) =>" in script


def test_lerobot_train_source_policy_is_hidden_from_main_training_form() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "Train Source Policy / HF Base" not in template
    assert 'id="lerobot-train-source-policy-input" type="hidden" value="lerobot/smolvla_base"' in template
    assert 'const trainSourcePolicyInput = $("lerobot-train-source-policy-input");' in script
    assert "policy_pretrained_path: trainSourcePolicyInput ? trainSourcePolicyInput.value.trim() : \"\"," in script


def test_lerobot_wandb_local_api_key_controls_are_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="lerobot-train-wandb-api-key-input" type="password"' in template
    assert 'id="btn-wandb-local-api-key-save"' in template
    assert 'const trainWandbApiKeyInput = $("lerobot-train-wandb-api-key-input");' in script
    assert 'fetch("/api/lerobot/wandb-local/api-key")' in script
    assert 'postJson("/api/lerobot/wandb-local/api-key"' in script


def test_lerobot_unified_progress_components_are_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    for element_id in [
        "lerobot-isaac-rgbd-render-progress",
        "lerobot-isaac-augmentation-progress",
        "lerobot-visualization-progress",
        "lerobot-train-progress",
    ]:
        assert element_id in template
        assert element_id in script

    assert "createSmoothProgressController" in script
    assert "smoothProgressControllers" in script
    assert "renderUnifiedProgress(" in script
    assert "renderIsaacAugmentationProgress(data)" in script
    assert "isaac_data_augmentation_async: true" in script
    assert "pollIsaacAugmentationJob(data.job_id, payload, statusTarget)" in script
    assert 'postJson("/api/lerobot/augment/status", payload, 30000)' in script
    assert 'postJson("/api/lerobot/augment/isaac", payload, 300000)' not in script
    assert "renderVisualizationProgress(data)" in script
    assert "renderTrainingPreflightProgress(data)" in script
    assert "training_preflight" in script


def test_lerobot_training_eta_prefers_active_step_rate() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "function parseTrainingActiveStepsPerSec(log)" in script
    assert 'for (const key of ["updt_s", "data_s"])' in script
    assert "const activeRate = parseTrainingActiveStepsPerSec(log);" in script
    assert "const backendRate = Number(training.steps_per_sec || 0);" in script
    assert "const fallbackRate = current > 0 && elapsed > 0 ? current / elapsed : 0;" in script
    assert "const rate = activeRate > 0 ? activeRate : backendRate > 0 ? backendRate : fallbackRate;" in script
    assert "const rate = current > 0 && elapsed > 0 ? current / elapsed : Number(training.steps_per_sec || 0);" not in script


def test_lerobot_isaac_augmentation_summary_renders_qa_counts() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "valid_variant_count" in script
    assert "failed_variant_count" in script


def test_lerobot_gui_uses_selected_profile_pipeline_as_default() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "let observationPipelineProfileId = \"\";" in script
    assert "const selectedProfileId = profileSelect ? profileSelect.value : selected;" in script
    assert "const profileDefaultPipeline = profile.observation_pipeline_id || selectedPipeline;" in script
    assert "const pipelineProfileUnchanged = observationPipelineProfileId === selectedProfileId;" in script
    assert "observationPipelineProfileId = selectedProfileId;" in script


def test_lerobot_manipulation_profile_does_not_override_global_pipeline_select() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")
    body = script.split("function applyManipulationProfile", 1)[1].split("async function refreshManipulationProfile", 1)[0]

    assert "profileSelect.value = profile.profile_id" not in body
    assert "observationPipelineSelect.value = profile.observation_pipeline_id" not in body


def test_lerobot_manipulation_save_reapplies_canonical_server_profile() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")
    body = script.split("async function persistManipulationTaskProfile", 1)[1].split(
        "function setInputValue", 1
    )[0]

    assert "applyManipulationProfile(data.profile || {}, true);" in body


def test_lerobot_gui_defaults_to_official_rerun_visualizer() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert '<option value="rerun" selected>Official LeRobot Rerun viewer</option>' in template
    assert '<option value="distant" selected>distant - serve websocket</option>' in template
    assert 'id="lerobot-visualization-web-port-input" type="number" min="1" value="9092"' in template
    assert 'id="lerobot-visualization-ws-port-input" type="number" min="1" value="9089"' in template
    assert 'visualization_tool: visualizationToolInput ? visualizationToolInput.value || "rerun" : "rerun"' in script
    assert 'visualization_mode: visualizationModeInput ? visualizationModeInput.value || "distant" : "distant"' in script
    assert "visualization_web_port: numberValue(visualizationWebPortInput, 9092)" in script
    assert "visualization_ws_port: numberValue(visualizationWsPortInput, 9089)" in script
    assert "qa_failure_counts" in script
    assert "qa_summary_path" in script
    assert "function rerunViewerUrl(viz)" in script
    assert "encodeURIComponent(viz.rerun_ws_url)" in script
    assert "Rerun viewer:" in script


def test_lerobot_visualization_supports_multi_episode_and_isaac_preview() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="lerobot-episode-index-input" type="text" value="0" placeholder="0,1,2' in template
    assert "Preview Dataset + Isaac Media" in template
    assert "Isaac Sim sidecar recordings" in template
    assert "function episodeIndicesValue()" in script
    assert "function primaryEpisodeIndexValue()" in script
    assert "episode_indices: episodeIndicesValue()" in script
    assert "source_counts" in script
    assert "source || \"dataset\"" in script
    assert "visualizationPayload({ episode_index: numberValue(episodeIndexInput, 0) })" not in script


def test_lerobot_isaac_augmentation_preview_controls_are_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "btn-isaac-augment-preview" in template
    assert "lerobot-isaac-augment-preview-count-input" in template
    assert "lerobot-isaac-augmentation-preview" in template
    assert 'const isaacAugmentPreviewCountInput = $("lerobot-isaac-augment-preview-count-input");' in script
    assert "isaac_data_augmentation_preview_count: numberValue(isaacAugmentPreviewCountInput, 20)" in script
    assert 'postJson("/api/lerobot/augment/preview"' in script
    assert "renderIsaacAugmentationPreview" in script
    assert "source_depth_preview" in script
    assert "augmented_depth_preview" in script


def test_lerobot_dataset_health_card_is_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "lerobot-dataset-health" in template
    assert 'const datasetHealthEl = $("lerobot-dataset-health");' in script
    assert "renderDatasetHealth" in script
    assert "dataset_health" in script
    assert "raw_depth" in script
    assert "isaac_rgbd" in script
    assert "isaac_augmentation" in script
    assert "contact_audit" in script
    assert "Isaac RGB-D Contact Audit" in script
    assert "severe_episodes" in script


def test_lerobot_isaac_rgbd_render_failure_list_is_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "lerobot-isaac-rgbd-render-failure-list" in template
    assert 'const isaacRgbdRenderFailureListEl = $("lerobot-isaac-rgbd-render-failure-list");' in script
    assert "renderIsaacRgbdRenderFailureList" in script
    assert "failed_frames" in script
    assert "Excluded from sim/synthetic data" in script
    assert "No failed/excluded RGB-D episodes detected" in script


def test_lerobot_dataset_mix_controls_are_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    for element_id in [
        "lerobot-dataset-mix-real-weight-input",
        "lerobot-dataset-mix-isaac-rgbd-weight-input",
        "lerobot-dataset-mix-isaac-augmentation-weight-input",
        "lerobot-dataset-mix-isaac-lab-synthetic-weight-input",
        "lerobot-dataset-mix-isaac-rgbd-max-input",
        "lerobot-dataset-mix-isaac-augmentation-max-input",
        "lerobot-dataset-mix-isaac-lab-synthetic-max-input",
        "lerobot-dataset-mix-seed-input",
        "lerobot-dataset-exclude-flagged-episodes-input",
        "lerobot-dataset-include-real-original-input",
        "lerobot-dataset-include-isaac-rgbd-input",
        "lerobot-dataset-include-isaac-augmentation-input",
        "lerobot-dataset-include-isaac-lab-synthetic-input",
        "lerobot-fidelity-weighting-enabled-input",
        "lerobot-fidelity-real-weight-input",
        "lerobot-fidelity-isaac-rgbd-weight-input",
        "lerobot-fidelity-isaac-augmentation-weight-input",
        "lerobot-fidelity-isaac-lab-synthetic-weight-input",
    ]:
        assert element_id in template
        assert element_id in script
    assert "dataset_mix_real_original_weight: numberValue(datasetMixRealWeightInput, 1)" in script
    assert 'id="lerobot-dataset-mix-isaac-rgbd-weight-input" type="number" min="0" step="0.05" value="0.6"' in template
    assert 'id="lerobot-dataset-mix-isaac-lab-synthetic-weight-input" type="number" min="0" step="0.05" value="0.35"' in template
    assert 'id="lerobot-dataset-exclude-flagged-episodes-input" type="checkbox" checked' in template
    assert "Exclude flagged sim/synthetic data only" in template
    assert "Training Data Sources" in template
    assert 'id="lerobot-dataset-include-real-original-input" type="checkbox" checked' in template
    assert 'id="lerobot-dataset-include-isaac-rgbd-input" type="checkbox" checked' in template
    assert 'id="lerobot-dataset-include-isaac-augmentation-input" type="checkbox"' in template
    assert 'id="lerobot-dataset-include-isaac-lab-synthetic-input" type="checkbox" checked' in template
    assert 'id="lerobot-fidelity-isaac-rgbd-weight-input" type="number" min="0" max="1" step="0.05" value="0.55"' in template
    assert "dataset_include_real_original: boolValue(datasetIncludeRealOriginalInput)" in script
    assert "dataset_include_isaac_rgbd: boolValue(datasetIncludeIsaacRgbdInput)" in script
    assert "dataset_include_isaac_augmentation: boolValue(datasetIncludeIsaacAugmentationInput)" in script
    assert "dataset_include_isaac_lab_synthetic: boolValue(datasetIncludeIsaacLabSyntheticInput)" in script
    assert "dataset_mix_isaac_rgbd_weight: numberValue(datasetMixIsaacRgbdWeightInput, 0.6)" in script
    assert "dataset_mix_isaac_augmentation_weight: numberValue(datasetMixIsaacAugmentationWeightInput, 0)" in script
    assert "dataset_mix_isaac_lab_synthetic_weight: numberValue(datasetMixIsaacLabSyntheticWeightInput, 0.35)" in script
    assert "dataset_mix_isaac_lab_synthetic_max_samples: numberValue(datasetMixIsaacLabSyntheticMaxInput, null)" in script
    assert "dataset_exclude_flagged_episodes: excludeFlaggedEpisodesValue()" in script
    assert "fidelity_weighting_enabled: boolValue(fidelityWeightingEnabledInput)" in script
    assert "fidelity_real_original_weight: numberValue(fidelityRealWeightInput, 1)" in script
    assert "fidelity_isaac_rgbd_weight: numberValue(fidelityIsaacRgbdWeightInput, 0.55)" in script
    assert "fidelity_isaac_augmentation_weight: numberValue(fidelityIsaacAugmentationWeightInput, 0)" in script
    assert "fidelity_isaac_lab_synthetic_weight: numberValue(fidelityIsaacLabSyntheticWeightInput, 0.25)" in script


def test_lerobot_dataset_manage_tab_is_wired_for_merge_split_delete() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    for element_id in [
        "dataset-manage-tab-button",
        "dataset-manage-tab",
    ]:
        assert element_id in template

    for element_id in [
        "dataset-manage-merge-source-a",
        "dataset-manage-merge-source-b",
        "dataset-manage-merge-range-a",
        "dataset-manage-merge-range-b",
        "dataset-manage-output-repo",
        "btn-browse-dataset-manage-root",
        "dataset-manage-split-source",
        "dataset-manage-split-spec",
        "dataset-manage-delete-source",
        "dataset-manage-delete-range",
        "dataset-manage-delete-output-repo",
        "dataset-manage-list",
        "dataset-manage-status",
    ]:
        assert element_id in template
        assert element_id in script
    assert 'data-lerobot-tab-target="dataset-manage-tab"' in template
    assert "Dataset Manage" in template
    assert 'postJson("/api/lerobot/dataset-manage/list"' in script
    assert '"/api/lerobot/dataset-manage/merge"' in script
    assert '"/api/lerobot/dataset-manage/split"' in script
    assert '"/api/lerobot/dataset-manage/delete"' in script
    assert "function refreshDatasetManageList" in script
    assert "function syncDatasetManageRootFromLocalPaths" in script
    assert "function datasetManageMergePayload" in script
    assert "function datasetManageSplitPayload" in script
    assert "function datasetManageDeletePayload" in script
    assert 'bind("btn-browse-dataset-manage-root"' in script
    assert 'bind("btn-dataset-manage-merge"' in script
    assert 'bind("btn-dataset-manage-split"' in script
    assert 'bind("btn-dataset-manage-delete"' in script
    assert "dataset_mix_effective_counts" in script
    assert "fidelity_weights" in script


def test_manipulation_bridge_runtime_supervisor_cards_are_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    for label in [
        "Bridge State",
        "Port Lease",
        "Active Camera",
        "Robot Policy Runtime",
        "Rerun Telemetry",
        "Observation Preview",
        "Joint State",
        "Action Stream",
        "Viewer Evidence",
        "Vision Completion Gate",
        "Execution Safety",
    ]:
        assert label in template
    assert "Home Pose / Interlock" not in script
    assert "Pi0.5/SARM state" not in template
    assert "Pi0.5 / Policy Runtime" not in script
    assert "SARM Stage Progress" not in script
    assert "function executionSafetyFromReport" in script
    assert "function rerunTelemetryFromReport" in script
    assert "telemetry.latest_frame_artifact" in script
    assert "telemetry.joint_state" in script
    assert "telemetry.action_rate_hz" in script
    assert "renderManipulationAgentReport(data);" in script


def test_manipulation_bridge_defaults_match_rollout_inference_policy() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert '<option value="smolvla" selected>smolvla (SmolVLA)</option>' in template
    for policy_type in ["act", "diffusion", "pi0", "pi05", "pi0fast", "xvla", "vqbet"]:
        assert f'<option value="{policy_type}">' in template
    assert 'selectedManipulationPolicyType() || "smolvla"' in script
    assert 'rollout_inference_type: policyTypeKey === "pi05" ? "rtc" : "",' in script
    assert "rollout_action_clamp: manipulationActionClampInput ? boolValue(manipulationActionClampInput) : false," in script
    assert "rollout_max_relative_target: numberValue(manipulationMaxRelativeTargetInput, 5)," in script
    assert (
        "rollout_shoulder_lift_backstop: manipulationShoulderLiftBackstopInput ? "
        "boolValue(manipulationShoulderLiftBackstopInput) : true,"
    ) in script


def test_manipulation_bridge_reuses_rollout_configuration_layout() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "Use Rollout Settings" not in template
    assert "btn-manipulation-use-rollout-settings" not in template
    for element_id in [
        "lerobot-manipulation-task-id-input",
        "lerobot-manipulation-policy-select",
        "lerobot-manipulation-policy-type-input",
        "lerobot-manipulation-policy-input",
        "btn-browse-manipulation-policy",
        "btn-manipulation-latest-policy",
        "lerobot-manipulation-instruction-input",
        "lerobot-manipulation-duration-input",
        "lerobot-manipulation-action-clamp-input",
        "lerobot-manipulation-max-relative-target-input",
        "lerobot-manipulation-shoulder-lift-backstop-input",
        "lerobot-manipulation-temporal-ensemble-input",
        "lerobot-manipulation-temporal-coeff-input",
        "lerobot-manipulation-rtc-horizon-input",
        "lerobot-manipulation-rtc-guidance-input",
        "lerobot-manipulation-action-queue-input",
        "lerobot-manipulation-observation-input",
    ]:
        assert element_id in template
    for obsolete_id in [
        "lerobot-manipulation-strategy-input",
        "lerobot-manipulation-policy-backend-input",
        "lerobot-manipulation-source-input",
        "lerobot-manipulation-target-input",
        "lerobot-manipulation-specimen-id-input",
        "lerobot-manipulation-candidate-id-input",
        "lerobot-manipulation-stl-input",
        "lerobot-manipulation-camera-input",
        "lerobot-manipulation-display-input",
    ]:
        assert obsolete_id not in template
    assert "function manipulationRolloutPayload" in script
    assert "function applyManipulationTaskProfile" in script
    assert "async function persistManipulationTaskProfile" in script
    assert "await persistManipulationTaskProfile" in script
    assert "onSelect: persistSelectedManipulationPolicy" in script
    assert "task_profiles" in script
