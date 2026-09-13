/* Owner execution routes + source-bound internal relationships; themes are presentation only. */
(function(root) {
  'use strict';
  const AREAS = [
    ['high','High','#65c9ef'], ['middle','Middle','#7bc6ad'], ['low','Low','#a7b7cf'],
    ['guardian','Guardian / Safety','#e1b364'], ['knowledge','Knowledge / Evidence','#b9a1dc'],
  ];
  const TYPES = {execution:['Execution','#7e9ab8',''],validation:['Validation','#e1b364','8 5'],evidence:['Evidence','#b9a1dc','2 5']};
  TYPES.call=['Internal call','#91a6bf','5 3'];
  const THEMES={
    runtime:{background:'#0c1524',node:'#132135',text:'#e6edf7',muted:'#a7b7cf',colors:AREAS.map(row=>row[2])},
    document:{background:'#ffffff',node:'#ffffff',text:'#172b4d',muted:'#526174',colors:['#2463a5','#177768','#4c6079','#a36b16','#79529c']},
  };
  function sharedGeometry() {
    if(root.ATRRuntimeGraphGeometry)return root.ATRRuntimeGraphGeometry;
    if(typeof require!=='function')return null;
    const host=globalThis,hadWindow=Object.prototype.hasOwnProperty.call(host,'window'),previousWindow=host.window;
    try {
      host.window=host;
      require('./runtime_graph_geometry.js');
      return host.ATRRuntimeGraphGeometry || null;
    } finally {
      if(hadWindow)host.window=previousWindow;else delete host.window;
    }
  }
  const palette=options=>THEMES[options?.theme || 'runtime'] || THEMES.runtime;
  const areaColor=(area,theme)=>theme.colors[AREAS.findIndex(row=>row[0]===area)] || theme.muted;
  const esc = value => String(value ?? '').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function textRows(value,limit) {
    const rows=[''];
    for(const word of String(value).split(/\s+/)){if(rows[rows.length-1].length+word.length>limit)rows.push('');rows[rows.length-1]+=(rows[rows.length-1]?' ':'')+word;}
    return rows;
  }
  function relation(from,to) {return from === 'guardian' || to === 'guardian' ? 'validation' : from === 'knowledge' || to === 'knowledge' ? 'evidence' : 'execution';}
  function layout(module,catalog) {
    const executable=module.execution_graph;
    const view=module.metadata?.control_view || (executable?{}:null);
    if (!view) return null;
    const nodes=executable?executable.nodes.map((step,index)=>({key:step.id,step,phase:'execution_graph',index,area:step.area,label:step.label || step.id,llm:Boolean(step.llm)})):['pre_execution','internal_graph'].flatMap(phase=>(module[phase] || []).map((step,index)=>{
      const key=`${phase}:${step.id}`, declared=view.areas?.[key];
      const area=AREAS.some(([id])=>id===declared)?declared:'unassigned';
      const alias=view.label_sources?.[key]===step.label?view.labels?.[key]:null;
      return {key,step,phase,index,area,label:alias || step.label || step.id,llm:area!=='unassigned' && (view.llm_steps || []).includes(key)};
    }));
    const details={nodes:[],edges:[]};
    for(const owner of nodes) {
      const detail=catalog?.implementation_structure?.operations?.[owner.step.handler];
      if(!detail)continue;
      const key=id=>id==='$operation'?owner.key:`${owner.key}::${id}`;
      for(const item of detail.nodes)details.nodes.push({...item,key:key(item.id),owner:owner.key,owner_handler:owner.step.handler,step:{},implementation:true});
      for(const edge of detail.edges)details.edges.push({...edge,source:key(edge.source),target:key(edge.target),owner:owner.key});
    }
    let y=48;
    const groups=AREAS.map(([id,label,color])=>{
      const members=[...nodes,...details.nodes].filter(node=>node.area===id), central=['high','middle','low'].includes(id);
      const height=64+Math.max(1,Math.ceil(members.length/(central?2:1)))*112;
      const group={id,label,color,x:central?352:id==='guardian'?24:888,y:central?y:48,width:central?488:264,height};
      if(central)y+=height+48;
      members.forEach((node,index)=>{node.position=node.step.position || node.step.metadata?.position || {
        x:group.x+32+(central?index%2*240:0),y:group.y+56+Math.floor(index/(central?2:1))*112};});
      return group;
    });
    const unassigned=nodes.filter(node=>node.area==='unassigned');
    if(unassigned.length){
      const knowledge=groups.find(group=>group.id==='knowledge');
      const group={id:'unassigned',label:'Unassigned',color:'#adb7c4',x:888,y:knowledge.y+knowledge.height+48,width:264,height:64+unassigned.length*112};
      unassigned.forEach((node,index)=>{node.position=node.step.metadata?.position || {x:group.x+32,y:group.y+56+index*112};});
      groups.push(group);
    }
    return {nodes,groups,view,details,structure:catalog?.implementation_structure,executable:Boolean(executable),edges:executable?executable.edges:nodes.slice(1).map((node,index)=>({source:nodes[index].key,target:node.key,on:'next',kind:relation(nodes[index].area,node.area)}))};
  }
  function internalDetails(nodes,control) {
    const present=new Map(nodes.map(node=>[node.key || node.id,node]));
    const occupied=nodes.map(node=>node.position);
    const fresh=control.structure?layout({execution_graph:{nodes:nodes.map(node=>({...node.step,...node,id:node.key || node.id,handler:node.handler || node.step?.handler,area:node.metadata?.control_area || node.area})),edges:[]},metadata:{control_view:control.view}}, {implementation_structure:control.structure}).details:control.details;
    const details=(fresh?.nodes || []).filter(node=>present.get(node.owner)?.handler===node.owner_handler || present.get(node.owner)?.step?.handler===node.owner_handler).map(node=>{
      const position={...node.position};
      while(occupied.some(other=>Math.abs(other.x-position.x)<208 && Math.abs(other.y-position.y)<100))position.y+=112;
      occupied.push(position);return {...node,position};
    });
    const ids=new Set([...present.keys(),...details.map(node=>node.key)]);
    return {nodes:details,edges:(fresh?.edges || []).filter(edge=>ids.has(edge.source)&&ids.has(edge.target))};
  }
  function groupBoxes(nodes,control) {
    const all=[...nodes,...internalDetails(nodes,control).nodes];
    return control.groups.map(group=>{
      const members=all.filter(node=>(node.metadata?.control_area || node.area)===group.id);
      if(!members.length)return {...group,empty:true};
      const x=Math.min(...members.map(node=>node.position.x))-24;
      const y=Math.min(...members.map(node=>node.position.y))-48;
      return {...group,x,y,width:Math.max(group.width,Math.max(...members.map(node=>node.position.x+184))-x+24),
        height:Math.max(...members.map(node=>node.position.y+76))-y+24};
    });
  }
  function internalMarkup(nodes,control,options={}) {
    const theme=palette(options),detail=internalDetails(nodes,control),all=new Map([...nodes,...detail.nodes].map(node=>[node.key || node.id,node]));
    const lines=detail.edges.map((edge,index)=>{
      const a=all.get(edge.source).position,b=all.get(edge.target).position;
      const right=b.x>a.x,vertical=Math.abs(b.x-a.x)<80;
      const sx=vertical?a.x+92:a.x+(right?184:0),sy=vertical?a.y+(b.y>a.y?76:0):a.y+38;
      const tx=vertical?b.x+92:b.x+(right?0:184),ty=vertical?b.y+(b.y>a.y?0:76):b.y+38;
      const bend=vertical?(sy+ty)/2:(sx+tx)/2;
      const color=edge.kind==='validation'?areaColor('guardian',theme):edge.kind==='evidence'?areaColor('knowledge',theme):theme.muted;
      const path=vertical?`M${sx},${sy} C${sx+24},${bend} ${tx+24},${bend} ${tx},${ty}`:`M${sx},${sy} C${bend},${sy} ${bend},${ty} ${tx},${ty}`;
      const emphasis=options.selected===edge.owner;
      return `<g data-implementation-edge="${esc(edge.owner)}" pointer-events="none"><title>${esc(edge.label)} · ${esc(edge.kind)} (code-owned)</title><path d="${path}" fill="none" stroke="${color}" stroke-opacity="${emphasis?'.95':'.5'}" stroke-width="${emphasis?'2':'1.2'}" stroke-dasharray="${TYPES[edge.kind]?.[2] || ''}" marker-end="url(#control-detail-arrow)"/></g>`;
    }).join('');
    const boxes=detail.nodes.map(node=>`<g data-implementation-node="${esc(node.key)}" data-implementation-owner="${esc(node.owner)}" pointer-events="auto" role="${options.theme==='document'?'img':'button'}" ${options.theme==='document'?'':'tabindex="0"'} aria-label="${esc(`${node.label}; code-owned; ${node.source.symbol}`)}">
      <title>${esc(`${node.label}\nCode-owned inside ${node.owner}\n${node.source.path} · ${node.source.symbol}`)}</title>
      <rect x="${node.position.x}" y="${node.position.y}" width="184" height="76" rx="5" fill="${theme.node}" stroke="${areaColor(node.area,theme)}" stroke-opacity=".65" stroke-dasharray="4 3"/>
      ${textRows(node.label,24).slice(0,3).map((row,index)=>`<text x="${node.position.x+10}" y="${node.position.y+18+index*15}" fill="${theme.text}" font-size="12">${esc(row)}</text>`).join('')}
      <text x="${node.position.x+10}" y="${node.position.y+67}" fill="${theme.muted}" font-size="9">CODE · ${esc(node.owner)}</text>
    </g>`).join('');
    return `<defs><marker id="control-detail-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6z" fill="${theme.muted}"/></marker></defs>${lines}${boxes}`;
  }
  function backdrop(nodes,control,options={}) {
    const theme=palette(options);
    return groupBoxes(nodes,control).map(group=>`<g class="runtime-control-area" data-control-area="${group.id}" pointer-events="none">
      <rect x="${group.x}" y="${group.y}" width="${group.width}" height="${group.height}" rx="12" fill="${areaColor(group.id,theme)}" fill-opacity=".035" stroke="${areaColor(group.id,theme)}" stroke-opacity=".3"/>
      <text x="${group.x+16}" y="${group.y+26}" fill="${areaColor(group.id,theme)}" font-size="15" font-weight="600">${esc(group.label)}</text>
      ${group.empty?textRows(control.view.empty_roles?.[group.id] || (control.executable?'No separate owner operation':'No role declared'),31).map((row,index)=>`<text x="${group.x+16}" y="${group.y+74+index*18}" fill="${theme.muted}" font-size="12">${esc(row)}</text>`).join(''):''}</g>`).join('')+internalMarkup(nodes,control,options);
  }
  function legend(control) {
    return `<div class="runtime-control-legend"><strong>Control areas · not sequential layers</strong>
      ${AREAS.map(([id,label,color])=>`<span><i style="background:${color}"></i>${esc(label)}</span>`).join('')}
      ${Object.entries(TYPES).map(([id,[label,color,dash]])=>`<span><svg width="32" height="12" aria-hidden="true"><line x1="0" x2="30" y1="6" y2="6" stroke="${color}" stroke-width="2" stroke-dasharray="${dash}"/></svg>${label}</span>`).join('')}
      ${control?.groups.some(group=>group.id==='unassigned')?'<small>Unassigned: classify new or renamed checkpoints in module metadata.control_view.areas.</small>':''}
      <small>${control?.executable?'Solid boxes: editable execution. Dashed CODE boxes: existing internal functions/tools; not extra commands or live statuses. LLM feedback stays inside its bounded owner loop.':'Lines retain configured checkpoint order; styling denotes responsibility. LLM marks actual decision points.'}</small></div>`;
  }
  function renderSvg(module,options={theme:'document'}) {
    const theme=palette(options),control=layout(module,options.catalog);
    if(!control)throw new Error('No control view declared');
    const geometry=sharedGeometry();
    if(!geometry)throw new Error('Shared runtime graph geometry is unavailable');
    const boxes=groupBoxes(control.nodes,control);
    const width=Math.max(...boxes.map(box=>box.x+box.width))+24;
    const height=Math.max(...boxes.map(box=>box.y+box.height))+134;
    const edgeRecords=control.edges.flatMap((edge,index)=>{
      const previous=control.nodes.find(node=>node.key===edge.source),node=control.nodes.find(node=>node.key===edge.target);
      if(!previous || !node)return [];
      const ports=geometry.inferPorts(previous,node,{nodeWidth:184,nodeHeight:76});
      return [{...edge,key:`${edge.source}->${edge.target}:${edge.on}:${index}`,source:previous,target:node,sourceSide:ports.sourceSide,targetSide:ports.targetSide}];
    });
    geometry.assignOffsets(edgeRecords,{nodeWidth:184,nodeHeight:76,edgeSpacing:14,parallelSpacing:30});
    const detailNodes=internalDetails(control.nodes,control).nodes;
    const obstacles=[...control.nodes,...detailNodes].map(node=>({left:node.position.x-3,top:node.position.y-3,right:node.position.x+187,bottom:node.position.y+79}));
    const labelDrafts=edgeRecords.map(edge=>{
      const labelWidth=Math.max(38,String(edge.on).length*6+14);
      const origin=geometry.labelPoint(edge,{nodeWidth:184,nodeHeight:76,labelT:.5});
      const candidates=Array.from({length:37},(_,index)=>geometry.labelPoint(edge,{nodeWidth:184,nodeHeight:76,labelT:.14+index*.02}));
      return {...edge,x:origin.x,y:origin.y,width:labelWidth,height:20,candidates};
    });
    const labels=geometry.resolveLabelCollisions(labelDrafts,{gap:5,obstacles,maxX:width,maxY:height});
    const edges=edgeRecords.map((edge,index)=>{
      const type=edge.kind,[,,dash]=TYPES[type] || TYPES.execution;
      const color=type==='validation'?areaColor('guardian',theme):type==='evidence'?areaColor('knowledge',theme):theme.muted;
      const label=labels[index],path=geometry.path(edge,{nodeWidth:184,nodeHeight:76});
      return `<g data-source="${esc(edge.source.key)}" data-target="${esc(edge.target.key)}" data-outcome="${esc(edge.on)}" data-kind="${esc(type)}"><title>${esc(edge.source.key)} → ${esc(edge.target.key)} · ${esc(edge.on)} · ${esc(type)}</title><path d="${path}" fill="none" stroke="${color}" stroke-opacity=".8" stroke-width="2" stroke-dasharray="${dash}" marker-end="url(#control-arrow)"/>${control.executable?`<rect x="${label.x-label.width/2}" y="${label.y-label.height/2}" width="${label.width}" height="${label.height}" rx="4" fill="${theme.background}"/><text x="${label.x}" y="${label.y+4}" text-anchor="middle" fill="${color}" font-size="11">${esc(edge.on)}</text>`:''}</g>`;
    }).join('');
    const nodes=control.nodes.map(node=>{
      const words=node.label.split(/\s+/), rows=[''];
      for(const word of words){if(rows[rows.length-1].length+word.length>23)rows.push('');rows[rows.length-1]+=(rows[rows.length-1]?' ':'')+word;}
      return `<g><title>${esc(node.key)} · ${esc(node.step.handler || module.handler)}</title>
        <rect x="${node.position.x}" y="${node.position.y}" width="184" height="76" rx="9" fill="${theme.node}" stroke="${areaColor(node.area,theme)}" stroke-width="2"/>
        ${rows.slice(0,3).map((row,index)=>`<text x="${node.position.x+12}" y="${node.position.y+21+index*16}" fill="${theme.text}" font-size="12">${esc(row)}</text>`).join('')}
        ${node.llm?`<text x="${node.position.x+145}" y="${node.position.y+68}" fill="${areaColor(node.area,theme)}" font-size="10">LLM</text>`:''}</g>`;
    }).join('');
    return `<svg xmlns="http://www.w3.org/2000/svg" data-theme="${options.theme || 'runtime'}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(module.label)} five-area internal graph" style="font-family:Arial,sans-serif;background:${theme.background}">
      <title>${esc(module.label)} — five-area internal graph</title><desc>${control.executable?'Executable owner operations and explicit outcomes. Positions are presentation only. Composite LLM tools are not separate editable operations.':'Existing editable checkpoints grouped by responsibility. Not five sequential layers.'}</desc>
      <rect width="100%" height="100%" fill="${theme.background}"/>
      <defs><marker id="control-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6z" fill="${theme.muted}"/></marker></defs>
      ${backdrop(control.nodes,control,options)}${edges}${nodes}
      ${Object.entries(TYPES).map(([id,[label,,dash]],index)=>`<line x1="${24+index*220}" x2="${62+index*220}" y1="${height-76}" y2="${height-76}" stroke="${theme.muted}" stroke-width="2" stroke-dasharray="${dash}"/><text x="${72+index*220}" y="${height-72}" fill="${theme.text}" font-size="14">${label}</text>`).join('')}
      <text x="24" y="${height-40}" fill="${theme.muted}" font-size="13">Solid boxes: executable operations · Dashed CODE boxes: implementation relationships · LLM: bounded decision</text>
    </svg>`;
  }
  const api=Object.freeze({layout,relation,internalDetails,groupBoxes,backdrop,legend,renderSvg});
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.AX4LABControlView=api;
})(typeof window!=='undefined'?window:globalThis);
