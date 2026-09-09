"""Check the actual solver subprocess environment without invoking a real solver."""
import json
import sys
import pytest

from device_bridges.calculix_bridge import CalculiXBridge, CalculiXBridgeConfig


@pytest.mark.parametrize(('requested', 'expected'), [(0, 1), (-5, 1), (999, 4), ('invalid', 1), (2, 2)])
def test_equation_solver_thread_limit_is_bounded(tmp_path, requested, expected):
    bridge = CalculiXBridge(CalculiXBridgeConfig(artifact_dir=tmp_path))
    limits = bridge._computation_limits({
        'computation_limits': {'threads': 4, 'equation_solver_threads': requested},
    })
    assert limits['equation_solver_threads'] == expected


def test_equation_solver_thread_limit_is_independent_and_request_scoped(tmp_path, monkeypatch):
    executable = tmp_path / 'environment_solver'
    executable.write_text(
        f'#!{sys.executable}\nimport json, os\n'
        'print(json.dumps({k: os.environ.get(k) for k in '
        '["OMP_NUM_THREADS", "CCX_NPROC_EQUATION_SOLVER"]}))\n'
    )
    executable.chmod(0o755)
    inp = tmp_path / 'input.inp'
    inp.write_text('*HEADING\nenvironment probe\n')
    monkeypatch.setenv('CCX_NPROC_EQUATION_SOLVER', '7')
    bridge = CalculiXBridge(CalculiXBridgeConfig(
        executable_path=str(executable), artifact_dir=tmp_path / 'artifacts',
    ))
    payload = {'inp_path': str(inp), 'runtime_solver_enabled': True,
               'computation_limits': {'threads': 4, 'equation_solver_threads': 1}}
    result = bridge.solve(payload)
    assert result['ok'] is True
    assert json.loads(result['stdout_tail']) == {
        'OMP_NUM_THREADS': '4', 'CCX_NPROC_EQUATION_SOLVER': '1',
    }
    assert result['computation_limits']['equation_solver_threads'] == 1
    # The next request still inherits the operator environment, not the last request.
    result = bridge.solve({**payload, 'computation_limits': {'threads': 2}})
    assert json.loads(result['stdout_tail']) == {
        'OMP_NUM_THREADS': '2', 'CCX_NPROC_EQUATION_SOLVER': '7',
    }
