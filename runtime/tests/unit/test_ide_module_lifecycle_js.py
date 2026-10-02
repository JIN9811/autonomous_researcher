"""IDE preview describes draft changes without applying them."""
import json
from pathlib import Path
import subprocess

from test_planning_design_report_js import _extract_function


def test_lifecycle_markup_distinguishes_applied_and_draft_and_escapes_names():
    source = (Path(__file__).resolve().parents[2] / "web/static/runtime_ide.js").read_text()
    fn = _extract_function(source, "moduleLifecyclePreviewMarkup")
    payload = {"applied": ["design_agent"], "draft": ["<new>"],
               "added": ["<new>"], "removed": ["design_agent"], "running": True}
    script = "const escapeHtml=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');\n" + fn
    script += "\nprocess.stdout.write(moduleLifecyclePreviewMarkup(" + json.dumps(payload) + "));"
    html = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    for text in ("Applied", "Draft", "Add", "Remove", "design_agent", "&lt;new&gt;", "run is active", "History"):
        assert text in html
    assert "<new>" not in html


def test_older_manifest_response_cannot_reattach_removed_design():
    source = (Path(__file__).resolve().parents[2] / "web/static/planning.js").read_text()
    fn = "async " + _extract_function(source, "refreshLiveAgentManifest")
    script = """
const assert = require('node:assert/strict');
let LIVE_AGENTS = [], liveAgentManifestRequestGeneration = 0;
let liveAgentManifestStatus = {ok:true}, liveLastSession = null;
const pending = [], applied = [];
const fetch = () => new Promise(resolve => pending.push(resolve));
const applyLiveAgentManifest = payload => {LIVE_AGENTS=payload.agents; applied.push(payload.agents); return true;};
const liveAgentModuleHost = {reconcile:async()=>({errors:[]})};
const liveAgentModuleHostServices = () => ({});
const setChatStatus = () => {};
""" + fn + """
(async()=>{
  const older=refreshLiveAgentManifest(), newer=refreshLiveAgentManifest();
  pending[1]({ok:true,json:async()=>({ok:true,agents:[]})});
  await newer;
  pending[0]({ok:true,json:async()=>({ok:true,agents:[{id:'design'}]})});
  await older;
  assert.deepEqual(LIVE_AGENTS, []);
  assert.equal(applied.length, 1);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
