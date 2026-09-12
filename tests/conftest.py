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
def handoff_no_external(monkeypatch):
    """Opt-in physical/process denial, installed before a test bootstraps runtime.

    Only the scoped handoff suites opt in. Simulations replace registered I/O
    callbacks explicitly; untouched transports may never contact hardware.
    """
    import socket
    import subprocess
    import json
    from types import SimpleNamespace
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
    from agents.analysis_runtime import AnalysisRuntimeService
    monkeypatch.setattr(AnalysisRuntimeService, "resume", lambda *args, **kwargs: None)
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
