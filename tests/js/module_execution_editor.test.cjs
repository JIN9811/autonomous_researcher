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
test('model badges distinguish a High decision from a process calling it without changing the route',()=>{
 const module=structuredClone(payload.module);
 module.execution_graph.nodes[0].llm=true;
 module.execution_graph.nodes[1].llm=true;
 const before=JSON.stringify(module);
 const svg=view.renderSvg(module);
 const decision=svg.split('<g><title>a · fixture.choose</title>')[1].split('</g>')[0];
 const caller=svg.split('<g><title>b · fixture.result</title>')[1].split('</g>')[0];
 const ordinary=svg.split('<g><title>c · fixture.work</title>')[1].split('</g>')[0];
 assert.match(decision,/>LLM<\/text>/);
 assert.doesNotMatch(decision,/>LLM call<\/text>/);
 assert.match(caller,/>LLM call<\/text>/);
 assert.doesNotMatch(ordinary,/>LLM(?: call)?<\/text>/);
 assert.equal(JSON.stringify(module),before);
});
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

test('module request fingerprint ignores a hidden stale editor while Package Manager is active',()=>{
 const tabPayload={module:{id:'knowledge',owner_plan:{settings:{decision_max_steps:6}}}};
 const staleEditor={module:{id:'knowledge',owner_plan:{settings:{decision_max_steps:4}}}};
 const tab={id:'module:knowledge',kind:'module',moduleId:'knowledge',modulePayload:tabPayload,graph:{id:'module:knowledge'}};
 const context={MODULE_TAB_PREFIX:'module:',graphTabs:[tab,{id:'packages',kind:'packages'}],modulePayloadCache:new Map([['knowledge',tabPayload]]),
   activeModuleId:'knowledge',activeGraphTabId:'packages',modulePayloadFingerprint:JSON.stringify,
   parseModuleEditor:()=>staleEditor,parseGraphEditor:()=>({id:'stale-editor-graph'})};
 const fingerprint=runtimeFunction('moduleRequestFingerprint',context)('knowledge',tab);
 const [payloadFingerprint,graphFingerprint]=JSON.parse(fingerprint);
 assert.equal(payloadFingerprint,JSON.stringify(tabPayload));
 assert.deepEqual(graphFingerprint,{id:'module:knowledge'});
});

test('module request fingerprint uses cache when Package Manager is active without an owner tab',()=>{
 const cached={module:{id:'knowledge',owner_plan:{settings:{decision_max_steps:6}}}};
 const staleEditor={module:{id:'knowledge',owner_plan:{settings:{decision_max_steps:4}}}};
 const context={MODULE_TAB_PREFIX:'module:',graphTabs:[{id:'packages',kind:'packages'}],
   modulePayloadCache:new Map([['knowledge',cached]]),activeModuleId:'knowledge',activeGraphTabId:'packages',
   modulePayloadFingerprint:JSON.stringify,parseModuleEditor:()=>staleEditor,parseGraphEditor:()=>({})};
 const fingerprint=runtimeFunction('moduleRequestFingerprint',context)('knowledge',null);
 const [payloadFingerprint,graphFingerprint]=JSON.parse(fingerprint);
 assert.equal(payloadFingerprint,JSON.stringify(cached));
 assert.equal(graphFingerprint,null);
});

test('module request fingerprint keeps the editor path outside auxiliary views without an owner tab',()=>{
 const cached={module:{id:'knowledge',owner_plan:{settings:{decision_max_steps:6}}}};
 const editor={module:{id:'knowledge',owner_plan:{settings:{decision_max_steps:7}}}};
 const context={MODULE_TAB_PREFIX:'module:',graphTabs:[{id:'main',kind:'main'}],
   modulePayloadCache:new Map([['knowledge',cached]]),activeModuleId:'knowledge',activeGraphTabId:'main',
   modulePayloadFingerprint:JSON.stringify,parseModuleEditor:()=>editor,parseGraphEditor:()=>({})};
 const fingerprint=runtimeFunction('moduleRequestFingerprint',context)('knowledge',null);
 assert.equal(JSON.parse(fingerprint)[0],JSON.stringify(editor));
});

test('Package Manager owner controls validate drafts and explicitly apply only the selected owner module',async()=>{
 const packageHelpers=require('../../web/static/experimental_packages.js');
 const status={className:'',textContent:''};
 const requests=[];
 const knowledge={module:{id:'knowledge',handler:'agent.knowledge_agent',notes:'knowledge kept'}};
 const guardian={module:{id:'guardian',handler:'agent.guardian_agent',notes:'guardian kept'}};
 const context={
   AX4LABExperimentalPackages:packageHelpers,modulePayloadCache:new Map([
     ['knowledge',structuredClone(knowledge)],['guardian',structuredClone(guardian)],
   ]),graphTabs:[],MODULE_TAB_PREFIX:'module:',moduleRequestTokens:new Map(),moduleOpenToken:null,activeModuleId:'',activeGraphTabId:'main',
   experimentalPackageDraft:null,
   packageCompositionOutput:{querySelector:()=>status},cloneConfig:structuredClone,
   modulePayloadFingerprint:JSON.stringify,markModulePreflightDirty:()=>{},renderPackageComposition:()=>{},log:()=>{},
   requestJson:async(url,options)=>{requests.push({url,options});return url.endsWith('/validate')
     ?{ok:true,errors:[]}:{ok:true,errors:[],activated:true,version:{version_id:'plan-version'}};},
 };
 for(const name of ['moduleRequestFingerprint','captureModuleRequest','moduleRequestDraftState','ownerPlanRequestDraftState','ownerPlanModulePayload','storeOwnerPlanDraft','setOwnerPlanControlStatus','updateOwnerPlanDraftFromControls','validateOwnerPlanControl','applyOwnerPlanControl'])runtimeFunction(name,context);
 context.ownerPlanControlValues=()=>({mode:'configured',id:'knowledge_reference',version:'1.0.0',contractVersion:'1.0.0',settingsText:'{"corpora":["markdown"]}'});

 await context.validateOwnerPlanControl('knowledge');
 assert.equal(requests[0].url,'/api/modules/knowledge/validate');
 assert.equal(JSON.parse(requests[0].options.body).activate,false);
 assert.deepEqual(context.modulePayloadCache.get('knowledge').module.owner_plan.settings,{corpora:['markdown']});
 assert.equal(context.modulePayloadCache.get('guardian').module.owner_plan,undefined);
 assert.match(status.textContent,/Draft valid/);

 await context.applyOwnerPlanControl('knowledge');
 assert.equal(requests[1].url,'/api/modules/knowledge');
 assert.equal(JSON.parse(requests[1].options.body).activate,true);
 assert.match(status.textContent,/Applied/);

 context.ownerPlanControlValues=()=>({mode:'configured',id:'knowledge_reference',version:'1.0.0',contractVersion:'1.0.0',settingsText:'[]'});
 const rejected=await context.validateOwnerPlanControl('knowledge');
 assert.equal(rejected.ok,false);
 assert.equal(requests.length,2);
 assert.match(status.textContent,/settings.*object/i);

 context.ownerPlanControlValues=()=>({mode:'default',id:'knowledge_reference',version:'1.0.0',contractVersion:'1.0.0',settingsText:'{}'});
 await context.applyOwnerPlanControl('knowledge');
 assert.equal(JSON.parse(requests[2].options.body).module.module.owner_plan,undefined);
 assert.equal(context.modulePayloadCache.get('guardian').module.notes,'guardian kept');
});

function ownerPlanRequestHarness({withTab=true}={}) {
 const packageHelpers=require('../../web/static/experimental_packages.js');
 const payload=steps=>({module:{id:'knowledge',handler:'agent.knowledge_agent',owner_plan:{
   schema:'ax4lab.owner_plan.v1',id:'knowledge_reference',owner:'knowledge',version:'1.0.0',contract_version:'1.0.0',
   settings:{corpora:['markdown'],decision_max_steps:steps},
 }}});
 const graphFor=value=>({id:'module:knowledge',steps:value.module.owner_plan.settings.decision_max_steps});
 const initial=payload(5);
 const tab={id:'module:knowledge',kind:'module',moduleId:'knowledge',modulePayload:payload(6),graph:graphFor(payload(6)),
   baselineModulePayload:structuredClone(initial),baselineGraph:graphFor(initial),dirty:true};
 const status={className:'runtime-owner-plan-status warn',textContent:'Draft changed: Unsaved.'};
 const pending=[];
 const c={
   AX4LABExperimentalPackages:packageHelpers,MODULE_TAB_PREFIX:'module:',moduleRequestTokens:new Map(),moduleOpenToken:null,
   modulePayloadCache:new Map([['knowledge',structuredClone(tab.modulePayload)]]),
   graphTabs:[...(withTab?[tab]:[]),{id:'packages',kind:'packages'}],
   activeModuleId:'knowledge',activeGraphTabId:'packages',moduleJson:{value:JSON.stringify(payload(4))},graphJson:{value:'{}'},
   experimentalPackageDraft:null,packageCompositionOutput:{querySelector:()=>status},cloneConfig:structuredClone,
   modulePayloadFingerprint:JSON.stringify,modulePayloadToGraph:graphFor,
   parseModuleEditor:()=>JSON.parse(c.moduleJson.value),parseGraphEditor:()=>JSON.parse(c.graphJson.value),
   currentGraphTabKind:()=> 'packages',
   markModulePreflightDirty:()=>{},renderPackageComposition:()=>{},renderGraphTabs:()=>{},log:()=>{},
   moduleEvidenceRecord:()=>({}),rememberExecutionContract:()=>{},setModuleJson:()=>{},updateModuleSummary:()=>{},
   renderModuleGraph:()=>{},renderModuleTabs:()=>{},renderGraph:()=>{},moduleSelect:null,
   requestJson:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve})),
 };
 for(const name of ['moduleRequestFingerprint','captureModuleRequest','moduleRequestOwnsView','moduleRequestDraftState','ownerPlanRequestDraftState',
   'ownerPlanModulePayload','storeOwnerPlanDraft','setOwnerPlanControlStatus','updateOwnerPlanDraftFromControls',
   'validateOwnerPlanControl','applyOwnerPlanControl']) {
   if(source.includes(`function ${name}(`))runtimeFunction(name,c);
 }
 let steps=6,settingsText=JSON.stringify({corpora:['markdown'],decision_max_steps:steps});
 c.ownerPlanControlValues=()=>({mode:'configured',id:'knowledge_reference',version:'1.0.0',contractVersion:'1.0.0',
   settingsText});
 const edit=value=>{steps=value;settingsText=JSON.stringify({corpora:['markdown'],decision_max_steps:steps});c.updateOwnerPlanDraftFromControls('knowledge');};
 const editRaw=value=>{settingsText=value;c.updateOwnerPlanDraftFromControls('knowledge');};
 const success={ok:true,errors:[],activated:true,version:{version_id:'owner-plan-version'}};
 return {c,tab,status,pending,payload,graphFor,edit,editRaw,success};
}

test('owner plan Apply acknowledges the sent snapshot while preserving edits made during PUT',async()=>{
 const {c,tab,status,pending,edit,success}=ownerPlanRequestHarness();
 const applying=c.applyOwnerPlanControl('knowledge');
 edit(7);
 assert.equal(JSON.parse(pending[0].options.body).module.module.owner_plan.settings.decision_max_steps,6);

 pending[0].resolve(success);await applying;

 assert.equal(tab.modulePayload.module.owner_plan.settings.decision_max_steps,7);
 assert.equal(c.modulePayloadCache.get('knowledge').module.owner_plan.settings.decision_max_steps,7);
 assert.equal(tab.baselineModulePayload.module.owner_plan.settings.decision_max_steps,6);
 assert.equal(tab.baselineGraph.steps,6);
 assert.equal(tab.graph.steps,7);
 assert.equal(tab.dirty,true);
 assert.match(status.textContent,/Draft changed/);
});

test('owner plan Validate cannot mark a newer unsent draft valid',async()=>{
 const {c,tab,status,pending,edit}=ownerPlanRequestHarness();
 const validating=c.validateOwnerPlanControl('knowledge');
 edit(7);
 pending[0].resolve({ok:true,errors:[]});await validating;

 assert.equal(tab.modulePayload.module.owner_plan.settings.decision_max_steps,7);
 assert.equal(tab.dirty,true);
 assert.match(status.textContent,/Draft changed/);
 assert.doesNotMatch(status.textContent,/Draft valid/);
});

test('only the latest overlapping owner plan Apply may update acknowledgement state',async()=>{
 const {c,tab,status,pending,edit,success}=ownerPlanRequestHarness();
 const first=c.applyOwnerPlanControl('knowledge');
 edit(7);
 const second=c.applyOwnerPlanControl('knowledge');

 pending[1].resolve(success);await second;
 pending[0].resolve(success);await first;

 assert.equal(tab.modulePayload.module.owner_plan.settings.decision_max_steps,7);
 assert.equal(tab.baselineModulePayload.module.owner_plan.settings.decision_max_steps,7);
 assert.equal(tab.baselineGraph.steps,7);
 assert.equal(tab.dirty,false);
 assert.match(status.textContent,/Applied/);
});

test('owner plan response cannot mutate a closed and reopened module tab',async()=>{
 const {c,tab,status,pending,payload,graphFor,success}=ownerPlanRequestHarness();
 const applying=c.applyOwnerPlanControl('knowledge');
 const reopenedPayload=payload(7);
 const reopened={...tab,modulePayload:reopenedPayload,graph:graphFor(reopenedPayload),
   baselineModulePayload:payload(5),baselineGraph:graphFor(payload(5)),dirty:true};
 c.graphTabs[0]=reopened;
 status.textContent='Reopened draft: Unsaved.';

 pending[0].resolve(success);await applying;

 assert.equal(reopened.modulePayload.module.owner_plan.settings.decision_max_steps,7);
 assert.equal(reopened.baselineModulePayload.module.owner_plan.settings.decision_max_steps,5);
 assert.equal(reopened.baselineGraph.steps,5);
 assert.equal(reopened.dirty,true);
 assert.match(status.textContent,/Reopened draft/);
});

for(const operation of ['Apply','Validate'])test(`owner plan ${operation} with no owner tab preserves a newer cache draft`,async()=>{
 const {c,status,pending,edit,success}=ownerPlanRequestHarness({withTab:false});
 const request=operation==='Apply'?c.applyOwnerPlanControl('knowledge'):c.validateOwnerPlanControl('knowledge');
 edit(7);
 pending[0].resolve(operation==='Apply'?success:{ok:true,errors:[]});await request;

 assert.equal(c.modulePayloadCache.get('knowledge').module.owner_plan.settings.decision_max_steps,7);
 assert.match(status.textContent,/Draft changed/);
 assert.doesNotMatch(status.textContent,/Applied|Draft valid/);
});

for(const operation of ['Apply','Validate'])test(`owner plan ${operation} response preserves newer invalid settings text`,async()=>{
 const {c,tab,status,pending,editRaw,success}=ownerPlanRequestHarness();
 const request=operation==='Apply'?c.applyOwnerPlanControl('knowledge'):c.validateOwnerPlanControl('knowledge');
 editRaw('{bad');
 assert.match(status.textContent,/Draft invalid/);
 pending[0].resolve(operation==='Apply'?success:{ok:true,errors:[]});await request;

 assert.equal(tab.baselineModulePayload.module.owner_plan.settings.decision_max_steps,operation==='Apply'?6:5);
 assert.equal(tab.baselineGraph.steps,operation==='Apply'?6:5);
 assert.equal(tab.dirty,true);
 assert.match(status.textContent,/Draft invalid/);
 assert.doesNotMatch(status.textContent,/Applied|Draft valid/);
});

test('readiness applies a local catalog only to its matching module graph and never to the outer graph',()=>{
 const catalog={schema:'ax4lab.execution_catalog.v1',module_id:'knowledge',operations:[{handler:'knowledge.task'}]};
 const context={
   activeGraph:null,latestStateSnapshot:{state:{}},activeModuleId:'knowledge',availableHandlers:['global.handler'],availableModules:[{id:'knowledge'}],
   moduleExecutionContracts:new Map([['knowledge',{catalog}]]),runModeSelect:{value:'test'},activationEvidence:{validation:{ok:true},dry_run:{ok:true},compile:{ok:true},dirty:false},
   moduleCatalogById:()=>new Map([['knowledge',{id:'knowledge'}]]),logicalTransitionEdges:()=>[],nodeMapByStageOrId:nodes=>new Map(nodes.flatMap(node=>[[node.id,node],[node.stage,node]].filter(([key])=>key))),
   nodeStage:node=>node.stage||node.id,normalizeModuleIdRef:value=>String(value||'').replace(/^modules\//,'').trim(),handlerMetadataStatus:()=>({kind:'ok'}),
   livePreflightStatus:draft=>({moduleTab:draft?.metadata?.ide_tab_kind==='module',draftClean:true,gateOk:true,liveMode:false,confirmed:false}),
   moduleSavePreflightStatus:()=>({ok:true,validationOk:true,dryRunOk:true}),modulePayloadForGraphDraft:()=>({}),
 };
 const readiness=runtimeFunction('runtimeReadinessStatus',context);
 const node=handler=>({id:'task',stage:'knowledge',kind:'agent',handler});
 const moduleGraph={metadata:{ide_tab_kind:'module',module_id:'knowledge'},entry_node:'task',finish_nodes:['task'],nodes:[node('knowledge.task')],edges:[]};
 const mismatchedGraph={...moduleGraph,metadata:{...moduleGraph.metadata,module_id:'guardian',execution_catalog:catalog}};
 const outerGraph={metadata:{},entry_node:'task',finish_nodes:['task'],nodes:[node('knowledge.task')],edges:[]};
 const unknownGraph={...moduleGraph,nodes:[node('knowledge.unknown')]};

 assert.deepEqual(readiness(moduleGraph).missingHandlers,[]);
 assert.deepEqual(readiness(mismatchedGraph).missingHandlers.map(item=>item.handler),['knowledge.task']);
 assert.deepEqual(readiness(outerGraph).missingHandlers.map(item=>item.handler),['knowledge.task']);
 assert.deepEqual(readiness(unknownGraph).missingHandlers.map(item=>item.handler),['knowledge.unknown']);
});

test('installed Equipment opens its catalog-backed execution graph and keeps Skill Flow as a side workspace',async()=>{
 const normalized={module:{id:'equipment',label:'Lab Equipment',execution_graph:{entry:'task',nodes:[{id:'task'}],edges:[],terminals:['task']}}};
 const projected={id:'module:equipment',metadata:{ide_tab_kind:'module',module_id:'equipment',execution_graph_revision:'rev'},nodes:[{id:'task'}]};
 const tabs=[];const workspace=[];let rendered=null;
 const context={MODULE_TAB_PREFIX:'module:',moduleOpenToken:null,modulePayloadCache:new Map(),graphTabs:tabs,moduleRequestTokens:new Map(),moduleExecutionContracts:new Map(),runtimeEquipmentFlowProfileId:'utm_windows_v1',runtimeEquipmentFlowPayload:{graph:{id:'equipment-skill-flow'}},
   activeGraphTabId:'main',activeModuleId:'',moduleSelect:{value:''},normalizedModulePayload:p=>p.module?p:{module:p},cloneConfig:structuredClone,
   captureModuleRequest:id=>({moduleId:id,fingerprint:'f'}),moduleRequestOwnsView:()=>true,applyModuleResponse:()=>true,
   requestJson:async()=>({module:normalized,execution_graph_revision:'rev'}),setModuleJson:()=>{},updateModuleSummary:()=>{},rememberActiveGraphDraft:()=>{},
   showRuntimeEquipmentFlowWorkspace:value=>workspace.push(value),loadRuntimeEquipmentSkillFlow:async()=>({graph:{id:'equipment-skill-flow'}}),
   modulePayloadToGraph:()=>projected,renderModuleGraph:()=>{},renderGraph:g=>{rendered=g;},log:()=>{},
   upsertGraphTab:tab=>tabs.push(tab),
 };
 const open=runtimeFunction('openModuleGraphTab',context);
 await open('equipment');
 assert.equal(tabs[0].subtitle,'agent internal map');
 assert.equal(tabs[0].graph.id,'module:equipment');
 assert.equal(rendered.id,'module:equipment');
 assert.deepEqual(workspace,[true]);
});

test('Equipment Skill Flow refresh cannot overwrite a catalog-backed module tab graph',async()=>{
 const executionGraph={id:'module:equipment',metadata:{execution_graph_revision:'rev'}};
 const tab={id:'module:equipment',moduleId:'equipment',modulePayload:{module:{id:'equipment',execution_graph:{entry:'task'}}},graph:executionGraph,baselineGraph:structuredClone(executionGraph),dirty:false};
 let rendered=0,workspaceRendered=0;
 const context={MODULE_TAB_PREFIX:'module:',runtimeEquipmentFlowProfileId:'utm_windows_v1',runtimeEquipmentProfiles:[],runtimeEquipmentFlowPayload:{},
   graphTabs:[tab],activeGraphTabId:'module:equipment',cloneConfig:structuredClone,
   requestJson:async url=>url==='/api/equipment/profiles'?{profiles:[{profile_id:'utm_windows_v1'}]}:{graph:{id:'equipment-skill-flow'}},
   renderRuntimeEquipmentSkillFlow:()=>{workspaceRendered+=1;},renderGraph:()=>{rendered+=1;},
 };
 const refresh=runtimeFunction('loadRuntimeEquipmentSkillFlow',context);
 await refresh('utm_windows_v1');
 assert.equal(tab.graph.id,'module:equipment');
 assert.equal(tab.baselineGraph.id,'module:equipment');
 assert.equal(rendered,0);
 assert.equal(workspaceRendered,1);
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
 for(const name of ['moduleRequestFingerprint','captureModuleRequest','moduleRequestOwnsView','moduleRequestDraftState','applyModuleResponse','loadModule','saveModule','openModuleGraphTab']){
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
