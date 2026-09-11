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
  // Document-only geometry: retain the GUI topology with generous spacing.
  // README uses a horizontal viewport rather than shrinking the whole map.
  const width = 224, height = 84;
  runtimeMapGeometryOptions = () => ({
    nodeWidth: width, nodeHeight: height, edgeSpacing: 14,
    parallelSpacing: 26, handlePercent: 0.28, outwardOffset: 8,
  });
  graph.nodes.forEach(n => {
    n.position = { x: n.position.x * 1.15, y: n.position.y };
  });
  const normalized = RUNTIME_MAP_GEOMETRY.normalizeNodePositions(graph, {
    grid: 8, nodeWidth: width, nodeHeight: height,
    collisionGapX: 56, collisionGapY: 40,
  });
  const edges = runtimeMapEdges(normalized);
  return {
    nodes: normalized.nodes,
    edges: edges.map(e => ({
      key: e.key, source: e.source.id, target: e.target.id,
      type: runtimeMapEdgeType(e), condition: e.condition,
      conditional: e.runtimeEdgeType === 'logical_transition' && e.metadata.default_transition === false,
      d: runtimeMapEdgePath(e),
    })),
    bounds: {
      width: Math.max(...normalized.nodes.map(n => n.position.x + width)) + 40,
      height: Math.max(...normalized.nodes.map(n => n.position.y + height)) + 64,
    },
    width, height,
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
  logical_transition: ['#315C9B', '', 'Default route'],
  conditional: ['#315C9B', '8 5', 'Conditional route'],
  control_overlay: ['#B26A00', '10 8', 'Guardian / control'],
  device_bridge: ['#397B8C', '6 5', 'Device bridge'],
  evidence_flow: ['#2E7D59', '5 6', 'Evidence'],
  runtime_sidecar: ['#806699', '12 5 3 5', 'Sidecar'],
};
function wrapLabel(label) {
  const lines = [''];
  for (const word of label.split(/\s+/)) {
    const last = lines.length - 1;
    if ((lines[last] + ' ' + word).trim().length > 16 && lines[last]) lines.push(word);
    else lines[last] = (lines[last] + ' ' + word).trim();
  }
  assert(lines.length <= 3, `Label needs review: ${label}`);
  return lines;
}
const width = model.bounds.width;
const height = model.bounds.height + 104;
const markers = Object.entries(palette).map(([type, [color]]) =>
  `<marker id="arrow-${type}" markerWidth="12" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,5 L0,10 L2.6,5 z" fill="${color}"/></marker>`).join('\n');
const edges = [...model.edges].sort((a, b) => Number(a.type === 'logical_transition') - Number(b.type === 'logical_transition')).map(e => {
  const style = e.conditional ? 'conditional' : e.type;
  const [color, dash] = palette[style];
  const primary = e.type === 'logical_transition';
  assert(!/NaN|Infinity/.test(e.d), 'Invalid edge geometry');
  return `<path data-edge="${esc(e.key)}" d="${e.d}" fill="none" stroke="${color}" stroke-width="${primary ? (e.conditional ? 2.7 : 3.6) : 1.8}"${dash ? ` stroke-dasharray="${dash}"` : ''} stroke-linecap="round" opacity="${primary ? 1 : 0.62}" marker-end="url(#arrow-${style})"><title>${esc(e.source)} → ${esc(e.target)} · ${esc(e.condition)}</title></path>`;
}).join('\n');
const nodes = model.nodes.map(n => {
  const label = (n.label || n.id).replace(/ Agent$/, '').replace(/ Plane$/, '');
  const lines = wrapLabel(label);
  const color = n.kind === 'bridge' ? '#397B8C' : n.kind === 'evidence_plane' ? '#2E7D59' : n.kind === 'sidecar' ? '#B26A00' : '#315C9B';
  const fill = n.kind === 'evidence_plane' ? '#E9F7EF' : n.kind === 'sidecar' ? '#FFF1D6' : '#EEF4FF';
  const dashed = n.metadata?.runtime_node === 'sidecar' || ['bridge', 'evidence_plane'].includes(n.kind);
  const text = lines.map((line, i) => `<tspan x="${model.width / 2}" y="${model.height / 2 - (lines.length - 1) * 14 + i * 28}">${esc(line)}</tspan>`).join('');
  return `<g data-node-id="${esc(n.id)}" transform="translate(${n.position.x} ${n.position.y})"><title>${esc(n.label)} · ${esc(n.handler || n.metadata?.plane || n.id)}</title><rect width="${model.width}" height="${model.height}" rx="10" fill="${fill}" stroke="${color}" stroke-width="1.5"${dashed ? ' stroke-dasharray="6 4"' : ''}/><text fill="#172B42" font-size="22" font-weight="400" text-anchor="middle" dominant-baseline="middle">${text}</text></g>`;
}).join('\n');
const legend = Object.entries(palette).map(([type, [color, dash, label]], i) => {
  const x = 52 + (i % 3) * ((width - 104) / 3);
  const y = model.bounds.height + Math.floor(i / 3) * 42;
  return `<g transform="translate(${x} ${y})"><path d="M0 0 H48" stroke="${color}" stroke-width="3"${dash ? ` stroke-dasharray="${dash}"` : ''}/><text x="62" y="7" fill="#365164" font-size="23">${label}</text></g>`;
}).join('\n');
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title description">
<title id="title">Orchestration Route — main GUI runtime map</title>
<desc id="description">Document-styled main GUI LangGraph Runtime Map. ${model.nodes.length} nodes and ${model.edges.length} displayed connections retain the saved graph and GUI edge filtering. Document-only spacing and larger labels use the shared node normalization and Bezier routing. Solid blue routes are defaults; dashed blue routes are conditional; muted overlays show control, device, evidence and sidecar connections. No live status is shown.</desc>
<!-- Regenerate: node docs/assets/readme/export-orchestration-route.cjs -->
<defs>${markers}</defs>
<rect width="100%" height="100%" fill="#ffffff"/>
<g font-family="DejaVu Sans, Arial, sans-serif">${edges}\n${nodes}\n${legend}</g>
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
