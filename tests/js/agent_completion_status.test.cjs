const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js', 'utf8');
function status(runtimeStatus, stage='idle', agent='design') {
  const context = vm.createContext({
    currentRunEventSources: () => [{agent, status:'done'}, {agent,level:'error'}],
    agentIdFromEvent: e=>e.agent, agentIdFromStage: s=>s,
    planningMessagesCache: [{agent,content:'Old discussion',pending_operator_input:true}],
    agentIdFromMessage: m=>m.agent, liveApprovals:{pending:[]},
    eventRequiresOperatorInput:()=>false, isResolvedEmergencyLifecycleEvent:()=>false,
    isTransientPrinterCommunicationEvent:()=>false,
  });
  for (const name of ['specimenExecutionDisplayState','manipulationExecutionDisplayState','eventStatusForAgent']) {
    const start=source.indexOf(`function ${name}(`);
    vm.runInContext(source.slice(start,source.indexOf('\n}',start)+2),context);
  }
  return context.eventStatusForAgent(agent, {run_id:'current',loop_count:2,stage,agent_status:{[`${agent}_agent`]:runtimeStatus}},true);
}
test('chat and done event alone cannot complete an unstarted agent',()=>{
  assert.equal(status(undefined),'idle');
  assert.equal(status({state:'idle',success:null}),'idle');
});
for (const agent of ['orchestrator','design','specimen','vision','manipulation','equipment','analysis','bo','knowledge','guardian']) {
  test(`${agent}: past messages/errors and other cycles cannot override runtime`,()=>{
    assert.equal(status(undefined,'idle',agent),'idle');
    assert.equal(status({state:'done',success:true},'idle',agent),'done');
    assert.equal(status({state:'waiting',success:null},agent,agent),'waiting');
    assert.equal(status({state:'error',success:false},'idle',agent),'error');
    assert.equal(status({state:'done',success:true,run_id:'previous',loop_id:2},'idle',agent),'idle');
    assert.equal(status({state:'done',success:true,run_id:'current',loop_id:1},'idle',agent),'idle');
  });
}
test('only runtime completion marks design done',()=>{
  assert.equal(status({state:'idle',success:true}),'done');
  assert.equal(status({state:'done',success:true}),'done');
  assert.equal(status({state:'waiting',success:null},'design'),'waiting');
  assert.equal(status({state:'running',success:null},'design'),'running');
  assert.equal(status({state:'error',success:false}),'error');
});
