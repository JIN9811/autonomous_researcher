const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const THREE = require('../../web/frontend/omx_telemetry_viewer/node_modules/three');
const source = fs.readFileSync('web/frontend/omx_telemetry_viewer/src/index.js', 'utf8');
test('FIT frames the platform on the left and robot on the right as in the approved view', () => {
  const robot = new THREE.Mesh(new THREE.BoxGeometry(.15,.12,.25));
  robot.position.set(.315,.06,.105);
  const environment = new THREE.Mesh(new THREE.BoxGeometry(.395,.395,.085));
  environment.position.set(.425,.1875,.0225);
  const camera = new THREE.PerspectiveCamera(38, 2, .005, 10);
  camera.up.set(0,0,1);
  const controls = {target: new THREE.Vector3(),update(){camera.lookAt(this.target);camera.updateMatrixWorld();}};
  const context = {THREE,camera,controls,measuredRobot:{root:robot},environmentGroup:environment};
  const start = source.indexOf('  const bounds = new THREE.Box3().setFromObject(measuredRobot.root)');
  const end = source.indexOf('  const currentActual =', start);
  vm.createContext(context);
  vm.runInContext(source.match(/^const CAMERA_FIT_.*$/gm).join('\n') + '\n' + source.slice(start,end)+'\nzoomToFit();',context);
  const platen = new THREE.Vector3(.535,.18,.169).project(camera);
  const base = new THREE.Vector3(.315,.06,0).project(camera);
  assert.ok(platen.x < base.x, 'platen must be left of robot in the FIT view');
  let extent = 0;
  for (const mesh of [robot, environment]) {
    const b = new THREE.Box3().setFromObject(mesh);
    for (const x of [b.min.x,b.max.x]) for (const y of [b.min.y,b.max.y]) for (const z of [b.min.z,b.max.z]) {
      const p = new THREE.Vector3(x,y,z).project(camera);
      extent = Math.max(extent,Math.abs(p.x),Math.abs(p.y));
      assert.ok(Math.abs(p.x)<1 && Math.abs(p.y)<1, 'FIT keeps the complete workstation inside the viewport');
    }
  }
  assert.ok(extent > .91, 'FIT uses the card space instead of leaving oversized margins');
});
