import json
import subprocess

from app.controller import MainController


def test_stage_transition_survives_compaction_and_clicks_destination():
    controller = MainController.__new__(MainController)
    event = controller._compact_event_for_buffer({
        "event_id": "transition-1", "run_id": "run-1",
        "event_type": "stage_transition", "type": "edge.traversed",
        "payload": {"from_stage": "design", "to_stage": "specimen", "large_unrelated": [1, 2, 3]},
    })
    assert event["payload"] == {"from_stage": "design", "to_stage": "specimen"}
    script = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const event = JSON.parse(process.argv[1]);
const clicks = [];
const ctx = vm.createContext({liveLastAgentTransitionKey:'', liveSelectedAgent:'design',
  liveCurrentRunId:()=> 'run-1', agentIdFromStage:s=>s, knownLiveAgent:s=>s==='specimen',
  liveAgentBinderList:{querySelectorAll:()=>[{dataset:{agentId:'specimen'},click:()=>clicks.push('specimen')}]}});
const src=fs.readFileSync('web/static/planning.js','utf8');
const start=src.indexOf('function selectAgentOnOrchestrationTransition(');
vm.runInContext(src.slice(start,src.indexOf('\n}',start)+2),ctx);
ctx.selectAgentOnOrchestrationTransition(event);
ctx.selectAgentOnOrchestrationTransition(event);
assert.deepEqual(clicks,['specimen']);
'''
    subprocess.run(["node", "-e", script, json.dumps(event)], check=True)
