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
MODULES += ("app.equipment_tail_recovery",)


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
    # Bounded code-only migration for servers started before final BO reporting.
    from app.bo_final_hotfix import needs_patch, apply_hotfix
    if needs_patch():
        return await apply_hotfix(controller)
    # One-time, observation-only migration for servers already running v3.
    # Never reload workflow/device classes or rewind an active experiment.
    from utils import lerobot_joint_telemetry as telemetry
    if (telemetry.GRASP_CONTACT_GAP_THRESHOLD == 2.0
            and telemetry.GRASP_OUTCOME_RULE_VERSION == "absolute_contact_gap_v3"):
        return await reload_grasp_display_threshold(controller)
    if (controller._state.run_metadata.get("vision_agent_payload") or {}).get("failure_code") in {
            "VISION_ROS_STOP_UNCONFIRMED", "VISION_ROS_RESTART_UNCONFIRMED"}:
        return await reload_vision_ros_support(controller)
    if (controller._state.stage in {Stage.COMPLETE, Stage.ERROR}
            and getattr(controller._state.agent_status.get('vision_agent'), 'success', None) is False
            and (controller._state.run_metadata.get('specimen_result') or {}).get('printer_completion_verified')):
        from app.vision_review_recovery import validate_boundary
        try:
            validate_boundary(controller)
        except (ValueError, OSError, KeyError):
            # Clearance/placement failures are not pre-pickup ActiveCam retries.
            # Fall through to code-only reload with the normal idle/safety gates;
            # never prepare a rewind or change the failed run's recovery state.
            pass
        else:
            return await reload_vision_review(controller)
    if printer_wait_failed(controller):
        return await reload_printer_wait_support(controller)
    if controller._state.stage == Stage.GUARDIAN and controller._state.is_paused:
        from app.equipment_entry_resume import matches, hot_reload
        if matches(controller._state):
            return await hot_reload(controller)
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
        "tests/unit/test_error_run_resume.py", "tests/unit/test_equipment_tail_recovery.py", "-q", "--tb=short"], cwd=root,
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


async def reload_grasp_display_threshold(controller):
    """Publish only the approved display constants; retain all execution state."""
    import ast
    import asyncio
    from utils import lerobot_joint_telemetry as telemetry
    from utils.monitor_process import existing_monitor_process

    expected = {"GRASP_CONTACT_GAP_THRESHOLD": 1.2,
                "GRASP_OUTCOME_RULE_VERSION": "absolute_contact_gap_v4"}
    tree = ast.parse(Path(telemetry.__file__).read_text())
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in expected:
                    values[target.id] = ast.literal_eval(node.value)
    if values != expected:
        raise ValueError("Grasp display hotfix source does not match approved constants")
    # Existing imported functions share this namespace. Bump the artifact rule
    # so cached v3 failures are reclassified from raw telemetry, not reused.
    telemetry.__dict__.update(values)
    worker = existing_monitor_process("robot")
    if worker is not None:
        await asyncio.to_thread(worker.close)
    result = {"ok": True, "scope": "grasp_display_only",
              "contact_gap_threshold": telemetry.GRASP_CONTACT_GAP_THRESHOLD,
              "rule_version": telemetry.GRASP_OUTCOME_RULE_VERSION,
              "server_restarted": False, "actuation_performed": False}
    await controller._emit_control_event("runtime.hot_reload",
        "Grasp display threshold updated; final vision verification unchanged", result)
    return result


def assert_vision_ros_patch_boundary(controller):
    """Code-only repair: retain the stopped run, safety controls and live bridges."""
    from orchestrator.state import Stage
    state = controller._state
    if (controller.snapshot().get("is_running") or controller._planning_request_lock.locked()
            or state.stage not in {Stage.COMPLETE, Stage.ERROR}):
        raise ValueError("ROS hotfix requires an inactive terminal workflow")
    for name in ("_run_task", "_planning_handoff_task"):
        task = getattr(controller, name, None)
        if task is not None and not task.done():
            raise ValueError("ROS hotfix cannot patch an active workflow")
    if (state.run_metadata.get("vision_agent_payload") or {}).get("failure_code") not in {
            "VISION_ROS_STOP_UNCONFIRMED", "VISION_ROS_RESTART_UNCONFIRMED"}:
        raise ValueError("No failed ROS reload to repair")


async def reload_vision_ros_support(controller):
    """Patch only three leaf function bodies; never recreate the ROS manager."""
    import ast
    import asyncio
    import hashlib
    import subprocess
    import sys
    assert_vision_ros_patch_boundary(controller)
    root = Path(__file__).resolve().parents[1]
    targets = {
        "device_bridges.camera_vision.tools": ("_reload_vision_cycle", "_restart_vision_runtime", "_reload_for_capture"),
        "agents.vision.decision": ("select_vision_tool",),
    }
    staged, digests = [], {}
    for name, functions in targets.items():
        module = importlib.import_module(name)
        path = Path(module.__file__)
        source = path.read_bytes()
        digests[str(path)] = hashlib.sha256(source).hexdigest()
        tree = ast.parse(source)
        for function in functions:
            current = getattr(module, function)
            node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function)
            if node.decorator_list:
                raise ValueError("ROS leaf decorators changed")
            candidate_tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
            namespace = dict(module.__dict__)
            exec(compile(ast.fix_missing_locations(candidate_tree), str(path), "exec"), namespace)
            candidate = namespace[function]
            if inspect.signature(current) != inspect.signature(candidate) or current.__code__.co_freevars != candidate.__code__.co_freevars:
                raise ValueError("ROS leaf signature changed")
            staged.append((current, candidate))
    # Only the cycle-admission method is published, not other controller edits.
    from app.controller import MainController
    path = root / "app/controller.py"
    source = path.read_bytes()
    digests[str(path)] = hashlib.sha256(source).hexdigest()
    owner = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "MainController")
    current = MainController._run_planning_design_stage
    node = next(n for n in owner.body if isinstance(n, ast.AsyncFunctionDef) and n.name == current.__name__)
    namespace = dict(current.__globals__)
    tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), str(path), "exec"), namespace)
    candidate = namespace[current.__name__]
    if inspect.signature(current) != inspect.signature(candidate) or current.__code__.co_freevars != candidate.__code__.co_freevars:
        raise ValueError("Cycle admission signature changed")
    staged.append((current, candidate))
    helper = root / "utils/vision_cycle_runtime.py"
    compile(helper.read_bytes(), str(helper), "exec")
    digests[str(helper)] = hashlib.sha256(helper.read_bytes()).hexdigest()
    staged.append(stage_resume(root / "app/controller.py"))
    helper = root / "app/vision_ros_recovery.py"
    compile(helper.read_bytes(), str(helper), "exec")
    digests[str(helper)] = hashlib.sha256(helper.read_bytes()).hexdigest()
    checked = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "pytest",
        "tests/unit/test_vision_ros_cycle_reload.py", "tests/unit/test_camera_tools_utm_runtime.py",
        "tests/unit/test_safe_hot_reload.py", "tests/unit/test_vision_ros_recovery.py", "-q", "--tb=short"], cwd=root,
        capture_output=True, text=True, timeout=60)
    if checked.returncode:
        raise ValueError("ROS hotfix tests failed; live code retained")
    assert_vision_ros_patch_boundary(controller)
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest for path, digest in digests.items()):
        raise ValueError("ROS source changed during validation")
    from device_bridges.camera_vision import tools
    if not tools._VISION_RELOAD_LOCK.acquire(blocking=False):
        raise ValueError("ROS reload is in progress; retry after it finishes")
    try:
        for current, candidate in staged:
            current.__code__ = candidate.__code__
    finally:
        tools._VISION_RELOAD_LOCK.release()
    result = {"ok": True, "scope": "vision_ros_reload_only", "sha256": digests,
              "server_restarted": False, "actuation_performed": False,
              "run_resumed": False, "successful_cycle_cache_preserved": True}
    from app.vision_ros_recovery import validate
    try:
        boundary = validate(controller)
    except ValueError as exc:
        result["recovery_blocked"] = str(exc)
    else:
        controller._state.run_metadata["vision_ros_retry"] = {**boundary, "status": "ready"}
        result["recovery_status"] = "ready"
    await controller._emit_control_event("runtime.vision_ros_hotfix", "ROS reload leaf functions patched; run and safety state retained", result)
    return result


def stage_resume(path):
    """Compile only Resume; no controller initialization or other method changes."""
    import ast
    from app.controller import MainController
    current = MainController.resume
    tree = ast.parse(Path(path).read_text())
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MainController')
    node = next(n for n in owner.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'resume')
    if node.decorator_list:
        raise ValueError('Resume decorators changed')
    namespace = dict(current.__globals__)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    candidate = namespace['resume']
    if inspect.signature(current) != inspect.signature(candidate) or current.__code__.co_freevars != candidate.__code__.co_freevars:
        raise ValueError('Resume signature changed')
    return current, candidate


async def reload_vision_review(controller):
    import asyncio
    import hashlib
    import subprocess
    import sys
    from app.vision_review_recovery import validate_boundary
    boundary = validate_boundary(controller)
    root = Path(__file__).resolve().parents[1]
    names = ('agents.core.knowledge.context', 'agents.vision.decision', 'app.vision_review_recovery')
    sources = {name: Path(importlib.import_module(name).__file__) for name in names}
    checked_sources = {**sources, 'controller_resume': root / 'app/controller.py'}
    digests = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in checked_sources.items()}
    current, candidate = stage_resume(root / 'app/controller.py')
    checked = await asyncio.to_thread(subprocess.run, [sys.executable, '-m', 'pytest',
        'tests/unit/test_vision_decision.py', 'tests/unit/test_vision_review_recovery.py',
        'tests/unit/test_safe_hot_reload.py', '-q', '--tb=short'], cwd=root,
        capture_output=True, text=True, timeout=60)
    if checked.returncode:
        raise ValueError('Vision hotfix validation failed; live code retained')
    if validate_boundary(controller) != boundary or any(hashlib.sha256(path.read_bytes()).hexdigest() != digests[name]
            for name, path in checked_sources.items()):
        raise ValueError('Vision recovery scope or source changed during validation')
    loaded = reload_sources(sources)
    current.__code__ = candidate.__code__
    controller._state.run_metadata['vision_review_retry'] = {**boundary, 'status': 'ready'}
    controller._state.is_paused = True
    await controller._emit_control_event('runtime.vision_review_hotfix',
        'Vision review hotfixed; fresh capture prepared for operator Resume',
        {'modules': loaded, 'sha256': digests, 'actuation_performed': False})
    return {'ok': True, 'modules': loaded, 'sha256': digests, 'status': 'vision_retry_ready',
            'server_restarted': False, 'actuation_performed': False}


def printer_wait_failed(controller):
    """Only the most recent failed handoff may admit this narrow hotfix."""
    messages = getattr(controller, "_planning_messages", [])
    return bool(messages and messages[-1].get("ok") is False and
                "printer completion wait timed out:" in str(messages[-1].get("content", "")))


def assert_printer_wait_inactive(controller):
    if not printer_wait_failed(controller):
        raise ValueError("No terminal printer-wait timeout to patch")
    if controller.snapshot().get("is_running") or controller._planning_request_lock.locked():
        raise ValueError("Printer wait hotfix requires an inactive workflow")
    for name in ("_run_task", "_planning_handoff_task"):
        task = getattr(controller, name, None)
        if task is not None and not task.done():
            raise ValueError("Cannot patch a suspended/running workflow")
    if controller._active_safety_sources() or any(getattr(controller._state, key) for key in
            ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
        raise ValueError("Resolve safety controls before hot reload")


def stage_printer_wait_timing(path):
    """Compile just the pure timeout calculator, retaining the controller instance."""
    import ast
    from app.controller import MainController
    name = "_printer_completion_wait_timing"
    current = MainController.__dict__[name].__func__
    tree = ast.parse(Path(path).read_text())
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainController")
    node = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == name)
    if len(node.decorator_list) != 1 or not isinstance(node.decorator_list[0], ast.Name) or node.decorator_list[0].id != "classmethod":
        raise ValueError("Printer timing contract changed; restart required")
    node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    namespace = dict(current.__globals__)
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    candidate = namespace[name]
    if inspect.signature(current) != inspect.signature(candidate) or current.__code__.co_freevars != candidate.__code__.co_freevars:
        raise ValueError("Printer timing signature changed; restart required")
    return current, candidate


async def reload_printer_wait_support(controller):
    """No restart, device action, state change, resume, or printer re-submission."""
    import asyncio
    import hashlib
    import subprocess
    import sys
    assert_printer_wait_inactive(controller)
    root = Path(__file__).resolve().parents[1]
    paths = {"app.controller:printer_wait_timing": root / "app/controller.py",
             "utils.printer_wait_timing": root / "utils/printer_wait_timing.py"}
    digests = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    current, candidate = stage_printer_wait_timing(paths["app.controller:printer_wait_timing"])
    checked = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "pytest",
        "tests/unit/test_printer_wait_timing.py", "tests/unit/test_safe_hot_reload.py",
        "-q", "--tb=short"], cwd=root, capture_output=True, text=True, timeout=60)
    if checked.returncode:
        raise ValueError("Printer hotfix validation failed; live code retained")
    assert_printer_wait_inactive(controller)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != digests[name] for name, path in paths.items()):
        raise ValueError("Source changed during validation; live code retained")
    reload_sources({"utils.printer_wait_timing": paths["utils.printer_wait_timing"]})
    current.__code__ = candidate.__code__
    await controller._emit_control_event("runtime.hot_reload", "Slicer-based printer timeout calculator hotfixed; no device action",
        {"modules": list(paths), "sha256": digests, "actuation_performed": False})
    return {"ok": True, "scope": "printer_wait_timing_only", "server_restarted": False,
            "actuation_performed": False, "workflow_resumed": False, "sha256": digests}


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
