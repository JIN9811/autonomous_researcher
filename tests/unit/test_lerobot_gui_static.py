"""Static checks for the LeRobot GUI surface."""

from __future__ import annotations

from pathlib import Path


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


def test_lerobot_isaac_lab_synthetic_controls_and_payload_are_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    for element_id in [
        "isaac-synthetic-panel",
        "isaac-synthetic-pipeline-mode",
        "isaac-synthetic-fallback-policy",
        "isaac-synthetic-source-intent",
        "isaac-synthetic-isaac-sim-python",
        "isaac-synthetic-mimic-trials",
        "isaac-synthetic-mimic-num-envs",
        "isaac-synthetic-rl-teacher-steps",
        "isaac-synthetic-check-digital-twin",
        "isaac-synthetic-build",
        "isaac-synthetic-run-replicator-worker",
        "isaac-synthetic-run-replicator-smoke",
        "isaac-synthetic-preview",
        "isaac-synthetic-export-hdf5",
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
    ]:
        assert element_id in template
        assert element_id in script

    assert "Isaac Lab Synthetic Intelligence" in template
    assert "function isaacSyntheticPayload" in script
    assert 'const isaacSyntheticIsaacSimPythonInput = $("isaac-synthetic-isaac-sim-python");' in script
    assert 'pipeline_mode: isaacSyntheticPipelineModeInput' in script
    assert 'isaac_sim_python: isaacSyntheticIsaacSimPythonInput ? isaacSyntheticIsaacSimPythonInput.value.trim() : ""' in script
    assert "mimic_trials: numberValue(isaacSyntheticMimicTrialsInput, 20)" in script
    assert "mimic_num_envs: numberValue(isaacSyntheticMimicNumEnvsInput, 1)" in script
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
    assert '"/api/lerobot/isaac-lab/status"' in script
    assert '["job", data?.job?.status || "-"]' in script
    assert 'setSyntheticCard(isaacSyntheticHdf5El, "HDF5 Export"' in script
    assert "function syntheticCameraPrimLabel(cameraPrims)" in script
    assert "syntheticCameraPrimLabel(digitalTwin.camera_prims)" in script
    assert "function sourceWeightLabel(sourceType)" in script
    assert '["real weights", sourceWeightLabel("real_lerobot")]' in script
    assert '["synthetic weights", sourceWeightLabel("isaac_lab_synthetic")]' in script


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


def test_lerobot_isaac_rgbd_render_progress_bar_is_smoothed() -> None:
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "ISAAC_RGBD_RENDER_PROGRESS_EASE" in script
    assert "isaacRgbdRenderDisplayedPercent" in script
    assert "updateIsaacRgbdRenderProgressBar(clampedPercent)" in script
    assert "isaacRgbdRenderProgressBarEl.style.width" in script


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
        "lerobot-fidelity-weighting-enabled-input",
        "lerobot-fidelity-real-weight-input",
        "lerobot-fidelity-isaac-rgbd-weight-input",
        "lerobot-fidelity-isaac-augmentation-weight-input",
        "lerobot-fidelity-isaac-lab-synthetic-weight-input",
    ]:
        assert element_id in template
        assert element_id in script
    assert "dataset_mix_real_original_weight: numberValue(datasetMixRealWeightInput, 1)" in script
    assert "dataset_mix_isaac_rgbd_weight: numberValue(datasetMixIsaacRgbdWeightInput, 0.5)" in script
    assert "dataset_mix_isaac_augmentation_weight: numberValue(datasetMixIsaacAugmentationWeightInput, 0.5)" in script
    assert "dataset_mix_isaac_lab_synthetic_weight: numberValue(datasetMixIsaacLabSyntheticWeightInput, 0.5)" in script
    assert "dataset_mix_isaac_lab_synthetic_max_samples: numberValue(datasetMixIsaacLabSyntheticMaxInput, null)" in script
    assert "fidelity_weighting_enabled: boolValue(fidelityWeightingEnabledInput)" in script
    assert "fidelity_real_original_weight: numberValue(fidelityRealWeightInput, 1)" in script
    assert "fidelity_isaac_rgbd_weight: numberValue(fidelityIsaacRgbdWeightInput, 0.5)" in script
    assert "fidelity_isaac_augmentation_weight: numberValue(fidelityIsaacAugmentationWeightInput, 0.3)" in script
    assert "fidelity_isaac_lab_synthetic_weight: numberValue(fidelityIsaacLabSyntheticWeightInput, 0.2)" in script
    assert "dataset_mix_effective_counts" in script
    assert "fidelity_weights" in script
