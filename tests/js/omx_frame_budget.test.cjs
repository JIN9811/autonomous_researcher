const test = require('node:test');
const assert = require('node:assert/strict');
const {frameBudget} = require('../../web/frontend/omx_telemetry_viewer/src/frame_budget.cjs');

test('pose draws at most 15fps and never when hidden', () => {
  let last = -Infinity, count = 0;
  for (let frame = 0; frame < 120; frame++) {
    const tick = frameBudget(frame * 1000 / 120, last, true);
    if (tick) { count++; last = tick.timestamp; }
  }
  assert.equal(count, 15);
  assert.equal(frameBudget(10000, last, false), null);
});
test('15fps interpolation retains the original time-based response', () => {
  const tick = frameBudget(1000 / 15, 0, true);
  assert.ok(Math.abs(tick.alpha - (1 - 0.72 ** 4)) < 1e-10);
  assert.ok(Number.isFinite(frameBudget(0, -Infinity, true).alpha));
});
