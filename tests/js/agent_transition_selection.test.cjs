const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
test('only fresh cross-agent orchestration transitions click the binder',()=>{
  const clicks=[];
  const context=vm.createContext({liveLastAgentTransitionKey:'',liveSelectedAgent:'orchestrator',
    liveCurrentRunId:()=> 'r',agentIdFromStage:s=>s,
    knownLiveAgent:s=>['design','vision','manipulation'].includes(s),
    liveAgentBinderList:{querySelectorAll:()=>['design','vision','manipulation'].map(id=>({dataset:{agentId:id},click:()=>clicks.push(id)}))}});
  const source=fs.readFileSync('web/static/planning.js','utf8');
  const start=source.indexOf('function selectAgentOnOrchestrationTransition(');
  vm.runInContext(source.slice(start,source.indexOf('\n}',start)+2),context);
  const event={event_type:'stage_transition',run_id:'r',timestamp:'1',payload:{from_stage:'design',to_stage:'vision'}};
  context.selectAgentOnOrchestrationTransition(event);
  context.selectAgentOnOrchestrationTransition(event);
  for(const e of [{...event,run_id:'old'},{...event,event_type:'agent_result'},
    {...event,payload:{from_stage:'vision',to_stage:'vision'}},
    {...event,payload:{from_stage:'vision',to_stage:'complete'}}]) context.selectAgentOnOrchestrationTransition(e);
  assert.deepEqual(clicks,['vision']);
});
