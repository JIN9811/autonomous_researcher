const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../../web/static/loop_chat_history.js'),'utf8');
const planning = fs.readFileSync(path.join(__dirname,'../../web/static/planning.js'),'utf8');
function fn(name, next) { return 'function '+name+planning.split('function '+name)[1].split('function '+next)[0]; }
function environment(fetch) {
  const window = {};
  const context = vm.createContext({window,fetch,URLSearchParams,Date,Map,Set,Number,String,Array,Boolean,Math,
    isChatSurfaceMessage:()=>true,isOperatorPlanningMessage:m=>m.role==='operator',
    planningMessageCycleIndex:m=>Number(m.cycle_index||0),planningMessageTotalCycles:()=>20,
    planningWorkflowCompleteAfter:()=>false,planningMessageStableToken:m=>String(m.transcript_index),
    chatGroupKeyForMessage:m=>m.role,makePlanningChatGroupKey:(key,m)=>key+':'+m.transcript_index});
  vm.runInContext(source,context);
  vm.runInContext(fn('annotatePlanningChatCycles(', 'planningWorkflowCompleteAfter(')
    +fn('buildPlanningChatItems(', 'planningChatItemRevealKey('),context);
  return {api:window.AX4LABLoopChatHistory,context,window};
}
const messages = Array.from({length:400},(_,i)=>({transcript_index:i,cycle_index:Math.floor(i/50)+1,
  role:'orchestrator',content:`Cycle ${Math.floor(i/50)+1} update ${i}`,run_id:'run-a',
  fabrication_report:{huge_blob:'not retained'},specimen:{mesh:[1,2,3]}}));
const session = {state:{run_id:'run-a'},planning_session_id:'run-a',message_total:400,
  messages:messages.slice(-160),has_more_messages:true,next_before:240};
(async()=>{
  let calls=0,changed=0;
  const e=environment(async url=>{
    calls++; assert.match(url,/before=240/);
    return {ok:true,json:async()=>({messages:messages.slice(0,240),has_more_messages:false,next_before:null,
      transcript_path:'/runs/run-a/live_planning_transcript.jsonl'})};
  });
  await e.api.sync(session,()=>changed++);
  assert.equal(changed,1);assert.equal(calls,1);
  e.context.latest=messages.slice(-160);
  const groups=vm.runInContext('buildPlanningChatItems(latest).filter(x=>x.group?.kind==="loop_summary")',e.context);
  assert.deepEqual(Array.from(groups,g=>g.group.loopCycle),[1,2,3,4,5,6,7]);
  assert.equal(groups[0].group.messages.length,50);
  assert.equal(groups[0].group.messages[0].fabrication_report,undefined);
  assert.equal(groups[0].group.messages[0].specimen,undefined);
  await e.api.sync(session,()=>changed++);assert.equal(calls,1,'no repeated full-history fetch on polling');
  await e.api.sync({...session,state:{run_id:'run-b'},planning_session_id:'run-b',message_total:0,messages:[],has_more_messages:false},()=>{});
  assert.equal(e.api.merge([]).length,0,'run changes clear old loop history');
  const mismatch=environment(async()=>({ok:true,json:async()=>({messages:messages.slice(0,240),transcript_path:'/runs/other/transcript',has_more_messages:false})}));
  await mismatch.api.sync(session,()=>{});
  assert.equal(mismatch.api.merge([]).length,160,'wrong-run pages are never admitted');
  // Refresh creates a fresh module: all seven summaries hydrate again.
  const refreshed=environment(async()=>({ok:true,json:async()=>({messages:messages.slice(0,240),has_more_messages:false,transcript_path:'/runs/run-a/transcript'})}));
  await refreshed.api.sync(session,()=>{});
  assert.equal(refreshed.api.merge([]).length,400);
  refreshed.window.AX4LABReplay={};assert.equal(refreshed.api.merge([]).length,0,'replay never borrows live history');
  if (process.env.ATR_LIVE_CHAT_CHECK === '1') {
    const liveSession=await (await fetch('http://127.0.0.1:7860/api/planning/session')).json();
    const live=environment(url=>fetch('http://127.0.0.1:7860'+url));
    await live.api.sync(liveSession,()=>{});
    live.context.latest=liveSession.messages;
    const cycles=vm.runInContext('buildPlanningChatItems(latest).filter(x=>x.group?.kind==="loop_summary").map(x=>x.group.loopCycle)',live.context);
    assert.deepEqual(Array.from(cycles),[1,2,3,4,5,6,7]);
    console.log('Current run completed-loop headings:',Array.from(cycles).join(', '));
  }
  console.log('Loop history: all seven summaries, bounded payloads, refresh, run isolation and replay isolation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
