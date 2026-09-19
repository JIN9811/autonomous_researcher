const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js', 'utf8');
function setup(agent = 'design', pending = []) {
  const context = vm.createContext({
    liveSelectedAgent: agent, liveRunArtifacts: [{name: 'plot.png'}], liveApprovals: {pending},
    liveAgentNeedsChatPanel: id => ['orchestrator', 'objective', 'guardian', 'knowledge'].includes(id),
    renderDashboardMetric: (label, value, meta, tone) => `[${label}:${value}:${tone}]`,
    renderDashboardCard: (title, body) => `<section><h4>${title}</h4>${body}</section>`,
    renderAgentSpecializedDashboardSections: () => '<section>Original agent cards</section>',
  });
  for (const name of ['renderStageProgressCard', 'renderBackendConnectionCard', 'renderDashboardRows',
    'renderEvidenceWarningsCard', 'renderArtifactDashboardCard', 'renderDecisionRegisterCard',
    'renderRuntimeSignalGraph', 'renderRouteGraphDashboard', 'renderReportList']) context[name] = () => name;
  for (const name of ['renderRuntimeSupportCard', 'renderLiveDashboardReportSections', 'syncLiveReportAttributes']) {
    const start = source.indexOf(`function ${name}(`);
    vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), context);
  }
  return context;
}
const report = {state: {stage: 'equipment'}, warnings: [], artifactItems: [], messages: [], events: []};
test('every agent keeps specialized cards and has one collapsed runtime support', () => {
  for (const agent of ['orchestrator', 'objective', 'design', 'specimen', 'vision', 'manipulation', 'equipment', 'analysis', 'knowledge', 'bo', 'guardian']) {
    const html = setup(agent).renderLiveDashboardReportSections({}, report, 'running', agent);
    assert.equal((html.match(/<h4>Runtime Support<\/h4>/g) || []).length, 1, agent);
    assert.match(html, /Original agent cards/);
    assert.match(html, /<details class="runtime-support-detail">/);
    assert.doesNotMatch(html, /<details[^>]* open/);
    for (const label of ['Stage', 'Warnings', 'Artifacts', 'Approvals']) assert.match(html, new RegExp(`\\[${label}:`));
    for (const title of ['Backend Trace', 'Warnings', 'Artifacts', 'Approvals / Decisions']) assert.ok(html.includes(`<h4>${title}</h4>`));
  }
});
test('warnings and pending approvals remain highlighted while collapsed', () => {
  const html = setup('design', [{}]).renderRuntimeSupportCard({...report, warnings: ['attention']}, 'waiting');
  const summary = html.slice(0, html.indexOf('</summary>'));
  assert.match(summary, /Warnings:1:warning/);
  assert.match(summary, /Approvals:1:warning/);
});
test('control-agent route and signals remain available under details', () => {
  const html = setup('guardian').renderRuntimeSupportCard(report, 'waiting');
  assert.match(html, /renderRouteGraphDashboard/);
  assert.match(html, /renderRuntimeSignalGraph/);
});
test('report refresh preserves opened support details', () => {
  const removed = [];
  const current = {attributes: [{name: 'open'}], matches: selector => selector.includes('.runtime-support-detail'),
    removeAttribute: name => removed.push(name)};
  setup().syncLiveReportAttributes(current, {attributes: [], hasAttribute: () => false});
  assert.deepEqual(removed, []);
});
