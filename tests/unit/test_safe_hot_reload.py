import sys
import types

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('activecam_boundary', [True, False])
async def test_vision_hotfix_routing_uses_validated_boundary(monkeypatch, activecam_boundary):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app import safe_hot_reload, vision_review_recovery
    from orchestrator.state import Stage
    controller = SimpleNamespace(_state=SimpleNamespace(stage=Stage.COMPLETE,
        agent_status={'vision_agent': SimpleNamespace(success=False)},
        run_metadata={'specimen_result': {'printer_completion_verified': True}}))
    def validate(candidate):
        assert candidate is controller
        if not activecam_boundary:
            raise ValueError('Downstream execution exists; cannot rewind to pickup')
        return {'contract_id': 'active_cam'}
    class CodeOnlyBoundary(Exception):
        pass
    def idle(candidate):
        assert candidate is controller
        raise CodeOnlyBoundary  # Stop before any source publication or mutation.
    retry = AsyncMock(return_value={'ok': True})
    monkeypatch.setattr(vision_review_recovery, 'validate_boundary', validate)
    monkeypatch.setattr(safe_hot_reload, 'reload_vision_review', retry)
    monkeypatch.setattr(safe_hot_reload, 'assert_idle', idle)
    if activecam_boundary:
        assert await safe_hot_reload.reload_equipment_support(controller) == {'ok': True}
        retry.assert_awaited_once_with(controller)
    else:
        with pytest.raises(CodeOnlyBoundary):
            await safe_hot_reload.reload_equipment_support(controller)
        retry.assert_not_awaited()
        assert 'vision_review_retry' not in controller._state.run_metadata


def test_reload_stages_all_modules_before_publishing(tmp_path):
    from app.safe_hot_reload import reload_sources
    module = types.ModuleType("reload_fixture")
    exec("def value(): return 1", module.__dict__)
    prior = module.value
    source = tmp_path / "leaf.py"
    source.write_text("def value(): return 2\n")
    sys.modules[module.__name__] = module
    try:
        reload_sources({module.__name__: source})
        assert module.value() == 2
        assert prior() == 2  # Existing imports must not retain the old function.
        # A compile failure must leave the running implementation unchanged.
        source.write_text("def value(:\n")
        with pytest.raises(SyntaxError):
            reload_sources({module.__name__: source})
        assert module.value() == 2
    finally:
        sys.modules.pop(module.__name__, None)


def test_reload_rejects_changed_callable_contract(tmp_path):
    from app.safe_hot_reload import reload_sources
    module = types.ModuleType("reload_fixture")
    exec("def value(): return 1", module.__dict__)
    source = tmp_path / "leaf.py"
    source.write_text("def value(required): return required\n")
    sys.modules[module.__name__] = module
    try:
        with pytest.raises(ValueError, match="signature"):
            reload_sources({module.__name__: source})
        assert module.value() == 1
    finally:
        sys.modules.pop(module.__name__, None)


def test_printer_wait_patch_requires_terminal_failure_and_no_active_work():
    from app.safe_hot_reload import assert_printer_wait_inactive
    from types import SimpleNamespace
    controller = SimpleNamespace(
        _planning_messages=[{"ok":False,"content":"printer completion wait timed out: active"}],
        snapshot=lambda: {"is_running":False}, _planning_request_lock=SimpleNamespace(locked=lambda:False),
        _active_safety_sources=lambda: [],
        _state=SimpleNamespace(stop_requested=False,safe_stop_requested=False,emergency_stop_requested=False))
    assert_printer_wait_inactive(controller)
    controller._run_task = SimpleNamespace(done=lambda:False)
    with pytest.raises(ValueError, match="running"):
        assert_printer_wait_inactive(controller)
    controller._run_task = None
    controller._state.emergency_stop_requested = True
    with pytest.raises(ValueError, match="safety"):
        assert_printer_wait_inactive(controller)
    controller._state.emergency_stop_requested = False
    controller._planning_messages.append({"ok":True,"content":"new work"})
    with pytest.raises(ValueError, match="terminal"):
        assert_printer_wait_inactive(controller)


def test_printer_timing_staging_compiles_only_allowed_method(tmp_path):
    from app.safe_hot_reload import stage_printer_wait_timing
    source = tmp_path / 'controller.py'
    source.write_text('raise RuntimeError("must not execute")\nclass MainController:\n'
        '    @classmethod\n'
        '    def _printer_completion_wait_timing(cls, experiment_spec: dict[str, Any], specimen_payload: dict[str, Any]) -> tuple[float, float]:\n'
        '        return 123.0, 2.0\n')
    current, candidate = stage_printer_wait_timing(source)
    assert candidate(None, {}, {}) == (123.0, 2.0)
    assert current is not candidate


@pytest.mark.asyncio
async def test_cycle_driver_reload_preserves_controller_instance_and_rejects_signature_changes(tmp_path):
    from app import safe_hot_reload
    from app.bootstrap import load_runtime
    controller = load_runtime()
    run_id = controller._state.run_id
    source = tmp_path / "controller.py"
    source.write_text('raise RuntimeError("module body must not execute")\n'
        'class MainController:\n'
        '    async def _run_planning_cycle_series(self, *, first_spec: dict[str, Any], '
        'design_constraints: dict[str, Any], start_cycle: int = 1, resume_tail_stage: Stage | None = None) -> dict[str, Any]:\n'
        '        return {"run_id": self._state.run_id, "decision": "paused_after_design"}\n')
    current, candidate = safe_hot_reload.stage_cycle_driver(source)
    original = current.__code__
    try:
        current.__code__ = candidate.__code__
        result = await controller._run_planning_cycle_series(first_spec={}, design_constraints={})
        assert result == {"run_id": run_id, "decision": "paused_after_design"}
    finally:
        current.__code__ = original
    source.write_text('class MainController:\n    async def _run_planning_cycle_series(self, required): pass\n')
    with pytest.raises(ValueError, match="signature"):
        safe_hot_reload.stage_cycle_driver(source)
