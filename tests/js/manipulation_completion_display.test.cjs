const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
test('completion highlighting requires running execution and preserves explicit evidence',()=>{
  const source=fs.readFileSync('web/frontend/omx_telemetry_viewer/src/index.js','utf8');
  const start=source.indexOf('function applyCompletionVerification(completion)');
  const row={dataset:{atrRuntimeStep:'release'},querySelector:()=>({})};
  const context=vm.createContext({runtime:{runtimeView:{execution:{runtime_status:'not_started'}}},document:{querySelectorAll:()=>[row]},setNodeTextIfChanged:()=>{}});
  vm.runInContext(source.slice(start,source.indexOf('\n}',start)+2),context);
  const completion={current_step:'release',steps:[{id:'release',status:'waiting'}]};
  for(const status of ['not_started','idle','completed','failed']){
    context.runtime.runtimeView.execution.runtime_status=status;
    context.applyCompletionVerification(completion);
    assert.equal(row.dataset.status,'waiting');
  }
  context.runtime.runtimeView.execution.runtime_status='running';
  context.applyCompletionVerification(completion);
  assert.equal(row.dataset.status,'active');
  completion.steps[0].status='complete';
  context.applyCompletionVerification(completion);
  assert.equal(row.dataset.status,'complete');
});
