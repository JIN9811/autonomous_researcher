"""One-time code-only BO final-report migration, safe while another owner runs."""
from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
from pathlib import Path
import subprocess
import sys


def needs_patch():
    from agents.bo.agent import BOAgent
    return "finalize_bo" not in BOAgent._run_task.__code__.co_names


def targets():
    from agents.bo.agent import BOAgent
    from learning.botorch_backend import propose_next
    from app.controller import MainController
    return [BOAgent._run_task, propose_next, MainController._format_planning_bo_message]


def assert_boundary(controller):
    from orchestrator.state import Stage
    if controller._state.stage == Stage.BO:
        raise ValueError("Cannot patch while BO owns the current stage")
    codes = {f.__code__ for f in targets()}
    # BO may also run standalone or in a numerical background thread.
    for frame in sys._current_frames().values():
        while frame:
            if frame.f_code in codes:
                raise ValueError("Cannot patch an executing BO function")
            frame = frame.f_back
    try:
        tasks = asyncio.all_tasks()
    except RuntimeError:
        tasks = []
    for task in tasks:
        awaited = task.get_coro()
        while awaited is not None:
            frame = getattr(awaited, "cr_frame", None) or getattr(awaited, "gi_frame", None)
            if frame is not None and frame.f_code in codes:
                raise ValueError("Cannot patch an awaiting BO function")
            awaited = getattr(awaited, "cr_await", None) or getattr(awaited, "gi_yieldfrom", None)


def stage_function(current, path):
    tree = ast.parse(Path(path).read_text())
    owner = current.__qualname__.split(".")[0]
    nodes = next((n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner), tree.body)
    node = next(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == current.__name__)
    if node.decorator_list:
        raise ValueError("Decorated BO hotfix target requires restart")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    namespace = dict(current.__globals__)
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    candidate = namespace[current.__name__]
    old, new = inspect.signature(current), inspect.signature(candidate)
    new_without_flag = new.replace(parameters=[p for p in new.parameters.values() if p.name != "report_only"])
    if (old != new and not (current.__name__ == "propose_next" and old == new_without_flag)):
        raise ValueError("Unexpected hotfix signature change")
    if current.__code__.co_freevars != candidate.__code__.co_freevars:
        raise ValueError("Unexpected hotfix closure change")
    return candidate


def publish(staged):
    # Caller has rechecked the inactive boundary; no await during publication.
    for current, candidate in staged:
        current.__code__ = candidate.__code__
        current.__defaults__ = candidate.__defaults__
        current.__kwdefaults__ = candidate.__kwdefaults__


async def apply_hotfix(controller):
    assert_boundary(controller)
    root = Path(__file__).resolve().parents[1]
    functions = targets()
    sources = {Path(f.__code__.co_filename).resolve() for f in functions}
    sources.update({root / "agents/bo/final_report.py", Path(__file__).resolve()})
    digests = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    staged = [(f, stage_function(f, Path(f.__code__.co_filename))) for f in functions]
    checked = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "pytest",
        "tests/unit/test_bo_final_report.py", "tests/unit/test_bo_final_hotfix.py",
        "tests/unit/test_bo_agent.py", "tests/unit/test_botorch_backend.py", "-q", "--tb=short"],
        cwd=root, capture_output=True, text=True, timeout=90)
    if checked.returncode:
        raise ValueError("BO final-report validation failed; live code unchanged: " + checked.stdout[-2000:])
    assert_boundary(controller)
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest for path, digest in digests.items()):
        raise ValueError("BO hotfix source changed during validation")
    publish(staged)
    result = {"ok": True, "scope": "bo_final_report_only", "server_restarted": False,
        "actuation_performed": False, "run_id": controller._state.run_id,
        "loop_count": controller._state.loop_count, "sha256": digests,
        "validated": checked.stdout.split("\n")[-2], "installed": not needs_patch()}
    controller._state.run_metadata["bo_final_report_hotfix"] = result
    await controller._emit_control_event("runtime.hot_reload", "Final BO reporting installed; active run preserved", result)
    return result
