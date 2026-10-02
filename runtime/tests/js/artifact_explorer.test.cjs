const test = require('node:test');
const assert = require('node:assert/strict');
let api = {};
try { api = require('../../web/static/artifact_explorer.js'); } catch (e) { if(e.code !== 'MODULE_NOT_FOUND') throw e; }
const files = [
  {run_id:'one',path:'runtime/loops/loop-000001/analysis_agent/attempt-000001/files/a.csv',agent:'analysis_agent',loop_index:0},
  {run_id:'one',path:'runtime/loops/loop-000002/analysis_agent/attempt-000001/files/b.csv',agent:'analysis_agent',loop_index:1},
  {run_id:'two',path:'other.csv',agent:'analysis_agent',loop_index:0},
  {run_id:'one',path:'legacy.csv',agent:null,loop_index:null},
];
test('live artifact history remains visible before the current cycle produces graphs',()=>{
  const explorer=new api.Explorer({addEventListener(){}});explorer.render=()=>{};
  explorer.update({run:'one',loop:2,agent:'analysis',includeHistory:true,files,label:x=>x});
  assert.equal(explorer.scope.loop,'all');
  assert.deepEqual(explorer.visible(),[files[0],files[1]]);
  explorer.scope.loop='0';explorer.update(explorer.context);
  assert.equal(explorer.scope.loop,'0');
});
test('run, loop and agent filters do not mix history or unowned legacy files',()=>{
  assert.deepEqual(api.filterFiles?.(files,{run:'one',loop:'0',agent:'analysis'}),[files[0]]);
  assert.deepEqual(api.filterFiles?.(files,{run:'one',loop:'all',agent:'all'}),[files[0],files[1],files[3]]);
});
test('folder tree retains actual hierarchy and same-named files remain distinct',()=>{
  const tree=api.folders?.([{path:'a/files/data.csv'},{path:'b/files/data.csv'}]);
  assert.deepEqual(tree?.map(x=>x.path),['','a','a/files','b','b/files']);
});
test('display name removes archive hash only, without changing source path',()=>{
  assert.equal(api.displayName?.({name:'a'.repeat(64)+'_force_displacement.csv'}),'force displacement.csv');
});
test('CSV preview supports quoted separators, multiline cells and escaped quotes',()=>{
  assert.deepEqual(api.csvRows?.('x,y\r\n"a,b","two\nlines"\r\n"a""b",3'),[['x','y'],['a,b','two\nlines'],['a"b','3']]);
});
test('preview URLs must use existing local artifact-serving routes',()=>{
  assert.equal(api.safeUrl?.('javascript:alert(1)'), '');
  assert.equal(api.safeUrl?.('https://other.example/data.csv'), '');
  assert.equal(api.safeUrl?.('/api/runs/one/artifact-file/a.csv'), '/api/runs/one/artifact-file/a.csv');
});
test('agent and loop changes reset explorer scope, but polling preserves manual navigation',()=>{
  const explorer=new api.Explorer({addEventListener(){}});
  explorer.render=()=>{};
  const context={run:'one',loop:0,agent:'design',files:[],label:x=>x};
  explorer.update(context);
  assert.deepEqual(explorer.scope,{run:'one',loop:'0',agent:'design'});
  explorer.scope.agent='all';explorer.folder='runtime';
  explorer.update(context);
  assert.equal(explorer.scope.agent,'all');assert.equal(explorer.folder,'runtime');
  explorer.update({...context,agent:'analysis'});
  assert.equal(explorer.scope.agent,'analysis');assert.equal(explorer.folder,null);
  explorer.update({...context,agent:'analysis',loop:1});
  assert.equal(explorer.scope.loop,'1');
});
test('conversation references join the index without duplicate URLs or invented loop ownership',()=>{
  const indexed=[{run_id:'r',path:'a.png',url:'/api/runs/r/artifact-file/a.png'}];
  const refs=[{run_id:'r',loop_index:0,role:'analysis_ai',fem_artifacts:{contour_url:indexed[0].url,report_url:'/api/planning/artifacts/r/s/report.json'}},
    {run_id:'r',role:'bo_ai',bo_result:{recommendation:{x:1}}}];
  const merged=api.mergeReferences?.(indexed,refs);
  assert.equal(merged?.length,3);
  assert.equal(merged?.[1].agent,'analysis');
  assert.equal(merged?.[2].loop_index,null);
});
