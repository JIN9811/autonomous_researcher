const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/run_review.js','utf8');
const functions = source.slice(source.indexOf('  function navigationTarget('), source.indexOf('  async function loadPoint('));
const context = {};
vm.runInNewContext(functions, context);
const points = [{id:'a',cycle:0},{id:'b',cycle:0},{id:'c',cycle:2},{id:'d',cycle:2},{id:'e',cycle:4}];
const target = (key, point='d', list=points) => JSON.parse(JSON.stringify(context.navigationTarget(key,list,point)));
test('left/right traverse records within the session, stopping at either end', () => {
  assert.deepEqual(target('ArrowLeft'),{point:'c'});
  assert.deepEqual(target('ArrowRight'),{point:'e'});
  assert.equal(target('ArrowLeft','a'),null);
  assert.equal(target('ArrowRight','e'),null);
  assert.equal(target('ArrowRight','missing'),null);
  assert.equal(target('ArrowRight','a',[]),null);
});
test('a single session and cycle still supports left/right through all 79 records', () => {
  const records=Array.from({length:79},(_,i)=>({id:String(i+1).padStart(6,'0'),cycle:0}));
  for(let i=0;i<78;i++) assert.deepEqual(target('ArrowRight',records[i].id,records),{point:records[i+1].id});
  assert.deepEqual(target('ArrowLeft','000079',records),{point:'000078'});
  assert.equal(target('ArrowDown','000001',records),null);
});
test('up/down skip events within a cycle and handle gaps', () => {
  assert.deepEqual(target('ArrowUp'),{point:'a'});
  assert.deepEqual(target('ArrowDown'),{point:'e'});
  assert.deepEqual(target('ArrowDown','a'),{point:'c'});
  assert.equal(target('ArrowUp','a'),null);
  assert.equal(target('ArrowDown','e'),null);
  assert.equal(target('ArrowDown','d',[]),null);
});
test('input/select editing, modifiers, and held keys do not navigate', () => {
  for(const extra of [{repeat:true},{ctrlKey:true},{altKey:true},{metaKey:true},{shiftKey:true},{defaultPrevented:true},
    {target:{isContentEditable:true}},{target:{closest:()=>({})}}]) {
    // No document in this context: any attempted navigation would throw.
    context.navigateReplay({key:'ArrowRight',...extra});
  }
});
