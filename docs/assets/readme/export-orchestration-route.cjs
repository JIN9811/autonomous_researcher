/* Documentation-only export of the main GUI's LangGraph Runtime Map.
 * Reuses app.js edge filtering and runtime_graph_geometry.js, without starting
 * the app or evaluating its event handlers, network requests or device code.
 * Run: node docs/assets/readme/export-orchestration-route.cjs [--check]
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '../../..');
const python = process.env.DOCS_PYTHON || path.join(root, '.venv/bin/python');
const graph = JSON.parse(execFileSync(python, ['-c',
  'import json, yaml; from pathlib import Path; print(json.dumps(yaml.safe_load(Path("graphs/configs/atr_closed_loop.yaml").read_text())["graph"]))',
], { cwd: root, encoding: 'utf8' }));
const frontend = fs.readFileSync(path.join(root, 'web/static/app.js'), 'utf8');
const start = frontend.indexOf('const RUNTIME_MAP_EDGE_TYPES =');
const end = frontend.indexOf('function renderRuntimeMapLegend(', start);
assert(start >= 0 && end > start, 'Main GUI graph helper boundary changed; review exporter.');
const context = vm.createContext({ window: {}, graph });
vm.runInContext(fs.readFileSync(path.join(root, 'web/static/runtime_graph_geometry.js'), 'utf8'), context);
vm.runInContext(frontend.slice(start, end), context);
const model = vm.runInContext(`(() => {
  const normalized = RUNTIME_MAP_GEOMETRY.normalizeNodePositions(graph, { grid: 16 });
  const edges = runtimeMapEdges(normalized);
  return {
    nodes: normalized.nodes,
    edges: edges.map(e => ({
      key: e.key, source: e.source.id, target: e.target.id,
      type: runtimeMapEdgeType(e), condition: e.condition,
      d: runtimeMapEdgePath(e),
    })),
    bounds: runtimeMapBounds(normalized.nodes),
    width: RUNTIME_MAP_NODE_WIDTH, height: RUNTIME_MAP_NODE_HEIGHT,
    types: Array.from(RUNTIME_MAP_EDGE_TYPES),
  };
})()`, context);

// Independently check the exported inventory against the GUI's declared filter.
const nodeIds = new Set(graph.nodes.map(n => n.id));
const expectedEdges = new Set(graph.edges.filter(e => model.types.includes(e.metadata?.runtime_edge))
  .filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
  .map(e => `${e.source}->${e.target}:${e.metadata.runtime_edge}:${String(e.condition || e.metadata?.condition || e.metadata?.transition_condition || e.metadata?.overlay_relation || e.metadata?.bridge || e.metadata.runtime_edge).trim()}`));
assert.deepEqual(new Set(model.nodes.map(n => n.id)), nodeIds);
assert.deepEqual(new Set(model.edges.map(e => e.key)), expectedEdges);
for (let i = 0; i < model.nodes.length; i++) {
  const a = model.nodes[i].position;
  for (const n of model.nodes.slice(i + 1)) {
    const b = n.position;
    assert(!(a.x < b.x + model.width && a.x + model.width > b.x &&
      a.y < b.y + model.height && a.y + model.height > b.y), 'Overlapping graph nodes');
  }
}

const esc = s => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const palette = {
  logical_transition: ['#7aa7ff', '', 'Route'],
  control_overlay: ['#f59e0b', '10 8', 'Guardian / control'],
  device_bridge: ['#06b6d4', '6 5', 'Device bridge'],
  evidence_flow: ['#10b981', '5 6', 'Evidence'],
  runtime_sidecar: ['#a855f7', '12 5 3 5', 'Sidecar'],
};
function wrapLabel(label) {
  const lines = [''];
  for (const word of label.split(/\s+/)) {
    const last = lines.length - 1;
    if ((lines[last] + ' ' + word).trim().length > 20 && lines[last]) lines.push(word);
    else lines[last] = (lines[last] + ' ' + word).trim();
  }
  assert(lines.length <= 3, `Label needs review: ${label}`);
  return lines;
}
const width = model.bounds.width;
const height = model.bounds.height + 85;
const markers = Object.entries(palette).map(([type, [color]]) =>
  `<marker id="arrow-${type}" markerWidth="12" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,5 L0,10 L2.6,5 z" fill="${color}"/></marker>`).join('\n');
const edges = model.edges.map(e => {
  const [color, dash] = palette[e.type];
  assert(!/NaN|Infinity/.test(e.d), 'Invalid edge geometry');
  return `<path data-edge="${esc(e.key)}" d="${e.d}" fill="none" stroke="${color}" stroke-width="${e.type === 'logical_transition' ? 2.4 : 2.1}"${dash ? ` stroke-dasharray="${dash}"` : ''} stroke-linecap="round" opacity="0.74" marker-end="url(#arrow-${e.type})"><title>${esc(e.source)} → ${esc(e.target)} · ${esc(e.condition)}</title></path>`;
}).join('\n');
const nodes = model.nodes.map(n => {
  const lines = wrapLabel(n.label || n.id);
  const color = n.kind === 'bridge' ? '#06b6d4' : n.kind === 'evidence_plane' ? '#10b981' : n.kind === 'sidecar' ? '#f59e0b' : '#53647f';
  const dashed = n.metadata?.runtime_node === 'sidecar' || ['bridge', 'evidence_plane'].includes(n.kind);
  const text = lines.map((line, i) => `<tspan x="92" y="${38 - (lines.length - 1) * 11 + i * 22}">${esc(line)}</tspan>`).join('');
  return `<g data-node-id="${esc(n.id)}" transform="translate(${n.position.x} ${n.position.y})"><title>${esc(n.label)} · ${esc(n.handler || n.metadata?.plane || n.id)}</title><rect width="${model.width}" height="${model.height}" rx="17" fill="#09122d" stroke="${color}" stroke-width="1.5"${dashed ? ' stroke-dasharray="6 4"' : ''}/><text fill="#f8fbff" font-size="17" font-weight="600" text-anchor="middle" dominant-baseline="middle">${text}</text></g>`;
}).join('\n');
const legend = Object.entries(palette).map(([type, [color, dash, label]], i) => {
  const x = 70 + i * 355;
  return `<g transform="translate(${x} ${model.bounds.height + 17})"><path d="M0 0 H58" stroke="${color}" stroke-width="3"${dash ? ` stroke-dasharray="${dash}"` : ''}/><text x="72" y="6" fill="#e5edff" font-size="21">${label}</text></g>`;
}).join('\n');
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title description">
<title id="title">Orchestration Route — main GUI runtime map</title>
<desc id="description">Static documentation export of the main GUI's LangGraph Runtime Map. ${model.nodes.length} nodes and ${model.edges.length} displayed connections, using the same saved graph, node normalization, edge filtering and Bezier routing. Colors and dash patterns identify route, control, bridge, evidence and sidecar connections. No live status is shown.</desc>
<!-- Regenerate: node docs/assets/readme/export-orchestration-route.cjs -->
<defs>${markers}<linearGradient id="canvas" x2="1" y2="1"><stop stop-color="#070c1f"/><stop offset="1" stop-color="#0c1c41"/></linearGradient><pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" fill="none" stroke="#60a5fa" stroke-opacity="0.07"/></pattern></defs>
<rect width="100%" height="100%" rx="20" fill="url(#canvas)"/>
<rect width="100%" height="100%" rx="20" fill="url(#grid)"/>
<g font-family="Arial, Helvetica, sans-serif">${edges}\n${nodes}\n${legend}</g>
</svg>
`;
const target = path.join(__dirname, 'orchestration-route.svg');
if (process.argv.includes('--check')) {
  assert.equal(fs.readFileSync(target, 'utf8'), svg, 'Regenerate orchestration-route.svg');
  console.log(`PASS: ${model.nodes.length} nodes, ${model.edges.length} GUI connections; no node overlap; SVG current.`);
} else {
  fs.writeFileSync(target, svg);
  console.log(`Exported ${path.relative(root, target)} (${model.nodes.length} nodes, ${model.edges.length} connections).`);
}
