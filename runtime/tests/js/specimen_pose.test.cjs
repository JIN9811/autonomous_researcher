const test=require('node:test');
const assert=require('node:assert/strict');
const {specimenPosition}=require('../../web/frontend/omx_telemetry_viewer/src/specimen_pose.cjs');
test('poses predating server startup cannot override spawn; post-start poses survive page reloads',()=>{
 const fallback=[.315,.2475,.0152],start=Date.parse('2026-09-15T00:00:00Z');
 const pose={schema:'specimen_pose.v1',timestamp:'2026-09-07T08:03:18Z',position_isaac_world_mm:{x:323,y:366,z:15}};
 assert.deepEqual(specimenPosition(pose,fallback,start),fallback);
 assert.deepEqual(specimenPosition({...pose,timestamp:'2026-09-15T00:00:01Z'},fallback,start),[.323,.366,.015]);
 assert.deepEqual(specimenPosition({...pose,timestamp:null},fallback,start),fallback);
 // A later page reload reuses the same server cutoff, not the browser clock.
 assert.deepEqual(specimenPosition({...pose,timestamp:'2026-09-15T00:00:01Z'},fallback,start),[.323,.366,.015]);
});
test('absent and incomplete pose use the input-centered spawn; zero coordinates remain valid',()=>{
 const fallback=[.315,.2475,.0152];
 for(const pose of [null,{}, {schema:'specimen_pose.v1',position_isaac_world_mm:null}, {schema:'specimen_pose.v1',position_isaac_world_mm:{x:null,y:20,z:30}}]) assert.deepEqual(specimenPosition(pose,fallback),fallback);
 assert.deepEqual(specimenPosition({schema:'specimen_pose.v1',position_isaac_world_mm:{x:0,y:200,z:15}},fallback),[0,.2,.015]);
});
