const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
test('first click posts existing E-STOP endpoint before audit; audit failure cannot block stop',async()=>{
  const source=fs.readFileSync('web/static/planning.js','utf8');
  const start=source.indexOf('async function confirmOrRequestLiveEmergencyStop()');
  const calls=[];
  const ctx=vm.createContext({resetLiveEmergencyStopArm:()=>{},
    liveEmergencyEndpoint:(_kind,fallback)=>fallback,
    setChatStatus:()=>{},fetchJsonOrThrow:async(url,options)=>{calls.push([url,options.method]);return {};},
    recordLiveIntentEvent:async()=>{calls.push(['audit']);throw Error('audit offline');},
    refreshPlanningState:async()=>calls.push(['refresh']),
    appendLiveRuntimeEvent:()=>assert.fail('stop should succeed'),liveSelectedAgent:'guardian'});
  vm.runInContext(source.slice(start,source.indexOf('\n}',start)+2),ctx);
  await ctx.confirmOrRequestLiveEmergencyStop();
  assert.deepEqual(calls[0],['/api/run/emergency-stop','POST']);
  assert.deepEqual(calls.slice(1),[['audit'],['refresh']]);
});
