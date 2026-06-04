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

const profileSelect = $("lerobot-profile-select");
const modeSelect = $("lerobot-mode-select");
const fpsInput = $("lerobot-fps-input");
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
const resumeInput = $("lerobot-resume-input");
const pushHubInput = $("lerobot-push-hub-input");
const policyTypeInput = $("lerobot-policy-type-input");
const outputDirInput = $("lerobot-output-dir-input");
const policyInput = $("lerobot-policy-input");
const rolloutPolicyInput = $("lerobot-rollout-policy-input");
const rolloutInstructionInput = $("lerobot-rollout-instruction-input");
const rolloutDurationInput = $("lerobot-rollout-duration-input");
const rolloutActionClampInput = $("lerobot-rollout-action-clamp-input");
const rolloutMaxRelativeTargetInput = $("lerobot-rollout-max-relative-target-input");
const rolloutTemporalEnsembleInput = $("lerobot-rollout-temporal-ensemble-input");
const rolloutTemporalCoeffInput = $("lerobot-rollout-temporal-coeff-input");
const manipulationTaskIdInput = $("lerobot-manipulation-task-id-input");
const manipulationStrategyInput = $("lerobot-manipulation-strategy-input");
const manipulationPolicyBackendInput = $("lerobot-manipulation-policy-backend-input");
const manipulationPolicyTypeInput = $("lerobot-manipulation-policy-type-input");
const manipulationSourceInput = $("lerobot-manipulation-source-input");
const manipulationTargetInput = $("lerobot-manipulation-target-input");
const manipulationMaxDurationInput = $("lerobot-manipulation-max-duration-input");
const manipulationRtcHorizonInput = $("lerobot-manipulation-rtc-horizon-input");
const manipulationRtcGuidanceInput = $("lerobot-manipulation-rtc-guidance-input");
const manipulationSpecimenIdInput = $("lerobot-manipulation-specimen-id-input");
const manipulationCandidateIdInput = $("lerobot-manipulation-candidate-id-input");
const manipulationPolicyInput = $("lerobot-manipulation-policy-input");
const manipulationStlInput = $("lerobot-manipulation-stl-input");
const manipulationTaskInput = $("lerobot-manipulation-task-input");
const manipulationObservationInput = $("lerobot-manipulation-observation-input");
const manipulationCameraInput = $("lerobot-manipulation-camera-input");
const manipulationDisplayInput = $("lerobot-manipulation-display-input");
const manipulationContinuousInput = $("lerobot-manipulation-continuous-input");
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
const trainSaveCheckpointInput = $("lerobot-train-save-checkpoint-input");
const trainUseAmpInput = $("lerobot-train-use-amp-input");
const trainWandbInput = $("lerobot-train-wandb-input");
const trainWandbProjectInput = $("lerobot-train-wandb-project-input");
const trainWandbModeInput = $("lerobot-train-wandb-mode-input");
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
const outputEl = $("lerobot-output");
const sessionListEl = $("lerobot-session-list");
const browserEl = $("lerobot-browser");
const policyListEl = $("lerobot-policy-list");
const visualizationEl = $("lerobot-visualization");
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

let lastSessions = [];
let lastSessionByWorkflow = {};
let lastBrowseTargetInput = null;
let lastBrowseKind = "any";
let lastBrowseOptions = {};
let lastPortCandidates = [];
let lastConfigData = null;
let extraCameraKeys = [];
let trainStatusTimer = null;
let manipulationProfileLoaded = false;

function setStatusDot(el, state) {
  if (!el) return;
  el.className = "status-dot";
  el.classList.add(state || "idle");
}

function boolValue(el) {
  return Boolean(el && el.checked);
}

function numberValue(el, fallback = null) {
  if (!el || el.value === "") return fallback;
  const value = Number(el.value);
  return Number.isFinite(value) ? value : fallback;
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

function trainExtraArgs() {
  const raw = trainExtraArgsInput ? trainExtraArgsInput.value.trim() : "";
  if (!raw) return [];
  return raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

const PI05_BASE_POLICY = "lerobot/pi05_base";
const PI05_TRAIN_EXTRA_DEFAULTS = [
  "--policy.compile_model=false",
  "--policy.gradient_checkpointing=true",
  "--policy.dtype=bfloat16",
  "--policy.freeze_vision_encoder=false",
  "--policy.train_expert_only=false",
];
const PI05_TRAIN_EXTRA_KEYS = PI05_TRAIN_EXTRA_DEFAULTS.map((item) => item.split("=", 1)[0]);
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
    batch_size: "32",
    steps: "3000",
    num_workers: "12",
    eval_freq: "500",
    log_freq: "5",
    save_freq: "500",
    optimizer_type: "",
    n_obs_steps: "1",
    chunk_size: "50",
    n_action_steps: "50",
    eval_batch_size: "",
    wandb_enable: true,
    wandb_mode: "offline",
  },
};
const GENERATED_PATH_SUFFIX_RE = /-(?:\d{8}T\d{6}(?:\d{6})?Z)(?:-\d{2})?$/;

const TRAIN_DEFAULT_VALUE_SETS = {
  source_policy: new Set(["", PI05_BASE_POLICY]),
  job_name: new Set(["", "atr_lerobot_train", "atr_lerobot_act_train", "atr_lerobot_pi05_train"]),
  batch_size: new Set(["", "2", "4", "8", "16", "32"]),
  steps: new Set(["", "20000", "100000", "3000"]),
  num_workers: new Set(["", "2", "4", "12", "16", "20"]),
  eval_freq: new Set(["", "500", "2000", "20000"]),
  log_freq: new Set(["", "5", "100", "200"]),
  save_freq: new Set(["", "500", "2000", "20000"]),
  optimizer_type: new Set(["", "adamw"]),
  n_obs_steps: new Set(["", "1"]),
  chunk_size: new Set(["", "100", "50"]),
  n_action_steps: new Set(["", "100", "50"]),
  eval_batch_size: new Set(["", "1", "2", "4", "8"]),
  wandb_mode: new Set(["", "disabled", "offline", "online"]),
};

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
  } else {
    removeTrainExtraArgsByKeys(PI05_TRAIN_EXTRA_KEYS);
  }
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

function browseSelectionValue(path) {
  if (lastBrowseOptions && typeof lastBrowseOptions.valueTransform === "function") {
    return lastBrowseOptions.valueTransform(path);
  }
  return path;
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

function policyFields(inputEl = policyInput) {
  const selected = policySelect ? policySelect.value : "";
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

function parseJsonText(inputEl, fallback = {}) {
  const raw = inputEl ? String(inputEl.value || "").trim() : "";
  if (!raw) return fallback;
  try {
    return JSON.parse(raw);
  } catch (err) {
    return { parse_error: String(err), raw };
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
    task_instruction: taskInput ? taskInput.value : "Pick up the cylinder",
    dataset_root: datasetRootInput ? datasetRootInput.value.trim() : "",
    dataset_repo_id: datasetSplit.repo || "jin/record-test",
    dataset_path: datasetSplit.path,
    policy_path: policy.policy_path,
    policy_checkpoint_path: policy.policy_checkpoint_path,
    policy_pretrained_path: trainSourcePolicyInput ? trainSourcePolicyInput.value.trim() : "",
    policy_type: policyTypeInput ? policyTypeInput.value || "act" : "act",
    output_dir: outputDirInput ? outputDirInput.value.trim() : "",
    job_name: jobNameInput ? jobNameInput.value.trim() : "atr_lerobot_train",
    device: deviceInput ? deviceInput.value || "cuda" : "cuda",
    seed: numberValue(trainSeedInput, null),
    batch_size: numberValue(trainBatchSizeInput, 8),
    steps: numberValue(trainStepsInput, 100000),
    num_workers: numberValue(trainWorkersInput, 4),
    eval_freq: numberValue(trainEvalFreqInput, 20000),
    log_freq: numberValue(trainLogFreqInput, 200),
    save_freq: numberValue(trainSaveFreqInput, 20000),
    save_checkpoint: boolValue(trainSaveCheckpointInput),
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
    train_extra_args: trainExtraArgs(),
    fps: numberValue(fpsInput, 30),
    warmup_s: 2,
    episode_s: numberValue(episodeTimeInput, 60),
    reset_s: numberValue(resetTimeInput, 30),
    num_episodes: numberValue(episodesInput, 1),
    tts_engine: ttsEngineInput ? ttsEngineInput.value || "piper" : "piper",
    tts_rate: numberValue(ttsRateInput, -35),
    display_data: boolValue(displayDataInput),
    camera_enabled: true,
    resume: boolValue(resumeInput),
    push_to_hub: boolValue(pushHubInput),
    confirm_live_execute: boolValue(confirmLiveInput),
    episode_index: numberValue(episodeIndexInput, 0),
    visualization_tool: visualizationToolInput ? visualizationToolInput.value || "html" : "html",
    visualization_mode: visualizationModeInput ? visualizationModeInput.value || "local" : "local",
    visualization_batch_size: numberValue(visualizationBatchSizeInput, 32),
    visualization_num_workers: numberValue(visualizationWorkersInput, 4),
    visualization_web_port: numberValue(visualizationWebPortInput, 9090),
    visualization_ws_port: numberValue(visualizationWsPortInput, 9087),
    visualization_tolerance_s: numberValue(visualizationToleranceInput, 0.0001),
    visualization_save: boolValue(visualizationSaveInput),
    visualization_output_dir: visualizationOutputDirInput ? visualizationOutputDirInput.value.trim() : "",
    observation: parseObservation(),
    dry_run: (modeSelect ? modeSelect.value : "test") !== "live",
    ...overrides,
  };
}

function rolloutPayload(overrides = {}) {
  const payload = basePayload(overrides);
  const policy = rolloutPolicyFields();
  payload.policy_path = policy.policy_path;
  payload.policy_checkpoint_path = policy.policy_checkpoint_path;
  payload.policy_repo_id = policy.policy_path ? "" : policy.policy_repo_id;
  payload.task_instruction = rolloutInstructionInput && rolloutInstructionInput.value.trim()
    ? rolloutInstructionInput.value.trim()
    : payload.task_instruction;
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
  payload.rollout_action_clamp = rolloutActionClampInput ? boolValue(rolloutActionClampInput) : true;
  payload.rollout_max_relative_target = numberValue(rolloutMaxRelativeTargetInput, 5);
  payload.rollout_temporal_ensemble = rolloutTemporalEnsembleInput ? boolValue(rolloutTemporalEnsembleInput) : true;
  payload.rollout_temporal_ensemble_coeff = numberValue(rolloutTemporalCoeffInput, 0.01);
  return payload;
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

function syncManipulationTaskPreset(force = false) {
  const taskId = selectedManipulationTaskId();
  const preset = MANIPULATION_TASK_PRESETS[taskId] || MANIPULATION_TASK_PRESETS.transfer_to_utm;
  const sourceDefault = Object.values(MANIPULATION_TASK_PRESETS).some((item) => manipulationSourceInput && manipulationSourceInput.value === item.source);
  const targetDefault = Object.values(MANIPULATION_TASK_PRESETS).some((item) => manipulationTargetInput && manipulationTargetInput.value === item.target);
  if (manipulationSourceInput && (force || !manipulationSourceInput.value.trim() || sourceDefault)) manipulationSourceInput.value = preset.source;
  if (manipulationTargetInput && (force || !manipulationTargetInput.value.trim() || targetDefault)) manipulationTargetInput.value = preset.target;
  if (manipulationTaskInput && (force || !manipulationTaskInput.value.trim())) manipulationTaskInput.value = preset.instruction;
  if (manipulationObservationInput && (force || !manipulationObservationInput.value.trim())) {
    manipulationObservationInput.value = JSON.stringify(preset.observation);
  }
}

function manipulationDefaultInstruction(taskId, specimenId, sourceLocation, targetLocation) {
  const preset = MANIPULATION_TASK_PRESETS[taskId] || MANIPULATION_TASK_PRESETS.transfer_to_utm;
  if (taskId === "clear_utm_to_disposal") {
    return `Move ${specimenId} from ${sourceLocation} to ${targetLocation}, release it into the discard bin, retreat to standby_clear_of_utm, then request Vision verification.`;
  }
  return `Move ${specimenId} from ${sourceLocation} to ${targetLocation}, place the flat compression face on the UTM datum, release, retreat to standby_clear_of_utm, then request Vision verification.`;
}

function manipulationAgentPayload(overrides = {}) {
  const payload = rolloutPayload(overrides);
  const policy = policyFields(manipulationPolicyInput || rolloutPolicyInput || policyInput);
  const taskId = selectedManipulationTaskId();
  const preset = MANIPULATION_TASK_PRESETS[taskId] || MANIPULATION_TASK_PRESETS.transfer_to_utm;
  const policyType = manipulationPolicyTypeInput ? manipulationPolicyTypeInput.value || "pi05" : "pi05";
  const strategy = manipulationStrategyInput ? manipulationStrategyInput.value || "pi05_lerobot_policy" : "pi05_lerobot_policy";
  const specimenId = manipulationSpecimenIdInput ? manipulationSpecimenIdInput.value.trim() || "manual-specimen" : "manual-specimen";
  const candidateId = manipulationCandidateIdInput ? manipulationCandidateIdInput.value.trim() || "manual-candidate" : "manual-candidate";
  const sourceLocation = manipulationSourceInput ? manipulationSourceInput.value.trim() || preset.source : preset.source;
  const targetLocation = manipulationTargetInput ? manipulationTargetInput.value.trim() || preset.target : preset.target;
  payload.policy_path = policy.policy_path;
  payload.policy_checkpoint_path = policy.policy_checkpoint_path;
  payload.policy_repo_id = policy.policy_path ? "" : policy.policy_repo_id;
  payload.policy_type = policyType;
  payload.rollout_inference_type = policyType === "pi05" ? "rtc" : "";
  payload.manipulation_strategy = strategy;
  payload.task_id = taskId;
  payload.skill_id = taskId;
  payload.policy_backend = manipulationPolicyBackendInput ? manipulationPolicyBackendInput.value || "lerobot_cli" : "lerobot_cli";
  payload.max_duration_s = numberValue(manipulationMaxDurationInput, 30);
  payload.rollout_rtc_execution_horizon = numberValue(manipulationRtcHorizonInput, 10);
  payload.rollout_rtc_max_guidance_weight = numberValue(manipulationRtcGuidanceInput, 1.0);
  payload.task_instruction = manipulationTaskInput && manipulationTaskInput.value.trim()
    ? manipulationTaskInput.value.trim()
    : manipulationDefaultInstruction(taskId, specimenId, sourceLocation, targetLocation);
  payload.camera_enabled = manipulationCameraInput ? boolValue(manipulationCameraInput) : true;
  payload.display_data = manipulationDisplayInput ? boolValue(manipulationDisplayInput) : false;
  payload.continuous_rollout = manipulationContinuousInput ? boolValue(manipulationContinuousInput) : true;
  payload.source_location = sourceLocation;
  payload.target_location = targetLocation;
  payload.observation = parseJsonText(manipulationObservationInput, preset.observation);
  payload.specimen_result = {
    ok: true,
    specimen_id: specimenId,
    candidate_id: candidateId,
    handoff_status: "ready",
    stl_path: manipulationStlInput ? manipulationStlInput.value.trim() : "",
    sliced_path: "",
  };
  return payload;
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
  if (profileSelect && profile.profile_id) {
    const hasProfile = Array.from(profileSelect.options || []).some((opt) => opt.value === profile.profile_id);
    if (hasProfile) profileSelect.value = profile.profile_id;
  }
  setInputValue(manipulationTaskIdInput, profile.task_id || profile.skill_id);
  setInputValue(manipulationStrategyInput, profile.manipulation_strategy);
  setInputValue(manipulationPolicyBackendInput, profile.policy_backend);
  setInputValue(manipulationPolicyTypeInput, profile.policy_type);
  setInputValue(manipulationSourceInput, profile.source_location);
  setInputValue(manipulationTargetInput, profile.target_location);
  setInputValue(manipulationMaxDurationInput, profile.max_duration_s);
  setInputValue(manipulationRtcHorizonInput, profile.rollout_rtc_execution_horizon);
  setInputValue(manipulationRtcGuidanceInput, profile.rollout_rtc_max_guidance_weight);
  setInputValue(
    manipulationPolicyInput,
    profile.policy_path || profile.policy_checkpoint_path || profile.policy_repo_id || "",
  );
  if (profile.task_instruction) setInputValue(manipulationTaskInput, profile.task_instruction);
  setCheckboxValue(manipulationCameraInput, profile.camera_enabled);
  setCheckboxValue(manipulationDisplayInput, profile.display_data);
  setCheckboxValue(manipulationContinuousInput, profile.continuous_rollout);
  if (deviceInput && profile.device) deviceInput.value = profile.device;
  if (fpsInput && profile.fps) fpsInput.value = String(profile.fps);
  if (rolloutActionClampInput && profile.rollout_action_clamp !== undefined) {
    rolloutActionClampInput.checked = Boolean(profile.rollout_action_clamp);
  }
  if (rolloutMaxRelativeTargetInput && profile.rollout_max_relative_target !== undefined) {
    rolloutMaxRelativeTargetInput.value = String(profile.rollout_max_relative_target);
  }
  if (rolloutTemporalEnsembleInput && profile.rollout_temporal_ensemble !== undefined) {
    rolloutTemporalEnsembleInput.checked = Boolean(profile.rollout_temporal_ensemble);
  }
  if (rolloutTemporalCoeffInput && profile.rollout_temporal_ensemble_coeff !== undefined) {
    rolloutTemporalCoeffInput.value = String(profile.rollout_temporal_ensemble_coeff);
  }
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

function visualizationPayload(overrides = {}) {
  const payload = basePayload(overrides);
  const explicitPath = visualizationPathInput && visualizationPathInput.value.trim() ? visualizationPathInput.value.trim() : "";
  if (explicitPath) {
    payload.dataset_path = explicitPath;
    payload.dataset_repo_id = "";
  }
  return payload;
}

function devicePayload(role, overrides = {}) {
  return {
    mode: modeSelect ? modeSelect.value : "test",
    runtime_mode: modeSelect ? modeSelect.value : "test",
    profile_id: profileSelect ? profileSelect.value : "",
    device_role: role,
    port: manualPortInput ? manualPortInput.value.trim() : "",
    camera_key: overrides.camera_key || (manualCameraKeyInput ? manualCameraKeyInput.value.trim() || "top" : "top"),
    confirm_live_execute: boolValue(confirmLiveInput),
    dry_run: (modeSelect ? modeSelect.value : "test") !== "live",
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

function isActiveSession(session) {
  if (!session || !session.session_id) return false;
  const status = String(session.status || "").toUpperCase();
  const terminal = new Set(["STOPPED", "FAILED", "COMPLETED", "CANCELLED", "DATASET_COMPLETE"]);
  if (terminal.has(status)) return false;
  return session.returncode === undefined || session.returncode === null;
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
      <span class="state-pill">${session.status || "unknown"}</span>
    `;
    row.addEventListener("click", () => renderResult("session", session));
    sessionListEl.appendChild(row);
  }
}

function applyDefaultPaths(data) {
  const paths = data.paths || {};
  if (datasetRootInput && !datasetRootInput.value) datasetRootInput.value = paths.dataset_root || "";
  if (outputDirInput && !outputDirInput.value) outputDirInput.value = paths.output_root ? `${paths.output_root}/atr_lerobot_train` : "";
  if (visualizationOutputDirInput && !visualizationOutputDirInput.value) visualizationOutputDirInput.value = paths.output_root ? `${paths.output_root}/visualize_dataset` : "";
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

function renderManipulationAgentReport(data) {
  if (!manipulationReportEl) return;
  const report = manipulationReportFromResponse(data);
  if (!report) return;
  const packet = robotTaskResultFromResponse(data, report) || {};
  const task = report.task || {};
  const policy = report.policy_plan || {};
  const preflight = report.preflight || {};
  const vision = report.vision_context || {};
  const stage = report.stage_machine || {};
  const sarm = report.sarm || {};
  const decision = report.decision || {};
  const runtime = report.rollout_runtime || {};
  const evidence = packet.evidence_refs || (report.knowledge_payload && report.knowledge_payload.evidence_paths) || [];
  const preflightState = String(preflight.status || "unknown");
  const handoffState = String(packet.handoff_status || decision.handoff_status || "unknown");
  manipulationReportEl.innerHTML = `
    <article class="lerobot-report-card wide">
      <div class="lerobot-report-card-title">
        <strong>Skill Episode Board</strong>
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
    <article class="lerobot-report-card">
      <div class="lerobot-report-card-title"><strong>Preflight</strong><span class="state-pill ${escapeHtml(preflightState === "pass" ? "ok" : preflightState === "fail" ? "warning" : "")}">${escapeHtml(preflightState)}</span></div>
      ${reportRowsHtml([
        ["Profile", preflight.profile_id],
        ["Robot Ready", preflight.robot_ready],
        ["Camera Ready", preflight.camera_ready],
        ["Policy Ready", preflight.policy_ready],
        ["Operator Confirmed", preflight.operator_confirmed],
        ["RTC", preflight.rtc_enabled],
        ["Action Clamp", preflight.action_clamp_enabled],
      ])}
      <div class="lerobot-report-subtitle">Warnings / blockers</div>
      ${reportListHtml([...(preflight.blocking_reasons || []), ...(preflight.warnings || [])])}
    </article>
    <article class="lerobot-report-card">
      <div class="lerobot-report-card-title"><strong>Pi0.5 / Policy Runtime</strong></div>
      ${reportRowsHtml([
        ["Backend", policy.policy_backend],
        ["Policy Type", policy.policy_type],
        ["Policy Ref", policy.policy_ref],
        ["Inference", policy.inference_type],
        ["RTC Horizon", policy.rtc_execution_horizon],
        ["RTC Guidance", policy.rtc_max_guidance_weight],
        ["Max Duration", policy.max_duration_s],
        ["Rollout Status", runtime.status],
        ["Session", runtime.session_id],
      ])}
    </article>
    <article class="lerobot-report-card">
      <div class="lerobot-report-card-title"><strong>Vision Dependency</strong></div>
      ${reportRowsHtml([
        ["Observation", vision.observation_id],
        ["Camera", vision.camera],
        ["Pickup Ready", vision.pickup_target_ready],
        ["Fixture Visible", vision.fixture_visible],
        ["Anomaly", vision.anomaly],
        ["Freshness", vision.freshness && vision.freshness.reason],
      ])}
    </article>
    <article class="lerobot-report-card">
      <div class="lerobot-report-card-title"><strong>SARM Stage Progress</strong></div>
      ${reportRowsHtml([
        ["Current Stage", stage.current_stage],
        ["Next Expected", stage.next_expected_stage],
        ["Completed", (stage.completed_stages || []).length],
        ["Progress", sarm.progress_score],
        ["Failure Precursor", sarm.failure_precursor],
        ["Recovery", sarm.recovery_suggested],
      ])}
    </article>
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
  const scope = el ? el.closest(".lerobot-device-card, .lerobot-port-panel, .lerobot-workflow-card, .lerobot-visualization-panel, .lerobot-config-panel") : null;
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
  if (data.failure_code) return `${data.failure_code}: ${data.message || data.error || data.status || "failed"}`;
  if (data.error) return String(data.error);
  if (data.training) {
    const t = data.training;
    return `${data.status || "training"} · ${t.current_step || 0}/${t.total_steps || "?"} · ${Number(t.progress_percent || 0).toFixed(1)}%`;
  }
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

function trainingProgressHtml(data) {
  const training = data && data.training ? data.training : null;
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
  const training = data && data.training ? data.training : null;
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

function trainIsActive(data) {
  if (!data || data.workflow !== "train") return false;
  const status = String(data.status || "").toUpperCase();
  const terminal = new Set(["STOPPED", "FAILED", "COMPLETED", "CANCELLED"]);
  return !terminal.has(status) && (data.returncode === undefined || data.returncode === null);
}

function setActionStatus(target, state, label, data = null) {
  if (!target) return;
  const el = typeof target === "string" ? $(target) : target;
  if (!el) return;
  const normalized = state || "idle";
  const prefix = normalized === "ok" ? "OK" : normalized === "error" ? "ERROR" : normalized === "running" ? "RUNNING" : "IDLE";
  const logTail = compactLogTail(data);
  const progressHtml = trainingProgressHtml(data);
  const logHtml = logTail ? `<pre class="lerobot-inline-log">${escapeHtml(logTail)}</pre>` : "";
  el.className = `lerobot-action-status ${normalized}`;
  el.innerHTML = `<strong>${prefix}</strong><span>${escapeHtml(label || "action")}</span><small>${escapeHtml(actionSummary(data))}</small>${progressHtml}${logHtml}`;
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
      const removable = !defaultKeys.has(key);
      return `
        <article class="lerobot-device-card">
          <div class="lerobot-card-title-row">
            <strong>${escapeHtml(key)} Camera</strong>
            ${removable ? `<button class="btn mini danger camera-remove" data-camera-key="${escapeHtml(key)}" type="button">-</button>` : `<span class="state-pill">default</span>`}
          </div>
          <code>${escapeHtml(camera.port || "not saved")}</code>
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
    for (const button of cameraCardListEl.querySelectorAll(".camera-action")) {
      button.addEventListener("click", (event) => {
        const cameraKey = button.dataset.cameraKey || "top";
        if (manualCameraKeyInput) manualCameraKeyInput.value = cameraKey;
        const action = button.dataset.cameraAction || "test";
        const statusTarget = actionStatusFromEvent(event);
        if (action === "baseline") return runDevicePortAction(`${cameraKey} camera baseline`, "/api/lerobot/ports/baseline", "camera", { port: "", camera_key: cameraKey }, statusTarget);
        if (action === "detect") return runDevicePortAction(`${cameraKey} camera detect/save`, "/api/lerobot/ports/detect", "camera", { port: "", camera_key: cameraKey }, statusTarget);
        return runDevicePortAction(`${cameraKey} camera capture test`, "/api/lerobot/camera/test", "camera", { port: "", camera_key: cameraKey }, statusTarget);
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
  if (profileSelect) {
    const prior = profileSelect.value || selected;
    profileSelect.innerHTML = "";
    for (const profile of profiles) {
      const opt = document.createElement("option");
      opt.value = profile.profile_id;
      opt.textContent = `${profile.display_name || profile.profile_id} (${profile.profile_id})`;
      profileSelect.appendChild(opt);
    }
    profileSelect.value = profiles.some((p) => p.profile_id === prior) ? prior : selected;
  }

  applyDefaultPaths(data);
  const profile = profiles.find((p) => p.profile_id === (profileSelect ? profileSelect.value : selected)) || profiles[0] || {};
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
  renderDeviceMemory(data);
  renderSessions(data.sessions || []);
}

async function refreshConfig() {
  try {
    const res = await fetch("/api/lerobot/config");
    const data = await res.json();
    renderConfig(data);
    await refreshPolicies();
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
  if (policySelect) {
    const prior = policySelect.value;
    policySelect.innerHTML = "";
    for (const policy of policies) {
      const opt = document.createElement("option");
      opt.value = policy.value || policy.path || policy.repo_id || "";
      opt.textContent = `${policy.label || opt.value || "manual"} · ${policy.source || "policy"}`;
      policySelect.appendChild(opt);
    }
    if (policies.some((p) => (p.value || p.path || p.repo_id || "") === prior)) policySelect.value = prior;
  }
  if (policyListEl) {
    policyListEl.innerHTML = policies.slice(0, 12).map((p) => `<button class="btn mini policy-chip" data-policy="${p.value || p.path || p.repo_id || ""}">${p.label || p.value || "policy"}</button>`).join("");
    for (const button of policyListEl.querySelectorAll(".policy-chip")) {
      button.addEventListener("click", () => {
        if (policyInput) policyInput.value = button.dataset.policy || "";
        if (rolloutPolicyInput) rolloutPolicyInput.value = button.dataset.policy || "";
        if (trainSourcePolicyInput) trainSourcePolicyInput.value = button.dataset.policy || "";
        if (policySelect) policySelect.value = button.dataset.policy || "";
      });
    }
  }
  return data;
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
  if (rolloutPolicyInput) rolloutPolicyInput.value = value;
  if (policyInput) policyInput.value = value;
  if (policySelect) policySelect.value = value;
  setActionStatus(statusTarget, "ok", "use latest policy", { policy_path: value, label: local.label });
  return local;
}

async function runAction(label, url, payload = null, statusTarget = null, timeoutMs = 30000) {
  renderResult(`${label} running`, { ok: true, status: "request_sent" });
  setActionStatus(statusTarget, "running", label, { status: "request sent" });
  try {
    const data = await postJson(url, payload || basePayload(), timeoutMs);
    renderResult(label, data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", label, data);
    syncFieldsFromWorkflowResponse(data);
    handleTrainProgressResponse(data, statusTarget);
    await refreshConfig();
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderResult(label, error);
    setActionStatus(statusTarget, "error", label, error);
    return error;
  }
}

function handleTrainProgressResponse(data, statusTarget = null) {
  if (!data || data.workflow !== "train") return;
  renderTrainingProgress(data);
  if (trainIsActive(data)) {
    startTrainStatusPolling(statusTarget || $("lerobot-train-action-status"));
  } else {
    stopTrainStatusPolling();
  }
}

function startTrainStatusPolling(statusTarget = null) {
  stopTrainStatusPolling();
  const target = statusTarget || $("lerobot-train-action-status");
  trainStatusTimer = window.setInterval(async () => {
    try {
      const data = await postJson("/api/lerobot/train/status", sessionPayload("train"));
      renderResult("train status", data);
      setActionStatus(target, data && data.ok ? "ok" : "error", "train status", data);
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
  const canUseCurrent = lastBrowseTargetInput && (lastBrowseOptions.select || "directory") !== "file";
  browserEl.innerHTML = `
    <div class="browser-head">
      <button class="btn mini" id="btn-browser-parent">Parent</button>
      ${canUseCurrent ? `<button class="btn mini primary" id="btn-browser-use-current">Use current folder</button>` : ""}
      <button class="btn mini" id="btn-browser-native">Native picker</button>
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
    useCurrentBtn.addEventListener("click", () => {
      if (lastBrowseTargetInput) lastBrowseTargetInput.value = browseSelectionValue(data.path || "");
      browserEl.classList.add("hidden");
    });
  }
  const nativeBtn = $("btn-browser-native");
  if (nativeBtn) nativeBtn.addEventListener("click", () => openNativePathPicker(data.path || ""));
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
    button.addEventListener("click", () => {
      const path = button.dataset.path || "";
      const kind = button.dataset.kind || "file";
      if (kind === "dir") {
        if (lastBrowseTargetInput) lastBrowseTargetInput.value = browseSelectionValue(path);
        browsePath(lastBrowseKind, path, lastBrowseTargetInput, lastBrowseOptions);
      } else if (lastBrowseTargetInput) {
        lastBrowseTargetInput.value = browseSelectionValue(path);
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
    if (lastBrowseTargetInput) lastBrowseTargetInput.value = browseSelectionValue(picked.selected_path);
    if (browserEl) browserEl.classList.add("hidden");
  }
  return picked;
}

async function browsePath(kind, path = "", targetInput = null, options = {}) {
  lastBrowseKind = kind || "any";
  lastBrowseTargetInput = targetInput;
  lastBrowseOptions = { include_files: true, select: "directory", ...options };
  const includeFiles = lastBrowseOptions.include_files !== false;
  const data = await postJson("/api/lerobot/files/browse", { kind: lastBrowseKind, path, include_files: includeFiles });
  renderBrowser(data);
  renderResult("browse paths", data);
  return data;
}

function renderVisualizationSession(data) {
  if (!visualizationEl) return;
  const viz = (data && data.visualization) || {};
  const command = Array.isArray(data && data.command_preview) ? data.command_preview.join(" ") : "";
  const tool = viz.tool || "html";
  const mode = viz.visualization_mode || "local";
  const viewerHint = tool === "html"
    ? `LeRobot HTML viewer: ${viz.viewer_url || "waiting for server URL"}`
    : mode === "distant"
    ? `Rerun websocket: ${viz.rerun_ws_url || "ws://localhost:9087"}`
    : (viz.save ? `RRD output: ${viz.output_dir || "configured output dir"}` : "Local Rerun viewer should open from the LeRobot process.");
  const viewerLink = viz.viewer_url
    ? `<a class="btn mini primary" href="${escapeHtml(viz.viewer_url)}" target="_blank" rel="noopener">Open viewer</a>`
    : "";
  visualizationEl.innerHTML = `
    <div class="visual-summary">
      <strong>${escapeHtml(viz.repo_id || data.dataset_path || "LeRobot visualization")}</strong>
      <span>tool=${escapeHtml(tool)} · session=${escapeHtml((data && data.session_id) || "")} · status=${escapeHtml((data && data.status) || "")} · episode=${escapeHtml(String(viz.episode_index ?? ""))}</span>
      <span>${escapeHtml(viewerHint)}</span>
      ${viewerLink}
    </div>
    <details open><summary>LeRobot visualize command</summary><pre class="command-output">${escapeHtml(command || "No command preview.")}</pre></details>
    ${data && data.log_tail ? `<details open><summary>Process log</summary><pre class="command-output">${escapeHtml(data.log_tail)}</pre></details>` : ""}
  `;
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
  const videoHtml = videos.map((item) => `<figure><video src="${item.serve_url}" controls muted></video><figcaption>${item.name}</figcaption></figure>`).join("");
  const imageHtml = images.map((item) => `<figure><img src="${item.serve_url}" alt="${item.name}" /><figcaption>${item.name}</figcaption></figure>`).join("");
  const dataHtml = dataFiles.slice(0, 12).map((item) => `<li>${item.name} · ${item.size_bytes} bytes</li>`).join("");
  visualizationEl.innerHTML = `
    <div class="visual-summary">
      <strong>${data.dataset_path}</strong>
      <span>episode=${data.episode_index} · videos=${videos.length} · images=${images.length} · data=${dataFiles.length}</span>
    </div>
    <div class="visual-media-grid">${videoHtml}${imageHtml || ""}</div>
    <details open><summary>Dataset metadata</summary><pre class="command-output">${JSON.stringify(data.metadata || {}, null, 2)}</pre></details>
    <details><summary>Data files</summary><ul>${dataHtml || "<li>No local media/data files found.</li>"}</ul></details>
  `;
}

async function visualizeDataset(statusTarget = null) {
  const payload = visualizationPayload({ episode_index: numberValue(episodeIndexInput, 0) });
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
  const payload = visualizationPayload({ episode_index: numberValue(episodeIndexInput, 0) });
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

function bind(id, handler) {
  const el = $(id);
  if (el) el.addEventListener("click", handler);
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
  const data = await postJson("/api/lerobot/config", { profile_id: profileSelect ? profileSelect.value : "", mode: modeSelect ? modeSelect.value : "test" });
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
  bind(`btn-port-detect-${role}`, (event) => runDevicePortAction(`${role} detect/save`, "/api/lerobot/ports/detect", role, { port: "" }, actionStatusFromEvent(event)));
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

bind("btn-browse-dataset-root", () => browsePath("dataset", datasetRootInput ? datasetRootInput.value : "", datasetRootInput));
bind("btn-browse-dataset-repo", () => browsePath("dataset", datasetBrowseStartPath(), datasetInput, { include_files: false, valueTransform: datasetRepoValueFromPath }));
bind("btn-browse-output-dir", () => browsePath("output", outputDirInput ? outputDirInput.value : "", outputDirInput));
bind("btn-browse-policy", () => browsePath("policy", policyInput ? policyInput.value : "", policyInput, { select: "file", include_files: true }));
bind("btn-browse-rollout-policy", () => {
  const startPath = (rolloutPolicyInput && rolloutPolicyInput.value.trim()) || (outputDirInput && outputDirInput.value.trim()) || "";
  return browsePath("policy", startPath, rolloutPolicyInput || policyInput, { select: "file", include_files: true });
});
bind("btn-browse-manipulation-policy", () => {
  const startPath = (manipulationPolicyInput && manipulationPolicyInput.value.trim())
    || (rolloutPolicyInput && rolloutPolicyInput.value.trim())
    || (outputDirInput && outputDirInput.value.trim())
    || "";
  return browsePath("policy", startPath, manipulationPolicyInput || rolloutPolicyInput || policyInput, { select: "file", include_files: true });
});
bind("btn-browse-manipulation-stl", () => browsePath("any", manipulationStlInput ? manipulationStlInput.value : "", manipulationStlInput, { select: "file", include_files: true }));
bind("btn-manipulation-use-rollout-policy", (event) => {
  if (manipulationPolicyInput && rolloutPolicyInput) manipulationPolicyInput.value = rolloutPolicyInput.value;
  const statusTarget = actionStatusFromEvent(event);
  setActionStatus(statusTarget, "ok", "use rollout policy", { status: "rollout policy copied to Manipulation Agent Bridge" });
});
bind("btn-rollout-latest-policy", (event) => useLatestLocalPolicy(actionStatusFromEvent(event)));
bind("btn-browse-visualization", () => browsePath("dataset", visualizationPathInput ? visualizationPathInput.value : "", visualizationPathInput));
bind("btn-browse-visualization-output", () => browsePath("output", visualizationOutputDirInput ? visualizationOutputDirInput.value : "", visualizationOutputDirInput));

bind("btn-teleop-start", (event) => runAction("teleoperate start", "/api/lerobot/teleoperate/start", basePayload({ teleop_time_s: numberValue(teleopTimeInput, null) }), actionStatusFromEvent(event)));
bind("btn-teleop-stop", (event) => runAction("teleoperate stop", "/api/lerobot/teleoperate/stop", sessionPayload("teleoperate"), actionStatusFromEvent(event)));
bind("btn-teleop-status", (event) => runAction("teleoperate status", "/api/lerobot/teleoperate/status", sessionPayload("teleoperate"), actionStatusFromEvent(event)));

if (ttsEngineInput) ttsEngineInput.addEventListener("change", () => { ttsEngineInput.dataset.userEdited = "1"; });
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

bind("btn-record-start", (event) => runAction("record start", "/api/lerobot/record/start", null, actionStatusFromEvent(event)));
async function runRecordControl(label, action, event) {
  return runAction(label, "/api/lerobot/record/control", sessionPayload("record", { action }), actionStatusFromEvent(event));
}

bind("btn-record-stop", (event) => runRecordControl("record force stop", "stop", event));
bind("btn-record-retry", (event) => runRecordControl("record retry", "retry", event));
bind("btn-record-next", (event) => runRecordControl("record next", "next", event));
bind("btn-record-finish", (event) => runRecordControl("record finish", "finish", event));

bind("btn-train-start", (event) => runAction("train start", "/api/lerobot/train/start", null, actionStatusFromEvent(event)));
bind("btn-train-cancel", (event) => runAction("train cancel", "/api/lerobot/train/cancel", sessionPayload("train"), actionStatusFromEvent(event)));
bind("btn-train-status", (event) => runAction("train status", "/api/lerobot/train/status", sessionPayload("train"), actionStatusFromEvent(event)));
bind("btn-policy-refresh", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  setActionStatus(statusTarget, "running", "refresh policies", { status: "request sent" });
  const data = await refreshPolicies();
  setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "refresh policies", data);
});

bind("btn-rollout-start", (event) => runAction("rollout start", "/api/lerobot/rollout/start", rolloutPayload(), actionStatusFromEvent(event)));
bind("btn-rollout-stop", (event) => runAction("rollout stop", "/api/lerobot/rollout/stop", sessionPayload("rollout"), actionStatusFromEvent(event)));
bind("btn-rollout-status", (event) => runAction("rollout status", "/api/lerobot/rollout/status", sessionPayload("rollout"), actionStatusFromEvent(event)));
bind("btn-manipulation-save", async (event) => {
  const statusTarget = actionStatusFromEvent(event);
  setActionStatus(statusTarget, "running", "manipulation defaults save", { status: "request sent" });
  try {
    const data = await postJson("/api/lerobot/manipulation-agent/config", manipulationAgentPayload());
    renderResult("manipulation defaults save", data);
    setActionStatus(statusTarget, data && data.ok ? "ok" : "error", "manipulation defaults save", data);
    applyManipulationProfile(data.profile || {}, true);
    await refreshConfig();
    return data;
  } catch (err) {
    const error = { ok: false, status: "request_failed", error: String(err) };
    renderResult("manipulation defaults save", error);
    setActionStatus(statusTarget, "error", "manipulation defaults save", error);
    return error;
  }
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
bind("btn-dataset-inspect", (event) => runAction("dataset inspect", "/api/lerobot/dataset/inspect", null, actionStatusFromEvent(event)));
bind("btn-dataset-visualize", (event) => visualizeDataset(actionStatusFromEvent(event)));
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

if (profileSelect) profileSelect.addEventListener("change", refreshConfig);
if (policySelect) {
  policySelect.addEventListener("change", () => {
    if (policyInput && policySelect.value) policyInput.value = policySelect.value;
    if (rolloutPolicyInput && policySelect.value) rolloutPolicyInput.value = policySelect.value;
    if (trainSourcePolicyInput && policySelect.value) trainSourcePolicyInput.value = policySelect.value;
  });
}
if (policyTypeInput) policyTypeInput.addEventListener("change", applyPolicyTypeDefaults);
if (manipulationTaskIdInput) manipulationTaskIdInput.addEventListener("change", () => syncManipulationTaskPreset(true));
initializeTtsControls();
syncManipulationTaskPreset(false);
applyPolicyTypeDefaults();
refreshConfig();
