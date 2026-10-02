"""Contract projections reuse the graph renderer without running devices."""
from pathlib import Path
import subprocess
from test_planning_design_report_js import _extract_function


def test_bridge_projection_uses_shared_canvas_and_safe_common_inspector():
    root = Path(__file__).resolve().parents[2]
    source = (root / "web/static/runtime_ide.js").read_text()
    functions = "\n".join(("async " if f"async function {name}(" in source else "") + _extract_function(source, name) for name in (
        "renderDeviceBridges", "renderBridgeNodeInspector", "beginNodeDrag", "beginPortConnect",
        "removeGraphNodeFromDraft", "applyTransitionEdit", "deleteSelectedEdge",
        "validateGraph", "compileGraph", "dryRunGraph", "saveGraph", "saveBridgeCustomActionDescriptor",
        "addCatalogModuleToCanvas", "addCatalogModuleAsGraphNode",
    ))
    script = r'''
const assert=require('node:assert/strict');
const AX4LABExperimentalPackages=require('./web/static/experimental_packages.js');
const packageCatalogPayload={schema:'ax4lab.package_catalog.v1',ok:true,
  agent_packages:[{id:'specimen',version:'1.0.0',bridge_modules:[{id:'fleet',version:'1.0.0'}]}],
  bridge_modules:[{id:'fleet',version:'1.0.0',label:'<script>bad</script>',
    ui:{workspace:'//external.invalid'},providers:[{id:'bambu',component:'internal.bambu'}]}]};
const experimentalPackageRefs=[{id:'specimen',version:'1.0.0'}];
const latestStateSnapshot={runtime_ide_contract:{device_bridges:[{id:'robot',label:'Robot'}]}};
const tab={kind:'bridges'}, activeGraphTab=()=>tab;
const cloneConfig=value=>JSON.parse(JSON.stringify(value));
let activeGraph=null;
const renderGraph=graph=>{activeGraph=graph};
const escapeHtml=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const compactJson=JSON.stringify;
const nodeInspector={innerHTML:'',querySelector:()=>null};
const closePackageCompositionView=()=>{};
const dryRunOutput={innerHTML:'preserved trace'};
''' + functions + r'''
(async()=>{
renderDeviceBridges();
assert.equal(activeGraph.id,'device-bridge-plane');
assert.ok(activeGraph.nodes.some(n=>n.label==='Robot'));
assert.ok(!activeGraph.nodes.some(n=>n.label==='bambu'));
renderBridgeNodeInspector(activeGraph.nodes.find(n=>n.kind==='bridge'));
assert.ok(nodeInspector.innerHTML.includes('runtime-node-inspector-card'));
assert.ok(!nodeInspector.innerHTML.includes('<script>'));
assert.ok(!nodeInspector.innerHTML.includes('href="//'));
assert.ok(!nodeInspector.innerHTML.includes('data-package-draft-toggle'));
assert.ok(nodeInspector.innerHTML.includes('data-bridge-enter'));
tab.bridgeId='fleet';
renderDeviceBridges();
assert.equal(activeGraph.id,'bridge:fleet');
assert.ok(activeGraph.nodes.some(n=>n.label==='bambu'));
assert.equal(activeGraph.nodes.some(n=>n.label==='Robot'),false);
assert.deepEqual(tab.baselineGraph,activeGraph);
// Downstream helpers are deliberately absent: reaching one fails this test.
beginNodeDrag({button:0},'x'); beginPortConnect('x');
assert.equal(removeGraphNodeFromDraft('x'),false);
applyTransitionEdit(); deleteSelectedEdge();
await validateGraph(); await compileGraph(); await dryRunGraph(); await saveGraph();
await saveBridgeCustomActionDescriptor();
addCatalogModuleToCanvas('specimen',{}); addCatalogModuleAsGraphNode({id:'specimen'},{});
assert.equal(dryRunOutput.innerHTML,'preserved trace');
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    result = subprocess.run(["node", "-e", script], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
