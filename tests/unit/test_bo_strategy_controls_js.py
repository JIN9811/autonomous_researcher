"""The workspace forwards strategy authority without restoring preference scoring."""
import json
from pathlib import Path

from tests.unit.test_bo_visualization_js import _node_eval, RENDERER

ROOT = Path(__file__).resolve().parents[2]


def test_workspace_strategy_control_survives_defaults_restore_and_submission():
    script = ROOT / "web/static/bo.js"
    result = _node_eval(f"""
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync({json.dumps(str(script))}, 'utf8');
const elements = {{}};
const context = {{document: {{getElementById: id => elements[id] ||= {{
  _value:'', get value() {{ return this._value; }}, set value(v) {{ this._value=String(v); }} }} }},
  pretty: JSON.stringify, defaults: {{}}}};
vm.createContext(context);
const bindings = source.slice(source.indexOf('const strategyInput ='), source.indexOf('const btnBenchmark ='));
const funcs = source.slice(source.indexOf('function boolValue('), source.indexOf('function renderCurve('));
vm.runInContext(bindings + funcs, context);
context.applyDefaults({{defaults: {{parameter_space: {{cell_size_mm:[5,10], relative_density:[.2,.48]}}}}}});
const initial = context.settingsPayload();
context.applySettings({{strategy_control:'adaptive', acquisition:'upper_confidence_bound',
  llm_preference_enabled:true, llm_candidate_weight:.45}});
const restored = context.settingsPayload();
console.log(JSON.stringify({{initial:initial.strategy_control, restored:restored.strategy_control,
  acquisition:restored.acquisition, preference:restored.llm_preference_enabled,
  weight:restored.llm_candidate_weight}}));
""")
    assert result == {"initial": "configured", "restored": "adaptive",
                      "acquisition": "upper_confidence_bound", "preference": False, "weight": 0}


def test_decision_display_exposes_validated_actions_without_raw_model_output():
    result = _node_eval(f"""
const renderer=require({json.dumps(str(RENDERER))});
const decision={{schema:'bo_decision.v1',status:'accepted',provenance:'llm',
  reason:'<script>unsafe</script>',trace:[{{status:'valid',response:'RAW_PRIVATE_RESPONSE',
    request:{{tool:'run_optimizer',arguments:{{acquisition:'upper_confidence_bound'}},reason:'Use UCB',evidence_refs:['diagnostics:current']}}}}]}};
const html = renderer.renderDecision(decision);
console.log(JSON.stringify({{action:html.includes('run_optimizer'),
  status:html.includes('accepted'), evidence:html.includes('diagnostics:current'),
  escaped:html.includes('&lt;script&gt;'), noScript:!html.includes('<script>'),
  noRaw:!html.includes('RAW_PRIVATE_RESPONSE')}}));
""")
    assert all(result.values()), result
