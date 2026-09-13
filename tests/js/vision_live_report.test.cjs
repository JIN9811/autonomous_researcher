"use strict";
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const root = require('node:path').resolve(__dirname, '../..');

test('Vision module mounts once, retains six cards and verification selections, and unmounts', async () => {
  const sandbox = {window: {}, URL, Promise};
  vm.runInNewContext(fs.readFileSync(`${root}/web/static/agent_module_host.js`, 'utf8'), sandbox);
  const modulePath = `${root}/agents/vision/frontend/live_report.js`;
  assert.ok(fs.existsSync(modulePath), 'Vision must own its frontend');
  let loads = 0;
  const host = sandbox.window.AX4LABAgentModuleHost.createModuleHost({globalObject: sandbox.window, loadAsset: async () => {
    loads++; vm.runInNewContext(fs.readFileSync(modulePath, 'utf8'), sandbox);
  }});
  const names = ['renderVisionUtmPlacementConfirmation','renderVisionSpecimenIntervention','renderVisionUtmVerification','renderVisionRuntimeControls','renderVisionLiveFrameEvidence','renderVisionInspectionFeed','renderVisionSegmentationPanels','renderVisionRuntimeHeaderActions','renderVisionActiveCamEjectionCheck','renderVisionUtmVerificationTabs','renderVisionCameraRuntimeSummary','renderVisionCameraHealthBoard','renderVisionRuntimeNodeFlow','renderVisionHandoffSignal','renderVisionEvidenceReviewBoard','renderVisionAgenticProgress','renderVisionConfusionMatrix','renderMiniBarChart'];
  const services = Object.fromEntries(names.map(name => [name, (...args) => `${name}:${JSON.stringify(args)}`]));
  Object.assign(services, {
    latestVisionAgentReport: () => ({}), latestVisionReport: report => report.vision,
    latestVisionSignalPacket: () => ({next_action:'wait'}), visionSpecimenInterventionFor: () => ({}),
    latestActiveCamArtifact: () => ({}), utmVerificationScope: () => ({}),
    updateUtmVerificationSelection: () => ({index:2}),
    selectVerification: (_, index) => ({index, title:'Clearance', status:'pending', confirmed:false}),
    visionLiveCameraProfile: () => ({}), visionLiveFrameEvidence: () => ({}),
    visionRuntimeStatus: () => ({status:'stopped'}),
    escapeHtml: String, renderRuntimeValue: String,
    renderDashboardCard: (title, body, options) => `<article>${title}:${body}:${JSON.stringify(options)}</article>`,
    renderVisionCardDetails: (label, body) => `${label}:${body}`,
    renderDashboardMetric: (label,value) => `${label}:${value}`,
    runtimeRows: rows => JSON.stringify(rows), renderDashboardRows: rows => JSON.stringify(rows),
    dashboardList: items => items.join(';'), renderReportList: items => items.join(';'),
  });
  const manifest = {id:'vision', implementation:{version:'1.0.0',frontend:{asset_url:'/module-assets/vision/live_report.js',namespace:'AX4LABVisionUI',factory:'createFrontend'}}};
  await host.reconcile([manifest], services);
  const ui = host.get('vision');
  await host.reconcile([manifest], services);
  assert.equal(host.get('vision'), ui); assert.equal(loads, 1);
  assert.equal(ui.renderReport({}), '');
  const report = {vision:{task:'placement',signal_board:[{signal:'ready',status:'blocked',confidence:0}],safety_anomaly:{anomaly:false}}};
  const details = ui.renderReport(report);
  assert.match(details, /ready · blocked/); assert.match(details, /conf=0/); assert.match(details, /placement/);
  const html = ui.renderDashboard(report, 'running', 'Vision', {});
  assert.equal((html.match(/<article>/g)||[]).length, 6);
  for (const title of ['Live Observation','Active Cam Ejection','UTM Verification','Camera / Runtime','Handoff Signal','Agentic Progress']) assert.ok(html.includes(title));
  assert.match(html,/renderVisionUtmVerification:.*Clearance/);
  assert.match(html,/renderVisionUtmVerificationTabs:\[\{\},2\]/);
  await host.reconcile([], services); assert.equal(host.get('vision'), null);
  await host.reconcile([manifest], services); assert.notEqual(host.get('vision'), ui);
});
