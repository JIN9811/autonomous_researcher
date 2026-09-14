const {test}=require('node:test');
const assert=require('node:assert/strict');
const {boxUnion}=require('../../web/frontend/omx_telemetry_viewer/src/box_union.cjs');
test('touching blocks expose no contact face and keep exterior area',()=>{
 const q=boxUnion([{position:[0,0,0],size:[2,2,2]},{position:[2,0,0],size:[2,2,2]}]);
 assert.ok(q.every(f=>!(f.axis===0&&f.points[0][0]===1)));
 const area=q.reduce((sum,f)=>{const u=(f.axis+1)%3,v=(f.axis+2)%3;return sum+(Math.max(...f.points.map(p=>p[u]))-Math.min(...f.points.map(p=>p[u])))*(Math.max(...f.points.map(p=>p[v]))-Math.min(...f.points.map(p=>p[v])));},0);
 assert.equal(area,40);
});
