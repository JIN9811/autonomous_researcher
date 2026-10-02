const test=require('node:test');
const assert=require('node:assert/strict');
global.window={};
require('../../web/static/runtime_graph_geometry.js');
const geometry=window.ATRRuntimeGraphGeometry;

test('route labels avoid obstacles along their own line, without floating away',()=>{
  const candidates=[{x:100,y:50},{x:70,y:50},{x:130,y:50}];
  const [label]=geometry.resolveLabelCollisions([{key:'next',x:100,y:50,width:20,height:12,candidates}],
    {gap:4,obstacles:[{left:90,top:30,right:110,bottom:70}]});
  assert.equal(label.y,50);
  assert.equal(label.x,70);
});

test('curve anchors follow the drawn Bezier rather than a displaced grid',()=>{
  const edge={source:{position:{x:0,y:0}},target:{position:{x:384,y:0}},sourceSide:'right',targetSide:'left'};
  // Start port is x=192, target port x=376; all control points lie at y=38.
  assert.deepEqual(geometry.labelPoint(edge,{labelT:0}),{x:192,y:38});
  assert.deepEqual(geometry.labelPoint(edge,{labelT:1}),{x:376,y:38});
});
