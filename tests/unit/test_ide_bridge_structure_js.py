"""Render the real bridge view without transports or browser globals."""
from pathlib import Path
import subprocess
from test_planning_design_report_js import _extract_function


def test_bridge_structure_renders_owned_providers_safely_without_management_controls():
    root = Path(__file__).resolve().parents[2]
    function = _extract_function((root / "web/static/runtime_ide.js").read_text(), "renderDeviceBridges")
    script = r'''
const assert=require('node:assert/strict');
const AX4LABExperimentalPackages=require('./web/static/experimental_packages.js');
const packageCatalogPayload={schema:'ax4lab.package_catalog.v1',ok:true,
  agent_packages:[{id:'specimen',version:'1.0.0',bridge_modules:[{id:'fleet',version:'1.0.0'}]}],
  bridge_modules:[{id:'fleet',version:'1.0.0',label:'<script>bad</script>',
    ui:{workspace:'//external.invalid'},providers:[{id:'bambu',component:'internal.bambu'}]}]};
const experimentalPackageRefs=[{id:'specimen',version:'1.0.0'}];
let selectedBridgeDetailId='';
const escapeHtml=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let writes=0,markup='';
const packageCompositionOutput={dataset:{},get innerHTML(){return markup},set innerHTML(value){markup=value;writes++},
 querySelector:()=>null,querySelectorAll:()=>[]};
const closePackageCompositionView=()=>{};
''' + function + r'''
renderDeviceBridges();
assert.ok(markup.includes('<svg'));
assert.ok(markup.includes('INTERNAL PROVIDER'));
assert.ok(!markup.includes('<script>'));
assert.ok(!markup.includes('href="//'));
assert.ok(!markup.includes('data-package-draft-toggle'));
assert.ok(!markup.includes('Export Package'));
renderDeviceBridges();
assert.equal(writes,1,'Unchanged live graph updates must not reset view scroll/focus');
selectedBridgeDetailId='bridge:fleet@1.0.0:provider:bambu';
renderDeviceBridges();
assert.ok(markup.includes('internal.bambu'));
assert.equal(writes,2);
'''
    result = subprocess.run(["node", "-e", script], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
