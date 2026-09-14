const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js', 'utf8');
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} exists`);
  const end = source.indexOf('\nfunction ', start + 1);
  const asyncEnd = source.indexOf('\nasync function ', start + 1);
  return source.slice(start, Math.min(...[end, asyncEnd].filter(x => x >= 0)));
}
test('LHS hydration selects newest current-run figure without a BO result', async () => {
  let incoming = {run_id: 'run-a', step: 1, artifacts: {png_url: '/initial.png'}, initial_design: {points: []}};
  const context = {window: {LHSDesignVisualization: {isValid: p => !!p?.initial_design}},
    liveLhsVisualization: null, liveBoVisualization: null,
    liveCurrentRunId: () => 'run-a', invalidateLiveCenterRender: () => {},
    currentRunBoVisualization: () => null, updateLiveBoVisualizationCards: () => false,
    fetch: async () => ({ok: true, json: async () => ({state: {run_id: 'run-a'}, recent_lhs_visualization: incoming})})};
  vm.createContext(context);
  vm.runInContext(extract('updateLiveLhsVisualization') + '\n' + extract('latestBoInitialDesign') + '\nasync ' + extract('hydrateLiveBoVisualization'), context);
  await context.hydrateLiveBoVisualization();
  const report = {state: {run_id: 'run-a', run_metadata: {}}};
  assert.equal(context.latestBoInitialDesign(report).visualization.artifacts.png_url, '/initial.png');
  incoming = {...incoming, step: 2, artifacts: {png_url: '/second.png'}};
  await context.hydrateLiveBoVisualization();
  assert.equal(context.latestBoInitialDesign(report).visualization.step, 2);
  context.updateLiveLhsVisualization({...incoming, step: 1});
  assert.equal(context.latestBoInitialDesign(report).visualization.step, 2);
  context.updateLiveLhsVisualization({...incoming, run_id: 'other'});
  assert.equal(context.latestBoInitialDesign(report).visualization.run_id, 'run-a');
  assert.equal(context.latestBoInitialDesign({state: {run_id: 'other', run_metadata: {}}}), null);
});
