const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js', 'utf8');

test('startup replaces restored DSN selection with ORC report without changing subsequent selections', () => {
  const match = source.match(/function initializeLiveAgentLanding\(\) \{[\s\S]*?\n\}/);
  assert.ok(match, 'dedicated startup selection exists');
  const c = {liveSelectedAgent:'design', liveReportPage:'attention', liveSelectedEventKey:'old',
    liveSelectedReportSectionTitle:'Design', setLiveView:view=>{c.view=view;}};
  vm.runInNewContext(match[0], c);
  c.initializeLiveAgentLanding();
  assert.equal(c.liveSelectedAgent, 'orchestrator');
  assert.equal(c.liveReportPage, 'agent');
  assert.equal(c.view, 'report');
  c.liveSelectedAgent = 'specimen';
  assert.equal(c.liveSelectedAgent, 'specimen');
  assert.match(source, /restoreCachedPlanningState\(\);\s*initializeLiveAgentLanding\(\);/);
  assert.equal((source.match(/initializeLiveAgentLanding\(\);/g)||[]).length,1);
});
