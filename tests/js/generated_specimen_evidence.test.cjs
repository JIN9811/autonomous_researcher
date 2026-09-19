const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js','utf8');
const inject = (ctx, name) => {
  const start = source.indexOf(`function ${name}(`);
  vm.runInContext(source.slice(start, source.indexOf('\n}',start)+2), ctx);
};
const number = value => value == null || value === '' ? null : Number.isFinite(Number(value)) ? Number(value) : null;

test('one fixed set of fields before and after generation, without design proxy values', () => {
  const ctx = vm.createContext({dashboardFiniteNumber:number,escapeHtml:String});
  inject(ctx,'renderDesignSpecimenMetricStrip');
  const before = ctx.renderDesignSpecimenMetricStrip({cell_size_mm:7,wall_thickness_mm:0.8,
    expected_mass_g:999,expected_print_time_min:888,expected_objective_proxy_score:0.9});
  const after = ctx.renderDesignSpecimenMetricStrip({__actual_specimen:true,cell_size_mm:7,wall_thickness_mm:0.8,
    stl_path:'part.stl',gcode_path:'part.gcode.3mf',design_evaluation:{validity:{status:'pass'}},
    specimen_geometry:{mass_g:14.57,mass_source:'slicer'},duration_evidence:{source:'slicer',duration_min:126.6167},
    performance_evidence:{value:5.7227,unit:'J/g'}});
  const labels = html => [...html.matchAll(/<b>(.*?)<\/b>/g)].map(match=>match[1]);
  assert.deepEqual(labels(before),labels(after));
  assert.equal(labels(after).length,8);
  assert.doesNotMatch(before,/999|888|0\.9|OBJ|RSK|INF/);
  assert.match(before,/Awaiting analysis/);
  for(const value of ['7 mm','0.8 mm','14.57 g','126.617 min','5.723 J/g','Ready']) assert.ok(after.includes(value),value);
});

test('archived generation, slicer and analysis are joined by specimen, cached, and run scoped', async () => {
  const payloads = {
    '/spec':{run_id:'run',specimen_id:'s1',experiment_spec:{candidate_id:'c1',cell_size_mm:7,wall_thickness_mm:0.8,geometry_type:'gyroid'}},
    '/spc':{data:{specimen_result:{run_id:'run',specimen_id:'s1',sliced_path:'part.gcode.3mf',
      expected_print_time_min:999,slicer_result:{ok:true,estimated_print_time_sec:4200,estimated_mass_g:14.57}}}},
    '/anl':{ok:true,specimen_id:'s1',objective_score:5.7227,bo_observation:{unit:'J/g'},
      specimen_geometry:{mass_g:14.57,mass_source:'slicer'},utm_curve:[1,2,3]},
    '/wrong':{data:{specimen_result:{run_id:'other',specimen_id:'s1',slicer_result:{estimated_print_time_sec:1}}}},
  };
  const files = [
    {path:'specimens/s1/handoff_package.json',url:'/spec'},
    {path:'runtime/loops/loop-000001/specimen_agent/attempt-000001/result.json',url:'/spc'},
    {path:'analysis/s1/analysis_report.json',url:'/anl'},
    {path:'runtime/loops/loop-000002/specimen_agent/attempt-000001/result.json',url:'/wrong'},
  ];
  let calls = 0;
  const ctx=vm.createContext({window:{},liveRunArtifacts:files,liveSelectedAgent:'design',liveLastSession:{},
    liveDesignEvidenceCache:{runId:'',records:{},fetched:new Set(),pending:false},
    invalidateLiveCenterRender(){},renderLiveRuntime(){},fetch:async url=>{calls++;return {ok:true,json:async()=>payloads[url]};}});
  inject(ctx,'designArchivedSpecimenEvidence');
  ctx.designArchivedSpecimenEvidence({state:{run_id:'run'}});
  await new Promise(setImmediate);
  const [row]=ctx.designArchivedSpecimenEvidence({state:{run_id:'run'}});
  assert.equal(row.cell_size_mm,7);
  assert.equal(row.wall_thickness_mm,0.8);
  assert.equal(row.duration_evidence.duration_min,70);
  assert.equal(row.performance_evidence.value,5.7227);
  assert.equal(row.specimen_geometry.mass_g,14.57);
  assert.equal(row.gcode_path,'part.gcode.3mf');
  assert.equal(row.utm_curve,undefined);
  assert.equal(calls,4);
});

test('older cards receive only their own evidence; gcode.3mf is recognized', () => {
  const ctx=vm.createContext({dashboardFiniteNumber:number,
    liveRunArtifacts:[{path:'specimens/s1/specimen.stl',url:'/s1.stl'},
      {path:'specimens/s1/specimen.gcode.3mf',url:'/s1.gcode.3mf'},
      {path:'specimens/s2/specimen.stl',url:'/s2.stl'}],
    designCandidateRows:()=>[],designCandidateIdFromSpecimenId:()=>'',designLoopIndexFromIds:()=>null,
    designRunArtifactUrlFromPath:()=>'',latestSpecimenAgentReport:()=>({}),
    latestSpecimenFabricationReport:()=>({}),latestSpecimenFabricatedPacket:()=>({})});
  for(const name of ['designSpecimenIdFromPath','mergeDesignActualSpecimenRecord','designActualSpecimenRows']) inject(ctx,name);
  const rows=ctx.designActualSpecimenRows({}, {}, {spec:{specimen_id:'s2',cell_size_mm:9,wall_thickness_mm:1.1},
    specimenEvidence:[{specimen_id:'s1',cell_size_mm:6,wall_thickness_mm:0.7,performance_evidence:{value:3,unit:'J/g'}}]});
  assert.equal(rows.find(row=>row.specimen_id==='s1').cell_size_mm,6);
  assert.equal(rows.find(row=>row.specimen_id==='s1').gcode_url,'/s1.gcode.3mf');
  assert.equal(rows.find(row=>row.specimen_id==='s2').cell_size_mm,9);
  assert.equal(rows.find(row=>row.specimen_id==='s2').performance_evidence,undefined);
});
