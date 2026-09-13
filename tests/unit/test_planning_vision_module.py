"""Vision uses current state observations and shared document graph layout."""
from pathlib import Path
import subprocess

from test_planning_design_report_js import _extract_function

ROOT = Path(__file__).resolve().parents[2]


def test_projector_preserves_inputs_and_report_fallbacks():
    from copy import deepcopy
    from agents.vision.presentation import project_vision_report
    payload = {'vision_report': {'task': 'payload'}, 'vision_agent_report': {'status': 'payload'}}
    metadata = {'latest_vision_observation': {'vision_report': {'task': 'metadata'}},
                '_projection_state': {'latest_observations': {'vision_report': {'task': 'state'}}}}
    before = deepcopy(metadata)
    assert project_vision_report(metadata, payload)['vision_report']['task'] == 'state'
    assert metadata == before
    metadata['_projection_state']['latest_observations'] = {}
    assert project_vision_report(metadata, payload)['vision_report']['task'] == 'metadata'
    assert project_vision_report({}, payload)['vision_agent_report']['status'] == 'payload'
    assert project_vision_report({}, {})['vision_report'] is None


def test_frontend_observation_precedence_matches_backend_current_state():
    source = (ROOT / 'web/static/planning.js').read_text()
    script = '\n'.join(_extract_function(source, name) for name in ('latestVisionReport', 'latestVisionAgentReport', 'latestVisionSignalPacket'))
    script += '''
const assert = require('node:assert/strict');
const report = {state:{run_metadata:{latest_vision_observation:{vision_report:{id:'old'},vision_agent_report:{id:'old'}}},latest_observations:{vision_report:{id:'current'},vision_agent_report:{id:'current'}}}};
assert.equal(latestVisionReport(report).id,'current');
assert.equal(latestVisionAgentReport(report).id,'current');
report.state.run_metadata.latest_vision_observation.vision_signal = {id:'old'};
report.state.latest_observations.vision_signal = {id:'current'};
assert.equal(latestVisionSignalPacket(report).id,'current');
report.state.run_metadata.vision_report = {id:'explicit'};
assert.equal(latestVisionReport(report).id,'explicit');
'''
    subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
