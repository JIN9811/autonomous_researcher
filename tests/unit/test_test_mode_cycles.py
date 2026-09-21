"""Cycle budget persistence and request snapshots, without hardware execution."""
from copy import deepcopy
import json

import pytest

from app.bootstrap import load_runtime
from orchestrator.runtime_defaults import TEST_MODE_LOOP_CYCLES
from utils.test_mode_execution_profiles import TestModeExecutionProfileStore as Store, _document_hash

pytestmark = pytest.mark.usefixtures('handoff_no_external')


@pytest.fixture(autouse=True)
def isolated_bo_settings(tmp_path, monkeypatch):
    monkeypatch.setattr('app.test_bo_settings.WORKSPACE_SETTINGS_PATH', tmp_path / 'bo.json')


def test_default_cycle_count_is_fifteen(tmp_path):
    assert TEST_MODE_LOOP_CYCLES == 15
    assert Store(tmp_path / 'profiles.json').snapshot()['total_cycles'] == 15


def test_cycle_setting_roundtrip_and_old_profile_migration(tmp_path):
    path = tmp_path / 'profiles.json'
    store = Store(path)
    old = store.snapshot()
    old.pop('total_cycles', None)
    old['revision'] = 4
    old['profiles']['installed_printer']['agents']['manipulation']['device_mode'] = 'virtual'
    old['sha256'] = _document_hash(old)
    path.write_text(json.dumps(old))
    loaded = store.snapshot()
    assert loaded['revision'] == 4
    assert not loaded.get('warnings')
    assert loaded['profiles'] == old['profiles']
    assert loaded['total_cycles'] == TEST_MODE_LOOP_CYCLES
    saved = store.save_profile('virtual_bridge', loaded['profiles']['virtual_bridge'], expected_revision=4, total_cycles=7)
    assert Store(path).snapshot() == saved
    assert saved['total_cycles'] == 7
    assert store.resolve('installed_printer')['total_cycles'] == 7
    unchanged = store.save_profile('virtual_bridge', loaded['profiles']['virtual_bridge'], expected_revision=5)
    assert unchanged['total_cycles'] == 7


@pytest.mark.parametrize('value', [0, -1, 2.5, True, '3'])
def test_invalid_counts_do_not_write(tmp_path, value):
    store = Store(tmp_path / 'profiles.json')
    profile = store.snapshot()['profiles']['virtual_bridge']
    with pytest.raises(ValueError):
        store.save_profile('virtual_bridge', profile, expected_revision=0, total_cycles=value)
    assert not store.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['virtual_bridge', 'installed_printer', 'physical_print'])
async def test_test_request_pins_cycles_and_new_request_reads_saved_value(tmp_path, monkeypatch, path):
    c = load_runtime()
    c._bind_planning_session(None)
    c._test_mode_execution_profiles_path = tmp_path / 'profiles.json'
    store = Store(c._test_mode_execution_profiles_path)
    profile = store.snapshot()['profiles']['virtual_bridge']
    store.save_profile('virtual_bridge', profile, expected_revision=0, total_cycles=7)
    captured = {}
    monkeypatch.setattr(c._test_scenario, 'start', lambda **kw: captured.update(kw) or True)
    await c._run_test_mode_planning(goal=None, constraints={'printer_test_path': path}, operator_message='테스트 모드')
    constraints = deepcopy(captured['constraints'])
    assert c._bind_planning_cycle_contract(constraints) == 7
    constraints = c._publish_orchestrator_design_contract(constraints, cycle_index=1, total_cycles=7)
    built = c._build_planning_spec(base_spec={}, constraints=constraints)
    assert c._planning_cycle_limit(built) == 7
    c._store_planning_resume_context(goal='SEA', current_spec=built, design_constraints=constraints,
        cycle_index=2, total_cycles=7, phase='specimen')
    store.save_profile('virtual_bridge', profile, expected_revision=1, total_cycles=12)
    assert c._planning_cycle_limit(built) == 7
    assert c._state.run_metadata['planning_cycle_contract']['total_cycles'] == 7
    assert c._state.run_metadata['safety_budget']['max_loop_count'] == 7
    assert c._planning_cycle_limit({'material': 'PLA'}) == 1
    await c._run_test_mode_planning(goal=None, constraints={}, operator_message='테스트 모드')
    assert c._planning_cycle_limit(captured['constraints']) == 12


def test_restore_one_keeps_common_cycles_restore_all_resets(tmp_path):
    store = Store(tmp_path / 'profiles.json')
    profile = store.snapshot()['profiles']['virtual_bridge']
    store.save_profile('virtual_bridge', profile, expected_revision=0, total_cycles=3)
    assert store.reset('virtual_bridge', expected_revision=1)['total_cycles'] == 3
    assert store.reset(None, expected_revision=2)['total_cycles'] == TEST_MODE_LOOP_CYCLES


@pytest.mark.asyncio
async def test_cycle_runner_uses_original_bound_budget(monkeypatch):
    c = load_runtime()
    spec = {'test_mode_autofill': True, 'test_total_cycles': 3}
    c._bind_planning_cycle_contract(spec)
    seen = []
    async def design(**kw):
        seen.append(('design', kw['cycle_index'], kw['total_cycles']))
        return dict(spec)
    async def specimen(*args, **kw):
        return {'pending': False}
    async def tail(*args, **kw):
        seen.append(('tail', kw['cycle_index'], kw['total_cycles']))
        return {'ok': True, 'decision': 'continue'}
    monkeypatch.setattr(c, '_run_planning_design_stage', design)
    monkeypatch.setattr(c, '_run_planning_specimen_stage', specimen)
    monkeypatch.setattr(c, '_run_planning_loop_tail', tail)
    result = await c._run_planning_cycle_series(first_spec={**spec, 'test_total_cycles': 12},
        design_constraints=spec, start_cycle=2)
    assert result['ok']
    assert seen == [('tail', 2, 3), ('design', 3, 3), ('tail', 3, 3)]


@pytest.mark.asyncio
@pytest.mark.parametrize('has_spec', [True, False])
async def test_legacy_resume_preserves_saved_budget(monkeypatch, has_spec):
    c = load_runtime()
    captured = {}
    async def resumed(**kw):
        captured.update(kw)
        return {'ok': True}
    async def message(*args, **kw):
        pass
    monkeypatch.setattr(c, '_run_planning_cycle_series', resumed)
    monkeypatch.setattr(c, '_handoff_planning_to_design', resumed)
    monkeypatch.setattr(c, '_append_planning_message', message)
    spec = {'test_mode_autofill': True}
    result = await c._resume_planning_handoff_from_context({
        'current_spec': spec if has_spec else {}, 'design_constraints': spec,
        'cycle_index': 2, 'total_cycles': 5, 'interrupted_stage': 'design'})
    assert result['ok']
    assert c._state.run_metadata['planning_cycle_contract']['total_cycles'] == 5
    restored = captured['first_spec'] if has_spec else captured['constraints']
    assert restored['test_total_cycles'] == 5


@pytest.mark.asyncio
async def test_initial_design_capture_keeps_bound_cycles(monkeypatch):
    c = load_runtime()
    c._bind_planning_cycle_contract({'test_mode_autofill': True, 'test_total_cycles': 7})
    c._state.current_experiment_spec = {
        'geometry_type': 'gyroid',
        'constraints': {'test_mode_autofill': True, 'test_total_cycles': 7}}
    monkeypatch.setattr(c, '_planning_handoff_active', lambda: True)
    context = c._capture_planning_resume_context(reason='test')
    assert context['total_cycles'] == 7
    seen = {}
    async def series(**kw):
        seen.update(kw)
        return {'ok': True}
    async def message(*args, **kw):
        pass
    monkeypatch.setattr(c, '_run_planning_cycle_series', series)
    monkeypatch.setattr(c, '_append_planning_message', message)
    await c._resume_planning_handoff_from_context(context)
    assert c._planning_cycle_limit(seen['first_spec']) == 7
    assert c._state.run_metadata['planning_cycle_contract']['total_cycles'] == 7
