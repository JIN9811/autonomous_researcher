#!/usr/bin/env node
/*
 * Static LeRobot GUI harness for browser smoke tests.
 *
 * It intentionally avoids importing app.main because that FastAPI app has a
 * shutdown hook that cleans up live LeRobot subprocesses. This harness serves
 * only /lerobot, /static/*, and mocked /api/lerobot/* responses.
 */

const fs = require("fs");
const http = require("http");
const path = require("path");
const { URL } = require("url");

const repoRoot = process.cwd();
const portFile = process.argv[2];
const requestLogPath = process.argv[3];

if (!portFile || !requestLogPath) {
  console.error("usage: lerobot_gui_synthetic_browser_harness.js <port-file> <request-log>");
  process.exit(2);
}

const title = "LeRobot Synthetic Browser Smoke";
const stagePath = path.join(repoRoot, "sim", "robotis_omx", "scene", "omx_table_layout.usda");
const datasetRoot = path.join(repoRoot, "runs", "smoke");
const datasetPath = path.join(datasetRoot, "lerobot_synthetic_5x10");
const outputRoot = path.join(datasetPath, "sidecar", "isaac_lab_synthetic", "latest");

function jsonResponse(res, payload, statusCode = 200) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function textResponse(res, body, contentType = "text/html") {
  res.writeHead(200, {
    "content-type": contentType,
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function notFound(res) {
  res.writeHead(404, {"content-type": "text/plain"});
  res.end("not found");
}

function appendRequestLog(row) {
  fs.mkdirSync(path.dirname(requestLogPath), { recursive: true });
  fs.appendFileSync(requestLogPath, `${JSON.stringify(row)}\n`, "utf8");
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch {
        resolve({ raw });
      }
    });
  });
}

function configResponse() {
  return {
    ok: true,
    default_profile_id: "fake_omx_ai",
    selected_profile_id: "fake_omx_ai",
    default_observation_pipeline_id: "raw_depth_adapter",
    selected_observation_pipeline_id: "raw_depth_adapter",
    profiles: [
      {
        profile_id: "fake_omx_ai",
        display_name: "Fake ROBOTIS OMX-AI",
        robot_family: "robotis_omx",
        robot_type: "omx_follower",
        teleop_type: "omx_leader",
        observation_pipeline_id: "raw_depth_adapter",
        camera_map: { top: "D455F", wrist: "D405" },
        live_gate_summary: {
          live_enabled: false,
          allow_teleoperation: false,
          allow_recording: false,
          allow_training: true,
          allow_policy_rollout: false,
        },
      },
    ],
    observation_pipelines: [
      { pipeline_id: "raw_depth_adapter", label: "Raw depth adapter", description: "16-bit RealSense depth sidecar." },
      { pipeline_id: "rgbd_sidecar", label: "RGB-D sidecar", description: "RGB-D sidecar compatibility." },
    ],
    paths: {
      dataset_root: datasetRoot,
      output_root: path.join(repoRoot, "outputs"),
      policy_root: path.join(repoRoot, "policies"),
    },
    workflow_defaults: {
      dataset_repo_id: "local/synthetic-e2e-fixture",
      record_task_instruction: "Pick up the red cube",
      record_num_episodes: 5,
    },
    live_gate_summary: {
      live_enabled: false,
      allow_teleoperation: false,
      allow_recording: false,
      allow_training: true,
      allow_policy_rollout: false,
    },
    environment: { conda_env_name: "lerobot" },
    device_memory: { profiles: {} },
    sessions: [],
    tts: { engine: "piper", rate: 1.0 },
    wandb: { local_base_url: "http://127.0.0.1:8081" },
  };
}

function syntheticResponse(endpoint, body) {
  const isExport = endpoint.endsWith("/export-hdf5");
  const status = isExport ? "READY_FOR_HDF5" : "READY_FOR_TRAINING";
  const hdf5 = isExport
    ? {
        ok: true,
        status: "passed",
        hdf5_available: true,
        canonical_frame_count: 750,
        exported_frame_count: 750,
        output_path: path.join(outputRoot, "hdf5", "exported_successful_real_episodes.hdf5"),
      }
    : {};
  return {
    ok: true,
    tool: isExport ? "lerobot.isaac_lab.export_hdf5" : "lerobot.isaac_lab.build_synthetic",
    schema: "atr.lerobot.isaac_lab_synthetic.response.v1",
    status,
    dataset_path: datasetPath,
    output_root: outputRoot,
    run_id: "latest",
    pipeline_mode: body.pipeline_mode || "isaac_lab_replicator",
    fallback_policy: body.fallback_policy || "block_on_primary_failure",
    source_intent: body.source_intent || "train_ready_success_only",
    fallback_used: false,
    validation_report: {
      ok: true,
      status: "passed",
      checks: [
        { id: "validate_render_camera_plan", group: "digital_twin", status: "passed", message: "camera plan ok" },
        { id: "validate_canonical_episode_index", group: "canonical_index", status: "passed", message: "canonical ok" },
        { id: "validate_training_import", group: "training", status: "passed", message: "training ok" },
      ],
      blockers: [],
      warnings: [],
    },
    compatibility: {
      compatibility_status: "passed",
      isaac_lab_exists: true,
      isaac_sim_docs_version: "6.0.0",
    },
    digital_twin: {
      stage_exists: true,
      stage_path: stagePath,
      camera_prims: [
        {
          camera: "top",
          path: "/World/ATRRenderCameras/top",
          found: false,
          source: "replicator_worker_fallback",
          planned_pose: { position: [0.315, 0.205, 0.72], look_at: [0.315, 0.265, 0.0] },
        },
      ],
    },
    canonical_episode_index: {
      status: "passed",
      episode_count: 5,
      frame_count: 750,
    },
    replicator: {
      status: "ready",
      runtime_probe: { status: "pending" },
      checks: [{ id: "replicator_import_probe", status: "pending" }],
    },
    hdf5,
    mimic: {
      status: "ready",
      candidate_count: 8,
      success_count: 6,
      failure_count: 2,
    },
    rl_teacher: {
      status: "ready",
      candidate_count: 1,
      success_count: 1,
      failure_count: 0,
    },
    source_labels: {
      counts: { real_lerobot: 5, replicator_render_only: 0, isaac_lab_mimic: 6, isaac_lab_rl_teacher: 1 },
      details: {
        real_lerobot: { trainable_count: 5 },
        replicator_render_only: { trainable_count: 0 },
        isaac_lab_mimic: { trainable_count: 6 },
        isaac_lab_rl_teacher: { trainable_count: 1 },
        isaac_lab_synthetic: { trainable_count: 7, source_weight: 0.2, fidelity_weight: 0.25, effective_weight: 0.05, training_row_count: 7 },
      },
    },
    training_exposure: {
      row_count: 12,
      candidate_row_count: 12,
      exposed_row_count: 12,
      blocked_row_count: 0,
      validation_status: "passed",
      candidate_source_counts: { real_lerobot: 5, isaac_lab_synthetic: 7 },
      source_counts: { real_lerobot: 5, isaac_lab_synthetic: 7 },
    },
    synthetic_trajectory_metrics: {
      schema: "atr.lerobot.synthetic_trajectory_metrics.v1",
      mimic: { status: "ready", candidate_count: 8, success_count: 6, failure_count: 2, training_row_count: 6, effective_training_samples: 0.3 },
      rl_teacher: { status: "ready", candidate_count: 1, success_count: 1, failure_count: 0, training_row_count: 1, effective_training_samples: 0.06 },
      total: { candidate_count: 9, success_count: 7, failure_count: 2, training_row_count: 7, effective_training_samples: 0.36 },
    },
    progress: { percent: 100 },
    step_trace: [
      { stage: "digital_twin", status: "passed", message: "camera plan ok" },
      { stage: "canonical_index", status: "passed", message: "750 frames" },
      { stage: isExport ? "hdf5" : "training", status: "passed", message: isExport ? "hdf5 ok" : "training import ok" },
    ],
    error: null,
  };
}

function harnessScript() {
  return `
<div id="synthetic-browser-smoke" data-status="pending" style="position:fixed;left:8px;bottom:8px;z-index:9999;background:#fff;border:1px solid #333;padding:6px;font:12px monospace">pending</div>
<script>
(() => {
  const marker = document.getElementById("synthetic-browser-smoke");
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  async function waitFor(predicate, label, timeoutMs = 20000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (predicate()) return;
      await sleep(100);
    }
    throw new Error("Timed out waiting for " + label);
  }
  function setValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
  }
  function setChecked(id, value) {
    const el = document.getElementById(id);
    if (el) el.checked = Boolean(value);
  }
  async function clickAndWait(id, text, label) {
    const button = document.getElementById(id);
    if (!button) throw new Error("missing button " + id);
    button.click();
    await waitFor(() => (document.getElementById("isaac-synthetic-output")?.textContent || "").includes(text), label);
  }
  window.addEventListener("load", async () => {
    try {
      await waitFor(() => document.getElementById("isaac-synthetic-build"), "synthetic controls");
      setValue("lerobot-mode-select", "test");
      setValue("lerobot-dataset-root-input", ${JSON.stringify(datasetRoot)});
      setValue("lerobot-dataset-input", "local/synthetic-e2e-fixture");
      setValue("isaac-synthetic-isaac-sim-python", "/home/jin/IsaacSim/python.sh");
      setValue("isaac-synthetic-stage-path", ${JSON.stringify(stagePath)});
      setValue("isaac-synthetic-pipeline-mode", "isaac_lab_replicator");
      setValue("isaac-synthetic-fallback-policy", "block_on_primary_failure");
      setValue("isaac-synthetic-source-intent", "train_ready_success_only");
      setChecked("isaac-synthetic-enable-replicator", true);
      setChecked("isaac-synthetic-enable-hdf5-export", true);
      await clickAndWait("isaac-synthetic-build", "READY_FOR_TRAINING", "build render");
      const digitalTwinText = document.getElementById("isaac-synthetic-status-digital-twin")?.textContent || "";
      if (!digitalTwinText.includes("/World/ATRRenderCameras/top")) {
        throw new Error("digital twin camera fallback was not rendered: " + digitalTwinText);
      }
      const exposureText = document.getElementById("isaac-synthetic-status-training-exposure")?.textContent || "";
      if (!exposureText.includes("rows") || !exposureText.includes("5")) {
        throw new Error("training exposure card did not render row counts: " + exposureText);
      }
      const generationText = document.getElementById("isaac-synthetic-status-generation")?.textContent || "";
      if (!generationText.includes("mimic trajectories") || !generationText.includes("6 ok")) {
        throw new Error("synthetic trajectory metrics did not render: " + generationText);
      }
      await clickAndWait("isaac-synthetic-export-hdf5", "READY_FOR_HDF5", "hdf5 render");
      const hdf5Text = document.getElementById("isaac-synthetic-status-hdf5")?.textContent || "";
      if (!hdf5Text.includes("750")) {
        throw new Error("HDF5 card did not render frame count: " + hdf5Text);
      }
      marker.dataset.status = "passed";
      marker.textContent = "passed";
    } catch (err) {
      marker.dataset.status = "failed";
      marker.textContent = "failed: " + (err && err.stack ? err.stack : String(err));
      console.error(err);
    }
  });
})();
</script>`;
}

function lerobotHtml() {
  const template = fs.readFileSync(path.join(repoRoot, "web", "templates", "lerobot.html"), "utf8");
  return template.replace("{{ title }}", title).replace("</body>", `${harnessScript()}\n</body>`);
}

function serveStatic(reqPath, res) {
  const clean = decodeURIComponent(reqPath.replace(/^\/static\//, "")).split("?")[0];
  const filePath = path.resolve(path.join(repoRoot, "web", "static", clean));
  const staticRoot = path.resolve(path.join(repoRoot, "web", "static"));
  if (!filePath.startsWith(staticRoot) || !fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    return notFound(res);
  }
  const ext = path.extname(filePath);
  const contentType = ext === ".js" ? "application/javascript" : ext === ".css" ? "text/css" : "application/octet-stream";
  textResponse(res, fs.readFileSync(filePath), contentType);
}

const server = http.createServer(async (req, res) => {
  const parsed = new URL(req.url, "http://127.0.0.1");
  if (req.method === "GET" && parsed.pathname === "/lerobot") return textResponse(res, lerobotHtml());
  if (req.method === "GET" && parsed.pathname.startsWith("/static/")) return serveStatic(parsed.pathname, res);
  if (req.method === "GET" && parsed.pathname === "/api/lerobot/config") return jsonResponse(res, configResponse());
  if (req.method === "GET" && parsed.pathname === "/api/lerobot/policies") return jsonResponse(res, { ok: true, policies: [] });
  if (req.method === "GET" && parsed.pathname === "/api/lerobot/manipulation-agent/config") {
    return jsonResponse(res, { ok: true, profile: { device: "cpu", fps: 15, camera_fps: 15 } });
  }
  if (req.method === "POST" && parsed.pathname.startsWith("/api/lerobot/isaac-lab/")) {
    const body = await readBody(req);
    appendRequestLog({ method: req.method, path: parsed.pathname, body });
    return jsonResponse(res, syntheticResponse(parsed.pathname, body));
  }
  return notFound(res);
});

server.listen(0, "127.0.0.1", () => {
  const address = server.address();
  fs.writeFileSync(portFile, String(address.port), "utf8");
});

process.on("SIGTERM", () => server.close(() => process.exit(0)));
process.on("SIGINT", () => server.close(() => process.exit(0)));
