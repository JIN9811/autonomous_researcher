/*
File purpose:
- Frontend runtime for the LeRobot / ROBOTIS workspace.

Key classes/functions:
- refreshConfig
- runAction
- browsePath
- visualizeDataset

Inputs/outputs:
- Input: /api/lerobot/* JSON responses
- Output: updated LeRobot GUI controls, session list, command previews, local path browser, and dataset media visualization

Dependencies:
- Fetch API

Modification guide:
- Safe places to edit: render labels and action grouping
- Risky places to edit: endpoint URLs and element IDs consumed by lerobot.html
- Related files: web/templates/lerobot.html, app/main.py
*/

const $ = (id) => document.getElementById(id);
const DEFAULT_LEROBOT_TASK_INSTRUCTION = "Pick up the cube and place it";
const DEFAULT_PI05_ROLLOUT_TASK = DEFAULT_LEROBOT_TASK_INSTRUCTION;
const DEFAULT_RECORD_NUM_EPISODES = 60;

const profileSelect = $("lerobot-profile-select");
const observationPipelineSelect = $("lerobot-observation-pipeline-select");
const modeSelect = $("lerobot-mode-select");
const fpsInput = $("lerobot-fps-input");
const cameraFpsInput = $("lerobot-camera-fps-input");
const deviceInput = $("lerobot-device-input");
const confirmLiveInput = $("lerobot-confirm-live-input");
const taskInput = $("lerobot-task-input");
const datasetRootInput = $("lerobot-dataset-root-input");
const datasetInput = $("lerobot-dataset-input");
const episodesInput = $("lerobot-episodes-input");
const episodeTimeInput = $("lerobot-episode-time-input");
const resetTimeInput = $("lerobot-reset-time-input");
const ttsEngineInput = $("lerobot-tts-engine-input");
const ttsRateInput = $("lerobot-tts-rate-input");
const ttsRateValue = $("lerobot-tts-rate-value");
const ttsRateDefaultButton = $("btn-tts-rate-default");
const ttsHelpButton = $("btn-tts-help");
const ttsHelpPopover = $("lerobot-tts-help-popover");
const teleopTimeInput = $("lerobot-teleop-time-input");
const displayDataInput = $("lerobot-display-data-input");
const teleopHandoffPanel = $("lerobot-teleop-handoff-panel");
const teleopHandoffContextEl = $("lerobot-teleop-handoff-context");
const teleopHandoffStatusEl = $("lerobot-teleop-handoff-status");
const teleopHandoffCompleteButton = $("btn-teleop-handoff-complete");
const resumeInput = $("lerobot-resume-input");
const trainResumeInput = $("lerobot-train-resume-input");
const pushHubInput = $("lerobot-push-hub-input");
const policyTypeInput = $("lerobot-policy-type-input");
const outputDirInput = $("lerobot-output-dir-input");
const policyInput = $("lerobot-policy-input");
const rolloutPolicyTypeInput = $("lerobot-rollout-policy-type-input");
const rolloutPolicyInput = $("lerobot-rollout-policy-input");
const rolloutInstructionInput = $("lerobot-rollout-instruction-input");
const rolloutDurationInput = $("lerobot-rollout-duration-input");
const rolloutActionClampInput = $("lerobot-rollout-action-clamp-input");
const plcRolloutStopInput = $("lerobot-plc-rollout-stop-input");
const plcRolloutStopStatusEl = $("lerobot-plc-rollout-stop-status");
const rolloutMaxRelativeTargetInput = $("lerobot-rollout-max-relative-target-input");
const rolloutShoulderLiftBackstopInput = $("lerobot-rollout-shoulder-lift-backstop-input");
const rolloutTemporalEnsembleInput = $("lerobot-rollout-temporal-ensemble-input");
const rolloutTemporalCoeffInput = $("lerobot-rollout-temporal-coeff-input");
const rolloutRtcHorizonInput = $("lerobot-rollout-rtc-horizon-input");
const rolloutRtcGuidanceInput = $("lerobot-rollout-rtc-guidance-input");
const rolloutActionQueueInput = $("lerobot-rollout-action-queue-input");
const manipulationTaskIdInput = $("lerobot-manipulation-task-id-input");
const manipulationPolicySelect = $("lerobot-manipulation-policy-select");
const manipulationPolicyTypeInput = $("lerobot-manipulation-policy-type-input");
const manipulationPolicyInput = $("lerobot-manipulation-policy-input");
const manipulationInstructionInput = $("lerobot-manipulation-instruction-input");
const manipulationDurationInput = $("lerobot-manipulation-duration-input");
const manipulationActionClampInput = $("lerobot-manipulation-action-clamp-input");
const manipulationMaxRelativeTargetInput = $("lerobot-manipulation-max-relative-target-input");
const manipulationShoulderLiftBackstopInput = $("lerobot-manipulation-shoulder-lift-backstop-input");
const manipulationTemporalEnsembleInput = $("lerobot-manipulation-temporal-ensemble-input");
const manipulationTemporalCoeffInput = $("lerobot-manipulation-temporal-coeff-input");
const manipulationRtcHorizonInput = $("lerobot-manipulation-rtc-horizon-input");
const manipulationRtcGuidanceInput = $("lerobot-manipulation-rtc-guidance-input");
const manipulationActionQueueInput = $("lerobot-manipulation-action-queue-input");
const manipulationObservationInput = $("lerobot-manipulation-observation-input");
const manipulationReportEl = $("lerobot-manipulation-report");
const policySelect = $("lerobot-policy-select");
const jobNameInput = $("lerobot-job-name-input");
const trainSourcePolicyInput = $("lerobot-train-source-policy-input");
const trainPolicyRepoInput = $("lerobot-train-policy-repo-input");
const trainBatchSizeInput = $("lerobot-train-batch-size-input");
const trainStepsInput = $("lerobot-train-steps-input");
const trainWorkersInput = $("lerobot-train-workers-input");
const trainEvalFreqInput = $("lerobot-train-eval-freq-input");
const trainLogFreqInput = $("lerobot-train-log-freq-input");
const trainSaveFreqInput = $("lerobot-train-save-freq-input");
const trainSeedInput = $("lerobot-train-seed-input");
const trainOptimizerInput = $("lerobot-train-optimizer-input");
const trainLrInput = $("lerobot-train-lr-input");
const trainWeightDecayInput = $("lerobot-train-weight-decay-input");
const trainGradClipInput = $("lerobot-train-grad-clip-input");
const trainSchedulerInput = $("lerobot-train-scheduler-input");
const trainWarmupInput = $("lerobot-train-warmup-input");
const trainDecayStepsInput = $("lerobot-train-decay-steps-input");
const trainPeakLrInput = $("lerobot-train-peak-lr-input");
const trainDecayLrInput = $("lerobot-train-decay-lr-input");
const trainNObsInput = $("lerobot-train-n-obs-input");
const trainChunkInput = $("lerobot-train-chunk-input");
const trainNActionInput = $("lerobot-train-n-action-input");
const trainEvalBatchInput = $("lerobot-train-eval-batch-input");
const trainExtraArgsInput = $("lerobot-train-extra-args-input");
const datasetMixRealWeightInput = $("lerobot-dataset-mix-real-weight-input");
const datasetMixIsaacRgbdWeightInput = $("lerobot-dataset-mix-isaac-rgbd-weight-input");
const datasetMixIsaacAugmentationWeightInput = $("lerobot-dataset-mix-isaac-augmentation-weight-input");
const datasetMixIsaacLabSyntheticWeightInput = $("lerobot-dataset-mix-isaac-lab-synthetic-weight-input");
const datasetMixRealMaxInput = $("lerobot-dataset-mix-real-max-input");
const datasetMixIsaacRgbdMaxInput = $("lerobot-dataset-mix-isaac-rgbd-max-input");
const datasetMixIsaacAugmentationMaxInput = $("lerobot-dataset-mix-isaac-augmentation-max-input");
const datasetMixIsaacLabSyntheticMaxInput = $("lerobot-dataset-mix-isaac-lab-synthetic-max-input");
const datasetMixSeedInput = $("lerobot-dataset-mix-seed-input");
const datasetExcludeFlaggedEpisodesInput = $("lerobot-dataset-exclude-flagged-episodes-input");
const datasetIncludeRealOriginalInput = $("lerobot-dataset-include-real-original-input");
const datasetIncludeIsaacRgbdInput = $("lerobot-dataset-include-isaac-rgbd-input");
const datasetIncludeIsaacAugmentationInput = $("lerobot-dataset-include-isaac-augmentation-input");
const datasetIncludeIsaacLabSyntheticInput = $("lerobot-dataset-include-isaac-lab-synthetic-input");
const fidelityWeightingEnabledInput = $("lerobot-fidelity-weighting-enabled-input");
const fidelityRealWeightInput = $("lerobot-fidelity-real-weight-input");
const fidelityIsaacRgbdWeightInput = $("lerobot-fidelity-isaac-rgbd-weight-input");
const fidelityIsaacAugmentationWeightInput = $("lerobot-fidelity-isaac-augmentation-weight-input");
const fidelityIsaacLabSyntheticWeightInput = $("lerobot-fidelity-isaac-lab-synthetic-weight-input");
const trainSaveCheckpointInput = $("lerobot-train-save-checkpoint-input");
const trainBackgroundInput = $("lerobot-train-background-input");
const trainUseAmpInput = $("lerobot-train-use-amp-input");
const trainWandbInput = $("lerobot-train-wandb-input");
const trainWandbProjectInput = $("lerobot-train-wandb-project-input");
const trainWandbModeInput = $("lerobot-train-wandb-mode-input");
const trainWandbBaseUrlInput = $("lerobot-train-wandb-base-url-input");
const trainWandbApiKeyInput = $("lerobot-train-wandb-api-key-input");
const wandbApiKeyStatusEl = $("lerobot-wandb-api-key-status");
const trainProgressEl = $("lerobot-train-progress");
const trainProgressLabelEl = $("lerobot-train-progress-label");
const trainProgressBarEl = $("lerobot-train-progress-bar");
const observationInput = $("lerobot-observation-input");
const episodeIndexInput = $("lerobot-episode-index-input");
const visualizationPathInput = $("lerobot-visualization-path-input");
const visualizationToolInput = $("lerobot-visualization-tool-input");
const visualizationModeInput = $("lerobot-visualization-mode-input");
const visualizationBatchSizeInput = $("lerobot-visualization-batch-size-input");
const visualizationWorkersInput = $("lerobot-visualization-workers-input");
const visualizationWebPortInput = $("lerobot-visualization-web-port-input");
const visualizationWsPortInput = $("lerobot-visualization-ws-port-input");
const visualizationToleranceInput = $("lerobot-visualization-tolerance-input");
const visualizationSaveInput = $("lerobot-visualization-save-input");
const visualizationOutputDirInput = $("lerobot-visualization-output-dir-input");
const isaacAugmentProfileInput = $("lerobot-isaac-augment-profile-input");
const isaacAugmentVariantsInput = $("lerobot-isaac-augment-variants-input");
const isaacAugmentMaxFramesInput = $("lerobot-isaac-augment-max-frames-input");
const isaacAugmentSeedInput = $("lerobot-isaac-augment-seed-input");
const isaacAugmentCamerasInput = $("lerobot-isaac-augment-cameras-input");
const isaacAugmentOutputDirInput = $("lerobot-isaac-augment-output-dir-input");
const isaacAugmentImageInput = $("lerobot-isaac-augment-image-input");
const isaacAugmentPhotometricInput = $("lerobot-isaac-augment-photometric-input");
const isaacAugmentSensorNoiseInput = $("lerobot-isaac-augment-sensor-noise-input");
const isaacAugmentDepthNoiseInput = $("lerobot-isaac-augment-depth-noise-input");
const isaacAugmentRenderDomainInput = $("lerobot-isaac-augment-render-domain-input");
const isaacAugmentCameraPoseInput = $("lerobot-isaac-augment-camera-pose-input");
const isaacAugmentExcludeFlaggedEpisodesInput = $("lerobot-isaac-augment-exclude-flagged-episodes-input");
const isaacAugmentRgbStrengthInput = $("lerobot-isaac-augment-rgb-strength-input");
const isaacAugmentDepthStrengthInput = $("lerobot-isaac-augment-depth-strength-input");
const isaacAugmentRenderDomainStrengthInput = $("lerobot-isaac-augment-render-domain-strength-input");
const isaacAugmentCameraPoseStrengthInput = $("lerobot-isaac-augment-camera-pose-strength-input");
const isaacAugmentPreviewCountInput = $("lerobot-isaac-augment-preview-count-input");
const isaacSyntheticPanelEl = $("isaac-lab-advanced-settings");
const isaacSyntheticPipelineModeInput = $("isaac-synthetic-pipeline-mode");
const isaacSyntheticFallbackPolicyInput = $("isaac-synthetic-fallback-policy");
const isaacSyntheticSourceIntentInput = $("isaac-synthetic-source-intent");
const isaacSyntheticIsaacLabPathInput = $("isaac-synthetic-isaac-lab-path");
const isaacSyntheticIsaacSimPythonInput = $("isaac-synthetic-isaac-sim-python");
const isaacSyntheticStagePathInput = $("isaac-synthetic-stage-path");
const isaacSyntheticMimicTrialsInput = $("isaac-synthetic-mimic-trials");
const isaacSyntheticMimicNumEnvsInput = $("isaac-synthetic-mimic-num-envs");
const isaacSyntheticMimicBackendInput = $("isaac-synthetic-mimic-backend");
const isaacLabDomainRandomizationProfileInput = $("isaac-lab-domain-randomization-profile");
const isaacSyntheticRlTeacherStepsInput = $("isaac-synthetic-rl-teacher-steps");
const isaacSyntheticEnableReplicatorInput = $("isaac-synthetic-enable-replicator");
const isaacSyntheticEnableHdf5ExportInput = $("isaac-synthetic-enable-hdf5-export");
const isaacSyntheticEnableMimicInput = $("isaac-synthetic-enable-mimic");
const isaacSyntheticEnableRlTeacherInput = $("isaac-synthetic-enable-rl-teacher");
const isaacLabVisualizeGenerationInput = $("isaac-lab-visualize-generation-input");
const isaacLabMimicCamerasInput = $("isaac-lab-mimic-cameras-input");
const isaacLabDomainMimicRgbdInput = $("isaac-lab-domain-mimic-rgbd-input");
const isaacLabDomainMimicOverwriteInput = $("isaac-lab-domain-mimic-overwrite-input");
const isaacLabDomainMimicOverwriteAllInput = $("isaac-lab-domain-mimic-overwrite-all-input");
const isaacLabDomainMimicEpisodesInput = $("isaac-lab-domain-mimic-episodes-input");
const isaacLabDomainMimicRenderMissingRgbdInput = $("isaac-lab-domain-mimic-render-missing-rgbd");
const isaacRgbdRenderProgressEl = $("lerobot-isaac-rgbd-render-progress");
const isaacRgbdRenderProgressLabelEl = $("lerobot-isaac-rgbd-render-progress-label");
const isaacRgbdRenderProgressBarEl = $("lerobot-isaac-rgbd-render-progress-bar");
const isaacRgbdRenderFailureListEl = $("lerobot-isaac-rgbd-render-failure-list");
const isaacRgbdRenderOverwriteInput = $("lerobot-isaac-rgbd-render-overwrite-input");
const isaacRgbdRenderSessionOverrideInput = $("lerobot-isaac-rgbd-render-session-override-input");
const isaacRgbdRenderOverrideAllInput = $("lerobot-isaac-rgbd-render-override-all-input");
const isaacRgbdRenderEpisodesInput = $("lerobot-isaac-rgbd-render-episodes-input");
const isaacAugmentationProgressEl = $("lerobot-isaac-augmentation-progress");
const isaacAugmentationProgressLabelEl = $("lerobot-isaac-augmentation-progress-label");
const isaacAugmentationProgressBarEl = $("lerobot-isaac-augmentation-progress-bar");
const visualizationProgressEl = $("lerobot-visualization-progress");
const visualizationProgressLabelEl = $("lerobot-visualization-progress-label");
const visualizationProgressBarEl = $("lerobot-visualization-progress-bar");
const ISAAC_RGBD_RENDER_PROGRESS_EASE = 0.18;
const ISAAC_RGBD_RENDER_PROGRESS_ANIMATION_MS = 80;
const ISAAC_RGBD_RENDER_PROGRESS_MIN_STEP = 0.15;
let isaacRgbdRenderDisplayedPercent = 0;
let isaacRgbdRenderTargetPercent = 0;
let isaacRgbdRenderProgressTimer = null;
let isaacRgbdRenderValidateAfterCompletion = false;
let lastIsaacRgbdRenderJob = null;
let lastIsaacRgbdHealth = null;
const smoothProgressControllers = {};
const outputEl = $("lerobot-output");
const sessionListEl = $("lerobot-session-list");
const browserEl = $("lerobot-browser");
const policyListEl = $("lerobot-policy-list");
const visualizationEl = $("lerobot-visualization");
const datasetHealthEl = $("lerobot-dataset-health");
const datasetManageRootInput = $("dataset-manage-root");
const datasetManageNamespaceInput = $("dataset-manage-namespace");
const datasetManageDatePrefixInput = $("dataset-manage-date-prefix");
const datasetManageOutputRepoInput = $("dataset-manage-output-repo");
const datasetManageOverwriteInput = $("dataset-manage-overwrite");
const datasetManageMergeSourceAInput = $("dataset-manage-merge-source-a");
const datasetManageMergeSourceBInput = $("dataset-manage-merge-source-b");
const datasetManageMergeRangeAInput = $("dataset-manage-merge-range-a");
const datasetManageMergeRangeBInput = $("dataset-manage-merge-range-b");
const datasetManageSplitSourceInput = $("dataset-manage-split-source");
const datasetManageSplitSpecInput = $("dataset-manage-split-spec");
const datasetManageDeleteSourceInput = $("dataset-manage-delete-source");
const datasetManageDeleteRangeInput = $("dataset-manage-delete-range");
const datasetManageDeleteOutputRepoInput = $("dataset-manage-delete-output-repo");
const datasetManageListEl = $("dataset-manage-list");
const datasetManageStatusEl = $("dataset-manage-status");
const isaacAugmentationEl = $("lerobot-isaac-augmentation");
const isaacAugmentationPreviewEl = $("lerobot-isaac-augmentation-preview");
const isaacSyntheticOutputEl = $("isaac-synthetic-output");
const isaacSyntheticProgressEl = $("isaac-synthetic-progress");
const isaacSyntheticProgressLabelEl = $("isaac-synthetic-progress-label");
const isaacSyntheticProgressBarEl = $("isaac-synthetic-progress-bar");
const isaacSyntheticStepTraceEl = $("isaac-synthetic-step-trace");
const isaacSyntheticCompatibilityEl = $("isaac-synthetic-status-compatibility");
const isaacSyntheticDigitalTwinEl = $("isaac-synthetic-status-digital-twin");
const isaacSyntheticSourceLabelsEl = $("isaac-synthetic-status-source-labels");
const isaacSyntheticCanonicalIndexEl = $("isaac-synthetic-status-canonical-index");
const isaacSyntheticGenerationEl = $("isaac-synthetic-status-generation");
const isaacSyntheticHdf5El = $("isaac-synthetic-status-hdf5");
const isaacSyntheticTrainingExposureEl = $("isaac-synthetic-status-training-exposure");
const isaacLabE2eStatusCardEl = $("isaac-lab-e2e-status-card");
const isaacLabLauncherProgressEl = $("isaac-lab-launcher-progress");
const isaacLabLauncherProgressLabelEl = $("isaac-lab-launcher-progress-label");
const isaacLabLauncherProgressBarEl = $("isaac-lab-launcher-progress-bar");
const isaacLabLauncherFailureListEl = $("isaac-lab-launcher-failure-list");
const lerobotTabButtons = Array.from(document.querySelectorAll("[data-lerobot-tab-target]"));
const lerobotTabPanels = Array.from(document.querySelectorAll(".lerobot-tab-panel"));
const statusDotEl = $("lerobot-status-dot");
const statusLabelEl = $("lerobot-status-label");
const statusDetailEl = $("lerobot-status-detail");
const gateDotEl = $("lerobot-gate-dot");
const gateLabelEl = $("lerobot-gate-label");
const gateDetailEl = $("lerobot-gate-detail");
const sessionPillEl = $("lerobot-session-pill");
const followerPortDisplayEl = $("lerobot-follower-port-display");
const leaderPortDisplayEl = $("lerobot-leader-port-display");
const cameraCardListEl = $("lerobot-camera-card-list");
const newCameraKeyInput = $("lerobot-new-camera-key-input");
const manualPortInput = $("lerobot-manual-port-input");
const manualRoleSelect = $("lerobot-manual-role-select");
const manualCameraKeyInput = $("lerobot-manual-camera-key-input");
const portCandidatesEl = $("lerobot-port-candidates");
const cameraPreviewEl = $("lerobot-camera-preview");
const isaacMirrorOutputEl = $("lerobot-isaac-mirror-output");
const isaacMirrorEnabledInput = $("lerobot-isaac-mirror-enabled-input");
const isaacMirrorEndpointInput = $("lerobot-isaac-mirror-endpoint-input");
const isaacMirrorHzInput = $("lerobot-isaac-mirror-hz-input");
const isaacMirrorTimeoutInput = $("lerobot-isaac-mirror-timeout-input");
const isaacMirrorMaxSamplesInput = $("lerobot-isaac-mirror-max-samples-input");
const activeRobotCamEnabledInput = $("lerobot-active-robot-cam-enabled-input");
const activeRobotCamRecordStartInput = $("lerobot-active-robot-cam-record-start-input");

let lastSessions = [];
let lastSessionByWorkflow = {};
const teleopHandoffQuery = new URLSearchParams(window.location.search);
const teleopHandoffToken = teleopHandoffQuery.get("handoff_token") || "";
const teleopHandoffRunId = teleopHandoffQuery.get("run_id") || "";
let teleopHandoffContext = null;
let teleopHandoffSessionId = "";
let lastConfigPaths = {};
let lastWorkflowDefaults = {};
let lastAutoDatasetRepo = "";
let lastAutoTrainName = "";
let lastAutoOutputDir = "";
let lastBrowseTargetInput = null;
let lastBrowseKind = "any";
let lastBrowseOptions = {};
let lastPortCandidates = [];
let lastConfigData = null;
let extraCameraKeys = [];
let policyCatalogByValue = new Map();
let manipulationTaskProfiles = {};
let activeManipulationTaskId = "transfer_to_utm";
const defaultRealsenseCameraKeys = new Set(["top", "wrist"]);
const cameraRealsenseOverrides = new Map();
const cameraFpsOverrides = new Map();
let recordStatusTimer = null;
let trainStatusTimer = null;
let rolloutStatusTimer = null;
let isaacRgbdRenderStatusTimer = null;
let lastIsaacRgbdRenderSessionId = "";
let lastIsaacLiveE2eJobId = "";
let lastIsaacDomainMimicJobId = "";
let lastIsaacLabOutputCheck = null;
let rolloutProfileLoaded = false;
let manipulationProfileLoaded = false;
let manipulationProfileSavePromise = Promise.resolve();
let profileSelectionInitialized = false;
let observationPipelineProfileId = "";

function setStatusDot(el, state) {
  if (!el) return;
  el.className = "status-dot";
  el.classList.add(state || "idle");
}

function boolValue(el) {
  return Boolean(el && el.checked);
}

function checkboxValue(el) {
  return boolValue(el);
}

function numberValue(el, fallback = null) {
  if (!el || el.value === "") return fallback;
  const value = Number(el.value);
  return Number.isFinite(value) ? value : fallback;
}

function episodeIndicesValue() {
  const raw = episodeIndexInput ? String(episodeIndexInput.value || "").trim() : "";
  return raw || "0";
}

function primaryEpisodeIndexValue() {
  const raw = episodeIndicesValue().toLowerCase();
  if (raw === "all" || raw === "*") return 0;
  const match = raw.match(/\d+/);
  return match ? Number(match[0]) : 0;
}

const LEROBOT_TTS_RATE_STORAGE_KEY = "atr_lerobot_tts_rate_default";
const LEROBOT_TTS_RATE_DEFAULT = -35;
const LEROBOT_TTS_RATE_MIN = -100;
const LEROBOT_TTS_RATE_MAX = 100;
let lerobotTtsServerDefaultRate = LEROBOT_TTS_RATE_DEFAULT;

function clampTtsRate(value, fallback = LEROBOT_TTS_RATE_DEFAULT) {
  const numeric = Number(value);
  const safe = Number.isFinite(numeric) ? Math.round(numeric) : fallback;
  return Math.max(LEROBOT_TTS_RATE_MIN, Math.min(LEROBOT_TTS_RATE_MAX, safe));
}

function storedTtsRateDefault() {
  try {
    const raw = window.localStorage.getItem(LEROBOT_TTS_RATE_STORAGE_KEY);
    return raw === null ? null : clampTtsRate(raw);
  } catch (_err) {
    return null;
  }
}

function saveTtsRateDefault(rate) {
  try {
    window.localStorage.setItem(LEROBOT_TTS_RATE_STORAGE_KEY, String(clampTtsRate(rate)));
  } catch (_err) {
    // Browser storage can be unavailable in restricted contexts; payload still uses the visible slider value.
  }
}

function setTtsRate(value, options = {}) {
  const rate = clampTtsRate(value);
  if (ttsRateInput) ttsRateInput.value = String(rate);
  if (ttsRateValue) ttsRateValue.textContent = String(rate);
  if (options.userEdited && ttsRateInput) ttsRateInput.dataset.userEdited = "1";
  if (options.persist) saveTtsRateDefault(rate);
  return rate;
}

function initializeTtsControls() {
  const savedRate = storedTtsRateDefault();
  if (savedRate !== null) {
    setTtsRate(savedRate, { userEdited: true });
  } else {
    setTtsRate(ttsRateInput ? ttsRateInput.value : LEROBOT_TTS_RATE_DEFAULT);
  }
}

function setTtsHelpVisible(visible) {
  if (!ttsHelpButton || !ttsHelpPopover) return;
  ttsHelpPopover.hidden = !visible;
  ttsHelpButton.setAttribute("aria-expanded", visible ? "true" : "false");
}

function activateLeRobotGuiTab(targetId) {
  const target = $(targetId);
  if (!target) return;
  lerobotTabPanels.forEach((panel) => {
    const active = panel.id === targetId;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
  lerobotTabButtons.forEach((button) => {
    const active = button.dataset.lerobotTabTarget === targetId;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  target.scrollIntoView({ block: "start" });
  target.focus({ preventScroll: false });
}

function trainExtraArgs() {
  const raw = trainExtraArgsInput ? trainExtraArgsInput.value.trim() : "";
  if (!raw) return [];
  return raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

const PI05_BASE_POLICY = "lerobot/pi05_base";
const XVLA_BASE_POLICY = "lerobot/xvla-base";
const SMOLVLA_BASE_POLICY = "lerobot/smolvla_base";
const PI05_TRAIN_EXTRA_DEFAULTS = [
  "--policy.compile_model=true",
  "--policy.gradient_checkpointing=true",
  "--policy.dtype=bfloat16",
  "--policy.freeze_vision_encoder=false",
  "--policy.train_expert_only=false",
];
const PI05_TRAIN_EXTRA_KEYS = PI05_TRAIN_EXTRA_DEFAULTS.map((item) => item.split("=", 1)[0]);
const XVLA_TRAIN_EXTRA_DEFAULTS = [
  "--policy.dtype=bfloat16",
  "--policy.action_mode=auto",
  "--policy.freeze_vision_encoder=false",
  "--policy.freeze_language_encoder=false",
  "--policy.train_policy_transformer=true",
  "--policy.train_soft_prompts=true",
];
const XVLA_TRAIN_EXTRA_KEYS = XVLA_TRAIN_EXTRA_DEFAULTS.map((item) => item.split("=", 1)[0]);
const SMOLVLA_TRAIN_EXTRA_DEFAULTS = [
  "--policy.freeze_vision_encoder=true",
  "--policy.train_expert_only=true",
  "--policy.train_state_proj=true",
];
const SMOLVLA_TRAIN_EXTRA_KEYS = SMOLVLA_TRAIN_EXTRA_DEFAULTS.map((item) => item.split("=", 1)[0]);
const TRAIN_DEFAULTS = {
  act: {
    source_policy: "",
    job_name: "atr_lerobot_act_train",
    batch_size: "8",
    steps: "100000",
    num_workers: "4",
    eval_freq: "20000",
    log_freq: "200",
    save_freq: "20000",
    optimizer_type: "",
    n_obs_steps: "1",
    chunk_size: "100",
    n_action_steps: "100",
    wandb_enable: false,
    wandb_mode: "",
  },
  pi05: {
    source_policy: PI05_BASE_POLICY,
    job_name: "atr_lerobot_pi05_train",
    batch_size: "16",
    steps: "3000",
    num_workers: "12",
    eval_freq: "500",
    log_freq: "50",
    save_freq: "500",
    optimizer_type: "",
    n_obs_steps: "1",
    chunk_size: "50",
    n_action_steps: "50",
    eval_batch_size: "",
    wandb_enable: true,
    wandb_mode: "offline",
  },
  xvla: {
    source_policy: XVLA_BASE_POLICY,
    job_name: "atr_lerobot_xvla_train",
    batch_size: "8",
    steps: "20000",
    num_workers: "4",
    eval_freq: "20000",
    log_freq: "200",
    save_freq: "20000",
    optimizer_type: "",
    n_obs_steps: "1",
    chunk_size: "100",
    n_action_steps: "100",
    eval_batch_size: "",
    wandb_enable: false,
    wandb_mode: "",
  },
  smolvla: {
    source_policy: SMOLVLA_BASE_POLICY,
    job_name: "atr_lerobot_smolvla_train",
    batch_size: "8",
    steps: "20000",
    num_workers: "4",
    eval_freq: "20000",
    log_freq: "200",
    save_freq: "20000",
    optimizer_type: "",
    n_obs_steps: "1",
    chunk_size: "50",
    n_action_steps: "50",
    eval_batch_size: "",
    wandb_enable: false,
    wandb_mode: "",
  },
};
const GENERATED_PATH_SUFFIX_RE = /-(?:\d{8}T\d{6}(?:\d{6})?Z)(?:-\d{2})?$/;

function trainDefaultNumber(field, fallback = null) {
  const type = policyTypeInput ? String(policyTypeInput.value || "act").toLowerCase() : "act";
  const defaults = TRAIN_DEFAULTS[type] || TRAIN_DEFAULTS.act || {};
  const value = Number(defaults[field]);
  return Number.isFinite(value) ? value : fallback;
}

function trainNumberValue(el, field, fallback = null) {
  return numberValue(el, trainDefaultNumber(field, fallback));
}

const TRAIN_DEFAULT_VALUE_SETS = {
  source_policy: new Set(["", PI05_BASE_POLICY, XVLA_BASE_POLICY, SMOLVLA_BASE_POLICY]),
  job_name: new Set(["", "atr_lerobot_train", "atr_lerobot_act_train", "atr_lerobot_pi05_train", "atr_lerobot_xvla_train", "atr_lerobot_smolvla_train"]),
  batch_size: new Set(["", "2", "4", "8", "16", "32"]),
  steps: new Set(["", "20000", "100000", "3000"]),
  num_workers: new Set(["", "2", "4", "12", "16", "20"]),
  eval_freq: new Set(["", "500", "2000", "20000"]),
  log_freq: new Set(["", "5", "50", "100", "200"]),
  save_freq: new Set(["", "500", "2000", "20000"]),
  optimizer_type: new Set(["", "adamw"]),
  n_obs_steps: new Set(["", "1"]),
  chunk_size: new Set(["", "100", "50"]),
  n_action_steps: new Set(["", "100", "50"]),
  eval_batch_size: new Set(["", "1", "2", "4", "8"]),
  wandb_mode: new Set(["", "disabled", "offline", "local", "online"]),
};

const LEGACY_DATASET_DEFAULTS = new Set(["", "jin/record-test", "local/fake_lerobot_dataset"]);
const LEGACY_OUTPUT_DEFAULT_SUFFIXES = [
  "",
  "atr_lerobot_train",
  "atr_lerobot_act_train",
  "atr_lerobot_pi05_train",
  "atr_lerobot_xvla_train",
  "atr_lerobot_smolvla_train",
];
const LEGACY_TASK_DEFAULTS = new Set([
  "",
  "Pick up the cylinder",
  "Pick up the cube and put on the metal plate",
  DEFAULT_LEROBOT_TASK_INSTRUCTION,
]);

function markUserEdited(input) {
  if (input) input.dataset.userEdited = "1";
}

function todayRunNameFallback() {
  const now = new Date();
  const yyyy = String(now.getFullYear());
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}${mm}${dd}_1`;
}

function runNameFromDatasetRepo(value) {
  const clean = String(value || "").trim().replace(/\/+$/, "");
  if (!clean) return "";
  const parts = clean.split("/");
  return parts[parts.length - 1] || "";
}

function currentTrainPolicySuffix() {
  const clean = policyTypeInput ? String(policyTypeInput.value || "smolvla").trim().toLowerCase() : "smolvla";
  return clean.replace(/[^a-z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "") || "smolvla";
}

function trainNameFromDatasetRepo(value) {
  const runName = runNameFromDatasetRepo(value) || lastWorkflowDefaults.run_name || todayRunNameFallback();
  const suffix = currentTrainPolicySuffix();
  if (/_train\([A-Za-z0-9_.-]+\)$/.test(runName)) return runName.replace(/_train\([A-Za-z0-9_.-]+\)$/, `_train(${suffix})`);
  if (runName.endsWith("_train")) return `${runName}(${suffix})`;
  return `${runName}_train(${suffix})`;
}

function outputDirForTrainName(trainName) {
  const root = String((lastConfigPaths && lastConfigPaths.output_root) || "").replace(/\/+$/, "");
  return root ? `${root}/${trainName}` : trainName;
}

function basenameFromPath(value) {
  const clean = String(value || "").trim().replace(/\/+$/, "");
  if (!clean) return "";
  const parts = clean.split("/");
  return parts[parts.length - 1] || clean;
}

function isLegacyOutputDefault(value) {
  const clean = String(value || "").trim().replace(/\/+$/, "");
  const base = basenameFromPath(clean);
  return LEGACY_OUTPUT_DEFAULT_SUFFIXES.includes(clean) || LEGACY_OUTPUT_DEFAULT_SUFFIXES.includes(base);
}

function isAutoTrainNameDefault(value) {
  const clean = String(value || "").trim();
  return TRAIN_DEFAULT_VALUE_SETS.job_name.has(clean) || /^\d{8}_\d+_train(?:\([A-Za-z0-9_.-]+\))?$/.test(clean);
}

function canReplaceAutoInput(input, legacyPredicate, previousAutoValue = "") {
  if (!input) return false;
  const current = String(input.value || "").trim();
  return !input.dataset.userEdited || current === previousAutoValue || legacyPredicate(current);
}

function resumeDatasetRequested() {
  return boolValue(resumeInput);
}

function resumeTrainingRequested() {
  return boolValue(trainResumeInput);
}

function syncTrainNamingFromDataset(options = {}) {
  if (!datasetInput) return;
  if (resumeTrainingRequested() && !options.force) return;
  const force = Boolean(options.force);
  const datasetRepo = String(datasetInput.value || "").trim() || lastWorkflowDefaults.dataset_repo_id || `jin/${todayRunNameFallback()}`;
  const trainName = trainNameFromDatasetRepo(datasetRepo);
  const outputDir = outputDirForTrainName(trainName);
  if (outputDirInput && (force || canReplaceAutoInput(outputDirInput, isLegacyOutputDefault, lastAutoOutputDir))) {
    outputDirInput.value = outputDir;
  }
  if (jobNameInput && (force || canReplaceAutoInput(jobNameInput, isAutoTrainNameDefault, lastAutoTrainName))) {
    jobNameInput.value = trainName;
  }
  lastAutoDatasetRepo = datasetRepo;
  lastAutoTrainName = trainName;
  lastAutoOutputDir = outputDir;
}

function syncJobNameFromOutputDir(options = {}) {
  if (!outputDirInput || !jobNameInput) return;
  if (resumeTrainingRequested() && !options.force) return;
  const force = Boolean(options.force);
  const trainName = basenameFromPath(outputDirInput.value);
  if (!trainName) return;
  if (force || canReplaceAutoInput(jobNameInput, isAutoTrainNameDefault, lastAutoTrainName)) {
    jobNameInput.value = trainName;
    lastAutoTrainName = trainName;
    lastAutoOutputDir = outputDirInput.value.trim();
  }
}

function syncRolloutTaskFromRecordTask(options = {}) {
  if (!taskInput || !rolloutInstructionInput) return;
  const force = Boolean(options.force);
  const recordTask = String(taskInput.value || "").trim() || DEFAULT_LEROBOT_TASK_INSTRUCTION;
  if (force || canReplaceAutoInput(rolloutInstructionInput, (value) => LEGACY_TASK_DEFAULTS.has(value), lastWorkflowDefaults.rollout_task_instruction || "")) {
    rolloutInstructionInput.value = recordTask;
  }
}

function applyWorkflowDefaults(data) {
  const defaults = data.workflow_defaults || {};
  lastWorkflowDefaults = defaults;
  const datasetRepo = defaults.dataset_repo_id || `jin/${todayRunNameFallback()}`;
  const resumeDataset = resumeDatasetRequested();
  const resumeTraining = resumeTrainingRequested();
  if (!resumeDataset && datasetInput && canReplaceAutoInput(datasetInput, (value) => LEGACY_DATASET_DEFAULTS.has(value), lastAutoDatasetRepo)) {
    datasetInput.value = datasetRepo;
  }
  if (taskInput && canReplaceAutoInput(taskInput, (value) => LEGACY_TASK_DEFAULTS.has(value), DEFAULT_LEROBOT_TASK_INSTRUCTION)) {
    taskInput.value = defaults.record_task_instruction || DEFAULT_LEROBOT_TASK_INSTRUCTION;
  }
  if (episodesInput && canReplaceAutoInput(episodesInput, (value) => ["", "1", "5"].includes(value), String(DEFAULT_RECORD_NUM_EPISODES))) {
    episodesInput.value = String(defaults.record_num_episodes || DEFAULT_RECORD_NUM_EPISODES);
  }
  if (!resumeTraining) syncTrainNamingFromDataset();
  syncRolloutTaskFromRecordTask();
}

function ensureTrainExtraArg(arg) {
  if (!trainExtraArgsInput || !arg) return;
  const current = trainExtraArgs();
  const key = arg.split("=", 1)[0];
  if (current.some((item) => item.split("=", 1)[0] === key)) return;
  trainExtraArgsInput.value = [...current, arg].join("\n");
}

function removeTrainExtraArgsByKeys(keys) {
  if (!trainExtraArgsInput || !keys.length) return;
  const keySet = new Set(keys);
  const next = trainExtraArgs().filter((item) => !keySet.has(item.split("=", 1)[0]));
  trainExtraArgsInput.value = next.join("\n");
}

function replaceTrainExtraArgsByDefaults(defaults) {
  if (!trainExtraArgsInput) return;
  const keys = defaults.map((item) => item.split("=", 1)[0]);
  removeTrainExtraArgsByKeys(keys);
  const current = trainExtraArgs();
  trainExtraArgsInput.value = [...defaults, ...current].join("\n");
}


function applyInputDefault(input, key, value, force = false) {
  if (!input) return;
  const current = String(input.value || "").trim();
  if (force || (TRAIN_DEFAULT_VALUE_SETS[key] && TRAIN_DEFAULT_VALUE_SETS[key].has(current))) {
    input.value = value;
  }
}

function applyPolicyTypeDefaults(options = {}) {
  if (!policyTypeInput) return;
  const type = (policyTypeInput.value || "").toLowerCase();
  const defaults = TRAIN_DEFAULTS[type];
  if (!defaults) return;
  const force = Boolean(options.force);

  applyInputDefault(trainSourcePolicyInput, "source_policy", defaults.source_policy, force);
  applyInputDefault(jobNameInput, "job_name", defaults.job_name, force);
  applyInputDefault(trainBatchSizeInput, "batch_size", defaults.batch_size, force);
  applyInputDefault(trainStepsInput, "steps", defaults.steps, force);
  applyInputDefault(trainWorkersInput, "num_workers", defaults.num_workers, force);
  applyInputDefault(trainEvalFreqInput, "eval_freq", defaults.eval_freq, force);
  applyInputDefault(trainLogFreqInput, "log_freq", defaults.log_freq, force);
  applyInputDefault(trainSaveFreqInput, "save_freq", defaults.save_freq, force);
  applyInputDefault(trainOptimizerInput, "optimizer_type", defaults.optimizer_type, force);
  applyInputDefault(trainNObsInput, "n_obs_steps", defaults.n_obs_steps, force);
  applyInputDefault(trainChunkInput, "chunk_size", defaults.chunk_size, force);
  applyInputDefault(trainNActionInput, "n_action_steps", defaults.n_action_steps, force);
  if (defaults.eval_batch_size !== undefined) {
    applyInputDefault(trainEvalBatchInput, "eval_batch_size", defaults.eval_batch_size, force);
  }
  if (defaults.wandb_mode !== undefined) {
    applyInputDefault(trainWandbModeInput, "wandb_mode", defaults.wandb_mode, force);
  }
  if (trainWandbInput && defaults.wandb_enable !== undefined) {
    trainWandbInput.checked = Boolean(defaults.wandb_enable);
  }

  if (type === "pi05") {
    replaceTrainExtraArgsByDefaults(PI05_TRAIN_EXTRA_DEFAULTS);
    removeTrainExtraArgsByKeys([...XVLA_TRAIN_EXTRA_KEYS, ...SMOLVLA_TRAIN_EXTRA_KEYS]);
  } else if (type === "xvla") {
    replaceTrainExtraArgsByDefaults(XVLA_TRAIN_EXTRA_DEFAULTS);
    removeTrainExtraArgsByKeys([...PI05_TRAIN_EXTRA_KEYS, ...SMOLVLA_TRAIN_EXTRA_KEYS]);
  } else if (type === "smolvla") {
    replaceTrainExtraArgsByDefaults(SMOLVLA_TRAIN_EXTRA_DEFAULTS);
    removeTrainExtraArgsByKeys([...PI05_TRAIN_EXTRA_KEYS, ...XVLA_TRAIN_EXTRA_KEYS]);
  } else {
    removeTrainExtraArgsByKeys([...PI05_TRAIN_EXTRA_KEYS, ...XVLA_TRAIN_EXTRA_KEYS, ...SMOLVLA_TRAIN_EXTRA_KEYS]);
  }
}

function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function setInputFromConfig(input, value) {
  if (!input || value === undefined || value === null || value === "") return;
  input.value = String(value);
}

function setCheckboxFromConfig(input, value) {
  if (!input || value === undefined || value === null) return;
  input.checked = Boolean(value);
}

function firstConfigValue(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return "";
}

function applyTrainConfigDefaults(config = {}) {
  const dataset = objectValue(config.dataset);
  const policy = objectValue(config.policy);
  const optimizer = objectValue(config.optimizer);
  const scheduler = objectValue(config.scheduler);
  const evalConfig = objectValue(config.eval);
  const wandb = objectValue(config.wandb);
  setInputFromConfig(datasetInput, dataset.repo_id);
  setInputFromConfig(policyTypeInput, firstConfigValue(policy.type, policy.policy_type));
  setInputFromConfig(trainSourcePolicyInput, firstConfigValue(policy.pretrained_path, policy.path));
  setInputFromConfig(trainPolicyRepoInput, policy.repo_id);
  setInputFromConfig(trainBatchSizeInput, config.batch_size);
  setInputFromConfig(trainStepsInput, config.steps);
  setInputFromConfig(trainWorkersInput, config.num_workers);
  setInputFromConfig(trainEvalFreqInput, config.eval_freq);
  setInputFromConfig(trainLogFreqInput, config.log_freq);
  setInputFromConfig(trainSaveFreqInput, config.save_freq);
  setInputFromConfig(trainSeedInput, config.seed);
  setCheckboxFromConfig(trainSaveCheckpointInput, config.save_checkpoint);
  setInputFromConfig(trainEvalBatchInput, evalConfig.batch_size);
  setInputFromConfig(trainOptimizerInput, optimizer.type);
  setInputFromConfig(trainLrInput, firstConfigValue(optimizer.lr, policy.optimizer_lr));
  setInputFromConfig(trainWeightDecayInput, firstConfigValue(optimizer.weight_decay, policy.optimizer_weight_decay));
  setInputFromConfig(trainGradClipInput, firstConfigValue(optimizer.grad_clip_norm, policy.optimizer_grad_clip_norm));
  setInputFromConfig(trainSchedulerInput, scheduler.type);
  setInputFromConfig(trainWarmupInput, firstConfigValue(scheduler.num_warmup_steps, policy.scheduler_warmup_steps));
  setInputFromConfig(trainDecayStepsInput, firstConfigValue(scheduler.num_decay_steps, policy.scheduler_decay_steps));
  setInputFromConfig(trainPeakLrInput, firstConfigValue(scheduler.peak_lr, policy.scheduler_peak_lr));
  setInputFromConfig(trainDecayLrInput, firstConfigValue(scheduler.decay_lr, policy.scheduler_decay_lr));
  setInputFromConfig(trainNObsInput, policy.n_obs_steps);
  setInputFromConfig(trainChunkInput, policy.chunk_size);
  setInputFromConfig(trainNActionInput, policy.n_action_steps);
  setCheckboxFromConfig(trainUseAmpInput, policy.use_amp);
  setCheckboxFromConfig(trainWandbInput, wandb.enable);
  setInputFromConfig(trainWandbProjectInput, wandb.project);
  setInputFromConfig(trainWandbModeInput, wandb.mode);
  setInputFromConfig(outputDirInput, config.output_dir);
  setInputFromConfig(jobNameInput, config.job_name);
}

function applyLocalPolicyTrainingResume(policy) {
  if (!policy) return;
  const configPolicy = objectValue(objectValue(policy.train_config || {}).policy);
  const policyType = policy.policy_type || configPolicy.type || configPolicy.policy_type || "";
  if (policyType && policyTypeInput) policyTypeInput.value = policyType;
  applyPolicyTypeDefaults({ force: true });
  applyTrainConfigDefaults(policy.train_config || {});
  if (trainResumeInput) trainResumeInput.checked = true;
  if (outputDirInput && policy.output_dir) outputDirInput.value = policy.output_dir;
  if (jobNameInput && policy.job_name) jobNameInput.value = policy.job_name;
  if (outputDirInput) markUserEdited(outputDirInput);
  if (jobNameInput) markUserEdited(jobNameInput);
}

function selectedRolloutPolicyType() {
  const rolloutType = rolloutPolicyTypeInput ? String(rolloutPolicyTypeInput.value || "").trim() : "";
  if (rolloutType) return rolloutType;
  const trainType = policyTypeInput ? String(policyTypeInput.value || "").trim() : "";
  return trainType || "smolvla";
}

function selectedManipulationPolicyType() {
  const manipulationType = manipulationPolicyTypeInput ? String(manipulationPolicyTypeInput.value || "").trim() : "";
  if (manipulationType) return manipulationType;
  return selectedRolloutPolicyType() || "smolvla";
}

function setRolloutOptionDisabled(input, disabled) {
  if (!input) return;
  input.disabled = Boolean(disabled);
  const label = input.closest("label");
  if (label) label.classList.toggle("muted", Boolean(disabled));
}

function syncRolloutPolicyOptions() {
  const type = selectedRolloutPolicyType().toLowerCase();
  const isAct = type === "act";
  const isPi05 = type === "pi05";
  setRolloutOptionDisabled(rolloutTemporalEnsembleInput, !isAct);
  setRolloutOptionDisabled(rolloutTemporalCoeffInput, !isAct);
  setRolloutOptionDisabled(rolloutRtcHorizonInput, !isPi05);
  setRolloutOptionDisabled(rolloutRtcGuidanceInput, !isPi05);
  setRolloutOptionDisabled(rolloutActionQueueInput, !isPi05);
}

function syncManipulationPolicyOptions() {
  const type = selectedManipulationPolicyType().toLowerCase();
  const isAct = type === "act";
  const isPi05 = type === "pi05";
  setRolloutOptionDisabled(manipulationTemporalEnsembleInput, !isAct);
  setRolloutOptionDisabled(manipulationTemporalCoeffInput, !isAct);
  setRolloutOptionDisabled(manipulationRtcHorizonInput, !isPi05);
  setRolloutOptionDisabled(manipulationRtcGuidanceInput, !isPi05);
  setRolloutOptionDisabled(manipulationActionQueueInput, !isPi05);
}

function parseObservation() {
  const raw = observationInput ? observationInput.value.trim() : "";
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch (err) {
    return { parse_error: String(err), raw };
  }
}

function splitPathOrRepo(value) {
  const clean = String(value || "").trim();
  if (!clean) return { path: "", repo: "" };
  if (clean.startsWith("/") || clean.startsWith("~") || clean.startsWith(".") || clean.startsWith("fake://")) {
    return { path: clean, repo: "" };
  }
  return { path: "", repo: clean };
}

function joinPath(base, child) {
  const cleanBase = String(base || "").trim().replace(/\/+$/, "");
  const cleanChild = String(child || "").trim().replace(/^\/+/, "");
  if (!cleanBase) return cleanChild;
  if (!cleanChild) return cleanBase;
  return `${cleanBase}/${cleanChild}`;
}

function stripGeneratedNameSuffixes(name) {
  let clean = String(name || "").trim();
  while (GENERATED_PATH_SUFFIX_RE.test(clean)) {
    const next = clean.replace(GENERATED_PATH_SUFFIX_RE, "");
    if (!next || next === clean) break;
    clean = next;
  }
  return clean;
}

function stripGeneratedPathSuffixes(path) {
  const raw = String(path || "").trim().replace(/\/+$/, "");
  if (!raw) return raw;
  const parts = raw.split("/");
  const name = parts.pop() || "";
  const baseName = stripGeneratedNameSuffixes(name);
  parts.push(baseName);
  return parts.join("/");
}

function datasetBrowseStartPath() {
  const datasetValue = datasetInput ? datasetInput.value.trim() : "";
  const split = splitPathOrRepo(datasetValue);
  if (split.path) return split.path;
  const root = datasetRootInput ? datasetRootInput.value.trim() : "";
  return split.repo ? joinPath(root, split.repo) : root;
}

function datasetRepoValueFromPath(path) {
  const cleanPath = String(path || "").trim().replace(/\/+$/, "");
  const root = datasetRootInput ? datasetRootInput.value.trim().replace(/\/+$/, "") : "";
  if (!cleanPath) return "";
  if (root && cleanPath === root) return "";
  if (root && cleanPath.startsWith(`${root}/`)) return cleanPath.slice(root.length + 1);
  return cleanPath;
}

function currentDatasetRepoValue() {
  const datasetValue = datasetInput ? datasetInput.value.trim() : "";
  const datasetSplit = splitPathOrRepo(datasetValue);
  return datasetSplit.repo || lastWorkflowDefaults.dataset_repo_id || "";
}

function freshDatasetRepoValue() {
  return currentDatasetRepoValue() || `jin/${todayRunNameFallback()}`;
}

function recordDatasetRepoValue() {
  return freshDatasetRepoValue();
}

function trainDatasetRepoValue() {
  return boolValue(trainResumeInput) ? currentDatasetRepoValue() : freshDatasetRepoValue();
}

function browseSelectionValue(path) {
  if (lastBrowseOptions && typeof lastBrowseOptions.valueTransform === "function") {
    return lastBrowseOptions.valueTransform(path);
  }
  return path || "";
}

async function applyBrowseSelection(path) {
  const value = browseSelectionValue(path);
  if (lastBrowseTargetInput) lastBrowseTargetInput.value = value;
  if (lastBrowseOptions && typeof lastBrowseOptions.onSelect === "function") {
    await lastBrowseOptions.onSelect(value);
  }
  return value;
}

function applyDatasetProfileFromInspect(data) {
  const dataset = (data && data.dataset) || {};
  const changes = [];
  const profileId = dataset.robot_profile_id || dataset.profile_id || "";
  if (profileSelect && profileId) {
    const hasProfile = Array.from(profileSelect.options || []).some((opt) => opt.value === profileId);
    if (hasProfile && profileSelect.value !== profileId) {
      profileSelect.value = profileId;
      changes.push(`profile=${profileId}`);
    }
  }
  const pipelineId = dataset.observation_pipeline_id || "";
  if (observationPipelineSelect && pipelineId) {
    const hasPipeline = Array.from(observationPipelineSelect.options || []).some((opt) => opt.value === pipelineId);
    if (hasPipeline && observationPipelineSelect.value !== pipelineId) {
      observationPipelineSelect.value = pipelineId;
      changes.push(`pipeline=${pipelineId}`);
    }
  }
  if (changes.length) {
    renderResult("dataset profile restored", {
      ok: true,
      restored: changes,
      dataset_path: dataset.path || "",
      pipeline_metadata_path: dataset.pipeline_metadata_path || "",
    });
  }
}

async function restoreDatasetProfileFromCurrentInput() {
  if (!datasetInput || !datasetInput.value.trim()) return null;
  try {
    const data = await postJson("/api/lerobot/dataset/inspect", basePayload(), 60000);
    applyDatasetProfileFromInspect(data);
    renderDatasetHealth(data);
    return data;
  } catch (err) {
    renderResult("dataset profile restore", { ok: false, error: String(err) });
    return null;
  }
}

function placeBrowserNearTarget() {
  if (!browserEl || !lastBrowseTargetInput) return;
  const label = lastBrowseTargetInput.closest("label");
  if (label && label.parentNode) {
    label.parentNode.insertBefore(browserEl, label.nextSibling);
    return;
  }
  const row = lastBrowseTargetInput.closest(".input-action-row");
  if (row && row.parentNode) row.parentNode.insertBefore(browserEl, row.nextSibling);
}

function syncFieldsFromWorkflowResponse(data) {
  if (!data || !data.ok) return;
  if (data.tool === "lerobot.record.start" && datasetInput) {
    const nextDataset = data.dataset_repo_id || datasetRepoValueFromPath(data.dataset_path || "");
    if (nextDataset) datasetInput.value = nextDataset;
  }
  if (data.tool === "lerobot.train.start") {
    const config = (data.training && data.training.config) || {};
    const nextOutput = data.output_dir || config.output_dir || "";
    if (nextOutput && outputDirInput) {
      outputDirInput.dataset.lastRunOutputDir = nextOutput;
      outputDirInput.value = stripGeneratedPathSuffixes(nextOutput);
    }
    if (config.job_name && jobNameInput) jobNameInput.value = config.job_name;
  }
}

function policyFields(inputEl = policyInput, selectEl = policySelect) {
  const selected = selectEl ? selectEl.value : "";
  const raw = inputEl && inputEl.value.trim() ? inputEl.value.trim() : selected;
  const split = splitPathOrRepo(raw);
  return {
    policy_path: split.path,
    policy_checkpoint_path: split.path && !split.path.startsWith("fake://") ? split.path : "",
    policy_repo_id: split.repo,
  };
}

function rolloutPolicyFields() {
  return policyFields(rolloutPolicyInput || policyInput);
}

function manipulationPolicyFields() {
  return policyFields(manipulationPolicyInput || rolloutPolicyInput || policyInput, manipulationPolicySelect || policySelect);
}

function parseJsonText(inputEl, fallback = {}) {
  const raw = inputEl ? String(inputEl.value || "").trim() : "";
  if (!raw) return fallback;
  try {
    return JSON.parse(raw);
  } catch (err) {
    return { parse_error: String(err), raw };
  }
}

function wandbLocalPortValue() {
  const raw = trainWandbBaseUrlInput ? String(trainWandbBaseUrlInput.value || "").trim() : "";
  if (!raw) return 8081;
  try {
    const parsed = new URL(raw);
    return parsed.port ? Number(parsed.port) : 8081;
  } catch (_err) {
    const match = raw.match(/:(\d+)(?:\/)?$/);
    return match ? Number(match[1]) : 8081;
  }
}

function basePayload(overrides = {}) {
  const datasetValue = datasetInput ? datasetInput.value.trim() : "";
  const datasetSplit = splitPathOrRepo(datasetValue);
  const policy = policyFields();
  return {
    mode: modeSelect ? modeSelect.value : "test",
    runtime_mode: modeSelect ? modeSelect.value : "test",
    profile_id: profileSelect ? profileSelect.value : "",
    observation_pipeline_id: observationPipelineSelect ? observationPipelineSelect.value : "raw_depth_adapter",
    task_instruction: taskInput ? taskInput.value : DEFAULT_LEROBOT_TASK_INSTRUCTION,
    dataset_root: datasetRootInput ? datasetRootInput.value.trim() : "",
    dataset_repo_id: datasetSplit.repo || lastWorkflowDefaults.dataset_repo_id || "",
    dataset_path: datasetSplit.path,
    policy_path: policy.policy_path,
    policy_checkpoint_path: policy.policy_checkpoint_path,
    policy_pretrained_path: trainSourcePolicyInput ? trainSourcePolicyInput.value.trim() : "",
    policy_type: policyTypeInput ? policyTypeInput.value || "act" : "act",
    output_dir: outputDirInput ? outputDirInput.value.trim() : "",
    job_name: jobNameInput ? jobNameInput.value.trim() : lastWorkflowDefaults.job_name || trainNameFromDatasetRepo(datasetValue),
    device: deviceInput ? deviceInput.value || "cuda" : "cuda",
    seed: numberValue(trainSeedInput, null),
    batch_size: trainNumberValue(trainBatchSizeInput, "batch_size", 8),
    steps: trainNumberValue(trainStepsInput, "steps", 100000),
    num_workers: trainNumberValue(trainWorkersInput, "num_workers", 4),
    eval_freq: trainNumberValue(trainEvalFreqInput, "eval_freq", 20000),
    log_freq: trainNumberValue(trainLogFreqInput, "log_freq", 200),
    save_freq: trainNumberValue(trainSaveFreqInput, "save_freq", 20000),
    save_checkpoint: boolValue(trainSaveCheckpointInput),
    train_background: trainBackgroundInput ? boolValue(trainBackgroundInput) : true,
    eval_batch_size: numberValue(trainEvalBatchInput, null),
    optimizer_type: trainOptimizerInput ? trainOptimizerInput.value || "" : "",
    optimizer_lr: numberValue(trainLrInput, null),
    optimizer_weight_decay: numberValue(trainWeightDecayInput, null),
    optimizer_grad_clip_norm: numberValue(trainGradClipInput, null),
    scheduler_type: trainSchedulerInput ? trainSchedulerInput.value : "",
    scheduler_warmup_steps: numberValue(trainWarmupInput, null),
    scheduler_decay_steps: numberValue(trainDecayStepsInput, null),
    scheduler_peak_lr: numberValue(trainPeakLrInput, null),
    scheduler_decay_lr: numberValue(trainDecayLrInput, null),
    policy_repo_id: trainPolicyRepoInput && trainPolicyRepoInput.value.trim()
      ? trainPolicyRepoInput.value.trim()
      : policy.policy_repo_id,
    policy_n_obs_steps: numberValue(trainNObsInput, null),
    policy_chunk_size: numberValue(trainChunkInput, null),
    policy_n_action_steps: numberValue(trainNActionInput, null),
    policy_use_amp: boolValue(trainUseAmpInput),
    wandb_enable: boolValue(trainWandbInput),
    wandb_project: trainWandbProjectInput ? trainWandbProjectInput.value.trim() : "",
    wandb_mode: trainWandbModeInput ? trainWandbModeInput.value || "" : "",
    wandb_base_url: trainWandbBaseUrlInput ? trainWandbBaseUrlInput.value.trim() : "",
    wandb_local_port: wandbLocalPortValue(),
    train_extra_args: trainExtraArgs(),
    dataset_include_real_original: boolValue(datasetIncludeRealOriginalInput),
    dataset_include_isaac_rgbd: boolValue(datasetIncludeIsaacRgbdInput),
    dataset_include_isaac_augmentation: boolValue(datasetIncludeIsaacAugmentationInput),
    dataset_include_isaac_lab_synthetic: boolValue(datasetIncludeIsaacLabSyntheticInput),
    dataset_mix_real_original_weight: numberValue(datasetMixRealWeightInput, 1),
    dataset_mix_isaac_rgbd_weight: numberValue(datasetMixIsaacRgbdWeightInput, 0.6),
    dataset_mix_isaac_augmentation_weight: numberValue(datasetMixIsaacAugmentationWeightInput, 0),
    dataset_mix_isaac_lab_synthetic_weight: numberValue(datasetMixIsaacLabSyntheticWeightInput, 0.35),
    dataset_mix_real_original_max_samples: numberValue(datasetMixRealMaxInput, null),
    dataset_mix_isaac_rgbd_max_samples: numberValue(datasetMixIsaacRgbdMaxInput, null),
    dataset_mix_isaac_augmentation_max_samples: numberValue(datasetMixIsaacAugmentationMaxInput, null),
    dataset_mix_isaac_lab_synthetic_max_samples: numberValue(datasetMixIsaacLabSyntheticMaxInput, null),
    dataset_mix_seed: numberValue(datasetMixSeedInput, 0),
    dataset_exclude_flagged_episodes: excludeFlaggedEpisodesValue(),
    fidelity_weighting_enabled: boolValue(fidelityWeightingEnabledInput),
    fidelity_real_original_weight: numberValue(fidelityRealWeightInput, 1),
    fidelity_isaac_rgbd_weight: numberValue(fidelityIsaacRgbdWeightInput, 0.55),
    fidelity_isaac_augmentation_weight: numberValue(fidelityIsaacAugmentationWeightInput, 0),
    fidelity_isaac_lab_synthetic_weight: numberValue(fidelityIsaacLabSyntheticWeightInput, 0.25),
    fps: numberValue(fpsInput, 15),
    camera_fps: numberValue(cameraFpsInput, 15),
    warmup_s: 2,
    episode_s: numberValue(episodeTimeInput, 60),
    reset_s: numberValue(resetTimeInput, 30),
    num_episodes: numberValue(episodesInput, DEFAULT_RECORD_NUM_EPISODES),
    tts_engine: ttsEngineInput ? ttsEngineInput.value || "piper" : "piper",
    tts_rate: numberValue(ttsRateInput, -35),
    display_data: boolValue(displayDataInput),
    camera_enabled: true,
    resume: false,
    push_to_hub: boolValue(pushHubInput),
    confirm_live_execute: boolValue(confirmLiveInput),
    episode_index: primaryEpisodeIndexValue(),
    episode_indices: episodeIndicesValue(),
    visualization_tool: visualizationToolInput ? visualizationToolInput.value || "rerun" : "rerun",
    visualization_mode: visualizationModeInput ? visualizationModeInput.value || "distant" : "distant",
    visualization_batch_size: numberValue(visualizationBatchSizeInput, 32),
    visualization_num_workers: numberValue(visualizationWorkersInput, 4),
    visualization_web_port: numberValue(visualizationWebPortInput, 9092),
    visualization_ws_port: numberValue(visualizationWsPortInput, 9089),
    visualization_tolerance_s: numberValue(visualizationToleranceInput, 0.0001),
    visualization_save: boolValue(visualizationSaveInput),
    visualization_output_dir: visualizationOutputDirInput ? visualizationOutputDirInput.value.trim() : "",
    isaac_data_augmentation_profile: isaacAugmentProfileInput ? isaacAugmentProfileInput.value || "conservative" : "conservative",
    isaac_data_augmentation_variants: numberValue(isaacAugmentVariantsInput, 8),
    isaac_data_augmentation_max_frames: numberValue(isaacAugmentMaxFramesInput, 200),
    isaac_data_augmentation_seed: numberValue(isaacAugmentSeedInput, 0),
    isaac_data_augmentation_cameras: isaacAugmentCamerasInput
      ? isaacAugmentCamerasInput.value.trim() || "top,front,right"
      : "top,front,right",
    isaac_data_augmentation_output_dir: isaacAugmentOutputDirInput ? isaacAugmentOutputDirInput.value.trim() : "",
    isaac_data_augmentation_image_enabled: boolValue(isaacAugmentImageInput),
    isaac_data_augmentation_photometric_enabled: boolValue(isaacAugmentPhotometricInput),
    isaac_data_augmentation_sensor_noise_enabled: boolValue(isaacAugmentSensorNoiseInput),
    isaac_data_augmentation_depth_noise_enabled: boolValue(isaacAugmentDepthNoiseInput),
    isaac_data_augmentation_render_domain_enabled: boolValue(isaacAugmentRenderDomainInput),
    isaac_data_augmentation_camera_pose_enabled: boolValue(isaacAugmentCameraPoseInput),
    isaac_data_augmentation_rgb_strength: numberValue(isaacAugmentRgbStrengthInput, 1),
    isaac_data_augmentation_depth_strength: numberValue(isaacAugmentDepthStrengthInput, 1),
    isaac_data_augmentation_render_domain_strength: numberValue(isaacAugmentRenderDomainStrengthInput, 1),
    isaac_data_augmentation_camera_pose_strength: numberValue(isaacAugmentCameraPoseStrengthInput, 1),
    isaac_data_augmentation_preview_count: numberValue(isaacAugmentPreviewCountInput, 20),
    isaac_mirror_enabled: boolValue(isaacMirrorEnabledInput),
    isaac_mirror_endpoint: isaacMirrorEndpointInput ? isaacMirrorEndpointInput.value.trim() : "http://127.0.0.1:8766/joints",
    isaac_mirror_sample_hz: numberValue(isaacMirrorHzInput, 15),
    isaac_mirror_timeout_s: numberValue(isaacMirrorTimeoutInput, 0.5),
    isaac_mirror_max_samples: numberValue(isaacMirrorMaxSamplesInput, null),
    isaac_mirror_receiver_launch_mode: "isaac_extension",
    active_robot_cam_enabled: boolValue(activeRobotCamEnabledInput),
    active_robot_cam_record_start_enabled: boolValue(activeRobotCamRecordStartInput),
    active_robot_cam_camera_priority: "d405,d455f",
    active_robot_cam_primary_camera_key: "wrist",
    active_robot_cam_fallback_camera_key: "top",
    active_robot_cam_resume_mode: "auto",
    active_robot_cam_d455f_fallback_enabled: true,
    active_robot_cam_trigger_on_first_action: true,
    observation: parseObservation(),
    dry_run: (modeSelect ? modeSelect.value : "test") !== "live",
    ...overrides,
  };
}

function rolloutPayload(overrides = {}) {
  const payload = basePayload(overrides);
  const policy = rolloutPolicyFields();
  const rolloutPolicyType = selectedRolloutPolicyType();
  const rolloutPolicyTypeKey = rolloutPolicyType.toLowerCase();
  payload.policy_path = policy.policy_path;
  payload.policy_checkpoint_path = policy.policy_checkpoint_path;
  payload.policy_repo_id = policy.policy_path ? "" : policy.policy_repo_id;
  payload.policy_type = rolloutPolicyType;
  payload.task_instruction = rolloutInstructionInput && rolloutInstructionInput.value.trim()
    ? rolloutInstructionInput.value.trim()
    : DEFAULT_PI05_ROLLOUT_TASK;
  const rolloutDurationRaw = rolloutDurationInput && rolloutDurationInput.value.trim()
    ? rolloutDurationInput.value.trim()
    : "";
  if (rolloutDurationRaw) {
    payload.episode_s = Number(rolloutDurationRaw);
    payload.num_episodes = 1;
    payload.continuous_rollout = false;
  } else {
    payload.num_episodes = 1;
    payload.continuous_rollout = true;
  }
  payload.rollout_action_clamp = rolloutActionClampInput ? boolValue(rolloutActionClampInput) : false;
  payload.plc_rollout_stop_enabled = boolValue(plcRolloutStopInput);
  payload.rollout_max_relative_target = numberValue(rolloutMaxRelativeTargetInput, 5);
  payload.rollout_shoulder_lift_backstop = rolloutShoulderLiftBackstopInput ? boolValue(rolloutShoulderLiftBackstopInput) : true;
  payload.rollout_temporal_ensemble = rolloutPolicyTypeKey === "act" && (rolloutTemporalEnsembleInput ? boolValue(rolloutTemporalEnsembleInput) : true);
  payload.rollout_temporal_ensemble_coeff = numberValue(rolloutTemporalCoeffInput, 0.01);
  payload.rollout_inference_type = rolloutPolicyTypeKey === "pi05" ? "rtc" : "";
  payload.rollout_rtc_execution_horizon = rolloutPolicyTypeKey === "pi05" ? numberValue(rolloutRtcHorizonInput, 20) : null;
  payload.rollout_rtc_max_guidance_weight = rolloutPolicyTypeKey === "pi05" ? numberValue(rolloutRtcGuidanceInput, 1.0) : null;
  payload.rollout_action_queue_size_to_get_new_actions = rolloutPolicyTypeKey === "pi05" ? numberValue(rolloutActionQueueInput, 60) : null;
  return payload;
}

function currentRolloutProfile() {
  const policy = rolloutPolicyFields();
  const policyType = selectedRolloutPolicyType();
  const policyTypeKey = policyType.toLowerCase();
  const durationRaw = rolloutDurationInput && rolloutDurationInput.value.trim()
    ? rolloutDurationInput.value.trim()
    : "";
  return {
    profile_id: profileSelect ? profileSelect.value : "",
    observation_pipeline_id: observationPipelineSelect ? observationPipelineSelect.value : "",
    policy_type: policyType,
    policy_path: policy.policy_path,
    policy_checkpoint_path: policy.policy_checkpoint_path,
    policy_repo_id: policy.policy_path ? "" : policy.policy_repo_id,
    task_instruction: rolloutInstructionInput && rolloutInstructionInput.value.trim()
      ? rolloutInstructionInput.value.trim()
      : DEFAULT_PI05_ROLLOUT_TASK,
    continuous_rollout: !durationRaw,
    max_duration_s: durationRaw ? Number(durationRaw) : null,
    rollout_action_clamp: rolloutActionClampInput ? boolValue(rolloutActionClampInput) : false,
    rollout_max_relative_target: numberValue(rolloutMaxRelativeTargetInput, 5),
    rollout_shoulder_lift_backstop: rolloutShoulderLiftBackstopInput ? boolValue(rolloutShoulderLiftBackstopInput) : true,
    rollout_temporal_ensemble: policyTypeKey === "act" && (rolloutTemporalEnsembleInput ? boolValue(rolloutTemporalEnsembleInput) : true),
    rollout_temporal_ensemble_coeff: numberValue(rolloutTemporalCoeffInput, 0.01),
    rollout_inference_type: policyTypeKey === "pi05" ? "rtc" : "",
    rollout_rtc_execution_horizon: policyTypeKey === "pi05" ? numberValue(rolloutRtcHorizonInput, 20) : null,
    rollout_rtc_max_guidance_weight: policyTypeKey === "pi05" ? numberValue(rolloutRtcGuidanceInput, 1.0) : null,
    rollout_action_queue_size_to_get_new_actions: policyTypeKey === "pi05" ? numberValue(rolloutActionQueueInput, 60) : null,
    observation: parseObservation(),
  };
}

function savedPolicyOptionLabel(value, policyType = "") {
  const clean = String(value || "").trim();
  const checkpointMatch = clean.match(/\/checkpoints\/([^/]+)\/pretrained_model\/?$/);
  const checkpoint = checkpointMatch ? checkpointMatch[1] : "";
  const typeLabel = String(policyType || inferPolicyTypeFromPolicy(clean)).trim();
  const parts = ["Saved rollout"];
  if (typeLabel) parts.push(typeLabel);
  if (checkpoint) parts.push(`checkpoint ${checkpoint}`);
  return parts.join(" · ");
}

function ensureSavedPolicyOption(selectEl, value, policyType = "") {
  const clean = String(value || "").trim();
  if (!selectEl || !clean) return null;
  let option = Array.from(selectEl.options || []).find((item) => item.value === clean) || null;
  if (!option) {
    option = document.createElement("option");
    option.value = clean;
    selectEl.appendChild(option);
  }
  option.textContent = savedPolicyOptionLabel(clean, policyType);
  option.dataset.policyType = policyType || inferPolicyTypeFromPolicy(clean);
  option.dataset.savedRollout = "1";
  return option;
}

function applyRolloutProfile(profile, force = false) {
  if (!profile || (rolloutProfileLoaded && !force)) return;
  rolloutProfileLoaded = true;
  const policyRef = profile.policy_path || profile.policy_checkpoint_path || profile.policy_repo_id || "";
  setInputValue(rolloutPolicyTypeInput, profile.policy_type || "smolvla");
  setInputValue(rolloutPolicyInput, policyRef);
  if (policySelect && policyRef) {
    ensureSavedPolicyOption(policySelect, policyRef, profile.policy_type || "");
    policySelect.value = policyRef;
  }
  setInputValue(rolloutInstructionInput, profile.task_instruction || DEFAULT_PI05_ROLLOUT_TASK);
  if (rolloutDurationInput) {
    rolloutDurationInput.value = profile.continuous_rollout === false && profile.max_duration_s
      ? String(profile.max_duration_s)
      : "";
  }
  setCheckboxValue(rolloutActionClampInput, profile.rollout_action_clamp);
  setInputValue(rolloutMaxRelativeTargetInput, profile.rollout_max_relative_target);
  setCheckboxValue(rolloutShoulderLiftBackstopInput, profile.rollout_shoulder_lift_backstop);
  setCheckboxValue(rolloutTemporalEnsembleInput, profile.rollout_temporal_ensemble);
  setInputValue(rolloutTemporalCoeffInput, profile.rollout_temporal_ensemble_coeff);
  setInputValue(rolloutRtcHorizonInput, profile.rollout_rtc_execution_horizon);
  setInputValue(rolloutRtcGuidanceInput, profile.rollout_rtc_max_guidance_weight);
  setInputValue(rolloutActionQueueInput, profile.rollout_action_queue_size_to_get_new_actions);
  if (observationInput && profile.observation && typeof profile.observation === "object") {
    observationInput.value = JSON.stringify(profile.observation);
  }
  syncRolloutPolicyOptions();
}

async function refreshRolloutProfile({ force = false } = {}) {
  try {
    const res = await fetch("/api/lerobot/rollout/config");
    const data = await res.json();
    applyRolloutProfile(data.profile || {}, force);
    return data;
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

const MANIPULATION_TASK_PRESETS = {
  transfer_to_utm: {
    source: "3dp_output_area",
    target: "utm_fixture",
    instruction: "Move the printed specimen from the 3D printer pickup area to the UTM fixture datum, release safely, retreat to standby_clear_of_utm, then wait for Vision verification.",
    observation: { observation_id: "manual-transfer", anomaly: false, transfer_readiness: { ready: true, pose_confidence: 0.82 } },
  },
  clear_utm_to_disposal: {
    source: "utm_fixture",
    target: "discard_bin",
    instruction: "After the UTM test is complete and the fixture is safe, move the tested specimen from the UTM fixture to the discard bin, release fully, retreat to standby_clear_of_utm, then wait for Vision verification.",
    observation: { observation_id: "manual-clear-utm", anomaly: false, transfer_readiness: { ready: true, pose_confidence: 0.82 } },
  },
};

function selectedManipulationTaskId() {
  const value = manipulationTaskIdInput ? manipulationTaskIdInput.value : "transfer_to_utm";
  return MANIPULATION_TASK_PRESETS[value] ? value : "transfer_to_utm";
}

function manipulationDefaultInstruction(taskId, specimenId, sourceLocation, targetLocation) {
  const preset = MANIPULATION_TASK_PRESETS[taskId] || MANIPULATION_TASK_PRESETS.transfer_to_utm;
  if (taskId === "clear_utm_to_disposal") {
    return `Move ${specimenId} from ${sourceLocation} to ${targetLocation}, release it into the discard bin, retreat to standby_clear_of_utm, then request Vision verification.`;
  }
  return `Move ${specimenId} from ${sourceLocation} to ${targetLocation}, place the flat compression face on the UTM datum, release, retreat to standby_clear_of_utm, then request Vision verification.`;
}

function defaultManipulationTaskProfile(taskId = selectedManipulationTaskId()) {
  const preset = MANIPULATION_TASK_PRESETS[taskId] || MANIPULATION_TASK_PRESETS.transfer_to_utm;
  return {
    manipulation_strategy: "lerobot_policy",
    policy_backend: "lerobot_cli",
    policy_type: "smolvla",
    policy_path: "",
    policy_checkpoint_path: "",
    policy_repo_id: "",
    task_instruction: preset.instruction,
    source_location: preset.source,
    target_location: preset.target,
    continuous_rollout: true,
    max_duration_s: null,
    rollout_action_clamp: false,
    rollout_max_relative_target: 5,
    rollout_shoulder_lift_backstop: true,
    rollout_temporal_ensemble: true,
    rollout_temporal_ensemble_coeff: 0.01,
    rollout_inference_type: "",
    rollout_rtc_execution_horizon: 20,
    rollout_rtc_max_guidance_weight: 1.0,
    rollout_action_queue_size_to_get_new_actions: 60,
    observation: preset.observation,
  };
}

function applyManipulationTaskProfile(taskId, profile = {}) {
  const presetProfile = defaultManipulationTaskProfile(taskId);
  const merged = { ...presetProfile, ...(profile || {}) };
  activeManipulationTaskId = taskId;
  const policyRef = merged.policy_path || merged.policy_checkpoint_path || merged.policy_repo_id || "";
  setInputValue(manipulationPolicyTypeInput, merged.policy_type || "smolvla");
  setInputValue(manipulationPolicyInput, policyRef);
  if (manipulationPolicySelect && policyRef) {
    ensureSavedPolicyOption(manipulationPolicySelect, policyRef, merged.policy_type || "");
    manipulationPolicySelect.value = policyRef;
  }
  setInputValue(manipulationInstructionInput, merged.task_instruction || presetProfile.task_instruction);
  if (manipulationDurationInput) {
    manipulationDurationInput.value = merged.continuous_rollout === false && merged.max_duration_s ? String(merged.max_duration_s) : "";
  }
  setCheckboxValue(manipulationActionClampInput, merged.rollout_action_clamp);
  setInputValue(manipulationMaxRelativeTargetInput, merged.rollout_max_relative_target);
  setCheckboxValue(manipulationShoulderLiftBackstopInput, merged.rollout_shoulder_lift_backstop);
  setCheckboxValue(manipulationTemporalEnsembleInput, merged.rollout_temporal_ensemble);
  setInputValue(manipulationTemporalCoeffInput, merged.rollout_temporal_ensemble_coeff);
  setInputValue(manipulationRtcHorizonInput, merged.rollout_rtc_execution_horizon);
  setInputValue(manipulationRtcGuidanceInput, merged.rollout_rtc_max_guidance_weight);
  setInputValue(manipulationActionQueueInput, merged.rollout_action_queue_size_to_get_new_actions);
  if (manipulationObservationInput) {
    manipulationObservationInput.value = JSON.stringify(merged.observation || presetProfile.observation);
  }
  syncManipulationPolicyOptions();
}

async function handleManipulationTaskChange() {
  if (activeManipulationTaskId && MANIPULATION_TASK_PRESETS[activeManipulationTaskId]) {
    manipulationTaskProfiles[activeManipulationTaskId] = currentManipulationTaskProfile(activeManipulationTaskId);
  }
  const taskId = selectedManipulationTaskId();
  applyManipulationTaskProfile(taskId, manipulationTaskProfiles[taskId] || defaultManipulationTaskProfile(taskId));
  await persistManipulationTaskProfile();
}

function currentManipulationTaskProfile(taskId = selectedManipulationTaskId()) {
  const preset = MANIPULATION_TASK_PRESETS[taskId] || MANIPULATION_TASK_PRESETS.transfer_to_utm;
  const policy = manipulationPolicyFields();
  const policyType = selectedManipulationPolicyType() || "smolvla";
  const durationRaw = manipulationDurationInput && manipulationDurationInput.value.trim()
    ? manipulationDurationInput.value.trim()
    : "";
  const continuous = !durationRaw;
  const policyTypeKey = policyType.toLowerCase();
  return {
    manipulation_strategy: "lerobot_policy",
    policy_backend: "lerobot_cli",
    policy_type: policyType,
    policy_path: policy.policy_path,
    policy_checkpoint_path: policy.policy_checkpoint_path,
    policy_repo_id: policy.policy_path ? "" : policy.policy_repo_id,
    task_instruction: manipulationInstructionInput && manipulationInstructionInput.value.trim()
      ? manipulationInstructionInput.value.trim()
      : preset.instruction,
    source_location: preset.source,
    target_location: preset.target,
    continuous_rollout: continuous,
    max_duration_s: continuous ? null : Number(durationRaw),
    rollout_action_clamp: manipulationActionClampInput ? boolValue(manipulationActionClampInput) : false,
    rollout_max_relative_target: numberValue(manipulationMaxRelativeTargetInput, 5),
    rollout_shoulder_lift_backstop: manipulationShoulderLiftBackstopInput ? boolValue(manipulationShoulderLiftBackstopInput) : true,
    rollout_temporal_ensemble: policyTypeKey === "act" && (manipulationTemporalEnsembleInput ? boolValue(manipulationTemporalEnsembleInput) : true),
    rollout_temporal_ensemble_coeff: numberValue(manipulationTemporalCoeffInput, 0.01),
    rollout_inference_type: policyTypeKey === "pi05" ? "rtc" : "",
    rollout_rtc_execution_horizon: policyTypeKey === "pi05" ? numberValue(manipulationRtcHorizonInput, 20) : null,
    rollout_rtc_max_guidance_weight: policyTypeKey === "pi05" ? numberValue(manipulationRtcGuidanceInput, 1.0) : null,
    rollout_action_queue_size_to_get_new_actions: policyTypeKey === "pi05" ? numberValue(manipulationActionQueueInput, 60) : null,
    observation: parseJsonText(manipulationObservationInput, preset.observation),
  };
}

function manipulationRolloutPayload(overrides = {}) {
  const taskId = selectedManipulationTaskId();
  const taskProfile = currentManipulationTaskProfile();
  const payload = basePayload(overrides);
  const taskProfiles = { ...(manipulationTaskProfiles || {}), [taskId]: taskProfile };
  const specimen = overrides.specimen_result && typeof overrides.specimen_result === "object" ? overrides.specimen_result : {};
  payload.policy_type = taskProfile.policy_type;
  payload.policy_path = taskProfile.policy_path;
  payload.policy_checkpoint_path = taskProfile.policy_checkpoint_path;
  payload.policy_repo_id = taskProfile.policy_repo_id;
  payload.task_instruction = taskProfile.task_instruction;
  payload.manipulation_strategy = taskProfile.manipulation_strategy;
  payload.task_id = taskId;
  payload.skill_id = taskId;
  payload.policy_backend = taskProfile.policy_backend;
  payload.fps = numberValue(fpsInput, 15);
  payload.camera_fps = numberValue(cameraFpsInput, 15);
  payload.camera_enabled = true;
  payload.display_data = boolValue(displayDataInput);
  payload.source_location = taskProfile.source_location;
  payload.target_location = taskProfile.target_location;
  payload.observation = taskProfile.observation;
  payload.continuous_rollout = taskProfile.continuous_rollout;
  payload.max_duration_s = taskProfile.max_duration_s;
  if (taskProfile.continuous_rollout) {
    payload.num_episodes = 1;
  } else {
    payload.episode_s = taskProfile.max_duration_s;
    payload.num_episodes = 1;
  }
  payload.rollout_action_clamp = taskProfile.rollout_action_clamp;
  payload.plc_rollout_stop_enabled = boolValue(plcRolloutStopInput);
  payload.rollout_max_relative_target = taskProfile.rollout_max_relative_target;
  payload.rollout_shoulder_lift_backstop = taskProfile.rollout_shoulder_lift_backstop;
  payload.rollout_temporal_ensemble = taskProfile.rollout_temporal_ensemble;
  payload.rollout_temporal_ensemble_coeff = taskProfile.rollout_temporal_ensemble_coeff;
  payload.rollout_inference_type = taskProfile.rollout_inference_type;
  payload.rollout_rtc_execution_horizon = taskProfile.rollout_rtc_execution_horizon;
  payload.rollout_rtc_max_guidance_weight = taskProfile.rollout_rtc_max_guidance_weight;
  payload.rollout_action_queue_size_to_get_new_actions = taskProfile.rollout_action_queue_size_to_get_new_actions;
  payload.task_profiles = taskProfiles;
  payload.specimen_result = {
    ok: true,
    specimen_id: specimen.specimen_id || `${taskId}-manual-specimen`,
    candidate_id: specimen.candidate_id || `${taskId}-manual-candidate`,
    handoff_status: "ready",
    stl_path: specimen.stl_path || "",
    sliced_path: specimen.sliced_path || "",
  };
  return payload;
}

function manipulationAgentPayload(overrides = {}) {
  return manipulationRolloutPayload(overrides);
}

function applyDevicePLCStopAvailability(status = {}) {
  if (!plcRolloutStopInput) return false;
  const available = status.connection_state === "online"
    && status.plc_layer_active === true
    && status.fast_stop_monitor?.running === true;
  plcRolloutStopInput.disabled = !available;
  if (!available) plcRolloutStopInput.checked = false;
  if (plcRolloutStopStatusEl) {
    plcRolloutStopStatusEl.textContent = available ? "online" : "offline";
  }
  return available;
}

async function refreshDevicePLCStopAvailability() {
  try {
    const response = await fetch("/api/plc/status", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`PLC status HTTP ${response.status}`);
    const status = await response.json();
    return applyDevicePLCStopAvailability(status);
  } catch (_err) {
    return applyDevicePLCStopAvailability({});
  }
}

async function persistManipulationTaskProfile({ statusTarget = null, render = false, refresh = false } = {}) {
  const taskId = selectedManipulationTaskId();
  manipulationTaskProfiles[taskId] = currentManipulationTaskProfile(taskId);
  const payload = manipulationAgentPayload();
  const target = statusTarget || $("lerobot-manipulation-action-status");
  setActionStatus(target, "running", "manipulation task save", { status: "saving", task_id: taskId });

  const save = async () => {
    try {
      const data = await postJson("/api/lerobot/manipulation-agent/config", payload);
      if (data && data.profile && data.profile.task_profiles) {
        manipulationTaskProfiles = { ...data.profile.task_profiles };
      }
      if (data && data.ok) {
        manipulationProfileLoaded = true;
        applyManipulationProfile(data.profile || {}, true);
      }
      if (render) renderResult("manipulation defaults save", data);
      setActionStatus(target, data && data.ok ? "ok" : "error", "manipulation task save", data);
      if (refresh) await refreshConfig();
      return data;
    } catch (err) {
      const error = { ok: false, status: "request_failed", error: String(err), task_id: taskId };
      if (render) renderResult("manipulation defaults save", error);
      setActionStatus(target, "error", "manipulation task save", error);
      return error;
    }
  };

  manipulationProfileSavePromise = manipulationProfileSavePromise.catch(() => null).then(save);
  return manipulationProfileSavePromise;
}

function setInputValue(input, value) {
  if (!input || value === undefined || value === null) return;
  input.value = String(value);
}

function setCheckboxValue(input, value) {
  if (!input || value === undefined || value === null) return;
  input.checked = Boolean(value);
}

function applyManipulationProfile(profile, force = false) {
  if (!profile || (manipulationProfileLoaded && !force)) return;
  manipulationProfileLoaded = true;
  manipulationTaskProfiles = profile.task_profiles && typeof profile.task_profiles === "object" ? { ...profile.task_profiles } : {};
  const taskId = MANIPULATION_TASK_PRESETS[profile.task_id] ? profile.task_id : selectedManipulationTaskId();
  setInputValue(manipulationTaskIdInput, taskId);
  const taskProfile = manipulationTaskProfiles[taskId] || profile;
  applyManipulationTaskProfile(taskId, taskProfile);
  if (deviceInput && profile.device) deviceInput.value = profile.device;
  if (fpsInput && profile.fps) fpsInput.value = String(profile.fps);
  if (cameraFpsInput && profile.camera_fps) cameraFpsInput.value = String(profile.camera_fps);
}

async function refreshManipulationProfile({ force = false } = {}) {
  try {
    const res = await fetch("/api/lerobot/manipulation-agent/config");
    const data = await res.json();
    applyManipulationProfile(data.profile || {}, force);
    return data;
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

function recordPayload(overrides = {}) {
  return basePayload({ dataset_repo_id: recordDatasetRepoValue(), resume: recordResumeValue(), ...overrides });
}

function trainPayload(overrides = {}) {
  return basePayload({ dataset_repo_id: trainDatasetRepoValue(), resume: boolValue(trainResumeInput), ...overrides });
}

function prepareLocalWandbForTraining() {
  if (trainWandbBaseUrlInput && !trainWandbBaseUrlInput.value.trim()) {
    trainWandbBaseUrlInput.value = "http://127.0.0.1:8081";
  }
  if (trainWandbInput) trainWandbInput.checked = true;
  if (trainWandbModeInput) trainWandbModeInput.value = "local";
}

function wandbLocalPayload(overrides = {}) {
  const payload = basePayload(overrides);
  payload.wandb_base_url = trainWandbBaseUrlInput && trainWandbBaseUrlInput.value.trim()
    ? trainWandbBaseUrlInput.value.trim()
    : "http://127.0.0.1:8081";
  payload.wandb_local_port = wandbLocalPortValue();
  return payload;
}

function renderWandbLocalApiKeyStatus(data = {}) {
  if (!wandbApiKeyStatusEl) return;
  if (data.ok === false) {
    wandbApiKeyStatusEl.textContent = `W&B local API key status failed: ${data.message || data.error || "unknown error"}`;
    return;
  }
  wandbApiKeyStatusEl.textContent = data.has_key
    ? `W&B local API key saved · source=${data.source || "memory"}`
    : "W&B local API key is not saved.";
}

async function refreshWandbLocalApiKeyStatus() {
  try {
    const res = await fetch("/api/lerobot/wandb-local/api-key");
    const data = await res.json();
    renderWandbLocalApiKeyStatus(data);
  } catch (err) {
    renderWandbLocalApiKeyStatus({ ok: false, error: String(err) });
  }
}

async function saveWandbLocalApiKey(statusTarget = null) {
  const apiKey = trainWandbApiKeyInput ? trainWandbApiKeyInput.value.trim() : "";
  if (!apiKey) {
    renderWandbLocalApiKeyStatus({ ok: false, message: "enter an API key before saving" });
    return;
  }
  renderWandbLocalApiKeyStatus({ ok: true, has_key: false, source: "saving" });
  try {
    const data = await postJson("/api/lerobot/wandb-local/api-key", { api_key: apiKey, enabled: true });
    if (data.ok === false) {
      renderWandbLocalApiKeyStatus(data);
      if (statusTarget) setActionStatus(statusTarget, "error", "wandb local api key save", data);
      return;
    }
    if (trainWandbApiKeyInput) trainWandbApiKeyInput.value = "";
    renderWandbLocalApiKeyStatus(data);
    if (statusTarget) setActionStatus(statusTarget, "ok", "wandb local api key save", data);
  } catch (err) {
    const data = { ok: false, error: String(err) };
    renderWandbLocalApiKeyStatus(data);
    if (statusTarget) setActionStatus(statusTarget, "error", "wandb local api key save", data);
  }
}

function visualizationPayload(overrides = {}) {
  const payload = basePayload(overrides);
  const explicitPath = visualizationPathInput && visualizationPathInput.value.trim() ? visualizationPathInput.value.trim() : "";
  if (explicitPath) {
    payload.dataset_path = explicitPath;
    payload.dataset_repo_id = "";
  }
  return payload;
}

function isaacAugmentationPayload(overrides = {}) {
  return visualizationPayload({ isaac_data_augmentation_async: true, ...overrides });
}

function isaacSyntheticPayload(overrides = {}) {
  const payload = visualizationPayload(overrides);
  const cameraList = isaacAugmentCamerasInput
    ? isaacAugmentCamerasInput.value.split(",").map((item) => item.trim()).filter(Boolean)
    : ["top", "front", "right"];
  return {
    ...payload,
    pipeline_mode: isaacSyntheticPipelineModeInput
      ? isaacSyntheticPipelineModeInput.value || "isaac_lab_replicator"
      : "isaac_lab_replicator",
    fallback_policy: isaacSyntheticFallbackPolicyInput
      ? isaacSyntheticFallbackPolicyInput.value || "block_on_primary_failure"
      : "block_on_primary_failure",
    source_intent: isaacSyntheticSourceIntentInput
      ? isaacSyntheticSourceIntentInput.value || "train_ready_success_only"
      : "train_ready_success_only",
    isaac_lab_path: isaacSyntheticIsaacLabPathInput ? isaacSyntheticIsaacLabPathInput.value.trim() : "",
    isaac_sim_python: isaacSyntheticIsaacSimPythonInput ? isaacSyntheticIsaacSimPythonInput.value.trim() : "",
    stage_path: isaacSyntheticStagePathInput ? isaacSyntheticStagePathInput.value.trim() : "",
    cameras: cameraList.length ? cameraList : ["top", "front", "right"],
    max_source_frames: numberValue(isaacAugmentMaxFramesInput, 5000),
    attempts_per_source_frame: numberValue(isaacAugmentVariantsInput, 1),
    seed: numberValue(isaacAugmentSeedInput, 42),
    augmentation_profile: isaacAugmentProfileInput ? isaacAugmentProfileInput.value || "conservative" : "conservative",
    rgb_strength: numberValue(isaacAugmentRgbStrengthInput, 0.15),
    depth_strength: numberValue(isaacAugmentDepthStrengthInput, 0.15),
    render_strength: numberValue(isaacAugmentRenderDomainStrengthInput, 0.15),
    camera_pose_strength: numberValue(isaacAugmentCameraPoseStrengthInput, 0.05),
    mimic_trials: numberValue(isaacSyntheticMimicTrialsInput, 3),
    mimic_num_envs: numberValue(isaacSyntheticMimicNumEnvsInput, 3),
    mimic_generation_backend: isaacSyntheticMimicBackendInput
      ? isaacSyntheticMimicBackendInput.value || "official"
      : "official",
    domain_randomization_profile: isaacLabDomainRandomizationProfileInput
      ? isaacLabDomainRandomizationProfileInput.value || "standard"
      : "standard",
    rl_teacher_steps: numberValue(isaacSyntheticRlTeacherStepsInput, 0),
    enable_replicator: boolValue(isaacSyntheticEnableReplicatorInput),
    enable_hdf5_export: boolValue(isaacSyntheticEnableHdf5ExportInput),
    enable_mimic: boolValue(isaacSyntheticEnableMimicInput),
    enable_rl_teacher: boolValue(isaacSyntheticEnableRlTeacherInput),
    isaac_lab_visualize_generation: checkboxValue(isaacLabVisualizeGenerationInput),
    mimic_enable_cameras: checkboxValue(isaacLabMimicCamerasInput),
    dataset_exclude_flagged_episodes: excludeFlaggedEpisodesValue(),
    real_weight: numberValue(datasetMixRealWeightInput, 1),
    isaac_rgbd_weight: numberValue(datasetMixIsaacRgbdWeightInput, 0.6),
    isaac_lab_synthetic_weight: numberValue(datasetMixIsaacLabSyntheticWeightInput, 0.35),
    legacy_sidecar_weight: numberValue(datasetMixIsaacAugmentationWeightInput, 0),
    ...overrides,
  };
}

function setInputValue(input, value) {
  if (input) input.value = String(value);
}

function setCheckboxValue(input, value) {
  if (input) input.checked = Boolean(value);
}

function syncIsaacLabMimicRgbdInputs(value) {
  setCheckboxValue(isaacLabMimicCamerasInput, value);
  setCheckboxValue(isaacLabDomainMimicRgbdInput, value);
}

function excludeFlaggedEpisodesValue() {
  if (datasetExcludeFlaggedEpisodesInput) return boolValue(datasetExcludeFlaggedEpisodesInput);
  if (isaacAugmentExcludeFlaggedEpisodesInput) return boolValue(isaacAugmentExcludeFlaggedEpisodesInput);
  return true;
}

function syncExcludeFlaggedEpisodesCheckboxes(source = null) {
  const value = source ? boolValue(source) : excludeFlaggedEpisodesValue();
  if (datasetExcludeFlaggedEpisodesInput && datasetExcludeFlaggedEpisodesInput !== source) {
    datasetExcludeFlaggedEpisodesInput.checked = value;
  }
  if (isaacAugmentExcludeFlaggedEpisodesInput && isaacAugmentExcludeFlaggedEpisodesInput !== source) {
    isaacAugmentExcludeFlaggedEpisodesInput.checked = value;
  }
}

function applyIsaacLabStandardDefaults() {
  setInputValue(isaacSyntheticIsaacLabPathInput, "/home/jin/IsaacLab");
  setInputValue(isaacSyntheticIsaacSimPythonInput, "/home/jin/IsaacSim/python.sh");
  setInputValue(isaacSyntheticStagePathInput, "/home/jin/autonomous_researcher/sim/robotis_omx/scene/omx_table_layout.usda");
  setInputValue(isaacSyntheticMimicTrialsInput, 3);
  setInputValue(isaacSyntheticMimicNumEnvsInput, 3);
  setInputValue(isaacSyntheticRlTeacherStepsInput, 0);
  setInputValue(isaacAugmentVariantsInput, 8);
  setInputValue(isaacAugmentMaxFramesInput, 5000);
  setInputValue(isaacAugmentSeedInput, 0);
  setInputValue(isaacAugmentRgbStrengthInput, 1);
  setInputValue(isaacAugmentDepthStrengthInput, 1);
  setInputValue(isaacAugmentRenderDomainStrengthInput, 1);
  setInputValue(isaacAugmentCameraPoseStrengthInput, 1);
  setInputValue(datasetMixRealWeightInput, 1);
  setInputValue(datasetMixIsaacRgbdWeightInput, 0.6);
  setInputValue(datasetMixIsaacAugmentationWeightInput, 0);
  setInputValue(datasetMixIsaacLabSyntheticWeightInput, 0.35);
  setCheckboxValue(datasetIncludeRealOriginalInput, true);
  setCheckboxValue(datasetIncludeIsaacRgbdInput, true);
  setCheckboxValue(datasetIncludeIsaacAugmentationInput, false);
  setCheckboxValue(datasetIncludeIsaacLabSyntheticInput, true);
  setCheckboxValue(datasetExcludeFlaggedEpisodesInput, true);
  setCheckboxValue(isaacAugmentExcludeFlaggedEpisodesInput, true);
  syncExcludeFlaggedEpisodesCheckboxes(datasetExcludeFlaggedEpisodesInput);
  setInputValue(fidelityRealWeightInput, 1);
  setInputValue(fidelityIsaacRgbdWeightInput, 0.55);
  setInputValue(fidelityIsaacAugmentationWeightInput, 0);
  setInputValue(fidelityIsaacLabSyntheticWeightInput, 0.25);
  if (isaacSyntheticPipelineModeInput) isaacSyntheticPipelineModeInput.value = "isaac_lab_replicator";
  if (isaacSyntheticFallbackPolicyInput) isaacSyntheticFallbackPolicyInput.value = "block_on_primary_failure";
  if (isaacSyntheticSourceIntentInput) isaacSyntheticSourceIntentInput.value = "train_ready_success_only";
  if (isaacSyntheticMimicBackendInput) isaacSyntheticMimicBackendInput.value = "official";
  if (isaacLabDomainRandomizationProfileInput) isaacLabDomainRandomizationProfileInput.value = "standard";
  if (isaacAugmentProfileInput) isaacAugmentProfileInput.value = "conservative";
  setCheckboxValue(isaacSyntheticEnableReplicatorInput, false);
  setCheckboxValue(isaacSyntheticEnableHdf5ExportInput, true);
  setCheckboxValue(isaacSyntheticEnableMimicInput, true);
  setCheckboxValue(isaacSyntheticEnableRlTeacherInput, false);
  setCheckboxValue(isaacLabVisualizeGenerationInput, true);
  syncIsaacLabMimicRgbdInputs(true);
  setCheckboxValue(isaacAugmentImageInput, true);
  setCheckboxValue(isaacAugmentPhotometricInput, true);
  setCheckboxValue(isaacAugmentSensorNoiseInput, true);
  setCheckboxValue(isaacAugmentDepthNoiseInput, true);
  setCheckboxValue(isaacAugmentRenderDomainInput, true);
  setCheckboxValue(isaacAugmentCameraPoseInput, true);
  setCheckboxValue(isaacAugmentExcludeFlaggedEpisodesInput, true);
  syncExcludeFlaggedEpisodesCheckboxes(isaacAugmentExcludeFlaggedEpisodesInput);
}

function devicePayload(role, overrides = {}) {
  const cameraKey = overrides.camera_key || (manualCameraKeyInput ? manualCameraKeyInput.value.trim() || "top" : "top");
  const cameraOptions = role === "camera" ? cameraPayloadOptions(cameraKey) : {};
  return {
    mode: modeSelect ? modeSelect.value : "test",
    runtime_mode: modeSelect ? modeSelect.value : "test",
    profile_id: profileSelect ? profileSelect.value : "",
    device_role: role,
    port: manualPortInput ? manualPortInput.value.trim() : "",
    camera_key: cameraKey,
    confirm_live_execute: boolValue(confirmLiveInput),
    dry_run: (modeSelect ? modeSelect.value : "test") !== "live",
    ...cameraOptions,
    ...overrides,
  };
}

async function postJson(url, body = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: controller.signal,
  });
  window.clearTimeout(timeoutId);
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (err) {
    data = { ok: false, status: "invalid_json", error: String(err), raw_response: text };
  }
  if (!res.ok) {
    return { ok: false, status: "http_error", status_code: res.status, error: data.detail || data.error || text, response: data };
  }
  return data;
}

function renderResult(label, data) {
  if (!outputEl) return;
  outputEl.textContent = `${label}\n${JSON.stringify(data, null, 2)}`;
  rememberWorkflowSession(data);
  if (sessionPillEl) {
    const sessionId = data && data.session_id ? data.session_id : "NO SESSION";
    sessionPillEl.textContent = sessionId;
    sessionPillEl.className = data && data.ok ? "badge running" : "badge idle";
  }
}

function renderIsaacMirror(data) {
  if (!isaacMirrorOutputEl) return;
  if (!data || !data.ok) {
    isaacMirrorOutputEl.innerHTML = `<pre class="command-output">${escapeHtml(JSON.stringify(data || {}, null, 2))}</pre>`;
    return;
  }
  const scene = data.scene_path || "";
  const root = data.articulation_root || "";
  const receiverHealth = data.receiver_health || data.health || {};
  const verification = data.verification || {};
  const rows = Array.isArray(data.joint_state) && data.joint_state.length
    ? data.joint_state
    : Array.isArray(data.last_joint_state) && data.last_joint_state.length
      ? data.last_joint_state
    : Array.isArray(data.joint_map)
      ? data.joint_map
      : [];
  const hasState = (Array.isArray(data.joint_state) && data.joint_state.length)
    || (Array.isArray(data.last_joint_state) && data.last_joint_state.length);
  const body = rows.map((item) => `
    <tr>
      <td>${escapeHtml(item.motor_id ?? "")}</td>
      <td>${escapeHtml(item.motor_name || "")}</td>
      <td>${escapeHtml(item.isaac_joint_name || "")}</td>
      <td>${hasState ? escapeHtml(Number(item.position_deg || 0).toFixed(3)) : "-"}</td>
      <td><code>${escapeHtml(item.isaac_joint_path || "")}</code></td>
    </tr>
  `).join("");
  isaacMirrorOutputEl.innerHTML = `
    <div class="visual-summary">
      <strong>${escapeHtml(data.probe_source || data.tool || "Isaac mirror")}</strong>
      <span>scene=${escapeHtml(scene || "-")} · root=${escapeHtml(root || "-")} · follower=${escapeHtml(data.follower_port || "-")}</span>
      <span>status=${escapeHtml(data.status || "-")} · launch=${escapeHtml(data.launch_mode || "-")} · link samples=${escapeHtml(data.sample_count ?? receiverHealth.sample_count ?? "-")} · evidence=${escapeHtml(data.mirror_record_path || "-")}</span>
      <span>endpoint=${escapeHtml(data.mirror_endpoint || "-")} · health=${escapeHtml(data.health_url || receiverHealth.health_url || "-")} · apply=${escapeHtml(data.apply_mode || receiverHealth.apply_mode || "-")}</span>
      ${verification.session_id ? `<span>verified=${escapeHtml(verification.session_id)} #${escapeHtml(verification.sample_index ?? "-")} · link samples=${escapeHtml(verification.receiver_sample_count_before ?? "-")}→${escapeHtml(verification.receiver_sample_count_after ?? "-")}</span>` : ""}
    </div>
    <table>
      <thead>
        <tr>
          <th>Motor</th>
          <th>Name</th>
          <th>Isaac Joint</th>
          <th>${hasState ? "Position" : "Position"}</th>
          <th>Path</th>
        </tr>
      </thead>
      <tbody>${body || `<tr><td colspan="5">No mirror joint data.</td></tr>`}</tbody>
    </table>
  `;
}

function isActiveSession(session) {
  if (!session || !session.session_id) return false;
  const status = String(session.status || "").toUpperCase();
  const terminal = new Set(["STOPPED", "FAILED", "COMPLETED", "CANCELLED", "DATASET_COMPLETE"]);
  if (terminal.has(status)) return false;
  return session.returncode === undefined || session.returncode === null;
}

function latestRecordSession() {
  for (let index = lastSessions.length - 1; index >= 0; index -= 1) {
    const session = lastSessions[index];
    if (session && String(session.workflow || "") === "record") return session;
  }
  return null;
}

function recordSessionDatasetIdentifier(session) {
  if (!session) return "";
  const repo = String(session.dataset_repo_id || "").trim();
  if (repo) return repo;
  const pathValue = String(session.dataset_path || "").trim();
  return datasetRepoValueFromPath(pathValue) || pathValue.replace(/\/+$/, "");
}

function currentRecordDatasetIdentifier() {
  const datasetValue = datasetInput ? datasetInput.value.trim() : "";
  const split = splitPathOrRepo(datasetValue);
  if (split.repo) return split.repo;
  if (split.path) return datasetRepoValueFromPath(split.path) || split.path.replace(/\/+$/, "");
  return "";
}

function recordRestartShouldResume() {
  const latest = latestRecordSession();
  if (!latest || isActiveSession(latest)) return false;
  if (String(latest.status || "").toUpperCase() !== "STOPPED") return false;
  const currentDataset = currentRecordDatasetIdentifier();
  const latestDataset = recordSessionDatasetIdentifier(latest);
  return Boolean(currentDataset && latestDataset && currentDataset === latestDataset);
}

function recordResumeValue() {
  return boolValue(resumeInput) || recordRestartShouldResume();
}

function rememberWorkflowSession(session) {
  const workflow = session && session.workflow ? String(session.workflow) : "";
  const sessionId = session && session.session_id ? String(session.session_id) : "";
  if (!workflow || !sessionId) return;
  const currentId = lastSessionByWorkflow[workflow] || "";
  const current = lastSessions.find((item) => String(item.session_id || "") === currentId);
  if (isActiveSession(session) || !currentId || !isActiveSession(current)) {
    lastSessionByWorkflow[workflow] = sessionId;
  }
}

function renderSessions(sessions) {
  lastSessions = Array.isArray(sessions) ? sessions : [];
  lastSessionByWorkflow = {};
  const fallbackByWorkflow = {};
  for (const session of lastSessions) {
    if (session && session.workflow && session.session_id) {
      const workflow = String(session.workflow);
      fallbackByWorkflow[workflow] = String(session.session_id);
      if (isActiveSession(session)) {
        lastSessionByWorkflow[workflow] = String(session.session_id);
      }
      if (session.isaac_rgbd_post_render) {
        handleIsaacRgbdRenderResponse(session);
      }
    }
  }
  for (const [workflow, sessionId] of Object.entries(fallbackByWorkflow)) {
    if (!lastSessionByWorkflow[workflow]) lastSessionByWorkflow[workflow] = sessionId;
  }
  if (!sessionListEl) return;
  sessionListEl.innerHTML = "";
  if (!lastSessions.length) {
    sessionListEl.innerHTML = `<div class="list-item"><span>No LeRobot sessions yet</span></div>`;
    return;
  }
  for (const session of lastSessions.slice().reverse()) {
    const row = document.createElement("div");
    row.className = "list-item lerobot-session-row";
    row.innerHTML = `
      <span>${session.workflow || "workflow"} · ${session.session_id || "session"}</span>
      <span class="state-pill">${session.runtime_phase || session.status || "unknown"}</span>
    `;
    row.addEventListener("click", () => renderResult("session", session));
    sessionListEl.appendChild(row);
  }
}

function applyDefaultPaths(data) {
  const paths = data.paths || {};
  lastConfigPaths = paths;
  if (datasetRootInput && !datasetRootInput.value) datasetRootInput.value = paths.dataset_root || "";
  syncDatasetManageRootFromLocalPaths();
  if (visualizationOutputDirInput && !visualizationOutputDirInput.value) visualizationOutputDirInput.value = paths.output_root ? `${paths.output_root}/visualize_dataset` : "";
}

function syncDatasetManageRootFromLocalPaths(force = false) {
  if (!datasetManageRootInput) return;
  const current = String(datasetManageRootInput.value || "").trim();
  const localRoot = datasetRootInput && datasetRootInput.value.trim()
    ? datasetRootInput.value.trim()
    : String((lastConfigPaths && lastConfigPaths.dataset_root) || "").trim();
  if (!localRoot) return;
  const builtInDefaults = new Set(["", "/home/jin/.cache/huggingface/lerobot", "~/.cache/huggingface/lerobot"]);
  if (force || (!datasetManageRootInput.dataset.userEdited && builtInDefaults.has(current))) {
    datasetManageRootInput.value = localRoot;
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function compactValue(value) {
  if (value === undefined || value === null || value === "") return "-";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function reportRowsHtml(rows) {
  return rows.map(([label, value]) => `
    <div class="lerobot-report-row">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(compactValue(value))}</strong>
    </div>
  `).join("");
}

function reportListHtml(items) {
  const clean = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!clean.length) return `<span class="hint">none</span>`;
  return `<ul class="lerobot-report-list">${clean.map((item) => `<li>${escapeHtml(typeof item === "object" ? JSON.stringify(item) : item)}</li>`).join("")}</ul>`;
}

function contactAuditEpisodeHtml(episodes) {
  const clean = Array.isArray(episodes) ? episodes.filter(Boolean).slice(0, 10) : [];
  if (!clean.length) return `<span class="hint">none</span>`;
  return `<ul class="lerobot-report-list">${clean.map((episode) => {
    const ranges = []
      .concat(Array.isArray(episode.closed_not_near_ranges) ? episode.closed_not_near_ranges : [])
      .concat(Array.isArray(episode.near_closed_without_contact_ranges) ? episode.near_closed_without_contact_ranges : [])
      .slice(0, 4)
      .join(", ");
    const detail = [
      `closed=${compactValue(episode.closed_frame_count)}`,
      `lifted=${compactValue(episode.lifted_frame_count)}`,
      `contact=${compactValue(episode.any_contact_frame_count)}`,
      ranges ? `frames ${ranges}` : "",
    ].filter(Boolean).join(" · ");
    return `<li><strong>ep ${escapeHtml(compactValue(episode.episode_index))}</strong> · ${escapeHtml(detail)}</li>`;
  }).join("")}</ul>`;
}

function renderDatasetHealth(data) {
  if (!datasetHealthEl) return;
  const health = data && data.dataset_health ? data.dataset_health : null;
  if (!health) {
    datasetHealthEl.innerHTML = "";
    return;
  }
  lastIsaacRgbdHealth = health;
  renderIsaacRgbdRenderFailureList();
  const metrics = health.metrics || {};
  const sidecars = health.sidecars || {};
  const raw_depth = sidecars.raw_depth || {};
  const isaac_rgbd = sidecars.isaac_rgbd || {};
  const isaac_augmentation = sidecars.isaac_augmentation || {};
  const training_exclusions = sidecars.training_exclusions || {};
  const contact_audit = isaac_rgbd.contact_audit || {};
  const mix = health.dataset_mix || {};
  const dataset_mix_effective_counts = mix.effective_counts || {};
  const severity = String(health.severity || "unknown");
  const issues = Array.isArray(health.issues) ? health.issues : [];
  const severe_episodes = Array.isArray(contact_audit.severe_episodes) ? contact_audit.severe_episodes : [];
  const transient_episodes = Array.isArray(contact_audit.transient_episodes) ? contact_audit.transient_episodes : [];
  const excluded_episode_indices = Array.isArray(training_exclusions.episode_indices)
    ? training_exclusions.episode_indices
    : [];
  datasetHealthEl.innerHTML = `
    <article class="lerobot-report-card wide">
      <div class="lerobot-report-card-title">
        <strong>Dataset Health</strong>
        <span class="state-pill ${escapeHtml(severity === "ok" ? "ok" : "warning")}">${escapeHtml(severity)}</span>
      </div>
      ${reportRowsHtml([
        ["Episodes", metrics.episodes],
        ["Original frames", metrics.original_frames],
        ["Raw depth frames", metrics.raw_depth_total_frames],
        ["Isaac RGB-D rendered", metrics.isaac_rgbd_rendered_frames],
        ["Aug valid variants", metrics.augmentation_valid_variants],
        ["Flagged train exclusions", metrics.excluded_flagged_episode_count || training_exclusions.episode_count || 0],
        ["Train effective frames", metrics.train_effective_frame_count],
      ])}
      <div class="lerobot-report-subtitle">Training mix</div>
      ${reportRowsHtml([
        ["real_original", dataset_mix_effective_counts.real_original],
        ["isaac_rgbd", dataset_mix_effective_counts.isaac_rgbd],
        ["isaac_augmentation", dataset_mix_effective_counts.isaac_augmentation],
        ["total", dataset_mix_effective_counts.total],
      ])}
      <div class="lerobot-report-subtitle">Sidecars</div>
      ${reportRowsHtml([
        ["raw_depth", raw_depth.available ? JSON.stringify(raw_depth.camera_counts || {}) : "missing"],
        ["isaac_rgbd", `${isaac_rgbd.rendered_count || 0}/${isaac_rgbd.row_count || 0}`],
        ["isaac_augmentation", `${isaac_augmentation.valid_variant_count || 0}/${isaac_augmentation.variant_count || 0}`],
        ["training_exclusions", training_exclusions.available ? `episodes ${excluded_episode_indices.join(", ") || "none"}` : "missing"],
      ])}
      <div class="lerobot-report-subtitle">Isaac RGB-D Contact Audit</div>
      ${reportRowsHtml([
        ["unique frames", contact_audit.unique_frame_count || 0],
        ["severe contact episodes", contact_audit.severe_episode_count || 0],
        ["transient contact dropouts", contact_audit.transient_episode_count || 0],
      ])}
      ${severe_episodes.length ? `<div class="lerobot-warning-strip">Check contact replay: ${escapeHtml(severe_episodes.length)} episode(s) closed without reliable contact/lift.</div>` : ""}
      ${contactAuditEpisodeHtml(severe_episodes)}
      ${transient_episodes.length ? `<div class="lerobot-report-subtitle">Transient contact dropouts</div>${contactAuditEpisodeHtml(transient_episodes)}` : ""}
      <div class="lerobot-report-subtitle">Issues</div>
      ${reportListHtml(issues.map((issue) => `${issue.severity || "warning"} · ${issue.code || "UNKNOWN"} · ${issue.message || ""}`))}
    </article>
  `;
}

function manipulationReportFromResponse(data) {
  if (!data || typeof data !== "object") return null;
  if (data.manipulation_report && typeof data.manipulation_report === "object") return data.manipulation_report;
  if (data.data && data.data.manipulation_report && typeof data.data.manipulation_report === "object") return data.data.manipulation_report;
  return null;
}

function robotTaskResultFromResponse(data, report = null) {
  if (!data || typeof data !== "object") return report && report.handoff_packet ? report.handoff_packet : null;
  if (data.robot_task_result && typeof data.robot_task_result === "object") return data.robot_task_result;
  if (data.data && data.data.robot_task_result && typeof data.data.robot_task_result === "object") return data.data.robot_task_result;
  return report && report.handoff_packet ? report.handoff_packet : null;
}

function manipulationResponseFromData(data) {
  if (!data || typeof data !== "object") return {};
  if (data.manipulation && typeof data.manipulation === "object") return data.manipulation;
  if (data.data && data.data.manipulation && typeof data.data.manipulation === "object") return data.data.manipulation;
  return data;
}

function executionSafetyFromReport(report) {
  if (!report || typeof report !== "object") return {};
  if (report.execution_safety && typeof report.execution_safety === "object") return report.execution_safety;
  if (report.runtime_safety_monitor && typeof report.runtime_safety_monitor === "object") return report.runtime_safety_monitor;
  return report.sarm && typeof report.sarm === "object" ? report.sarm : {};
}

function rerunTelemetryFromReport(report, data = {}) {
  const runtime = report && typeof report.rollout_runtime === "object" ? report.rollout_runtime : {};
  const response = manipulationResponseFromData(data);
  for (const candidate of [
    runtime.rerun_telemetry,
    runtime.rerun,
    report && report.rerun_telemetry,
    response && response.rerun_telemetry,
    response && response.visualization,
    data && data.visualization,
    data && data.data && data.data.visualization,
  ]) {
    if (candidate && typeof candidate === "object") return candidate;
  }
  return {};
}

function statusPillClass(status) {
  const value = String(status || "").toLowerCase();
  if (!value || value === "-" || value === "unknown" || value === "waiting") return "";
  if (/(ok|pass|ready|returned|complete|completed|active|running|policy_active|idle)/.test(value)) return "ok";
  if (/(fail|failed|blocked|error|timeout|missing|stale|conflict|interlock)/.test(value)) return "warning";
  return "";
}

function boolStatus(value, trueLabel = "ok", falseLabel = "blocked") {
  if (value === undefined || value === null || value === "") return "unknown";
  return value ? trueLabel : falseLabel;
}

function runtimeCardHtml(title, status, rows = [], extra = "") {
  return `
    <article class="lerobot-report-card">
      <div class="lerobot-report-card-title">
        <strong>${escapeHtml(title)}</strong>
        <span class="state-pill ${escapeHtml(statusPillClass(status))}">${escapeHtml(compactValue(status))}</span>
      </div>
      ${reportRowsHtml(rows)}
      ${extra || ""}
    </article>
  `;
}

function renderManipulationAgentReport(data) {
  if (!manipulationReportEl) return;
  const report = manipulationReportFromResponse(data);
  if (!report) return;
  const packet = robotTaskResultFromResponse(data, report) || {};
  const response = manipulationResponseFromData(data);
  const task = report.task || {};
  const policy = report.policy_plan || {};
  const preflight = report.preflight || {};
  const vision = report.vision_context || {};
  const stage = report.stage_machine || {};
  const safety = executionSafetyFromReport(report);
  const decision = report.decision || {};
  const runtime = report.rollout_runtime || {};
  const telemetry = rerunTelemetryFromReport(report, data);
  const activeCamera = report.active_camera_lease || response.active_camera_lease || response.active_robot_cam || {};
  const portLease = report.port_lease || response.port_lease || {};
  const evidence = packet.evidence_refs || (report.knowledge_payload && report.knowledge_payload.evidence_paths) || [];
  const preflightState = String(preflight.status || "unknown");
  const runtimeState = runtime.status || response.status || data.status || "unknown";
  const handoffState = String(packet.handoff_status || decision.handoff_status || "unknown");
  const viewerUrl = telemetry.viewer_url || telemetry.rerun_web_url || "";
  const observationPreview = telemetry.observation_preview || telemetry.latest_frame || {};
  const latestFrameArtifact = telemetry.latest_frame_artifact || observationPreview.latest_frame_artifact || observationPreview.path || "";
  const jointState = telemetry.joint_state || {};
  const actionStream = telemetry.action_stream || {};
  const viewerLink = viewerUrl
    ? `<a class="btn mini primary" href="${escapeHtml(viewerUrl)}" target="_blank" rel="noopener">Open Full Rerun Viewer</a>`
    : `<span class="hint">Rerun viewer evidence is waiting for an active display-data session.</span>`;
  manipulationReportEl.innerHTML = `
    <article class="lerobot-report-card wide">
      <div class="lerobot-report-card-title">
        <strong>Bridge State</strong>
        <span class="state-pill ${escapeHtml(handoffState === "blocked" ? "warning" : handoffState.includes("ready") ? "ok" : "")}">${escapeHtml(handoffState)}</span>
      </div>
      ${reportRowsHtml([
        ["Task", task.task_id],
        ["Skill", packet.skill_id || task.task_id],
        ["Episode", packet.episode_id || report.session_id],
        ["Specimen", task.specimen_id],
        ["Route", `${task.source_location || "-"} -> ${task.target_location || "-"}`],
        ["Terminal Pose", packet.terminal_pose || task.intended_terminal_pose],
      ])}
    </article>
    ${runtimeCardHtml("Port Lease", portLease.status || preflightState, [
        ["Profile", preflight.profile_id],
        ["Robot Ready", preflight.robot_ready],
        ["Follower", portLease.follower_port || portLease.follower || "-"],
        ["Leader", portLease.leader_port || portLease.leader || "-"],
        ["Reclaim", portLease.reclaim_status || portLease.reclaim_attempt || "-"],
        ["Operator Confirmed", preflight.operator_confirmed],
      ], `
      <div class="lerobot-report-subtitle">Warnings / blockers</div>
      ${reportListHtml([...(preflight.blocking_reasons || []), ...(preflight.warnings || [])])}
    `)}
    ${runtimeCardHtml("Active Camera", activeCamera.status || boolStatus(preflight.camera_ready, "ready", "blocked"), [
        ["Camera Ready", preflight.camera_ready],
        ["Owner", activeCamera.owner || activeCamera.camera_owner || "-"],
        ["Camera", activeCamera.camera_key || vision.camera || "-"],
        ["Returned to VLA", vision.camera_returned_to_vla ?? activeCamera.camera_returned_to_vla],
        ["Conflict", activeCamera.conflict_reason || activeCamera.blocking_reason || "-"],
      ])}
    ${runtimeCardHtml("Robot Policy Runtime", runtimeState, [
        ["Backend", policy.policy_backend],
        ["Policy Type", policy.policy_type],
        ["Policy Ref", policy.policy_ref],
        ["Inference", policy.inference_type],
        ["RTC Horizon", policy.rtc_execution_horizon],
        ["RTC Guidance", policy.rtc_max_guidance_weight],
        ["Action Clamp", policy.action_clamp_enabled ?? preflight.action_clamp_enabled],
        ["Max Duration", policy.max_duration_s],
        ["Session", runtime.session_id],
      ])}
    ${runtimeCardHtml("Rerun Telemetry", telemetry.status || telemetry.viewer_status || (viewerUrl ? "available" : "waiting"), [
        ["Viewer PID", telemetry.viewer_pid || telemetry.pid || "-"],
        ["Viewer URL", viewerUrl || "-"],
        ["WebSocket", telemetry.rerun_ws_url || telemetry.ws_url || "-"],
        ["RRD", telemetry.rrd_path || telemetry.output_path || "-"],
        ["Log", response.log_path || runtime.log_path || "-"],
      ], viewerLink)}
    ${runtimeCardHtml("Observation Preview", observationPreview.status || (latestFrameArtifact ? "available" : "waiting"), [
        ["RGB/Depth Frame", latestFrameArtifact || "waiting for streamed frame"],
        ["Frame Artifact", observationPreview.artifact_path || observationPreview.path || "-"],
        ["Frame Time", observationPreview.timestamp || observationPreview.frame_ts || "-"],
        ["Stream Keys", (telemetry.stream_keys || []).join(", ") || "-"],
      ])}
    ${runtimeCardHtml("Joint State", jointState.status || (jointState.current || jointState.follower ? "available" : "waiting"), [
        ["Follower", jointState.current || jointState.follower || jointState.follower_joint_vector || "-"],
        ["Policy Target", jointState.policy_target || jointState.action_target || "-"],
        ["Delta", jointState.delta_summary || jointState.max_abs_delta || runtime.max_abs_delta || "-"],
      ])}
    ${runtimeCardHtml("Action Stream", actionStream.status || (telemetry.action_rate_hz || runtime.action_count ? "active" : "waiting"), [
        ["Action Rate", actionStream.action_rate_hz || telemetry.action_rate_hz || "-"],
        ["Queue Depth", actionStream.action_queue_depth || telemetry.action_queue_depth || "-"],
        ["Last Action", actionStream.last_action_timestamp || telemetry.last_action_timestamp || "-"],
        ["Clamp / Filter", actionStream.clamp_status || actionStream.filter_status || telemetry.clamp_status || "-"],
      ])}
    ${runtimeCardHtml("Viewer Evidence", telemetry.status || telemetry.viewer_status || (viewerUrl ? "available" : "waiting"), [
        ["Viewer PID", telemetry.viewer_pid || telemetry.pid || "-"],
        ["Viewer URL", viewerUrl || "-"],
        ["RRD", telemetry.rrd_path || telemetry.output_path || "-"],
        ["Log", response.log_path || runtime.log_path || "-"],
      ], viewerLink)}
    ${runtimeCardHtml("Vision Completion Gate", decision.completion_status || vision.completion_status || "waiting", [
        ["Observation", vision.observation_id],
        ["Camera", vision.camera],
        ["Pickup Ready", vision.pickup_target_ready],
        ["Fixture Visible", vision.fixture_visible],
        ["Anomaly", vision.anomaly],
        ["Freshness", vision.freshness && vision.freshness.reason],
        ["Stop On Detection", decision.stop_rollout_on_completion ?? packet.stop_rollout_on_completion ?? "-"],
      ])}
    ${runtimeCardHtml("Execution Safety", safety.status || boolStatus(!safety.recovery_suggested, "nominal", "recovery"), [
        ["Current Stage", stage.current_stage],
        ["Next Expected", stage.next_expected_stage],
        ["Completed", (stage.completed_stages || []).length],
        ["Progress", safety.progress_score],
        ["Failure Precursor", safety.failure_precursor],
        ["Recovery", safety.recovery_suggested],
      ])}
    <article class="lerobot-report-card wide">
      <div class="lerobot-report-card-title"><strong>Decision / Handoff</strong></div>
      ${reportRowsHtml([
        ["Completion", packet.completion_status || decision.completion_status],
        ["Next Agent", packet.next_action || decision.recommended_next_agent],
        ["Reason", decision.reason],
        ["Verification", decision.verification && decision.verification.reason],
      ])}
      <div class="lerobot-report-subtitle">Evidence</div>
      ${reportListHtml(Array.isArray(evidence) ? evidence.map((item) => item.path || item) : [])}
    </article>
  `;
}

function actionStatusFromEvent(event) {
  const el = event && event.currentTarget ? event.currentTarget : null;
  const scope = el ? el.closest(".lerobot-device-card, .lerobot-port-panel, .lerobot-workflow-card, .lerobot-visualization-panel, .lerobot-config-panel, .lerobot-card") : null;
  return scope ? scope.querySelector(".lerobot-action-status") : null;
}

function actionSummary(data) {
  if (!data) return "No response.";
  if (data.hardware_alert) {
    const alert = data.hardware_alert;
    const severity = String(alert.severity || "alert").toUpperCase();
    const target = [alert.device, alert.component].filter(Boolean).join(" / ") || "hardware";
    const reason = alert.message || alert.failure_code || data.status || "hardware issue";
    const recovery = alert.recovery_hint ? ` · ${alert.recovery_hint}` : "";
    return `${severity} · ${target} · ${reason}${recovery}`;
  }
  if (data.training || data.workflow === "train") {
    const t = normalizedTrainingProgress(data) || data.training || {};
    const fidelity_weights = data.fidelity_weights || t.fidelity_weights || {};
    const weights = fidelity_weights.weights || {};
    const fidelity = weights.isaac_augmentation !== undefined
      ? ` · sim fidelity=${weights.isaac_rgbd ?? "-"} / ${weights.isaac_augmentation} / ${weights.isaac_lab_synthetic ?? "-"}`
      : "";
    return `${data.status || "training"} · ${t.current_step || 0}/${t.total_steps || "?"} · ${Number(t.progress_percent || 0).toFixed(1)}%${fidelity}`;
  }
  if (data.runtime) {
    const rt = data.runtime;
    const count = rt.action_count ? ` · actions=${rt.action_count}` : "";
    const delta = rt.max_abs_delta !== null && rt.max_abs_delta !== undefined ? ` · max_delta=${Number(rt.max_abs_delta).toFixed(3)}` : "";
    return `${data.status || "runtime"} · ${rt.phase || "RUNNING"} · ${rt.message || "runtime active"}${count}${delta}`;
  }
  if (data.failure_code) return `${data.failure_code}: ${data.message || data.error || data.status || "failed"}`;
  if (data.error) return String(data.error);
  if (data.status) return String(data.status);
  if (data.step_trace && data.step_trace.length) {
    const step = data.step_trace[data.step_trace.length - 1];
    return `${step.step || "step"} -> ${step.status || "unknown"}${step.detail ? ` (${step.detail})` : ""}`;
  }
  if (data.tool) return String(data.tool);
  return "completed";
}

function compactLogTail(data) {
  const raw = data && data.log_tail ? String(data.log_tail) : "";
  if (!raw.trim()) return "";
  const lines = raw.trim().split(/\r?\n/);
  const useful = lines.filter((line) => {
    const clean = line.trim();
    return clean && !clean.includes("wgpu_hal") && !clean.includes("winit::platform_impl");
  });
  const selected = useful.slice(-32).join("\n") || lines.slice(-32).join("\n");
  return selected.length > 6000 ? selected.slice(-6000) : selected;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return "unknown";
  const total = Math.max(0, Math.round(Number(seconds)));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function runtimeStatusHtml(data) {
  if (data && data.workflow === "train") return "";
  const rt = data && data.runtime ? data.runtime : null;
  if (!rt) return "";
  const warnings = Array.isArray(rt.warnings) && rt.warnings.length
    ? `<div class="lerobot-runtime-warnings">${rt.warnings.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`
    : "";
  const count = rt.action_count ? `${rt.action_count} actions` : "no action yet";
  const delta = rt.max_abs_delta !== null && rt.max_abs_delta !== undefined ? `max delta ${Number(rt.max_abs_delta).toFixed(3)}` : "delta pending";
  return `
    <div class="lerobot-runtime-status">
      <div><strong>${escapeHtml(rt.phase || "RUNTIME")}</strong><span>${escapeHtml(rt.message || "runtime status pending")}</span></div>
      <small>${escapeHtml(count)} · ${escapeHtml(delta)} · pid=${escapeHtml(rt.pid || "-")}</small>
      ${warnings}
    </div>
  `;
}

function parseTrainingCount(value, suffix = "") {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) return 0;
  const cleanSuffix = String(suffix || "").toLowerCase();
  const multiplier = cleanSuffix === "m" ? 1000000 : cleanSuffix === "k" ? 1000 : 1;
  return Math.round(numeric * multiplier);
}

function parseTrainingActiveStepsPerSec(log) {
  const durations = [];
  for (const line of String(log || "").split("\n")) {
    if (!/\b(?:step|global_step)\s*[=:]/i.test(line) || line.includes("cfg.steps")) continue;
    let duration = 0;
    for (const key of ["updt_s", "data_s"]) {
      const match = line.match(new RegExp(`\\b${key}\\s*[=:]\\s*([0-9]+(?:\\.[0-9]+)?)`, "i"));
      if (match) duration += Number(match[1]) || 0;
    }
    if (duration > 0) durations.push(duration);
  }
  if (!durations.length) return 0;
  const recent = durations.slice(-10);
  const avg = recent.reduce((total, item) => total + item, 0) / recent.length;
  return avg > 0 ? 1 / avg : 0;
}

function parseTrainingEffectiveBatchSize(log, training) {
  const configured = Number((training && training.batch_size) || (training && training.config && training.config.batch_size) || 0);
  for (const line of String(log || "").split("\n").reverse()) {
    const match = line.match(/\bEffective batch size:\s*\d+\s*x\s*\d+\s*=\s*(\d+)\b/i);
    if (match) {
      const parsed = Number(match[1]);
      if (Number.isFinite(parsed) && parsed > 0) return parsed;
    }
  }
  return Number.isFinite(configured) && configured > 0 ? configured : 0;
}

function parseTrainingSampleStep(log, training) {
  const countPattern = "(\\d{1,9}(?:\\.\\d+)?)([kKmM]?)";
  const effectiveBatchSize = parseTrainingEffectiveBatchSize(log, training);
  if (!(effectiveBatchSize > 0)) return 0;
  let samples = 0;
  for (const line of String(log || "").split("\n")) {
    const match = line.match(new RegExp(`\\b(?:smpl|samples|sample)\\s*[=:]\\s*${countPattern}`, "i"));
    if (match) samples = Math.max(samples, parseTrainingCount(match[1], match[2]));
  }
  return samples > 0 ? Math.round(samples / effectiveBatchSize) : 0;
}

function parseTrainingLogProgress(data, training) {
  const log = String((data && data.log_tail) || "");
  const countPattern = "(\\d{1,9}(?:\\.\\d+)?)([kKmM]?)";
  let current = Number(training.current_step || 0);
  let total = Number(training.total_steps || 0);
  let lastLoss = training.last_loss;

  for (const line of log.split("\n")) {
    if (!line.includes("cfg.steps")) {
      const stepMatch = line.match(new RegExp(`\\b(?:step|global_step)\\s*[=:]\\s*${countPattern}`, "i"));
      if (stepMatch) current = Math.max(current, parseTrainingCount(stepMatch[1], stepMatch[2]));
    }
    const lossMatch = line.match(/\b(?:loss|train_loss|l1_loss)\s*[=:]\s*([0-9]+(?:\.[0-9]+)?(?:e[-+]?\d+)?)/i);
    if (lossMatch) lastLoss = Number(lossMatch[1]);
  }

  const sampleStep = parseTrainingSampleStep(log, training);
  if (sampleStep > current) current = sampleStep;

  const elapsed = Number(training.elapsed_sec || 0);
  const activeRate = parseTrainingActiveStepsPerSec(log);
  const backendRate = Number(training.steps_per_sec || 0);
  const fallbackRate = current > 0 && elapsed > 0 ? current / elapsed : 0;
  const rate = activeRate > 0 ? activeRate : backendRate > 0 ? backendRate : fallbackRate;
  const eta = rate > 0 && total > 0 && current < total ? (total - current) / rate : training.eta_sec;
  const percent = total > 0 ? Math.max(0, Math.min(100, (current / total) * 100)) : Number(training.progress_percent || 0);

  return {
    ...training,
    current_step: current,
    total_steps: total,
    progress_percent: percent,
    eta_sec: eta,
    steps_per_sec: rate,
    last_loss: Number.isFinite(lastLoss) ? lastLoss : training.last_loss,
  };
}

function normalizedTrainingProgress(data) {
  const training = data && data.training ? data.training : null;
  if (!training) return null;
  return parseTrainingLogProgress(data, training);
}

function trainingProgressHtml(data) {
  const training = normalizedTrainingProgress(data);
  if (!training) return "";
  const current = Number(training.current_step || 0);
  const total = Number(training.total_steps || 0);
  const percent = Number(training.progress_percent || 0);
  const eta = training.eta_sec === null || training.eta_sec === undefined ? "ETA unknown" : `ETA ${formatDuration(training.eta_sec)}`;
  const loss = training.last_loss === null || training.last_loss === undefined ? "" : ` · loss=${training.last_loss}`;
  return `
    <div class="training-progress-inline">
      <div class="training-progress-head">
        <strong>${Math.max(0, Math.min(100, percent)).toFixed(1)}%</strong>
        <span>${current} / ${total || "?"} steps · ${eta}${loss}</span>
      </div>
      <div class="training-progress-track"><span style="width:${Math.max(0, Math.min(100, percent))}%"></span></div>
    </div>
  `;
}

function renderTrainingProgress(data) {
  const training = normalizedTrainingProgress(data);
  if (!training || !trainProgressEl) return;
  trainProgressEl.classList.remove("hidden");
  const percent = Math.max(0, Math.min(100, Number(training.progress_percent || 0)));
  const current = Number(training.current_step || 0);
  const total = Number(training.total_steps || 0);
  const eta = training.eta_sec === null || training.eta_sec === undefined ? "ETA unknown" : `ETA ${formatDuration(training.eta_sec)}`;
  const rate = Number(training.steps_per_sec || 0);
  if (trainProgressLabelEl) {
    trainProgressLabelEl.textContent = `${current} / ${total || "?"} · ${percent.toFixed(1)}% · ${eta} · ${rate.toFixed(3)} step/s`;
  }
  if (trainProgressBarEl) {
    trainProgressBarEl.style.width = `${percent}%`;
  }
}

function renderTrainingPreflightProgress(data) {
  if (!data || !data.training_preflight) return;
  renderUnifiedProgress(
    "training_preflight",
    trainProgressEl,
    trainProgressLabelEl,
    trainProgressBarEl,
    data.training_preflight,
    { label: "Preflight" },
  );
}

function trainIsActive(data) {
  if (!data || data.workflow !== "train") return false;
  const status = String(data.status || "").toUpperCase();
  const terminal = new Set(["STOPPED", "FAILED", "COMPLETED", "CANCELLED"]);
  return !terminal.has(status) && (data.returncode === undefined || data.returncode === null);
}

function inferActionWorkflow(label = "", data = null) {
  const parts = [
    label,
    data && data.workflow,
    data && data.tool,
    data && data.session_id,
    data && data.status,
    data && data.failure_code,
    data && data.message,
    data && data.error,
    data && data.runtime && data.runtime.message,
    data && data.log_tail,
  ].filter(Boolean).map((item) => String(item).toLowerCase());
  const text = parts.join(" ");
  if (text.includes("rollout") || text.includes("inference")) return "rollout";
  if (text.includes("train") || text.includes("training")) return "train";
  if (text.includes("record")) return "record";
  if (text.includes("teleoperate") || text.includes("teleop")) return "teleoperate";
  return "";
}

function expectedWorkflowForStatusTarget(el) {
  if (!el || !el.id) return "";
  if (el.id === "lerobot-train-action-status") return "train";
  if (el.id === "lerobot-rollout-action-status") return "rollout";
  return "";
}

function setActionStatus(target, state, label, data = null) {
  if (!target) return;
  const el = typeof target === "string" ? $(target) : target;
  if (!el) return;
  const expectedWorkflow = expectedWorkflowForStatusTarget(el);
  const actualWorkflow = inferActionWorkflow(label, data);
  if (expectedWorkflow && actualWorkflow && expectedWorkflow !== actualWorkflow) return;
  const normalized = state || "idle";
  const prefix = normalized === "ok" ? "OK" : normalized === "error" ? "ERROR" : normalized === "running" ? "RUNNING" : "IDLE";
  const logTail = compactLogTail(data);
  const progressHtml = expectedWorkflow === "train" ? "" : trainingProgressHtml(data);
  const runtimeHtml = runtimeStatusHtml(data);
  const logHtml = logTail ? `<pre class="lerobot-inline-log">${escapeHtml(logTail)}</pre>` : "";
  el.className = `lerobot-action-status ${normalized}`;
  el.innerHTML = `<strong>${prefix}</strong><span>${escapeHtml(label || "action")}</span><small>${escapeHtml(actionSummary(data))}</small>${runtimeHtml}${progressHtml}${logHtml}`;
}

function normalizeCameraKey(value) {
  return String(value || "")
    .trim()
    .replace(/\s+/g, "_")
    .replace(/[^A-Za-z0-9_-]/g, "")
    .toLowerCase();
}

function defaultCameraKeys(profile) {
  return new Set(["top", "wrist", ...Object.keys((profile && profile.camera_map) || {}).map(normalizeCameraKey)]);
}

function realsenseDefaultIdentifier(cameraKey) {
  const key = normalizeCameraKey(cameraKey);
  if (key === "wrist") return "352122273019";
  if (key === "top") return "Intel RealSense D455F";
  return "Intel RealSense";
}

function realsenseCheckboxLabel(cameraKey) {
  const key = normalizeCameraKey(cameraKey);
  if (key === "top") return "RealSense D455F";
  if (key === "wrist") return "RealSense D405";
  return "RealSense SDK";
}

function cameraUsesRealsense(camera) {
  const backend = String((camera && camera.backend) || "").toLowerCase();
  return backend === "intelrealsense" || backend === "realsense" || backend === "realsense_sdk";
}

function cameraUsbLinkBadge(camera, realsense) {
  if (!realsense) return "";
  camera = camera || {};
  const rawStatus = String(camera.usb_link_status || "").toLowerCase();
  const status = ["ok", "warning"].includes(rawStatus) ? rawStatus : "unknown";
  let label = camera.usb_link_label || "USB link unknown";
  if (status === "warning" && !String(label).toLowerCase().includes("rollout risk")) {
    label = `${label} · rollout risk`;
  }
  return `<span class="lerobot-camera-usb-link ${status}" title="Negotiated camera USB link">${escapeHtml(label)}</span>`;
}

function cameraRealsenseDefaultChecked(cameraKey, camera) {
  const key = normalizeCameraKey(cameraKey);
  if (cameraRealsenseOverrides.has(key)) return Boolean(cameraRealsenseOverrides.get(key));
  if (defaultRealsenseCameraKeys.has(key)) return true;
  return cameraUsesRealsense(camera);
}

function cameraRealsenseChecked(cameraKey) {
  const key = normalizeCameraKey(cameraKey);
  for (const input of document.querySelectorAll(".camera-realsense-toggle")) {
    if (normalizeCameraKey(input.dataset.cameraKey) === key) return Boolean(input.checked);
  }
  return defaultRealsenseCameraKeys.has(key);
}

function cameraFpsDefault(cameraKey, camera) {
  const key = normalizeCameraKey(cameraKey);
  if (cameraFpsOverrides.has(key)) return cameraFpsOverrides.get(key);
  const saved = Number((camera && (camera.fps || camera.camera_fps)) || 0);
  if (Number.isFinite(saved) && saved > 0) return saved;
  return 15;
}

function cameraFpsForKey(cameraKey) {
  const key = normalizeCameraKey(cameraKey);
  for (const input of document.querySelectorAll(".camera-fps-input")) {
    if (normalizeCameraKey(input.dataset.cameraKey) === key) return numberValue(input, 15);
  }
  if (cameraFpsOverrides.has(key)) return cameraFpsOverrides.get(key);
  return 15;
}

function cameraPayloadOptions(cameraKey) {
  const useRealsense = cameraRealsenseChecked(cameraKey);
  return {
    camera_backend: useRealsense ? "realsense" : "opencv",
    camera_use_depth: useRealsense,
    camera_fps: useRealsense ? cameraFpsForKey(cameraKey) : numberValue(cameraFpsInput, 15),
    camera_width: 640,
    camera_height: 480,
  };
}

function cameraKeysForProfile(profile, devices) {
  const keys = ["top", "wrist"];
  for (const key of Object.keys((profile && profile.camera_map) || {})) keys.push(key);
  for (const key of Object.keys((devices && devices.cameras) || {})) keys.push(key);
  for (const key of extraCameraKeys) keys.push(key);
  return [...new Set(keys.map(normalizeCameraKey).filter(Boolean))];
}

function renderDeviceMemory(data) {
  lastConfigData = data;
  const profileId = profileSelect ? profileSelect.value : data.selected_profile_id || data.default_profile_id || "";
  const memory = data.device_memory || {};
  const profileMemory = ((memory.profiles || {})[profileId] || {});
  const devices = profileMemory.devices || {};
  const profiles = data.profiles || [];
  const profile = profiles.find((p) => p.profile_id === profileId) || profiles[0] || {};
  const follower = devices.follower || {};
  const leader = devices.leader || {};
  if (followerPortDisplayEl) followerPortDisplayEl.textContent = follower.port || "not saved";
  if (leaderPortDisplayEl) leaderPortDisplayEl.textContent = leader.port || "not saved";
  if (cameraCardListEl) {
    const cameras = devices.cameras || {};
    const keys = cameraKeysForProfile(profile, devices);
    const defaultKeys = defaultCameraKeys(profile);
    cameraCardListEl.innerHTML = keys.map((key) => {
      const camera = cameras[key] || (devices.camera && (devices.camera.camera_key || "top") === key ? devices.camera : {});
      const realsense = cameraRealsenseDefaultChecked(key, camera);
      const cameraFps = cameraFpsDefault(key, camera);
      const cameraIdentity = camera.serial_number_or_name || camera.port || realsenseDefaultIdentifier(key);
      const removable = !defaultKeys.has(key);
      return `
        <article class="lerobot-device-card">
          <div class="lerobot-card-title-row">
            <div class="lerobot-camera-title-group">
              <strong>${escapeHtml(key)} Camera</strong>
              <label class="checkbox-line inline-check lerobot-camera-backend-line" title="Checked: Detect & Save stores the role-specific RealSense RGB + depth camera.">
                <input class="camera-realsense-toggle" data-camera-key="${escapeHtml(key)}" type="checkbox" ${realsense ? "checked" : ""} />
                ${escapeHtml(realsenseCheckboxLabel(key))}
              </label>
              <label class="lerobot-camera-fps-line" title="RealSense camera FPS for this camera role.">
                FPS
                <input class="camera-fps-input" data-camera-key="${escapeHtml(key)}" type="number" min="1" value="${escapeHtml(String(cameraFps))}" ${realsense ? "" : "disabled"} />
              </label>
            </div>
            ${removable ? `<button class="btn mini danger camera-remove" data-camera-key="${escapeHtml(key)}" type="button">-</button>` : `<span class="state-pill">default</span>`}
          </div>
          <code>${escapeHtml(cameraIdentity || "not saved")}</code>
          ${cameraUsbLinkBadge(camera, realsense)}
          ${camera.raw_port ? `<span class="hint">raw: ${escapeHtml(camera.raw_port)}</span>` : ""}
          <div class="button-row compact">
            <button class="btn mini camera-action" data-camera-action="baseline" data-camera-key="${escapeHtml(key)}">Baseline</button>
            <button class="btn mini primary camera-action" data-camera-action="detect" data-camera-key="${escapeHtml(key)}">Detect & Save</button>
            <button class="btn mini camera-action" data-camera-action="test" data-camera-key="${escapeHtml(key)}">Capture Test</button>
          </div>
          <div id="lerobot-camera-status-${escapeHtml(key)}" class="lerobot-action-status idle">Waiting for ${escapeHtml(key)} camera action.</div>
        </article>
      `;
    }).join("");
    for (const input of cameraCardListEl.querySelectorAll(".camera-realsense-toggle")) {
      input.addEventListener("change", () => {
        const key = normalizeCameraKey(input.dataset.cameraKey);
        cameraRealsenseOverrides.set(key, Boolean(input.checked));
        const fpsInput = cameraCardListEl.querySelector(`.camera-fps-input[data-camera-key="${CSS.escape(key)}"]`);
        if (fpsInput) fpsInput.disabled = !input.checked;
      });
    }
    for (const input of cameraCardListEl.querySelectorAll(".camera-fps-input")) {
      input.addEventListener("input", () => {
        cameraFpsOverrides.set(normalizeCameraKey(input.dataset.cameraKey), numberValue(input, 15));
      });
      input.addEventListener("change", () => {
        cameraFpsOverrides.set(normalizeCameraKey(input.dataset.cameraKey), numberValue(input, 15));
      });
    }
    for (const button of cameraCardListEl.querySelectorAll(".camera-action")) {
      button.addEventListener("click", (event) => {
        const cameraKey = button.dataset.cameraKey || "top";
        if (manualCameraKeyInput) manualCameraKeyInput.value = cameraKey;
        const action = button.dataset.cameraAction || "test";
        const statusTarget = actionStatusFromEvent(event);
        const cameraOptions = cameraPayloadOptions(cameraKey);
        if (action === "baseline") return runDevicePortAction(`${cameraKey} camera baseline`, "/api/lerobot/ports/baseline", "camera", { port: "", camera_key: cameraKey, ...cameraOptions }, statusTarget);
        if (action === "detect") return runDevicePortAction(`${cameraKey} camera detect/save`, "/api/lerobot/ports/detect", "camera", { port: "", camera_key: cameraKey, ...cameraOptions }, statusTarget);
        return runDevicePortAction(`${cameraKey} camera capture test`, "/api/lerobot/camera/test", "camera", { port: "", camera_key: cameraKey, ...cameraOptions }, statusTarget);
      });
    }
    for (const button of cameraCardListEl.querySelectorAll(".camera-remove")) {
      button.addEventListener("click", (event) => {
        const cameraKey = button.dataset.cameraKey || "";
        if (!cameraKey || defaultKeys.has(cameraKey)) return;
        extraCameraKeys = extraCameraKeys.filter((key) => key !== cameraKey);
        const statusTarget = $("lerobot-camera-manager-status");
        if (cameras[cameraKey]) {
          return runDevicePortAction(`${cameraKey} camera remove`, "/api/lerobot/ports/delete", "camera", { port: "", camera_key: cameraKey }, statusTarget);
        }
        setActionStatus($("lerobot-camera-manager-status"), "ok", `${cameraKey} camera remove`, { status: "removed local unsaved camera" });
        renderDeviceMemory(lastConfigData || { profiles: [], device_memory: {} });
      });
    }
  }
}

function renderConfig(data) {
  const profiles = data.profiles || [];
  const selected = data.selected_profile_id || data.default_profile_id || "";
  if (confirmLiveInput && !confirmLiveInput.dataset.userEdited) confirmLiveInput.checked = true;
  if (profileSelect) {
    const prior = profileSelectionInitialized ? profileSelect.value || selected : selected;
    profileSelect.innerHTML = "";
    for (const profile of profiles) {
      const opt = document.createElement("option");
      opt.value = profile.profile_id;
      opt.textContent = `${profile.display_name || profile.profile_id} (${profile.profile_id})`;
      profileSelect.appendChild(opt);
    }
    profileSelect.value = profiles.some((p) => p.profile_id === prior) ? prior : selected;
    profileSelectionInitialized = true;
  }
  const selectedProfileId = profileSelect ? profileSelect.value : selected;
  const profile = profiles.find((p) => p.profile_id === selectedProfileId) || profiles[0] || {};
  const pipelineOptions = Array.isArray(data.observation_pipelines) ? data.observation_pipelines : [];
  const selectedPipeline = data.selected_observation_pipeline_id || data.default_observation_pipeline_id || "raw_depth_adapter";
  if (observationPipelineSelect) {
    const profileDefaultPipeline = profile.observation_pipeline_id || selectedPipeline;
    const pipelineProfileUnchanged = observationPipelineProfileId === selectedProfileId;
    const priorPipeline = pipelineProfileUnchanged && observationPipelineSelect.value ? observationPipelineSelect.value : profileDefaultPipeline;
    observationPipelineSelect.innerHTML = "";
    for (const pipeline of pipelineOptions) {
      const opt = document.createElement("option");
      opt.value = pipeline.pipeline_id;
      opt.textContent = `${pipeline.label || pipeline.pipeline_id}`;
      opt.title = pipeline.description || pipeline.pipeline_id;
      observationPipelineSelect.appendChild(opt);
    }
    if (!pipelineOptions.length) {
      for (const id of ["legacy_lerobot", "rgbd_sidecar", "raw_depth_adapter"]) {
        const opt = document.createElement("option");
        opt.value = id;
        opt.textContent = id;
        observationPipelineSelect.appendChild(opt);
      }
    }
    const validPipelines = Array.from(observationPipelineSelect.options || []).map((opt) => opt.value);
    observationPipelineSelect.value = validPipelines.includes(priorPipeline) ? priorPipeline : profileDefaultPipeline;
    observationPipelineProfileId = selectedProfileId;
  }

  applyDefaultPaths(data);
  applyWorkflowDefaults(data);
  const gates = profile.live_gate_summary || data.live_gate_summary || {};
  const liveEnabled = Boolean(gates.live_enabled);
  setStatusDot(statusDotEl, data.ok ? "busy" : "warn");
  setStatusDot(gateDotEl, liveEnabled ? "active" : "warn");
  if (statusLabelEl) statusLabelEl.textContent = data.ok ? `Profile ${profile.profile_id || selected}` : "Config unavailable";
  if (statusDetailEl) {
    const env = data.environment || {};
    statusDetailEl.textContent = profile.robot_family
      ? `${profile.robot_family} · robot=${profile.robot_type} · teleop=${profile.teleop_type} · env=${env.conda_env_name || "lerobot"}`
      : "No selected robot profile.";
  }
  if (gateLabelEl) gateLabelEl.textContent = liveEnabled ? "Live gates enabled" : "Live gates disabled";
  if (gateDetailEl) {
    const paths = data.paths || {};
    const tts = data.tts || {};
    gateDetailEl.textContent = `dataset=${paths.dataset_root || ""} · output=${paths.output_root || ""} · teleop=${Boolean(gates.allow_teleoperation)} record=${Boolean(gates.allow_recording)} train=${Boolean(gates.allow_training)} rollout=${Boolean(gates.allow_policy_rollout)} · voice=${tts.engine || "piper"}:${tts.rate ?? ""}`;
  }
  if (data.tts) {
    if (ttsEngineInput && data.tts.engine && !ttsEngineInput.dataset.userEdited) ttsEngineInput.value = data.tts.engine;
    if (data.tts.rate !== undefined) lerobotTtsServerDefaultRate = clampTtsRate(data.tts.rate);
    if (ttsRateInput && !ttsRateInput.dataset.userEdited) {
      setTtsRate(lerobotTtsServerDefaultRate);
    } else {
      setTtsRate(ttsRateInput ? ttsRateInput.value : lerobotTtsServerDefaultRate);
    }
  }
  if (data.wandb && trainWandbBaseUrlInput && !trainWandbBaseUrlInput.dataset.userEdited) {
    trainWandbBaseUrlInput.value = data.wandb.local_base_url || "http://127.0.0.1:8081";
  }
  renderDeviceMemory(data);
  renderSessions(data.sessions || []);
  restoreActiveTrainingStatus(data.sessions || []);
}

function restoreActiveTrainingStatus(sessions) {
  const activeTrain = (Array.isArray(sessions) ? sessions : []).find((session) => session && session.workflow === "train" && isActiveSession(session));
  if (!activeTrain) return;
  rememberWorkflowSession(activeTrain);
  renderTrainingProgress(activeTrain);
  const target = $("lerobot-train-action-status");
  setActionStatus(target, "running", "train status", activeTrain);
  startTrainStatusPolling();
}

async function refreshConfig() {
  try {
    const res = await fetch("/api/lerobot/config");
    const data = await res.json();
    renderConfig(data);
    await refreshPolicies();
    await refreshRolloutProfile();
    await refreshManipulationProfile();
    return data;
  } catch (err) {
    renderResult("config error", { ok: false, error: String(err) });
    setStatusDot(statusDotEl, "warn");
    return { ok: false };
  }
}

async function refreshPolicies() {
  let data = { ok: false, policies: [], error: "" };
  try {
    const res = await fetch("/api/lerobot/policies");
    data = await res.json();
  } catch (err) {
    data = { ok: false, policies: [], error: String(err) };
  }
  const policies = data.policies || [];
  policyCatalogByValue = new Map();
  for (const policy of policies) {
    const value = policy.value || policy.path || policy.repo_id || "";
    if (value) policyCatalogByValue.set(value, policy);
  }
  if (policySelect) {
    const prior = (rolloutPolicyInput && rolloutPolicyInput.value.trim()) || policySelect.value;
    policySelect.innerHTML = "";
    for (const policy of policies) {
      const opt = document.createElement("option");
      opt.value = policy.value || policy.path || policy.repo_id || "";
      opt.textContent = `${policy.label || opt.value || "manual"} · ${policy.source || "policy"}`;
      opt.dataset.policyType = policy.policy_type || "";
      policySelect.appendChild(opt);
    }
    if (prior) {
      const priorPolicy = policyCatalogByValue.get(prior) || {};
      ensureSavedPolicyOption(policySelect, prior, priorPolicy.policy_type || selectedRolloutPolicyType());
      policySelect.value = prior;
    }
  }
  if (manipulationPolicySelect) {
    const prior = (manipulationPolicyInput && manipulationPolicyInput.value.trim()) || manipulationPolicySelect.value;
    manipulationPolicySelect.innerHTML = "";
    for (const policy of policies) {
      const opt = document.createElement("option");
      opt.value = policy.value || policy.path || policy.repo_id || "";
      opt.textContent = `${policy.label || opt.value || "manual"} · ${policy.source || "policy"}`;
      opt.dataset.policyType = policy.policy_type || "";
      manipulationPolicySelect.appendChild(opt);
    }
    if (prior) {
      const priorPolicy = policyCatalogByValue.get(prior) || {};
      ensureSavedPolicyOption(manipulationPolicySelect, prior, priorPolicy.policy_type || selectedManipulationPolicyType());
      manipulationPolicySelect.value = prior;
    }
  }
  if (policyListEl) {
    const displayPolicies = policies.slice().sort((a, b) => policySortRank(a) - policySortRank(b));
    const trainingPolicies = displayPolicies.filter((p) => p.source === "local");
    policyListEl.innerHTML = trainingPolicies.slice(0, 12).map((p) => {
      const value = p.value || p.path || p.repo_id || "";
      const label = p.label || value || "policy";
      const source = p.source || "policy";
      const policyType = p.policy_type || inferPolicyTypeFromPolicy(value, label);
      return `
        <div class="lerobot-policy-chip" data-policy="${escapeHtml(value)}" data-policy-type="${escapeHtml(policyType)}">
          <div class="lerobot-policy-chip-text">
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(source)}${policyType ? ` · ${escapeHtml(policyType)}` : ""}</span>
          </div>
          <button class="btn mini policy-chip-select" type="button" data-policy="${escapeHtml(value)}" data-policy-type="${escapeHtml(policyType)}" ${value ? "" : "disabled"}>Select</button>
        </div>
      `;
    }).join("");
    for (const button of policyListEl.querySelectorAll(".policy-chip-select")) {
      button.addEventListener("click", () => {
        const value = button.dataset.policy || "";
        const policy = policyCatalogByValue.get(value) || null;
        applyPolicySelection(value, button.dataset.policyType || "", policy);
        setActionStatus("lerobot-train-action-status", "ok", "resume policy selected", { policy_path: value, output_dir: policy ? policy.output_dir || "" : "" });
      });
    }
  }
  return data;
}

function inferPolicyTypeFromPolicy(value = "", label = "") {
  const text = `${value} ${label}`.toLowerCase();
  if (text.includes("smolvla") || text.includes("smol-vla")) return "smolvla";
  if (text.includes("xvla") || text.includes("x-vla")) return "xvla";
  if (text.includes("pi0fast")) return "pi0fast";
  if (text.includes("pi05") || text.includes("pi0.5")) return "pi05";
  if (text.includes("pi0_base") || text.includes("/pi0") || text.includes(" pi0")) return "pi0";
  if (text.includes("act")) return "act";
  return "";
}

function policySortRank(policy) {
  const source = String(policy.source || "").toLowerCase();
  const value = policy.value || policy.path || policy.repo_id || "";
  if (source === "local" && value) return 0;
  if (source === "huggingface" && value) return 1;
  if (value) return 2;
  return 3;
}

function applyPolicySelection(value, policyType = "", selectedPolicy = null) {
  const clean = String(value || "").trim();
  const policy = selectedPolicy || policyCatalogByValue.get(clean) || {};
  const selectedOption = policySelect
    ? Array.from(policySelect.options || []).find((opt) => opt.value === clean)
    : null;
  const inferredPolicyType = String(
    policyType
    || (policy && policy.policy_type)
    || (selectedOption && selectedOption.dataset.policyType)
    || inferPolicyTypeFromPolicy(clean, selectedOption ? selectedOption.textContent : ""),
  ).trim();
  if (policyInput) policyInput.value = clean;
  if (rolloutPolicyInput) rolloutPolicyInput.value = clean;
  if (trainSourcePolicyInput && policy.source !== "local") trainSourcePolicyInput.value = clean;
  if (policySelect) policySelect.value = clean;
  if (inferredPolicyType && policyTypeInput) policyTypeInput.value = inferredPolicyType;
  if (inferredPolicyType && rolloutPolicyTypeInput) rolloutPolicyTypeInput.value = inferredPolicyType;
  if (policy && policy.source === "local") {
    applyLocalPolicyTrainingResume(policy);
  } else {
    applyPolicyTypeDefaults();
  }
  syncRolloutPolicyOptions();
  return clean;
}

function applyManipulationPolicySelection(value, policyType = "", selectedPolicy = null) {
  const clean = String(value || "").trim();
  const policy = selectedPolicy || policyCatalogByValue.get(clean) || {};
  const selectedOption = manipulationPolicySelect
    ? Array.from(manipulationPolicySelect.options || []).find((opt) => opt.value === clean)
    : null;
  const inferredPolicyType = String(
    policyType
    || (policy && policy.policy_type)
    || (selectedOption && selectedOption.dataset.policyType)
    || inferPolicyTypeFromPolicy(clean, selectedOption ? selectedOption.textContent : ""),
  ).trim();
  if (manipulationPolicyInput) manipulationPolicyInput.value = clean;
  if (manipulationPolicySelect) manipulationPolicySelect.value = clean;
  if (inferredPolicyType && manipulationPolicyTypeInput) manipulationPolicyTypeInput.value = inferredPolicyType;
  syncManipulationPolicyOptions();
  return clean;
}

async function persistSelectedManipulationPolicy(value, policyType = "", selectedPolicy = null) {
  const clean = applyManipulationPolicySelection(value, policyType, selectedPolicy);
  if (!clean) {
    return { ok: false, status: "policy_required", error: "Select a Manipulation policy checkpoint before saving." };
  }
  return persistManipulationTaskProfile();
}


async function useLatestLocalPolicy(statusTarget = null) {
  setActionStatus(statusTarget, "running", "use latest policy", { status: "refreshing local policies" });
  const data = await refreshPolicies();
  const local = (data.policies || []).find((item) => item.source === "local" && (item.path || item.value));
  if (!local) {
    setActionStatus(statusTarget, "error", "use latest policy", { error: "No local LeRobot policy checkpoint found under outputs/train." });
    return null;
  }
  const value = local.path || local.value || "";
  const policyType = local.policy_type || inferPolicyTypeFromPolicy(value, local.label || "");
  applyPolicySelection(value, policyType, local);
  setActionStatus(statusTarget, "ok", "use latest policy", { policy_path: value, label: local.label, policy_type: policyType, output_dir: local.output_dir || "" });
  return local;
}

async function useLatestManipulationPolicy(statusTarget = null) {
  setActionStatus(statusTarget, "running", "use latest manipulation policy", { status: "refreshing local policies" });
  const data = await refreshPolicies();
  const local = (data.policies || []).find((item) => item.source === "local" && (item.path || item.value));
  if (!local) {
    setActionStatus(statusTarget, "error", "use latest manipulation policy", { error: "No local LeRobot policy checkpoint found under outputs/train." });
    return null;
  }
  const value = local.path || local.value || "";
  const policyType = local.policy_type || inferPolicyTypeFromPolicy(value, local.label || "");
  const saved = await persistSelectedManipulationPolicy(value, policyType, local);
  setActionStatus(statusTarget, saved && saved.ok ? "ok" : "error", "use latest manipulation policy", {
    ...saved,
    policy_path: value,
    label: local.label,
    policy_type: policyType,
    output_dir: local.output_dir || "",
  });
  return local;
}

async function runAction(label, url, payload = null, statusTarget = null, timeoutMs = 30000) {
  renderResult(`${label} running`, { ok: true, status: "request_sent" });
  setActionStatus(statusTarget, "running", label, { status: "request sent" });
  try {
    const data = await postJson(url, payload || basePayload(), timeoutMs);
    renderResult(label, data);
    if (String(url || "").includes("/api/lerobot/manipulation-agent/") || String(label || "").includes("manipulation agent")) {
      renderManipulationAgentReport(data);
    }
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", label, data);
    syncFieldsFromWorkflowResponse(data);
    handleRecordProgressResponse(data);
    handleIsaacRgbdRenderResponse(data);
    await refreshConfig();
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    return error;
  }
}

function renderTeleopHandoff(message = "") {
  if (!teleopHandoffPanel || !teleopHandoffToken || !teleopHandoffRunId) return;
  teleopHandoffPanel.classList.remove("hidden");
  const context = teleopHandoffContext || {};
  teleopHandoffContextEl.innerHTML = [
    `<strong>Run:</strong> ${escapeHtml(context.run_id || teleopHandoffRunId)}`,
    `<strong>Cycle:</strong> ${escapeHtml(String(context.cycle_index || "-"))}`,
    `<strong>Specimen:</strong> ${escapeHtml(context.specimen_id || "-")}`,
    `<strong>Candidate:</strong> ${escapeHtml(context.candidate_id || "-")}`,
    "<strong>Route:</strong> Manipulation → UTM Vision → Lab Equipment",
  ].join("<br>");
  teleopHandoffCompleteButton.disabled = !teleopHandoffSessionId || ["operator_confirmed", "confirmed"].includes(context.status);
  if (message) {
    teleopHandoffStatusEl.textContent = message;
    teleopHandoffStatusEl.className = "lerobot-action-status ok";
  }
}

async function loadTeleopHandoff() {
  if (!teleopHandoffToken || !teleopHandoffRunId) return;
  if (modeSelect) modeSelect.value = "live";
  try {
    const response = await fetch(`/api/planning/runs/${encodeURIComponent(teleopHandoffRunId)}/teleop-handoff?handoff_token=${encodeURIComponent(teleopHandoffToken)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `handoff lookup failed (${response.status})`);
    teleopHandoffContext = data;
    if (data.teleop_session_id) teleopHandoffSessionId = String(data.teleop_session_id);
    renderTeleopHandoff("Start teleop, move the specimen, then click Teleop Complete.");
  } catch (error) {
    teleopHandoffPanel.classList.remove("hidden");
    teleopHandoffStatusEl.textContent = String(error);
    teleopHandoffStatusEl.className = "lerobot-action-status error";
  }
}

async function startTeleopForHandoff(event) {
  const data = await runAction(
    "teleoperate start",
    "/api/lerobot/teleoperate/start",
    basePayload({
      teleop_time_s: numberValue(teleopTimeInput, null),
      handoff_token: teleopHandoffToken,
      handoff_run_id: teleopHandoffRunId,
    }),
    actionStatusFromEvent(event),
  );
  if (data && data.ok && data.session_id) {
    teleopHandoffSessionId = String(data.session_id);
    lastSessionByWorkflow.teleoperate = teleopHandoffSessionId;
    renderTeleopHandoff("Teleop is active. Move the specimen, then click Teleop Complete.");
  }
  return data;
}

async function stopTeleopForHandoff(event) {
  const data = await runAction(
    "teleoperate stop",
    "/api/lerobot/teleoperate/stop",
    sessionPayload("teleoperate", teleopHandoffSessionId ? { session_id: teleopHandoffSessionId } : {}),
    actionStatusFromEvent(event),
  );
  if (teleopHandoffToken && data && data.ok) {
    renderTeleopHandoff("Teleop stopped. Click Teleop Complete to confirm the transfer.");
  }
  return data;
}

async function completeTeleopHandoff() {
  if (!teleopHandoffSessionId || !teleopHandoffContext) return;
  teleopHandoffCompleteButton.disabled = true;
  teleopHandoffStatusEl.textContent = "Stopping teleop through the standard Stop path.";
  teleopHandoffStatusEl.className = "lerobot-action-status running";
  try {
    const stopped = await postJson("/api/lerobot/teleoperate/stop", sessionPayload("teleoperate", { session_id: teleopHandoffSessionId }));
    if (!stopped.ok || stopped.status !== "STOPPED" || !stopped.port_released || !stopped.camera_returned_to_vision) {
      throw new Error(stopped.failure_code || "TELEOP_RESOURCES_NOT_RELEASED");
    }
    const confirmed = await postJson(
      `/api/planning/runs/${encodeURIComponent(teleopHandoffRunId)}/teleop-handoff/confirm`,
      {
        handoff_token: teleopHandoffToken,
        teleop_session_id: teleopHandoffSessionId,
        confirmed_by: "local_operator",
      },
    );
    teleopHandoffContext = confirmed;
    renderTeleopHandoff("Transfer confirmed. UTM Vision verification is next.");
  } catch (error) {
    teleopHandoffStatusEl.textContent = String(error);
    teleopHandoffStatusEl.className = "lerobot-action-status error";
    teleopHandoffCompleteButton.disabled = false;
  }
}

function recordIsActive(data) {
  if (!data || data.workflow !== "record") return false;
  const status = String(data.status || "").toUpperCase();
  const terminal = new Set(["STOPPED", "FAILED", "COMPLETED", "CANCELLED", "DATASET_COMPLETE"]);
  return !terminal.has(status) && (data.returncode === undefined || data.returncode === null);
}

function handleRecordProgressResponse(data) {
  if (!data || data.workflow !== "record") return;
  if (recordIsActive(data)) {
    startRecordStatusPolling(data.session_id || "");
  } else {
    stopRecordStatusPolling();
  }
  handleIsaacRgbdRenderResponse(data);
}

function startRecordStatusPolling(sessionId = "") {
  stopRecordStatusPolling();
  const target = $("lerobot-record-action-status");
  recordStatusTimer = window.setInterval(async () => {
    try {
      const data = await postJson("/api/lerobot/record/status", sessionPayload("record", sessionId ? { session_id: sessionId } : {}));
      setActionStatus(target, data && data.ok ? "ok" : "error", "record status", data);
      renderResult("record status", data);
      syncFieldsFromWorkflowResponse(data);
      handleIsaacRgbdRenderResponse(data);
      if (!recordIsActive(data)) {
        stopRecordStatusPolling();
        await refreshConfig();
      }
    } catch (err) {
      setActionStatus(target, "error", "record status", { error: String(err) });
      stopRecordStatusPolling();
    }
  }, 3000);
}

function stopRecordStatusPolling() {
  if (recordStatusTimer) {
    window.clearInterval(recordStatusTimer);
    recordStatusTimer = null;
  }
}

async function runTrainAction(label, url, payload = null, timeoutMs = 30000) {
  const statusTarget = $("lerobot-train-action-status");
  renderTrainingPreflightProgress({
    training_preflight: {
      stage: "request_sent",
      done: 0,
      total: 4,
      percent: 5,
      message: "training request sent",
      stages: [],
    },
  });
  renderResult(`${label} running`, { ok: true, workflow: "train", status: "request_sent" });
  setActionStatus(statusTarget, "running", label, { status: "request sent", workflow: "train" });
  try {
    const data = await postJson(url, payload || trainPayload(), timeoutMs);
    renderResult(label, data);
    if (data && data.workflow && data.workflow !== "train") {
      setActionStatus(statusTarget, "error", label, {
        status: "workflow_mismatch",
        error: `Expected train response, received ${data.workflow}.`,
      });
      return data;
    }
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", label, data);
    syncFieldsFromWorkflowResponse(data);
    handleTrainProgressResponse(data);
    await refreshConfig();
    return data;
  } catch (err) {
    const error = { ok: false, workflow: "train", status: "request_failed", error: String(err) };
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    return error;
  }
}

async function runRolloutAction(label, url, payload = null, timeoutMs = 30000) {
  const statusTarget = $("lerobot-rollout-action-status");
  renderResult(`${label} running`, { ok: true, workflow: "rollout", status: "request_sent" });
  setActionStatus(statusTarget, "running", label, { status: "request sent", workflow: "rollout" });
  try {
    const data = await postJson(url, payload || rolloutPayload(), timeoutMs);
    renderResult(label, data);
    if (data && data.workflow && data.workflow !== "rollout") {
      setActionStatus(statusTarget, "error", label, {
        status: "workflow_mismatch",
        error: `Expected rollout response, received ${data.workflow}.`,
      });
      return data;
    }
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", label, data);
    syncFieldsFromWorkflowResponse(data);
    handleRolloutProgressResponse(data);
    await refreshConfig();
    return data;
  } catch (err) {
    const error = { ok: false, workflow: "rollout", status: "request_failed", error: String(err) };
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    return error;
  }
}

function handleTrainProgressResponse(data) {
  if (!data || data.workflow !== "train") return;
  renderTrainingPreflightProgress(data);
  renderTrainingProgress(data);
  if (trainIsActive(data)) {
    startTrainStatusPolling();
  } else {
    stopTrainStatusPolling();
  }
}

function startTrainStatusPolling() {
  stopTrainStatusPolling();
  const target = $("lerobot-train-action-status");
  trainStatusTimer = window.setInterval(async () => {
    try {
      const data = await postJson("/api/lerobot/train/status", sessionPayload("train"));
      if (data && data.workflow && data.workflow !== "train") {
        stopTrainStatusPolling();
        return;
      }
      setActionStatus(target, data && data.ok ? "ok" : "error", "train status", data);
      renderTrainingPreflightProgress(data);
      renderTrainingProgress(data);
      if (!trainIsActive(data)) {
        stopTrainStatusPolling();
        await refreshConfig();
      }
    } catch (err) {
      setActionStatus(target, "error", "train status", { error: String(err) });
      stopTrainStatusPolling();
    }
  }, 5000);
}

function stopTrainStatusPolling() {
  if (trainStatusTimer) {
    window.clearInterval(trainStatusTimer);
    trainStatusTimer = null;
  }
}

function rolloutIsActive(data) {
  if (!data || data.workflow !== "rollout") return false;
  const status = String(data.status || "").toUpperCase();
  const terminal = new Set(["STOPPED", "FAILED", "COMPLETED", "CANCELLED"]);
  return !terminal.has(status) && (data.returncode === undefined || data.returncode === null);
}

function handleRolloutProgressResponse(data) {
  if (!data || data.workflow !== "rollout") return;
  if (rolloutIsActive(data)) {
    startRolloutStatusPolling(data.session_id || "");
  } else {
    stopRolloutStatusPolling();
  }
}

function startRolloutStatusPolling(sessionId = "") {
  stopRolloutStatusPolling();
  const target = $("lerobot-rollout-action-status");
  rolloutStatusTimer = window.setInterval(async () => {
    try {
      const payload = sessionPayload("rollout", sessionId ? { session_id: sessionId } : {});
      const data = await postJson("/api/lerobot/rollout/status", payload);
      renderResult("rollout status", data);
      if (data && data.workflow && data.workflow !== "rollout") {
        stopRolloutStatusPolling();
        return;
      }
      setActionStatus(target, data && data.ok ? "ok" : "error", "rollout status", data);
      if (!rolloutIsActive(data)) {
        stopRolloutStatusPolling();
        await refreshConfig();
      }
    } catch (err) {
      setActionStatus(target, "error", "rollout status", { error: String(err) });
      stopRolloutStatusPolling();
    }
  }, 3000);
}

function stopRolloutStatusPolling() {
  if (rolloutStatusTimer) {
    window.clearInterval(rolloutStatusTimer);
    rolloutStatusTimer = null;
  }
}

function sessionPayload(workflow, overrides = {}) {
  return basePayload({ session_id: lastSessionByWorkflow[workflow] || "", ...overrides });
}

function renderBrowser(data) {
  if (!browserEl) return;
  browserEl.classList.remove("hidden");
  const entries = data.entries || [];
  const rows = entries.map((entry) => `
    <button class="browser-entry ${escapeHtml(entry.kind)}" data-path="${escapeHtml(entry.path)}" data-kind="${escapeHtml(entry.kind)}">
      <span>${entry.kind === "dir" ? "DIR" : "FILE"}</span>
      <strong>${escapeHtml(entry.name)}</strong>
    </button>
  `).join("");
  const canUseCurrent = Boolean(lastBrowseTargetInput) && ((lastBrowseOptions.select || "directory") !== "file" || lastBrowseKind === "policy");
  browserEl.innerHTML = `
    <div class="browser-head">
      <button class="btn mini" id="btn-browser-parent">Parent</button>
      ${canUseCurrent ? `<button class="btn mini primary" id="btn-browser-use-current">Use current path</button>` : ""}
      <button class="btn mini" id="btn-browser-refresh">Refresh</button>
      <button class="btn mini danger" id="btn-browser-close">Close</button>
      <code>${escapeHtml(data.path || "")}</code>
    </div>
    <div class="browser-grid">${rows || "<p>No entries.</p>"}</div>
  `;
  const parentBtn = $("btn-browser-parent");
  if (parentBtn && data.parent) parentBtn.addEventListener("click", () => browsePath(lastBrowseKind, data.parent, lastBrowseTargetInput, lastBrowseOptions));
  const useCurrentBtn = $("btn-browser-use-current");
  if (useCurrentBtn) {
    useCurrentBtn.addEventListener("click", async () => {
      await applyBrowseSelection(data.path || "");
      browserEl.classList.add("hidden");
      if (lastBrowseKind === "dataset" && lastBrowseTargetInput === datasetInput) {
        await restoreDatasetProfileFromCurrentInput();
      }
    });
  }
  const refreshBtn = $("btn-browser-refresh");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", async () => {
      const refreshed = await postJson("/api/lerobot/files/browse", {
        kind: lastBrowseKind,
        path: data.path || "",
        include_files: lastBrowseOptions.include_files !== false,
      });
      renderBrowser(refreshed);
      renderResult("browse refresh", refreshed);
    });
  }
  const closeBtn = $("btn-browser-close");
  if (closeBtn) closeBtn.addEventListener("click", () => browserEl.classList.add("hidden"));
  for (const button of browserEl.querySelectorAll(".browser-entry")) {
    button.addEventListener("click", async () => {
      const path = button.dataset.path || "";
      const kind = button.dataset.kind || "file";
      if (kind === "dir") {
        if (lastBrowseTargetInput) lastBrowseTargetInput.value = browseSelectionValue(path);
        if (lastBrowseKind === "dataset" && lastBrowseTargetInput === datasetInput) {
          await restoreDatasetProfileFromCurrentInput();
        }
        browsePath(lastBrowseKind, path, lastBrowseTargetInput, lastBrowseOptions);
      } else if (lastBrowseTargetInput) {
        await applyBrowseSelection(path);
        browserEl.classList.add("hidden");
        if (lastBrowseKind === "dataset" && lastBrowseTargetInput === datasetInput) {
          await restoreDatasetProfileFromCurrentInput();
        }
      }
    });
  }
}

function renderPortCandidates(data) {
  if (!portCandidatesEl) return;
  const ports = [];
  if (Array.isArray(data.candidates)) {
    for (const port of data.candidates) ports.push({ port, role: data.device_role || "candidate" });
  }
  if (Array.isArray(data.ports)) {
    for (const item of data.ports) ports.push({ port: item.port, role: item.role || item.port_type || "candidate" });
  }
  if (Array.isArray(data.serial_ports)) {
    for (const port of data.serial_ports) ports.push({ port, role: "serial" });
  }
  if (Array.isArray(data.camera_ports)) {
    for (const port of data.camera_ports) ports.push({ port, role: "camera" });
  }
  const unique = [];
  const seen = new Set();
  for (const item of ports) {
    if (!item.port || seen.has(item.port)) continue;
    seen.add(item.port);
    unique.push(item);
  }
  lastPortCandidates = unique;
  portCandidatesEl.innerHTML = unique.length
    ? unique.map((item) => `<button class="btn mini" data-port="${item.port}">${item.role}: ${item.port}</button>`).join("")
    : "<span class=\"hint\">No candidate ports found yet.</span>";
  for (const button of portCandidatesEl.querySelectorAll("button[data-port]")) {
    button.addEventListener("click", () => {
      if (manualPortInput) manualPortInput.value = button.dataset.port || "";
    });
  }
}

function renderCameraTest(data) {
  if (!cameraPreviewEl) return;
  if (!data.ok) {
    cameraPreviewEl.innerHTML = `<pre class="command-output">${JSON.stringify(data, null, 2)}</pre>`;
    return;
  }
  const capture = data.capture || {};
  const img = capture.serve_url ? `<img src="${capture.serve_url}" alt="LeRobot camera test frame" />` : "";
  cameraPreviewEl.innerHTML = `
    ${img}
    <div class="visual-summary">
      <strong>${capture.path || "capture complete"}</strong>
      <span>${data.camera_key || "camera"} · ${data.camera_port || ""} · ${capture.synthetic ? "synthetic" : "live"}</span>
    </div>
  `;
}

function rerunViewerUrl(viz) {
  if (!viz || viz.tool !== "rerun" || viz.visualization_mode !== "distant" || viz.save) return "";
  if (viz.viewer_url) return viz.viewer_url;
  if (!viz.rerun_web_url || !viz.rerun_ws_url) return viz.rerun_web_url || "";
  const separator = String(viz.rerun_web_url).includes("?") ? "&" : "/?url=";
  if (separator === "&") return `${viz.rerun_web_url}&url=${encodeURIComponent(viz.rerun_ws_url)}`;
  return `${String(viz.rerun_web_url).replace(/\/$/, "")}${separator}${encodeURIComponent(viz.rerun_ws_url)}`;
}

async function runDevicePortAction(label, url, role, overrides = {}, statusTarget = null) {
  const statusTargetId = statusTarget && statusTarget.id ? statusTarget.id : "";
  renderResult(`${label} running`, { ok: true, status: "request_sent", role });
  setActionStatus(statusTarget, "running", label, { status: "request sent" });
  try {
    const data = await postJson(url, devicePayload(role, overrides));
    renderResult(label, data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", label, data);
    renderPortCandidates(data);
    if (data.tool === "lerobot.camera.test") renderCameraTest(data);
    await refreshConfig();
    if (statusTargetId) setActionStatus(statusTargetId, data && data.ok ? "ok" : "error", label, data);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    if (statusTargetId) setActionStatus(statusTargetId, "error", label, error);
    return error;
  }
}

async function openNativePathPicker(path = "") {
  const select = lastBrowseOptions.select || "directory";
  const includeFiles = lastBrowseOptions.include_files !== false;
  renderResult("native path picker", { ok: true, status: "opening_native_picker" });
  const picked = await postJson("/api/lerobot/files/pick", { kind: lastBrowseKind, path, include_files: includeFiles, select }, 300000);
  renderResult("native path picker", picked);
  if (picked && picked.ok && picked.selected_path) {
    await applyBrowseSelection(picked.selected_path);
    if (browserEl) browserEl.classList.add("hidden");
    if (lastBrowseKind === "dataset" && lastBrowseTargetInput === datasetInput) {
      await restoreDatasetProfileFromCurrentInput();
    }
  }
  return picked;
}

async function browsePath(kind, path = "", targetInput = null, options = {}) {
  lastBrowseKind = kind || "any";
  lastBrowseTargetInput = targetInput;
  lastBrowseOptions = { include_files: true, select: "directory", ...options };
  if (browserEl) browserEl.classList.add("hidden");

  try {
    const picked = await openNativePathPicker(path || "");
    const pickerStatus = String((picked && (picked.status || picked.failure_code)) || "").toLowerCase();
    if (picked && (picked.ok || pickerStatus.includes("cancel"))) return picked;
  } catch (err) {
    renderResult("native path picker", { ok: false, status: "request_failed", error: String(err) });
  }

  placeBrowserNearTarget();
  const includeFiles = lastBrowseOptions.include_files !== false;
  try {
    const data = await postJson("/api/lerobot/files/browse", { kind: lastBrowseKind, path, include_files: includeFiles });
    renderBrowser(data);
    renderResult("browse paths fallback", data);
    return data;
  } catch (err) {
    const error = { ok: false, tool: "lerobot.files.browse", status: "request_failed", error: String(err) };
    renderResult("browse paths", error);
    if (browserEl) {
      browserEl.classList.remove("hidden");
      browserEl.innerHTML = `<div class="browser-head"><button class="btn mini danger" id="btn-browser-close">Close</button><code>Browse failed</code></div><pre class="command-output">${escapeHtml(String(err))}</pre>`;
      const closeBtn = $("btn-browser-close");
      if (closeBtn) closeBtn.addEventListener("click", () => browserEl.classList.add("hidden"));
    }
    return error;
  }
}

function renderVisualizationSession(data) {
  if (!visualizationEl) return;
  renderVisualizationProgress(data);
  const viz = (data && data.visualization) || {};
  const command = Array.isArray(data && data.command_preview) ? data.command_preview.join(" ") : "";
  const tool = viz.tool || "html";
  const mode = viz.visualization_mode || "local";
  const episodeList = Array.isArray(viz.episode_indices) && viz.episode_indices.length
    ? viz.episode_indices.join(",")
    : String(viz.episode_index ?? "");
  const openViewerUrl = rerunViewerUrl(viz) || viz.viewer_url || "";
  const viewerHint = tool === "html"
    ? `LeRobot HTML viewer: ${viz.viewer_url || "waiting for server URL"}`
    : mode === "distant"
    ? `Rerun viewer: ${viz.viewer_url || viz.rerun_web_url || "waiting for viewer URL"} · websocket: ${viz.rerun_ws_url || "ws://localhost:9089"}`
    : (viz.save ? `RRD output: ${viz.output_dir || "configured output dir"}` : "Local Rerun viewer should open from the LeRobot process.");
  const viewerLink = openViewerUrl
    ? `<a class="btn mini primary" href="${escapeHtml(openViewerUrl)}" target="_blank" rel="noopener">Open viewer</a>`
    : "";
  visualizationEl.innerHTML = `
    <div class="visual-summary">
      <strong>${escapeHtml(viz.repo_id || data.dataset_path || "LeRobot visualization")}</strong>
      <span>tool=${escapeHtml(tool)} · session=${escapeHtml((data && data.session_id) || "")} · status=${escapeHtml((data && data.status) || "")} · viewer episode=${escapeHtml(String(viz.episode_index ?? ""))} · selected=${escapeHtml(episodeList)}</span>
      <span>${escapeHtml(viewerHint)}</span>
      ${viewerLink}
    </div>
    <details open><summary>LeRobot visualize command</summary><pre class="command-output">${escapeHtml(command || "No command preview.")}</pre></details>
    ${data && data.log_tail ? `<details open><summary>Process log</summary><pre class="command-output">${escapeHtml(data.log_tail)}</pre></details>` : ""}
  `;
}

function visualizationProgressPayload(data) {
  const status = String((data && data.status) || "").toUpperCase();
  const viz = (data && data.visualization) || {};
  if (viz && viz.stale) {
    return { stage: "stale", done: 1, total: 1, percent: 100, message: viz.stale_reason || "viewer process is stale" };
  }
  if (!data || data.status === "request_sent") {
    return { stage: "request_sent", done: 0, total: 4, percent: 8, message: "request sent" };
  }
  if (status === "RUNNING") {
    return { stage: "viewer_running", done: 3, total: 4, percent: 75, message: viz.viewer_url || viz.rerun_web_url || viz.rerun_ws_url || "viewer process started" };
  }
  if (status === "VISUALIZING") {
    return { stage: "viewer_running", done: 4, total: 4, percent: 100, message: viz.viewer_url || viz.rerun_web_url || viz.rerun_ws_url || "viewer process is running" };
  }
  if (status === "COMPLETED") {
    return { stage: "complete", done: 4, total: 4, percent: 100, message: "visualization complete" };
  }
  if (status === "FAILED" || data.ok === false) {
    return { stage: "failed", done: 4, total: 4, percent: 100, message: data.error || "visualization failed" };
  }
  return { stage: "starting", done: 2, total: 4, percent: 45, message: viz.viewer_url || viz.rerun_web_url || "starting viewer" };
}

function renderVisualizationProgress(data) {
  renderUnifiedProgress(
    "visualization",
    visualizationProgressEl,
    visualizationProgressLabelEl,
    visualizationProgressBarEl,
    visualizationProgressPayload(data),
  );
}

function renderVisualization(data) {
  if (!visualizationEl) return;
  if (!data.ok) {
    visualizationEl.innerHTML = `<pre class="command-output">${JSON.stringify(data, null, 2)}</pre>`;
    return;
  }
  const media = data.media || [];
  const videos = media.filter((item) => item.media_type === "video");
  const images = media.filter((item) => item.media_type === "image");
  const dataFiles = media.filter((item) => item.media_type === "data");
  const sourceCounts = data.summary && data.summary.source_counts ? data.summary.source_counts : {};
  const episodeList = Array.isArray(data.episode_indices) && data.episode_indices.length
    ? data.episode_indices.join(",")
    : String(data.episode_index ?? "");
  const sourceCountsHtml = Object.entries(sourceCounts)
    .map(([source, count]) => `<span>${escapeHtml(source)}=${escapeHtml(String(count))}</span>`)
    .join("");
  const caption = (item) => `${escapeHtml(item.source || "dataset")} · ep=${escapeHtml(String(item.episode_index ?? ""))} · ${escapeHtml(item.name || "")}`;
  const videoHtml = videos.map((item) => `<figure><video src="${item.serve_url}" controls muted></video><figcaption>${caption(item)}</figcaption></figure>`).join("");
  const imageHtml = images.map((item) => `<figure><img src="${item.serve_url}" alt="${escapeHtml(item.name || "dataset image")}" /><figcaption>${caption(item)}</figcaption></figure>`).join("");
  const dataHtml = dataFiles.slice(0, 36).map((item) => `<li><a href="${escapeHtml(item.serve_url || "#")}" target="_blank" rel="noopener">${escapeHtml(item.name || item.path || "data")}</a> · ${escapeHtml(item.source || "dataset")} · ep=${escapeHtml(String(item.episode_index ?? ""))} · ${escapeHtml(String(item.size_bytes || 0))} bytes</li>`).join("");
  visualizationEl.innerHTML = `
    <div class="visual-summary">
      <strong>${escapeHtml(data.dataset_path || "")}</strong>
      <span>episodes=${escapeHtml(episodeList)} · videos=${videos.length} · images=${images.length} · data=${dataFiles.length}</span>
      <span>${sourceCountsHtml || "no source counts"}</span>
    </div>
    <div class="visual-media-grid">${videoHtml}${imageHtml || ""}</div>
    <details open><summary>Dataset metadata</summary><pre class="command-output">${escapeHtml(JSON.stringify(data.metadata || {}, null, 2))}</pre></details>
    <details><summary>Data files</summary><ul>${dataHtml || "<li>No local media/data files found.</li>"}</ul></details>
  `;
}

function renderIsaacAugmentation(data) {
  if (!isaacAugmentationEl) return;
  renderIsaacAugmentationProgress(data);
  if (!data || !data.ok) {
    isaacAugmentationEl.innerHTML = `<pre class="command-output">${escapeHtml(JSON.stringify(data || {}, null, 2))}</pre>`;
    return;
  }
  const summary = data.summary || {};
  const families = Array.isArray(summary.common_augmentation_families)
    ? summary.common_augmentation_families.join(", ")
    : "";
  const recipe = summary.augmentation_recipe_version || (summary.augmentation_recipe && summary.augmentation_recipe.version) || "";
  const profile = summary.augmentation_profile || "";
  const options = summary.augmentation_options || {};
  const validVariants = Number(summary.valid_variant_count ?? summary.variant_count ?? 0);
  const failedVariants = Number(summary.failed_variant_count ?? 0);
  const qaFailureCounts = summary.qa_failure_counts && typeof summary.qa_failure_counts === "object"
    ? summary.qa_failure_counts
    : {};
  const command = Array.isArray(data.command_preview) ? data.command_preview.join(" ") : "";
  isaacAugmentationEl.innerHTML = `
    <div class="visual-summary">
      <strong>${escapeHtml(summary.output_dir || data.output_dir || "Isaac augmentation sidecar")}</strong>
      <span>sources=${escapeHtml(String(summary.source_frame_count ?? 0))} · variants=${escapeHtml(String(summary.variant_count ?? 0))} · cameras=${escapeHtml((summary.cameras || []).join ? summary.cameras.join(",") : "")}</span>
      <span>qa valid=${escapeHtml(String(validVariants))} · failed=${escapeHtml(String(failedVariants))}</span>
      <span>recipe=${escapeHtml(recipe || "unknown")} · profile=${escapeHtml(profile || "unknown")}</span>
      <span>${escapeHtml(families)}</span>
    </div>
    <details open><summary>Augmentation manifest</summary><pre class="command-output">${escapeHtml(summary.manifest_path || "No manifest path.")}</pre></details>
    <details><summary>QA summary</summary><pre class="command-output">${escapeHtml(JSON.stringify({
      qa_summary_path: summary.qa_summary_path || "",
      valid_variant_count: validVariants,
      failed_variant_count: failedVariants,
      qa_failure_counts: qaFailureCounts,
    }, null, 2))}</pre></details>
    <details><summary>Recipe options</summary><pre class="command-output">${escapeHtml(JSON.stringify(options, null, 2))}</pre></details>
    <details><summary>Command preview</summary><pre class="command-output">${escapeHtml(command || "No command preview.")}</pre></details>
  `;
}

function isaacAugmentationProgressPayload(data) {
  const summary = (data && data.summary) || {};
  if (data && data.augmentation_progress) return data.augmentation_progress;
  if (summary && summary.progress) return summary.progress;
  if (!data || data.status === "request_sent") {
    return { stage: "request_sent", done: 0, total: 1, percent: 5, message: "request sent" };
  }
  if (data && data.ok === false) {
    return { stage: "failed", done: 1, total: 1, percent: 100, message: data.error || "augmentation failed" };
  }
  if (data && data.ok) {
    const total = Number(summary.variant_count || 1);
    return { stage: "complete", done: total, total, percent: 100, message: "augmentation complete" };
  }
  return { stage: "waiting", done: 0, total: 1, percent: 0, message: "waiting" };
}

function renderIsaacAugmentationProgress(data) {
  renderUnifiedProgress(
    "isaac_augmentation",
    isaacAugmentationProgressEl,
    isaacAugmentationProgressLabelEl,
    isaacAugmentationProgressBarEl,
    isaacAugmentationProgressPayload(data),
  );
}

function isaacPreviewImageHtml(title, ref) {
  const serveUrl = ref && ref.serve_url ? String(ref.serve_url) : "";
  if (!serveUrl) {
    return `
      <figure>
        <div class="visual-placeholder">missing</div>
        <figcaption>${escapeHtml(title)}</figcaption>
      </figure>
    `;
  }
  return `
    <figure>
      <img src="${escapeHtml(serveUrl)}" alt="${escapeHtml(title)}" loading="lazy" />
      <figcaption>${escapeHtml(title)}</figcaption>
    </figure>
  `;
}

function renderIsaacAugmentationPreview(data) {
  if (!isaacAugmentationPreviewEl) return;
  if (!data || !data.ok) {
    isaacAugmentationPreviewEl.innerHTML = `<pre class="command-output">${escapeHtml(JSON.stringify(data || {}, null, 2))}</pre>`;
    return;
  }
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const cards = rows.map((row) => {
    const qa = row.qa || {};
    const qaState = qa.ok ? "ok" : "warning";
    return `
      <article class="lerobot-report-card wide">
        <div class="lerobot-report-card-title">
          <strong>${escapeHtml(row.variant_id || "variant")}</strong>
          <span class="state-pill ${escapeHtml(qaState)}">${escapeHtml(qa.ok ? "qa ok" : (qa.failure_code || "qa failed"))}</span>
        </div>
        <div class="visual-media-grid">
          ${isaacPreviewImageHtml("source rgb", row.source_rgb)}
          ${isaacPreviewImageHtml("source_depth_preview", row.source_depth_preview)}
          ${isaacPreviewImageHtml("augmented rgb", row.augmented_rgb)}
          ${isaacPreviewImageHtml("augmented_depth_preview", row.augmented_depth_preview)}
        </div>
        ${reportRowsHtml([
          ["Episode", row.episode_index],
          ["Frame", row.frame_index],
          ["Camera", row.camera],
          ["Depth valid", qa.depth_valid_ratio],
        ])}
        <details><summary>Pose / augmentation metadata</summary><pre class="command-output">${escapeHtml(JSON.stringify({
          source_pose: row.source_pose || {},
          augmentation_parameters: row.augmentation_parameters || {},
          qa,
        }, null, 2))}</pre></details>
      </article>
    `;
  }).join("");
  isaacAugmentationPreviewEl.innerHTML = `
    <div class="visual-summary">
      <strong>${escapeHtml(data.preview_dir || "Isaac augmentation previews")}</strong>
      <span>preview rows=${escapeHtml(String(data.preview_count ?? rows.length))} · requested=${escapeHtml(String(data.requested_count ?? ""))}</span>
      <span>${escapeHtml(data.manifest_path || "")}</span>
    </div>
    <div class="lerobot-report-grid">${cards || "<p>No preview rows available.</p>"}</div>
  `;
}

function setSyntheticCard(el, title, rows = []) {
  if (!el) return;
  el.innerHTML = `
    <div class="lerobot-report-card-title"><strong>${escapeHtml(title)}</strong></div>
    ${reportRowsHtml(rows)}
  `;
}

function syntheticCameraPrimLabel(cameraPrims) {
  if (!Array.isArray(cameraPrims) || !cameraPrims.length) return "-";
  return cameraPrims
    .map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return "";
      const camera = item.camera || "";
      const path = item.path || "";
      const status = item.found === false ? "missing" : "";
      return [camera, path, status].filter(Boolean).join(":");
    })
    .filter(Boolean)
    .join(", ");
}

function renderIsaacSyntheticProgress(data) {
  const progress = (data && data.progress) || {};
  const isDomainMimicJob = Boolean(
    data
    && (
      data.job_id
      || data.job
      || (data.summary && data.summary.mimic)
      || String(progress.stage || "").includes("rgbd_render")
    )
    && (
      data.mimic
      || (data.summary && data.summary.mimic)
      || String(data.kind || data.job?.kind || "").includes("mimic")
      || String(progress.stage || "").includes("rgbd_render")
    )
  );
  const unifiedProgress = isDomainMimicJob
    ? isaacDomainMimicProgressPayload(data)
    : {
        stage: data && data.status ? data.status : "waiting",
        done: Number(progress.percent || 0),
        total: 100,
        percent: Number(progress.percent || (data && data.ok ? 100 : 0)),
        message: data && data.status ? data.status : "waiting",
      };
  renderUnifiedProgress(
    "isaac_synthetic",
    isaacSyntheticProgressEl,
    isaacSyntheticProgressLabelEl,
    isaacSyntheticProgressBarEl,
    unifiedProgress,
    isDomainMimicJob ? { label: "7", stage: data && data.status ? data.status : "waiting" } : {},
  );
}

function isaacLabPreviewMediaHtml(title, ref) {
  const serveUrl = ref && ref.serve_url ? String(ref.serve_url) : "";
  const rawPath = ref && ref.path ? String(ref.path) : "";
  if (!serveUrl) {
    return `
      <figure>
        <div class="visual-placeholder">missing</div>
        <figcaption>${escapeHtml(title)}</figcaption>
      </figure>
    `;
  }
  const lowerPath = rawPath.toLowerCase();
  if (lowerPath.endsWith(".html") || lowerPath.endsWith(".htm")) {
    return `
      <figure>
        <div class="visual-placeholder">
          <a class="btn mini" href="${escapeHtml(serveUrl)}" target="_blank" rel="noopener">Open preview</a>
        </div>
        <figcaption>${escapeHtml(title)}</figcaption>
      </figure>
    `;
  }
  return `
    <figure>
      <img src="${escapeHtml(serveUrl)}" alt="${escapeHtml(title)}" loading="lazy" />
      <figcaption>${escapeHtml(title)}</figcaption>
    </figure>
  `;
}

function renderIsaacLabPreviewCards(sourceLabels) {
  const cards = Array.isArray(sourceLabels.cards) ? sourceLabels.cards : [];
  if (!cards.length) return "";
  const cardHtml = cards.map((card) => {
    const media = card.media || {};
    const trajectory = card.trajectory || {};
    const qa = card.qa || card.metrics || {};
    const eligible = Boolean(card.train_eligible);
    const state = eligible ? "ok" : "warning";
    const title = [
      card.source_type || "source",
      card.episode_index !== undefined ? `ep=${card.episode_index}` : "",
      card.frame_index !== undefined ? `frame=${card.frame_index}` : "",
      card.camera ? `cam=${card.camera}` : "",
      card.variant_index !== undefined ? `v=${card.variant_index}` : "",
    ].filter(Boolean).join(" · ");
    const mediaHtml = [
      ["real rgb", media.real_rgb],
      ["raw depth", media.raw_depth_preview],
      ["isaac rgbd", media.isaac_rgbd],
      ["replicator rgb", media.replicator_rgb],
      ["replicator depth", media.replicator_depth_preview],
      ["generated rgb", media.generated_rgb_preview],
      ["generated depth", media.generated_depth_preview],
      ["trajectory preview", trajectory.preview],
    ]
      .filter(([, ref]) => ref && (ref.available || ref.serve_url))
      .map(([label, ref]) => isaacLabPreviewMediaHtml(label, ref))
      .join("");
    return `
      <article class="lerobot-report-card wide">
        <div class="lerobot-report-card-title">
          <strong>${escapeHtml(title || card.row_id || "Isaac Lab source")}</strong>
          <span class="state-pill ${escapeHtml(state)}">${escapeHtml(eligible ? "train" : (card.train_exclusion_reason || "preview"))}</span>
        </div>
        <div class="visual-media-grid">${mediaHtml || "<p>No preview media available.</p>"}</div>
        ${reportRowsHtml([
          ["source", card.source_type || "-"],
          ["episode", card.episode_index ?? "-"],
          ["frame", card.frame_index ?? "-"],
          ["camera", card.camera || "-"],
          ["trajectory", trajectory.trajectory_id || card.source_id || "-"],
        ])}
        <details><summary>Source metadata</summary><pre class="command-output">${escapeHtml(JSON.stringify({
          row_id: card.row_id || "",
          qa,
          metrics: card.metrics || {},
          trajectory,
          train_exclusion_reason: card.train_exclusion_reason || "",
        }, null, 2))}</pre></details>
      </article>
    `;
  }).join("");
  return `
    <div class="visual-summary">
      <strong>Isaac Lab preview sources</strong>
      <span>preview cards=${escapeHtml(String(cards.length))} · requested=${escapeHtml(String(sourceLabels.requested_count ?? ""))}</span>
    </div>
    <div class="lerobot-report-grid">${cardHtml}</div>
  `;
}

function renderIsaacSynthetic(data) {
  if (!isaacSyntheticOutputEl) return;
  renderIsaacSyntheticProgress(data);
  const compatibility = (data && data.compatibility) || {};
  const digitalTwin = (data && data.digital_twin) || {};
  const canonical = (data && data.canonical_episode_index) || {};
  const sourceLabels = (data && data.source_labels) || {};
  const trainingExposure = (data && data.training_exposure) || {};
  const syntheticTrajectoryMetrics = (data && data.synthetic_trajectory_metrics) || {};
  const syntheticTrajectoryTotal = syntheticTrajectoryMetrics.total || {};
  const hdf5 = (data && data.hdf5) || {};
  const validation = (data && data.validation_report) || {};
  const blockers = Array.isArray(validation.blockers) ? validation.blockers : [];
  const sourceCounts = sourceLabels.counts || {};
  const sourceDetails = sourceLabels.details || {};
  const sourceTrainableCount = (sourceType) => {
    const detail = sourceDetails[sourceType] || {};
    return Number(detail.trainable_count || 0);
  };
  const sourceCountLabel = (sourceType) => `${Number(sourceCounts[sourceType] || 0)} total / ${sourceTrainableCount(sourceType)} trainable`;
  function syntheticTrajectoryMetricLabel(kind) {
    const metric = syntheticTrajectoryMetrics[kind] || {};
    return `${Number(metric.candidate_count || 0)} cand / ${Number(metric.success_count || 0)} ok / ${Number(metric.failure_count || 0)} fail`;
  }
  function syntheticSourceTypeSummary() {
    const names = Object.keys(sourceCounts).filter((name) => Number(sourceCounts[name] || 0) > 0);
    if (!names.length) return "-";
    return names.map((name) => `${name}:${Number(sourceCounts[name] || 0)}`).join(" · ");
  }
  function syntheticEffectiveSampleLabel() {
    const total = syntheticTrajectoryTotal.effective_training_samples;
    const rows = syntheticTrajectoryTotal.training_row_count;
    if (total === undefined && rows === undefined) return "-";
    return `${total ?? "-"} effective / ${rows ?? 0} rows`;
  }
  function sourceWeightLabel(sourceType) {
    const detail = sourceDetails[sourceType] || {};
    const sourceWeight = detail.source_weight ?? sourceLabels.weights?.[sourceType];
    const fidelityWeight = detail.fidelity_weight ?? sourceLabels.fidelity_weights?.[sourceType];
    const effectiveWeight = detail.effective_weight;
    const trainingRows = detail.training_row_count ?? 0;
    return `src=${sourceWeight ?? "-"} fidelity=${fidelityWeight ?? "-"} effective=${effectiveWeight ?? "-"} rows=${trainingRows}`;
  }
  const candidateSourceCounts = trainingExposure.candidate_source_counts || {};
  const exposedSourceCounts = trainingExposure.source_counts || {};
  const replicatorProbeCheck = Array.isArray(data?.replicator?.checks)
    ? data.replicator.checks.find((check) => check && check.id === "replicator_import_probe")
    : null;
  const replicatorProbe = (data?.replicator?.runtime_probe) || {};
  setSyntheticCard(isaacSyntheticCompatibilityEl, "Compatibility", [
    ["status", compatibility.compatibility_status || data?.status || "-"],
    ["Lab", compatibility.isaac_lab_exists === undefined ? "-" : compatibility.isaac_lab_exists ? "present" : "missing"],
    ["Lab tag", compatibility.isaac_lab_git_tag || compatibility.lab?.git_tag || "-"],
    ["Lab commit", compatibility.isaac_lab_git_commit || compatibility.lab?.git_commit || "-"],
    ["Sim", compatibility.isaac_sim_version || compatibility.sim?.version || "-"],
    ["docs", compatibility.isaac_sim_docs_version || "-"],
    ["Replicator", compatibility.replicator?.status || replicatorProbe.status || "-"],
  ]);
  setSyntheticCard(isaacSyntheticDigitalTwinEl, "Digital Twin", [
    ["stage", digitalTwin.stage_exists === undefined ? "-" : digitalTwin.stage_exists ? "present" : "missing"],
    ["cameras", syntheticCameraPrimLabel(digitalTwin.camera_prims)],
  ]);
  setSyntheticCard(isaacSyntheticSourceLabelsEl, "Source Labels", [
    ["real", sourceCountLabel("real_lerobot")],
    ["isaac_rgbd", sourceCountLabel("isaac_rgbd_render")],
    ["replicator", sourceCountLabel("replicator_render_only")],
    ["mimic", sourceCountLabel("isaac_lab_mimic")],
    ["rl_teacher", sourceCountLabel("isaac_lab_rl_teacher")],
    ["source types", syntheticSourceTypeSummary()],
    ["effective samples", syntheticEffectiveSampleLabel()],
    ["real weights", sourceWeightLabel("real_lerobot")],
    ["synthetic weights", sourceWeightLabel("isaac_lab_synthetic")],
  ]);
  setSyntheticCard(isaacSyntheticCanonicalIndexEl, "Canonical Index", [
    ["episodes", canonical.episode_count || 0],
    ["frames", canonical.frame_count || 0],
  ]);
  setSyntheticCard(isaacSyntheticGenerationEl, "Generation", [
    ["replicator", data?.replicator?.status || "skipped"],
    ["replicator probe", replicatorProbe.status || replicatorProbeCheck?.status || "-"],
    ["worker", data?.worker?.status || "-"],
    ["worker return", data?.worker?.returncode === undefined ? "-" : data.worker.returncode],
    ["mimic", data?.mimic?.status || "skipped"],
    ["rl", data?.rl_teacher?.status || "skipped"],
    ["mimic trajectories", syntheticTrajectoryMetricLabel("mimic")],
    ["rl trajectories", syntheticTrajectoryMetricLabel("rl_teacher")],
    ["job", data?.job?.status || "-"],
    ["job id", data?.job_id || data?.job?.job_id || "-"],
  ]);
  setSyntheticCard(isaacSyntheticHdf5El, "HDF5 Export", [
    ["status", hdf5.status || "not run"],
    ["blocker", hdf5.blocker || "-"],
    ["frames", hdf5.canonical_frame_count || 0],
  ]);
  setSyntheticCard(isaacSyntheticTrainingExposureEl, "Training Exposure", [
    ["rows", trainingExposure.row_count || 0],
    ["candidates", trainingExposure.candidate_row_count || 0],
    ["exposed", trainingExposure.exposed_row_count || 0],
    ["blocked rows", trainingExposure.blocked_row_count || 0],
    ["validation", trainingExposure.validation_status || "-"],
    ["candidate sources", Object.keys(candidateSourceCounts).length ? JSON.stringify(candidateSourceCounts) : "-"],
    ["exposed sources", Object.keys(exposedSourceCounts).length ? JSON.stringify(exposedSourceCounts) : "-"],
    ["synthetic training rows", syntheticTrajectoryTotal.training_row_count ?? 0],
    ["synthetic effective", syntheticTrajectoryTotal.effective_training_samples ?? "-"],
    ["blocked", blockers.length],
  ]);
  const e2e = trainingExposure.e2e || {};
  const ilTrain = trainingExposure.il_train || {};
  const ilEval = trainingExposure.il_eval || {};
  const annotation = hdf5.annotation || {};
  const domainProfile = data?.domain_randomization_profile || data?.request?.domain_randomization_profile || (e2e.domain_randomization_profile) || (isaacLabDomainRandomizationProfileInput ? isaacLabDomainRandomizationProfileInput.value : "conservative");
  setSyntheticCard(isaacLabE2eStatusCardEl, "Isaac Lab Mimic + IL E2E", [
    ["Version Gate", compatibility.compatibility_status || data?.status || "-"],
    ["HDF5 Source", hdf5.status || "not run"],
    ["Annotation", annotation.status || e2e.annotation?.status || "not run"],
    ["Mimic Generation", data?.mimic?.status || e2e.mimic?.status || "not run"],
    ["Domain Randomization Profile", domainProfile || "conservative"],
    ["Generated Success Import", syntheticTrajectoryMetricLabel("mimic")],
    ["Isaac Lab IL Training", ilTrain.status || e2e.train?.status || "not run"],
    ["Isaac Lab IL Evaluation", ilEval.status || e2e.eval?.status || "not run"],
    ["LeRobot Training Exposure", trainingExposure.validation_status || syntheticEffectiveSampleLabel()],
  ]);
  if (isaacSyntheticStepTraceEl) {
    const trace = Array.isArray(data && data.step_trace) ? data.step_trace : [];
    const items = trace.map((item) => `
      <li><strong>${escapeHtml(item.stage || item.step || "-")}</strong> · ${escapeHtml(item.status || "-")} · ${escapeHtml(item.message || item.detail || "")}</li>
    `).join("");
    isaacSyntheticStepTraceEl.innerHTML = `<details open><summary>Synthetic step trace</summary><ul>${items || "<li>No step trace.</li>"}</ul></details>`;
  }
  isaacSyntheticOutputEl.innerHTML = `
    <div class="visual-summary">
      <strong>${escapeHtml(data && data.output_root ? data.output_root : "Isaac Lab synthetic")}</strong>
      <span>status=${escapeHtml(data && data.status ? data.status : "unknown")} · blockers=${escapeHtml(String(blockers.length))}</span>
      <span>${escapeHtml(data && data.pipeline_mode ? data.pipeline_mode : "")}</span>
    </div>
    ${renderIsaacLabPreviewCards(sourceLabels)}
    <details><summary>Validation report</summary><pre class="command-output">${escapeHtml(JSON.stringify(validation, null, 2))}</pre></details>
    <details><summary>Full response</summary><pre class="command-output">${escapeHtml(JSON.stringify(data || {}, null, 2))}</pre></details>
  `;
}

async function runIsaacAugmentation(statusTarget = null) {
  const payload = isaacAugmentationPayload();
  renderIsaacAugmentationProgress({ status: "request_sent" });
  setActionStatus(statusTarget, "running", "Isaac data augmentation", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/augment/isaac", payload, 30000);
    renderIsaacAugmentation(data);
    renderResult("Isaac data augmentation", data);
    if (data && data.ok && data.job_id && String(data.status || "").toUpperCase() === "RUNNING") {
      return await pollIsaacAugmentationJob(data.job_id, payload, statusTarget);
    }
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "Isaac data augmentation", data);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderIsaacAugmentation(error);
    renderResult("Isaac data augmentation", error);
    setActionStatus(statusTarget, "error", "Isaac data augmentation", error);
    return error;
  }
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function pollIsaacAugmentationJob(jobId, basePayload, statusTarget = null) {
  const payload = {
    ...basePayload,
    isaac_data_augmentation_job_id: jobId,
  };
  let latest = null;
  for (;;) {
    await delay(1500);
    latest = await postJson("/api/lerobot/augment/status", payload, 30000);
    renderIsaacAugmentation(latest);
    renderResult("Isaac data augmentation", latest);
    const status = String(latest && latest.status ? latest.status : "").toUpperCase();
    if (status === "COMPLETED" || status === "FAILED" || !latest || latest.ok === false) {
      setActionStatus(statusTarget, latest && latest.ok ? "ok" : "error", "Isaac data augmentation", latest);
      return latest;
    }
    setActionStatus(statusTarget, "running", "Isaac data augmentation", latest);
  }
}

async function runIsaacSyntheticAction(label, endpoint, statusTarget = null, timeoutMs = 300000, overrides = {}) {
  const payload = isaacSyntheticPayload(overrides);
  renderIsaacSyntheticProgress({ status: "request_sent", progress: { percent: 5 } });
  setActionStatus(statusTarget, "running", label, { status: "request sent" });
  try {
    const data = await postJson(endpoint, payload, timeoutMs);
    renderIsaacSynthetic(data);
    renderResult(label, data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", label, data);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderIsaacSynthetic(error);
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    return error;
  }
}

function isaacDomainMimicPayload(overrides = {}) {
  const rgbdEnabled = checkboxValue(isaacLabDomainMimicRgbdInput || isaacLabMimicCamerasInput);
  const domainMimicOverwrite = boolValue(isaacLabDomainMimicOverwriteInput) || boolValue(isaacLabDomainMimicOverwriteAllInput);
  const domainMimicEpisodeIndices = boolValue(isaacLabDomainMimicOverwriteAllInput) ? "" : (isaacLabDomainMimicEpisodesInput ? isaacLabDomainMimicEpisodesInput.value.trim() : "");
  syncIsaacLabMimicRgbdInputs(rgbdEnabled);
  return isaacSyntheticPayload({
    mode: "live",
    runtime_mode: "live",
    dry_run: false,
    force_rebuild: domainMimicOverwrite,
    resume: !domainMimicOverwrite,
    overwrite_latest: domainMimicOverwrite,
    isaac_lab_episode_indices: domainMimicEpisodeIndices,
    enable_mimic: true,
    enable_hdf5_export: true,
    enable_replicator: false,
    mimic_generation_backend: "official",
    require_digital_twin_pass: false,
    require_depth_pass: false,
    require_physics_pass: false,
    require_articulation_pass: false,
    max_source_frames: 0,
    attempts_per_source_frame: 3,
    mimic_trials: 3,
    mimic_num_envs: 3,
    mimic_camera_width: 320,
    mimic_camera_height: 240,
    mimic_annotation_mode: "auto",
    isaac_lab_visualize_generation: checkboxValue(isaacLabVisualizeGenerationInput),
    domain_randomization_profile: isaacLabDomainRandomizationProfileInput
      ? isaacLabDomainRandomizationProfileInput.value || "standard"
      : "standard",
    mimic_enable_cameras: rgbdEnabled,
    ...overrides,
  });
}

function isaacDomainMimicFollowupPayload(payload = null) {
  return {
    ...(payload || isaacDomainMimicPayload()),
    force_rebuild: false,
    overwrite_latest: false,
    resume: true,
  };
}

function formatElapsedFromIso(value) {
  const startedMs = Date.parse(String(value || ""));
  if (!Number.isFinite(startedMs)) return "";
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedMs) / 1000));
  const hours = Math.floor(elapsedSeconds / 3600);
  const minutes = Math.floor((elapsedSeconds % 3600) / 60);
  const seconds = elapsedSeconds % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

function isaacDomainMimicProgressMessage(...parts) {
  return parts.map((part) => String(part || "").trim()).filter(Boolean).join(" · ");
}

function isaacDomainMimicProgressPayload(data) {
  const responseProgress = data && typeof data.progress === "object" ? data.progress : {};
  const jobProgress = data && data.job && typeof data.job.progress === "object" ? data.job.progress : {};
  const progress = Object.keys(jobProgress).length ? jobProgress : responseProgress;
  const mimic = data && data.summary && typeof data.summary.mimic === "object"
    ? data.summary.mimic
    : data && typeof data.mimic === "object"
      ? data.mimic
      : {};
  const success = Number(mimic.success_count ?? 0);
  const failure = Number(mimic.failure_count ?? 0);
  const status = String(data && data.status ? data.status : "waiting").toUpperCase();
  const stage = String(progress.stage || status || "waiting").toUpperCase();
  const progressDone = Number(progress.done ?? progress.current_step ?? 0);
  const progressTotal = Number(progress.total ?? progress.total_steps ?? 0);
  const configuredTotal = Number(mimic.candidate_count ?? progressTotal ?? mimic.mimic_trials ?? 100);
  const useBackendProgressOnly = status === "RUNNING" && (stage.includes("RGBD_RENDER") || progressTotal > 0);
  const done = useBackendProgressOnly ? progressDone : success + failure;
  const total = Math.max(
    progressTotal > 0 ? progressTotal : configuredTotal > 0 ? configuredTotal : 100,
    done,
  );
  const countPercent = total > 0 && done > 0 ? (done / total) * 100 : 0;
  const backendPercent = Number(progress.percent ?? 0);
  const percent = status === "COMPLETED" ? 100 : Math.max(backendPercent, countPercent);
  const jobLabel = data && data.job_id ? `job=${data.job_id}` : "";
  const elapsed = formatElapsedFromIso(data && data.job ? data.job.started_at : data && data.started_at);
  const runningDetails = useBackendProgressOnly
    ? [
        configuredTotal > 0 ? `target=${configuredTotal}` : "",
        elapsed ? `elapsed=${elapsed}` : "",
      ].filter(Boolean).join(" · ")
    : "";
  const message = progress.message
    ? String(progress.message || "")
    : isaacDomainMimicProgressMessage(jobLabel, runningDetails);
  return {
    stage: stage || "WAITING",
    done: done > 0 ? done : progressDone,
    total: total > 0 ? total : Number(progress.total ?? 100),
    percent,
    message,
    indeterminate: useBackendProgressOnly && backendPercent <= 5 && done <= 0,
  };
}

function renderIsaacDomainMimicLauncherProgress(data) {
  renderUnifiedProgress(
    "isaac_domain_mimic_launcher",
    isaacLabLauncherProgressEl,
    isaacLabLauncherProgressLabelEl,
    isaacLabLauncherProgressBarEl,
    isaacDomainMimicProgressPayload(data),
    { label: "7", stage: data && data.status ? data.status : "waiting" },
  );
}

function isaacLabOutputIssueLabel(issue) {
  const code = String(issue && issue.code ? issue.code : "").trim();
  const message = String(issue && issue.message ? issue.message : "").trim();
  if (code === "MIMIC_CANDIDATE_COUNT_MISMATCH") return `Mimic candidate mismatch · ${message || code}`;
  if (code === "MIMIC_REPLAY_FAILURES_PRESENT") return `Mimic replay failed · ${message || code}`;
  if (code === "MIMIC_REPLAY_VALIDATION_PENDING") return `Mimic replay pending · ${message || code}`;
  if (code) return `${code} · ${message || "check failed"}`;
  return message || "Isaac Lab output check failed";
}

function renderIsaacLabOutputCheckList(data = null) {
  if (!isaacLabLauncherFailureListEl) return;
  if (data) lastIsaacLabOutputCheck = data;
  const result = data || lastIsaacLabOutputCheck || {};
  const issues = Array.isArray(result.issues) ? result.issues : [];
  const checks = Array.isArray(result.checks) ? result.checks : [];
  const summary = result.check_summary || {};
  if (!issues.length && checks.length) {
    isaacLabLauncherFailureListEl.innerHTML = `
      <div class="lerobot-render-failure-empty">
        Isaac Lab output check passed · episodes=${escapeHtml(String(summary.episode_count ?? 0))}
        · mimic=${escapeHtml(String(summary.mimic_success_count ?? 0))}/${escapeHtml(String(summary.expected_mimic_candidates ?? 0))}
        · train=${escapeHtml(String(summary.training_row_count ?? 0))}
      </div>
    `;
    return;
  }
  if (!issues.length) {
    isaacLabLauncherFailureListEl.innerHTML = "";
    return;
  }
  const lines = issues.slice(0, 16).map(isaacLabOutputIssueLabel);
  if (issues.length > 16) lines.push(`+${issues.length - 16} more issue(s)`);
  isaacLabLauncherFailureListEl.innerHTML = `
    <div class="lerobot-render-failure-title">Isaac Lab Failed / Blocked Outputs</div>
    <ul>${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>
  `;
}

async function checkIsaacDomainMimicOutputs(statusTarget = null, status = "checking Isaac Lab outputs", payload = null) {
  const label = "Isaac Lab output check";
  const checkPayload = isaacDomainMimicFollowupPayload(payload);
  setActionStatus(statusTarget, "running", label, { status });
  try {
    const data = await postJson("/api/lerobot/isaac-lab/check-outputs", checkPayload, 60000);
    renderIsaacLabOutputCheckList(data);
    renderIsaacSynthetic(data);
    renderResult(label, data);
    setActionStatus(
      statusTarget,
      data && data.ok ? "ok" : "error",
      label,
      data && data.ok ? { status: "Isaac Lab output check passed", check_summary: data.check_summary || {} } : data,
    );
    return data;
  } catch (err) {
    const error = { ok: false, status: "check_failed", error: String(err) };
    renderIsaacLabOutputCheckList(error);
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    return error;
  }
}

async function refreshIsaacDomainMimicTrainingImport(payload, statusTarget = null) {
  const label = "Domain randomization + mimic pipeline";
  setActionStatus(statusTarget, "running", label, { status: "refreshing training import" });
  renderIsaacDomainMimicLauncherProgress({ status: "refreshing_training_import", progress: { percent: 95 } });
  const refreshed = await postJson("/api/lerobot/isaac-lab/build-synthetic", payload, 300000);
  renderIsaacSynthetic(refreshed);
  renderResult(label, refreshed);
  renderIsaacDomainMimicLauncherProgress({ status: refreshed && refreshed.ok ? "COMPLETED" : "FAILED", progress: { percent: refreshed && refreshed.ok ? 100 : 95 } });
  setActionStatus(statusTarget, refreshed && refreshed.ok ? "ok" : "error", label, refreshed);
  if (refreshed && refreshed.ok) {
    return await checkIsaacDomainMimicOutputs(statusTarget, "checking completed Isaac Lab outputs", payload);
  }
  return refreshed;
}

function shouldRenderIsaacLabMimicRgbdAfterGeneration(payload = {}) {
  return Boolean(payload && payload.isaac_lab_visualize_generation && payload.mimic_enable_cameras);
}

function isaacLabMimicStatusPostRunStage(data = {}) {
  const jobPostRun = data && data.job && typeof data.job.post_run === "object" ? data.job.post_run : {};
  const directPostRun = data && typeof data.post_run === "object" ? data.post_run : {};
  const summary = data && data.summary && typeof data.summary === "object" ? data.summary : {};
  const summaryMimic = summary && typeof summary.mimic === "object" ? summary.mimic : {};
  const summaryRunner = summary && typeof summary.runner === "object" ? summary.runner : {};
  const mimicRunner = summaryMimic && typeof summaryMimic.runner === "object" ? summaryMimic.runner : {};
  const summaryPostRun = summaryRunner && typeof summaryRunner.post_run === "object" ? summaryRunner.post_run : {};
  const mimicPostRun = mimicRunner && typeof mimicRunner.post_run === "object" ? mimicRunner.post_run : {};
  return String(jobPostRun.stage || directPostRun.stage || summaryPostRun.stage || mimicPostRun.stage || "").trim().toLowerCase();
}

function isaacLabMimicStatusIsRgbdRender(data = {}) {
  return isaacLabMimicStatusPostRunStage(data) === "rgbd_render_after_generation";
}

async function pollIsaacDomainMimicJob(jobId, basePayload, statusTarget = null) {
  const label = "Domain randomization + mimic pipeline";
  const payload = { ...isaacDomainMimicFollowupPayload(basePayload), job_id: jobId };
  let latest = null;
  for (;;) {
    await delay(2000);
    latest = await postJson("/api/lerobot/isaac-lab/mimic/status", payload, 30000);
    renderIsaacDomainMimicLauncherProgress(latest);
    renderIsaacSynthetic(latest);
    renderResult(label, latest);
    if (isaacSyntheticJobIsTerminal(latest)) {
      const status = String(latest && latest.status ? latest.status : "").toUpperCase();
      if (latest && latest.ok && status === "COMPLETED") {
        const refreshed = await refreshIsaacDomainMimicTrainingImport(isaacDomainMimicFollowupPayload(basePayload), statusTarget);
        if (refreshed && refreshed.ok && shouldRenderIsaacLabMimicRgbdAfterGeneration(basePayload) && !isaacLabMimicStatusIsRgbdRender(latest)) {
          return await renderMissingIsaacLabMimicRgbd(statusTarget, basePayload);
        }
        return refreshed;
      }
      setActionStatus(statusTarget, latest && latest.ok ? "ok" : "error", label, latest);
      return latest;
    }
    setActionStatus(statusTarget, "running", label, latest);
  }
}

async function runIsaacDomainMimicPipeline(statusTarget = null) {
  const label = "Domain randomization + mimic pipeline";
  const payload = isaacDomainMimicPayload();
  const followupPayload = isaacDomainMimicFollowupPayload(payload);
  renderIsaacLabOutputCheckList({ issues: [], checks: [] });
  renderIsaacSyntheticProgress({ status: "request_sent", progress: { percent: 5 } });
  renderIsaacDomainMimicLauncherProgress({ status: "request_sent", progress: { percent: 5 } });
  setActionStatus(statusTarget, "running", label, { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/isaac-lab/domain-mimic/run", payload, 300000);
    renderIsaacDomainMimicLauncherProgress(data);
    renderIsaacSynthetic(data);
    renderResult(label, data);
    lastIsaacDomainMimicJobId = String(data && (data.job_id || (data.job && data.job.job_id)) || lastIsaacDomainMimicJobId || "");
    if (lastIsaacDomainMimicJobId && !isaacSyntheticJobIsTerminal(data)) {
      setActionStatus(statusTarget, "running", label, data);
      return await pollIsaacDomainMimicJob(lastIsaacDomainMimicJobId, followupPayload, statusTarget);
    }
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", label, data);
    if (data && data.ok) {
      const checked = await checkIsaacDomainMimicOutputs(statusTarget, "checking completed Isaac Lab outputs", followupPayload);
      if (checked && checked.ok && shouldRenderIsaacLabMimicRgbdAfterGeneration(followupPayload)) {
        return await renderMissingIsaacLabMimicRgbd(statusTarget, followupPayload);
      }
      return checked;
    }
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderIsaacSynthetic(error);
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    return error;
  }
}

async function renderMissingIsaacLabMimicRgbd(statusTarget = null, basePayload = null) {
  const label = "Render missing Mirror RGB-D";
  const payload = isaacDomainMimicFollowupPayload(basePayload || isaacDomainMimicPayload({
    isaac_lab_visualize_generation: true,
    mimic_enable_cameras: true,
  }));
  payload.isaac_lab_visualize_generation = true;
  payload.mimic_enable_cameras = true;
  renderIsaacLabOutputCheckList({ issues: [], checks: [] });
  renderIsaacSyntheticProgress({ status: "lab_rgbd_render_requested", progress: { percent: 5 } });
  renderIsaacDomainMimicLauncherProgress({ status: "lab_rgbd_render_requested", progress: { percent: 5 } });
  setActionStatus(statusTarget, "running", label, { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/isaac-lab/mimic-rgbd/render-missing", payload, 300000);
    renderIsaacDomainMimicLauncherProgress(data);
    renderIsaacSynthetic(data);
    renderResult(label, data);
    lastIsaacDomainMimicJobId = String(data && (data.job_id || (data.job && data.job.job_id)) || lastIsaacDomainMimicJobId || "");
    if (lastIsaacDomainMimicJobId && !isaacSyntheticJobIsTerminal(data)) {
      setActionStatus(statusTarget, "running", label, data);
      return await pollIsaacDomainMimicJob(lastIsaacDomainMimicJobId, payload, statusTarget);
    }
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", label, data);
    if (data && data.ok) {
      return await checkIsaacDomainMimicOutputs(statusTarget, "checking completed Mirror RGB-D output", payload);
    }
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderIsaacSynthetic(error);
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    return error;
  }
}

async function stopIsaacDomainMimicPipeline(statusTarget = null) {
  const label = "Domain randomization + mimic stop";
  const payload = isaacDomainMimicFollowupPayload(
    isaacDomainMimicPayload(lastIsaacDomainMimicJobId ? { job_id: lastIsaacDomainMimicJobId } : {}),
  );
  setActionStatus(statusTarget, "running", label, { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/isaac-lab/mimic/stop", payload, 30000);
    lastIsaacDomainMimicJobId = String(data && (data.job_id || (data.job && data.job.job_id)) || lastIsaacDomainMimicJobId || "");
    renderIsaacDomainMimicLauncherProgress(data);
    renderIsaacSynthetic(data);
    renderResult(label, data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", label, data);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderIsaacSynthetic(error);
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    return error;
  }
}

async function restoreIsaacDomainMimicPipelineStatus() {
  const statusTarget = $("isaac-lab-launcher-action-status");
  try {
    const data = await postJson("/api/lerobot/isaac-lab/mimic/status", isaacDomainMimicPayload(), 30000);
    if (!data || !data.ok || !data.job_id) return null;
    lastIsaacDomainMimicJobId = String(data.job_id || "");
    renderIsaacDomainMimicLauncherProgress(data);
    renderIsaacSynthetic(data);
    setActionStatus(statusTarget, isaacSyntheticJobIsTerminal(data) ? "ok" : "running", "Domain randomization + mimic pipeline", data);
    if (!isaacSyntheticJobIsTerminal(data)) {
      pollIsaacDomainMimicJob(lastIsaacDomainMimicJobId, isaacDomainMimicFollowupPayload(), statusTarget);
    }
    return data;
  } catch (err) {
    return null;
  }
}

function isaacSyntheticLiveE2ePayload(overrides = {}) {
  return isaacSyntheticPayload({
    mode: "live",
    runtime_mode: "live",
    dry_run: false,
    e2e_create_fixture: false,
    e2e_episodes: 3,
    e2e_episode_s: 10,
    e2e_fps: 15,
    mimic_trials: 3,
    mimic_enable_cameras: checkboxValue(isaacLabMimicCamerasInput),
    mimic_camera_width: 320,
    mimic_camera_height: 240,
    enable_mimic: true,
    enable_hdf5_export: true,
    enable_replicator: false,
    isaac_lab_visualize_generation: checkboxValue(isaacLabVisualizeGenerationInput),
    ...overrides,
  });
}

function isaacSyntheticJobIsTerminal(data) {
  const status = String(data && data.status ? data.status : data && data.job && data.job.status ? data.job.status : "").toUpperCase();
  return ["BLOCKED", "COMPLETED", "FAILED", "STOPPED", "CANCELLED"].includes(status);
}

async function pollIsaacLiveE2eJob(jobId, basePayload, statusTarget = null) {
  const payload = { ...basePayload, job_id: jobId };
  let latest = null;
  for (;;) {
    await delay(2000);
    latest = await postJson("/api/lerobot/isaac-lab/live-e2e/status", payload, 30000);
    renderIsaacSynthetic(latest);
    renderResult("Isaac Lab 10s x 3 live check", latest);
    if (isaacSyntheticJobIsTerminal(latest)) {
      setActionStatus(statusTarget, latest && latest.ok ? "ok" : "error", "Isaac Lab 10s x 3 live check", latest);
      return latest;
    }
    setActionStatus(statusTarget, "running", "Isaac Lab 10s x 3 live check", latest);
  }
}

async function runIsaacLiveE2eCheck(statusTarget = null) {
  const payload = isaacSyntheticLiveE2ePayload();
  renderIsaacSyntheticProgress({ status: "request_sent", progress: { percent: 5 } });
  setActionStatus(statusTarget, "running", "Isaac Lab 10s x 3 live check", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/isaac-lab/run-live-e2e-check", payload, 30000);
    renderIsaacSynthetic(data);
    renderResult("Isaac Lab 10s x 3 live check", data);
    lastIsaacLiveE2eJobId = String(data && (data.job_id || (data.job && data.job.job_id)) || lastIsaacLiveE2eJobId || "");
    if (lastIsaacLiveE2eJobId && !isaacSyntheticJobIsTerminal(data)) {
      setActionStatus(statusTarget, "running", "Isaac Lab 10s x 3 live check", data);
      return await pollIsaacLiveE2eJob(lastIsaacLiveE2eJobId, payload, statusTarget);
    }
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "Isaac Lab 10s x 3 live check", data);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderIsaacSynthetic(error);
    renderResult("Isaac Lab 10s x 3 live check", error);
    setActionStatus(statusTarget, "error", "Isaac Lab 10s x 3 live check", error);
    return error;
  }
}

async function runIsaacLiveE2eControl(label, endpoint, statusTarget = null) {
  const payload = isaacSyntheticLiveE2ePayload(lastIsaacLiveE2eJobId ? { job_id: lastIsaacLiveE2eJobId } : {});
  setActionStatus(statusTarget, "running", label, { status: "request sent" });
  try {
    const data = await postJson(endpoint, payload, 30000);
    renderIsaacSynthetic(data);
    renderResult(label, data);
    lastIsaacLiveE2eJobId = String(data && (data.job_id || (data.job && data.job.job_id)) || lastIsaacLiveE2eJobId || "");
    setActionStatus(statusTarget, data && data.ok ? (isaacSyntheticJobIsTerminal(data) ? "ok" : "running") : "error", label, data);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderIsaacSynthetic(error);
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    return error;
  }
}

async function previewIsaacAugmentation(statusTarget = null) {
  const payload = isaacAugmentationPayload();
  setActionStatus(statusTarget, "running", "Isaac augmentation preview", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/augment/preview", payload, 60000);
    renderIsaacAugmentationPreview(data);
    renderResult("Isaac augmentation preview", data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "Isaac augmentation preview", data);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderIsaacAugmentationPreview(error);
    renderResult("Isaac augmentation preview", error);
    setActionStatus(statusTarget, "error", "Isaac augmentation preview", error);
    return error;
  }
}

function clampPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(100, numeric));
}

function createSmoothProgressController(barEl, options = {}) {
  let displayedPercent = 0;
  let targetPercent = 0;
  let timer = null;

  function setBar(percent) {
    const clamped = clampPercent(percent);
    if (barEl) barEl.style.width = `${clamped.toFixed(2)}%`;
    if (typeof options.onRender === "function") options.onRender(clamped, targetPercent);
  }

  function stop() {
    if (!timer) return;
    window.clearTimeout(timer);
    timer = null;
  }

  function step() {
    const delta = targetPercent - displayedPercent;
    if (Math.abs(delta) <= ISAAC_RGBD_RENDER_PROGRESS_MIN_STEP) {
      displayedPercent = targetPercent;
      setBar(displayedPercent);
      stop();
      return;
    }
    displayedPercent += delta * ISAAC_RGBD_RENDER_PROGRESS_EASE;
    setBar(displayedPercent);
    timer = window.setTimeout(step, ISAAC_RGBD_RENDER_PROGRESS_ANIMATION_MS);
  }

  return {
    update(percent) {
      const target = clampPercent(percent);
      targetPercent = target;
      if (target < displayedPercent) {
        stop();
        displayedPercent = target;
        setBar(target);
        return;
      }
      if (!timer) step();
    },
    reset() {
      stop();
      displayedPercent = 0;
      targetPercent = 0;
      setBar(0);
    },
    stop,
    displayedPercent() {
      return displayedPercent;
    },
    targetPercent() {
      return targetPercent;
    },
  };
}

function smoothProgressController(key, barEl, options = {}) {
  if (!smoothProgressControllers[key]) {
    smoothProgressControllers[key] = createSmoothProgressController(barEl, options);
  }
  return smoothProgressControllers[key];
}

function progressPercentFromPayload(progress) {
  const total = Number(progress && (progress.total ?? progress.total_steps ?? 0));
  const done = Number(progress && (progress.done ?? progress.current_step ?? 0));
  if (progress && progress.percent !== undefined) return clampPercent(progress.percent);
  if (progress && progress.progress_percent !== undefined) return clampPercent(progress.progress_percent);
  return total > 0 ? clampPercent((done / total) * 100) : 0;
}

function renderUnifiedProgress(key, progressEl, labelEl, barEl, progress, options = {}) {
  if (!progressEl || !progress) return;
  progressEl.classList.remove("hidden");
  const total = Number(progress.total ?? progress.total_steps ?? 0);
  const done = Number(progress.done ?? progress.current_step ?? 0);
  const percent = progressPercentFromPayload(progress);
  const stage = String(progress.stage || progress.status || options.stage || "running");
  const message = String(progress.message || options.message || "");
  const prefix = options.label || "";
  if (labelEl) {
    const countText = total > 0 ? `${done} / ${total}` : `${done} / ?`;
    labelEl.textContent = `${prefix ? `${prefix} · ` : ""}${countText} · ${percent.toFixed(1)}% · ${stage}${message ? ` · ${message}` : ""}`;
  }
  if (barEl) barEl.classList.toggle("is-indeterminate", Boolean(progress.indeterminate));
  smoothProgressController(key, barEl).update(percent);
}

function setIsaacRgbdRenderProgressBar(percent) {
  if (!smoothProgressControllers.isaac_rgbd_render && isaacRgbdRenderProgressBarEl) {
    isaacRgbdRenderProgressBarEl.style.width = `${clampPercent(percent).toFixed(2)}%`;
  }
  const controller = smoothProgressController("isaac_rgbd_render", isaacRgbdRenderProgressBarEl, {
    onRender(displayed, target) {
      isaacRgbdRenderDisplayedPercent = displayed;
      isaacRgbdRenderTargetPercent = target;
    },
  });
  controller.update(percent);
}

function stopIsaacRgbdRenderProgressAnimation() {
  const controller = smoothProgressControllers.isaac_rgbd_render;
  if (controller) controller.stop();
  isaacRgbdRenderProgressTimer = null;
}

function stepIsaacRgbdRenderProgressBar() {
  setIsaacRgbdRenderProgressBar(isaacRgbdRenderTargetPercent);
}

function updateIsaacRgbdRenderProgressBar(clampedPercent) {
  const target = clampPercent(clampedPercent);
  isaacRgbdRenderTargetPercent = target;
  if (target < isaacRgbdRenderDisplayedPercent) {
    stopIsaacRgbdRenderProgressAnimation();
    isaacRgbdRenderDisplayedPercent = target;
    setIsaacRgbdRenderProgressBar(target);
    return;
  }
  if (!isaacRgbdRenderProgressTimer) {
    stepIsaacRgbdRenderProgressBar();
  }
}

function resetIsaacRgbdRenderProgressBar() {
  stopIsaacRgbdRenderProgressAnimation();
  isaacRgbdRenderDisplayedPercent = 0;
  isaacRgbdRenderTargetPercent = 0;
  const controller = smoothProgressController("isaac_rgbd_render", isaacRgbdRenderProgressBarEl, {
    onRender(displayed, target) {
      isaacRgbdRenderDisplayedPercent = displayed;
      isaacRgbdRenderTargetPercent = target;
    },
  });
  controller.reset();
}

function rgbdEpisodeLabel(episodeIndex) {
  const parsed = Number(episodeIndex);
  return Number.isFinite(parsed) ? `episode ${parsed}` : `episode ${episodeIndex}`;
}

function renderIsaacRgbdRenderFailureList() {
  if (!isaacRgbdRenderFailureListEl) return;
  const job = lastIsaacRgbdRenderJob || {};
  const health = lastIsaacRgbdHealth || {};
  const sidecars = health.sidecars || {};
  const trainingExclusions = sidecars.training_exclusions || {};
  const isaacRgbd = sidecars.isaac_rgbd || {};
  const contactAudit = isaacRgbd.contact_audit || {};
  const coverage = isaacRgbd.coverage || {};
  const failedFrames = Array.isArray(job.failed_frames) ? job.failed_frames : [];
  const excludedEpisodes = Array.isArray(trainingExclusions.episode_indices)
    ? trainingExclusions.episode_indices
    : [];
  const severeEpisodes = Array.isArray(contactAudit.severe_episodes)
    ? contactAudit.severe_episodes
    : [];
  const missingEpisodes = Array.isArray(coverage.missing_episode_indices)
    ? coverage.missing_episode_indices
    : [];
  const lines = [];
  if (failedFrames.length) {
    lines.push(...failedFrames.slice(0, 12).map((frame) => {
      const episode = rgbdEpisodeLabel(frame.episode_index);
      const frameIndex = frame.frame_index ?? "-";
      const message = frame.message || frame.status || "render failed";
      return `Render failed · ${episode} · frame ${frameIndex} · ${message}`;
    }));
    if (failedFrames.length > 12) lines.push(`Render failed · +${failedFrames.length - 12} more frame(s)`);
  } else if (Number(job.failed || 0) > 0 && job.last_error) {
    lines.push(`Render failed · ${job.failed} frame(s) · ${job.last_error}`);
  }
  if (excludedEpisodes.length) {
    lines.push(`Excluded from sim/synthetic data · ${excludedEpisodes.map(rgbdEpisodeLabel).join(", ")}`);
  }
  if (missingEpisodes.length || Number(coverage.missing_episode_count || 0) > 0) {
    const listed = missingEpisodes.slice(0, 16).map(rgbdEpisodeLabel).join(", ");
    const hidden = Math.max(0, Number(coverage.missing_episode_count || 0) - missingEpisodes.slice(0, 16).length);
    lines.push(`Incomplete RGB-D coverage · missing ${coverage.missing_episode_count || missingEpisodes.length} episode(s)${listed ? ` · ${listed}` : ""}${hidden ? `, +${hidden} more` : ""}`);
  }
  for (const episode of severeEpisodes.slice(0, 8)) {
    const episodeIndex = episode.episode_index;
    const badFrames = episode.bad_frame_count ?? 0;
    const liftedFrames = episode.lifted_frame_count ?? 0;
    lines.push(`Contact warning · ${rgbdEpisodeLabel(episodeIndex)} · bad=${badFrames} · lifted=${liftedFrames}`);
  }
  if (!lines.length) {
    isaacRgbdRenderFailureListEl.innerHTML = `<div class="lerobot-render-failure-empty">No failed/excluded RGB-D episodes detected.</div>`;
    return;
  }
  isaacRgbdRenderFailureListEl.innerHTML = `
    <div class="lerobot-render-failure-title">RGB-D Failed / Excluded Data</div>
    <ul>${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>
  `;
}

function renderIsaacRgbdRenderProgress(data) {
  const job = data && data.post_render
    ? data.post_render
    : data && data.isaac_rgbd_post_render
      ? data.isaac_rgbd_post_render
      : data || {};
  if (!isaacRgbdRenderProgressEl || !job || !Object.keys(job).length) return;
  lastIsaacRgbdRenderJob = job;
  isaacRgbdRenderProgressEl.classList.remove("hidden");
  const done = Number(job.done || 0);
  const total = Number(job.total || 0);
  const percent = Number(job.percent ?? (total > 0 ? (done / total) * 100 : 100));
  const clampedPercent = clampPercent(percent);
  const failed = Number(job.failed || 0);
  const skipped = Number(job.skipped || 0);
  const rendered = Number(job.rendered || 0);
  const status = String(job.status || "IDLE");
  if (isaacRgbdRenderProgressLabelEl) {
    isaacRgbdRenderProgressLabelEl.textContent = `${done} / ${total} · ${clampedPercent.toFixed(1)}% · rendered=${rendered} · skipped=${skipped} · failed=${failed} · ${status}`;
  }
  updateIsaacRgbdRenderProgressBar(clampedPercent);
  renderIsaacRgbdRenderFailureList();
}

function isaacRgbdRenderIsActive(data) {
  const job = data && data.post_render
    ? data.post_render
    : data && data.isaac_rgbd_post_render
      ? data.isaac_rgbd_post_render
      : data || {};
  return ["RUNNING", "STOPPING"].includes(String(job.status || "").toUpperCase());
}

function handleIsaacRgbdRenderResponse(data) {
  const job = data && data.post_render
    ? data.post_render
    : data && data.isaac_rgbd_post_render
      ? data.isaac_rgbd_post_render
      : null;
  if (!job) return;
  renderIsaacRgbdRenderProgress(job);
  const responseSessionId = Object.prototype.hasOwnProperty.call(job, "session_id")
    ? job.session_id
    : data && Object.prototype.hasOwnProperty.call(data, "session_id")
      ? data.session_id
      : "";
  lastIsaacRgbdRenderSessionId = String(responseSessionId ?? "");
  const target = $("lerobot-isaac-rgbd-render-action-status");
  setActionStatus(target, isaacRgbdRenderIsActive(job) ? "running" : (Number(job.failed || 0) > 0 ? "error" : "ok"), "Isaac RGB-D render", job);
  if (isaacRgbdRenderIsActive(job)) {
    startIsaacRgbdRenderStatusPolling(lastIsaacRgbdRenderSessionId);
  } else {
    stopIsaacRgbdRenderStatusPolling();
  }
}

function syncIsaacRgbdRenderEpisodeOverride() {
  if (!isaacRgbdRenderEpisodesInput) return;
  isaacRgbdRenderEpisodesInput.disabled = boolValue(isaacRgbdRenderOverrideAllInput);
}

function handleIsaacRgbdRenderOverrideAllChange() {
  syncIsaacRgbdRenderEpisodeOverride();
  if (boolValue(isaacRgbdRenderOverrideAllInput) && isaacRgbdRenderOverwriteInput) isaacRgbdRenderOverwriteInput.checked = true;
}

function syncIsaacDomainMimicEpisodeOverride() {
  if (!isaacLabDomainMimicEpisodesInput) return;
  isaacLabDomainMimicEpisodesInput.disabled = boolValue(isaacLabDomainMimicOverwriteAllInput);
}

function handleIsaacDomainMimicOverwriteAllChange() {
  syncIsaacDomainMimicEpisodeOverride();
  if (boolValue(isaacLabDomainMimicOverwriteAllInput) && isaacLabDomainMimicOverwriteInput) {
    isaacLabDomainMimicOverwriteInput.checked = true;
  }
}

function isaacRgbdContactWarningCount(data) {
  const health = data && data.dataset_health ? data.dataset_health : {};
  const sidecars = health.sidecars || {};
  const isaacRgbd = sidecars.isaac_rgbd || {};
  const audit = isaacRgbd.contact_audit || {};
  const coverage = isaacRgbd.coverage || {};
  return Number(audit.severe_episode_count || 0) + Number(coverage.missing_episode_count || 0);
}

async function validateIsaacRgbdRenderContactAfterCompletion(statusTarget = null) {
  if (!isaacRgbdRenderValidateAfterCompletion) return null;
  isaacRgbdRenderValidateAfterCompletion = false;
  return runIsaacRgbdRenderContactCheck(statusTarget, "checking completed render output");
}

async function checkIsaacRgbdRenderContact(statusTarget = null) {
  isaacRgbdRenderValidateAfterCompletion = false;
  return runIsaacRgbdRenderContactCheck(statusTarget, "checking rendered output");
}

async function runIsaacRgbdRenderContactCheck(statusTarget = null, status = "checking rendered output") {
  setActionStatus(statusTarget, "running", "Isaac RGB-D contact check", { status });
  try {
    const data = await postJson("/api/lerobot/dataset/inspect", basePayload(), 60000);
    renderDatasetHealth(data);
    renderResult("Isaac RGB-D contact check", data);
    const severeCount = isaacRgbdContactWarningCount(data);
    setActionStatus(
      statusTarget,
      severeCount > 0 ? "error" : "ok",
      "Isaac RGB-D contact check",
      severeCount > 0
        ? { status: "RGB-D warnings remain", rgbd_warning_count: severeCount }
        : { status: "RGB-D check passed", rgbd_warning_count: 0 },
    );
    return data;
  } catch (err) {
    const error = { ok: false, status: "contact_check_failed", error: String(err) };
    renderResult("Isaac RGB-D contact check", error);
    setActionStatus(statusTarget, "error", "Isaac RGB-D contact check", error);
    return error;
  }
}

async function runIsaacRgbdRender(statusTarget = null, options = {}) {
  lastIsaacRgbdRenderSessionId = "";
  syncIsaacRgbdRenderEpisodeOverride();
  if (options.validateAfterCompletion) isaacRgbdRenderValidateAfterCompletion = true;
  const renderSessionId = boolValue(isaacRgbdRenderSessionOverrideInput) ? (lastSessionByWorkflow.record || "") : "";
  const payload = basePayload({ session_id: renderSessionId, isaac_rgbd_post_render_inline: false });
  payload.isaac_rgbd_post_render_execution_mode = "headless_preplay_replay";
  payload.isaac_rgbd_post_render_overwrite = options.forceAll ? true : boolValue(isaacRgbdRenderOverwriteInput);
  const renderEpisodeIndices = options.forceAll || boolValue(isaacRgbdRenderOverrideAllInput) ? "" : (isaacRgbdRenderEpisodesInput ? isaacRgbdRenderEpisodesInput.value.trim() : "");
  payload.isaac_rgbd_post_render_episode_indices = renderEpisodeIndices;
  resetIsaacRgbdRenderProgressBar();
  setActionStatus(statusTarget, "running", "Isaac RGB-D render", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/isaac-rgbd/render/start", payload, 30000);
    renderIsaacRgbdRenderProgress(data);
    renderResult("Isaac RGB-D render", data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "Isaac RGB-D render", data);
    handleIsaacRgbdRenderResponse(data);
    if (!isaacRgbdRenderIsActive(data)) await validateIsaacRgbdRenderContactAfterCompletion(statusTarget);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    isaacRgbdRenderValidateAfterCompletion = false;
    renderResult("Isaac RGB-D render", error);
    setActionStatus(statusTarget, "error", "Isaac RGB-D render", error);
    return error;
  }
}

function isaacRgbdRenderStopPayload() {
  const sessionId = lastIsaacRgbdRenderSessionId || "";
  const renderDatasetPath = String((lastIsaacRgbdRenderJob && lastIsaacRgbdRenderJob.dataset_path) || "").trim();
  return basePayload({ session_id: sessionId, dataset_path: renderDatasetPath, dataset_repo_id: "" });
}

async function stopIsaacRgbdRender(statusTarget = null) {
  isaacRgbdRenderValidateAfterCompletion = false;
  const payload = isaacRgbdRenderStopPayload();
  setActionStatus(statusTarget, "running", "Isaac RGB-D render stop", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/isaac-rgbd/render/stop", payload, 30000);
    renderIsaacRgbdRenderProgress(data);
    renderResult("Isaac RGB-D render stop", data);
    setActionStatus(statusTarget, data && data.ok ? (isaacRgbdRenderIsActive(data) ? "running" : "ok") : "error", "Isaac RGB-D render stop", data);
    handleIsaacRgbdRenderResponse(data);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderResult("Isaac RGB-D render stop", error);
    setActionStatus(statusTarget, "error", "Isaac RGB-D render stop", error);
    return error;
  }
}

function startIsaacRgbdRenderStatusPolling(sessionId = "") {
  stopIsaacRgbdRenderStatusPolling();
  const target = $("lerobot-isaac-rgbd-render-action-status");
  const pollingSessionId = String(sessionId ?? "");
  isaacRgbdRenderStatusTimer = window.setInterval(async () => {
    try {
      const payload = basePayload({ session_id: pollingSessionId });
      const data = await postJson("/api/lerobot/isaac-rgbd/render/status", payload);
      renderIsaacRgbdRenderProgress(data);
      setActionStatus(target, data && data.ok ? (isaacRgbdRenderIsActive(data) ? "running" : "ok") : "error", "Isaac RGB-D render", data);
      if (!isaacRgbdRenderIsActive(data)) {
        stopIsaacRgbdRenderStatusPolling();
        await validateIsaacRgbdRenderContactAfterCompletion(target);
        await refreshConfig();
      }
    } catch (err) {
      setActionStatus(target, "error", "Isaac RGB-D render", { error: String(err) });
      stopIsaacRgbdRenderStatusPolling();
    }
  }, 2000);
}

function stopIsaacRgbdRenderStatusPolling() {
  if (isaacRgbdRenderStatusTimer) {
    window.clearInterval(isaacRgbdRenderStatusTimer);
    isaacRgbdRenderStatusTimer = null;
  }
}

async function visualizeDataset(statusTarget = null) {
  const payload = visualizationPayload();
  renderVisualizationProgress({ status: "request_sent" });
  setActionStatus(statusTarget, "running", "LeRobot visualize start", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/visualize/start", payload, 60000);
    renderVisualizationSession(data);
    renderResult("LeRobot visualize start", data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "LeRobot visualize start", data);
    if (data && data.ok && data.visualization && data.visualization.viewer_url) {
      window.open(data.visualization.viewer_url, "_blank", "noopener");
    }
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderVisualizationSession(error);
    renderResult("LeRobot visualize start", error);
    setActionStatus(statusTarget, "error", "LeRobot visualize start", error);
    return error;
  }
}

async function previewDataset(statusTarget = null) {
  const payload = visualizationPayload();
  setActionStatus(statusTarget, "running", "preview local media", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/visualize/dataset", payload);
    renderVisualization(data);
    renderResult("preview local media", data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "preview local media", data);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderVisualization(error);
    renderResult("preview local media", error);
    setActionStatus(statusTarget, "error", "preview local media", error);
    return error;
  }
}

function datasetManageCommonPayload(overrides = {}) {
  syncDatasetManageRootFromLocalPaths();
  return {
    mode: modeSelect ? modeSelect.value : "test",
    runtime_mode: modeSelect ? modeSelect.value : "test",
    profile_id: profileSelect ? profileSelect.value : "",
    dataset_root: datasetManageRootInput && datasetManageRootInput.value.trim()
      ? datasetManageRootInput.value.trim()
      : (datasetRootInput ? datasetRootInput.value.trim() : ""),
    namespace: datasetManageNamespaceInput ? datasetManageNamespaceInput.value.trim() || "jin" : "jin",
    date_prefix: datasetManageDatePrefixInput ? datasetManageDatePrefixInput.value.trim() : "",
    overwrite: boolValue(datasetManageOverwriteInput),
    ...overrides,
  };
}

function datasetManageSelectedRepo(selectEl) {
  return selectEl ? String(selectEl.value || "").trim() : "";
}

function datasetManageSource(selectEl, rangeEl = null) {
  return {
    dataset_repo_id: datasetManageSelectedRepo(selectEl),
    episode_range: rangeEl && rangeEl.value.trim() ? rangeEl.value.trim() : "all",
  };
}

function datasetManageMergePayload() {
  return datasetManageCommonPayload({
    sources: [
      datasetManageSource(datasetManageMergeSourceAInput, datasetManageMergeRangeAInput),
      datasetManageSource(datasetManageMergeSourceBInput, datasetManageMergeRangeBInput),
    ],
    output_repo_id: datasetManageOutputRepoInput ? datasetManageOutputRepoInput.value.trim() : "",
  });
}

function datasetManageSplitPayload() {
  const raw = datasetManageSplitSpecInput ? String(datasetManageSplitSpecInput.value || "") : "";
  const splits = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const match = line.match(/^([^=]+)=(.+)$/);
      if (!match) return { name: `split_${index}`, episode_range: line };
      return { name: match[1].trim(), episode_range: match[2].trim() };
    });
  return datasetManageCommonPayload({
    source: datasetManageSource(datasetManageSplitSourceInput),
    splits,
  });
}

function datasetManageDeletePayload() {
  return datasetManageCommonPayload({
    source: datasetManageSource(datasetManageDeleteSourceInput),
    delete_episode_range: datasetManageDeleteRangeInput ? datasetManageDeleteRangeInput.value.trim() : "",
    output_repo_id: datasetManageDeleteOutputRepoInput ? datasetManageDeleteOutputRepoInput.value.trim() : "",
  });
}

function datasetManagePopulateSelect(selectEl, datasets, preferred = "") {
  if (!selectEl) return;
  const current = preferred || selectEl.value;
  selectEl.innerHTML = "";
  datasets.forEach((dataset) => {
    const option = document.createElement("option");
    option.value = dataset.repo_id || "";
    option.textContent = `${dataset.repo_id || ""} (${dataset.total_episodes || 0} ep / ${dataset.total_frames || 0} frames)`;
    selectEl.appendChild(option);
  });
  if (current && Array.from(selectEl.options).some((option) => option.value === current)) {
    selectEl.value = current;
  }
}

function datasetManageRenderList(data) {
  const datasets = Array.isArray(data && data.datasets) ? data.datasets : [];
  const suggested = data && data.suggested_repo_id ? String(data.suggested_repo_id) : "";
  const previousMergeA = datasetManageMergeSourceAInput ? datasetManageMergeSourceAInput.value : "";
  const previousMergeB = datasetManageMergeSourceBInput ? datasetManageMergeSourceBInput.value : "";
  if (datasetManageOutputRepoInput && suggested && !datasetManageOutputRepoInput.value.trim()) {
    datasetManageOutputRepoInput.value = suggested;
  }
  datasetManagePopulateSelect(datasetManageMergeSourceAInput, datasets, previousMergeA);
  datasetManagePopulateSelect(datasetManageMergeSourceBInput, datasets, previousMergeB || (datasets.length >= 2 ? datasets[datasets.length - 1].repo_id : ""));
  datasetManagePopulateSelect(datasetManageSplitSourceInput, datasets, datasetManageSplitSourceInput ? datasetManageSplitSourceInput.value : "");
  datasetManagePopulateSelect(datasetManageDeleteSourceInput, datasets, datasetManageDeleteSourceInput ? datasetManageDeleteSourceInput.value : "");
  if (datasetManageMergeSourceAInput && datasets.length >= 1 && !datasetManageMergeSourceAInput.value) datasetManageMergeSourceAInput.value = datasets[0].repo_id || "";
  if (datasetManageMergeSourceBInput && datasets.length >= 2 && (!datasetManageMergeSourceBInput.value || datasetManageMergeSourceBInput.value === datasetManageMergeSourceAInput.value)) {
    datasetManageMergeSourceBInput.value = datasets[datasets.length - 1].repo_id || "";
  }
  if (!datasetManageListEl) return;
  if (!datasets.length) {
    datasetManageListEl.innerHTML = `<div class="lerobot-report-empty">No local datasets found.</div>`;
    return;
  }
  const rows = datasets.map((dataset) => `
    <tr>
      <td><code>${escapeHtml(dataset.repo_id || "")}</code></td>
      <td>${escapeHtml(dataset.total_episodes ?? 0)}</td>
      <td>${escapeHtml(dataset.total_frames ?? 0)}</td>
      <td>${escapeHtml(dataset.codebase_version || "")}</td>
      <td>${escapeHtml((dataset.sidecars || []).join(", "))}</td>
    </tr>
  `).join("");
  datasetManageListEl.innerHTML = `
    <div class="lerobot-card-note">next=${escapeHtml(suggested || "-")} · root=${escapeHtml((data && data.dataset_root) || "")}</div>
    <div class="table-scroll"><table>
      <thead><tr><th>repo</th><th>episodes</th><th>frames</th><th>version</th><th>sidecars</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  `;
}

async function refreshDatasetManageList(statusTarget = null) {
  setActionStatus(statusTarget || datasetManageStatusEl, "running", "dataset list", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/dataset-manage/list", datasetManageCommonPayload(), 60000);
    datasetManageRenderList(data);
    renderResult("dataset manage list", data);
    setActionStatus(statusTarget || datasetManageStatusEl, data && data.ok ? "ok" : "error", "dataset list", data);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    datasetManageRenderList(error);
    renderResult("dataset manage list", error);
    setActionStatus(statusTarget || datasetManageStatusEl, "error", "dataset list", error);
    return error;
  }
}

async function runDatasetManageAction(label, url, payload, statusTarget = null) {
  setActionStatus(statusTarget || datasetManageStatusEl, "running", label, { status: "request sent" });
  try {
    const data = await postJson(url, payload, 300000);
    renderResult(label, data);
    setActionStatus(statusTarget || datasetManageStatusEl, data && data.ok ? "ok" : "error", label, data);
    await refreshDatasetManageList(datasetManageStatusEl);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderResult(label, error);
    setActionStatus(statusTarget || datasetManageStatusEl, "error", label, error);
    return error;
  }
}

function bind(id, handler) {
  const el = $(id);
  if (el) el.addEventListener("click", handler);
}

lerobotTabButtons.forEach((button) => {
  button.addEventListener("click", () => activateLeRobotGuiTab(button.dataset.lerobotTabTarget || "lerobot-main-tab"));
});

if (isaacLabDomainMimicRgbdInput) {
  isaacLabDomainMimicRgbdInput.addEventListener("change", () => {
    syncIsaacLabMimicRgbdInputs(checkboxValue(isaacLabDomainMimicRgbdInput));
  });
}
if (isaacLabMimicCamerasInput) {
  isaacLabMimicCamerasInput.addEventListener("change", () => {
    syncIsaacLabMimicRgbdInputs(checkboxValue(isaacLabMimicCamerasInput));
  });
}

bind("btn-lerobot-refresh", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  setActionStatus(statusTarget, "running", "refresh config", { status: "request sent" });
  const data = await refreshConfig();
  setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "refresh config", data);
});
bind("btn-lerobot-save-profile", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  setActionStatus(statusTarget, "running", "config saved", { status: "request sent" });
  const data = await postJson("/api/lerobot/config", {
    profile_id: profileSelect ? profileSelect.value : "",
    observation_pipeline_id: observationPipelineSelect ? observationPipelineSelect.value : "raw_depth_adapter",
    mode: modeSelect ? modeSelect.value : "test",
  });
  renderResult("config saved", data);
  setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "config saved", data);
  await refreshConfig();
});
bind("btn-lerobot-validate", (event) => runAction("profile validate", "/api/lerobot/profiles/validate", null, actionStatusFromEvent(event)));
bind("btn-lerobot-find-ports", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  setActionStatus(statusTarget, "running", "find ports", { status: "request sent" });
  const params = new URLSearchParams({ profile_id: profileSelect ? profileSelect.value : "", mode: modeSelect ? modeSelect.value : "test" });
  const res = await fetch(`/api/lerobot/ports?${params.toString()}`);
  const data = await res.json();
  renderResult("find ports", data);
  setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "find ports", data);
  renderPortCandidates(data);
  await refreshConfig();
});

for (const role of ["follower", "leader"]) {
  bind(`btn-port-baseline-${role}`, (event) => runDevicePortAction(`${role} baseline`, "/api/lerobot/ports/baseline", role, { port: "" }, actionStatusFromEvent(event)));
  bind(`btn-port-detect-${role}`, (event) => runDevicePortAction(`${role} ID detect/save`, "/api/lerobot/ports/detect", role, { port: "" }, actionStatusFromEvent(event)));
}

bind("btn-add-camera", () => {
  const key = normalizeCameraKey(newCameraKeyInput ? newCameraKeyInput.value : "");
  if (!key) {
    setActionStatus($("lerobot-camera-manager-status"), "error", "add camera", { error: "Camera key is required." });
    return;
  }
  if (!extraCameraKeys.includes(key)) extraCameraKeys.push(key);
  if (manualCameraKeyInput) manualCameraKeyInput.value = key;
  if (newCameraKeyInput) newCameraKeyInput.value = "";
  setActionStatus($("lerobot-camera-manager-status"), "ok", "add camera", { status: `${key} camera added locally` });
  renderDeviceMemory(lastConfigData || { profiles: [], device_memory: {} });
});

bind("btn-port-save-manual", (event) => {
  const role = manualRoleSelect ? manualRoleSelect.value || "follower" : "follower";
  return runDevicePortAction(`${role} manual save`, "/api/lerobot/ports/save", role, {}, actionStatusFromEvent(event));
});

bind("btn-isaac-mirror-map", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("load Isaac joint mapping", "/api/lerobot/mirror/joint-mapping", basePayload(), statusTarget);
  renderIsaacMirror(data);
});

bind("btn-isaac-mirror-receiver-start", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("open Isaac Sim mirror", "/api/lerobot/mirror/receiver-process/start", basePayload(), statusTarget);
  renderIsaacMirror(data);
});

bind("btn-isaac-mirror-receiver-status", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("mirror link status", "/api/lerobot/mirror/receiver-process/status", basePayload(), statusTarget);
  renderIsaacMirror(data);
});

bind("btn-isaac-mirror-receiver-stop", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("close Isaac Sim link", "/api/lerobot/mirror/receiver-process/stop", basePayload(), statusTarget);
  renderIsaacMirror(data);
});

bind("btn-isaac-mirror-health", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("check Isaac link", "/api/lerobot/mirror/receiver-health", basePayload(), statusTarget);
  renderIsaacMirror(data);
});

bind("btn-isaac-mirror-verify", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("send Isaac test pose", "/api/lerobot/mirror/receiver-verify", basePayload(), statusTarget);
  renderIsaacMirror(data);
});

bind("btn-isaac-mirror-probe", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("read follower state", "/api/lerobot/mirror/state-probe", basePayload(), statusTarget);
  renderIsaacMirror(data);
});

bind("btn-isaac-mirror-loop-start", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("standalone mirror start", "/api/lerobot/mirror/loop/start", basePayload({ isaac_mirror_enabled: true }), statusTarget);
  renderIsaacMirror(data);
});

bind("btn-isaac-mirror-loop-status", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("standalone mirror status", "/api/lerobot/mirror/loop/status", sessionPayload("isaac_mirror"), statusTarget);
  renderIsaacMirror(data);
});

bind("btn-isaac-mirror-loop-stop", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("standalone mirror stop", "/api/lerobot/mirror/loop/stop", sessionPayload("isaac_mirror"), statusTarget);
  renderIsaacMirror(data);
});

bind("btn-browse-dataset-root", () => browsePath("dataset", datasetRootInput ? datasetRootInput.value : "", datasetRootInput));
bind("btn-browse-dataset-manage-root", () => browsePath("dataset", datasetManageRootInput ? datasetManageRootInput.value : "", datasetManageRootInput));
bind("btn-browse-dataset-repo", () => browsePath("dataset", datasetBrowseStartPath(), datasetInput, { include_files: false, valueTransform: datasetRepoValueFromPath }));
bind("btn-browse-output-dir", () => browsePath("output", outputDirInput ? outputDirInput.value : "", outputDirInput));
bind("btn-browse-policy", () => browsePath("policy", policyInput ? policyInput.value : "", policyInput, { select: "file", include_files: true }));
bind("btn-browse-rollout-policy", () => {
  const startPath = (rolloutPolicyInput && rolloutPolicyInput.value.trim()) || "";
  return browsePath("policy", startPath, rolloutPolicyInput || policyInput, { select: "file", include_files: true });
});
bind("btn-browse-manipulation-policy", () => {
  const startPath = (manipulationPolicyInput && manipulationPolicyInput.value.trim()) || "";
  return browsePath("policy", startPath, manipulationPolicyInput || rolloutPolicyInput || policyInput, {
    select: "file",
    include_files: true,
    onSelect: persistSelectedManipulationPolicy,
  });
});
bind("btn-rollout-latest-policy", (event) => useLatestLocalPolicy(actionStatusFromEvent(event)));
bind("btn-manipulation-latest-policy", (event) => useLatestManipulationPolicy(actionStatusFromEvent(event)));
bind("btn-browse-visualization", () => browsePath("dataset", visualizationPathInput ? visualizationPathInput.value : "", visualizationPathInput));
bind("btn-browse-visualization-output", () => browsePath("output", visualizationOutputDirInput ? visualizationOutputDirInput.value : "", visualizationOutputDirInput));
bind("btn-browse-isaac-augment-output", () => browsePath("output", isaacAugmentOutputDirInput ? isaacAugmentOutputDirInput.value : "", isaacAugmentOutputDirInput));

bind("btn-teleop-start", startTeleopForHandoff);
bind("btn-teleop-stop", stopTeleopForHandoff);
bind("btn-teleop-status", (event) => runAction("teleoperate status", "/api/lerobot/teleoperate/status", sessionPayload("teleoperate"), actionStatusFromEvent(event)));
bind("btn-teleop-handoff-complete", completeTeleopHandoff);

if (ttsEngineInput) ttsEngineInput.addEventListener("change", () => { ttsEngineInput.dataset.userEdited = "1"; });
if (confirmLiveInput) confirmLiveInput.addEventListener("change", () => { confirmLiveInput.dataset.userEdited = "1"; });
if (ttsRateInput) {
  ttsRateInput.addEventListener("input", () => setTtsRate(ttsRateInput.value, { persist: true, userEdited: true }));
  ttsRateInput.addEventListener("change", () => setTtsRate(ttsRateInput.value, { persist: true, userEdited: true }));
}
if (ttsRateDefaultButton) {
  ttsRateDefaultButton.addEventListener("click", (event) => {
    event.preventDefault();
    setTtsRate(lerobotTtsServerDefaultRate, { persist: true, userEdited: true });
  });
}
if (ttsHelpButton) {
  ttsHelpButton.addEventListener("click", (event) => {
    event.preventDefault();
    setTtsHelpVisible(ttsHelpButton.getAttribute("aria-expanded") !== "true");
  });
}
document.addEventListener("click", (event) => {
  if (!ttsHelpButton || !ttsHelpPopover || ttsHelpPopover.hidden) return;
  if (ttsHelpButton.contains(event.target) || ttsHelpPopover.contains(event.target)) return;
  setTtsHelpVisible(false);
});

bind("btn-record-start", (event) => runAction("record start", "/api/lerobot/record/start", recordPayload(), actionStatusFromEvent(event)));
async function runRecordControl(label, action, event) {
  return runAction(label, "/api/lerobot/record/control", sessionPayload("record", { action }), actionStatusFromEvent(event));
}

bind("btn-record-stop", (event) => runRecordControl("record force stop", "stop", event));
bind("btn-record-retry", (event) => runRecordControl("record retry", "retry", event));
bind("btn-record-next", (event) => runRecordControl("record next", "next", event));
bind("btn-record-finish", (event) => runRecordControl("record finish", "finish", event));
if (isaacRgbdRenderOverrideAllInput) {
  isaacRgbdRenderOverrideAllInput.addEventListener("change", handleIsaacRgbdRenderOverrideAllChange);
  syncIsaacRgbdRenderEpisodeOverride();
}
if (isaacLabDomainMimicOverwriteAllInput) {
  isaacLabDomainMimicOverwriteAllInput.addEventListener("change", handleIsaacDomainMimicOverwriteAllChange);
  syncIsaacDomainMimicEpisodeOverride();
}
for (const input of [datasetExcludeFlaggedEpisodesInput, isaacAugmentExcludeFlaggedEpisodesInput]) {
  if (input) input.addEventListener("change", () => syncExcludeFlaggedEpisodesCheckboxes(input));
}
syncExcludeFlaggedEpisodesCheckboxes();
bind("btn-isaac-rgbd-render-start", (event) => runIsaacRgbdRender(actionStatusFromEvent(event), { validateAfterCompletion: true }));
bind("btn-isaac-rgbd-render-check", (event) => checkIsaacRgbdRenderContact(actionStatusFromEvent(event)));
bind("btn-isaac-rgbd-render-stop", (event) => stopIsaacRgbdRender(actionStatusFromEvent(event)));

bind("btn-train-start", () => runTrainAction("train start", "/api/lerobot/train/start", trainPayload()));
bind("btn-train-cancel", () => runTrainAction("train cancel", "/api/lerobot/train/cancel", sessionPayload("train")));
bind("btn-train-status", () => runTrainAction("train status", "/api/lerobot/train/status", sessionPayload("train")));
bind("btn-wandb-local-start", (event) => {
  prepareLocalWandbForTraining();
  return runAction("wandb local start", "/api/lerobot/wandb-local/start", wandbLocalPayload(), actionStatusFromEvent(event), 120000);
});
bind("btn-wandb-local-stop", (event) => runAction("wandb local stop", "/api/lerobot/wandb-local/stop", wandbLocalPayload(), actionStatusFromEvent(event), 120000));
bind("btn-wandb-local-status", (event) => runAction("wandb local status", "/api/lerobot/wandb-local/status", wandbLocalPayload(), actionStatusFromEvent(event)));
bind("btn-wandb-local-api-key-save", (event) => saveWandbLocalApiKey(actionStatusFromEvent(event)));
bind("btn-wandb-local-open", (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const url = trainWandbBaseUrlInput && trainWandbBaseUrlInput.value.trim() ? trainWandbBaseUrlInput.value.trim() : "http://127.0.0.1:8081";
  window.open(url, "_blank", "noopener");
  setActionStatus(statusTarget, "ok", "wandb local open", { ok: true, status: "browser_open_requested", url });
});
bind("btn-policy-refresh", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  setActionStatus(statusTarget, "running", "refresh policies", { status: "request sent" });
  const data = await refreshPolicies();
  setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "refresh policies", data);
});

bind("btn-rollout-start", () => runRolloutAction("rollout start", "/api/lerobot/rollout/start", rolloutPayload()));
bind("btn-rollout-stop", () => runRolloutAction("rollout stop", "/api/lerobot/rollout/stop", sessionPayload("rollout")));
bind("btn-rollout-status", () => runRolloutAction("rollout status", "/api/lerobot/rollout/status", sessionPayload("rollout")));
bind("btn-rollout-save", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  setActionStatus(statusTarget, "running", "rollout defaults save", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/rollout/config", currentRolloutProfile());
    renderResult("rollout defaults save", data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "rollout defaults save", data);
    applyRolloutProfile(data.profile || {}, true);
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderResult("rollout defaults save", error);
    setActionStatus(statusTarget, "error", "rollout defaults save", error);
    return error;
  }
});
bind("btn-manipulation-save", async (event) => {
  return persistManipulationTaskProfile({
    statusTarget: actionStatusFromEvent(event),
    render: true,
    refresh: true,
  });
});
bind("btn-manipulation-test", (event) => runAction("manipulation agent test", "/api/lerobot/manipulation-agent/test", manipulationAgentPayload(), actionStatusFromEvent(event), 300000));
bind("btn-manipulation-preview", (event) => {
  const payload = manipulationAgentPayload();
  renderResult("manipulation agent payload preview", payload);
  setActionStatus(actionStatusFromEvent(event), "ok", "manipulation preview", { status: "payload generated", payload });
});
bind("btn-manipulation-run", (event) => runAction("manipulation agent run", "/api/lerobot/manipulation-agent/run", manipulationAgentPayload(), actionStatusFromEvent(event), 300000));
bind("btn-manipulation-rollout-stop", (event) => runAction("manipulation rollout stop", "/api/lerobot/rollout/stop", sessionPayload("rollout"), actionStatusFromEvent(event)));
bind("btn-manipulation-rollout-status", (event) => runAction("manipulation rollout status", "/api/lerobot/rollout/status", sessionPayload("rollout"), actionStatusFromEvent(event)));
bind("btn-dataset-inspect", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  setActionStatus(statusTarget, "running", "dataset inspect", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/dataset/inspect", basePayload(), 60000);
    applyDatasetProfileFromInspect(data);
    renderDatasetHealth(data);
    renderResult("dataset inspect", data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "dataset inspect", data);
  } catch (err) {
    const error = { ok: false, error: String(err) };
    renderResult("dataset inspect", error);
    setActionStatus(statusTarget, "error", "dataset inspect", error);
  }
});
bind("btn-dataset-visualize", (event) => visualizeDataset(actionStatusFromEvent(event)));
bind("isaac-synthetic-check-digital-twin", (event) => runIsaacSyntheticAction("Isaac Lab synthetic prepare", "/api/lerobot/isaac-lab/prepare", actionStatusFromEvent(event), 120000));
bind("isaac-synthetic-build", (event) => runIsaacSyntheticAction("Isaac Lab synthetic build", "/api/lerobot/isaac-lab/build-synthetic", actionStatusFromEvent(event), 300000));
bind("isaac-synthetic-run-replicator-worker", (event) => runIsaacSyntheticAction("Isaac Lab Replicator worker", "/api/lerobot/isaac-lab/run-replicator-worker", actionStatusFromEvent(event), 900000, { enable_replicator: true }));
bind("isaac-synthetic-run-replicator-visual", (event) => runIsaacSyntheticAction("Isaac Lab visual Replicator", "/api/lerobot/isaac-lab/run-replicator-worker", actionStatusFromEvent(event), 900000, { enable_replicator: true, isaac_lab_visualize_generation: true }));
bind("isaac-synthetic-run-replicator-smoke", (event) => runIsaacSyntheticAction("Isaac Lab Replicator smoke", "/api/lerobot/isaac-lab/run-replicator-worker", actionStatusFromEvent(event), 180000, { enable_replicator: true, max_source_frames: 1, attempts_per_source_frame: 1, cameras: ["top"] }));
bind("isaac-synthetic-preview", (event) => runIsaacSyntheticAction("Isaac Lab synthetic preview", "/api/lerobot/isaac-lab/preview", actionStatusFromEvent(event), 60000));
bind("isaac-synthetic-export-hdf5", (event) => runIsaacSyntheticAction("Isaac Lab HDF5 export", "/api/lerobot/isaac-lab/export-hdf5", actionStatusFromEvent(event), 120000));
bind("isaac-lab-annotate-source", (event) => runIsaacSyntheticAction("Isaac Lab Mimic annotation", "/api/lerobot/isaac-lab/annotate", actionStatusFromEvent(event), 300000));
bind("isaac-lab-generate-mimic", (event) => runIsaacSyntheticAction("Isaac Lab Mimic generation", "/api/lerobot/isaac-lab/generate-mimic", actionStatusFromEvent(event), 900000, { enable_mimic: true }));
bind("isaac-lab-train-il", (event) => runIsaacSyntheticAction("Isaac Lab IL train", "/api/lerobot/isaac-lab/train-il", actionStatusFromEvent(event), 900000));
bind("isaac-lab-eval-il", (event) => runIsaacSyntheticAction("Isaac Lab IL eval", "/api/lerobot/isaac-lab/eval-il", actionStatusFromEvent(event), 900000));
bind("isaac-lab-run-e2e", (event) => runIsaacSyntheticAction("Isaac Lab Mimic + IL E2E", "/api/lerobot/isaac-lab/run-e2e", actionStatusFromEvent(event), 1800000, { enable_mimic: true }));
bind("isaac-synthetic-mimic-stop", (event) => stopIsaacDomainMimicPipeline(actionStatusFromEvent(event)));
bind("isaac-lab-domain-mimic-pipeline", (event) => runIsaacDomainMimicPipeline(actionStatusFromEvent(event)));
bind("isaac-lab-domain-mimic-check", (event) => checkIsaacDomainMimicOutputs(actionStatusFromEvent(event)));
bind("isaac-lab-domain-mimic-render-missing-rgbd", (event) => renderMissingIsaacLabMimicRgbd(actionStatusFromEvent(event)));
bind("isaac-lab-domain-mimic-stop", (event) => stopIsaacDomainMimicPipeline(actionStatusFromEvent(event)));
bind("isaac-synthetic-run-live-e2e-check", (event) => runIsaacLiveE2eCheck(actionStatusFromEvent(event)));
bind("isaac-synthetic-live-e2e-status", (event) => runIsaacLiveE2eControl("Isaac Lab 10s x 3 live status", "/api/lerobot/isaac-lab/live-e2e/status", actionStatusFromEvent(event)));
bind("isaac-synthetic-live-e2e-stop", (event) => runIsaacLiveE2eControl("Isaac Lab 10s x 3 live stop", "/api/lerobot/isaac-lab/live-e2e/stop", actionStatusFromEvent(event)));
bind("isaac-synthetic-run-mimic", (event) => runIsaacSyntheticAction("Isaac Lab Mimic runner", "/api/lerobot/isaac-lab/run-mimic", actionStatusFromEvent(event), 300000, { enable_mimic: true }));
bind("isaac-synthetic-run-mimic-smoke", (event) => runIsaacSyntheticAction("Isaac Lab Mimic smoke", "/api/lerobot/isaac-lab/run-mimic-smoke", actionStatusFromEvent(event), 120000, { enable_mimic: true }));
bind("isaac-synthetic-mimic-status", (event) => runIsaacSyntheticAction("Isaac Lab Mimic status", "/api/lerobot/isaac-lab/mimic/status", actionStatusFromEvent(event), 60000, { enable_mimic: true }));
bind("isaac-synthetic-run-rl-teacher", (event) => runIsaacSyntheticAction("Isaac Lab RL teacher runner", "/api/lerobot/isaac-lab/run-rl-teacher", actionStatusFromEvent(event), 300000, { enable_rl_teacher: true }));
bind("isaac-synthetic-run-rl-teacher-smoke", (event) => runIsaacSyntheticAction("Isaac Lab RL teacher smoke", "/api/lerobot/isaac-lab/run-rl-teacher-smoke", actionStatusFromEvent(event), 120000, { enable_rl_teacher: true }));
bind("isaac-synthetic-rl-teacher-status", (event) => runIsaacSyntheticAction("Isaac Lab RL teacher status", "/api/lerobot/isaac-lab/rl-teacher/status", actionStatusFromEvent(event), 60000, { enable_rl_teacher: true }));
bind("isaac-synthetic-rl-teacher-stop", (event) => runIsaacSyntheticAction("Isaac Lab RL teacher stop", "/api/lerobot/isaac-lab/rl-teacher/stop", actionStatusFromEvent(event), 60000, { enable_rl_teacher: true }));
bind("isaac-synthetic-e2e-smoke", (event) => runIsaacSyntheticAction("Isaac Lab 5x10 E2E smoke", "/api/lerobot/isaac-lab/e2e-smoke", actionStatusFromEvent(event), 300000, { e2e_create_fixture: true, e2e_episodes: 5, e2e_episode_s: 10, e2e_fps: 15, e2e_train_steps: 2, enable_replicator: false, require_physics_pass: false, require_articulation_pass: false }));
bind("isaac-synthetic-status", (event) => runIsaacSyntheticAction("Isaac Lab synthetic status", "/api/lerobot/isaac-lab/status", actionStatusFromEvent(event), 60000));
bind("isaac-lab-apply-standard-defaults", (event) => {
  applyIsaacLabStandardDefaults();
  const result = {
    ok: true,
    status: "standard_defaults_applied",
    mimic_trials: 3,
    mimic_num_envs: 3,
    domain_randomization_profile: "standard",
    visual: true,
    rgbd_cameras: true,
    dataset_mix: {
      real: 1,
      isaac_rgbd: 0.6,
      isaac_lab_synthetic: 0.35,
      legacy_augmentation: 0,
    },
    fidelity: {
      real: 1,
      isaac_rgbd: 0.55,
      isaac_lab_synthetic: 0.25,
      legacy_augmentation: 0,
    },
  };
  renderResult("Isaac Lab standard defaults", result);
  setActionStatus(actionStatusFromEvent(event), "ok", "Isaac Lab standard defaults", result);
});
bind("btn-isaac-augment-run", (event) => runIsaacAugmentation(actionStatusFromEvent(event)));
bind("btn-isaac-augment-preview", (event) => previewIsaacAugmentation(actionStatusFromEvent(event)));
bind("btn-dataset-visualize-status", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("LeRobot visualize status", "/api/lerobot/visualize/status", sessionPayload("visualize"), statusTarget);
  renderVisualizationSession(data);
});
bind("btn-dataset-visualize-stop", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  const data = await runAction("LeRobot visualize stop", "/api/lerobot/visualize/stop", sessionPayload("visualize"), statusTarget);
  renderVisualizationSession(data);
});
bind("btn-dataset-preview", (event) => previewDataset(actionStatusFromEvent(event)));
bind("btn-dataset-manage-refresh", (event) => refreshDatasetManageList(actionStatusFromEvent(event)));
bind("btn-dataset-manage-merge", (event) => {
  return runDatasetManageAction("dataset merge", "/api/lerobot/dataset-manage/merge", datasetManageMergePayload(), actionStatusFromEvent(event));
});
bind("btn-dataset-manage-split", (event) => {
  return runDatasetManageAction("dataset split", "/api/lerobot/dataset-manage/split", datasetManageSplitPayload(), actionStatusFromEvent(event));
});
bind("btn-dataset-manage-delete", (event) => {
  return runDatasetManageAction("dataset delete compact", "/api/lerobot/dataset-manage/delete", datasetManageDeletePayload(), actionStatusFromEvent(event));
});

if (profileSelect) profileSelect.addEventListener("change", refreshConfig);
if (policyTypeInput) policyTypeInput.addEventListener("change", () => {
  applyPolicyTypeDefaults();
  syncTrainNamingFromDataset({ policyChanged: true });
});
if (rolloutPolicyTypeInput) rolloutPolicyTypeInput.addEventListener("change", () => syncRolloutPolicyOptions());
if (datasetInput) {
  datasetInput.addEventListener("input", () => {
    markUserEdited(datasetInput);
    syncTrainNamingFromDataset();
  });
  datasetInput.addEventListener("change", () => syncTrainNamingFromDataset());
}
if (datasetRootInput) {
  datasetRootInput.addEventListener("input", () => syncDatasetManageRootFromLocalPaths());
  datasetRootInput.addEventListener("change", () => syncDatasetManageRootFromLocalPaths());
}
if (datasetManageRootInput) datasetManageRootInput.addEventListener("input", () => markUserEdited(datasetManageRootInput));
if (outputDirInput) {
  outputDirInput.addEventListener("input", () => {
    markUserEdited(outputDirInput);
    syncJobNameFromOutputDir();
  });
  outputDirInput.addEventListener("change", () => syncJobNameFromOutputDir());
}
if (jobNameInput) jobNameInput.addEventListener("input", () => markUserEdited(jobNameInput));
if (taskInput) {
  taskInput.addEventListener("input", () => {
    markUserEdited(taskInput);
    syncRolloutTaskFromRecordTask();
  });
  taskInput.addEventListener("change", () => syncRolloutTaskFromRecordTask());
}
if (rolloutInstructionInput) rolloutInstructionInput.addEventListener("input", () => markUserEdited(rolloutInstructionInput));
if (trainWandbBaseUrlInput) trainWandbBaseUrlInput.addEventListener("input", () => markUserEdited(trainWandbBaseUrlInput));
if (episodesInput) episodesInput.addEventListener("input", () => markUserEdited(episodesInput));
if (resumeInput) {
  resumeInput.addEventListener("change", () => {
    if (resumeDatasetRequested()) {
      markUserEdited(datasetInput);
      return;
    }
    if (lastWorkflowDefaults && lastWorkflowDefaults.dataset_repo_id) applyWorkflowDefaults({ workflow_defaults: lastWorkflowDefaults });
  });
}
if (trainResumeInput) {
  trainResumeInput.addEventListener("change", () => {
    if (resumeTrainingRequested()) {
      markUserEdited(outputDirInput);
      markUserEdited(jobNameInput);
      return;
    }
    syncTrainNamingFromDataset({ force: true });
  });
}
if (policySelect) {
  policySelect.addEventListener("change", () => {
    const selectedOption = policySelect.options[policySelect.selectedIndex] || null;
    const policyType = selectedOption
      ? selectedOption.dataset.policyType || inferPolicyTypeFromPolicy(policySelect.value, selectedOption.textContent || "")
      : "";
    applyPolicySelection(policySelect.value, policyType);
  });
}
if (manipulationTaskIdInput) manipulationTaskIdInput.addEventListener("change", handleManipulationTaskChange);
if (manipulationPolicySelect) {
  manipulationPolicySelect.addEventListener("change", async () => {
    const selectedOption = manipulationPolicySelect.options[manipulationPolicySelect.selectedIndex] || null;
    const policyType = selectedOption
      ? selectedOption.dataset.policyType || inferPolicyTypeFromPolicy(manipulationPolicySelect.value, selectedOption.textContent || "")
      : "";
    await persistSelectedManipulationPolicy(manipulationPolicySelect.value, policyType);
  });
}
if (manipulationPolicyInput) {
  manipulationPolicyInput.addEventListener("change", async () => {
    await persistSelectedManipulationPolicy(manipulationPolicyInput.value, selectedManipulationPolicyType());
  });
}
if (manipulationPolicyTypeInput) {
  manipulationPolicyTypeInput.addEventListener("change", async () => {
    syncManipulationPolicyOptions();
    await persistManipulationTaskProfile();
  });
}
initializeTtsControls();
applyManipulationTaskProfile(selectedManipulationTaskId(), defaultManipulationTaskProfile(selectedManipulationTaskId()));
applyPolicyTypeDefaults();
syncRolloutPolicyOptions();
syncManipulationPolicyOptions();
refreshConfig();
refreshDatasetManageList(datasetManageStatusEl);
refreshWandbLocalApiKeyStatus();
restoreIsaacDomainMimicPipelineStatus();
refreshDevicePLCStopAvailability();
loadTeleopHandoff();
window.setInterval(refreshDevicePLCStopAvailability, 1000);
