"""Transactional publication of a small, explicit set of stateless leaf modules.

Device bridge instances and running workflows are not reloadable. At an idle
boundary only the explicitly listed cycle-driver body may be patched in place;
the controller class, state, sessions and all other methods remain untouched.
"""
import importlib
import inspect
from pathlib import Path
import types


MODULES = ("utils.equipment_vision_tasks", "agents.equipment.recovery", "agents.equipment.workflow",
           "utils.utm_specimen_presence", "utils.utm_clear_cycle", "agents.vision.decision", "app.run_recovery")
MODULES += ("utils.utm_observation_roi", "device_bridges.camera_vision.tools")


def stage_cycle_driver(path):
    """Compile only the allowed method, never execute the controller module/class."""
    import ast
    from app.controller import MainController
    current = MainController._run_planning_cycle_series
    tree = ast.parse(Path(path).read_text())
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainController")
    node = next(n for n in owner.body if isinstance(n, ast.AsyncFunctionDef) and n.name == current.__name__)
    if node.decorator_list:
        raise ValueError("Cycle driver decorators changed; restart required")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    namespace = dict(current.__globals__)
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    candidate = namespace[current.__name__]
    if inspect.signature(current) != inspect.signature(candidate) or current.__code__.co_freevars != candidate.__code__.co_freevars:
        raise ValueError("Cycle driver signature changed; restart required")
    return current, candidate


def reload_sources(sources):
    staged = []
    for name, path in sources.items():
        current = importlib.import_module(name)
        replacement = types.ModuleType(name)
        replacement.__file__ = str(path)
        replacement.__package__ = current.__package__
        # Compile and evaluate every candidate before touching live namespaces.
        exec(compile(Path(path).read_text(), str(path), "exec"), replacement.__dict__)
        for key, value in vars(current).items():
            if inspect.isfunction(value) and value.__module__ == name:
                changed = vars(replacement).get(key)
                if (not inspect.isfunction(changed) or inspect.signature(value) != inspect.signature(changed)
                        or value.__code__.co_freevars != changed.__code__.co_freevars):
                    raise ValueError(f"Hot reload signature changed: {name}.{key}; restart required")
        staged.append((current, replacement))
    # No await / yield: server requests cannot see a partially published set.
    for current, replacement in staged:
        values = dict(replacement.__dict__)
        for key, value in values.items():
            if inspect.isfunction(value) and value.__module__ == current.__name__:
                existing = vars(current).get(key)
                if inspect.isfunction(existing) and existing.__module__ == current.__name__:
                    # Keep imported aliases valid. Only closure-compatible leaf
                    # functions are admitted, at an inactive execution boundary.
                    existing.__code__ = value.__code__
                    existing.__defaults__ = value.__defaults__
                    existing.__kwdefaults__ = value.__kwdefaults__
                    existing.__annotations__ = value.__annotations__
                    values[key] = existing
                else:
                    replacement_function = types.FunctionType(value.__code__, current.__dict__,
                        value.__name__, value.__defaults__, value.__closure__)
                    replacement_function.__kwdefaults__ = value.__kwdefaults__
                    replacement_function.__annotations__ = value.__annotations__
                    values[key] = replacement_function
        current.__dict__.update(values)
    return [current.__name__ for current, _ in staged]


def supported_sources():
    return {name: Path(importlib.import_module(name).__file__) for name in MODULES}


def assert_idle(controller):
    from orchestrator.state import Stage
    if controller.snapshot().get("is_running") or controller._planning_request_lock.locked():
        raise ValueError("Hot reload requires an inactive controller")
    if controller._state.stage not in {Stage.IDLE, Stage.ERROR, Stage.COMPLETE}:
        raise ValueError("Paused/in-progress workflows cannot be hot-reloaded")
    if controller._active_safety_sources() or any(getattr(controller._state, k) for k in
            ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
        raise ValueError("Resolve safety controls before hot reload")


async def reload_equipment_support(controller):
    import asyncio
    import hashlib
    import subprocess
    import sys
    from orchestrator.state import Stage
    if controller._state.stage == Stage.GUARDIAN and controller._state.is_paused:
        return await reload_selection_review(controller)
    assert_idle(controller)
    sources = supported_sources()
    root = Path(__file__).resolve().parents[1]
    checked_sources = {**sources, "app.controller:cycle_driver": root / "app/controller.py"}
    digests = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in checked_sources.items()}
    driver, candidate = stage_cycle_driver(checked_sources["app.controller:cycle_driver"])
    checked = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "pytest",
        "tests/unit/test_equipment_workflow_decision.py", "tests/unit/test_equipment_vision_tasks.py",
        "tests/unit/test_safe_hot_reload.py", "tests/unit/test_run_recovery_checkpoint.py",
        "tests/unit/test_utm_clear_presence.py", "tests/unit/test_utm_clear_cycle.py", "tests/unit/test_vision_decision.py",
        "tests/unit/test_camera_tools_utm_runtime.py",
        "tests/unit/test_error_run_resume.py", "-q", "--tb=short"], cwd=root,
        capture_output=True, text=True, timeout=60)
    if checked.returncode:
        raise ValueError("Hot reload validation failed; current code retained")
    assert_idle(controller)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != digests[name] for name, path in checked_sources.items()):
        raise ValueError("Source changed during validation; current code retained")
    loaded = reload_sources(sources)
    driver.__code__ = candidate.__code__
    loaded.append("app.controller:cycle_driver")
    await controller._emit_control_event("runtime.hot_reload", "Validated Equipment support modules reloaded",
        {"modules": loaded, "sha256": digests, "actuation_performed": False})
    return {"ok": True, "modules": loaded, "sha256": digests, "server_restarted": False,
            "actuation_performed": False, "scope": "equipment_support_only"}


async def reload_selection_review(controller):
    """Only a rejected pre-actuation selection; no suspended owner workflow."""
    import asyncio
    import hashlib
    import subprocess
    import sys
    from app.equipment_selection_recovery import selection_recovery_inputs
    from orchestrator.state import Stage
    record, corrected = selection_recovery_inputs(controller)
    source_id = record["execution_id"]
    root = Path(__file__).resolve().parents[1]
    names = ("agents.equipment.decision", "agents.equipment.workflow",
             "utils.manipulation_execution", "utils.manipulation_runtime_view")
    sources = {name: Path(importlib.import_module(name).__file__) for name in names}
    digests = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()}
    checked = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "pytest",
        "tests/unit/test_equipment_selection_recovery.py", "tests/unit/test_equipment_workflow_decision.py",
        "tests/unit/test_manipulation_task_progress.py", "tests/unit/test_manipulation_runtime_view.py",
        "-q", "--tb=short"], cwd=root, capture_output=True, text=True, timeout=60)
    if checked.returncode:
        raise ValueError("Selection recovery tests failed; live code unchanged")
    latest, corrected = selection_recovery_inputs(controller)
    if latest != record or any(hashlib.sha256(path.read_bytes()).hexdigest() != digests[name]
                              for name, path in sources.items()):
        raise ValueError("Selection recovery changed during validation")
    loaded = reload_sources(sources)
    # Publication and staging are atomic within the event loop. Resume is separate.
    controller._state.run_metadata["specimen_result"] = corrected
    controller._state.run_metadata["equipment_selection_retry"] = {"source_execution_id": source_id}
    controller._state.run_metadata["guardian_recovery_wait"]["status"] = "retry_prepared"
    controller._state.stage = Stage.EQUIPMENT
    await controller._emit_control_event("runtime.selection_review_prepared",
        "Never-executed Equipment selection prepared for fresh review; awaiting Resume",
        {"source_execution_id": source_id, "modules": loaded, "sha256": digests, "actuation_performed": False})
    return {"ok": True, "status": "selection_review_prepared", "server_restarted": False,
            "actuation_performed": False, "source_execution_id": source_id}
