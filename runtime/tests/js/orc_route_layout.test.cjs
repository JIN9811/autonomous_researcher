const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

test("compact orchestration card separates EQP below ORC without changing the source graph", () => {
  const graph = { id: "atr_closed_loop", nodes: [
    { id: "orchestrator", position: { x: 1536, y: 240 } },
    { id: "equipment", position: { x: 1616, y: 384 } },
    { id: "analysis", position: { x: 1280, y: 592 } },
  ], edges: [{ source: "orchestrator", target: "equipment" }] };
  const before = JSON.stringify(graph);
  const context = vm.createContext({ liveGraphPayload: { graph }, LIVE_RUNTIME_MAP_GEOMETRY: null });
  const source = fs.readFileSync("web/static/planning.js", "utf8");
  const start = source.indexOf("function orcRuntimeGraphSource(");
  vm.runInContext(source.slice(start, source.indexOf("\n}", start) + 2), context);
  const projected = context.orcRuntimeGraphSource();
  const equipment = projected.nodes.find(node => node.id === "equipment");
  const shift = equipment.position.y - graph.nodes[1].position.y;
  assert.ok(shift >= 32 && shift <= 64, "EQP needs a small downward separation in the compact card");
  assert.equal(equipment.position.x, graph.nodes[1].position.x);
  assert.deepEqual(projected.nodes[0], graph.nodes[0]);
  assert.deepEqual(projected.nodes[2], graph.nodes[2]);
  assert.deepEqual(projected.edges, graph.edges);
  assert.equal(JSON.stringify(graph), before);
  assert.equal(context.orcRuntimeGraphSource().nodes[1].position.y, equipment.position.y, "polling must not accumulate the offset");
});
