/* Read-only projection of the existing run artifact index; no storage migration. */
(function (root) {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const owner = v => String(v || '').replace(/_agent$/, '');
  const parent = p => String(p || '').split('/').slice(0,-1).join('/');
  const decode = v => {try{return decodeURIComponent(v);}catch{return v;}};
  function filterFiles(files, scope) {
    return files.filter(f => f.run_id === scope.run
      && (scope.loop === 'all' || f.loop_index != null && String(f.loop_index) === String(scope.loop))
      && (scope.agent === 'all' || owner(f.agent) === owner(scope.agent)));
  }
  function folders(files) {
    const found = new Set(['']);
    files.forEach(f=>{const parts=parent(f.path).split('/').filter(Boolean);parts.forEach((_,i)=>found.add(parts.slice(0,i+1).join('/')));});
    return [...found].sort().map(path=>({path,label:path.split('/').pop() || 'Run folder',depth:path ? path.split('/').length : 0}));
  }
  function displayName(file) {
    return String(file.name || String(file.path).split('/').pop()).replace(/^[a-f0-9]{32,64}_/i,'').replaceAll('_',' ');
  }
  function safeUrl(value) {
    const url=String(value || '');
    return /^\/api\/(?:runs\/[^/?#]+\/artifact-file\/|artifacts\/|planning\/artifacts\/)/.test(url) && !/[\\\r\n]/.test(url) ? url : '';
  }
  function mergeReferences(indexed, messages) {
    const result=[...indexed],seen=new Set(indexed.map(f=>String(f.url||'').split('?')[0]));
    messages.forEach((msg,i)=>{
      const agent=owner(String(msg.role||'unknown').replace(/_ai$/,''));
      const loop=msg.loop_index ?? (Number(msg.cycle_index)>0?Number(msg.cycle_index)-1:null);
      const base={run_id:msg.run_id || '',agent,loop_index:loop,archive_status:'Conversation reference',size_bytes:null};
      const visit=(value,prefix)=>{
        if(!value||typeof value!=='object')return;
        Object.entries(value).forEach(([key,v])=>{
          const url=typeof v==='string' && /url$/.test(key)?safeUrl(v):'';
          if(url&&!seen.has(url.split('?')[0])){
            seen.add(url.split('?')[0]);const name=decode(url.split('?')[0].split('/').pop()),suffix='.'+name.split('.').pop().toLowerCase();
            result.push({...base,run_id:base.run_id||decode(url.split('/')[url.startsWith('/api/planning/')?4:3]||''),name,path:`Linked references/${agent}/${i}/${prefix}/${name}`,url,download_url:url,suffix,
              preview_kind:/\.(png|svg|jpg|jpeg|webp|gif)$/.test(suffix)?'image':/\.(json|jsonl|csv|txt|log|md)$/.test(suffix)?'text':'download'});
          }else if(v&&typeof v==='object')visit(v,`${prefix}/${key}`);
        });
      };
      ['artifacts','artifact_pair','fem_artifacts','bo_result'].forEach(key=>visit(msg[key],key));
      if(msg.bo_result && Object.keys(msg.bo_result).length)result.push({...base,path:`Linked references/${agent}/${i}/BO results.json`,name:'BO results.json',suffix:'.json',inline_data:msg.bo_result,preview_kind:'text'});
    });
    return result;
  }
  function csvRows(text, limit=101) {
    const rows=[];let row=[],cell='',quoted=false;
    for(let i=0;i<text.length && rows.length<limit;i++) {
      const c=text[i];
      if(c==='"') {if(quoted && text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
      else if(c===',' && !quoted){row.push(cell);cell='';}
      else if((c==='\n'||c==='\r')&&!quoted){row.push(cell);rows.push(row);row=[];cell='';if(c==='\r'&&text[i+1]==='\n')i++;}
      else cell+=c;
    }
    if((cell || row.length) && rows.length<limit){row.push(cell);rows.push(row);}
    return rows;
  }
  const bytes = n => n!=null && Number.isFinite(Number(n)) ? (n>=1048576 ? `${(n/1048576).toFixed(1)} MB` : n>=1024 ? `${(n/1024).toFixed(1)} KB` : `${n} B`) : '—';
  class Explorer {
    constructor(host) {
      this.host=host;this.files=[];this.scope={run:'',loop:'all',agent:'all'};this.folder='';this.openFolders=new Set(['']);this.ticket=0;this.previewTicket=0;
      host.addEventListener('change',e=>this.change(e));
      host.addEventListener('click',e=>this.click(e));
    }
    update(context) {
      this.context=context;
      const key=[context.run,context.loop,context.agent].join(':');
      if(key!==this.contextKey){this.contextKey=key;this.scope={run:context.run,loop:String(context.loop ?? 'all'),agent:owner(context.agent)||'all'};this.files=context.files || [];this.folder=null;this.selected=null;this.error='';this.ticket++;this.previewTicket++;}
      else if(this.scope.run===context.run) {
        if(!this.files.length && context.files?.length && this.folder==='' && this.scope.agent!=='all')this.folder=null;
        this.files=context.files || [];
      }
      const signature=JSON.stringify([this.scope,this.files,this.error]);
      if(signature===this.signature)return;
      this.signature=signature;this.render();
    }
    visible(){return filterFiles(this.files,this.scope);}
    render() {
      const files=this.visible(),tree=folders(files);
      if(this.folder===null){this.folder=parent(files[0]?.path);const p=this.folder.split('/');p.forEach((_,i)=>this.openFolders.add(p.slice(0,i+1).join('/')));}
      if(!tree.some(x=>x.path===this.folder))this.folder='';
      const runs=[...new Set([this.context.run,this.scope.run,...(this.context.runs || [])].filter(Boolean))];
      const loops=[...new Set(this.files.filter(x=>x.loop_index!=null).map(x=>String(x.loop_index)))];
      if(this.scope.loop!=='all'&&!loops.includes(this.scope.loop))loops.push(this.scope.loop);
      const agents=[...new Set(this.files.map(x=>owner(x.agent)).filter(Boolean))];
      if(this.scope.agent!=='all'&&!agents.includes(this.scope.agent))agents.push(this.scope.agent);
      const options=(values,selected,label)=>values.map(v=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(label(v))}</option>`).join('');
      const list=files.filter(f=>parent(f.path)===this.folder);
      this.host.innerHTML=`<section class="artifact-explorer">
        <header class="ae-toolbar"><label>Session<select data-ae-scope="run">${options(runs,this.scope.run,v=>v)}</select></label>
        <label>Loop<select data-ae-scope="loop"><option value="all">All loops / legacy</option>${options(loops.sort((a,b)=>a-b),this.scope.loop,v=>`Loop ${Number(v)+1}`)}</select></label>
        <label>Agent<select data-ae-scope="agent"><option value="all">All agents / legacy</option>${options(agents.sort(),this.scope.agent,v=>this.context.label(v))}</select></label>
        <button type="button" class="btn" data-ae-action="all">All files</button><button type="button" class="btn" data-ae-action="current">Current context</button>
        <button type="button" class="btn" data-ae-action="refresh">Refresh</button></header>
        ${this.error?`<p role="status" class="hint">${esc(this.error)}</p>`:''}
        <div class="ae-layout"><nav class="ae-tree" aria-label="Artifact folders">${tree.filter(f=>!f.path || this.openFolders.has('') && f.path.split('/').slice(0,-1).every((_,i)=>this.openFolders.has(f.path.split('/').slice(0,i+1).join('/')))).map(f=>{
          const children=tree.some(x=>x.path && parent(x.path)===f.path);
          return `<div class="ae-folder-row" style="padding-left:${f.depth*12}px">${children?`<button type="button" data-ae-toggle="${esc(f.path)}" aria-label="Toggle ${esc(f.label)}" aria-expanded="${this.openFolders.has(f.path)}">${this.openFolders.has(f.path)?'▾':'▸'}</button>`:'<span class="ae-indent"></span>'}<button type="button" data-ae-folder="${esc(f.path)}" ${f.path===this.folder?'aria-current="location"':''} title="${esc(f.path || '/')}">${esc(f.label)}</button></div>`;
        }).join('')}</nav>
        <section class="ae-files" aria-label="Artifact files"><div class="ae-breadcrumb">${esc(this.folder || '/')} <span>${list.length} files</span></div>
        <div class="ae-table-scroll"><table><thead><tr><th>File</th><th>Type</th><th>Size</th></tr></thead><tbody>${list.map(f=>`<tr><td><button type="button" data-ae-file="${esc(f.path)}" title="${esc(f.name || f.path)}">${esc(displayName(f))}</button></td><td>${esc(f.suffix || f.preview_kind || 'file')}</td><td>${bytes(f.size_bytes)}</td></tr>`).join('')}</tbody></table>
        ${!list.length?`<p class="hint">${files.length?'Select a child folder to view its files.':'No indexed files for this scope. Use All files to include legacy and other agents.'}</p>`:''}</div>
        <section class="ae-preview" aria-label="Artifact preview" hidden></section></section></div>
        </section>`;
      if(this.selected && list.some(f=>f.path===this.selected))this.preview(this.selected);
    }
    async change(event) {
      const field=event.target.dataset.aeScope;if(!field)return;
      this.scope[field]=event.target.value;this.folder=null;this.selected=null;this.previewTicket++;
      if(field==='run'){this.files=[];this.scope.loop='all';this.render();await this.load();}else this.render();
    }
    async click(event) {
      const el=event.target.closest('[data-ae-folder],[data-ae-toggle],[data-ae-file],[data-ae-action]');if(!el)return;
      if(el.hasAttribute('data-ae-file'))return this.preview(el.dataset.aeFile);
      if(el.hasAttribute('data-ae-folder')){this.folder=el.dataset.aeFolder;this.selected=null;this.openFolders.add(this.folder);}
      if(el.hasAttribute('data-ae-toggle')){const p=el.dataset.aeToggle;this.openFolders.has(p)?this.openFolders.delete(p):this.openFolders.add(p);}
      const action=el.dataset.aeAction;
      if(action==='refresh')return this.load();
      if(action==='all'){this.scope.loop='all';this.scope.agent='all';this.folder='';this.selected=null;}
      if(action==='current'){this.contextKey=null;this.update(this.context);return;}
      this.previewTicket++;this.render();
    }
    async load() {
      const ticket=++this.ticket,run=this.scope.run;this.error='Loading artifact index…';this.render();
      try{const response=await fetch(`/api/runs/${encodeURIComponent(run)}/artifacts`);if(!response.ok)throw Error(`Artifact index unavailable (${response.status})`);const data=await response.json();
        if(ticket!==this.ticket || run!==this.scope.run)return;
        this.files=mergeReferences(Array.isArray(data.artifacts)?data.artifacts:[],this.context.references || []);this.error='';
      }catch(e){if(ticket!==this.ticket)return;this.error=String(e.message);}
      this.render();
    }
    async preview(path) {
      const f=this.visible().find(f=>f.path===path),panel=this.host.querySelector('.ae-preview');if(!f||!panel)return;
      this.selected=path;const ticket=++this.previewTicket,url=safeUrl(f.url),download=safeUrl(f.download_url);
      this.host.querySelectorAll('[data-ae-file]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.aeFile===path)));
      panel.hidden=false;
      panel.innerHTML=`<header><strong>${esc(displayName(f))}</strong> ${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open original</a>`:''} ${download?`<a href="${esc(download)}" download>Download</a>`:''}</header>
        <details><summary>File details</summary><code>${esc(f.path)}</code><p>Attempt ${esc(f.attempt_index ?? '—')} · ${esc(f.archive_status || 'Unclassified')} · ${bytes(f.size_bytes)}</p></details><div class="ae-preview-content"></div>`;
      const content=panel.querySelector('.ae-preview-content');
      if(f.inline_data){const pre=document.createElement('pre');pre.textContent=JSON.stringify(f.inline_data,null,2);content.replaceChildren(pre);return;}
      if(!url){content.textContent='Preview URL unavailable.';return;}
      if(f.preview_kind==='image'){content.innerHTML=`<img loading="lazy" src="${esc(url)}" alt="${esc(displayName(f))}">`;return;}
      if((f.preview_kind!=='text'&&f.suffix!=='.jsonl')||Number(f.size_bytes)>1048576){content.textContent='Use Open original or Download for this file. Inline text previews are limited to 1 MB.';return;}
      content.textContent='Loading preview…';
      try{const response=await fetch(url);if(!response.ok)throw Error(`Preview unavailable (${response.status})`);
        const reader=response.body.getReader(),decoder=new TextDecoder();let text='',size=0;
        try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>1048576){await reader.cancel();throw Error('Preview exceeds 1 MB. Open or download the original.');}text+=decoder.decode(value,{stream:true});}text+=decoder.decode();}finally{reader.releaseLock();}
        if(ticket!==this.previewTicket || !content.isConnected)return;
        if(f.suffix==='.csv'){const rows=csvRows(text);content.innerHTML=`<p class="hint">Preview: up to 100 data rows and 40 columns. Original unchanged.</p><div class="ae-table-scroll"><table>${rows.map((r,i)=>`<tr>${r.slice(0,40).map(c=>`<${i?'td':'th'}>${esc(c)}</${i?'td':'th'}>`).join('')}</tr>`).join('')}</table></div>`;}
        else{if(f.suffix==='.json'){try{text=JSON.stringify(JSON.parse(text),null,2);}catch{}}const pre=document.createElement('pre');pre.textContent=text;content.replaceChildren(pre);}
      }catch(e){if(ticket===this.previewTicket&&content.isConnected)content.textContent=String(e.message);}
    }
  }
  const api={filterFiles,folders,displayName,safeUrl,csvRows,mergeReferences,Explorer};
  if(typeof module!=='undefined')module.exports=api;else root.AtrArtifactExplorer=api;
})(typeof window!=='undefined'?window:this);
