"""Serve actual application routes with synthetic services, only after OS isolation.

These test doubles are not a supported PLC transport or physical evidence.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import importlib
import json
import os
from pathlib import Path
import sys
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import urllib.request

from .sandbox import require_boundary

MODES = {"import_only", "fake_services"}


@contextmanager
def fixture_application(lifespan_mode: str):
    if lifespan_mode not in MODES:
        raise ValueError("lifespan_mode must be import_only or fake_services")
    require_boundary()
    if "app.main" in sys.modules:
        raise RuntimeError("Use a fresh interpreter for each fixture mode")
    from scripts.orchestrator_verification_guard import VerificationGuard
    with ExitStack() as stack:
        original_check_output = subprocess.check_output
        def fixture_fontconfig(command, *args, **kwargs):
            if isinstance(command, list) and command and command[0] == "fc-list":
                # Matplotlib can use its bundled fonts; no host font discovery process.
                raise FileNotFoundError("fontconfig intentionally absent in fixture")
            return original_check_output(command, *args, **kwargs)
        stack.enter_context(patch.object(subprocess, "check_output", fixture_fontconfig))
        guard = stack.enter_context(VerificationGuard())
        audit_active = [True]
        writes = set()
        def audit_writes(event, args):
            if not audit_active[0]:
                return
            paths = []
            if event == "open" and len(args) >= 3:
                flags = args[2] or 0
                if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                    paths = [args[0]]
            elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.symlink"}:
                paths = [args[1] if event == "os.symlink" else args[0]]
            elif event in {"os.rename", "os.link"}:
                paths = list(args[:2])
            for path in paths:
                if isinstance(path, (str, bytes, os.PathLike)):
                    resolved = Path(os.fsdecode(path)).resolve()
                    writes.add(str(resolved))
                    if str(resolved) != "/dev/null" and not any(resolved.is_relative_to(root) for root in (Path("/snapshot"), Path("/tmp"))):
                        guard.deny()
        sys.addaudithook(audit_writes)
        stack.callback(lambda: audit_active.__setitem__(0, False))
        original_run = subprocess.run
        def fixture_telemetry(command, *args, **kwargs):
            if (isinstance(command, list) and len(command) == 3
                    and Path(command[0]).name == "nvidia-smi"
                    and command[1] == "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu"
                    and command[2] == "--format=csv,noheader,nounits"):
                return subprocess.CompletedProcess(command, 1, "", "No GPU in software fixture")
            return original_run(command, *args, **kwargs)
        stack.enter_context(patch.object(subprocess, "run", fixture_telemetry))
        # Only the fixture client's loopback HTTP is allowed, never model endpoints.
        guard.addresses.add(("127.0.0.1", 17860))
        stack.enter_context(patch.object(os, "kill", guard.deny))
        stack.enter_context(patch.object(os, "killpg", guard.deny))
        import app.bootstrap as bootstrap
        from backends.mock_llm import MockLLMBackend
        effects = dict(model_calls=0, plc_start=0, plc_stop=0, compute_configure=0,
                       compute_close=0, recorder_start=0, recorder_stop=0,
                       ingestion_start=0, ingestion_stop=0)
        class FixtureBackend(MockLLMBackend):
            async def complete(self, **kwargs):
                effects['model_calls'] += 1
                return await super().complete(**kwargs)
        synthetic = {"system": {"system": {"inference_backend": "ollama",
                     "force_real_llm_in_test": False, "allow_mock_fallback": True}},
                     "models": {"models": {"e4b": {"primary": "fixture-only"},
                                             "orchestrator": {"primary": "fixture-only"}}},
                     "devices": {}, "lerobot": {}, "logging": {}}
        from copy import deepcopy
        stack.enter_context(patch.object(bootstrap, "_load_configs", lambda *a, **kw: deepcopy(synthetic)))
        # Explicit disposable stores; source roots stay in the exported snapshot.
        from dataclasses import replace
        from tempfile import TemporaryDirectory
        from utils.runtime_paths import current_paths
        fixture_root = Path(stack.enter_context(TemporaryDirectory(prefix="atr-fixture-")))
        fixture_paths = replace(current_paths(), workspace_root=fixture_root / "workspace",
            run_root=fixture_root / "run-volume/runs", memory_root=fixture_root / "state-volume/memory",
            artifact_root=fixture_root / "export-volume/artifacts", output_root=fixture_root / "outputs",
            source_inbox_root=fixture_root / "inbox", user_file_root=fixture_root / "user-files",
            log_root=fixture_root / "logs")
        original_load_runtime = bootstrap.load_runtime
        stack.enter_context(patch.object(bootstrap, "load_runtime", lambda: original_load_runtime(paths=fixture_paths)))
        stack.enter_context(patch.object(bootstrap, "_build_backend", lambda *a, **kw: FixtureBackend()))

        from utils import plc_bridge_service, artifact_preservation, run_review, compute_pool
        lifecycle = {"started": False, "stopped": False}

        class FixturePLC(plc_bridge_service.PLCBridgeService):
            async def start(self):
                lifecycle["started"] = True
                effects['plc_start'] += 1

            async def shutdown(self):
                lifecycle["stopped"] = True
                effects['plc_stop'] += 1

        class FixtureRecorder:
            def __init__(self, *args, **kwargs):
                self.thread = SimpleNamespace(join=lambda *a: None)

            def start(self): effects['recorder_start'] += 1
            def stop(self): effects['recorder_stop'] += 1
            def close(self): pass
            def offer(self, *args, **kwargs): pass

        stack.enter_context(patch.object(plc_bridge_service, "PLCBridgeService", FixturePLC))
        stack.enter_context(patch.object(artifact_preservation, "PreservationService", FixtureRecorder))
        stack.enter_context(patch.object(run_review, "RunReviewRecorder", FixtureRecorder))
        def fixture_compute(workers=3, *, paths=None):
            assert paths is fixture_paths
            effects['compute_configure'] += 1
        stack.enter_context(patch.object(compute_pool, "configure_compute_pool", fixture_compute))
        stack.enter_context(patch.object(compute_pool, "close_compute_pool",
            lambda: effects.__setitem__('compute_close', effects['compute_close'] + 1)))
        from knowledge.source_runtime import SourceIngestionService
        async def no_background_start(self): effects['ingestion_start'] += 1
        async def no_background_stop(self): effects['ingestion_stop'] += 1
        stack.enter_context(patch.object(SourceIngestionService, "start", no_background_start))
        stack.enter_context(patch.object(SourceIngestionService, "shutdown", no_background_stop))
        from device_bridges.lerobot_bridge import LeRobotBridge
        from device_bridges.utm_runtime_bridge import UTMRuntimeProcessManager
        stack.enter_context(patch.object(LeRobotBridge, "shutdown", lambda self: None))
        stack.enter_context(patch.object(UTMRuntimeProcessManager, "shutdown", lambda self: None))
        module = importlib.import_module("app.main")
        from dataclasses import asdict
        module._layout_fixture_evidence = {'roots': {key: str(value) for key, value in asdict(fixture_paths).items()},
                                          'effects': effects, 'writes': writes}
        yield module, guard, lifecycle


def _import_origins() -> dict[str, str]:
    prefixes = {"app", "agents", "graphs", "utils", "knowledge", "memory", "device_bridges", "orchestrator"}
    return {name: str(Path(module.__file__).resolve()) for name, module in tuple(sys.modules.items())
            if name.split(".")[0] in prefixes and getattr(module, "__file__", None)
            }


def fixture_evidence(module, guard, lifecycle) -> dict:
    origins = _import_origins()
    evidence = module._layout_fixture_evidence
    return {'roots': evidence['roots'], 'effects': dict(evidence['effects']),
            'writes': sorted(evidence['writes']), 'import_origins': origins,
            'outside_imports': [name for name, path in origins.items()
                                if not Path(path).is_relative_to(evidence['roots']['runtime_root'])],
            'unexpected_effects': guard.denied, 'lifespan_started': lifecycle['started'],
            'lifespan_stopped': lifecycle['stopped'], 'evidence': 'software-only synthetic services'}


def verify_routes(*, lifespan_mode: str) -> dict:
    import uvicorn
    with fixture_application(lifespan_mode) as (module, guard, lifecycle):
        config = uvicorn.Config(module.app, host="127.0.0.1", port=17860, workers=1, reload=False,
                                lifespan="on" if lifespan_mode == "fake_services" else "off",
                                log_level="error", loop="asyncio", http="h11", access_log=False)
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        routes = {}
        try:
            if not server.started:
                raise AssertionError("Fixture server failed to start")
            paths = ["/", "/ide", "/live", "/knowledge", "/api/graphs", "/api/modules",
                     "/api/docs/agent-baseline", "/api/docs/agent-baseline.md",
                     "/api/state", "/api/packages", "/api/modules/knowledge", "/static/favicon.svg"]
            assets = []
            registry = module.controller._deps.agent_registry
            for installed in registry.modules():
                frontend = getattr(installed, "frontend_root", None)
                if frontend and installed.agent_name in registry.active_names():
                    candidates = sorted(p for p in frontend.rglob("*") if p.is_file() and p.suffix in {".js", ".css"})
                    assets.extend(f"/module-assets/{installed.module_id}/{candidate.relative_to(frontend)}"
                                  for candidate in candidates)
            if not assets:
                raise AssertionError("No active module assets discovered")
            for path in paths + assets:
                with urllib.request.urlopen("http://127.0.0.1:17860" + path, timeout=15) as response:
                    routes[path] = response.status
                    assert response.read(), path
            assert all(status == 200 for status in routes.values()), routes
        finally:
            server.should_exit = True
            thread.join(15)
            if thread.is_alive():
                raise AssertionError("Fixture server failed bounded teardown")
        result = {"routes": routes, "module_assets": len(assets), **fixture_evidence(module, guard, lifecycle)}
        assert result["unexpected_effects"] == [], result
        assert result["outside_imports"] == [], result
        if lifespan_mode == "fake_services":
            assert lifecycle == {"started": True, "stopped": True}, result
        return result


def main(*, lifespan_mode: str, port: int = 17860) -> int:
    if port != 17860:
        raise ValueError("Only the isolated fixture port 17860 is authorized")
    with fixture_application(lifespan_mode) as (module, guard, _):
        import uvicorn
        uvicorn.run(module.app, host="127.0.0.1", port=port, workers=1, reload=False,
                    lifespan="on" if lifespan_mode == "fake_services" else "off")
        return 1 if guard.denied else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "verify":
        print(json.dumps(verify_routes(lifespan_mode=sys.argv[2])))
    else:
        raise SystemExit(main(lifespan_mode=sys.argv[1] if len(sys.argv) > 1 else "import_only"))
