const test = require('node:test');
const assert = require('node:assert/strict');
const {renderEquationCard} = require('../../web/static/bo_visualization.js');
const {renderPlot} = require('../../web/static/bo_visualization.js');

test('Live posterior can show the exact stored figure without independently redrawing it', () => {
  const payload = {schema:'bo_visualization.v1',run_id:'r',step:20,artifacts:{png_url:'/api/runs/r/artifact-file/plot.png'},objective:{},backend:{}};
  payload.posterior = {x:[0],mean:[1],std:[0],lower_95:[1],upper_95:[1]};
  payload.acquisition = {x:[0],value:[0]};
  payload.candidate_index_view = {...payload.posterior,acquisition:[0]};
  const html = renderPlot(payload, {preferArtifact:true});
  assert.match(html, /<img/);
  assert.match(html, /src="\/api\/runs\/r\/artifact-file\/plot.png"/);
  const missing = renderPlot({...payload, artifacts:{}}, {preferArtifact:true});
  assert.doesNotMatch(missing, /<svg/);
  assert.match(missing, /figure/);
});

test('objective card preserves expression and constraints while folding technical identity', () => {
  const input = {schema:'bo_visualization.v1', objective:{name:'Energy',direction:'minimize',equation:'a / b',unit:'J',objective_id:'private-id',hash:'12345',constraints:['a < 2']},design_space:{variables:['a','b'],dimension:2}};
  const before = JSON.stringify(input);
  const html = renderEquationCard(input);
  const visible = html.split('<details')[0];
  assert.match(visible, /a \/ b/);
  assert.match(visible, />J</);
  assert.match(visible, /Minimize/);
  assert.match(visible, /a &lt; 2/);
  assert.doesNotMatch(visible, /private-id|12345|ACTIVE OBJECTIVE/);
  assert.match(html, /<details[^>]*>\s*<summary>Details<\/summary>/);
  assert.match(html, /private-id/);
  assert.equal(JSON.stringify(input), before);
});

test('objective card does not invent density or cell variables for another domain', () => {
  const html = renderEquationCard({schema:'bo_visualization.v1', objective:{equation:'<script>x</script>'},design_space:{variables:['temperature']}});
  assert.match(html, /Temperature/);
  assert.match(html, /&lt;script&gt;x&lt;\/script&gt;/);
  assert.doesNotMatch(html, /Relative density|Cell size|<script>/);
});
