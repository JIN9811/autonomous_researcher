const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("web/static/run_review_picker.js", "utf8");

function setup(runs=[]) {
  const nodes = {};
  function element(value="") {
    return {value, style:{}, dataset:{}, children:[], listeners:{},
      append(child){this.children.push(child); if(this.children.length===1) this.value=child.value;},
      replaceChildren(...children){this.children=[]; this.value=""; children.forEach(child=>this.append(child));},
      addEventListener(name,fn){this.listeners[name]=fn;}};
  }
  for(const name of ["mode-select","replay-session-field","replay-session-select","replay-session-status","main-run-control-grid","run-inference-field","run-fault-field","run-fault-stage-field"]) nodes[name]=element();
  nodes["mode-select"].value="test";
  const calls=[], opened=[], window={open:(...args)=>opened.push(args)};
  vm.runInNewContext(source,{document:{getElementById:id=>nodes[id],createElement:()=>element()},window,
    fetch:async(url,opts)=>{calls.push([url,opts]); return {ok:true,json:async()=>({runs})};},encodeURIComponent});
  return {nodes,calls,opened,window,change:async(mode)=>{nodes["mode-select"].value=mode; await nodes["mode-select"].listeners.change();}};
}

test("picker is invisible and makes no requests in experiment modes",async()=>{
  const s=setup(); assert.equal(s.nodes["replay-session-field"].hidden,true); assert.equal(s.calls.length,0);
  await s.change("live"); assert.equal(s.calls.length,0);
});
test("replay lists sessions and opens exact selection without run start",async()=>{
  const s=setup([{run_id:"session-1",points:2},{run_id:"session-2",points:9}]);
  await s.change("replay"); assert.equal(s.nodes["replay-session-field"].hidden,false);
  assert.equal(s.nodes["replay-session-select"].children.length,2);
  s.nodes["replay-session-select"].value="session-2"; s.window.AX4LABRunReviewPicker.open();
  assert.equal(s.opened[0][0],"/replay?run_id=session-2");
  assert.equal(s.opened[0][1],"_blank");
  assert.match(s.opened[0][2],/popup=yes,width=1440,height=960/);
  assert.match(s.opened[0][2],/noopener,noreferrer/);
  assert.equal(s.calls[0][0],"/api/review/runs"); assert.equal(s.calls[0][1].method,"GET");
  await s.change("test"); s.window.AX4LABRunReviewPicker.open();
  assert.equal(s.opened.length,1); assert.equal(s.nodes["replay-session-field"].hidden,true);
});
test("no archive never starts a run or silently opens another session",async()=>{
  const s=setup(); await s.change("replay"); s.window.AX4LABRunReviewPicker.open();
  assert.equal(s.opened.length,0); assert.equal(s.nodes["replay-session-select"].disabled,true);
});
test("session selector sits between Mode and Inference",()=>{
  const html=fs.readFileSync("web/templates/index.html","utf8");
  assert.ok(html.indexOf('id="mode-select"') < html.indexOf('id="replay-session-select"'));
  assert.ok(html.indexOf('id="replay-session-select"') < html.indexOf('id="backend-select"'));
});

test("Replay hides only experiment fields and restores them without changing values",async()=>{
  const s=setup();
  const names=["run-inference-field","run-fault-field","run-fault-stage-field"];
  names.forEach(id=>s.nodes[id].value="preserved");
  await s.change("replay");
  assert.equal(s.nodes["main-run-control-grid"].dataset.mode,"replay");
  for(const id of names) {
    assert.equal(s.nodes[id].hidden,true);
    assert.equal(s.nodes[id].style.display,"none");
  }
  for(const mode of ["test","live","fault-injection"]) {
    await s.change(mode);
    assert.equal(s.nodes["main-run-control-grid"].dataset.mode,mode);
    for(const id of names) {
      assert.equal(s.nodes[id].hidden,false);
      assert.equal(s.nodes[id].style.display,"");
      assert.equal(s.nodes[id].value,"preserved");
    }
  }
});
