"""Optional read-only regression against the preserved paired closed-loop run.

Raw local artifacts are intentionally not checked into Git. This test does not
invoke Agent.run(), a model, a solver, or a device and cannot overwrite the run.
"""
import hashlib
import json
from pathlib import Path

import pytest

from agents.analysis_agent import AnalysisAgent


def test_preserved_completed_cycle_same_stl_and_measured_reprocessing():
    root = Path(__file__).resolve().parents[2]
    run = root / 'runs/run-20260907T043145Z-f6152b'
    loop = run / 'runtime/loops/loop-000001'
    if not loop.exists():
        pytest.skip('Preserved operator-confirmed closed-loop archive is local-only')
    analysis_file = loop / 'analysis_agent/attempt-000001/result.json'
    specimen_file = loop / 'specimen_agent/attempt-000001/result.json'
    analysis = json.loads(analysis_file.read_text())['data']['analysis']
    specimen = json.loads(specimen_file.read_text())['data']['specimen_result']
    stl = Path(specimen['stl_path'])
    csv = Path(analysis['source']['path'])
    paths = [analysis_file, specimen_file, stl, csv]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert stl.resolve() == Path(analysis['cae_result']['request']['stl_path']).resolve()
    assert before[str(stl)] == '49364c80e36091768cc931c3fdd468f1d8dde6652baa9f6c0288315c1b8bec9d'
    assert before[str(csv)] == 'c0305780455d1ba2af0ce734ffce1fa904c5a4e8434bc73fe37ecd27e415e17e'
    agent = AnalysisAgent()
    curve, source = agent._read_curve_file(str(csv))
    assert source['ok'] is True
    assert len(curve) == 2113
    geometry = analysis['specimen_geometry']
    assert geometry['cross_section_area_mm2'] == 900
    assert geometry['gauge_length_mm'] == 30
    metrics = agent._metrics(curve, geometry)
    assert metrics['peak_force_limit_mm'] == 15
    assert metrics['peak_force_N'] == pytest.approx(6385.264)
    assert metrics['energy_density_50pct_MJ_per_m3'] == pytest.approx(1.941513759)
    assert metrics['energy_absorption_50pct_mJ'] == pytest.approx(52420.871477)
    assert metrics['energy_identity_relative_error'] < 1e-8
    assert analysis['cae_result']['solver_mode'] == 'deterministic_quasistatic_equivalent'
    # This verifies data pairing/reprocessing, NOT independent FE accuracy.
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before
