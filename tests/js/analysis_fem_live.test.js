const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const modulePath = path.resolve(__dirname, '../../web/static/analysis_fem_live.js');
const fem = fs.existsSync(modulePath) ? require(modulePath) : {};
const pointer = {job_id: 'j1', run_id: 'run/a', loop_key: 'loop1', specimen_id: 's1', status: 'queued'};
const analysis = {fem_job: pointer, utm_curve: {preview: [{displacement_mm: 0, force_N: 0}, {displacement_mm: 2, force_N: 40}]}, specimen_geometry: {gauge_length_mm: 10, cross_section_area_mm2: 20}};
const job = (extra = {}) => ({...pointer, experiment_curve: analysis.utm_curve.preview, specimen_geometry: analysis.specimen_geometry, attempts: [], events: [], progress: {}, ...extra});

test('pending FEM shows measured curve and exactly four cards without fabricating solver results', () => {
  assert.equal(typeof fem.createController, 'function', 'Live FEM controller is not implemented');
  const view = fem.createController(); view.setContext(analysis);
  const html = view.html();
  assert.equal((html.match(/data-fem-card=/g) || []).length, 4);
  assert.match(html, /Experiment vs FEM/);
  assert.match(html, /data-series="experiment"/);
  assert.doesNotMatch(html, /data-series="fem"/);
  assert.match(html, /FEM pending/);
});

test('Live host adapter can render each FEM panel as an independent common dashboard card', () => {
  const calls = [];
  const view = fem.createController({renderCard: (title, body, options) => {
    calls.push({title, body, options});
    return `<section class="ar-report-card live-report-section ar-span-${options.span}" data-fem-card="${options.id}">${body}</section>`;
  }});
  view.setContext(analysis);
  const html = view.html();
  assert.equal(calls.length, 4);
  assert.deepEqual(calls.map(call => call.title), ['Experiment vs FEM', 'FEM Response', 'Solver Contour', 'Agentic Progress']);
  assert.ok(calls.every(call => call.options.span === 6 && call.options.tone === 'analysis'));
  assert.equal((html.match(/class="ar-report-card live-report-section/g) || []).length, 4);
  assert.equal((html.match(/data-fem-body=/g) || []).length, 4);
  assert.match(html, /data-live-preserve="fem:/);
});

test('common FEM cards use Live report contrast tokens while plots keep a white canvas', () => {
  const css = fs.readFileSync(path.resolve(__dirname, '../../web/static/analysis_fem_live.css'), 'utf8');
  const liveCss = css.slice(css.indexOf('/* Common Live report cards'));
  assert.match(liveCss, /body\.planning-live-body \.analysis-fem-live \.fem-evidence dt,/);
  assert.match(liveCss, /color: var\(--ar-muted/);
  assert.match(liveCss, /body\.planning-live-body \.analysis-fem-live button[^}]*var\(--ar-text/s);
  assert.match(css, /\.fem-chart[^}]*background:\s*#fff/s);
});

test('common card bodies update controls in place without recreating wrappers', () => {
  let wrapperRenders = 0;
  const bodies = Object.fromEntries(['overlay', 'response', 'contour', 'agentic'].map(name => [name, {
    name, __femHTML: '', replacements: 0,
    querySelector: () => null,
    replaceChildren(content) { this.replacements += 1; this.lastContent = content; },
  }]));
  const ownerDocument = {createElement: () => {
    const content = {querySelector: () => null, html: ''};
    return {content, set innerHTML(value) { content.html = value; }};
  }};
  const mounted = {
    isConnected: true, ownerDocument,
    addEventListener() {},
    querySelector(selector) {
      const match = selector.match(/data-fem-body="([^"]+)"/);
      return match ? bodies[match[1]] : null;
    },
  };
  const view = fem.createController({renderCard: (title, body, options) => {
    wrapperRenders += 1;
    return `<section data-fem-card="${options.id}">${body}</section>`;
  }});
  view.setContext(analysis);
  view.html();
  view.mount(mounted);
  const responseBody = bodies.response;
  const before = responseBody.replacements;

  view.accept({jobs: [job({attempts: [{attempt_id: 'a1'}, {attempt_id: 'a2'}]})]});
  view.navigate('attempt', 1);

  assert.equal(wrapperRenders, 4);
  assert.equal(bodies.response, responseBody);
  assert.ok(responseBody.replacements > before);
  assert.match(responseBody.lastContent.html, /Attempt<\/dt><dd>a2/);
});

test('unavailable registration stays visible without inventing a job or making requests', async () => {
  const view = fem.createController({fetch: () => {throw Error('No job to query');}});
  view.setContext({fem_job: {status:'unavailable', reason:'worker unavailable'}});
  await view.poll();
  assert.match(view.html(), /unavailable/);
  assert.match(view.html(), /worker unavailable/);
  assert.equal(view.snapshot().job, null);
});

test('read-only polling accepts a late completed job after foreground completion', async () => {
  assert.equal(typeof fem.createController, 'function');
  let count = 0;
  const view = fem.createController({fetch: async (url, options) => {
    assert.equal(options.method, 'GET');
    assert.match(url, /run_id=run%2Fa&loop_key=loop1&specimen_id=s1/);
    count++;
    return {ok: true, json: async () => ({jobs: [job(count === 1 ? {} : {status: 'completed', attempts: [{attempt_id: 'a1', curve: [{displacement_mm: 0, force_N: 0}, {displacement_mm: 1, force_N: 30}], endpoint_reached: false}]})]})};
  }});
  view.setContext(analysis);
  await view.poll(); await view.poll();
  assert.match(view.html(), /data-series="fem"/);
  assert.match(view.html(), /Partial endpoint/);
  assert.equal(view.snapshot().job.status, 'completed');
});

test('late response and malformed/mismatched identities cannot bleed into a new loop', async () => {
  assert.equal(typeof fem.createController, 'function');
  let resolve;
  const view = fem.createController({fetch: () => new Promise(r => {resolve = r;})});
  view.setContext(analysis); const pending = view.poll();
  view.setContext({...analysis, fem_job: {...pointer, loop_key: 'loop2', job_id: 'j2'}});
  resolve({ok: true, json: async () => ({jobs: [job({status: 'completed'})]})});
  await pending;
  assert.equal(view.snapshot().job, null);
  view.accept({jobs: [job()]});
  assert.equal(view.snapshot().job, null);
  view.setContext({improvement: {job_id: 'old'}});
  assert.equal(view.snapshot().identity, null);
});

test('attempt and contour indices retain selected identities across reordered updates', () => {
  assert.equal(typeof fem.createController, 'function');
  const view = fem.createController(); view.setContext(analysis);
  const a = {attempt_id: 'a', field_asset_path: 'runs/a.fields.json'}, b = {attempt_id: 'b', field_asset_path: 'runs/b.fields.json'};
  view.accept({jobs: [job({attempts: [a, b]})]});
  view.navigate('attempt', 1); view.navigate('contour', 1);
  view.accept({jobs: [job({attempts: [b, a, {attempt_id: 'c'}]})]});
  assert.equal(view.snapshot().attempt.attempt_id, 'b');
  assert.equal(view.snapshot().contour.attempt.attempt_id, 'b');
  assert.equal((view.html().match(/data-fem-card=/g) || []).length, 4);
  view.setContext({...analysis, fem_job: {...pointer, loop_key: 'loop2'}});
  assert.equal(view.snapshot().attempt, null);
});

test('comparison and FEM response each expose navigation within their own card', () => {
  const view = fem.createController(); view.setContext(analysis);
  view.accept({jobs: [job({attempts: [{attempt_id: 'a'}, {attempt_id: 'b'}]})]});
  const html = view.html();
  const overlay = html.split('data-fem-body="overlay"')[1].split('</article>')[0];
  assert.match(overlay, /data-fem-nav="attempt"/);
  assert.match(overlay, /Selected attempt/);
});

test('contour metadata is lazy, selected only, cached, and expands frame navigation', async () => {
  assert.equal(typeof fem.createController, 'function');
  const urls = [];
  const view = fem.createController({fetch: async (url) => {
    urls.push(url);
    return {ok: true, json: async () => ({frames: [{frame_index: 0, time: .1, fields: {S_MISES: {units: 'MPa'}, U: {units: 'mm'}}}, {frame_index: 1, time: .2, fields: {S_MISES: {units: 'MPa'}}}]})};
  }});
  view.setContext(analysis); view.accept({jobs: [job({attempts: [{attempt_id: 'a', field_asset_path: 'runs/a.fields.json'}, {attempt_id: 'b', field_asset_path: 'runs/b.fields.json'}]})]});
  assert.equal(urls.length, 0);
  await view.loadContour(); await view.loadContour();
  assert.deepEqual(urls, ['/api/cae/fields/metadata?path=runs%2Fa.fields.json']);
  const before = view.snapshot().contourUrl;
  assert.match(view.html(), /<img[^>]+src="\/api\/cae\/fields\/render\?/);
  view.accept({jobs: [job({progress: {elapsed_s: 22}, attempts: [{attempt_id: 'a', field_asset_path: 'runs/a.fields.json'}, {attempt_id: 'b', field_asset_path: 'runs/b.fields.json'}]})]});
  assert.equal(view.snapshot().contourUrl, before);
  view.navigate('contour', 1);
  assert.match(view.snapshot().contourUrl, /frame=1/);
});

test('stress-strain uses FEM geometry and autoscale follows data, not a fixed target', () => {
  assert.equal(typeof fem.createController, 'function');
  const view = fem.createController(); view.setContext(analysis);
  view.accept({jobs: [job({attempts: [{attempt_id: 'a', curve: [{displacement_mm: 0, force_N: 0}, {displacement_mm: 1, force_N: 30}]}]})]});
  view.setMode('ss');
  assert.deepEqual(view.snapshot().femSeries, [{x: 0, y: 0}, {x: 10, y: 1.5}]);
  assert.match(view.html(), /Engineering strain/);
  assert.doesNotMatch(view.html(), /50%|target strain/);
  assert.deepEqual(fem.curveSeries([{displacement_mm: null, force_N: 8}], {}, 'fd'), []);
});

test('untrusted labels are escaped and artifact paths cannot become executable URLs', () => {
  assert.equal(typeof fem.createController, 'function');
  const view = fem.createController(); view.setContext(analysis);
  view.accept({jobs: [job({summary: '<script>alert(1)</script>', events: [{phase: '<img src=x onerror=x>', message: '" onclick="bad'}], attempts: [{attempt_id: '" onmouseover="bad', field_asset_path: 'javascript:alert(1)'}]})]});
  const html = view.html();
  assert.doesNotMatch(html, /<script|<img src=x|src="javascript:/);
  assert.match(html, /&lt;script&gt;/);
  assert.equal(view.snapshot().contourUrl, '');
});

function planningFunction(name) {
  const source = fs.readFileSync(path.resolve(__dirname, '../../web/static/planning.js'), 'utf8');
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} integration is missing`);
  const end = source.indexOf('\nfunction ', start + 10);
  return source.slice(start, end < 0 ? undefined : end);
}

test('Analysis owner report hydration takes precedence over scalar-compacted session state', () => {
  const context = {backendField: (source, keys) => {
    for (const key of keys) {
      let value = source;
      for (const part of key.split('.')) value = value && value[part];
      if (value !== undefined && value !== null) return value;
    }
    return null;
  }, eventPayload: event => event.payload || {}};
  vm.createContext(context);
  vm.runInContext(planningFunction('latestReportPayload'), context);
  vm.runInContext(planningFunction('latestAnalysisPayload'), context);
  const hydrated = {utm_curve: {preview: [{displacement_mm: 1, force_N: 20}]}, fem_job: pointer};
  context.report = {state: {latest_analysis: {objective_score: 0.7}}, messages: [{sections: {analysis_report: hydrated}}], events: []};
  const selected = vm.runInContext('latestAnalysisPayload(report)', context);
  assert.equal(selected.utm_curve.preview.length, 1);
  assert.equal(selected.fem_job.job_id, 'j1');
});

test('host-owned Analysis FEM evidence keeps four common cards for the owner frontend', () => {
  const context = {window: {AnalysisFemLive: fem}, liveAnalysisFemController: null,
    renderDashboardCard: (title, body, options) => `<section class="ar-report-card live-report-section" data-fem-card="${options.data['fem-card']}"><h4>${title}</h4>${body}</section>`};
  vm.createContext(context);
  vm.runInContext(planningFunction('renderAnalysisFemEvidence'), context);
  const html = vm.runInContext(`renderAnalysisFemEvidence(${JSON.stringify(analysis)})`, context);
  assert.equal((html.match(/data-fem-card=/g) || []).length, 4);
  assert.doesNotMatch(html, /Engineering Stress-Strain Curve|Solver Field Results|FEM \/ CAE Comparison/);
  assert.ok(context.liveAnalysisFemController);
});

test('active Analysis polling is independent of completed foreground and pauses on other views', async () => {
  const requests = [];
  const controller = fem.createController({fetch: async url => {requests.push(url); return {ok: true, json: async () => ({jobs: [job()]})};}});
  controller.setContext(analysis);
  const context = {liveSelectedAgent: 'analysis', liveCurrentView: 'report', liveReportPage: 'agent', document: {hidden: false}, liveAnalysisFemController: controller};
  vm.createContext(context);
  vm.runInContext(planningFunction('refreshLiveAnalysisFemEvidence'), context);
  await vm.runInContext('refreshLiveAnalysisFemEvidence()', context);
  assert.equal(requests.length, 1);
  context.liveSelectedAgent = 'bo';
  await vm.runInContext('refreshLiveAnalysisFemEvidence()', context);
  assert.equal(requests.length, 1);
});
