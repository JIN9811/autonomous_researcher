const test = require('node:test');
const assert = require('node:assert/strict');
const view = require('../../web/static/module_control_view.js');
const editor = require('../../web/static/module_execution_editor.js');
const moduleConfig = {id:'sample',label:'Sample',execution_graph:{schema:'ax4lab.execution_graph.v1',
  entry:'decision',terminals:['decision'],nodes:[{id:'decision',handler:'sample.decide',label:'Choose',area:'middle',llm:true}],edges:[]}};
const catalog = {operations:[{handler:'sample.decide',outcomes:['next']}],implementation_structure:{operations:{
  'sample.decide':{nodes:[{id:'inspect',label:'Inspect <evidence>',area:'low',source:{path:'agents/sample.py',symbol:'inspect'}}],
    edges:[{source:'$operation',target:'inspect',kind:'call',label:'inspect'},
      {source:'inspect',target:'$operation',kind:'evidence',label:'observation'}]}
}}};

test('internal relation projection binds handler instances without altering saved execution nodes',()=>{
  const graph=editor.project({module:moduleConfig},catalog,'rev',view);
  const detail=graph.metadata.control_view.details;
  assert.equal(detail?.nodes.length,1);
  assert.equal(detail.nodes[0].owner,'decision');
  assert.equal(detail.edges.length,2);
  const serialized=editor.serialize(graph,{module:moduleConfig}).module.execution_graph;
  assert.equal(serialized.nodes.length,1);
  assert.deepEqual(serialized.edges,[]);
  assert.equal(serialized.nodes[0].handler,'sample.decide');
  const before=JSON.stringify(graph);
  const markup=view.backdrop(graph.nodes,graph.metadata.control_view);
  assert.match(markup,/Inspect &lt;evidence&gt;/);
  assert.match(markup,/data-implementation-node/);
  assert.equal(JSON.stringify(graph),before);
  editor.removeNode(graph,'decision');
  assert.doesNotMatch(view.backdrop(graph.nodes,graph.metadata.control_view),/Inspect &lt;evidence&gt;/);
});

test('document theme and IDE theme share structure but not dark document backgrounds',()=>{
  const paper=view.renderSvg(moduleConfig,{theme:'document',catalog});
  const runtime=view.renderSvg(moduleConfig,{theme:'runtime',catalog});
  assert.match(paper,/Inspect &lt;evidence&gt;/);
  assert.match(paper,/data-theme="document"/);
  assert.doesNotMatch(paper,/#0c1524|#132135|#e6edf7/);
  assert.match(runtime,/#0c1524/);
  assert.match(paper,/observation/);
});

test('added and rebound owner operations update their code-bound details immediately',()=>{
  const graph=editor.project({module:moduleConfig},catalog,'rev',view);
  editor.addNode(graph,'sample.decide',{x:620,y:250});
  const markup=view.backdrop(graph.nodes,graph.metadata.control_view);
  assert.equal((markup.match(/data-implementation-node=/g)||[]).length,2);
  graph.nodes[0].handler='unregistered.changed';
  const rebound=view.backdrop(graph.nodes,graph.metadata.control_view);
  assert.equal((rebound.match(/data-implementation-node=/g)||[]).length,1);
});
