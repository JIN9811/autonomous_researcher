from pathlib import Path
import subprocess


def test_field_mapping_range_and_deformation_use_actual_values():
    source = Path('web/static/cae_fields.js').resolve()
    script = r'''
const assert = require('assert');
const view = require(process.argv[1]);
assert.equal(typeof view.scalars, 'function', 'numeric viewer contract required');
const field = {values: [[3,4,0],[0,0,2]], components: ['x','y','z']};
assert.deepStrictEqual(view.scalars(field,-1), [5,2]);
assert.deepStrictEqual(view.scalars(field,0), [3,0]);
assert.deepStrictEqual(view.colorRange([[0,1],[2,8]]), [0,8]);
assert.throws(()=>view.scalars({values:[[null]]},0));
assert.throws(()=>view.scalars(field,8));
const selected = {step: 2, time: 1, fields: {S:{units:'MPa',association:'point',components:['XX']}}};
assert.equal(view.matchFrame([{step:1,time:1},selected], selected), selected);
assert.equal(view.matchFrame([{step:1,time:1}], selected), undefined);
assert.throws(()=>view.compatibleField(selected.fields.S, {units:'Pa',association:'point',components:['XX']}));
assert.throws(()=>view.compatibleField(selected.fields.S, {units:'MPa',association:'cell',components:['XX']}));
assert.throws(()=>view.compatibleField(selected.fields.S, {units:'MPa',association:'point',components:['YY']}));
view.compatibleField(selected.fields.S, selected.fields.S);
assert.throws(()=>view.scalars({values:[[1,2,3,4,5,6]]},-1), /Tensor/);
assert.equal(view.fieldLabel('S',{components:['SXX','SYY'],units:'MPa'},1),'S · SYY [MPa]');
'''
    completed = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
