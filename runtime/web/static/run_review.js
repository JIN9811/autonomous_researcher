/* The original LIVE renderer, with an archive-only data source. */
(() => {
  "use strict";
  const nativeFetch = window.fetch.bind(window);
  const nativeOpen = window.open.bind(window);
  const emptyState = {run_id:"",stage:"idle",mode:"replay",loop_count:0,run_metadata:{},current_experiment_spec:{}};
  let point = null, manifest = {ok:true,agents:[]}, hooks = null, generation = 0;
  let pointIndex = [];
  let runArtifacts = [], resolveArtifact = () => '', artifactError = '';
  let session = {state:emptyState,messages:[],is_running:false,is_planning_busy:false};
  const requestedRun = new URLSearchParams(location.search).get("run_id");
  const reply = (body, status=200) => Promise.resolve(new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json"}}));
  const api = async path => {const response=await nativeFetch(`/api/review/${path}`,{cache:"no-store"}); if(!response.ok) throw new Error("Not recorded"); return response.json();};
  // Historical views neither restore nor overwrite LIVE UI caches.
  for (const name of ["localStorage","sessionStorage"]) {
    const data = new Map();
    Object.defineProperty(window,name,{value:{getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,String(value)),removeItem:key=>data.delete(key),clear:()=>data.clear()}});
  }
  window.fetch = (input, init={}) => {
    const url = new URL(typeof input === "string" ? input : input.url,location.href);
    const method = String(init.method || input?.method || "GET").toUpperCase();
    if(url.origin !== location.origin || method !== "GET") return reply({ok:false,read_only:true,error:"Replay is read-only"},403);
    if(url.pathname.startsWith("/api/review/") || url.pathname.startsWith("/static/") || url.pathname.startsWith("/module-assets/")) return nativeFetch(input,init);
    const artifactUrl=resolveArtifact(url.pathname+url.search);
    if(artifactUrl) return nativeFetch(artifactUrl,init);
    if(url.pathname === "/api/runtime/agent-manifests") return reply(manifest);
    if(url.pathname === "/api/planning/session") return reply(session);
    if(url.pathname === "/api/planning/messages") return reply({messages:session.messages,total:session.messages.length,has_more:false});
    if(url.pathname === "/api/events/recent" || /\/events$/.test(url.pathname)) return reply({events:point?.events || []});
    if(url.pathname === "/api/state" || url.pathname === "/api/runtime/state") return reply({state:session.state,is_running:false});
    if(/\/artifacts$/.test(url.pathname)) {
      const selected=url.pathname.match(/^\/api\/runs\/([^/]+)\/artifacts$/)?.[1] || url.searchParams.get('run_id') || point?.run_id;
      return reply({artifacts:decodeURIComponent(selected || '')===point?.run_id ? runArtifacts : [],read_only:true,scope:'session_files'});
    }
    if(/\/approvals$/.test(url.pathname)) return reply({approvals:[],pending:[],resolved:[]});
    if(/^\/api\/agents\/[^/]+\/report$/.test(url.pathname)) {
      const owner=url.pathname.split('/')[3], card=point?.cards?.[owner];
      return reply({ok:true,report:{agent_id:owner,run_id:point?.run_id,sections:rewrite(card?.data || {}),summary:"Recorded evidence",warnings:[],artifacts:runArtifacts.filter(file=>String(file.agent || '').replace(/_agent$/,'')===owner),decisions:[],metrics:{}}});
    }
    return reply({ok:false,read_only:true,status:"not_recorded",error:"Not recorded at this point"},404);
  };
  class OfflineStream extends EventTarget {constructor(){super();this.readyState=3;} close(){} send(){}}
  window.EventSource = OfflineStream;
  window.WebSocket = OfflineStream;
  window.open = value => {
    const url=resolveArtifact(value) || window.AX4LABReplayFiles.safeUrl(value);
    return url ? nativeOpen(url,'_blank','noopener,noreferrer') : null;
  };
  function images() {return [...(point?.images || []),...Object.values(point?.cards || {}).flatMap(card=>card.images || [])];}
  function imageUrl(image) {return `/api/review/${encodeURIComponent(point.run_id)}/assets/${encodeURIComponent(image.name)}`;}
  function rewrite(value) {
    if(Array.isArray(value)) return value.map(rewrite);
    if(value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key,child])=>[key,rewrite(child)]));
    if(typeof value === "string") {
      const match=images().find(image=>value === image.source_path || value.includes(encodeURIComponent(image.source_path || "\0")));
      if(match) return imageUrl(match);
      return resolveArtifact(value) || value;
    }
    return value;
  }
  function enforceReadOnly() {
    document.body.classList.add("run-replay-mode");
    for(const id of ["btn-live-safe-stop","btn-live-emergency-resume","btn-live-emergency-reset","btn-planning-send","btn-planning-generate","planning-message"]) {
      const node=document.getElementById(id); if(node){node.disabled=true;node.title="Read-only replay — no experiment controls";}
    }
    const stop=document.getElementById("btn-live-safe-stop"); if(stop && stop.textContent!=="READ ONLY") stop.textContent="READ ONLY";
    const stream=document.getElementById("live-stream-chip"); if(stream && stream.textContent!=="ARCHIVE") stream.textContent="ARCHIVE";
    const sync=document.getElementById("live-sync-chip");
    const text=point ? `Cycle ${Number(point.cycle)+1} · ${point.timestamp}` : "Not recorded";
    if(sync && sync.textContent!==text) {sync.textContent=text;sync.title=text;}
    document.querySelectorAll("img[src]").forEach(img=>{
      const src=img.getAttribute("src") || "";
      if(src.startsWith('/static/') || src.startsWith('/api/review/') || src.startsWith('data:')) return;
      const match=images().find(image=>src.includes(image.source_path || "\0") || src.includes(encodeURIComponent(image.source_path || "\0")));
      const linked=resolveArtifact(src);
      if(match) img.src=imageUrl(match);
      else if(linked) img.src=linked;
      else {img.removeAttribute("src");img.alt="Not recorded at this point";}
    });
    document.querySelectorAll("video,audio,iframe").forEach(node=>node.removeAttribute("src"));
  }
  function option(value,label){const node=document.createElement('option');node.value=value;node.textContent=label;return node;}
  function navigationTarget(key, points, pointId) {
    if (key === 'ArrowLeft' || key === 'ArrowRight') {
      const index = points.findIndex(item => item.id === pointId);
      if (index < 0) return null;
      const target = points[index + (key === 'ArrowLeft' ? -1 : 1)];
      return target ? {point: target.id} : null;
    }
    if (key !== 'ArrowUp' && key !== 'ArrowDown') return null;
    const current = points.find(item => item.id === pointId);
    if (!current) return null;
    const cycles = [...new Set(points.map(item => Number(item.cycle)).filter(Number.isFinite))].sort((a,b) => a-b);
    const index = cycles.indexOf(Number(current.cycle));
    if (index < 0) return null;
    const cycle = cycles[index + (key === 'ArrowUp' ? -1 : 1)];
    if (cycle === undefined) return null;
    const target = points.find(item => Number(item.cycle) === cycle);
    return target ? {point: target.id} : null;
  }
  function navigateReplay(event) {
    if (event.defaultPrevented || event.repeat || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.target?.isContentEditable || event.target?.closest?.('input,textarea,select,[role="textbox"],[role="combobox"],[role="slider"],dialog')) return;
    if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
    const points = document.getElementById('replay-point-select');
    const target = navigationTarget(event.key, pointIndex, points.value);
    event.preventDefault();
    if (!target) return;
    points.value = target.point;
    loadPoint().catch(showError);
  }
  async function loadPoint() {
    const revision=++generation, run=document.getElementById('replay-run-select').value;
    const id=document.getElementById('replay-point-select').value;
    if(!run || !id) return;
    const data=await api(`${encodeURIComponent(run)}/points/${id}`);
    if(revision!==generation) return;
    point=data;
    resolveArtifact=window.AX4LABReplayFiles.mapper(runArtifacts,data.run_id,data.cycle,data.timestamp);
    data.run_artifacts=runArtifacts;
    data.artifact_error=artifactError;
    const state=rewrite(data.state || {...emptyState,run_id:data.run_id,loop_count:data.cycle,stage:data.stage});
    state.run_metadata ||= {};
    if(data.cards?.vision?.event?.payload?.preview){
      const event=data.cards.vision.event.payload;
      const scope={run_id:data.run_id,loop_id:data.cycle,specimen_id:state.current_experiment_spec?.specimen_id || ''};
      state.run_metadata.utm_verifications={...scope,...(state.run_metadata.utm_verifications || {}),previews:{...(state.run_metadata.utm_verifications?.previews || {}),[event.checkpoint]:rewrite(event.preview)}};
    }
    session={state,messages:data.chat || [],message_total:(data.chat || []).length,has_more_messages:false,
      planning_session_id:`review:${data.run_id}:${data.id}`,is_running:false,is_planning_busy:false};
    hooks.render(data,session); enforceReadOnly();
  }
  async function loadRun() {
    const revision=++generation, run=document.getElementById('replay-run-select').value;
    const select=document.getElementById('replay-point-select'); select.replaceChildren(); select.disabled=true;
    point=null;pointIndex=[];runArtifacts=[];resolveArtifact=()=>'';artifactError='';session={state:{...emptyState},messages:[],is_running:false};hooks.render(null,session);
    if(!run){select.append(option('', 'Not recorded'));return;}
    const [index,files]=await Promise.all([api(`${encodeURIComponent(run)}/points`),
      api(`${encodeURIComponent(run)}/artifacts`).catch(()=>({artifacts:[],error:'Session files unavailable. Recorded points are still viewable.'}))]);
    if(revision!==generation) return;
    pointIndex=index.points;
    runArtifacts=files.artifacts || [];artifactError=files.error || '';
    index.points.forEach(item=>select.append(option(item.id,`Cycle ${Number(item.cycle)+1} · ${item.event} · ${item.timestamp}`)));
    select.disabled=!index.points.length;
    if(index.points.length) await loadPoint();
  }
  async function start(callbacks) {
    hooks=callbacks; manifest=await api('layout'); await hooks.initialize();
    const runSelect=document.getElementById('replay-run-select'), pointSelect=document.getElementById('replay-point-select');
    const data=await api('runs'); runSelect.replaceChildren();
    // Keep the session dropdown chronological; arrows navigate within the session.
    [...data.runs].reverse().forEach(run=>runSelect.append(option(run.run_id,run.run_id)));
    if(!data.runs.length || (requestedRun && !data.runs.some(run=>run.run_id===requestedRun))) {
      runSelect.prepend(option('', 'Not recorded'));runSelect.value='';
    } else runSelect.value=requestedRun || data.runs[0].run_id;
    runSelect.title='Select a recorded experiment session';
    pointSelect.title='Previous / next record: ← / → · Previous / next cycle: ↑ / ↓';
    document.addEventListener('keydown',navigateReplay);
    runSelect.addEventListener('change',()=>loadRun().catch(showError));
    pointSelect.addEventListener('change',()=>loadPoint().catch(showError));
    const observer=new MutationObserver(enforceReadOnly);observer.observe(document.body,{childList:true,subtree:true});
    document.addEventListener('submit',event=>{event.preventDefault();event.stopImmediatePropagation();},true);
    document.addEventListener('click',event=>{
      const anchor=event.target.closest('a');if(!anchor)return;
      const raw=anchor.getAttribute('href');
      const url=resolveArtifact(raw) || window.AX4LABReplayFiles.safeUrl(raw);
      event.stopImmediatePropagation();
      if(!url){event.preventDefault();return;}
      anchor.href=url;anchor.rel='noopener noreferrer';
      if(!anchor.hasAttribute('download')) anchor.target='_blank';
    },true);
    await loadRun();enforceReadOnly();window.dispatchEvent(new Event('ax4lab:live-ready'));
  }
  function showError(error){const node=document.getElementById('live-sync-chip');if(node)node.textContent=error.message;window.dispatchEvent(new Event('ax4lab:live-ready'));}
  window.AX4LABReplay=Object.freeze({start,artifactError:()=>artifactError,refresh:async()=>{hooks?.render(point,session);enforceReadOnly();return session;},showError});
})();
