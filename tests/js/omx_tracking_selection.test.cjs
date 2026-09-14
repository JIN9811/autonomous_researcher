const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/frontend/omx_telemetry_viewer/src/index.js', 'utf8');
test('tracking mount starts at Gripper, keeps valid user changes and falls back to Gripper', () => {
  const select = {value:'', dataset:{}, addEventListener(_name, callback) {this.change = callback;}};
  const context = {document:{querySelectorAll:()=>[select]}, scheduleChartRender:()=>{}, JOINT_NAMES:['Joint1','Joint2','Gripper']};
  vm.createContext(context);
  const runtime = source.slice(source.indexOf('const runtime ='), source.indexOf('\nfunction parseVector'));
  const bind = source.slice(source.indexOf('function bindJointSelectors()'), source.indexOf('function bindPoseFitButtons()'));
  vm.runInContext(runtime + bind + '\nbindJointSelectors();', context);
  assert.equal(select.value, 'Gripper');
  select.value = 'Joint2'; select.change();
  vm.runInContext('bindJointSelectors()', context);
  assert.equal(select.value, 'Joint2');
  select.value = 'invalid'; select.change();
  assert.equal(select.value, 'Gripper');
});
