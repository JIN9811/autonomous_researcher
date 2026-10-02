/* Scoped Knowledge views. No private content is persisted in browser storage. */
(function (global) {
  'use strict';
  async function request(url, body) {
    const response = await fetch(url, {method: body === undefined ? 'GET' : 'POST',
      cache: 'no-store', credentials: 'same-origin',
      ...(body === undefined ? {} : {headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)})});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(typeof data.detail === 'string' ? data.detail : 'Knowledge request failed'), {status: response.status});
    return data;
  }
  // Reviewed Wiki Markdown only. Never parse HTML or load arbitrary remote images.
  // Public figures reuse the published repository; no private file-serving route.
  const publicRepo='https://github.com/JIN9811/autonomous_researcher/blob/main/';
  const publicRaw='https://raw.githubusercontent.com/JIN9811/autonomous_researcher/main/';
  function wikiUrl(value, image=false) {
    if(!value || /[\\\s?#%]/.test(value) || value.startsWith('/') || /^[a-z]+:/i.test(value)) return '';
    const path=new URL(value,'https://wiki.invalid/docs/knowledge/wiki/').pathname.slice(1);
    if(image) return /^docs\/(?:agents\/assets\/figures|assets\/modularity)\/[a-zA-Z0-9_-]+\.(?:svg|png|webp)$/.test(path)?publicRaw+path:'';
    const topic=path.match(/^docs\/knowledge\/wiki\/([a-zA-Z0-9_-]+)\.md$/);
    if(topic) return '#wiki/'+encodeURIComponent('wiki:'+topic[1]);
    return /^docs\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.md$/.test(path) && !path.includes('/oldversion/') && !path.includes('/sources/')?publicRepo+path:'';
  }
  function renderWikiBody(doc, content) {
    const make=(tag,text='',cls='')=>{const el=doc.createElement(tag);el.textContent=text;el.className=cls;return el;};
    const root=make('div','','knowledge-wiki-body');
    function inline(parent,text) {
      const pattern=/(!?)\[([^\]\n]*)\]\(([^)\n]+)\)|\*\*([^*\n]+)\*\*|`([^`\n]+)`/g;
      let end=0;
      for(const m of text.matchAll(pattern)) {
        if(m.index>end) parent.append(make('span',text.slice(end,m.index)));
        if(m[4]) parent.append(make('strong',m[4]));
        else if(m[5]) parent.append(make('code',m[5]));
        else {
          const isImage=m[1]==='!',url=wikiUrl(m[3],isImage);
          if(!url) parent.append(make('span',m[2] || m[0]));
          else if(isImage) {
            const figure=make('figure'),img=make('img');
            img.src=url;img.alt=m[2];img.loading='lazy';img.referrerPolicy='no-referrer';
            const unavailable=()=>figure.replaceChildren(make('figcaption',m[2]+' — Figure unavailable; see the source document.'));
            img.addEventListener('error',unavailable);
            figure.append(img,make('figcaption',m[2]));parent.append(figure);
          } else {
            const link=make('a',m[2]);link.href=url;
            if(!url.startsWith('#')) {link.target='_blank';link.rel='noopener noreferrer';}
            parent.append(link);
          }
        }
        end=m.index+m[0].length;
      }
      if(end<text.length) parent.append(make('span',text.slice(end)));
    }
    const lines=String(content).replace(/\r\n/g,'\n').split('\n');
    const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());
    const divider=line=>/^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line || '');
    for(let i=0;i<lines.length;) {
      const line=lines[i];if(!line.trim()){i++;continue;}
      if(/^```/.test(line)) {
        const code=[];i++;while(i<lines.length&&!/^```/.test(lines[i]))code.push(lines[i++]);
        i++;const pre=make('pre');pre.append(make('code',code.join('\n')));root.append(pre);continue;
      }
      const heading=line.match(/^(#{1,6})\s+(.+)$/);
      if(heading) {const h=make('h'+Math.min(heading[1].length+1,6));inline(h,heading[2]);root.append(h);i++;continue;}
      if(line.includes('|')&&divider(lines[i+1])) {
        const scroll=make('div','','knowledge-wiki-table'),table=make('table'),head=make('thead'),hr=make('tr');
        for(const cell of cells(line)){const th=make('th');th.setAttribute('scope','col');inline(th,cell);hr.append(th);}
        head.append(hr);table.append(head);const body=make('tbody');i+=2;
        while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()) {
          const row=make('tr');for(const cell of cells(lines[i++])){const td=make('td');inline(td,cell);row.append(td);}body.append(row);
        }
        table.append(body);scroll.append(table);root.append(scroll);continue;
      }
      const ordered=/^\d+\.\s+/.test(line),list=/^(?:[-*]|\d+\.)\s+/.test(line);
      if(list) {
        const ul=make(ordered?'ol':'ul'),matcher=ordered?/^\d+\.\s+/:/^[-*]\s+/;
        while(i<lines.length&&matcher.test(lines[i])){const li=make('li');inline(li,lines[i++].replace(matcher,''));ul.append(li);}
        root.append(ul);continue;
      }
      const paragraph=[];
      do {paragraph.push(lines[i++]);} while(i<lines.length&&lines[i].trim()&&!/^(?:#{1,6}\s|```|[-*]\s|\d+\.\s)/.test(lines[i])&&!divider(lines[i+1]));
      const p=make('p');inline(p,paragraph.join('\n'));root.append(p);
    }
    return root;
  }
  function createBrowser(root, {kind, request: send = request}) {
    if (!['wiki', 'memory', 'delivery'].includes(kind)) throw new Error('Unknown Knowledge view');
    const doc = root.ownerDocument;
    const make = (tag, text='', cls='') => {const el=doc.createElement(tag); el.textContent=text; el.className=cls; return el;};
    const control = (label, fn) => {const el=make('button',label,'knowledge-button secondary'); el.type='button'; el.addEventListener('click',fn); return el;};
    const form=make('form','','knowledge-query-bar');
    const queryLabel=make('label','Search'); const queryInput=make('input'); queryInput.type='search'; queryInput.maxLength=2000;
    queryLabel.append(queryInput); form.append(queryLabel);
    const filterInputs={};
    const filterOptions = kind === 'memory' ? {status:['','candidate','active','expired'],kind:['','preference','research_context','decision','instruction','experience','knowledge']} : kind === 'delivery' ? {stage:['','retrieved','delivered','used','excluded']} : {};
    for (const [name, options] of Object.entries(filterOptions)) {
      const label=make('label',name[0].toUpperCase()+name.slice(1)), select=make('select');
      for (const value of options) {const option=make('option',value || 'All'); option.value=value; select.append(option);}
      filterInputs[name]=select; label.append(select); form.append(label);
    }
    const searchButton=make('button','Search','knowledge-button primary'); searchButton.type='submit'; form.append(searchButton);
    const status=make('p','Not loaded.','knowledge-scope-summary'); status.setAttribute('aria-live','polite');
    const layout=make('div','','knowledge-markdown-layout');
    const list=make('article','','knowledge-card'), detail=make('article','Select a record.','knowledge-card knowledge-v2-detail');
    detail.setAttribute('aria-live','polite'); layout.append(list,detail);
    const more=control('Load more',()=>search(undefined,true)); more.hidden=true;
    root.replaceChildren(form,status,layout,more);
    let generation=0, detailGeneration=0, query='', filters={}, cursor='', scope='', revision='', selected=null, rows=[], pending=false, dirty=false, draft=null;
    const idOf=item=>item.record_id || item.receipt_id;
    function clear(message='Select a record.') {detailGeneration++; selected=null; draft=null; detail.replaceChildren(make('p',message));}
    function failure(error) {
      if(draft && ![401,403,404].includes(error.status)) {
        if(error.status===409) draft.conflict=true;
        status.textContent='Memory draft preserved. Review the current revision before retrying.';
        return;
      }
      clear(); rows=[]; list.replaceChildren(); more.hidden=true; cursor='';
      status.textContent = error.status === 401 || error.status === 403
        ? 'Private Knowledge requires a trusted server identity and permitted access. Public Wiki remains available.'
        : error.status === 409 ? 'Knowledge changed. Refresh and review the current revision.' : 'Knowledge unavailable. Retry the query.';
    }
    function renderRows() {
      list.replaceChildren();
      if (!rows.length) list.append(make('p','No matching records.'));
      for (const row of rows) {
        const card=make('div','','knowledge-v2-row');
        const name=row.topic_id || row.consumer_binding || row.kind || idOf(row);
        const open=control(name,()=>{
          // Use the workspace's existing hash router, including its navigation
          // generation guard. Sidebar reads must not leave a previous Wiki URL.
          if(kind==='wiki' && global.location) {
            const target='#wiki/'+encodeURIComponent(idOf(row));
            if(global.location.hash!==target) {global.location.hash=target;return;}
          }
          return read(idOf(row));
        });
        card.append(open,make('small',[kind==='wiki'?row.freshness:'',row.status || row.stage || row.freshness, row.revision ? `revision ${row.revision}` : '', idOf(row)].filter(Boolean).join(' · ')));
        list.append(card);
      }
    }
    async function search(input, append=false, quiet=false) {
      if (quiet && dirty) return;
      const token=++generation;
      if (input) {query=String(input.query || ''); filters={...(input.filters || {})}; queryInput.value=query; dirty=false;}
      if (!quiet && !append) clear();
      if (!quiet) status.textContent='Loading…';
      try {
        const data=await send(`/api/knowledge/${kind}/query`,{query,filters,cursor:append?cursor:'',limit:25});
        if (token!==generation) return;
        if (scope && scope!==data.scope_ref) {clear(); rows=[];}
        if (quiet && scope===data.scope_ref && revision===data.revision) return;
        const envelopeRevisionChanged=quiet && scope===data.scope_ref && revision!==data.revision;
        scope=data.scope_ref; revision=data.revision; cursor=data.next_cursor || '';
        const previous=selected;
        if (!append) rows=[];
        const merged=new Map(rows.map(item=>[idOf(item),item]));
        for (const item of data.items || []) merged.set(idOf(item),item);
        rows=Array.from(merged.values()); renderRows(); more.hidden=!cursor;
        status.textContent=`${rows.length} records · ${data.status || 'ok'} · revision ${revision}`;
        if (quiet && previous && !pending) {
          const current=rows.find(item=>idOf(item)===idOf(previous));
          if (!current) clear('The selected record is no longer in this result scope.');
          else if(draft) {
            if(current.revision!==draft.revision) {draft.conflict=true;status.textContent='Memory changed. Draft preserved; review current revision before saving.';}
          } else if (envelopeRevisionChanged || current.revision!==previous.revision || current.stage!==previous.stage) await read(idOf(current));
        }
      } catch (error) {if(token===generation) failure(error);}
    }
    async function read(recordId, {reviewDraft=false}={}) {
      const token=++detailGeneration;
      const heldDraft=reviewDraft?draft:null;
      if(!reviewDraft) draft=null;
      if(!reviewDraft) {selected=null; detail.replaceChildren(make('p','Loading record…'));}
      try {
        const data=await send(`/api/knowledge/${kind}/read`,{record_id:recordId,filters:{}});
        if(token!==detailGeneration) return;
        const item=data.items?.[0]; if(!item) throw new Error('Missing record');
        selected=item;
        draft=heldDraft && (!scope || scope===data.scope_ref)?{...heldDraft,revision:item.revision,conflict:false}:null;
        detail.replaceChildren();
        if(kind!=='wiki') detail.append(make('h3',item.topic_id || item.consumer_binding || item.kind || recordId));
        const state=make('p',kind==='wiki'?[item.freshness,item.status].filter(Boolean).join(' · ') || 'Recorded':item.stage || item.status || item.freshness || 'Recorded'); state.dataset.stage=item.stage || ''; detail.append(state);
        if(item.content) detail.append(kind==='wiki'?renderWikiBody(doc,item.content):make('div',item.content,'knowledge-v2-body'));
        const metadata=kind==='wiki'?make('details','','knowledge-wiki-sources'):detail;
        if(kind==='wiki') {metadata.append(make('summary','Sources & verification'));detail.append(metadata);}
        for(const source of item.source_refs || []) {
          const row=make('p',String(source),'knowledge-v2-source');
          // Source references are repository-relative, unlike body links.
          const url=kind==='wiki'&&String(source).startsWith('docs/')?wikiUrl('../../../'+source):'';
          if(url){const link=make('a',String(source));link.href=url;link.target='_blank';link.rel='noopener noreferrer';row.replaceChildren(link);}
          metadata.append(row);
        }
        const scalar=value=>['string','number'].includes(typeof value)?String(value).slice(0,160):'';
        metadata.append(make('p',`Scope: ${scalar(item.scope_ref) || JSON.stringify(item.scope || {})} · revision ${scalar(item.revision) || scalar(data.revision) || 'Unknown'}`));
        for(const field of ['expires_at','created_at','updated_at','verified_at']) if(item[field]) metadata.append(make('p',`${field}: ${scalar(item[field])}`));
        if(item.source_revision) metadata.append(make('p',`Source hashes: ${JSON.stringify(item.source_revision)}`));
        if(kind==='delivery') {
          for(const [label,key] of [['Retrieved','citation_ids'],['Delivered','delivered_citation_ids'],['Used','used_citation_ids']]) detail.append(make('p',`${label}: ${(item[key] || []).join(', ') || 'None'}`));
          if(item.use_status) detail.append(make('p',`Use: ${item.use_status}${item.non_use_reason?' · '+item.non_use_reason:''}`));
        }
        if(kind==='memory') memoryActions(item);
      } catch(error) {if(token===detailGeneration) failure(error);}
    }
    function memoryActions(item) {
      const actions=make('div','','knowledge-v2-actions'); detail.append(actions);
      function edit() {
        draft=draft || {recordId:idOf(item),revision:item.revision,value:item.content || '',conflict:false};
        const editor=make('textarea'); editor.value=draft.value; editor.maxLength=4000; editor.setAttribute('aria-label','Memory content');
        editor.addEventListener('input',()=>{draft.value=editor.value;});
        actions.replaceChildren(editor,control('Save memory',()=>{draft.value=editor.value;return command('edit',item,{content:editor.value});}),
          control('Review current revision',()=>read(idOf(item),{reviewDraft:true})),control('Cancel',()=>read(idOf(item))));
      }
      if(draft) {edit();return;}
      if(item.status==='candidate') {
        actions.append(control('Confirm memory',()=>command('confirm',item)),control('Dismiss',()=>command('dismiss',item)));
      }
      if(['candidate','active'].includes(item.status)) {
        actions.append(control('Edit',edit),control('Expire',()=>command('expire',item)));
      }
      actions.append(control('Forget',()=>actions.replaceChildren(make('p','Erase this retained memory and its private history? Original artifacts are not deleted.'),control('Confirm forget',()=>command('forget',item)),control('Cancel',()=>read(idOf(item))))));
    }
    async function command(action,item,payload={}) {
      if(pending || !selected || idOf(selected)!==idOf(item) || selected.revision!==item.revision) return;
      if(action==='edit' && draft?.conflict) {status.textContent='Draft preserved. Review current revision before saving.';return;}
      pending=true; const token=detailGeneration;
      const idempotency_key=global.crypto?.randomUUID?.() || `memory-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      try {
        await send('/api/knowledge/memory/commands',{action,target_id:idOf(item),expected_revision:item.revision,idempotency_key,payload});
        if(token!==detailGeneration) return;
        clear('Memory updated.'); await search();
        global.dispatchEvent?.(new Event('ax4lab:knowledge-changed'));
      } catch(error) {if(token===detailGeneration) failure(error);}
      finally {pending=false;}
    }
    form.addEventListener('submit',event=>{
      event.preventDefault(); const next={}; for(const [name,input] of Object.entries(filterInputs)) if(input.value) next[name]=input.value;
      return search({query:queryInput.value,filters:next});
    });
    form.addEventListener('input',()=>{generation++; dirty=true; clear('Apply changed filters to search.'); rows=[]; list.replaceChildren(); more.hidden=true;});
    return {search,read,refresh:()=>search(undefined,false,true),clear:()=>{generation++;clear();revision=null;rows=[];list.replaceChildren();more.hidden=true;}};
  }
  function normalizeTab(name) {
    const alias={markdown:'memory',sources:'manuals'};
    const resolved=alias[name] || name;
    return ['wiki','memory','manuals','delivery','ontology'].includes(resolved)?resolved:'wiki';
  }
  function parseTarget(hash) {
    const [name,encoded,...extra]=String(hash || '').replace(/^#/,'').split('/'), tab=normalizeTab(name);
    let recordId='';try{recordId=decodeURIComponent(encoded || '');}catch(_error){}
    const patterns={wiki:/^wiki:[A-Za-z0-9_-]{1,160}$/,memory:/^mem-[a-f0-9]{32}$/,delivery:/^delivery-[a-f0-9]{32}$/};
    if(extra.length || !patterns[tab]?.test(recordId)) recordId='';
    return {tab,recordId};
  }
  async function openTarget(views,hash) {
    const target=parseTarget(hash);
    if(target.recordId && views[target.tab]) await views[target.tab].read(target.recordId);
    return target;
  }
  const api={createBrowser,request,normalizeTab,parseTarget,openTarget};
  if(typeof module!=='undefined' && module.exports) module.exports=api;
  else global.AX4LABKnowledgeWorkspace=api;
})(typeof window!=='undefined'?window:globalThis);
