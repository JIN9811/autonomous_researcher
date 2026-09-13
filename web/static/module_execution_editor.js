/* Adapter for the shared owner execution definition. No routing is inferred. */
(function(root) {
  'use strict';
  const copy=value=>JSON.parse(JSON.stringify(value));
  const isGraph=graph=>Boolean(graph?.metadata?.execution_graph);
  const operation=(graph,handler)=>graph.metadata.execution_catalog?.operations?.find(op=>op.handler===handler);
  function project(payload,catalog,revision,view) {
    const module=payload.module || payload, definition=module.execution_graph, control=view.layout(module,catalog);
    return {id:`module:${module.id}`,name:`${module.label || module.id} Execution Graph`,version:'draft',
      entry_node:definition.entry,finish_nodes:copy(definition.terminals),terminal_stages:copy(definition.terminals),transitions:{},
      stage_dispatch:Object.fromEntries(definition.nodes.map(node=>[node.id,node.id])),
      nodes:control.nodes.map(record=>({...copy(record.step),stage:record.key,kind:'execution_operation',module_id:`modules/${module.id}`,
        position:copy(record.position),metadata:{control_area:record.area,llm_decision:record.llm,module_step_phase:'execution_graph',icon:'artifact'}})),
      edges:definition.edges.map(edge=>({source:edge.source,target:edge.target,condition:edge.on,label:edge.on,kind:edge.kind,
        metadata:{runtime_edge:'logical_transition',from_stage:edge.source,to_stage:edge.target,execution_kind:edge.kind,auto_ports:true}})),
      metadata:{ide_tab_kind:'module',module_id:module.id,module_label:module.label,execution_graph:true,
        execution_schema:definition.schema,execution_catalog:copy(catalog || {operations:[]}),execution_graph_revision:revision || '',control_view:control}};
  }
  function serialize(graph,payload) {
    const result=copy(payload.module?payload:{module:payload});
    result.module.execution_graph={schema:graph.metadata.execution_schema,entry:graph.entry_node,
      nodes:graph.nodes.map(node=>{const output={id:node.id,handler:node.handler,label:node.label,area:node.area || node.metadata.control_area};
        for(const key of ['llm','config','position'])if(node[key]!==undefined)output[key]=copy(node[key]);return output;}),
      edges:graph.edges.map(edge=>({source:edge.source,target:edge.target,on:edge.condition,kind:edge.kind || edge.metadata?.execution_kind || 'execution'})),
      terminals:copy(graph.finish_nodes || [])};
    return result;
  }
  function addNode(graph,handler,position={x:400,y:400}) {
    const op=operation(graph,handler);if(!op)throw new Error('Choose a registered owner operation.');
    const base=handler.replace(/[^A-Za-z0-9_]/g,'_');let id=base,index=2;
    while(graph.nodes.some(node=>node.id===id))id=`${base}_${index++}`;
    const node={id,stage:id,label:op.label || handler,handler,area:'middle',config:{},position:copy(position),kind:'execution_operation',
      module_id:`modules/${graph.metadata.module_id}`,metadata:{control_area:'middle',module_step_phase:'execution_graph',icon:'artifact'}};
    graph.nodes.push(node);graph.stage_dispatch[id]=id;return node;
  }
  function removeNode(graph,id) {
    graph.nodes=graph.nodes.filter(node=>node.id!==id);graph.edges=graph.edges.filter(edge=>edge.source!==id && edge.target!==id);
    graph.finish_nodes=graph.finish_nodes.filter(node=>node!==id);delete graph.stage_dispatch[id];
    // Keep a deleted entry visibly invalid until the user chooses its replacement.
  }
  function deleteEdge(graph,source,target,on) {
    graph.edges=graph.edges.filter(edge=>!(edge.source===source && edge.target===target && edge.condition===on));
  }
  function upsertEdge(graph,source,target,on,kind='execution',previous=null,ports={}) {
    const node=graph.nodes.find(node=>node.id===source),op=operation(graph,node?.handler);
    if(!op?.outcomes?.includes(on))throw new Error('Choose an outcome declared by the source operation.');
    if(previous)deleteEdge(graph,previous.source,previous.target,previous.condition);
    deleteEdge(graph,source,target,on);
    graph.edges.push({source,target,condition:on,label:on,kind,metadata:{runtime_edge:'logical_transition',from_stage:source,to_stage:target,
      execution_kind:kind,auto_ports:ports.autoPorts!==false,source_port:ports.sourcePort || 'right',target_port:ports.targetPort || 'left'}});
    return {source,target,condition:on};
  }
  function nextOutcome(graph,source) {
    const node=graph.nodes.find(node=>node.id===source),outcomes=operation(graph,node?.handler)?.outcomes || [];
    return outcomes.find(outcome=>!graph.edges.some(edge=>edge.source===source && edge.condition===outcome)) || outcomes[0] || '';
  }
  function trace(graph,events,runId,dirty) {
    const empty={statuses:{},events:[],edge:null,invocation:null};
    if(dirty || !isGraph(graph) || !runId || !graph.metadata.execution_graph_revision)return empty;
    const scoped=events.filter(event=>{const p=event.payload || {};return p.schema==='ax4lab.execution_trace.v1' && p.module_id===graph.metadata.module_id && p.run_id===runId;});
    // The newest invocation wins even if its revision differs from this editor.
    const latest=scoped.find(event=>(event.type || event.event_type)==='execution.graph.started')?.payload;
    if(!latest || latest.graph_revision!==graph.metadata.execution_graph_revision)return empty;
    const selected=scoped.filter(event=>{const p=event.payload;return p.graph_revision===latest.graph_revision && p.invocation_id===latest.invocation_id && p.loop_index===latest.loop_index;});
    const statuses={};let edge=null;
    for(const event of [...selected].reverse()) {
      const p=event.payload,type=event.type || event.event_type;
      if(type==='execution.node.started')statuses[p.node_id]='running';
      if(type==='execution.node.completed')statuses[p.node_id]='done';
      if(type==='execution.node.failed')statuses[p.node_id]='failed';
      if(type==='execution.node.cancelled')statuses[p.node_id]='cancelled';
      if(type==='execution.edge.traversed')edge=p.edge;
    }
    return {statuses,events:selected,edge,invocation:latest.invocation_id};
  }
  const api={isGraph,project,serialize,operation,addNode,removeNode,deleteEdge,upsertEdge,nextOutcome,trace};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.AX4LABExecutionEditor=api;
})(typeof window!=='undefined'?window:globalThis);
