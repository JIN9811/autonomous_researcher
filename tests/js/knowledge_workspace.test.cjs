const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const modulePath = require('node:path').join(__dirname, '../../web/static/knowledge_workspace.js');
const Workspace = fs.existsSync(modulePath) ? require(modulePath) : {};

// DOM boundary only; browser rendering is a separate verification claim.
class Element {
  constructor(tag, doc) { this.tagName=tag; this.ownerDocument=doc; this.children=[]; this.dataset={}; this.value=''; this.text=''; this.attributes={}; }
  set textContent(v) { this.text=String(v); this.children=[]; }
  get textContent() { return this.text+this.children.map(x=>x.textContent).join(' '); }
  set innerHTML(v) { throw Error('Unsafe HTML'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.text=''; this.children=[...nodes]; }
  setAttribute(k,v) { this.attributes[k]=String(v); }
  addEventListener(k,fn) { this['on'+k]=fn; }
}
function root() { const doc={createElement:tag=>new Element(tag,doc)}; return doc.createElement('section'); }
function all(el) { return [el,...el.children.flatMap(all)]; }
function button(el,label) { return all(el).find(x=>x.tagName==='button'&&x.textContent===label); }
const envelope=(items, extra={})=>({items,next_cursor:'',scope_ref:'public',revision:'r1',as_of:'2026-09-13T00:00:00Z',status:'ok',...extra});
function create(el, options) { assert.equal(typeof Workspace.createBrowser,'function'); return Workspace.createBrowser(el,options); }

test('old tab links enter the corresponding preserved view and unknown links open Wiki',()=>{
 assert.equal(typeof Workspace.normalizeTab,'function');
 assert.equal(Workspace.normalizeTab('markdown'),'memory');
 assert.equal(Workspace.normalizeTab('manuals'),'manuals');
 assert.equal(Workspace.normalizeTab('sources'),'manuals');
 assert.equal(Workspace.normalizeTab('delivery'),'delivery');
 assert.equal(Workspace.normalizeTab('not-a-tab'),'wiki');
});

test('record detail is text, not active HTML or automatic image fetch',async()=>{
 const el=root(); const doc={record_id:'wiki:one',topic_id:'One',freshness:'fresh',content:'<img src=https://invalid/image onerror=alert(1)>',source_refs:['docs/agents/design_agent.md']};
 const view=create(el,{kind:'wiki',request:async(url)=>envelope([doc])});
 await view.search(); await button(el,'One').onclick();
 assert.match(el.textContent,/<img src=/);
 assert.equal(all(el).some(x=>x.tagName==='img'||x.tagName==='script'),false);
});
test('late search cannot overwrite new search results or selected scope',async()=>{
 const el=root(); let release;
 const view=create(el,{kind:'wiki',request:async(url,body)=>body.query==='old'?new Promise(r=>release=r):envelope([{record_id:'wiki:new',topic_id:'New'}],{scope_ref:'new'})});
 const old=view.search({query:'old'}); await view.search({query:'new'});
 release(envelope([{record_id:'wiki:old',topic_id:'Old'}],{scope_ref:'old'})); await old;
 assert.ok(button(el,'New')); assert.equal(button(el,'Old'),undefined);
});
test('candidate confirmation uses selected revision and no automatic write on read',async()=>{
 const el=root(); const calls=[]; const record={record_id:'mem-one',kind:'preference',status:'candidate',revision:3,content:'Use concise explanations',scope:{kind:'user'},confirmation:'pending'};
 const view=create(el,{kind:'memory',request:async(url,body)=>{calls.push([url,body]); return url.endsWith('/commands')?{record_id:'mem-one',revision:4,status:'active'}:envelope([record]);}});
 await view.search(); await view.read('mem-one');
 assert.equal(calls.some(([url])=>url.endsWith('/commands')),false);
 await button(el,'Confirm memory').onclick();
 const writes=calls.filter(([url])=>url.endsWith('/commands'));
 assert.equal(writes.length,1); assert.equal(writes[0][1].action,'confirm'); assert.equal(writes[0][1].expected_revision,3);
 assert.equal(writes[0][1].target_id,'mem-one'); assert.ok(writes[0][1].idempotency_key);
 assert.equal(calls.some(([url])=>url.includes('/start')),false);
});
test('forget requires a second explicit action and clears retained detail',async()=>{
 const el=root(); let forgotten=false;
 const record={record_id:'mem-two',kind:'decision',status:'active',revision:2,content:'Synthetic private detail'};
 const view=create(el,{kind:'memory',request:async(url)=>{
  if(url.endsWith('/commands')) {forgotten=true;return {deleted:true};}
  return envelope(forgotten?[]:[record]);
 }});
 await view.search(); await view.read('mem-two'); await button(el,'Forget').onclick(); assert.equal(forgotten,false);
 await button(el,'Confirm forget').onclick(); assert.equal(forgotten,true); assert.doesNotMatch(el.textContent,/Synthetic private detail/);
});
test('denied refresh clears prior private detail and shows access state',async()=>{
 const el=root(); let denied=false;
 const view=create(el,{kind:'memory',request:async()=>{if(denied) throw Object.assign(Error('denied'),{status:401}); return envelope([{record_id:'mem-a',content:'Synthetic private detail',status:'active',revision:1}]);}});
 await view.search(); await view.read('mem-a'); denied=true; await view.search();
 assert.doesNotMatch(el.textContent,/Synthetic private detail/); assert.match(el.textContent,/trusted server identity/i);
});
test('delivery receipt preserves retrieved stage rather than marking knowledge used',async()=>{
 const el=root(); const view=create(el,{kind:'delivery',request:async()=>envelope([{receipt_id:'receipt-a',consumer_binding:'design_agent',stage:'retrieved',citation_ids:['wiki:one'],used_citation_ids:[]}])});
 await view.search(); await view.read('receipt-a');
 const stage=all(el).find(x=>x.dataset.stage); assert.equal(stage.dataset.stage,'retrieved');
});
test('pagination forwards opaque continuation with unchanged narrowing filters',async()=>{
 const el=root(); const seen=[];
 const view=create(el,{kind:'memory',request:async(url,body)=>{seen.push(body); return envelope([{record_id:body.cursor?'mem-b':'mem-a'}],{next_cursor:body.cursor?'':'opaque-cursor'});}});
 await view.search({query:'purpose',filters:{status:'active'}}); await button(el,'Load more').onclick();
 assert.deepEqual(seen[1],{query:'purpose',filters:{status:'active'},cursor:'opaque-cursor',limit:25});
});

test('unchanged background refresh preserves load-more cursor and the open detail',async()=>{
 const el=root(), seen=[]; const record={record_id:'wiki:a',topic_id:'A',content:'Open detail'};
 const view=create(el,{kind:'wiki',request:async(url,body)=>{seen.push([url,body]);return envelope([record],{next_cursor:'next-page'});}});
 await view.search(); await view.read('wiki:a'); await view.refresh();
 assert.match(el.textContent,/Open detail/); await button(el,'Load more').onclick();
 assert.equal(seen.at(-1)[1].cursor,'next-page');
});

test('changed Wiki envelope revision rereads an open detail even without row revision',async()=>{
 const el=root(); let revision='r1', reads=0;
 const view=create(el,{kind:'wiki',request:async(url)=>{
  if(url.endsWith('/read')) {reads++; return envelope([{record_id:'wiki:a',topic_id:'A',content:reads===1?'Old detail':'Refreshed detail'}],{revision});}
  return envelope([{record_id:'wiki:a',topic_id:'A'}],{revision});
 }});
 await view.search(); await view.read('wiki:a'); revision='r2'; await view.refresh();
 assert.equal(reads,2); assert.match(el.textContent,/Refreshed detail/);
});

test('unchanged background refresh does not discard an in-flight detail read',async()=>{
 const el=root(); let finish;
 const view=create(el,{kind:'wiki',request:async(url)=>url.endsWith('/read')?new Promise(resolve=>finish=resolve):envelope([{record_id:'wiki:a',topic_id:'A'}])});
 await view.search(); const read=view.read('wiki:a'); await view.refresh();
 finish(envelope([{record_id:'wiki:a',content:'Fresh detail'}])); await read;
 assert.match(el.textContent,/Fresh detail/);
});
test('unapplied edited filters do not silently reload old-scope results',async()=>{
 const el=root(); let calls=0;
 const view=create(el,{kind:'wiki',request:async()=>{calls++;return envelope([{record_id:'wiki:a',topic_id:'A'}]);}});
 await view.search(); all(el).find(x=>x.tagName==='form').oninput(); await view.refresh();
 assert.equal(calls,1); assert.equal(button(el,'A'),undefined); assert.match(el.textContent,/Apply changed filters/);
});

test('denied lifecycle command clears prior private detail',async()=>{
 const el=root(); const record={record_id:'mem-denied',kind:'preference',status:'candidate',revision:1,content:'Private before denial'};
 const view=create(el,{kind:'memory',request:async(url)=>{
  if(url.endsWith('/commands')) throw Object.assign(Error('denied'),{status:403});
  return envelope([record]);
 }});
 await view.search(); await view.read('mem-denied'); await button(el,'Confirm memory').onclick();
 assert.doesNotMatch(el.textContent,/Private before denial/); assert.match(el.textContent,/trusted server identity/i);
});

for (const status of [409,422,503]) test(`recoverable ${status} preserves the private editor draft`,async()=>{
 const el=root(), record={record_id:'mem-a',kind:'preference',status:'active',revision:1,content:'Original'};
 const view=create(el,{kind:'memory',request:async(url)=>{if(url.endsWith('/commands')) throw Object.assign(Error('retry'),{status});return envelope([record]);}});
 await view.search(); await view.read('mem-a'); await button(el,'Edit').onclick();
 const editor=all(el).find(x=>x.tagName==='textarea'); editor.value='Unsaved private draft'; editor.oninput?.();
 await button(el,'Save memory').onclick();
 assert.equal(all(el).find(x=>x.tagName==='textarea')?.value,'Unsaved private draft');
 assert.match(el.textContent,/draft|review/i);
});
test('background revisions preserve editor and block stale save until explicit current-revision review',async()=>{
 const el=root(); let revision=1, writes=[];
 const view=create(el,{kind:'memory',request:async(url,body)=>{
  if(url.endsWith('/commands')) {writes.push(body); return {};}
  return envelope([{record_id:'mem-a',kind:'preference',status:'active',revision,content:'Server '+revision}],{revision:'r'+revision});
 }});
 await view.search(); await view.read('mem-a'); await button(el,'Edit').onclick();
 const editor=all(el).find(x=>x.tagName==='textarea'); editor.value='Draft'; editor.oninput?.();
 revision=2; await view.refresh();
 assert.equal(all(el).find(x=>x.tagName==='textarea')?.value,'Draft');
 await button(el,'Save memory').onclick(); assert.equal(writes.length,0);
 await button(el,'Review current revision').onclick();
 assert.equal(all(el).find(x=>x.tagName==='textarea')?.value,'Draft');
 await button(el,'Save memory').onclick(); assert.equal(writes[0].expected_revision,2);
});
test('scope loss clears an editor draft on background refresh',async()=>{
 const el=root(); let scope='alice';
 const view=create(el,{kind:'memory',request:async()=>envelope([{record_id:'mem-a',kind:'preference',status:'active',revision:1,content:'Private'}],{scope_ref:scope})});
 await view.search(); await view.read('mem-a'); await button(el,'Edit').onclick();
 scope='bob'; await view.refresh(); assert.equal(all(el).some(x=>x.tagName==='textarea'),false);
});
test('Workspace deep links resolve exact authorized read and handle denied or stale targets',async()=>{
 assert.equal(typeof Workspace.openTarget,'function');
 for(const [kind,id] of [['wiki','wiki:design-role'],['memory','mem-'+'a'.repeat(32)],['delivery','delivery-'+'b'.repeat(32)]]) {
  const calls=[], el=root(); let code=0;
  const view=create(el,{kind,request:async(url,body)=>{calls.push([url,body]);if(code)throw Object.assign(Error('missing'),{status:code});return envelope([{record_id:id,content:'Authorized detail'}]);}});
  await Workspace.openTarget({[kind]:view},`#${kind}/${encodeURIComponent(id)}`);
  assert.equal(calls[0][0],`/api/knowledge/${kind}/read`);assert.equal(calls[0][1].record_id,id);
  for(code of [401,404]) {await Workspace.openTarget({[kind]:view},`#${kind}/${encodeURIComponent(id)}`);assert.doesNotMatch(el.textContent,/Authorized detail/);}
 }
 assert.deepEqual(Workspace.parseTarget('#memory/secret%2Fpath'),{tab:'memory',recordId:''});
});
test('Workspace detail renders scope revision expiry timestamps and exact delivery lists',async()=>{
 const el=root(), row={receipt_id:'delivery-a',stage:'used',scope_ref:'scope-a',revision:7,created_at:'created',updated_at:'updated',expires_at:'expiry',citation_ids:['wiki:a','wiki:b'],delivered_citation_ids:['wiki:b'],used_citation_ids:['wiki:b']};
 const view=create(el,{kind:'delivery',request:async()=>envelope([row])});await view.read('delivery-a');
 assert.match(el.textContent,/Retrieved: wiki:a, wiki:b/);assert.match(el.textContent,/Delivered: wiki:b/);assert.match(el.textContent,/Used: wiki:b/);
 for(const text of ['scope-a','revision 7','created','updated','expiry']) assert.ok(el.textContent.includes(text));
});
test('failed current revision review keeps its editor draft visible',async()=>{
 const el=root();let failed=false;
 const view=create(el,{kind:'memory',request:async()=>{if(failed)throw Object.assign(Error('retry'),{status:503});return envelope([{record_id:'mem-a',status:'active',revision:1,content:'Original'}]);}});
 await view.search();await view.read('mem-a');await button(el,'Edit').onclick();
 const editor=all(el).find(x=>x.tagName==='textarea');editor.value='Draft';editor.oninput();failed=true;
 await button(el,'Review current revision').onclick();assert.equal(all(el).find(x=>x.tagName==='textarea')?.value,'Draft');
});

for(const latest of ['hash','tab']) test(`new ${latest} navigation prevents an older awaited hash from reopening its detail`,async()=>{
 const source=fs.readFileSync(require('node:path').join(__dirname,'../../web/static/knowledge.js'),'utf8');
 const activate=source.slice(source.indexOf('async function activateTab('),source.indexOf('async function refreshWorkspace()'));
 const open=source.slice(source.indexOf('async function openWorkspaceLocation()'),source.indexOf('refreshWorkspace().then(openWorkspaceLocation)'));
 const reads=[], refreshes=[], cleared=[];
 const view={clear:()=>cleared.push('cleared'),refresh:()=>new Promise(resolve=>refreshes.push(resolve)),read:async(id)=>reads.push(id)};
 const context={AX4LABKnowledgeWorkspace:Workspace,scopedKnowledgeViews:{wiki:view},workspaceNavigationGeneration:0,
  document:{querySelectorAll:()=>[]},window:{location:{hash:'#wiki/wiki%3Aa'},history:{replaceState:(_state,_title,hash)=>{context.window.location.hash=hash;}}}};
 const vm=require('node:vm');vm.createContext(context);vm.runInContext(activate+open,context);
 const first=context.openWorkspaceLocation();
 if(latest==='hash') context.window.location.hash='#wiki/wiki%3Ab';
 const second=latest==='hash'?context.openWorkspaceLocation():context.activateTab('wiki');
 refreshes[1]();await second;
 refreshes[0]();await first;
 assert.deepEqual(reads,latest==='hash'?['wiki:b']:[]);
 assert.equal(context.window.location.hash,latest==='hash'?'#wiki/wiki%3Ab':'#wiki');
 assert.equal(cleared.length,2,'each new navigation invalidates the previous detail immediately');
});

test('navigation clear followed by same-revision refresh reloads rows without restoring private detail or draft',async()=>{
 const el=root(), record={record_id:'mem-a',kind:'preference',status:'active',revision:1,content:'Private original'};
 let queries=0;
 const view=create(el,{kind:'memory',request:async(url)=>{if(url.endsWith('/query'))queries++;return envelope([record],{scope_ref:'private:alice',revision:'unchanged'});}});
 await view.search();await view.read('mem-a');await button(el,'Edit').onclick();
 const editor=all(el).find(x=>x.tagName==='textarea');editor.value='Private draft';editor.oninput();
 view.clear();
 assert.equal(button(el,'preference'),undefined);assert.equal(all(el).some(x=>x.tagName==='textarea'),false);
 assert.doesNotMatch(el.textContent,/Private original|Private draft/);
 await view.refresh();
 assert.equal(queries,2);assert.ok(button(el,'preference'));
 assert.equal(all(el).some(x=>x.tagName==='textarea'),false);assert.doesNotMatch(el.textContent,/Private original|Private draft/);
});
