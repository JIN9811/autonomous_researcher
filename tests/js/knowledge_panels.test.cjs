const test=require('node:test'),assert=require('node:assert/strict');
test('supply preserves chart above table without an inner colored box',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const css=fs.readFileSync(path.join(__dirname,'../../web/static/knowledge_panels.css'),'utf8');
  const js=fs.readFileSync(path.join(__dirname,'../../web/static/planning.js'),'utf8');
  assert.match(js,/class="knp-supply-layout"/);
  assert.match(js,/<details class="knp-supply-details"><summary>Details<\/summary>/);
  assert.match(css,/\.knp-supply-layout\s*\{[^}]*display:block/);
  assert.doesNotMatch(css, /background:#(?:10202e|132432|172c3a)/);
});
test('supply categories share a horizontal x-axis with vertical bars',()=>{
  const html=P.supplyChart({rows:[{label:'Design',status:'Delivered',citation_ids:['a'],used_citation_ids:[]},{label:'Vision',status:'Unavailable'}]});
  assert.match(html,/data-orientation="vertical"/);
  const labels=[...html.matchAll(/<text class="knp-agent-label" x="([\d.]+)" y="([\d.]+)"/g)];
  assert.equal(labels.length,2);assert.notEqual(labels[0][1],labels[1][1]);assert.equal(labels[0][2],labels[1][2]);
});
test('ORC response knowledge panel follows all orchestration report cards',()=>{
  const src=require('node:fs').readFileSync(require('node:path').join(__dirname,'../../web/static/planning.js'),'utf8');
  const body=src.slice(src.indexOf('function renderOrchestratorDashboardCards('),src.indexOf('function mergeDesignCandidateRecord('));
  assert.ok(body.indexOf('data-live-knowledge-body="orc"')>body.indexOf('Next Action / Audit'));
});
let P={};try{P=require('../../web/static/knowledge_panels.js');}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
test('knowledge panels display evidence inline without links or disclosure arrows',()=>{
  const html=P.library({wiki:{count:2}})+P.response({knowledge_delivery:{citation_ids:['wiki:a']}})+P.delivery({rows:[{label:'Design',status:'Delivered',receipt_id:'r',citation_ids:[],used_citation_ids:[]}]});
  assert.doesNotMatch(html,/<a\s|<details|<summary/);
});
test('no snapshot and no recorded cycles are distinct, without manufactured zeros',()=>{
  assert.match(P.activity?.(null,{run_id:'r'})||'',/Not loaded/);
  const html=P.activity?.({run_id:'r',cycles:[],totals:{used:0}},{run_id:'r'})||'';
  assert.match(html,/No recorded activity/);assert.doesNotMatch(html,/>0</);
});
test('activity rejects other run data and labels recorded counts without adding them',()=>{
  assert.match(P.activity?.({run_id:'old',cycles:[{used:100}]},{run_id:'r'})||'',/Not loaded/);
  const html=P.activity?.({run_id:'r',cycles:[{cycle_id:'loop-1',collected:3,updated:0,retrieved:2,used:1,event_count:2}]},{run_id:'r'})||'';
  assert.match(html,/loop-1/);assert.match(html,/>3</);assert.match(html,/>0</);assert.doesNotMatch(html,/Total operations/);
});
test('library counts do not claim freshness or reviewed status; inaccessible memory is not zero',()=>{
  const html=P.library?.({status:'ok',wiki:{count:13},memory:{count:0,status:'public_only'},scope_ref:'public'})||'';
  assert.match(html,/>13</);assert.match(html,/Not accessible/);assert.doesNotMatch(html,/reviewed|freshness checked|>0</);
});
test('response evidence distinguishes supplied candidates from actually cited knowledge',()=>{
  const html=P.response?.({message_id:'r',knowledge_delivery:{stage:'delivered',citation_ids:['wiki:a'],use_status:'unknown'},sources:[]})||'';
  assert.match(html,/Delivered/);assert.match(html,/Not recorded/);assert.doesNotMatch(html,/Memory saved/);
});
test('response proof uses its own IDs and escapes source labels',()=>{
  const html=P.response?.({knowledge_delivery:{stage:'used',citation_ids:['wiki:a'],used_citation_ids:['wiki:a']},sources:[{citation_id:'wiki:a',title:'<script>bad</script>'}]})||'';
  assert.match(html,/wiki:a/);assert.doesNotMatch(html,/<script>/);
});
test('patterns and improvement findings stay visible, not reduced to counts',()=>{
  const text='Observed failure context '.repeat(12);
  const html=P.patterns({failure_patterns:[{summary:text,agent_id:'design'}]})+P.findings([{target_id:'analysis',summary:'Refine evidence handling',status:'proposed'}],[]);
  assert.ok(html.includes(text));assert.match(html,/Refine evidence handling/);
  assert.doesNotMatch(html,/<details|<summary|<a\s/);
});
test('supply bar chart distinguishes observed counts from missing records without topology edges',()=>{
  const html=P.supplyChart({rows:[{label:'Design',status:'Delivered',receipt_id:'r',citation_ids:['a','b']},{label:'BO',status:'Unavailable'}]});
  assert.match(html,/<svg/);assert.match(html,/Design/);assert.match(html,/BO/);
  assert.match(html,/>2<\/text>/);assert.match(html,/Not recorded/);
  assert.doesNotMatch(html,/100%|success rate|<path/);
});
