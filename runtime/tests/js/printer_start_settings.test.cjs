const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/printer.js', 'utf8');
function read(prime, valid = true, enabled = true, xyScale = '100') {
  const field = value => ({value, checkValidity: () => valid, reportValidity() {}});
  const xyInput = {value: xyScale, checkValidity: () => Number(xyScale) >= 1 && Number(xyScale) <= 100, reportValidity() {}};
  const ctx = vm.createContext({xySpeedScaleInput: xyInput, startPointPrimeEnabledInput: {checked: enabled}, earlyLayerZSpeedLimitInput: {checked: enabled}, earlyLayerSpeedLimitInput: {checked: enabled}, startPointPrimeInput: field(prime), earlyLayerSpeedInput: field('35'), earlyLayerZSpeedInput: field('2')});
  const start = source.indexOf('function readPrintStartSettings(');
  vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), ctx);
  return JSON.parse(JSON.stringify(ctx.readPrintStartSettings()));
}
test('saved form payload preserves zero prime and custom early-layer limits', () => {
  assert.deepEqual(read('0'), {xy_speed_scale_percent: 100, start_point_prime_enabled: true, early_layer_z_speed_limit_enabled: true, early_layer_speed_limit_enabled: true, start_point_prime_mm: 0, early_layer_speed_mm_s: 35, early_layer_z_speed_mm_s: 2});
  assert.equal(read('0.03').start_point_prime_mm, 0.03);
  assert.equal(read('0.4').start_point_prime_mm, 0.4);
});
test('unchecked options preserve their editable numeric values in the save payload', () => {
  assert.deepEqual(read('0.03', true, false), {xy_speed_scale_percent: 100, start_point_prime_enabled: false, early_layer_z_speed_limit_enabled: false, early_layer_speed_limit_enabled: false, start_point_prime_mm: 0.03, early_layer_speed_mm_s: 35, early_layer_z_speed_mm_s: 2});
});
test('XY scale accepts the inclusive range and rejects invalid save values', () => {
  for (const value of ['1', '40.5', '80', '100']) {
    assert.equal(read('0.1', true, true, value).xy_speed_scale_percent, Number(value));
  }
  for (const value of ['', '0', '100.1', 'Infinity', 'NaN']) {
    assert.throws(() => read('0.1', true, true, value), /xy_speed_scale_percent/);
  }
});
test('empty, nonfinite and out-of-range form values cannot be submitted', () => {
  assert.throws(() => read(''), /start_point_prime_mm/);
  assert.throws(() => read('Infinity'), /start_point_prime_mm/);
  assert.throws(() => read('-0.1', false), /start_point_prime_mm/);
});

test('stale server cannot report a successful save and switch an unchecked cap back on', async () => {
  const requested = {start_point_prime_mm: 0.4, early_layer_speed_limit_enabled: false, early_layer_speed_mm_s: 35, early_layer_z_speed_mm_s: 2};
  const returned = {...requested};
  delete returned.early_layer_speed_limit_enabled;
  let filled = false;
  const logs = [];
  const ctx = vm.createContext({btnSave: {}, statusDot: {}, setBusy() {}, setDotState() {},
    readProfile: () => requested, apiJson: async () => ({profile: returned}),
    fillProfile: () => {filled = true;}, renderConfig() {}, refreshStatus: async () => {},
    writeLog: value => logs.push(value)});
  const start = source.indexOf('async function saveProfile(');
  vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), ctx);
  await ctx.saveProfile();
  assert.equal(filled, false);
  assert.equal(logs.at(-1).ok, false);
  assert.match(logs.at(-1).error, /server.*restart/i);
});
