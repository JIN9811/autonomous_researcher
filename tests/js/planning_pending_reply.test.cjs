const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js','utf8');
function part(name,next,prefix='function ') { return prefix+name+source.split(prefix+name)[1].split(next)[0]; }
function deferred() { let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject}; }
function setup() {
  const network=deferred();let calls=0;
  const c=vm.createContext({URLSearchParams,Set,Number,String,Boolean,
    window:{location:{search:'?auto=1'}},liveLastSession:{message_total:0},
    planningBootstrapStarted:false,planningMessageSubmitInFlight:false,planningMessagesCache:[],
    planningPendingRequestSeq:0,planningPendingRequestIds:new Set(),PLANNING_RENDER_CACHE_LIMIT:240,
    liveBackendPlanningBusy:false,planningThinkingCount:0,liveQuickActionBusy:false,
    planningPendingSpecimenInput:false,planningMessageInput:{value:''},liveSetupTransportVersion:0,
    collectPlanningContextPayload:()=>({}),collectPlanningPayload:()=>({}),setChatStatus:()=>{},
    updatePlanningControls:()=>{},renderLiveExperimentSetupPanel:()=>{},refreshLiveSetupState:async()=>{},
    fetch:()=>{calls++;return network.promise;}});
  c.renderPlanningMessages=messages=>{c.planningMessagesCache=c.limitPlanningMessageCache(messages);};
  c.applyPlanningSession=session=>{c.liveLastSession=session;c.renderPlanningMessages([...c.planningMessagesCache,...(session.messages||[])]);};
  c.pushPlanningThinking=()=>c.planningThinkingCount++;
  c.popPlanningThinking=()=>c.planningThinkingCount--;
  c.refreshPlanningState=async()=>{throw new Error('offline');};
  vm.runInContext(part('createPlanningPendingMessage(', 'function mergePlanningMessages(')
    +part('sendPlanningMessage(', 'function collectPlanningContextPayload(', 'async function ')
    +part('bootstrapLiveOrchestrator(', 'function shouldRefreshPlanningForRuntimeEvent(', 'async function '),c);
  return {c,network,calls:()=>calls};
}
test('opening restored or existing sessions never starts greeting or creates pending bubble',async()=>{
  for (const session of [{is_running:true,message_total:395},{is_running:false,message_total:395}]) {
    const {c,calls}=setup();c.liveLastSession=session;
    await c.bootstrapLiveOrchestrator();assert.equal(calls(),0);assert.equal(c.planningMessagesCache.length,0);
  }
});
test('pending is local to active request; restored and old anonymous placeholders are dropped',()=>{
  const {c}=setup();const active=c.createPlanningPendingMessage('orchestrator','test');
  c.renderPlanningMessages([{pendingReasoning:true},{pendingReasoning:true,message_id:'local-pending:old'},active,{content:'real'}]);
  assert.equal(c.planningMessagesCache.length,2);
  c.finishPlanningPendingMessage(active);
  assert.deepEqual(Array.from(c.planningMessagesCache,m=>m.content),['real']);
});
test('successful bootstrap removes placeholder without discarding events received in-flight',async()=>{
  const {c,network}=setup();const p=c.bootstrapLiveOrchestrator();
  assert.equal(c.planningMessagesCache[0].pendingReasoning,true);
  c.renderPlanningMessages([...c.planningMessagesCache,{content:'print progress'}]);
  network.resolve({ok:true,json:async()=>({ok:true,session:{messages:[{content:'Hello'}]}})});await p;
  assert.deepEqual(Array.from(c.planningMessagesCache,m=>m.content),['print progress','Hello']);
  assert.equal(c.planningPendingRequestIds.size,0);assert.equal(c.planningThinkingCount,0);
});
test('bootstrap failure and submitted-message rejection never leave response spinner',async()=>{
  for (const type of ['bootstrap-error','send-rejected','send-error','send-success']) {
    const {c,network}=setup();const p=type.startsWith('bootstrap')?c.bootstrapLiveOrchestrator():c.sendPlanningMessage('hello');
    if (type.endsWith('error')) network.reject(new Error('offline'));
    else network.resolve({ok:type.endsWith('success'),status:409,json:async()=>({ok:true,detail:'conflict',session:{messages:[{content:'accepted'}]}})});
    await p;
    assert.equal(c.planningMessagesCache.some(m=>m.pendingReasoning),false,type);
    assert.equal(c.planningPendingRequestIds.size,0);assert.equal(c.planningThinkingCount,0);
  }
});
test('finishing an older request does not erase a different active pending reply',()=>{
  const {c}=setup(),a=c.createPlanningPendingMessage('orchestrator','a'),b=c.createPlanningPendingMessage('printer_ai','b');
  c.renderPlanningMessages([a,b]);c.finishPlanningPendingMessage(a);
  assert.equal(c.planningMessagesCache.length,1);assert.equal(c.planningMessagesCache[0].message_id,b.message_id);
});
