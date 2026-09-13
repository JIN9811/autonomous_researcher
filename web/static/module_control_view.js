/* Presentation metadata only: preserve module steps, handlers and routing. */
(function(root) {
  'use strict';
  const AREAS = [
    ['high','High','#65c9ef'], ['middle','Middle','#7bc6ad'], ['low','Low','#a7b7cf'],
    ['guardian','Guardian / Safety','#e1b364'], ['knowledge','Knowledge / Evidence','#b9a1dc'],
  ];
  const TYPES = {execution:['Execution','#7e9ab8',''],validation:['Validation','#e1b364','8 5'],evidence:['Evidence','#b9a1dc','2 5']};
  const esc = value => String(value ?? '').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function textRows(value,limit) {
    const rows=[''];
    for(const word of String(value).split(/\s+/)){if(rows[rows.length-1].length+word.length>limit)rows.push('');rows[rows.length-1]+=(rows[rows.length-1]?' ':'')+word;}
    return rows;
  }
  function relation(from,to) {return from === 'guardian' || to === 'guardian' ? 'validation' : from === 'knowledge' || to === 'knowledge' ? 'evidence' : 'execution';}
  function layout(module) {
    const executable=module.execution_graph;
    const view=module.metadata?.control_view || (executable?{}:null);
    if (!view) return null;
    const nodes=executable?executable.nodes.map((step,index)=>({key:step.id,step,phase:'execution_graph',index,area:step.area,label:step.label || step.id,llm:Boolean(step.llm)})):['pre_execution','internal_graph'].flatMap(phase=>(module[phase] || []).map((step,index)=>{
      const key=`${phase}:${step.id}`, declared=view.areas?.[key];
      const area=AREAS.some(([id])=>id===declared)?declared:'unassigned';
      const alias=view.label_sources?.[key]===step.label?view.labels?.[key]:null;
      return {key,step,phase,index,area,label:alias || step.label || step.id,llm:area!=='unassigned' && (view.llm_steps || []).includes(key)};
    }));
    let y=48;
    const groups=AREAS.map(([id,label,color])=>{
      const members=nodes.filter(node=>node.area===id), central=['high','middle','low'].includes(id);
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
    return {nodes,groups,view,executable:Boolean(executable),edges:executable?executable.edges:nodes.slice(1).map((node,index)=>({source:nodes[index].key,target:node.key,on:'next',kind:relation(nodes[index].area,node.area)}))};
  }
  function groupBoxes(nodes,control) {
    return control.groups.map(group=>{
      const members=nodes.filter(node=>(node.metadata?.control_area || node.area)===group.id);
      if(!members.length)return {...group,empty:true};
      const x=Math.min(...members.map(node=>node.position.x))-24;
      const y=Math.min(...members.map(node=>node.position.y))-48;
      return {...group,x,y,width:Math.max(group.width,Math.max(...members.map(node=>node.position.x+184))-x+24),
        height:Math.max(...members.map(node=>node.position.y+76))-y+24};
    });
  }
  function backdrop(nodes,control) {
    return groupBoxes(nodes,control).map(group=>`<g class="runtime-control-area" data-control-area="${group.id}" pointer-events="none">
      <rect x="${group.x}" y="${group.y}" width="${group.width}" height="${group.height}" rx="12" fill="${group.color}" fill-opacity=".045" stroke="${group.color}" stroke-opacity=".35"/>
      <text x="${group.x+16}" y="${group.y+26}" fill="${group.color}" font-size="15" font-weight="600">${esc(group.label)}</text>
      ${group.empty?textRows(control.view.empty_roles?.[group.id] || (control.executable?'No separate owner operation':'No role declared'),31).map((row,index)=>`<text x="${group.x+16}" y="${group.y+74+index*18}" fill="#a7b7cf" font-size="12">${esc(row)}</text>`).join(''):''}</g>`).join('');
  }
  function legend(control) {
    return `<div class="runtime-control-legend"><strong>Control areas · not sequential layers</strong>
      ${AREAS.map(([id,label,color])=>`<span><i style="background:${color}"></i>${esc(label)}</span>`).join('')}
      ${Object.entries(TYPES).map(([id,[label,color,dash]])=>`<span><svg width="32" height="12" aria-hidden="true"><line x1="0" x2="30" y1="6" y2="6" stroke="${color}" stroke-width="2" stroke-dasharray="${dash}"/></svg>${label}</span>`).join('')}
      ${control?.groups.some(group=>group.id==='unassigned')?'<small>Unassigned: classify new or renamed checkpoints in module metadata.control_view.areas.</small>':''}
      <small>${control?.executable?'Explicit operation outcomes drive these routes. LLM = composite bounded decision; internal tools are not separately editable.':'Lines retain configured checkpoint order; styling denotes responsibility. LLM marks actual decision points.'}</small></div>`;
  }
  function renderSvg(module) {
    const control=layout(module);
    if(!control)throw new Error('No control view declared');
    const boxes=groupBoxes(control.nodes,control);
    const width=Math.max(...boxes.map(box=>box.x+box.width))+24;
    const height=Math.max(...boxes.map(box=>box.y+box.height))+134;
    const edges=control.edges.map((edge,index)=>{
      const previous=control.nodes.find(node=>node.key===edge.source),node=control.nodes.find(node=>node.key===edge.target);
      if(!previous || !node)return '';
      const type=edge.kind,[,color,dash]=TYPES[type] || TYPES.execution;
      const a=previous.position,b=node.position;
      const siblings=control.edges.filter(item=>item.source===edge.source && item.target===edge.target),offset=(siblings.indexOf(edge)-(siblings.length-1)/2)*30;
      const vertical=Math.abs(b.y-a.y)>100;
      const sx=vertical?a.x+92:a.x+(b.x>a.x?184:0),sy=vertical?a.y+(b.y>a.y?76:0):a.y+38;
      const tx=vertical?b.x+92:b.x+(b.x>a.x?0:184),ty=vertical?b.y+(b.y>a.y?0:76):b.y+38;
      const midX=(sx+tx)/2,midY=(sy+ty)/2+offset;
      const labelWidth=Math.max(38,String(edge.on).length*6+14);
      const path=vertical?`M${sx},${sy} C${sx},${midY} ${tx},${midY} ${tx},${ty}`:`M${sx},${sy} C${midX},${sy+offset*2} ${midX},${ty+offset*2} ${tx},${ty}`;
      return `<g data-source="${esc(edge.source)}" data-target="${esc(edge.target)}" data-outcome="${esc(edge.on)}" data-kind="${esc(type)}"><title>${esc(edge.source)} → ${esc(edge.target)} · ${esc(edge.on)} · ${esc(type)}</title><path d="${path}" fill="none" stroke="${color}" stroke-opacity=".65" stroke-width="1.5" stroke-dasharray="${dash}" marker-end="url(#control-arrow)"/>${control.executable?`<rect x="${midX-labelWidth/2}" y="${midY-13}" width="${labelWidth}" height="20" rx="4" fill="#0c1524"/><text x="${midX}" y="${midY+1}" text-anchor="middle" fill="${color}" font-size="11">${esc(edge.on)}</text>`:''}</g>`;
    }).join('');
    const nodes=control.nodes.map(node=>{
      const words=node.label.split(/\s+/), rows=[''];
      for(const word of words){if(rows[rows.length-1].length+word.length>23)rows.push('');rows[rows.length-1]+=(rows[rows.length-1]?' ':'')+word;}
      return `<g><title>${esc(node.key)} · ${esc(node.step.handler || module.handler)}</title>
        <rect x="${node.position.x}" y="${node.position.y}" width="184" height="76" rx="9" fill="#132135" stroke="${control.groups.find(group=>group.id===node.area).color}" stroke-opacity=".6"/>
        ${rows.slice(0,3).map((row,index)=>`<text x="${node.position.x+12}" y="${node.position.y+21+index*16}" fill="#e6edf7" font-size="12">${esc(row)}</text>`).join('')}
        ${node.llm?`<text x="${node.position.x+145}" y="${node.position.y+68}" fill="#65c9ef" font-size="10">LLM</text>`:''}</g>`;
    }).join('');
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(module.label)} five-area internal graph" style="font-family:Arial,sans-serif;background:#0c1524">
      <title>${esc(module.label)} — five-area internal graph</title><desc>${control.executable?'Executable owner operations and explicit outcomes. Positions are presentation only. Composite LLM tools are not separate editable operations.':'Existing editable checkpoints grouped by responsibility. Not five sequential layers.'}</desc>
      <defs><marker id="control-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6z" fill="#91a6bf"/></marker></defs>
      ${backdrop(control.nodes,control)}${edges}${nodes}
      ${Object.entries(TYPES).map(([id,[label,color,dash]],index)=>`<line x1="${24+index*220}" x2="${62+index*220}" y1="${height-76}" y2="${height-76}" stroke="${color}" stroke-width="2" stroke-dasharray="${dash}"/><text x="${72+index*220}" y="${height-72}" fill="#e6edf7" font-size="14">${label}</text>`).join('')}
      <text x="24" y="${height-40}" fill="#a7b7cf" font-size="13">${control.executable?'Explicit outcome routes · LLM = composite bounded decision · five areas are responsibility groups':'Configured checkpoint order retained · LLM = bounded decision point · five responsibility areas, not five stages'}</text>
    </svg>`;
  }
  const api=Object.freeze({layout,relation,groupBoxes,backdrop,legend,renderSvg});
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.AX4LABControlView=api;
})(typeof window!=='undefined'?window:globalThis);
