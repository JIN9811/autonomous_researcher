const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const THREE = require('../../web/frontend/omx_telemetry_viewer/node_modules/three');
const source = fs.readFileSync('web/frontend/omx_telemetry_viewer/src/index.js', 'utf8');
for (const compact of [false,true]) test(`${compact ? 'backend compact' : 'full'} batched release uses that sample joint pose, not the previous render frame`, () => {
  const root = new THREE.Group();
  const joint = new THREE.Group(); root.add(joint);
  const anchor = new THREE.Object3D(); anchor.position.set(1,0,0); joint.add(anchor);
  const measuredRobot = {root, joints:new Map([['Joint1',{group:joint,axis:new THREE.Vector3(0,0,1)}]])};
  const releases = [];
  const context = {THREE, JOINT_NAMES:['Joint1'],runtime:{sessionId:'run',latestSequence:-1,executionIndex:1,history:[],viewer:{measuredRobot}},
    resetSession:()=>{throw Error('unexpected reset');},
    applySpecimenGraspVisualization: outcome => {if(outcome.gripper_state === 'ungrasping') releases.push(anchor.getWorldPosition(new THREE.Vector3()).toArray());},
  };
  const apply = source.slice(source.indexOf('function applyJointRadians('),source.indexOf('function interpolateJointMap('));
  const append = source.slice(source.indexOf('function appendSample('),source.indexOf('function applySampleDisplay('));
  vm.createContext(context); vm.runInContext(apply+append, context);
  context.sample={type:'joint_sample',session_id:'run',execution_index:1,sequence:1,actual_rad:{Joint1:Math.PI/2},grasp_visual:{status:'success',gripper_state:'ungrasping'}};
  if (compact) {
    context.sample = JSON.parse(execFileSync('.venv/bin/python',['-c',`
import json,sys
from utils.lerobot_joint_telemetry import build_joint_telemetry_batch
packet=json.load(sys.stdin)
packet['motion_state']={'grasp_outcome':{'status':'success'},'measured':{'gripper_state':'ungrasping'}}
print(json.dumps(build_joint_telemetry_batch([packet],compact=True)['samples'][0]))
`],{input:JSON.stringify(context.sample),encoding:'utf8'}));
  }
  vm.runInContext('appendSample(sample,false)',context);
  assert.ok(Math.abs(releases[0][0]) < 1e-8);
  assert.ok(Math.abs(releases[0][1]-1) < 1e-8);
});

test('late model loading preserves the release position even after the robot returns home', async () => {
  const scene=new THREE.Scene(), environmentGroup=new THREE.Group(), root=new THREE.Group(), joint=new THREE.Group();
  scene.add(environmentGroup,root); root.add(joint);
  const cube=new THREE.Group(); cube.name='RedSpecimenBlock'; environmentGroup.add(cube);
  const graspAnchor=new THREE.Object3D(); graspAnchor.position.set(1,0,0); joint.add(graspAnchor);
  const viewer={scene,environmentGroup,graspAnchor,measuredRobot:{root,joints:new Map([['Joint1',{group:joint,axis:new THREE.Vector3(0,0,1)}]])},specimenGraspState:{held:false,attemptIndex:null,releasedAttemptIndex:null,original:null,poseLocked:false}};
  const context=vm.createContext({THREE,fixtureViewer:viewer});
  vm.runInContext(source.replace(/^import .*;$/gm,'').split('window.ATRRobotTelemetryCards =')[0]+`
    createViewer=async()=>fixtureViewer;
    runtime.history=[
      {actual_rad:{Joint1:0},grasp_visual:{status:'pending',attempt_index:1,gripper_state:'grasping'}},
      {actual_rad:{Joint1:Math.PI/2},grasp_visual:{status:'success',attempt_index:1,gripper_state:'ungrasping'}},
      {actual_rad:{Joint1:0},grasp_visual:{status:'success',attempt_index:1,gripper_state:'idle'}}
    ];
    runtime.latestActualRad={Joint1:0};
    globalThis.ready=ensureViewer();
  `,context);
  await context.ready;
  assert.equal(viewer.specimenGraspState.held,false);
  assert.equal(viewer.specimenGraspState.releasedAttemptIndex,1);
  assert.ok(Math.abs(cube.position.x)<1e-8);
  assert.ok(Math.abs(cube.position.y-1)<1e-8);
  assert.ok(Math.abs(joint.rotation.z)<1e-8);
});
