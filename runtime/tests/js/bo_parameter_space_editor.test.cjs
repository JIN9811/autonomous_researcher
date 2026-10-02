const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function element() {
  return {value: '', textContent: '', hidden: true, handlers: {},
    addEventListener(name, fn) { this.handlers[name] = fn; },
    setAttribute() {}, setCustomValidity(value) { this.error = value; },
    input(value) { this.value = value; this.handlers.input(); }};
}
function fixture() {
  const context = vm.createContext({window: {}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../web/static/bo_parameter_space_editor.js'), 'utf8'), context);
  const jsonInput = element(), error = element();
  const fields = {cell_size_mm: [element(), element()], wall_thickness_mm: [element(), element()]};
  const editor = context.window.BOParameterSpaceEditor.create({jsonInput, fields, error});
  const space = {cell_size_mm: [5, 10], wall_thickness_mm: [0.6, 1.2], geometry_type: ['gyroid'], skin_thickness_mm: [0.8]};
  editor.load(space);
  return {editor, jsonInput, fields, error, space};
}
test('load and reset project both numeric bounds', () => {
  const {editor, fields, space} = fixture();
  assert.equal(fields.cell_size_mm[0].value, '5');
  fields.cell_size_mm[0].input('6.25');
  editor.load(space);
  assert.equal(fields.cell_size_mm[0].value, '5');
});
test('numeric edits update JSON without removing advanced values', () => {
  const {editor, jsonInput, fields} = fixture();
  fields.wall_thickness_mm[0].input('0.725');
  assert.equal(editor.read().wall_thickness_mm[0], 0.725);
  assert.deepEqual(JSON.parse(jsonInput.value).skin_thickness_mm, [0.8]);
});
test('JSON edits update numeric controls and serialize the same values', () => {
  const {editor, jsonInput, fields, space} = fixture();
  jsonInput.input(JSON.stringify({...space, cell_size_mm: [5.25, 9.75]}));
  assert.equal(fields.cell_size_mm[1].value, '9.75');
  assert.equal(editor.read().cell_size_mm[0], 5.25);
});
test('incomplete numbers and inverted bounds block stale saves, then recover', () => {
  const {editor, fields, error} = fixture();
  for (const value of ['', '0', '-1', '11']) {
    fields.cell_size_mm[0].input(value);
    assert.throws(() => editor.read());
    assert.equal(error.hidden, false);
  }
  fields.cell_size_mm[0].input('6');
  assert.equal(editor.read().cell_size_mm[0], 6);
  assert.equal(error.hidden, true);
});
test('invalid JSON is retained and cannot be overwritten by numeric edits', () => {
  const {editor, jsonInput, fields, space} = fixture();
  jsonInput.input('{broken');
  fields.cell_size_mm[0].input('6');
  assert.equal(jsonInput.value, '{broken');
  assert.throws(() => editor.read());
  jsonInput.input(JSON.stringify(space));
  assert.equal(fields.cell_size_mm[0].value, '5');
  assert.equal(editor.read().cell_size_mm[0], 5);
});
test('reject malformed JSON shapes and nonnumeric ranges', () => {
  const {editor, jsonInput, space} = fixture();
  for (const bad of [[], null, {}, {...space, cell_size_mm: ['5', 10]}, {...space, wall_thickness_mm: [1.2, 0.6]}]) {
    jsonInput.input(JSON.stringify(bad));
    assert.throws(() => editor.read());
  }
});
test('repairing one invalid JSON range from the form preserves the other new range', () => {
  const {editor, jsonInput, fields, space} = fixture();
  jsonInput.input(JSON.stringify({...space, cell_size_mm: [6, 9], wall_thickness_mm: [0, 1.2]}));
  assert.throws(() => editor.read());
  fields.wall_thickness_mm[0].input('0.7');
  assert.deepEqual(JSON.parse(jsonInput.value).cell_size_mm, [6, 9]);
  assert.equal(editor.read().wall_thickness_mm[0], 0.7);
});
