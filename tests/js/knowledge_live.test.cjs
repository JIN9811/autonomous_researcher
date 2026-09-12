const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs');
const file=require('node:path').join(__dirname,'../../web/static/knowledge_live.js');
const Live=fs.existsSync(file)?require(file):{};
test('source links select their own corpus and opaque record without private text',()=>{
 const memory='mem-'+'a'.repeat(32), receipt='delivery-'+'b'.repeat(32);
 const html=Live.messageHTML({sources:[{citation_id:'wiki:design-role'},{citation_id:memory,title:'PRIVATE NAME',content:'PRIVATE BODY'}]});
 assert.ok(html.includes('/knowledge#wiki/wiki%3Adesign-role'));
 assert.ok(html.includes('/knowledge#memory/'+memory));
 assert.doesNotMatch(html,/PRIVATE NAME|PRIVATE BODY/);
 assert.equal(Live.workspaceHref(receipt),'/knowledge#delivery/'+receipt);
 assert.equal(Live.workspaceHref('private/path'),'/knowledge#wiki');
});
test('finalized absent citation displays Unknown while retaining delivered accounting',()=>{
 const model=Live.deliverySummary([{agent_id:'design',knowledge_delivery:{consumer_binding:'design_agent',stage:'delivered',use_status:'unknown',citation_ids:['wiki:a']}}],[{id:'design'}],'design');
 assert.equal(model.selected.status,'Unknown');
});
test('actual selected delivery link opens its receipt rather than a generic tab',()=>{
 const source=fs.readFileSync(require('node:path').join(__dirname,'../../web/static/planning.js'),'utf8');
 const code=source.slice(source.indexOf('function renderLiveDeliverySummary()'),source.indexOf('function renderLiveKnowledgeSummary('));
 const receipt='delivery-'+'b'.repeat(32);
 const context={window:{AX4LABKnowledgeLive:Live},liveKnowledgeDeliveryReports:()=>[{agent_id:'design',knowledge_delivery:{consumer_binding:'design_agent',receipt_id:receipt,stage:'delivered'}}],liveKnowledgeActiveConsumers:()=>[{id:'design'}],liveSelectedAgent:'design',liveKnowledgeProvenance:()=>({}),escapeHtml:String};
 require('node:vm').createContext(context);require('node:vm').runInContext(code,context);
 assert.ok(context.renderLiveDeliverySummary().includes('/knowledge#delivery/'+receipt));
});
test('memory request IDs remain available on LAN HTTP without randomUUID',()=>{
 assert.equal(typeof Live.requestId,'function');
 assert.equal(Live.requestId({randomUUID:()=> 'uuid'}),'uuid');
 const a=Live.requestId({}), b=Live.requestId({});
 assert.ok(a.length>10); assert.notEqual(a,b);
});
test('memory action accepts only current candidate target and cannot produce runtime command',()=>{
 assert.equal(typeof Live.memoryCommand,'function');
 const messages=[{memory_receipt:{record_id:'mem-a',revision:2,status:'candidate'},memory_pending_command:{target_id:'mem-a',expected_revision:2}}];
 const command=Live.memoryCommand(messages,'mem-a','confirm','request-a');
 assert.deepEqual(command,{action:'confirm',target_id:'mem-a',expected_revision:2,idempotency_key:'request-a',payload:{}});
 assert.equal(Live.memoryCommand(messages,'foreign','confirm','request-b'),null);
 assert.equal(Live.memoryCommand(messages,'mem-a','start_run','request-c'),null);
 messages[0].memory_receipt.status='active'; assert.equal(Live.memoryCommand(messages,'mem-a','confirm','request-d'),null);
});
test('knowledge-bound session content cannot enter persistent Live HTML cache',()=>{
 assert.equal(typeof Live.canPersist,'function');
 assert.equal(Live.canPersist({messages:[{content:'ordinary runtime'}]}, {scope_ref:'public'}),true);
 assert.equal(Live.canPersist({messages:[{knowledge_request:true,content:'private request'}]}, {scope_ref:'public'}),false);
 assert.equal(Live.canPersist({state:{nested:{knowledge_delivery:{scope_ref:'scoped:synthetic'}}}}, {scope_ref:'public'}),false);
 assert.equal(Live.canPersist({messages:[]},{scope_ref:'scoped:synthetic'}),false);
 assert.equal(Live.canPersist({messages:[]},null),false);
});
test('sources and memory chips escape hostile values and do not invent saved status',()=>{
 assert.equal(typeof Live.messageHTML,'function');
 const html=Live.messageHTML({sources:[{citation_id:'<img onerror=x>',revision:'1'}],memory_receipt:{status:'candidate',record_id:'mem-a'},memory_pending_command:{target_id:'mem-a',expected_revision:1}});
 assert.match(html,/Sources \(1\)/); assert.match(html,/&lt;img/); assert.doesNotMatch(html,/<img/);
 assert.match(html,/Confirm memory/); assert.doesNotMatch(html,/Memory saved/);
});

test('actual Live cache writer removes a knowledge-bound snapshot instead of serializing it',()=>{
 const source=fs.readFileSync(require('node:path').join(__dirname,'../../web/static/planning.js'),'utf8');
 const code=source.slice(source.indexOf('function persistLivePlanningCache('),source.indexOf('function restoreCachedPlanningState('));
 const writes=[], removed=[];
 const context={liveSessionStorage:()=>({setItem:(...v)=>writes.push(v),removeItem:key=>removed.push(key)}),planningSessionCacheKey:()=> 'synthetic-cache',planningSessionId:'session',
  liveKnowledgeSummary:{scope_ref:'public'},window:{AX4LABKnowledgeLive:Live}};
 require('node:vm').createContext(context);require('node:vm').runInContext(code,context);
 context.persistLivePlanningCache({planning_session_id:'session',messages:[{knowledge_request:true,content:'synthetic private text'}]});
 assert.deepEqual(writes,[]); assert.deepEqual(removed,['synthetic-cache']);
});

test('ORC evidence requires the explicitly selected response ID and never borrows another transcript entry',()=>{
 assert.equal(typeof Live.selectedResponseEvidence,'function');
 const messages=[
  {message_id:'old',role:'orchestrator',knowledge_delivery:{stage:'used',consumer_binding:'orchestrator_agent',citation_ids:['wiki:old']},citation_metadata:{scope_ref:'public',revision:'old-revision'},sources:[{citation_id:'wiki:old',revision:'old-revision'}],created_at:'2026-09-13T01:00:00Z'},
  {message_id:'current',role:'orchestrator',knowledge_delivery:{stage:'no_match',consumer_binding:'orchestrator_agent',citation_ids:[]},citation_metadata:{scope_ref:'public',revision:'current-revision'},sources:[],created_at:'2026-09-13T02:00:00Z'},
  {message_id:'other-agent',role:'design_ai',knowledge_delivery:{stage:'used',consumer_binding:'design_agent',citation_ids:['wiki:design']},citation_metadata:{scope_ref:'public',revision:'other-revision'},sources:[{citation_id:'wiki:design'}]},
 ];
 const current=Live.selectedResponseEvidence(messages,'current');
 assert.equal(current.response_id,'current'); assert.equal(current.status,'No match'); assert.equal(current.revision,'current-revision'); assert.equal(current.source_count,0);
 assert.equal(Live.selectedResponseEvidence(messages,'missing').status,'No retrieval yet');
 assert.equal(Live.selectedResponseEvidence(messages).status,'No retrieval yet');
});

test('delivery summary projects current agent-report receipts with exact run loop and attempt provenance',()=>{
 assert.equal(typeof Live.deliverySummary,'function');
 const agents=[{id:'design',label:'Design Agent',enabled:true,kind:'agent'},{id:'vision',label:'Vision Agent',enabled:true,kind:'agent'},{id:'bo',label:'BO Agent',enabled:true,kind:'agent'}];
 const reports=[
  {agent_id:'design',run_id:'run-current',sections:{role_specific:{design_decision:{decision_id:'design-current',knowledge_delivery:{receipt_id:'delivery-design',consumer_binding:'design_agent',stage:'retrieved',citation_ids:['wiki:design'],run_id:'run-current',loop_id:'4',attempt_id:'attempt-2',updated_at:'2026-09-13T02:00:00Z'}}}}},
  {agent_id:'design',run_id:'run-old',sections:{role_specific:{design_decision:{decision_id:'design-old',knowledge_delivery:{receipt_id:'delivery-old',consumer_binding:'design_agent',stage:'used',citation_ids:['wiki:old'],used_citation_ids:['wiki:old'],run_id:'run-old',loop_id:'3',attempt_id:'attempt-1'}}}}},
  {agent_id:'vision',run_id:'run-current',sections:{role_specific:{vision_decision:{decision_id:'vision-current',knowledge_delivery:{receipt_id:'delivery-vision',consumer_binding:'vision_agent',stage:'delivered',citation_ids:['wiki:vision'],run_id:'run-current',loop_id:'4',attempt_id:'attempt-2',updated_at:'2026-09-13T02:01:00Z'}}}}},
  {agent_id:'bo',run_id:'run-current',sections:{role_specific:{decision_id:'bo-current'}}},
 ];
 const model=Live.deliverySummary(reports,agents,'vision',{run_id:'run-current',loop_id:'4',attempt_id:'attempt-2'});
 assert.deepEqual(model.rows.map(row=>[row.agent_id,row.status]),[['design','Retrieved'],['vision','Delivered'],['bo','Unknown']]);
 assert.equal(model.selected.agent_id,'vision'); assert.deepEqual(model.selected.citation_ids,['wiki:vision']);
 assert.equal(model.selected.run_id,'run-current'); assert.equal(model.selected.loop_id,'4'); assert.equal(model.selected.attempt_id,'attempt-2');
});

test('Live delivery projection reads current runtime metadata rather than chat transcript messages',()=>{
 const source=fs.readFileSync(require('node:path').join(__dirname,'../../web/static/planning.js'),'utf8');
 const start=source.indexOf('function liveKnowledgeDeliveryReports()');
 const end=source.indexOf('function renderOrcKnowledgeEvidence()',start);
 assert.ok(start>=0 && end>start);
 const context={
  liveLastSession:{state:{run_id:'run-current',run_metadata:{design_agent_payload:{decisions:[{decision_id:'design-current',knowledge_delivery:{receipt_id:'delivery-design',consumer_binding:'design_agent',stage:'retrieved',citation_ids:['wiki:design'],run_id:'run-current',loop_id:'4',attempt_id:'attempt-2'}}]}},messages:[{message_id:'chat-only',knowledge_delivery:{consumer_binding:'vision_agent',stage:'used',run_id:'run-current',loop_id:'4',attempt_id:'attempt-2'}}]}},
  liveLastSnapshot:{},liveKnowledgeActiveConsumers:()=>[{id:'design'}],agentIdFromStage:()=>'',String,
 };
 require('node:vm').createContext(context);require('node:vm').runInContext(source.slice(start,end),context);
 const projected=context.liveKnowledgeDeliveryReports();
 const model=Live.deliverySummary(projected,[{id:'design',label:'Design Agent',enabled:true,kind:'agent'}],'design',{run_id:'run-current',loop_id:'4',attempt_id:'attempt-2'});
 assert.equal(model.selected.status,'Retrieved'); assert.equal(model.selected.receipt_id,'delivery-design');
});

test('Live delivery availability distinguishes an idle unrequested consumer from a missing projection',()=>{
 const source=fs.readFileSync(require('node:path').join(__dirname,'../../web/static/planning.js'),'utf8');
 const start=source.indexOf('function liveKnowledgeDeliveryReports()');
 const end=source.indexOf('function renderOrcKnowledgeEvidence()',start);
 const agents=[{id:'design'},{id:'vision'},{id:'bo'}];
 const context={liveLastSession:{state:{run_id:'run-current',agent_status:{vision_agent:{state:'idle'}},run_metadata:{design_agent_payload:{decisions:[]}}}},liveLastSnapshot:{},liveKnowledgeActiveConsumers:()=>agents,agentIdFromStage:()=>'',String};
 require('node:vm').createContext(context);require('node:vm').runInContext(source.slice(start,end),context);
 const reports=context.liveKnowledgeDeliveryReports();
 const model=Live.deliverySummary(reports,agents.map(agent=>({...agent,label:agent.id,enabled:true,kind:'agent'})),'vision',{run_id:'run-current'});
 assert.deepEqual(model.rows.map(row=>[row.agent_id,row.status]),[['design','Unknown'],['vision','Not requested'],['bo','Unavailable']]);
});

test('ORC response selector rejects operator messages even when generic role inference falls back to ORC',()=>{
 const source=fs.readFileSync(require('node:path').join(__dirname,'../../web/static/planning.js'),'utf8');
 const start=source.indexOf('function liveSelectedOrcResponses()');
 const end=source.indexOf('function liveKnowledgeProvenance()',start);
 const context={selectedMessages:()=>[{message_id:'operator-request',role:'operator',knowledge_request:true},{message_id:'orc-response',role:'orchestrator',knowledge_delivery:{stage:'retrieved'}}],liveKnowledgeResponseId:message=>String(message.message_id || ''),agentIdFromMessage:()=> 'orchestrator',String};
 require('node:vm').createContext(context);require('node:vm').runInContext(source.slice(start,end),context);
 assert.deepEqual(context.liveSelectedOrcResponses().map(message=>message.message_id),['orc-response']);
});

test('only explicit terminal memory receipts are rendered as terminal outcomes',()=>{
 assert.equal(typeof Live.memoryReceiptPresentation,'function');
 assert.deepEqual(Live.memoryReceiptPresentation({status:'active'}),{terminal:true,label:'Memory saved'});
 assert.deepEqual(Live.memoryReceiptPresentation({status:'deleted'}),{terminal:true,label:'Memory dismissed'});
 assert.deepEqual(Live.memoryReceiptPresentation({status:'candidate'}),{terminal:false,label:'Memory response: candidate (not confirmed)'});
});
