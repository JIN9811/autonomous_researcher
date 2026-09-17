const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const source=fs.readFileSync('web/static/planning.js','utf8');
function setup() {
  const clicks=[], actions=[], timers=[];
  const context=vm.createContext({liveSelectedAgent:'orchestrator', liveAttentionSeen:new Set(),
    livePendingAgentAttention:null, liveCurrentRunId:()=> 'r', liveLastSession:{state:{loop_count:2,stage:'design'}},
    agentIdFromStage:stage=>stage,
    liveSpecimenVideoPlaying:false, refreshPlanningState:async()=>{},
    window:{setTimeout:fn=>timers.push(fn)},
    liveAgentBinderList:{querySelectorAll:()=>['design','specimen','vision','manipulation','equipment','analysis','knowledge','bo'].map(id=>({
      dataset:{agentId:id},click:()=>{clicks.push(id);context.liveSelectedAgent=id;}}))},
    liveReportPanel:{querySelector:selector=>({click:()=>actions.push(selector)})}});
  for(const name of ['selectAgentOnAttentionRequest','applyPendingAgentAttention','recoverAgentAttentionRequest']) {
    const start=source.indexOf(`function ${name}(`);
    vm.runInContext(source.slice(start,source.indexOf('\n}',start)+2),context);
  }
  return {context,clicks,actions,timers};
}
function event(agent='design',checkpoint='handoff',action='report') {
  return {event_type:'agent.attention_requested',run_id:'r',timestamp:new Date().toISOString(),payload:{
    agent_id:agent,checkpoint,view_action:action,presentation_only:true,loop_index:2,
    attention_id:`r:2:${agent}:${checkpoint}`}};
}
test('only fresh current-run owner events click once; routing never clicks',()=>{
  const {context:c,clicks}=setup();
  for(const e of [
    {...event(),event_type:'stage_transition'}, {...event(),run_id:'old'},
    {...event(),timestamp:'2020-01-01'}, {...event(),payload:{...event().payload,loop_index:1}},
    event('specimen','handoff','report'),event('specimen','print_started','report'),
  ]) c.selectAgentOnAttentionRequest(e);
  assert.deepEqual(clicks,[]);
  for(const agent of ['design','equipment','analysis','knowledge','bo']) {
    c.selectAgentOnAttentionRequest(event(agent)); c.selectAgentOnAttentionRequest(event(agent));
  }
  assert.deepEqual(clicks,['design','equipment','analysis','knowledge','bo']);
});
test('printing plays video; vision selects requested verification without capture',()=>{
  const {context:c,clicks,actions}=setup();
  c.selectAgentOnAttentionRequest(event('specimen','print_started','printer_video'));
  c.selectAgentOnAttentionRequest(event('vision','active_cam','active_cam'));
  c.selectAgentOnAttentionRequest(event('vision','placement_home','verification_1'));
  c.selectAgentOnAttentionRequest(event('vision','replay_complete','verification_2'));
  assert.deepEqual(clicks,['specimen','vision','vision','vision']);
  assert.deepEqual(actions,['[data-spm-video-action="play"]','[data-utm-verification-select="1"]','[data-utm-verification-select="2"]']);
});
test('late panel rendering retries without reclicking owner; user navigation cancels',()=>{
  const {context:c,clicks,actions,timers}=setup();
  c.liveReportPanel={querySelector:()=>null};
  c.selectAgentOnAttentionRequest(event('specimen','print_started','printer_video'));
  assert.equal(timers.length,1);
  c.liveSelectedAgent='design'; timers.shift()();
  assert.deepEqual(clicks,['specimen']); assert.deepEqual(actions,[]);
  assert.equal(c.livePendingAgentAttention,null);
});

test('handoff received before the new run snapshot is recovered once after synchronization',()=>{
  const {context:c,clicks}=setup();
  c.liveCurrentRunId=()=> 'previous-run';
  const handoff=event();
  c.selectAgentOnAttentionRequest(handoff);
  assert.deepEqual(clicks,[]);
  c.liveCurrentRunId=()=> 'r';
  c.recoverAgentAttentionRequest([handoff]);
  c.recoverAgentAttentionRequest([handoff]);
  assert.deepEqual(clicks,['design']);
  c.liveSelectedAgent='bo';
  c.recoverAgentAttentionRequest([handoff]);
  assert.equal(c.liveSelectedAgent,'bo');
});

test('reconnect never replays stale, finished, other-loop or other-stage attention',()=>{
  const {context:c,clicks}=setup();
  c.recoverAgentAttentionRequest([{...event(),timestamp:'2020-01-01'}]);
  c.recoverAgentAttentionRequest([{...event(),timestamp:'invalid'}]);
  c.recoverAgentAttentionRequest([{...event(),payload:{...event().payload,loop_index:1}}]);
  c.liveLastSession.state.stage='specimen';
  c.recoverAgentAttentionRequest([event()]);
  c.liveLastSession.state.stage='design';
  c.liveLastSession.is_running=false;
  c.recoverAgentAttentionRequest([event()]);
  assert.deepEqual(clicks,[]);
});

test('only the latest vision checkpoint is recovered, never older unseen checkpoints',()=>{
  const {context:c,clicks,actions}=setup();
  c.liveLastSession.state.stage='vision';
  const older={...event('vision','placement_home','verification_1'),timestamp:new Date(Date.now()-1000).toISOString()};
  const latest=event('vision','replay_complete','verification_2');
  c.recoverAgentAttentionRequest([older,latest]);
  c.recoverAgentAttentionRequest([older,latest]);
  assert.deepEqual(clicks,['vision']);
  assert.deepEqual(actions,['[data-utm-verification-select="2"]']);
});
