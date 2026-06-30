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
        "lerobot-dataset-mix-isaac-rgbd-max-input",
        "lerobot-dataset-mix-isaac-augmentation-max-input",
        "lerobot-dataset-mix-seed-input",
        "lerobot-fidelity-weighting-enabled-input",
        "lerobot-fidelity-real-weight-input",
        "lerobot-fidelity-isaac-rgbd-weight-input",
        "lerobot-fidelity-isaac-augmentation-weight-input",
    ]:
        assert element_id in template
        assert element_id in script
    assert "dataset_mix_real_original_weight: numberValue(datasetMixRealWeightInput, 1)" in script
    assert "dataset_mix_isaac_rgbd_weight: numberValue(datasetMixIsaacRgbdWeightInput, 0.5)" in script
    assert "dataset_mix_isaac_augmentation_weight: numberValue(datasetMixIsaacAugmentationWeightInput, 0.5)" in script
    assert "fidelity_weighting_enabled: boolValue(fidelityWeightingEnabledInput)" in script
    assert "fidelity_real_original_weight: numberValue(fidelityRealWeightInput, 1)" in script
    assert "fidelity_isaac_rgbd_weight: numberValue(fidelityIsaacRgbdWeightInput, 0.5)" in script
    assert "fidelity_isaac_augmentation_weight: numberValue(fidelityIsaacAugmentationWeightInput, 0.3)" in script
    assert "dataset_mix_effective_counts" in script
    assert "fidelity_weights" in script
