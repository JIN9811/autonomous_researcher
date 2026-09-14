const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('agents/bo/frontend/live_report.js', 'utf8');
function model() {
  const context = {window: {}};
  vm.runInNewContext(source, context);
  return context.window.AX4LABBOUI.createPlotHistory();
}
function artifact(step, kind = 'posterior', run = 'run-a') {
  const name = kind === 'posterior' ? `${run}_bo_step_${String(step).padStart(3, '0')}_posterior.png` : `${run}_lhs_design_step_${String(step).padStart(3, '0')}.png`;
  return {run_id: run, name, path: `runtime/bo/${name}`, url: `/api/runs/${run}/artifact-file/runtime/bo/${name}`};
}
test('independent, bounded history sorted numerically; archived duplicates and foreign runs excluded', () => {
  const h = model();
  h.reset('run-a');
  h.accept([artifact(10), artifact(2), artifact(2), artifact(1, 'lhs'), artifact(3, 'lhs'), artifact(99, 'posterior', 'other')]);
  assert.equal(h.current('posterior').step, 10);
  assert.equal(h.move('posterior', -1), true);
  assert.equal(h.current('posterior').step, 2);
  assert.equal(h.move('posterior', -1), false);
  assert.equal(h.current('lhs').step, 3);
  assert.equal(h.move('lhs', -1), true);
  assert.equal(h.current('lhs').step, 1);
  assert.equal(h.status('posterior').total, 2);
});
test('new steps return to latest; unchanged refresh preserves browsing and new run clears history', () => {
  const h = model();
  h.reset('run-a');
  h.accept([artifact(1), artifact(2)]);
  h.move('posterior', -1);
  h.accept([artifact(1), artifact(2)]);
  assert.equal(h.current('posterior').step, 1);
  h.accept([artifact(1), artifact(2), artifact(3)]);
  assert.equal(h.current('posterior').step, 3);
  h.accept([artifact(4)]);
  assert.equal(h.current('posterior').step, 4);
  h.reset('run-b');
  assert.equal(h.current('posterior'), null);
  assert.equal(h.status('lhs').total, 0);
  assert.equal(h.move('posterior', -1), false);
});
