"""The operator must see decisions, software and devices in distinct areas."""
import json
import ast
import subprocess
from pathlib import Path

import pytest
import yaml

from agents.design.structure import design_implementation_structure
from agents.analysis.structure import analysis_implementation_structure
from agents.bo.structure import bo_implementation_structure
from agents.orchestrator_structure import orchestrator_implementation_structure
from agents.specimen.structure import specimen_implementation_structure
from agents.vision.structure import vision_implementation_structure
from agents.manipulation.structure import manipulation_implementation_structure
from agents.equipment.structure import equipment_implementation_structure

ROOT = Path(__file__).resolve().parents[2]
STRUCTURES = dict(design=design_implementation_structure, orchestrator=orchestrator_implementation_structure,
                  specimen=specimen_implementation_structure, vision=vision_implementation_structure,
                  manipulation=manipulation_implementation_structure,
                  equipment=equipment_implementation_structure,
                  analysis=analysis_implementation_structure, bo=bo_implementation_structure)
MODULES = [*STRUCTURES, 'analysis', 'bo', 'guardian', 'knowledge']


def projection(module_id):
    module = yaml.safe_load((ROOT / f'graphs/modules/{module_id}/module.yaml').read_text())['module']
    catalog = {'implementation_structure': STRUCTURES[module_id]()} if module_id in STRUCTURES else {}
    script = '''const v=require('./web/static/module_control_view.js');
const p=JSON.parse(process.argv[1]);process.stdout.write(JSON.stringify(v.layout(p.module,p.catalog)));'''
    result = subprocess.run(['node', '-e', script, json.dumps(dict(module=module, catalog=catalog))],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    return module, json.loads(result.stdout)


@pytest.mark.parametrize('module_id', MODULES)
def test_every_agent_exposes_its_local_llm_without_replacing_owner_steps(module_id):
    module, view = projection(module_id)
    assert view is not None, module_id
    nodes = view['nodes'] + view['details']['nodes']
    assert any(n['area'] == 'high' and (n.get('llm') or 'LLM' in n['label']) for n in nodes), module_id
    assert not any(n['area'] == 'unassigned' for n in nodes)
    expected = module.get('execution_graph', {}).get('nodes', module.get('internal_graph', []))
    assert [n['step'] for n in view['nodes']] == expected


@pytest.mark.parametrize('module_id', ['design', 'orchestrator', 'analysis', 'bo', 'knowledge', 'guardian'])
def test_software_only_agent_does_not_present_numeric_or_api_work_as_device_control(module_id):
    _, view = projection(module_id)
    assert view is not None
    assert not any(n['area'] == 'low' for n in view['nodes'] + view['details']['nodes'])


@pytest.mark.parametrize('module_id,owner,node', [
    ('design','prepare','generate'), ('design','decide','inspect'),
    ('design','finalize','handoff'), ('orchestrator','mission','contract'),
    ('orchestrator','plan','route'), ('orchestrator','decide','dispatch'),
    ('specimen','prepare','geometry'), ('specimen','decide','execute'),
    ('vision','observe','task'), ('vision','observe','capture'), ('vision','observe','stop'),
])
def test_api_dispatch_and_internal_processing_render_in_middle(module_id, owner, node):
    _, view = projection(module_id)
    actual = next(n for n in view['details']['nodes'] if n['key'] == f'{owner}::{node}')
    assert actual['area'] == 'middle'


@pytest.mark.parametrize('node', ['deliver','deliver_prepared','deliver_clearance'])
def test_vision_delivery_is_not_misrepresented_as_an_llm_decision(node):
    _, view = projection('vision')
    actual = next(n for n in view['nodes'] if n['key'] == node)
    assert actual['area'] == 'middle'


@pytest.mark.parametrize('module_id', MODULES)
def test_every_code_reference_resolves_without_registering_new_execution(module_id):
    _, view = projection(module_id)
    for node in view['details']['nodes']:
        source = node['source']
        tree = ast.parse((ROOT / source['path']).read_text())
        parts = source['symbol'].split('.')
        for part in parts:
            tree = next(n for n in ast.walk(tree) if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part)


@pytest.mark.parametrize('module_id', ['guardian'])
def test_legacy_checkpoint_projection_renders_internal_decisions_without_adding_steps(module_id):
    from test_planning_design_report_js import _extract_function
    source = (ROOT / 'web/static/runtime_ide.js').read_text()
    functions = '\n'.join(_extract_function(source, n) for n in ('normalizedModulePayload', 'moduleGraphNodeId', 'modulePayloadToGraph'))
    module = yaml.safe_load((ROOT / f'graphs/modules/{module_id}/module.yaml').read_text())
    script = '''const assert=require('node:assert/strict');
const AX4LABControlView=require('./web/static/module_control_view.js');
const activeModuleId='unused',MODULE_TAB_PREFIX='module:';
const snapToGrid=x=>x,defaultModuleNodePosition=r=>({x:r.index*208,y:100});
const inferPortPair=()=>({sourceSide:'right',targetSide:'left'});
''' + functions + '\nconst payload=' + json.dumps(module) + ''';
const original=JSON.stringify(payload),g=modulePayloadToGraph(payload),cv=g.metadata.control_view;
const detail=AX4LABControlView.internalDetails(g.nodes,cv);
assert.ok(g.nodes.some(n=>n.metadata.control_area==='high') || detail.nodes.some(n=>n.area==='high'));
assert.equal(g.nodes.length,payload.module.internal_graph.length);
assert.equal(g.edges.length,g.nodes.length-1);
assert.equal(JSON.stringify(payload),original);
assert.match(AX4LABControlView.backdrop(g.nodes,cv),/LLM/);
for(const d of detail.nodes)assert.ok(g.nodes.some(n=>n.id===d.owner));
if(detail.nodes.length){
  const removed=detail.nodes[0].owner;
  g.nodes=g.nodes.filter(n=>n.id!==removed);
  assert.ok(!AX4LABControlView.internalDetails(g.nodes,cv).nodes.some(n=>n.owner===removed));
}
'''
    subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, check=True)


@pytest.mark.parametrize('owner,node,area', [
    ('task', 'suitability', 'high'),
    ('task', 'terminal', 'high'),
    ('task', 'runtime', 'middle'),
    ('task', 'worker', 'low'),
    ('task', 'guardian', 'guardian'),
    ('task', 'csv', 'knowledge'),
])
def test_equipment_catalog_places_real_source_bound_components(owner, node, area):
    _, view = projection('equipment')
    actual = next(item for item in view['details']['nodes'] if item['key'] == f'{owner}::{node}')
    assert actual['area'] == area


def test_legacy_code_inspector_shows_canonical_guardian_source_and_area():
    from test_planning_design_report_js import _extract_function
    source = (ROOT / 'web/static/runtime_ide.js').read_text()
    markup = _extract_function(source, 'implementationInspectorMarkup')
    module, _ = projection('guardian')
    detail = module['metadata']['control_view']['checkpoint_details']['internal_graph:02_review_recent_failures']
    script = "const assert=require('node:assert/strict');const escapeHtml=x=>String(x);\n" + markup
    script += '\nconst detail=' + json.dumps(detail) + r''';
const html=implementationInspectorMarkup({id:'existing-checkpoint'},detail);
assert.match(html,/LLM policy evidence review/);
assert.match(html,/high/);
assert.match(html,/agents\/core\/guardian\/agent.py/);
assert.match(html,/existing-checkpoint/);
assert.equal(implementationInspectorMarkup({id:'other'},null),'');
'''
    subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, check=True)
