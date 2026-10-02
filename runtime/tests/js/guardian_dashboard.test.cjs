const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root, 'agents/core/guardian/frontend/live_report.js'), 'utf8');
const escapeHtml = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
function render(status) {
  const context = {window:{}};
  vm.runInNewContext(source, context);
  return context.window.AX4LABGuardianUI.createFrontend({
    escapeHtml, liveGuardianStatusPayload:()=>status, latestReportPayload:()=>null,
    liveApprovalSnapshot:()=>({pending:[],resolved:[]}),
    liveRunEvidenceCounts:()=>({artifacts:0,validationItems:0,warnings:0,events:0}),
    renderDashboardCard:(title,body)=>`<article><h4>${title}</h4>${body}</article>`,
    renderDashboardRows:rows=>JSON.stringify(rows), dashboardList:rows=>rows.join(''),
  }).renderDashboard({nextAction:'Do not use generic next action as a safety decision',warnings:[]});
}
test('Guardian uses recorded decisions, gate timeline, device evidence and all history rows',()=>{
  const html=render({status:'blocked',summary:{risk_score:0},
    handoff_packet:{latest_guardian_decision:{decision:'hold',reason_code:'STALE_CAMERA',next_action:'Refresh camera evidence'}},
    gate_timeline:Array.from({length:12},(_,i)=>({stage:`stage-${i}`,phase:'pre',decision:'hold',reason_code:'STALE_CAMERA'})),
    device_data_integrity:{live_device_heartbeat:[{device_id:'camera-A',heartbeat_status:'stale',bridge_state:'connected'}]},
    safe_stop_verification:{status:'not_requested',requested:false,verified:false},
    evidence_completeness:{status:'missing'},
    incident_ledger:{records:[{severity:'warning',message:'<script>unsafe</script>',stage:'vision'}]},
  });
  for(const text of ['STALE_CAMERA','Refresh camera evidence','stage-11','camera-A','stale','not_requested','&lt;script&gt;unsafe&lt;/script&gt;']) assert.ok(html.includes(text),text);
  assert.ok(!html.includes('Do not use generic next action'));
  assert.ok(!html.includes('<details'));
  assert.ok(!html.includes('<script>'));
});
test('Guardian missing data is not presented as approval or a zero risk score',()=>{
  const html=render(null);
  assert.ok(html.includes('Not evaluated'));
  assert.ok(!html.includes('Do not use generic next action'));
  assert.ok(!html.includes('0%'));
});
test('ATT Recently Resolved spans the full report width',()=>{
  const planning=fs.readFileSync(path.join(root,'web/static/planning.js'),'utf8');
  assert.ok(/renderReportSection\("Recently Resolved",[^\n]+\{ wide: true \}/.test(planning));
});
