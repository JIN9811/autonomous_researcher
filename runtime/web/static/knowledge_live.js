/* Pure presentation and admission helpers shared by Live Knowledge cards/chat. */
(function(global){
  'use strict';
  let requestSequence=0;
  function requestId(cryptoApi=global.crypto) {
    return cryptoApi?.randomUUID?.() || `knowledge-${Date.now()}-${++requestSequence}-${Math.random().toString(36).slice(2)}`;
  }
  const escape=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function memoryCommand(messages,target,action,requestId) {
    if(!['confirm','dismiss'].includes(action)) return null;
    const entry=[...(messages || [])].reverse().find(msg=>msg.memory_pending_command?.target_id===target);
    const receipt=entry?.memory_receipt, pending=entry?.memory_pending_command;
    if(!receipt || receipt.status!=='candidate' || receipt.record_id!==target || receipt.revision!==pending.expected_revision) return null;
    return {action,target_id:target,expected_revision:receipt.revision,idempotency_key:requestId,payload:{}};
  }
  function canPersist(session,summary) {
    if(!summary || summary.scope_ref!=='public') return false;
    const keys=new Set(['reference_only','knowledge_delivery','knowledge_request','memory_receipt','memory_pending_command','citation_metadata']);
    const seen=new WeakSet();
    const contains=value=>{
      if(!value || typeof value!=='object' || seen.has(value)) return false;
      seen.add(value);
      return Object.entries(value).some(([key,item])=>(keys.has(key) && item != null) || contains(item));
    };
    return !contains(session);
  }
  function requestKind(message={}) {
    if(message.memory_receipt || message.memory_pending_command) return 'Memory update';
    if(message.setup_proposal || message.setup_context) return 'Setup proposal';
    if(message.execution || message.run_id || message.loop_id) return 'Execution';
    return message.knowledge_request || message.knowledge_delivery || message.citation_metadata ? 'Question' : 'No retrieval yet';
  }
  function responseId(message={},fallback='') {
    return String(message.message_id || message.decision_id || message.request_id || fallback);
  }
  function selectedResponseEvidence(messages,selectedResponseId='') {
    const list=Array.isArray(messages)?messages:[];
    const selected=String(selectedResponseId || '');
    const message=selected ? list.find(entry=>responseId(entry)===selected) || null : null;
    if(!message) return {response_id:'',request:'No retrieval yet',scope_ref:'public',revision:'',retrieved_at:'',source_count:0,memory_activity:'None',status:'No retrieval yet',citation_ids:[]};
    const delivery=message.knowledge_delivery && typeof message.knowledge_delivery==='object'?message.knowledge_delivery:{};
    const metadata=message.citation_metadata && typeof message.citation_metadata==='object'?message.citation_metadata:{};
    const sources=Array.isArray(message.sources)?message.sources:[];
    const receipt=message.memory_receipt && typeof message.memory_receipt==='object'?message.memory_receipt:null;
    const stage=String(delivery.stage || delivery.status || '').toLowerCase();
    const stale=sources.some(source=>source && source.freshness && source.freshness!=='fresh');
    const status=stale?'Needs review':stage==='no_match'?'No match':stage==='unavailable'?'Unavailable':stage?'Retrieved':'No retrieval yet';
    const memoryActivity=receipt?.status==='candidate'?'Confirmation pending':receipt?.status==='active'?'Memory saved':receipt?.status==='deleted'?'Memory dismissed':receipt?.status==='unavailable'?'Memory unavailable':receipt?.status?`Memory response: ${String(receipt.status)}`:'None';
    return {response_id:responseId(message),request:requestKind(message),scope_ref:String(metadata.scope_ref || delivery.scope_ref || 'public'),revision:String(metadata.revision || delivery.revision || ''),retrieved_at:String(delivery.updated_at || delivery.created_at || message.created_at || message.timestamp || ''),source_count:sources.length,memory_activity:memoryActivity,status,citation_ids:(sources.length?sources:delivery.citation_ids || []).map(item=>typeof item==='string'?item:String(item?.citation_id || item?.record_id || '')).filter(Boolean)};
  }
  function deliveryStatus(delivery) {
    const stage=String(delivery?.stage || '').toLowerCase(), status=String(delivery?.status || '').toLowerCase();
    if(status==='unavailable' || stage==='unavailable') return 'Unavailable';
    if(delivery?.use_status==='unknown') return 'Unknown';
    if(!stage) return 'Not requested';
    if(stage==='no_match') return 'No match';
    if(stage==='not_requested') return 'Not requested';
    if(stage==='not_delivered') return 'Not delivered';
    if(stage==='retrieved') return 'Retrieved';
    if(stage==='delivered') return 'Delivered';
    if(stage==='used') return 'Used';
    if(stage==='excluded') return 'Excluded';
    return 'Unknown';
  }
  function consumerId(value) { return String(value || '').toLowerCase().replace(/_agent$/, '').replace(/[^a-z0-9]+/g,''); }
  function scopedValue(value,key) {
    if(!value || typeof value!=='object') return '';
    if(key==='loop_id') return String(value.loop_id ?? '');
    return String(value[key] ?? '');
  }
  function currentReceipt(receipt,provenance) {
    for(const key of ['run_id','loop_id','attempt_id']) {
      const expected=String(provenance?.[key] ?? '');
      if(expected && scopedValue(receipt,key)!==expected) return false;
    }
    return true;
  }
  function reportReceipts(reports,provenance={}) {
    const out=[];
    const visit=(value,inherited={},depth=0)=>{
      if(!value || typeof value!=='object' || depth>10) return;
      if(Array.isArray(value)) { for(const item of value) visit(item,inherited,depth+1); return; }
      const scope={...inherited};
      for(const key of ['agent_id','run_id','loop_id','attempt_id','decision_id','report_id']) if(scopedValue(value,key)) scope[key]=scopedValue(value,key);
      const delivery=value.knowledge_delivery;
      if(delivery && typeof delivery==='object') {
        const receipt={...scope,...delivery};
        if(currentReceipt(receipt,provenance)) out.push(receipt);
      }
      for(const [key,item] of Object.entries(value)) if(key!=='knowledge_delivery') visit(item,scope,depth+1);
    };
    for(const report of Array.isArray(reports)?reports:[]) visit(report,{},0);
    return out;
  }
  function deliverySummary(reports,agents,selectedAgent='',provenance={}) {
    const active=(Array.isArray(agents)?agents:[]).filter(agent=>agent && agent.enabled!==false && agent.kind!=='ui_only');
    const list=Array.isArray(reports)?reports:[];
    const receipts=reportReceipts(list,provenance);
    const rows=active.map(agent=>{
      const id=consumerId(agent.id);
      const delivery=[...receipts].reverse().find(entry=>consumerId(entry.consumer_binding)===id) || null;
      const report=list.find(entry=>consumerId(entry?.agent_id)===id);
      const availability=report ? String(report.availability || 'available') : 'unavailable';
      const status=delivery?deliveryStatus(delivery):(availability==='available'?'Unknown':availability==='not_requested'?'Not requested':'Unavailable');
      return {agent_id:String(agent.id),label:String(agent.label || agent.id),status,decision_id:String(delivery?.decision_id || ''),decision_at:String(delivery?.updated_at || delivery?.created_at || ''),citation_ids:Array.isArray(delivery?.citation_ids)?delivery.citation_ids:[],used_citation_ids:Array.isArray(delivery?.used_citation_ids)?delivery.used_citation_ids:[],receipt_id:String(delivery?.receipt_id || ''),run_id:String(delivery?.run_id || ''),loop_id:String(delivery?.loop_id || ''),attempt_id:String(delivery?.attempt_id || '')};
    });
    return {rows,selected:rows.find(row=>row.agent_id===selectedAgent) || {agent_id:String(selectedAgent || ''),label:String(selectedAgent || 'Selected agent'),status:'Unknown',decision_id:'',decision_at:'',citation_ids:[],used_citation_ids:[],receipt_id:'',run_id:'',loop_id:'',attempt_id:''}};
  }
  function memoryReceiptPresentation(receipt) {
    const status=String(receipt?.status || 'unknown');
    if(status==='active') return {terminal:true,label:'Memory saved'};
    if(status==='deleted') return {terminal:true,label:'Memory dismissed'};
    return {terminal:false,label:`Memory response: ${status} (not confirmed)`};
  }
  function messageHTML(message,knownReceipt=null) {
    const sources=Array.isArray(message.sources)?message.sources:[];
    let html='';
    if(sources.length) html+=`<details class="knowledge-chat-sources"><summary>Sources (${sources.length})</summary><ul>${sources.slice(0,10).map(s=>`<li><a href="${workspaceHref(s.citation_id || s.record_id)}" target="_blank" rel="noopener">${escape(s.citation_id || s.record_id)}</a>${['string','number'].includes(typeof s.revision)?` · revision ${escape(String(s.revision).slice(0,160))}`:''}</li>`).join('')}</ul></details>`;
    const receipt=knownReceipt || message.memory_receipt;
    if(receipt?.status==='candidate' && message.memory_pending_command) {
      const target=escape(receipt.record_id);
      html+=`<div class="knowledge-chat-memory"><span>Memory candidate</span> <button type="button" class="btn tiny" data-knowledge-memory-target="${target}" data-knowledge-memory-action="confirm">Confirm memory</button> <button type="button" class="btn tiny" data-knowledge-memory-target="${target}" data-knowledge-memory-action="dismiss">Dismiss</button></div>`;
    } else if(receipt?.status==='active') html+='<small class="knowledge-chat-memory">Memory saved</small>';
    else if(receipt?.status==='deleted') html+='<small class="knowledge-chat-memory">Memory dismissed</small>';
    else if(receipt?.status==='unavailable') html+='<small class="knowledge-chat-memory">Private memory unavailable</small>';
    else if(receipt?.status) html+=`<small class="knowledge-chat-memory">${escape(memoryReceiptPresentation(receipt).label)}</small>`;
    if(message.temporary_memory || receipt?.scope?.kind==='session' || receipt?.scope?.kind==='run') html+='<small class="knowledge-chat-memory">Temporary context</small>';
    return html;
  }
  function workspaceHref(id) {
    const value=String(id || '');
    const tab=/^wiki:[A-Za-z0-9_-]{1,160}$/.test(value)?'wiki':/^mem-[a-f0-9]{32}$/.test(value)?'memory':/^delivery-[a-f0-9]{32}$/.test(value)?'delivery':'';
    return tab?`/knowledge#${tab}/${encodeURIComponent(value)}`:'/knowledge#wiki';
  }
  const api={memoryCommand,canPersist,messageHTML,requestId,selectedResponseEvidence,deliverySummary,memoryReceiptPresentation,workspaceHref};
  if(typeof module!=='undefined'&&module.exports) module.exports=api; else global.AX4LABKnowledgeLive=api;
})(typeof window!=='undefined'?window:globalThis);
