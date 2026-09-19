const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js', 'utf8');
function setup() {
  const context = vm.createContext({window: {}, Set, WeakMap, Math});
  const start = source.indexOf('const generatedSpecimenAttention =');
  vm.runInContext(source.slice(start, source.indexOf('function renderDesignCandidateCards(', start)), context);
  return context;
}
function grid(id = 's1') {
  return {clientWidth: 300, scrollWidth: 1200, scrollLeft: 0, isConnected: true, id,
    querySelector() { return {dataset: {generatedSpecimenId: this.id}}; },
    addEventListener(_, callback) { this.scrolled = callback; }};
}
test('new specimen gets one horizontal attention, refresh respects manual scroll', () => {
  const ctx = setup(), node = grid(), root = {querySelector: () => node};
  ctx.attendLatestGeneratedSpecimen(root, 'run');
  assert.equal(node.scrollLeft, 900);
  node.scrollLeft = 120; node.scrolled();
  ctx.attendLatestGeneratedSpecimen(root, 'run');
  assert.equal(node.scrollLeft, 120);
  node.id = 's2'; node.scrollWidth = 1500;
  ctx.attendLatestGeneratedSpecimen(root, 'run');
  assert.equal(node.scrollLeft, 1200);
});
test('agent switch restores position, next run receives its own attention', () => {
  const ctx = setup(), first = grid();
  ctx.attendLatestGeneratedSpecimen({querySelector: () => first}, 'r1');
  first.scrollLeft = 90; first.scrolled();
  const remounted = grid();
  ctx.attendLatestGeneratedSpecimen({querySelector: () => remounted}, 'r1');
  assert.equal(remounted.scrollLeft, 90);
  ctx.attendLatestGeneratedSpecimen({querySelector: () => remounted}, 'r2');
  assert.equal(remounted.scrollLeft, 900);
});
test('hidden card does not consume attention and Replay remains read-only', () => {
  const ctx = setup(), node = grid();
  node.clientWidth = 0;
  ctx.attendLatestGeneratedSpecimen({querySelector: () => node}, 'run');
  assert.equal(node.scrollLeft, 0);
  node.clientWidth = 300;
  ctx.attendLatestGeneratedSpecimen({querySelector: () => node}, 'run');
  assert.equal(node.scrollLeft, 900);
  ctx.window.AX4LABReplay = {};
  node.id = 's2'; node.scrollLeft = 0;
  ctx.attendLatestGeneratedSpecimen({querySelector: () => node}, 'run');
  assert.equal(node.scrollLeft, 0);
});
test('Run label has its own row above status and clock', () => {
  const css = fs.readFileSync('web/static/styles.css', 'utf8');
  const end = css.slice(css.indexOf('/* Keep the day/hour clock'));
  assert.match(end, /\.mission-status-run \{[^}]*display: grid !important/);
  assert.match(end, /::before \{[^}]*grid-column: 1 \/ -1 !important;[^}]*grid-row: 1 !important/);
  for (const id of ['planning-run-detail', 'live-runtime-clock']) {
    assert.match(end, new RegExp(`#${id} \\{[^}]*grid-row: 2 !important`));
  }
});

test('archived constraint and SEA mass evidence loads once per run and survives card redraw', async () => {
  const files = [
    {path:'planning/s6/experiment_spec.json',url:'/spec'},
    {path:'analysis/s6/analysis_report.json',url:'/analysis'},
  ];
  const payloads = {
    '/spec':{specimen_id:'s6',candidate_id:'c6',design_evaluation:{selection_evaluation:{constraint_margins:[{constraint:'size',limit:30}]}}},
    '/analysis':{specimen_geometry:{mass_g:12.36,mass_source:'slicer'},utm_curve:new Array(1000).fill(1)},
  };
  let fetches = 0;
  const ctx = vm.createContext({window:{},liveRunArtifacts:files,liveSelectedAgent:'design',liveLastSession:{},
    liveDesignEvidenceCache:{runId:'',records:{},fetched:new Set(),pending:false},
    invalidateLiveCenterRender(){},renderLiveRuntime(){},
    fetch:async url => {fetches++; return {ok:true,json:async()=>payloads[url]};},
  });
  const start = source.indexOf('function designArchivedSpecimenEvidence(');
  vm.runInContext(source.slice(start, source.indexOf('\n}',start)+2),ctx);
  ctx.designArchivedSpecimenEvidence({state:{run_id:'run'}});
  await new Promise(setImmediate);
  const records = ctx.designArchivedSpecimenEvidence({state:{run_id:'run'}});
  assert.equal(records[0].specimen_geometry.mass_g,12.36);
  assert.equal(records[0].design_evaluation.selection_evaluation.constraint_margins[0].limit,30);
  assert.equal(records[0].utm_curve,undefined);
  await new Promise(setImmediate);
  assert.equal(fetches,2);
  ctx.window.AX4LABReplay = {};
  assert.equal(ctx.designArchivedSpecimenEvidence({state:{run_id:'other'}}).length,0);
});
