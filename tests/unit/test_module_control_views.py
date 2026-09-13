"""Check real module metadata against editable graph identities and SVG output."""
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest
import yaml

from test_planning_design_report_js import _extract_function

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('module_id', ['design', 'orchestrator'])
def test_control_layout_preserves_executable_nodes_edges_and_saved_positions(module_id):
    module = yaml.safe_load((ROOT / f'graphs/modules/{module_id}/module.yaml').read_text())['module']
    original = json.dumps(module)
    script = 'const v=require("./web/static/module_control_view.js");const m=JSON.parse(process.argv[1]);process.stdout.write(JSON.stringify(v.layout(m)));'
    layout = json.loads(subprocess.run(['node', '-e', script, original], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
    expected = [('execution_graph', step['id']) for step in module['execution_graph']['nodes']]
    assert [(node['phase'], node['step']['id']) for node in layout['nodes']] == expected
    assert all(node['step'] == module['execution_graph']['nodes'][node['index']] for node in layout['nodes'])
    assert layout['edges'] == module['execution_graph']['edges']
    assert {group['id'] for group in layout['groups']} == {'high', 'middle', 'low', 'guardian', 'knowledge'}
    for node in layout['nodes']:
        for other in layout['nodes']:
            if node is other:
                continue
            a,b=node['position'],other['position']
            assert abs(a['x']-b['x']) >= 184 or abs(a['y']-b['y']) >= 76


@pytest.mark.parametrize('module_id', ['design', 'orchestrator'])
def test_document_svg_is_current_renderer_output(module_id):
    from scripts.render_module_control_views import render
    generated = render(module_id, ROOT)
    assert ET.fromstring(generated).tag.endswith('svg')
    assert (ROOT / f'docs/agents/assets/figures/{module_id}_control_areas.svg').read_text() == generated


def test_real_ide_graph_projection_preserves_transitions_and_manual_position():
    source = (ROOT / 'web/static/runtime_ide.js').read_text()
    functions = '\n'.join(_extract_function(source, name) for name in ('normalizedModulePayload', 'moduleGraphNodeId', 'modulePayloadToGraph'))
    module = yaml.safe_load((ROOT / 'graphs/modules/design/module.yaml').read_text())
    module['module']['execution_graph']['nodes'][0]['position'] = {'x': 2000, 'y': 400}
    script = '''const assert=require('node:assert/strict');
let AX4LABControlView=require('./web/static/module_control_view.js');
const AX4LABExecutionEditor=require('./web/static/module_execution_editor.js');
const moduleExecutionContracts=new Map();
const activeModuleId='design',MODULE_TAB_PREFIX='module:';
const snapToGrid=x=>x, defaultModuleNodePosition=r=>({x:r.index*208,y:100});
const inferPortPair=()=>({sourceSide:'right',targetSide:'left'});
''' + functions + '\nconst payload=' + json.dumps(module) + ''';
const grouped=modulePayloadToGraph(payload);
assert.equal(grouped.nodes[0].position.x,2000);
assert.equal(grouped.nodes[0].metadata.control_area,'middle');
assert.ok(grouped.metadata.control_view);
assert.deepEqual(grouped.nodes.map(n=>n.id),['prepare','decide','finalize','owner_review']);
assert.deepEqual(grouped.transitions,{});
payload.module.execution_graph.nodes[0].label='Edited operation';
payload.module.execution_graph.nodes.push({id:'added',handler:'design.prepare',label:'Added operation',area:'middle'});
const edited=modulePayloadToGraph(payload);
assert.equal(edited.nodes.length,grouped.nodes.length+1);
assert.equal(edited.nodes[0].label,'Edited operation');
assert.deepEqual(edited.edges,grouped.edges);
assert.deepEqual(AX4LABExecutionEditor.serialize(edited,payload).module.execution_graph.edges,payload.module.execution_graph.edges);
'''
    subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, check=True)
