const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/lerobot.js', 'utf8');
function harness() {
  const ctx = {
    RTC_POLICY_TYPES: new Set(), RTC_DEFAULT_ENABLED_POLICY_TYPES: new Set(),
    MANIPULATION_TASK_PRESETS: {transfer_to_utm: {instruction: 'move'}},
    DEFAULT_PI05_ROLLOUT_TASK: 'move', rolloutProfileLoaded: false,
    selectedManipulationTaskId: () => 'transfer_to_utm',
    selectedRolloutPolicyType: () => 'smolvla', selectedManipulationPolicyType: () => 'smolvla',
    rolloutPolicyFields: () => ({}), manipulationPolicyFields: () => ({}),
    boolValue: el => !!el?.checked, numberValue: (el, def) => Number(el?.value) || def,
    parseObservation: () => ({}), parseJsonText: () => ({}),
    setInputValue: (el, value) => {if (el) el.value = value ?? '';},
    setCheckboxValue: (el, value) => {if (el) el.checked = !!value;},
    syncRolloutPolicyOptions: () => {}, syncManipulationPolicyOptions: () => {},
    defaultManipulationTaskProfile: () => ({rollout_linear_enabled: false}),
  };
  for (const name of source.match(/\b\w+(?:Input|Select)\b/g)) ctx[name] = {value: '', checked: false};
  vm.createContext(ctx);
  for (const name of ['currentRolloutProfile', 'currentManipulationTaskProfile', 'applyRolloutProfile', 'applyManipulationTaskProfile']) {
    const start = source.indexOf(`function ${name}(`);
    const end = source.indexOf('\n}', start) + 2;
    vm.runInContext(source.slice(start, end), ctx);
  }
  return ctx;
}
test('standalone and agent choices round trip independently, OFF by default', () => {
  const ctx = harness();
  assert.equal(ctx.currentRolloutProfile().rollout_linear_enabled, false);
  assert.equal(ctx.currentManipulationTaskProfile().rollout_linear_enabled, false);
  ctx.applyManipulationTaskProfile('transfer_to_utm', {rollout_linear_enabled: true});
  assert.equal(ctx.currentManipulationTaskProfile().rollout_linear_enabled, true);
  assert.equal(ctx.currentRolloutProfile().rollout_linear_enabled, false);
  ctx.applyRolloutProfile({rollout_linear_enabled: true}, true);
  assert.equal(ctx.currentRolloutProfile().rollout_linear_enabled, true);
  ctx.applyManipulationTaskProfile('transfer_to_utm', {rollout_linear_enabled: false});
  assert.equal(ctx.currentManipulationTaskProfile().rollout_linear_enabled, false);
});
test('both rendered checkboxes are initially unchecked', () => {
  const html = fs.readFileSync('web/templates/lerobot.html', 'utf8');
  for (const id of ['lerobot-rollout-linear-input', 'lerobot-manipulation-linear-input']) {
    const tag = html.match(new RegExp(`<input[^>]*id="${id}"[^>]*>`))[0];
    assert.doesNotMatch(tag, /checked/);
  }
});

test('standalone and agent output rates round trip independently', () => {
  const ctx = harness();
  ctx.applyRolloutProfile({rollout_linear_enabled: true, rollout_linear_hz: 60}, true);
  ctx.applyManipulationTaskProfile('transfer_to_utm', {rollout_linear_enabled: false, rollout_linear_hz: 100});
  assert.equal(ctx.currentRolloutProfile().rollout_linear_hz, 60);
  assert.equal(ctx.currentManipulationTaskProfile().rollout_linear_hz, 100);
  ctx.applyManipulationTaskProfile('transfer_to_utm', {rollout_linear_enabled: true, rollout_linear_hz: 50});
  assert.equal(ctx.currentManipulationTaskProfile().rollout_linear_hz, 50);
  assert.equal(ctx.currentRolloutProfile().rollout_linear_hz, 60);
});

test('enabling RTC after loading empty settings sends the requested defaults without auto-enabling', () => {
  const ctx = harness();
  ctx.RTC_POLICY_TYPES.add('smolvla');
  ctx.applyRolloutProfile({}, true);
  ctx.applyManipulationTaskProfile('transfer_to_utm', {});
  assert.equal(ctx.rolloutRtcEnabledInput.checked, false);
  assert.equal(ctx.manipulationRtcEnabledInput.checked, false);
  ctx.rolloutRtcEnabledInput.checked = true;
  ctx.manipulationRtcEnabledInput.checked = true;
  for (const profile of [ctx.currentRolloutProfile(), ctx.currentManipulationTaskProfile()]) {
    assert.equal(profile.rollout_rtc_execution_horizon, 10);
    assert.equal(profile.rollout_rtc_max_guidance_weight, 10);
    assert.equal(profile.rollout_action_queue_size_to_get_new_actions, 60);
  }
});
