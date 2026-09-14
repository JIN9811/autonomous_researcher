const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const scene = JSON.parse(fs.readFileSync('sim/robotis_omx/scene/omx_table_layout.web.json'));
const object = name => scene.objects.find(item => item.name === name);
const top = item => item.position[2] + (item.height || item.size[2]) / 2;
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`);
test('base pocket fits the robot and preserves drawing tray depth without upper/lower overlap',()=>{
 const baseMin=[.240,0,-.020],baseMax=[.390,.120,.0375];
 for(const o of scene.objects.filter(o=>o.source_prim.startsWith('/World/Table/'))) {
  const overlaps=[0,1,2].map(i=>Math.min(baseMax[i],o.position[i]+o.size[i]/2)-Math.max(baseMin[i],o.position[i]-o.size[i]/2));
  assert.ok(overlaps.some(v=>v<1e-8),o.name+' intersects base');
 }
 const upper=object('TableTop'),wall=object('LeftTrayGuard');
 near(upper.position[0]-upper.size[0]/2,.4025);
 const tray=object('TableTopFrontLeft');
 near(tray.position[0]-tray.size[0]/2,.2275);
 near(tray.position[0]+tray.size[0]/2,upper.position[0]-upper.size[0]/2);
 near((baseMin[0]+baseMax[0])/2,tray.position[0]);
 const rear=object('TableTopFrontRight');
 near(rear.position[0]-rear.size[0]/2,baseMax[0]);
 near(rear.position[0]+rear.size[0]/2,.4025);
 const tables=scene.objects.filter(o=>o.source_prim.startsWith('/World/Table/'));
 for(let i=0;i<tables.length;i++)for(let j=i+1;j<tables.length;j++) {
   const a=tables[i],b=tables[j];
   const overlap=[0,1,2].map(k=>Math.min(a.position[k]+a.size[k]/2,b.position[k]+b.size[k]/2)-Math.max(a.position[k]-a.size[k]/2,b.position[k]-b.size[k]/2));
   assert.ok(overlap.some(v=>v<1e-8),a.name+' overlaps '+b.name);
 }
 near(wall.position[1]+wall.size[1]/2-baseMax[1],.265);
 assert.deepEqual(object('RedSpecimenBlock').position.slice(0,2),object('A4Sheet').position.slice(0,2));
});
test('input has one center sticker and Isaac generation ignores web-only display offsets', () => {
  const stickers = scene.objects.filter(o=>o.name.startsWith('A4') && o.primitive==='circle');
  assert.equal(stickers.length, 1);
  assert.deepEqual(stickers[0].position.slice(0,2), object('A4Sheet').position.slice(0,2));
  const generated=require('node:child_process').execFileSync(process.execPath,['sim/robotis_omx/tools/build_web_layout_overlay.cjs'],{encoding:'utf8'});
  assert.equal(fs.readFileSync('sim/robotis_omx/scene/'+scene.source,'utf8').trim(),generated.trim());
});
test('raised platform and guards share the tray datum and preserve robot calibration', () => {
  assert.deepEqual(scene.robot_anchor, {position:[.315,.06,-.02],rotation_z_deg:90});
  near(top(object('TableTopFrontLeft')), 0);
  near(top(object('LeftTrayGuard')), .05);
  near(top(object('TableTop')), .065);
  near(top(object('TableTop')) - top(object('LeftTrayGuard')), .015);
});
test('platen assembly moves 30 mm toward robot without changing height or lateral alignment', () => {
  const platen=object('RightDiskAluminumTop');
  // Front center of the actual fixed base: X=315, Y=120 mm.
  near(platen.position[0] - .315, .22); // Isaac source remains unchanged.
  near(platen.position[1] - .120, .06);
  near(platen.position[2]-platen.height/2, top(object('TableTop')));
  assert.equal(platen.primitive,'cylinder');
  const vm=require('node:vm');
  const THREE=require('../../web/frontend/omx_telemetry_viewer/node_modules/three');
  const src=fs.readFileSync('web/frontend/omx_telemetry_viewer/src/index.js','utf8');
  const context=vm.createContext({THREE});
  vm.runInContext(src.replace(/^import .*;$/gm,'').split('window.ATRRobotTelemetryCards =')[0]+'\nglobalThis.make=buildEnvironmentObject;',context);
  for (const name of ['RightDiskAluminumTop','RightDiskBlackBase','RightDiskCenterYellowMarker']) {
    const item=object(name);
    const rendered=context.make({...item,surface_grid:false},{});
    assert.deepEqual(rendered.position.toArray(),[.505,.180,item.position[2]]);
    assert.deepEqual(item.position.slice(0,2),[.535,.180]);
  }
  near(platen.radius,.05);
  near(platen.height,.104);
});
test('environment rotates clockwise while tray depth center stays aligned with the fixed robot', () => {
  const tray=object('TableTopFrontLeft');
  near(tray.position[0], scene.robot_anchor.position[0]);
  near(tray.position[1], .2525);
  assert.deepEqual(tray.size, [.175,.265,.02]);
  near(object('A4Sheet').position[0], .315);
  near(object('A4Sheet').position[1], .2475);
});
test('lower tray reaches robot base offset without moving its working surface', () => {
  for(const name of ['TableTopFrontLeft','TableTopFrontRight']) {
    const item=object(name);
    near(item.position[2]-item.size[2]/2, scene.robot_anchor.position[2]);
    near(top(item), 0);
  }
  const upper=object('TableTop');
  near(upper.position[2]-upper.size[2]/2, -.02);
  near(upper.position[1]-upper.size[1]/2, -.01);
  near(upper.position[1]+upper.size[1]/2, .385);
});
