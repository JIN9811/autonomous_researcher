import zipfile

import pytest

from agents.specimen.agent import SpecimenMakingAgent
from tests.unit.test_analysis_agent import _state
from tests.unit.test_specimen_agent import _valid_spec
from utils.printer_wait_timing import slicer_duration_evidence


def test_selected_plate_duration(tmp_path):
    path = tmp_path / 'slice.3mf'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('Metadata/slice_info.config', '''<config>
          <plate><metadata key="index" value="1"/><metadata key="prediction" value="600"/></plate>
          <plate><metadata key="index" value="2"/><metadata key="prediction" value="4200"/></plate>
        </config>''')
    payload = {'tool_result': {'slicer_result': {'sliced_artifact_path': str(path), 'plate_index': 2}}}
    assert slicer_duration_evidence(payload)['duration_min'] == 70
    payload['tool_result']['slicer_result']['plate_index'] = 3
    assert slicer_duration_evidence(payload)['source'] == 'unavailable'


@pytest.mark.parametrize('value', [None, True, 0, -1, float('nan'), float('inf'), 'invalid'])
def test_no_heuristic_duration_fallback(value):
    evidence = slicer_duration_evidence({'expected_print_time_min': 999,
                                        'slicer_result': {'estimated_print_time_sec': value}})
    assert evidence['duration_min'] is None
    assert evidence['source'] == 'unavailable'


@pytest.mark.parametrize('slicer,minutes', [
    ({'ok': True, 'estimated_print_time_sec': 4200}, 70),
    ({'ok': False, 'estimated_print_time_sec': 4200}, None),
    ({}, None),
])
def test_report_time_comes_only_from_slicer(slicer, minutes):
    state, agent = _state(), SpecimenMakingAgent()
    spec = {**_valid_spec(), 'expected_print_time_min': 999}
    report = agent._build_fabrication_report(
        state=state, spec=spec, candidate='candidate', specimen_id='specimen',
        geometry_result={'ok': True}, mesh_result={'ok': True, 'mesh_status': 'pass'},
        manufacturability_result={'ok': True, 'expected_print_time_min': 888},
        handoff_result={}, experiment_response={},
        printer_response={'slicer_result': slicer, 'slicer_settings': {'expected_print_time_min': 777}},
        printer_payload={}, protocol_note='', live_gui_test_spec=False,
        printer_test_path='physical_print', top_cap_enabled=False, bottom_cap_enabled=False, geometry_payload={},
    )
    assert report['process_plan']['estimated_print_time_min'] == minutes
    screen = agent._specimen_agent_report_snapshot(state=state, spec=spec, candidate='candidate',
        specimen_id='specimen', fabrication_report=report, handoff_packet={})
    time = screen['estimated_print_time']
    assert time['estimated_print_time_min'] == minutes
    assert time['bars'] == ([] if minutes is None else [{'label': 'print (slicer)', 'value': minutes, 'unit': 'min'}])
    report['process_plan'].pop('duration_evidence')
    screen = agent._specimen_agent_report_snapshot(state=state, spec=spec, candidate='candidate',
        specimen_id='specimen', fabrication_report=report, handoff_packet={})
    assert screen['estimated_print_time']['estimated_print_time_min'] is None
