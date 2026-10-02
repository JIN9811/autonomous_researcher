const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const test = require("node:test");

function body(file, name) {
  const source = fs.readFileSync(file, "utf8");
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `Missing ${name}`);
  return source.slice(start, source.indexOf("\n}", start) + 2);
}

test("artifact explorer exposes files beyond 80 and isolates the selected loop", () => {
  const output = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
  const context = vm.createContext({
    currentArtifacts: Array.from({ length: 90 }, (_, i) => ({
      name: `result-${i}.json`, path: `result-${i}.json`, loop_index: i < 85 ? 0 : 1,
      loop_number: i < 85 ? 1 : 2, agent: "analysis_agent", attempt_index: 1,
    })),
    artifactLoopFilter: "", currentRunId: "run-1", artifactLineageOutput: output,
    artifactPreviewOutput: { innerHTML: "" }, artifactRelatedEvent: () => null,
    artifactStageFromPath: () => "analysis", escapeHtml: String,
  });
  vm.runInContext(body("web/static/runtime_ide.js", "renderArtifactLineage"), context);
  vm.runInContext("renderArtifactLineage()", context);
  assert.ok(output.innerHTML.includes("result-89.json"));
  assert.ok(output.innerHTML.includes("Loop 1") && output.innerHTML.includes("Loop 2"));
  context.artifactLoopFilter = "1";
  vm.runInContext("renderArtifactLineage()", context);
  assert.ok(output.innerHTML.includes("result-89.json"));
  assert.ok(!output.innerHTML.includes("result-0.json"));
  context.currentArtifacts = [{ name: "new-run.json", path: "new-run.json", loop_index: 0, agent: "bo_agent", attempt_index: 1 }];
  vm.runInContext("renderArtifactLineage()", context);
  assert.ok(output.innerHTML.includes("new-run.json"));
  assert.equal(context.artifactLoopFilter, "");
});

test("live loop archive renders saved execution files without current-session telemetry", () => {
  const context = vm.createContext({ escapeHtml: text => String(text).replaceAll("<", "&lt;") });
  vm.runInContext(body("web/static/planning.js", "renderLoopArtifactHistory"), context);
  const html = context.renderLoopArtifactHistory({
    executions: [{ execution_id: "past", agent: "manipulation_agent", attempt_index: 2, status: "failed", archive_status: "complete" }],
    artifacts: [{ execution_id: "past", name: "policy_tracking.png", preview_kind: "image", url: "/api/runs/old/artifact-file/past.png" }],
  });
  assert.ok(html.includes("manipulation_agent") && html.includes("failed"));
  assert.ok(html.includes("/api/runs/old/artifact-file/past.png"));
  assert.ok(!html.includes("/ws/lerobot"));
  assert.ok(context.renderLoopArtifactHistory({ executions: [], artifacts: [] }).includes("보관"));
});
