const test = require('node:test');
const assert = require('node:assert/strict');
const surface = require('../../web/static/bo_posterior_surface.js');
const renderer = require('../../web/static/bo_visualization.js');
function payload() {
  const empty={x:[],mean:[],std:[],lower_95:[],upper_95:[],acquisition:[]};
  return {schema:'bo_visualization.v1',run_id:'test',step:9,posterior:empty,
    acquisition:{x:[],value:[],name:'Expected Improvement',raw_name:'LogExpectedImprovement'},candidate_index_view:empty,
    objective:{unit:'J/g',direction:'maximize'},backend:{model:'SingleTaskGP'},
    response_surface:{mode:'continuous_2d_gp_surface',matrix_order:'yx',x_parameter:'cell_size_mm',y_parameter:'wall_thickness_mm',
      x_values:[5,10],y_values:[.6,1.2],mean:[[8,9],[10,11]],std:[[.1,.2],[.3,.4]],acquisition:[[0,.1],[.2,.3]]},
    training_observations:[{parameters:{cell_size_mm:5,wall_thickness_mm:.6},score:8,candidate_id:'<script>'}],
    next_point:{parameters:{cell_size_mm:7.5,wall_thickness_mm:.9},mean:9.5,std:.25,acquisition:.15},
    artifacts:{png_url:'/api/old.png',surface_2d_url:'/api/posterior_2d.png',surface_3d_url:'/api/posterior_3d.png'}};
}
test('full grid routes ahead of old PNG and offers the same data in 2D and 3D',()=>{
  const html=renderer.renderPlot(payload(),{preferArtifact:true});
  assert.match(html,/data-bo-surface-view="2d"/);
  assert.match(html,/data-bo-surface-view="3d" hidden/);
  assert.equal((html.match(/<img /g)||[]).length,2);
  assert.doesNotMatch(html,/old\.png|NaN|undefined|<script>/);
  assert.match(html,/posterior_2d.png/);
  assert.match(html,/posterior_3d.png/);
});
test('missing or unsafe surface artifacts use old artifact fallback',()=>{
  for(const bad of ['', 'javascript:alert(1)', '//evil.com/plot.png', '/\\evil.com/plot.png']) {
    const p=payload();p.artifacts.surface_2d_url=bad;
    assert.equal(surface.valid(p),false);
    assert.match(renderer.renderPlot(p,{preferArtifact:true}),/old\.png/);
  }
});
test('toggle is local and persists only by run across rerenders',()=>{
  const panes=['2d','3d'].map(m=>({dataset:{boSurfaceView:m},hidden:false}));
  const buttons=['2d','3d'].map(m=>({dataset:{boSurfaceMode:m},setAttribute(k,v){this[k]=v;}}));
  surface.select({dataset:{boSurfaceRun:'test'},querySelectorAll:s=>s.includes('view')?panes:buttons},'3d');
  assert.deepEqual(panes.map(p=>p.hidden),[true,false]);
  assert.deepEqual(buttons.map(b=>b['aria-pressed']),['false','true']);
  assert.match(surface.render(payload()),/data-bo-surface-view="2d" hidden/);
  const other=payload();other.run_id='other';
  assert.match(surface.render(other),/data-bo-surface-view="3d" hidden/);
});
