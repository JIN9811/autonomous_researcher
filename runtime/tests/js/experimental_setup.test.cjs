const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const modulePath = path.join(__dirname, '../../web/static/experimental_setup.js');
// Start with an absent implementation as an empty API, so RED is behavioral.
const Setup = fs.existsSync(modulePath) ? require(modulePath) : {};

function block(overrides = {}) {
  return {block_id:'b1', topic_key:'research.goal', revision:3,
    owners:['orchestrator_agent'], fields:[{id:'research.goal', type:'string'}],
    active:true, editable:true, target:'next_run', agreement_status:'draft',
    application_status:'not_applied', draft_values:{'research.goal':'Next goal'},
    confirmed_values:{'research.goal':'Confirmed goal'}, effective_values:{'research.goal':'Running goal'},
    receipts:{}, current_draft_proposal_id:'p1', ...overrides};
}
function snapshot(overrides = {}) {
  return {schema:'experimental_setup.v1', session_id:'canonical-a', revision:9,
    event_seq:9, projection_id:'projection-a', blocks:[block()], owners:[], ...overrides};
}

test('experimental package stays first and follows the supplied active graph without changing setup', () => {
  const el=root(); const input=snapshot();
  const before=JSON.stringify(input);
  Setup.renderBlocks(el,input,{graph:{id:'graph_a',name:'Graph A',metadata:{experimental_package:{id:'experiment_a',display_name:'Experiment A',version:'1.0.0'}}}});
  const cards=all(el).filter(e=>e.className==='setup-block');
  assert.equal(cards[0].dataset.kind,'package');
  assert.match(visibleText(cards[0]),/Experimental Package.*Experiment A.*Bound/);
  assert.equal(JSON.stringify(input),before);
  Setup.renderBlocks(el,input,{graph:{id:'graph_b',metadata:{experimental_package:{id:'experiment_b',display_name:'Experiment B',version:'1.0.0'}}}});
  assert.match(visibleText(cards[0]),/Experiment B/);
  Setup.renderBlocks(el,input,{graph:{id:'unbound_graph',name:'Not a package'}});
  assert.match(visibleText(cards[0]),/Not bound/);
  assert.doesNotMatch(visibleText(cards[0]),/Experiment B/);
});

// Deliberately tiny DOM at the renderer boundary; full browser checks live in tests/ui.
test('initial internal defaults never appear as current experiment settings', () => {
  const el=root();
  Setup.renderBlocks(el,snapshot({blocks:[block({internal_default_only:true})]}),{graph:{}});
  const cards=all(el).filter(e=>e.className==='setup-block');
  assert.equal(cards.length,1);
  assert.equal(cards[0].dataset.kind,'package');
  assert.doesNotMatch(visibleText(el),/Next goal|Running goal/);
});

class Element {
  constructor(tag, doc) { this.tagName=tag; this.ownerDocument=doc; this.children=[];
    this.dataset={}; this.attributes={}; this.hidden=false; this.text=''; this.parentNode=null;
    this.classList={toggle:()=>{}, add:()=>{}}; }
  set textContent(value) { this.text=String(value); this.children=[]; }
  get textContent() { return this.text + this.children.map(c=>c.textContent).join(' '); }
  set innerHTML(value) { throw new Error('Unsafe HTML insertion: '+value); }
  append(...nodes) { nodes.forEach(n=>this.appendChild(n)); }
  appendChild(n) { if(n.parentNode) n.remove(); n.parentNode=this; this.children.push(n); return n; }
  insertBefore(n, before) { if(n===before) return n; if(n.parentNode)n.remove();
    n.parentNode=this; const at=this.children.indexOf(before); this.children.splice(at<0?this.children.length:at,0,n); return n; }
  remove() { if(this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this),1); this.parentNode=null; }
  setAttribute(k,v) { this.attributes[k]=String(v); }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(k,fn) { this['on'+k]=fn; }
  focus() { this.ownerDocument.activeElement=this; }
}
function root() { const doc={createElement:tag=>new Element(tag,doc)}; return doc.createElement('div'); }
function all(el) { return [el,...el.children.flatMap(all)]; }
function find(el, predicate) { return all(el).find(predicate); }
function visibleText(el) {
  if (el.hidden) return '';
  const children=el.tagName==='details' && !el.open ? el.children.filter(c=>c.tagName==='summary') : el.children;
  return el.text + children.map(visibleText).join(' ');
}

test('compact setup presents readable values without exposing internal contracts by default', () => {
  const el=root();
  Setup.renderBlocks(el,snapshot({blocks:[block({title:'Specimen',draft_values:{material:'PLA',specimen_size_mm:[30,30,30]}})],
    owners:[{owner:'design_agent',contract_status:'supported',availability:{status:'unknown'}}]}));
  const visible=visibleText(el);
  assert.match(visible,/PLA/); assert.match(visible,/30 × 30 × 30 mm/);
  assert.match(visible,/Unsaved changes/); assert.match(visible,/Technical details/);
  assert.doesNotMatch(visible,/specimen_size_mm|orchestrator_agent|design_agent|Revision|Agreement:|Contract:|Receipts|\{/);
  const card=find(el,e=>e.dataset.blockId==='b1');
  find(card,e=>e.className==='setup-block-toggle').onclick();
  find(card,e=>e.tagName==='details').open=true;
  assert.match(visibleText(card),/Revision 3/);
});
test('conversation cards show the latest value and only their usable Edit action', () => {
  const el=root();
  Setup.renderBlocks(el,snapshot({blocks:[block({title:'Material',conversation_input:true,draft_values:{material:'PETG'}})]}));
  find(el,e=>e.className==='setup-block-toggle').onclick();
  const text=visibleText(el);
  assert.match(text,/PETG/); assert.match(text,/Saved/); assert.match(text,/Edit/);
  assert.doesNotMatch(text,/Confirm|Discard|Revision|Agreement:/);
});
test('one-line cards toggle, keep at most three open, and preserve expansion during value refresh', () => {
  const el=root();
  const blocks=[1,2,3,4].map(n=>block({block_id:`b${n}`,title:`Setting ${n}`}));
  Setup.renderBlocks(el,snapshot({blocks}));
  const toggles=all(el).filter(e=>e.className==='setup-block-toggle');
  const openCount=()=>toggles.filter(e=>e.attributes['aria-expanded']==='true').length;
  assert.equal(openCount(),0);
  toggles.forEach(t=>t.onclick());
  assert.equal(openCount(),3);
  assert.equal(toggles[0].attributes['aria-expanded'],'false');
  assert.equal(find(el,e=>e.dataset.blockId==='b1').children[1].hidden,true);
  Setup.renderBlocks(el,snapshot({revision:10,blocks:blocks.map(b=>({...b,revision:4,draft_values:{material:'PETG'}}))}));
  assert.equal(openCount(),3);
  assert.match(toggles[3].textContent,/PETG/);
  toggles[3].onclick(); assert.equal(openCount(),2);
  assert.equal(toggles[3].attributes['aria-expanded'],'false');
});
test('collapsed status never hides rejected or uncertain application receipts as scheduled', () => {
  for (const status of ['rejected','partial','unknown']) {
    const el=root();
    Setup.renderBlocks(el,snapshot({blocks:[block({agreement_status:'confirmed',application_status:status,current_draft_proposal_id:null})]}));
    assert.match(visibleText(el),/Needs attention/);
    assert.doesNotMatch(visibleText(el),/For next run/);
  }
  const el=root();
  Setup.renderBlocks(el,snapshot({blocks:[block({agreement_status:'confirmed',application_status:'applying',current_draft_proposal_id:null})]}));
  assert.match(visibleText(el),/Applying/);
});

test('editing selects context without sending a command', () => {
  assert.equal(typeof Setup.beginEdit, 'function');
  assert.deepEqual(Setup.beginEdit({block_id:'b1', revision:3}), {block_id:'b1', revision:3});
});
test('conversation inputs update the same block and are edited in chat, never confirmed as owner configuration', () => {
  const el=root(); let edited;
  const input=block({topic_key:'conversation.input.material',conversation_input:true,draft_values:{material:'PLA'}});
  Setup.renderBlocks(el,snapshot({blocks:[input]}),{onEdit:b=>edited=b});
  const card=find(el,e=>e.dataset.blockId==='__setup_specimen__');
  const edit=find(card,e=>e.attributes['aria-label']==='Edit Material');
  assert.equal(edit.disabled,false);
  assert.equal(find(card,e=>e.textContent==='Confirm').disabled,true);
  assert.equal(find(card,e=>e.textContent==='Discard').disabled,true);
  Setup.renderBlocks(el,snapshot({revision:10,blocks:[{...input,revision:4,draft_values:{material:'PETG'}}]}),{onEdit:b=>edited=b});
  assert.equal(find(el,e=>e.dataset.blockId==='__setup_specimen__'),card);
  find(card,e=>e.attributes['aria-label']==='Edit Material').onclick(); assert.equal(edited.revision,4);
  assert.match(card.textContent,/PETG/);
  assert.match(card.textContent,/editing does not apply or execute a run/);
});

test('semantic setup groups show each field once and preserve source IDs and run differences', () => {
  const el=root(); let edited;
  const conv=(id,key,value)=>block({block_id:id,topic_key:`conversation.input.${key}`,conversation_input:true,draft_values:{[key]:value}});
  const input=snapshot({current_run_values:{goal:'Previous goal',wall_thickness_bounds_mm:[0.8,1.6]},blocks:[
    block(),block({block_id:'space',topic_key:'bo.parameter_space',draft_values:{'bo.parameter_space':{cell_size_mm:[5,10],wall_thickness_mm:[0.8,1.6]}}}),
    conv('goal','goal','Maximize SEA'),conv('objective','objective_type','SEA'),conv('direction','objective_direction','maximize'),
    conv('wall','wall_thickness_bounds_mm',[0.6,1.2]),conv('cell','cell_size_bounds_mm',[5,10])
  ]});
  const before=JSON.stringify(input);
  Setup.renderBlocks(el,input,{onEdit:b=>edited=b});
  assert.equal(all(el).filter(e=>e.className==='setup-block').length,2);
  for(const toggle of all(el).filter(e=>e.className==='setup-block-toggle')) toggle.onclick();
  assert.equal(all(el).filter(e=>e.tagName==='dt'&&e.textContent==='Goal').length,1);
  const text=visibleText(el);
  assert.match(text,/Maximize SEA/); assert.match(text,/Current run: Previous goal/);
  assert.match(text,/0.6, 1.2/); assert.match(text,/Differs from run/);
  find(el,e=>e.attributes['aria-label']==='Edit Wall thickness range (mm)').onclick();
  assert.equal(edited.block_id,'wall'); assert.equal(edited.revision,3);
  assert.equal(JSON.stringify(input),before);
});
test('old event cannot overwrite a newer block state', () => {
  assert.equal(typeof Setup.acceptSnapshot, 'function');
  const current = {revision:4, blocks:[]};
  assert.equal(Setup.acceptSnapshot(current, {revision:3, blocks:[]}), current);
});
test('foreign session cannot replace canonical state even with a larger revision', () => {
  assert.equal(typeof Setup.acceptSnapshot, 'function');
  const current=snapshot();
  assert.equal(Setup.acceptSnapshot(current,snapshot({session_id:'foreign',revision:900})),current);
});
test('equal value revision accepts changed graph/status projection without ordering its hash', () => {
  assert.equal(typeof Setup.acceptSnapshot, 'function');
  const current=snapshot({projection_id:'z'}), incoming=snapshot({projection_id:'a',blocks:[block({editable:false,active:false})]});
  assert.equal(Setup.acceptSnapshot(current,incoming),incoming);
});
test('renderer uses text nodes for hostile IDs, labels and values and keeps draft distinct from effective', () => {
  assert.equal(typeof Setup.renderBlocks,'function');
  const el=root();
  Setup.renderBlocks(el,snapshot({blocks:[block({block_id:'<svg onload=alert(1)>',topic_key:'<img src=x>',draft_values:{goal:'<script>bad()</script>'}})]}),{});
  assert.match(el.textContent, /<script>bad\(\)<\/script>/);
  assert.match(el.textContent, /Draft/); assert.match(el.textContent,/Confirmed goal/);
  assert.match(el.textContent,/Effective/); assert.match(el.textContent,/Running goal/);
  assert.equal(all(el).some(e=>['script','img','svg','input','textarea'].includes(e.tagName)),false);
});
test('stable block nodes and controls survive status/revision changes, preserving open details and focus', () => {
  assert.equal(typeof Setup.renderBlocks,'function');
  const el=root(); let edited;
  Setup.renderBlocks(el,snapshot(),{onEdit:b=>edited=b});
  const card=find(el,e=>e.dataset.blockId==='b1');
  const detail=find(card,e=>e.tagName==='details'); detail.open=true;
  const edit=find(card,e=>e.textContent==='Edit'); edit.focus();
  Setup.renderBlocks(el,snapshot({revision:10,blocks:[block({revision:4,application_status:'scheduled'})]}),{onEdit:b=>edited=b});
  assert.equal(find(el,e=>e.dataset.blockId==='b1'),card);
  assert.equal(find(card,e=>e.tagName==='details'),detail); assert.equal(detail.open,true);
  assert.equal(el.ownerDocument.activeElement,edit);
  edit.onclick(); assert.equal(edited.revision,4);
});
test('unsupported owners and inactive blocks are read-only and never imply hardware readiness', () => {
  assert.equal(typeof Setup.renderBlocks,'function');
  const el=root();
  Setup.renderBlocks(el,snapshot({blocks:[block({active:false,editable:false})],owners:[{
    node_id:'unsupported',owner:'third_party',contract_status:'unknown',
    setup:{write_enabled:false,reason:'No writable setup contract'},availability:{status:'unknown'}
  }]}),{});
  assert.match(el.textContent,/Read-only/); assert.match(el.textContent,/Inactive/);
  assert.match(el.textContent,/third_party/); assert.match(el.textContent,/unknown/);
  assert.doesNotMatch(el.textContent,/Mission setup is ready|hardware ready/i);
  assert.equal(all(el).filter(e=>e.tagName==='button' && ['Edit','Confirm','Discard'].includes(e.textContent) && !e.disabled).length,0);
});
test('confirm/discard pass the current proposal and block revision, never global revision', () => {
  assert.equal(typeof Setup.renderBlocks,'function');
  const el=root(); const seen=[];
  Setup.renderBlocks(el,snapshot(),{onConfirm:b=>seen.push(['confirm',b.current_draft_proposal_id,b.revision]),onDiscard:b=>seen.push(['discard',b.current_draft_proposal_id,b.revision])});
  find(el,e=>e.textContent==='Confirm').onclick(); find(el,e=>e.textContent==='Discard').onclick();
  assert.deepEqual(seen,[['confirm','p1',3],['discard','p1',3]]);
});
test('a successor draft is labelled Confirm, never Retry for an older uncertain operation', () => {
  const el=root();
  const actionRequests=new Map([['b1',{pending:false,body:{action:'confirm',proposal_id:'p1',expected_revision:3}}]]);
  Setup.renderBlocks(el,snapshot({blocks:[block({revision:4,current_draft_proposal_id:'normalized-p2'})]}),{actionRequests});
  assert.ok(find(el,e=>e.tagName==='button' && e.textContent==='Confirm'));
  assert.equal(find(el,e=>e.tagName==='button' && e.textContent==='Retry confirm'),undefined);
});

function planningHarness(names, extras={}) {
  const source=fs.readFileSync(path.join(__dirname,'../../web/static/planning.js'),'utf8');
  const ctx=vm.createContext({ExperimentalSetup:Setup,liveSetupSnapshot:null,liveSetupSessionId:'',liveSetupEditContext:null,
    liveSetupTransportVersion:0,liveSetupAppliedVersion:0,liveSetupActionRequests:new Map(),liveSetupNotice:'',
    liveLastSession:{},planningSessionId:'tab-local',renderLiveExperimentSetupPanel:()=>{},renderLiveChatContextStrip:()=>{},
    ...extras});
  for(const name of names) {
    const start=source.search(new RegExp('(?:async )?function '+name+'\\('));
    assert.ok(start>=0,`${name} behavior must exist`);
    const end=source.indexOf('\n}',start)+2;
    vm.runInContext(source.slice(start,end),ctx);
  }
  return ctx;
}
test('canonical session sync clears edit context only on session/deletion/inactivity, not a block revision change', () => {
  const ctx=planningHarness(['syncLiveSetupSession','acceptLiveSetupSnapshot']);
  ctx.syncLiveSetupSession({planning_session_id:'canonical-a',state:{setup:snapshot()}});
  ctx.liveSetupEditContext={block_id:'b1',revision:3};
  ctx.acceptLiveSetupSnapshot(snapshot({revision:10,blocks:[block({revision:4})]}));
  assert.equal(ctx.liveSetupEditContext.revision,3);
  ctx.acceptLiveSetupSnapshot(snapshot({revision:11,blocks:[]})); assert.equal(ctx.liveSetupEditContext,null);
  ctx.liveSetupEditContext={block_id:'b1',revision:3};
  ctx.syncLiveSetupSession({planning_session_id:'canonical-b',state:{setup:snapshot({session_id:'canonical-b',revision:1})}});
  assert.equal(ctx.liveSetupSessionId,'canonical-b'); assert.equal(ctx.liveSetupEditContext,null);
  assert.equal(ctx.liveSetupSnapshot.revision,1);
});
test('an older in-flight equal-revision response cannot undo a later graph event', () => {
  const ctx=planningHarness(['syncLiveSetupSession','acceptLiveSetupSnapshot']);
  ctx.syncLiveSetupSession({planning_session_id:'canonical-a',state:{setup:snapshot()}});
  ctx.acceptLiveSetupSnapshot(snapshot({projection_id:'graph-new',blocks:[block({editable:false})]}),{version:10});
  ctx.acceptLiveSetupSnapshot(snapshot(),{version:9});
  assert.equal(ctx.liveSetupSnapshot.projection_id,'graph-new');
});
test('newer server revision wins over earlier request dispatch without lowering transport watermarks', () => {
  const current=snapshot(), incoming=snapshot({revision:10,projection_id:'committed-action'});
  const ctx=planningHarness(['acceptLiveSetupSnapshot'],{
    liveSetupSessionId:'canonical-a',liveSetupSnapshot:current,
    liveSetupAppliedVersion:2,liveSetupTransportVersion:2,
    liveLastSession:{planning_session_id:'canonical-a',state:{setup:current}},
  });
  assert.equal(ctx.acceptLiveSetupSnapshot(incoming,{version:1}),true);
  assert.equal(ctx.liveSetupSnapshot.revision,10);
  assert.equal(ctx.liveLastSession.state.setup,incoming);
  assert.equal(ctx.liveSetupAppliedVersion,2);
  assert.equal(ctx.liveSetupTransportVersion,2);
  assert.equal(ctx.acceptLiveSetupSnapshot(snapshot({revision:10,projection_id:'older-graph'}),{version:1}),false);
  assert.equal(ctx.liveSetupSnapshot.projection_id,'committed-action');
  assert.equal(ctx.acceptLiveSetupSnapshot(snapshot({revision:8}),{version:3}),false);
  assert.equal(ctx.acceptLiveSetupSnapshot(snapshot({session_id:'foreign',revision:999}),{version:4}),false);
  assert.equal(ctx.liveSetupAppliedVersion,2);
});
test('Chat attaches pinned context only to setup_context and uses the canonical session', () => {
  const ctx=planningHarness(['collectPlanningPayload'],{collectOptionalConstraints:()=>({live_is_running:false}),
    // Another tab may have updated shared localStorage after this tab bound its snapshot.
    ensurePlanningSessionId:()=> 'other-tab-id',liveSetupSessionId:'canonical-a',planningGoalInput:null,queryGoal:'',queryBackend:'test',
    liveSetupEditContext:{block_id:'b1',revision:3}});
  const payload=ctx.collectPlanningPayload('Change goal');
  assert.ok(payload.setup_context,'context must be included on contextual Chat');
  assert.deepEqual(JSON.parse(JSON.stringify(payload.setup_context)),{block_id:'b1',revision:3});
  assert.equal(payload.session_id,'canonical-a'); assert.equal(payload.constraints.setup_context,undefined);
  ctx.liveSetupEditContext=null; assert.equal('setup_context' in ctx.collectPlanningPayload('Question'),false);
});

test('Edit opens existing Chat and focuses its untouched unsent message without fetching', () => {
  const input={value:'My unsent thought',focus(){this.focused=true;}}; const calls=[];
  const ctx=planningHarness(['onEditSetupBlock'],{planningMessageInput:input,
    liveSetupSnapshot:snapshot(),liveSetupSessionId:'canonical-a',
    setLiveChatTargetMode:t=>calls.push(t),setLiveChatCollapsed:(v,o)=>calls.push([v,o.resetUnread]),
    renderLiveChatContextStrip:()=>{},fetch:()=>{throw new Error('Edit must not fetch');}});
  ctx.onEditSetupBlock(block());
  assert.equal(input.value,'My unsent thought'); assert.equal(input.focused,true);
  assert.deepEqual(calls,['orchestrator',[false,false]]);
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.liveSetupEditContext)),{block_id:'b1',revision:3});
});
test('setup actions send exact canonical six-field body and require a distinct explicit normalized confirmation', async () => {
  const sent=[]; let next=0;
  const ctx=planningHarness(['onSetupBlockAction','acceptLiveSetupSnapshot'],{
    liveSetupSnapshot:snapshot(),liveSetupSessionId:'canonical-a',
    crypto:{randomUUID:()=>`request-${++next}`},renderLiveChatContextStrip:()=>{},
    fetch:async(url,opts)=>{sent.push([url,JSON.parse(opts.body)]); return {ok:true,json:async()=>({ok:true,message:'Review and confirm again.',
      setup:snapshot({revision:10,blocks:[block({revision:4,current_draft_proposal_id:'normalized-p2'})]})})};}});
  await ctx.onSetupBlockAction('confirm',block());
  assert.equal(sent.length,1);
  assert.deepEqual(sent[0],['/api/planning/setup/actions',{action:'confirm',proposal_id:'p1',expected_revision:3,request_id:'request-1',session_id:'canonical-a',target:'next_run'}]);
  await ctx.onSetupBlockAction('confirm',ctx.liveSetupSnapshot.blocks[0]);
  assert.equal(sent.length,2); assert.equal(sent[1][1].request_id,'request-2');
  assert.equal(sent[1][1].proposal_id,'normalized-p2'); assert.equal(sent[1][1].expected_revision,4);
});
test('transport retry keeps the identical body and request ID, never automatically retries', async () => {
  const sent=[]; let next=0;
  const ctx=planningHarness(['onSetupBlockAction','acceptLiveSetupSnapshot'],{
    liveSetupSnapshot:snapshot(),liveSetupSessionId:'canonical-a',
    crypto:{randomUUID:()=>`request-${++next}`},renderLiveChatContextStrip:()=>{},
    fetch:async(url,opts)=>{sent.push(JSON.parse(opts.body)); if(sent.length===1)throw new Error('offline');
      return {ok:true,json:async()=>({ok:true,setup:snapshot({revision:10,blocks:[block({current_draft_proposal_id:null})]}),message:'Confirmed'})};}});
  await ctx.onSetupBlockAction('confirm',block()); assert.equal(sent.length,1);
  await ctx.onSetupBlockAction('confirm',block()); assert.deepEqual(sent[0],sent[1]);
});

module.exports={block,snapshot};
