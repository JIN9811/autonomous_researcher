#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${LEROBOT_GUI_SYNTHETIC_BROWSER_SMOKE_DIR:-$ROOT_DIR/runs/smoke/gui_browser}"
mkdir -p "$OUT_DIR"

PORT_FILE="$(mktemp)"
REQUEST_LOG="$OUT_DIR/requests.jsonl"
SCREENSHOT="$OUT_DIR/lerobot_gui_synthetic_browser_smoke.png"
rm -f "$REQUEST_LOG" "$SCREENSHOT"

node "$ROOT_DIR/scripts/lerobot_gui_synthetic_browser_harness.js" "$PORT_FILE" "$REQUEST_LOG" &
SERVER_PID="$!"
cleanup() {
  kill "$SERVER_PID" >/dev/null 2>&1 || true
  rm -f "$PORT_FILE"
}
trap cleanup EXIT

for _ in $(seq 1 100); do
  if [[ -s "$PORT_FILE" ]]; then
    break
  fi
  sleep 0.05
done

if [[ ! -s "$PORT_FILE" ]]; then
  echo "Browser smoke harness did not publish a port." >&2
  exit 2
fi

PORT="$(cat "$PORT_FILE")"
URL="http://127.0.0.1:$PORT/lerobot"

npx playwright screenshot \
  --browser chromium \
  --timeout 60000 \
  --wait-for-selector '#synthetic-browser-smoke[data-status="passed"]' \
  --full-page \
  "$URL" \
  "$SCREENSHOT" >/tmp/lerobot_gui_synthetic_browser_smoke_playwright.log 2>&1 || {
    cat /tmp/lerobot_gui_synthetic_browser_smoke_playwright.log >&2
    exit 3
  }

node - "$REQUEST_LOG" <<'JS'
const fs = require("fs");
const logPath = process.argv[2];
const rows = fs.readFileSync(logPath, "utf8").trim().split(/\n+/).filter(Boolean).map((line) => JSON.parse(line));
const build = rows.find((row) => row.path === "/api/lerobot/isaac-lab/build-synthetic");
const exportHdf5 = rows.find((row) => row.path === "/api/lerobot/isaac-lab/export-hdf5");
function assert(condition, message) {
  if (!condition) throw new Error(message);
}
assert(build, "build-synthetic API was not called");
assert(exportHdf5, "export-hdf5 API was not called");
assert(build.body.mode === "test", `expected test mode, got ${build.body.mode}`);
assert(build.body.pipeline_mode === "isaac_lab_replicator", `bad pipeline_mode ${build.body.pipeline_mode}`);
assert(build.body.fallback_policy === "block_on_primary_failure", `bad fallback_policy ${build.body.fallback_policy}`);
assert(build.body.source_intent === "train_ready_success_only", `bad source_intent ${build.body.source_intent}`);
assert(Array.isArray(build.body.cameras) && build.body.cameras.includes("top"), "top camera missing from payload");
assert(build.body.isaac_sim_python === "/home/jin/IsaacSim/python.sh", "Isaac Sim Python path missing from payload");
assert(String(build.body.stage_path || "").endsWith("sim/robotis_omx/scene/omx_table_layout.usda"), "stage path missing from payload");
JS

echo "SYNTHETIC_BROWSER_SMOKE_OK screenshot=$SCREENSHOT requests=$REQUEST_LOG"
