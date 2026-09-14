import sys
import types

import pytest


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
