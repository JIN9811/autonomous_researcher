const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js','utf8');
function extract(name,next,async=false) {
  return (async?'async ':'')+'function '+name+source.split('function '+name)[1].split(next)[0];
}
function deferred() { let resolve,reject; const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject}; }
function setup() {
  const requests=[],statuses=[],applied=[];
  const c=vm.createContext({Date:{now:()=>100},Math,Number,Boolean,Error,
    liveSpecimenVideoPlaying:false,liveSpecimenVideoStartedAt:0,liveSpecimenVideoStartSeq:0,
    liveLastSession:{},renderLiveRuntime:()=>{},setChatStatus:(...x)=>statuses.push(x),
    refreshLivePrinterMonitorStatus:async()=>({ok:true}),
    refreshLivePrinterVideoStatus:()=>{const d=deferred();requests.push(d);return d.promise;},
    applyPrinterVideoStatusResult:r=>applied.push(r),
    specimenVideoStreamUrl:c=>c.proxy_url,compactText:x=>x,specimenFirstValue:(...xs)=>xs.find(Boolean),escapeHtml:x=>x});
  vm.runInContext(extract('renderSpecimenVideoHeaderControls(', 'function applyPrinterMonitorSnapshotResult(')
    +extract('stopSpecimenVideoPlayback(', 'async function startSpecimenVideoPlayback(')
    +extract('startSpecimenVideoPlayback(', 'async function runSpecimenConnectionTest(',true),c);
  return {c,requests,statuses,applied};
}
test('Play remains clickable while active and each click refreshes/reconnects',async()=>{
  const {c,requests,applied}=setup();c.liveSpecimenVideoPlaying=true;
  assert.doesNotMatch(c.renderSpecimenVideoHeaderControls({cameraPanel:{proxy_url:'/stream'}}),/disabled/);
  const first=c.startSpecimenVideoPlayback();const stamp=c.liveSpecimenVideoStartedAt;
  const second=c.startSpecimenVideoPlayback();assert.ok(c.liveSpecimenVideoStartedAt>stamp);
  requests[1].resolve({ok:true,newest:true});await second;
  requests[0].reject(new Error('old request failed'));await first;
  assert.equal(c.liveSpecimenVideoPlaying,true);assert.equal(applied.length,1);assert.equal(applied[0].newest,true);
  const handler=source.split('const specimenVideoButton = event.target.closest')[1].split('const specimenProgressAction')[0];
  assert.doesNotMatch(handler,/\.disabled\s*=/);
});
test('Stop wins over a pending play and retry is possible after failure',async()=>{
  const {c,requests,applied}=setup();
  const first=c.startSpecimenVideoPlayback();c.stopSpecimenVideoPlayback();
  requests[0].resolve({ok:true});await first;
  assert.equal(c.liveSpecimenVideoPlaying,false);assert.equal(applied.length,0);
  const retry=c.startSpecimenVideoPlayback();requests[1].resolve({ok:false,error:'timeout'});await retry;
  assert.equal(c.liveSpecimenVideoPlaying,false);
  const recovered=c.startSpecimenVideoPlayback();requests[2].resolve({ok:true});await recovered;
  assert.equal(c.liveSpecimenVideoPlaying,true);assert.equal(applied.length,1);
});
test('video-status refresh is bounded and coalesces simultaneous requests',async()=>{
  const pending=deferred();let calls=0;
  const c=vm.createContext({livePrinterVideoStatusInFlight:null,
    fetchJsonOrThrowWithTimeout:(url,options,timeout)=>{assert.equal(url,'/api/printer/video-status');assert.equal(timeout,15000);calls++;return pending.promise;}});
  vm.runInContext(extract('refreshLivePrinterVideoStatus(', 'async function refreshPlanningAuxiliaryState(',true),c);
  const a=c.refreshLivePrinterVideoStatus(),b=c.refreshLivePrinterVideoStatus();assert.equal(calls,1);
  pending.reject(new Error('timeout'));await Promise.all([a,b]);assert.equal(c.livePrinterVideoStatusInFlight,null);
});
