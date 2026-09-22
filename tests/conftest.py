"""Pytest bootstrap to ensure project root is importable."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep automated tests deterministic and lightweight.
os.environ.setdefault("AUTONOMOUS_USE_REAL_LLM_IN_TEST", "0")
os.environ.setdefault("AUTONOMOUS_ALLOW_MOCK_FALLBACK", "1")
os.environ.setdefault("AUTONOMOUS_BACKEND", "ollama")
os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:9")


import pytest


@pytest.fixture
def simulated_vision_process(monkeypatch):
    """Replace ROS process I/O, keeping cycle admission and restart checks real."""
    from itertools import count
    from weakref import WeakKeyDictionary
    from device_bridges.camera_vision import tools
    from device_bridges.camera_vision.utm_runtime_bridge import UTMRuntimeProcessManager

    processes = WeakKeyDictionary()
    pids = count(10000)
    monkeypatch.setattr(tools, "_VISION_CYCLE_RELOADS", {})

    def status(manager):
        pid = processes.get(manager)
        return {"ok": True, "status": "running" if pid else "stopped", "pid": pid,
                "source": "controlled_test_process"}

    def start(manager):
        already_running = bool(processes.get(manager))
        if not already_running:
            processes[manager] = next(pids)
        return {**status(manager), "already_running": already_running}

    def stop(manager):
        previous_pid = processes.pop(manager, None)
        return {**status(manager), "previous_pid": previous_pid,
                "was_running": bool(previous_pid)}

    monkeypatch.setattr(UTMRuntimeProcessManager, "start", start)
    monkeypatch.setattr(UTMRuntimeProcessManager, "stop", stop)
    monkeypatch.setattr(UTMRuntimeProcessManager, "status", status)


@pytest.fixture
def handoff_no_external(monkeypatch, tmp_path):
    """Opt-in physical/process denial, installed before a test bootstraps runtime.

    Only the scoped handoff suites opt in. Simulations replace registered I/O
    callbacks explicitly; untouched transports may never contact hardware.
    """
    import socket
    import subprocess
    import json
    from types import SimpleNamespace
    from utils import manipulation_profile

    # Virtual handoff runs must not inherit an operator's persisted live robot
    # options (for example, live-only linear interpolation). Keep the production
    # validation enabled, and give each test its own initially empty profile.
    monkeypatch.setattr(
        manipulation_profile, "MANIPULATION_AGENT_PROFILE_PATH",
        tmp_path / "manipulation_agent_bridge.json",
    )
    def deny(*args, **kwargs):
        raise AssertionError("Unlisted external effect in handoff verification")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(os, "system", deny)
    original_open = os.open
    def device_open(path, *args, **kwargs):
        if isinstance(path, (str, bytes, os.PathLike)) and str(path).startswith("/dev/") and str(path) != "/dev/null":
            return deny(path)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(os, "open", device_open)
    from agents.base_agent import AgentContext
    original_complete = AgentContext.complete
    async def complete(self, task_type, prompt, **kwargs):
        if task_type == "orchestrator_plan":
            try:
                request = json.loads(prompt)
            except (TypeError, ValueError):
                request = {}
            if request.get("operation") == "decide_orchestration":
                return SimpleNamespace(model="controlled-handoff-test", raw={}, text=json.dumps({
                    "tool": "prepare_handoff", "arguments": {"candidate": request["context"]["handoff_candidates"][0]},
                    "reason": "Dispatcher-admitted test boundary", "evidence_refs": ["boundary:result"]}))
        return await original_complete(self, task_type, prompt, **kwargs)
    monkeypatch.setattr(AgentContext, "complete", complete)
    # Registered module owners select their backend through ModuleRuntimeContext,
    # not AgentContext.complete. Stub only the model response at that boundary.
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    original_module_complete = ModuleRuntimeContext.complete
    async def module_complete(self, task_type, prompt, **kwargs):
        if task_type == "orchestrator_plan":
            try:
                request = json.loads(prompt)
            except (TypeError, ValueError):
                request = {}
            if request.get("operation") == "decide_orchestration":
                return SimpleNamespace(model="controlled-module-handoff-test", raw={}, text=json.dumps({
                    "tool": "prepare_handoff", "arguments": {"candidate": request["context"]["handoff_candidates"][0]},
                    "reason": "Dispatcher-admitted test boundary", "evidence_refs": ["boundary:result"]}))
        return await original_module_complete(self, task_type, prompt, **kwargs)
    monkeypatch.setattr(ModuleRuntimeContext, "complete", module_complete)
