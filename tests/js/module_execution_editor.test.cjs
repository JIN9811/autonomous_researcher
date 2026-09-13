const {test} = require('node:test');
const assert = require('node:assert/strict');
const view = require('../../web/static/module_control_view.js');
let editor;
try { editor = require('../../web/static/module_execution_editor.js'); } catch { editor = {}; }
const payload = {module:{id:'fixture',label:'Fixture',pre_execution:[{id:'outer'}],execution_graph:{schema:'ax4lab.execution_graph.v1',entry:'a',nodes:[
  {id:'a',handler:'fixture.choose',area:'high',label:'Choice',config:{limit:3},position:{x:400,y:100}},
  {id:'b',handler:'fixture.result',area:'middle',label:'Result'},
  {id:'c',handler:'fixture.work',area:'knowledge',label:'Work'},
],edges:[{source:'a',target:'c',on:'yes',kind:'evidence'},{source:'a',target:'b',on:'no',kind:'validation'},{source:'c',target:'b',on:'next',kind:'execution'}],terminals:['b']}}};
const catalog = {operations:[{handler:'fixture.choose',outcomes:['yes','no'],config:{limit:{type:'integer'}}},{handler:'fixture.work',outcomes:['next'],config:{}},{handler:'fixture.result',outcomes:['next'],config:{}}]};
test('projection uses explicit executable nodes and relation kinds, omitting outer pre steps',()=>{
 const result=view.layout(payload.module);
 assert.ok(result,'execution graph must project without legacy metadata');
 assert.deepEqual(result.nodes.map(n=>n.key),['a','b','c']);
 assert.deepEqual(result.edges,payload.module.execution_graph.edges);
 assert.match(view.renderSvg(payload.module),/data-outcome="yes"/);
});
test('label and position edits preserve non-array routing, branches, config and outer policies',()=>{
 assert.equal(typeof editor.project,'function');
 const graph=editor.project(payload,catalog,'server-revision',view);
 graph.nodes[0].label='Edited'; graph.nodes[0].position={x:1000,y:300};
 const saved=editor.serialize(graph,payload);
 assert.deepEqual(saved.module.execution_graph.edges,payload.module.execution_graph.edges);
 assert.equal(saved.module.execution_graph.entry,'a');
 assert.deepEqual(saved.module.execution_graph.terminals,['b']);
 assert.deepEqual(saved.module.execution_graph.nodes[0],{...payload.module.execution_graph.nodes[0],label:'Edited',position:{x:1000,y:300}});
 assert.deepEqual(saved.module.pre_execution,[{id:'outer'}]);
 assert.equal(payload.module.execution_graph.nodes[0].label,'Choice');
});
test('registered operation addition and exact outcome edge edit/delete preserve sibling routes',()=>{
 assert.equal(typeof editor.project,'function');
 const graph=editor.project(payload,catalog,'revision',view);
 assert.throws(()=>editor.addNode(graph,'agent.arbitrary'));
 const node=editor.addNode(graph,'fixture.work',{x:200,y:200});
 assert.equal(node.handler,'fixture.work');
 editor.upsertEdge(graph,'a','b','yes','execution',{source:'a',target:'c',condition:'yes'});
 assert.deepEqual(editor.serialize(graph,payload).module.execution_graph.edges.slice(0,2),[{source:'a',target:'b',on:'no',kind:'validation'},{source:'c',target:'b',on:'next',kind:'execution'}]);
 editor.removeNode(graph,node.id);
 assert.equal(graph.nodes.length,3);
 editor.deleteEdge(graph,'a','b','yes');
 assert.ok(graph.edges.some(e=>e.condition==='no'));
 assert.equal(editor.serialize(graph,payload).module.execution_graph.edges.length,2);
});
test('trace paint requires same revision/run and latest invocation; dirty drafts and unmatched runs stay idle',()=>{
 assert.equal(typeof editor.trace,'function');
 const graph=editor.project(payload,catalog,'rev',view);
 const event=(type,node_id,invocation_id,extra={})=>({type:'execution.'+type,payload:{schema:'ax4lab.execution_trace.v1',module_id:'fixture',graph_revision:'rev',run_id:'run',loop_index:0,invocation_id,node_id,...extra}});
 const events=[event('node.started','c','new'),event('graph.started','a','new'),event('node.completed','b','old'),event('graph.started','a','old')];
 assert.deepEqual(editor.trace(graph,events,'run',false).statuses,{c:'running'});
 const late=[event('node.completed','b','old'),...events];
 assert.deepEqual(editor.trace(graph,late,'run',false).statuses,{c:'running'});
 assert.deepEqual(editor.trace(graph,[event('node.completed','b','old')],'run',false).statuses,{});
 assert.deepEqual(editor.trace(graph,events,'other',false).statuses,{});
 assert.deepEqual(editor.trace(graph,events,'run',true).statuses,{});
 graph.metadata.execution_graph_revision='different';
 assert.deepEqual(editor.trace(graph,events,'run',false).statuses,{});
});

test('removing every node keeps the empty execution definition editable and invalid',()=>{
 const graph=editor.project(payload,catalog,'rev',view);
 for(const node of [...graph.nodes])editor.removeNode(graph,node.id);
 const saved=editor.serialize(graph,payload);
 assert.deepEqual(saved.module.execution_graph.nodes,[]);
 assert.deepEqual(saved.module.execution_graph.edges,[]);
 assert.equal(saved.module.execution_graph.entry,'a');
 assert.deepEqual(editor.project(saved,catalog,'',view).nodes,[]);
 assert.deepEqual(saved.module.pre_execution,[{id:'outer'}]);
});

const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../web/static/runtime_ide.js'),'utf8');
function runtimeFunction(name,context) {
 const start=source.search(new RegExp(`(?:async )?function ${name}\\(`));
 const tail=source.slice(start),end=tail.slice(1).search(/\n(?:async )?function /)+1;
 vm.runInNewContext(end>0?tail.slice(0,end):tail,context);
 return context[name];
}
test('actual IDE reload keeps dirty same-module draft before issuing any backend read',async()=>{
 const context={graphTabs:[{id:'module:fixture',dirty:true}],MODULE_TAB_PREFIX:'module:',
 moduleSelect:{value:'fixture'},setStatus:()=>{},log:()=>{},requestJson:()=>{throw Error('dirty reload must not request');}};
 const reload=runtimeFunction('loadModule',context);
 await reload('fixture');
 assert.equal(context.graphTabs[0].dirty,true);
});
test('actual IDE structural preview clearly says owner operations were not executed',()=>{
 const context={escapeHtml:value=>String(value)};
 const markup=runtimeFunction('moduleDryRunResultMarkup',context)({ok:true,mode:'structural_preview',executes_owner_functions:false,paths:[{nodes:['a','c','b']}],sequence:[]},'fixture');
 assert.match(markup,/Structural preview/);
 assert.match(markup,/owner (?:functions|operations) (?:were )?not executed/i);
});

function requestHarness() {
 const payload=(id,label)=>({module:{id,label}});
 const design={id:'module:design',kind:'module',moduleId:'design',dirty:false,modulePayload:payload('design','original'),graph:{id:'module:design'}};
 const orc={id:'module:orchestrator',kind:'module',moduleId:'orchestrator',dirty:true,modulePayload:payload('orchestrator','ORC draft'),graph:{id:'module:orchestrator'}};
 const pending=[];
 const c={graphTabs:[design,orc],MODULE_TAB_PREFIX:'module:',activeGraphTabId:design.id,activeModuleId:'design',
   moduleSelect:{value:'design',options:[{value:'design'},{value:'orchestrator'}]},moduleRequestTokens:new Map(),moduleExecutionContracts:new Map(),moduleOpenToken:null,
   modulePayloadCache:new Map([['design',structuredClone(design.modulePayload)],['orchestrator',structuredClone(orc.modulePayload)]]),
   moduleJson:{value:JSON.stringify(design.modulePayload)},graphJson:{value:JSON.stringify(design.graph)},
   normalizedModulePayload:p=>p.module?p:{module:p},cloneConfig:structuredClone,modulePayloadFingerprint:JSON.stringify,
   isExecutionGraph:()=>false,setStatus:()=>{},log:()=>{},renderModuleTabs:()=>{},updateModuleSummary:()=>{},renderModuleGraph:()=>{},renderGraphTabs:()=>{},
   setModulePreflightEvidence:()=>{},moduleEvidenceRecord:()=>({}),moduleSavePreflightStatus:()=>({ok:true}),
   requestJson:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve})),
   activeGraphTab:()=>c.graphTabs.find(tab=>tab.id===c.activeGraphTabId),
   parseModuleEditor:()=>JSON.parse(c.moduleJson.value),parseGraphEditor:()=>JSON.parse(c.graphJson.value),
   modulePayloadToGraph:p=>({id:'module:'+p.module.id,label:p.module.label,metadata:{execution_graph_revision:c.moduleExecutionContracts.get(p.module.id)?.revision}}),
   rememberExecutionContract:(id,r)=>c.moduleExecutionContracts.set(id,{revision:r.execution_graph_revision}),
   setModuleJson:p=>{c.moduleJson.value=JSON.stringify(p);c.modulePayloadCache.set(p.module.id,structuredClone(p));},
   renderGraph:g=>{c.graphJson.value=JSON.stringify(g);},
   showRuntimeEquipmentFlowWorkspace:()=>{},
   upsertGraphTab:tab=>{const index=c.graphTabs.findIndex(item=>item.id===tab.id);if(index<0)c.graphTabs.push(tab);else Object.assign(c.graphTabs[index],tab);},
   persistModuleTabPayload:()=>{},refreshOpenModuleGraphTab:()=>{},rememberActiveGraphDraft:()=>{},
 };
 for(const name of ['moduleRequestFingerprint','captureModuleRequest','moduleRequestOwnsView','applyModuleResponse','loadModule','saveModule','openModuleGraphTab']){
   if(source.includes(`function ${name}(`))runtimeFunction(name,c);
 }
 const edit=(tab,label)=>{tab.dirty=true;tab.modulePayload=payload(tab.moduleId,label);c.modulePayloadCache.set(tab.moduleId,structuredClone(tab.modulePayload));if(c.activeGraphTabId===tab.id)c.moduleJson.value=JSON.stringify(tab.modulePayload);};
 const switchTo=tab=>{c.activeGraphTabId=tab.id;c.activeModuleId=tab.moduleId;c.moduleJson.value=JSON.stringify(tab.modulePayload);c.graphJson.value=JSON.stringify(tab.graph);};
 const response=label=>({module:payload('design',label),execution_graph_revision:'server-'+label});
 return {c,design,orc,pending,edit,switchTo,response};
}
for(const order of [[0,1],[1,0]])test(`latest different-module open wins with response order ${order.join(',')}`,async()=>{
 const {c,orc,pending,response}=requestHarness();
 orc.dirty=false;c.modulePayloadCache.clear();
 c.activeGraphTabId='main';c.activeModuleId='';
 const requests=[c.openModuleGraphTab('design'),c.openModuleGraphTab('orchestrator')];
 const responses=[response('backend'),{module:{module:{id:'orchestrator',label:'ORC backend'}},execution_graph_revision:'orc-backend'}];
 for(const index of order){pending[index].resolve(responses[index]);await requests[index];}
 assert.equal(c.activeGraphTabId,'module:orchestrator');assert.equal(c.activeModuleId,'orchestrator');
 assert.equal(c.parseModuleEditor().module.id,'orchestrator');
 assert.equal(c.modulePayloadCache.get('design').module.label,'backend');
 assert.equal(c.modulePayloadCache.get('orchestrator').module.label,'ORC backend');
 assert.equal(c.moduleExecutionContracts.get('design').revision,'server-backend');
 assert.equal(c.moduleExecutionContracts.get('orchestrator').revision,'orc-backend');
});
test('pending reload is owned by requested module, never the newly active dirty tab',async()=>{
 const {c,design,orc,pending,switchTo,response}=requestHarness();
 const loading=c.loadModule('design');switchTo(orc);pending[0].resolve(response('backend'));await loading;
 assert.equal(orc.modulePayload.module.id,'orchestrator');assert.equal(orc.dirty,true);
 assert.equal(c.modulePayloadCache.get('orchestrator').module.label,'ORC draft');
 assert.equal(c.parseModuleEditor().module.id,'orchestrator');
 assert.equal(design.modulePayload.module.label,'backend');
 assert.equal(c.moduleExecutionContracts.get('design').revision,'server-backend');
});
for(const phase of ['PUT','GET'])test(`save acknowledgement preserves edits made during ${phase} and records server baseline`,async()=>{
 const {c,design,pending,edit,response}=requestHarness();design.dirty=true;
 const saving=c.saveModule();
 if(phase==='PUT')edit(design,'new local');
 pending[0].resolve({ok:true,version:{version_id:'saved-version'}});
 await new Promise(resolve=>setImmediate(resolve));
 if(phase==='GET')edit(design,'new local');
 pending[1].resolve(response('original'));await saving;
 assert.equal(design.modulePayload.module.label,'new local');assert.equal(design.dirty,true);
 assert.equal(c.parseModuleEditor().module.label,'new local');assert.equal(c.modulePayloadCache.get('design').module.label,'new local');
 assert.equal(design.baselineModulePayload.module.label,'original');
 assert.equal(design.baselineGraph.metadata.execution_graph_revision,'server-original');
});
test('save after a tab switch updates only the saved module and preserves active ORC draft',async()=>{
 const {c,design,orc,pending,switchTo,response}=requestHarness();design.dirty=true;
 const saving=c.saveModule();switchTo(orc);pending[0].resolve({ok:true});
 await new Promise(resolve=>setImmediate(resolve));
 if(pending[1])pending[1].resolve(response('original'));await saving;
 assert.equal(design.modulePayload.module.id,'design');assert.equal(design.dirty,false);
 assert.equal(orc.modulePayload.module.label,'ORC draft');assert.equal(orc.dirty,true);
 assert.equal(c.parseModuleEditor().module.id,'orchestrator');assert.equal(c.activeModuleId,'orchestrator');
 assert.equal(c.modulePayloadCache.get('orchestrator').module.label,'ORC draft');
 assert.equal(design.baselineGraph.metadata.execution_graph_revision,'server-original');
});
for(const method of ['loadModule','openModuleGraphTab'])test(`${method} preserves edits made after its GET starts`,async()=>{
 const {c,design,pending,edit,response}=requestHarness();
 c.modulePayloadCache.delete('design'); // Exercise the existing open-tab GET path too.
 const loading=c[method]('design');edit(design,'typed during GET');
 pending[0].resolve(response('backend'));await loading;
 assert.equal(design.modulePayload.module.label,'typed during GET');assert.equal(design.dirty,true);
 assert.equal(c.parseModuleEditor().module.label,'typed during GET');
 assert.equal(design.baselineModulePayload.module.label,'backend');
});
test('an older GET cannot overwrite a later backend response for the same tab',async()=>{
 const {c,design,pending,response}=requestHarness();
 const first=c.loadModule('design'),second=c.loadModule('design');
 pending[1].resolve(response('newer'));await second;
 pending[0].resolve(response('older'));await first;
 assert.equal(design.modulePayload.module.label,'newer');
 assert.equal(c.moduleExecutionContracts.get('design').revision,'server-newer');
});
test('closing and reopening a tab while GET is pending does not replace its new draft',async()=>{
 const {c,design,pending,response}=requestHarness();
 const loading=c.loadModule('design');
 const reopened={...design,modulePayload:{module:{id:'design',label:'reopened draft'}},dirty:true};
 c.graphTabs[0]=reopened;
 pending[0].resolve(response('backend'));await loading;
 assert.equal(reopened.modulePayload.module.label,'reopened draft');assert.equal(reopened.dirty,true);
});
