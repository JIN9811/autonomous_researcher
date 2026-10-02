/* Evidence-only Live panels. Counts are observations, never completion scores. */
(function(root){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const count=v=>v!=null&&v!==''&&Number.isFinite(Number(v))&&Number(v)>=0?Number(v):null;
  const metric=(label,value,note='')=>`<div class="knp-metric"><span>${esc(label)}</span><strong>${value==null?'—':esc(value)}</strong>${note?`<small>${esc(note)}</small>`:''}</div>`;
  const empty=text=>`<p class="knp-empty">${esc(text)}</p>`;
  const scope=p=>`<div class="knp-scope"><span>Current run · ${esc(p.run_id||'Not bound')}</span>${p.loop_id!==undefined?`<span>Loop ${esc(Number(p.loop_id)+1)}</span>`:''}</div>`;
  function activity(snapshot,provenance={},error='') {
    if(!snapshot || snapshot.run_id!==provenance.run_id)return empty(error?'Activity unavailable — refresh failed.':'Not loaded for this run.');
    const rows=Array.isArray(snapshot.cycles)?snapshot.cycles:[];
    const keys=['collected','updated','retrieved','used'];
    const maximum=Math.max(1,...rows.flatMap(r=>keys.map(k=>count(r[k])||0)));
    const last=rows.map(r=>r.last_occurred_at||'').sort().pop();
    const bar=v=>{const n=count(v);return n===null?'—':`<span class="knp-bar"><svg viewBox="0 0 100 6" aria-hidden="true" preserveAspectRatio="none"><rect width="100" height="6" fill="#263c4b"/><rect width="${n/maximum*100}" height="6" fill="#62b8cc"/></svg><b>${n}</b></span>`;};
    return `<div class="knp">${scope(provenance)}${error?empty('Cached activity · refresh failed'):''}${!rows.length?empty('No recorded activity for this run.'): `<div class="knp-table-wrap"><table><caption>Recorded counts · latest ${rows.length} of ${esc(snapshot.available_cycle_count??rows.length)} cycles</caption><thead><tr><th>Cycle</th>${keys.map(k=>`<th>${k[0].toUpperCase()+k.slice(1)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr><th title="${esc((r.consumers||[]).join(', '))}">${esc(r.cycle_id)}</th>${keys.map(k=>`<td>${bar(r[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}${last?`<small>Latest recorded event · ${esc(last)}</small>`:''}${snapshot.malformed_line_count?`<p class="knp-warning">${esc(snapshot.malformed_line_count)} unreadable ledger lines; counts may be incomplete.</p>`:''}</div>`;
  }
  function library(summary,error='') {
    if(!summary)return empty('Library snapshot unavailable or loading.');
    const accessible=summary.memory?.status!=='public_only'&&summary.scope_ref!=='public';
    return `<div class="knp"><div class="knp-scope">Accessible library · not current-run activity${error?' · cached, refresh failed':''}</div><div class="knp-metrics">${metric('Wiki pages',count(summary.wiki?.count),'Indexed')}${metric('Memory records',accessible?count(summary.memory?.count):null,accessible?'Accessible scope':'Not accessible in public scope')}</div></div>`;
  }
  function delivery(model,provenance={},href=()=>'/knowledge#delivery') {
    const rows=model?.rows||[];
    if(!rows.length)return empty('Consumer registry not loaded.');
    return `<div class="knp">${scope(provenance)}<div class="knp-table-wrap"><table><thead><tr><th>Consumer</th><th>Recorded state</th><th>Retrieved</th><th>Used</th><th>Evidence</th></tr></thead><tbody>${rows.map(r=>{const observed=Boolean(r.receipt_id||r.decision_id||r.citation_ids?.length||['Retrieved','Delivered','Used','No match','Excluded'].includes(r.status));return `<tr><th>${esc(r.label)}</th><td><span class="knp-state" data-state="${esc(r.status)}">${esc(r.status==='Unavailable'?'No current evidence':r.status)}</span></td><td>${observed?r.citation_ids.length:'—'}</td><td>${r.used_citation_ids.length?r.used_citation_ids.length:r.status==='No match'||r.status==='Excluded'?'0':'—'}</td><td>${r.receipt_id?`Recorded`:'—'}</td></tr>`;}).join('')}</tbody></table></div><small>Retrieved or delivered does not imply used. — = not recorded.</small></div>`;
  }
  function supplyChart(model={}) {
    const rows=model.rows||[];
    if(!rows.length)return '';
    const values=rows.map(r=>({label:String(r.label||'Agent').replace(/ Supervisor Module| Agent Module| Module/g,''),retrieved:r.receipt_id||r.citation_ids?.length||['Retrieved','Delivered','Used','No match'].includes(r.status)?(r.citation_ids||[]).length:null,used:r.used_citation_ids?.length||(r.status==='No match'||r.status==='Excluded'?0:null)}));
    const max=Math.max(1,...values.flatMap(r=>[r.retrieved||0,r.used||0]));
    const width=Math.max(650,rows.length*90+50),step=(width-50)/rows.length;
    const marks=values.map((r,i)=>{const x=40+(i+.5)*step;return `<text class="knp-agent-label" x="${x}" y="198" text-anchor="middle" fill="#c4d5e1" font-size="14">${r.label.split(' ').map((word,j)=>`<tspan x="${x}" dy="${j?13:0}">${esc(word)}</tspan>`).join('')}</text>`+[['retrieved','#68b6cf',-17],['used','#83cbb1',3]].map(([key,color,dx])=>{const n=r[key],h=n===null?0:n/max*135;return `${n===null?'':`<rect x="${x+dx}" y="${175-h}" width="14" height="${h}" rx="2" fill="${color}"/>`}<text x="${x+dx+7}" y="${165-h}" text-anchor="middle" fill="${color}" font-size="14">${n===null?'—':n}</text>`;}).join('');}).join('');
    return `<div class="knp-supply-chart"><div class="knp-legend"><span>Retrieved</span><span>Used</span><span>— Not recorded</span></div><svg viewBox="0 0 ${width} 230" data-orientation="vertical" role="img" aria-label="Agent retrieval and use counts"><title>Recorded source counts by agent; missing records are not zero</title><line x1="40" x2="${width-10}" y1="175" y2="175" stroke="#354a5b"/>${marks}</svg></div>`;
  }
  function response(message,href=()=>'/knowledge#wiki') {
    if(!message)return empty('Select an orchestrator response to inspect its evidence.');
    const d=message.knowledge_delivery||{},sources=Array.isArray(message.sources)?message.sources:[];
    const retrieved=Array.isArray(d.citation_ids)?d.citation_ids:sources.map(s=>s.citation_id||s.record_id).filter(Boolean);
    const used=Array.isArray(d.used_citation_ids)?d.used_citation_ids:null;
    const stage=String(d.stage||d.status||''),memory=message.memory_receipt;
    const labels={retrieved:'Retrieved',delivered:'Delivered',used:'Used',no_match:'No match',unavailable:'Unavailable',excluded:'Excluded',not_requested:'Not requested'};
    const status=labels[stage]||'Not recorded';
    const usedCount=used?.length??(stage==='no_match'?0:null);
    return `<div class="knp"><div class="knp-scope">Selected response · ${esc(status)}</div><div class="knp-metrics">${metric('Retrieved',retrieved.length||('citation_ids' in d||sources.length?0:null))}${metric('Delivery',stage==='delivered'||stage==='used'?'Confirmed':null,stage==='retrieved'?'Retrieval only':'')}${metric('Used',usedCount,usedCount===null?'Not recorded':'Explicit citation record')}</div>${retrieved.length?`<div class="knp-table-wrap"><table><thead><tr><th>Source</th><th>Use in this response</th></tr></thead><tbody>${retrieved.map(id=>`<tr><td>${esc(id)}</td><td>${used?.includes(id)?'Cited':used?'Not cited':'Not recorded'}</td></tr>`).join('')}</tbody></table></div>`:empty(stage==='no_match'?'No matching sources were returned.':'No source records attached to this response.')}<div class="knp-memory-line">Memory · ${esc(memory?({candidate:'Confirmation pending',active:'Saved',deleted:'Dismissed',unavailable:'Unavailable'}[memory.status]||'Outcome not recorded'):'No memory operation recorded')}</div></div>`;
  }
  function patterns(report={}) {
    const rows=[...(report.failure_patterns||[]).map(x=>['Failure',x]),...(report.success_patterns||[]).map(x=>['Success',x])];
    if(!rows.length)return empty('No learned patterns recorded in this report.');
    return '<div class="knp knp-table-wrap"><table><thead><tr><th>Type</th><th>Finding</th><th>Context</th></tr></thead><tbody>'+rows.map(([kind,p])=>`<tr><td>${kind}</td><td>${esc(p.summary||p.description||p.name||p.failure_code||'No summary recorded')}</td><td>${esc(p.agent_id||p.agent||p.stage||'—')}</td></tr>`).join('')+'</tbody></table></div>';
  }
  function findings(packs=[],outcomes=[]) {
    const rows=[...packs.map(x=>['Proposal',x]),...outcomes.map(x=>['Outcome',x])];
    if(!rows.length)return empty('No improvement evidence recorded in this report.');
    return '<div class="knp knp-table-wrap"><table><thead><tr><th>Type</th><th>Target</th><th>Finding</th><th>Status</th></tr></thead><tbody>'+rows.map(([kind,p])=>`<tr><td>${kind}</td><td>${esc(p.target_id||p.target_type||'—')}</td><td>${esc(p.summary||p.description||p.reason||'No summary recorded')}</td><td>${esc(p.status||'Not recorded')}</td></tr>`).join('')+'</tbody></table></div>';
  }
  const api={activity,library,delivery,response,patterns,findings,supplyChart};
  if(typeof module!=='undefined')module.exports=api;else root.AX4LABKnowledgePanels=api;
})(typeof window!=='undefined'?window:this);
