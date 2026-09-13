"""Computational CAE bridge ownership and tool contracts."""
from __future__ import annotations

import importlib
from pathlib import Path
import tomllib


TOOL_IDS = {
    "cae.health",
    "cae.prepare_static_analysis",
    "cae.run_static_analysis",
    "calculix.health",
    "calculix.prepare_input",
    "calculix.solve",
    "calculix.postprocess",
    "calculix.run_job",
}


def test_cae_bridge_support_files_are_declared_as_package_data():
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = config["tool"]["setuptools"]["package-data"]
    assert package_data["device_bridges.cae"] == ["requirements.txt", "README.md"]


def test_cae_discovery_describes_computational_bridge_without_activation(monkeypatch):
    from device_bridges.cae.bridge import CAEBridge
    from device_bridges.cae.calculix import CalculiXBridge
    from device_bridges.module_discovery import discover_bridge_modules

    monkeypatch.setattr(CAEBridge, "__init__", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("CAE activated")))
    monkeypatch.setattr(CalculiXBridge, "__init__", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("CalculiX activated")))
    modules = [module.describe() for module in discover_bridge_modules() if module.module_id == "cae"]
    assert len(modules) == 1
    descriptor = modules[0]
    assert descriptor["classification"] == "computational"
    assert descriptor["physical_device"] is False
    assert descriptor["runtime_bridge_ids"] == ["cae_bridge", "calculix_bridge"]
    assert descriptor["providers"] == [
        {
            "id": "cae",
            "label": "CAE facade",
            "role": "deterministic analysis and guarded CalculiX orchestration",
            "implementation": "device_bridges.cae.bridge.CAEBridge",
            "source": "device_bridges/cae/bridge.py",
        },
        {
            "id": "calculix",
            "label": "CalculiX",
            "role": "prepared native finite-element solver boundary",
            "implementation": "device_bridges.cae.calculix.CalculiXBridge",
            "source": "device_bridges/cae/calculix.py",
        },
    ]
    assert descriptor["tools"] == sorted(TOOL_IDS)
    root = Path(__file__).resolve().parents[2]
    assert (root / descriptor["requirements"]).is_file()
    assert (root / descriptor["documentation"]).is_file()


def test_cae_legacy_bridge_and_tool_imports_share_canonical_identity(monkeypatch):
    aliases = {
        "device_bridges.cae_bridge": "device_bridges.cae.bridge",
        "device_bridges.calculix_bridge": "device_bridges.cae.calculix",
        "mcp_tools.cae_tools": "device_bridges.cae.tools",
        "mcp_tools.calculix_tools": "device_bridges.cae.calculix_tools",
    }
    for legacy_name, canonical_name in aliases.items():
        legacy = importlib.import_module(legacy_name)
        canonical = importlib.import_module(canonical_name)
        assert legacy is canonical
        monkeypatch.setattr(canonical, "_identity_probe", canonical_name, raising=False)
        assert importlib.import_module(legacy_name)._identity_probe == canonical_name


def test_cae_and_calculix_tool_ids_keep_one_existing_queue(tmp_path):
    from device_bridges.cae.calculix_tools import register_calculix_tools
    from device_bridges.cae.tools import register_cae_tools
    from mcp_tools.tool_registry import ToolRegistry

    class Queue:
        def __init__(self):
            self.calls = []

        def submit_sync(self, *, device, tool_name, handler, payload):
            self.calls.append((device, tool_name))
            return handler(payload)

        def status(self):
            return {"calls": list(self.calls)}

    queue = Queue()
    registry = ToolRegistry(job_queue=queue)
    cae = register_cae_tools(registry, {"devices": {"cae": {"mode": "test"}}}, repo_root=tmp_path)
    calculix = register_calculix_tools(registry, {"devices": {"calculix": {"mode": "test"}}}, repo_root=tmp_path)
    assert set(registry.list_tools()) == TOOL_IDS
    assert registry.resource("calculix_bridge") is calculix

    cae.prepare_static_analysis = lambda payload: {"ok": True, "payload": payload}
    calculix.prepare_input = lambda payload: {"ok": True, "payload": payload}
    registry.call("cae.prepare_static_analysis", {"run_id": "controlled-cae"})
    registry.call("calculix.prepare_input", {"run_id": "controlled-calculix"})
    assert queue.calls == [
        ("cae:calculix", "cae.prepare_static_analysis"),
        ("cae:calculix", "calculix.prepare_input"),
    ]


def test_analysis_package_resolves_one_cae_bridge_without_activation(monkeypatch):
    from agents.analysis.module import MODULE as analysis
    from device_bridges.cae.bridge import CAEBridge
    from device_bridges.cae.calculix import CalculiXBridge
    from device_bridges.module_discovery import discover_bridge_modules
    from packages.service import PackageService, installed_agent_packages

    monkeypatch.setattr(CAEBridge, "__init__", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("CAE activated")))
    monkeypatch.setattr(CalculiXBridge, "__init__", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("CalculiX activated")))
    packages = installed_agent_packages([analysis.describe()])
    bridges = [module.describe() for module in discover_bridge_modules()]
    service = PackageService(
        agent_packages=packages,
        bridge_modules=bridges,
        installed_handlers=["agent.analysis_agent"],
        installed_module_ids=["analysis"],
        validate_graph=lambda _raw: [],
        validate_module=lambda _ident, _raw: [],
    )
    catalog = service.catalog()
    assert catalog["ok"], catalog
    package = catalog["agent_packages"][0]
    assert package["bridge_modules"] == [{"id": "cae", "version": "1.0.0"}]
    bridge = next(item for item in catalog["bridge_modules"] if item["id"] == "cae")
    assert bridge["package_owners"] == [{"id": "analysis", "version": "1.0.0"}]
