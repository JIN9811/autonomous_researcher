const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const THREE = require('../../web/frontend/omx_telemetry_viewer/node_modules/three');
const source = fs.readFileSync('web/frontend/omx_telemetry_viewer/src/index.js','utf8');

test('reset unlocks a released specimen and restores its configured input position', () => {
  const factory = vm.createContext({THREE});
  vm.runInContext(source.replace(/^import .*;$/gm,'').split('window.ATRRobotTelemetryCards =')[0] + '\nglobalThis.make = buildEnvironmentObject;',factory);
  const specimen = factory.make({name:'RedSpecimenBlock',primitive:'box',size:[.03,.03,.03],position:[0.315,0.2475,0.0152],rotation_z_deg:0,surface_grid:false},{});
  specimen.position.set(0.535,0.180,0.185);
  const environmentGroup = new THREE.Group(); environmentGroup.add(specimen);
  const viewer={environmentGroup,specimenGraspState:{held:false,poseLocked:true,attemptIndex:1,releasedAttemptIndex:1}};
  const context={THREE,runtime:{viewer,specimenPoseFrameId:'old'},specimenObject:()=>specimen,setGripperOutcomeGlow:()=>{}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function resetSpecimenGraspVisualization('),source.indexOf('function applySpecimenGraspVisualization(')),context);
  vm.runInContext('resetSpecimenGraspVisualization()',context);
  assert.deepEqual(specimen.position.toArray(),[0.315,0.2475,0.0152]);
  assert.equal(viewer.specimenGraspState.poseLocked,false);
  assert.equal(viewer.specimenGraspState.releasedAttemptIndex,null);
});

test('server reset clears display history and rejects older in-flight packets', () => {
  const runtime={resetAtMs:0,sessionId:'old',history:[1],latestTargetRad:{Joint1:1}};
  const context={runtime,resetSession:id=>{runtime.sessionId=id;runtime.history=[];runtime.latestTargetRad={};},setPoseStatus:()=>{},setTrackingStatus:()=>{},applyRuntimeView:()=>{}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function consumePacket('),source.indexOf('function telemetryMountsPresent(')),context);
  vm.runInContext('consumePacket({type:"telemetry_state",status:"idle",reset_at_ms:100,session:{}})',context);
  assert.deepEqual(runtime.history,[]);
  assert.deepEqual(runtime.latestTargetRad,{});
  vm.runInContext('consumePacket({type:"telemetry_state",status:"complete",reset_at_ms:0,session:{session_id:"old"}})',context);
  assert.equal(runtime.sessionId,'');
  assert.equal(runtime.status,'idle');
});
