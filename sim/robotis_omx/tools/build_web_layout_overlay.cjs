// Derive the Isaac environment overlay from the Live Robot Pose geometry.
// Robot transforms, joints, physics settings and the original stage are untouched.
const fs = require('node:fs');
const path = require('node:path');
const {boxUnion}=require('../../../web/frontend/omx_telemetry_viewer/src/box_union.cjs');
const sceneDir = path.resolve(__dirname, '../scene');
const manifest = JSON.parse(fs.readFileSync(path.join(sceneDir, 'omx_table_layout.web.json')));
const tuple = values => `(${values.join(', ')})`;
const oldMarkers = {A4CenterMarker:[.315,.245,.00014],RightDiskCenterYellowMarker:[.59,.078,.1043]};
let out = '#usda 1.0\n(\n    defaultPrim = "World"\n    metersPerUnit = 1\n    upAxis = "Z"\n    subLayers = [@./omx_table_layout.usda@]\n)\n\nover "World"\n{\n';
for (const group of ['Table', 'Workspace']) {
  out += `    over "${group}"\n    {\n`;
  const removed = group === 'Table'
    ? ['RobotBasePocketFloor','TableTopRedwoodGrainSurface_Back','TableTopRedwoodGrainSurface_FrontLeft','TableTopRedwoodGrainSurface_FrontRight','RobotBasePocketFloorRedwoodGrainSurface']
    : ['A4CornerMarker_1','A4CornerMarker_2','A4CornerMarker_3','A4CornerMarker_4'];
  for (const name of removed) out += `        over "${name}" (active = false) {}\n`;
  for (const item of manifest.objects.filter(o=>o.source_prim.startsWith(`/World/${group}/`))) {
    if(group==='Table') { out += `        over "${item.name}" (active = false) {}\n`; continue; }
    const added = item.name.endsWith('TrayGuard');
    out += `        ${added ? 'def Cube' : 'over'} "${item.name}"${added ? ' (prepend apiSchemas = ["PhysicsCollisionAPI"])' : ''}\n        {\n`;
    if (added) out += '            double size = 1\n            bool physics:collisionEnabled = true\n';
    if (item.primitive === 'box') out += `            float3 xformOp:scale = ${tuple(item.size)}\n`;
    const old = oldMarkers[item.name];
    const position = old ? item.position.map((v,i)=>Number((v-old[i]).toFixed(9))) : item.position;
    out += `            double3 xformOp:translate = ${tuple(position)}\n`;
    const rotated = Number.isFinite(item.rotation_z_deg);
    if (rotated) out += `            double xformOp:rotateZ = ${item.rotation_z_deg}\n`;
    out += `            uniform token[] xformOpOrder = ["xformOp:translate"${rotated?', "xformOp:rotateZ"':''}${item.primitive==='box'?', "xformOp:scale"':''}]\n`;
    if (group === 'Table') out += '            rel material:binding = </World/Materials/dark_base>\n';
    out += '        }\n';
  }
  out += '    }\n';
}
const quads=boxUnion(manifest.objects.filter(o=>o.source_prim.startsWith('/World/Table/') && o.primitive==='box'));
out += `    def Mesh "UnifiedWorkstationBody" (prepend apiSchemas = ["PhysicsCollisionAPI"])\n    {\n`;
out += '        bool physics:collisionEnabled = true\n        uniform token subdivisionScheme = "none"\n';
out += '        rel material:binding = </World/Materials/dark_base>\n';
out += `        int[] faceVertexCounts = [${quads.map(()=>4).join(', ')}]\n`;
out += `        int[] faceVertexIndices = [${quads.flatMap((_,i)=>[i*4,i*4+1,i*4+2,i*4+3]).join(', ')}]\n`;
out += `        point3f[] points = [${quads.flatMap(q=>q.points.map(tuple)).join(', ')}]\n    }\n`;
out += '}\n';
// stdout allows callers to review/apply the generated asset without overwriting stages.
process.stdout.write(out);
