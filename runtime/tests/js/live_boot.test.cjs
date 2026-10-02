const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const code=fs.readFileSync('web/static/live_boot.js','utf8');
function boot(mode) {
  const events={}, timers=[]; let removed=false, fades=0;
  const cover={dataset:{bootMode:mode},classList:{add:name=>{if(name==='is-leaving') fades++;}},remove:()=>removed=true,
    querySelector:tag=>({addEventListener:(event,fn)=>events[tag+event]=fn})};
  vm.runInNewContext(code,{document:{getElementById:()=>cover},
    window:{addEventListener:(event,fn)=>events[event]=fn},
    setTimeout:(fn,ms)=>(timers.push({fn,ms}),timers.length),clearTimeout:()=>{}});
  return {events,timers,get removed(){return removed;},get fades(){return fades;}};
}
for(const trigger of ['imgerror']) {
  test(`startup cover exits on ${trigger}`,()=>{
    const b=boot(); b.events[trigger](); b.events[trigger]();
    assert.equal(b.fades,1); b.timers.find(t=>t.ms===550).fn(); assert.ok(b.removed);
  });
}
test('ready waits for decoded logo and white-to-dark presentation',async()=>{
  const b=boot();
  b.events['ax4lab:live-ready']();
  assert.equal(b.fades,0);
  b.events.imgload(); await Promise.resolve();
  assert.ok(b.timers.some(t=>t.ms===600));
  b.timers.find(t=>t.ms===2100).fn();
  assert.equal(b.fades,1);
});
test('unresponsive startup cannot trap the cover indefinitely',()=>{
  const b=boot(); b.timers.find(t=>t.ms===10000).fn();
  assert.equal(b.fades,1);
});
test('workspace presentation ends at 1.7s without waiting for a runtime event',async()=>{
  const b=boot('workspace');
  b.events.imgload(); await Promise.resolve();
  assert.ok(b.timers.some(t=>t.ms===1700));
  b.timers.find(t=>t.ms===1700).fn();
  assert.equal(b.fades,1);
});
