"""Portable composition must validate atomically without opening device transports."""
from copy import deepcopy
import importlib
from pathlib import Path

import pytest

def service(**overrides):
    from agents.design.module import MODULE as design
    from agents.specimen.module import MODULE as specimen
    from device_bridges.printer_fleet.module import MODULE as fleet
    from packages.service import PackageService, installed_agent_packages
    from graphs import ATRLangGraphCompiler, GraphConfig, HandlerRegistry

    registry = HandlerRegistry()
    async def handler(state):
        return state
    for name in ("agent.design_agent", "agent.specimen_agent", "agent.orchestrator_agent"):
        registry.register(name, handler)
    def validate_graph(raw):
        compiler = ATRLangGraphCompiler(GraphConfig.model_validate(raw), registry,
                                       module_ids={"design", "specimen", "orchestrator"})
        errors = compiler.validate()
        if not errors:
            compiler.compile()
        return errors
    args = dict(agent_packages=installed_agent_packages([design.describe(), specimen.describe()]),
                bridge_modules=[fleet.describe()],
                installed_handlers=registry.names(), installed_module_ids=["design", "specimen", "orchestrator"],
                validate_graph=validate_graph, validate_module=lambda ident, raw: [])
    args.update(overrides)
    return PackageService(**args)


def payload():
    return {"schema": "ax4lab.experimental_package.v1", "id": "example", "version": "1.0.0",
            "graph": {"id": "example", "name": "Example", "version": "1.0.0", "entry_node": "design",
                      "finish_nodes": ["specimen"], "nodes": [
                          {"id": "design", "label": "Design", "handler": "agent.design_agent", "module_id": "design", "stage": "design"},
                          {"id": "specimen", "label": "Specimen", "handler": "agent.specimen_agent", "module_id": "specimen", "stage": "specimen"}],
                      "stage_dispatch": {"design": "design", "specimen": "specimen"}, "terminal_stages": [],
                      "edges": [{"source": "design", "target": "specimen"}]},
            "agent_packages": [{"id": "design", "version": "1.0.0"}, {"id": "specimen", "version": "1.0.0"}],
            "module_configurations": {}, "bindings": []}


def test_catalog_resolves_bridge_free_design_and_shared_installed_fleet():
    svc = service()
    catalog = svc.catalog()
    assert catalog["ok"]
    packages = {item["id"]: item for item in catalog["agent_packages"]}
    assert packages["design"]["bridge_modules"] == []
    assert packages["specimen"]["bridge_modules"] == [{"id": "printer_fleet", "version": "1.0.0"}]
    fleet = catalog["bridge_modules"][0]
    assert fleet["package_owners"] == [{"id": "specimen", "version": "1.0.0"}]
    assert {item["id"] for item in fleet["providers"]} == {"bambu", "prusa"}
    second = deepcopy(packages["specimen"])
    second["id"] = "specimen_copy"
    shared = service(agent_packages=[packages["specimen"], second]).catalog()
    assert len(shared["bridge_modules"]) == 1
    assert len(shared["bridge_modules"][0]["package_owners"]) == 2
    catalog["bridge_modules"].clear()
    assert len(svc.catalog()["bridge_modules"]) == 1


@pytest.mark.parametrize("bridges", [[], [{"schema": "ax4lab.bridge_module.v1", "id": "printer_fleet", "version": "2.0.0"}]])
def test_catalog_missing_or_conflicting_dependency_is_atomic(bridges):
    result = service(bridge_modules=bridges).catalog()
    assert result["ok"] is False
    assert result["agent_packages"] == result["bridge_modules"] == []


def test_roundtrip_detached_rearranged_nodes_and_symbolic_bindings():
    svc, draft = service(), payload()
    draft["graph"]["nodes"].reverse()
    before = deepcopy(draft)
    exported = svc.export_experimental(draft)
    assert exported["ok"], exported
    assert draft == before
    assert exported["package"]["bridge_modules"] == [{"id": "printer_fleet", "version": "1.0.0"}]
    imported = svc.import_experimental(exported["package"])
    assert imported["ok"] and not imported["activated"] and not imported["persisted"]
    assert imported["draft"]["graph"] == draft["graph"]
    assert imported["draft"]["module_configurations"] == {}
    assert imported["unresolved_bindings"][0]["owner_id"] == "printer_fleet"
    imported["draft"]["graph"]["nodes"].clear()
    assert len(exported["package"]["graph"]["nodes"]) == 2


@pytest.mark.parametrize("mutation", [
    lambda p: p["agent_packages"].append(p["agent_packages"][0]),
    lambda p: p["agent_packages"][0].update(version=">=1.0.0"),
    lambda p: p["agent_packages"][0].update(version="9.0.0"),
    lambda p: p["graph"]["edges"][0].update(target="missing"),
    lambda p: p["graph"]["nodes"][0].update(handler="python.run"),
    lambda p: p.update(id="../escape"),
    lambda p: p.update(files=["secrets.txt"]),
    lambda p: p.update(connection={"host": "192.168.0.1"}),
    lambda p: p["graph"]["nodes"][0].update(executable="do_it"),
    lambda p: p["graph"].update(metadata={"path": "/private/example.json"}),
    lambda p: p["graph"].update(metadata={"file": "../../private.json"}),
    lambda p: p["graph"].update(metadata={"api_key": "secret"}),
    lambda p: p["graph"].update(metadata={"nested": {"command": "run"}}),
    lambda p: p.update(bindings=[{"id": "printer", "kind": "device", "owner_id": "printer_fleet", "value": "host"}]),
])
def test_import_rejects_invalid_or_private_payload_without_a_draft(mutation):
    svc = service()
    package = svc.export_experimental(payload())["package"]
    mutation(package)
    result = svc.import_experimental(package)
    assert result["ok"] is False, result
    assert result["draft"] is None
    assert result["errors"]


def test_export_excludes_runtime_state_and_credentials_but_preserves_declarative_references():
    draft = payload()
    draft["runtime_state"] = {"run_id": "private", "token": "secret"}
    draft["graph"]["metadata"] = {"api_key": "secret", "source": "graphs/configs/atr_closed_loop.yaml"}
    result = service().export_experimental(draft)
    assert result["ok"], result
    assert "runtime_state" not in result["package"]
    assert result["package"]["graph"]["metadata"] == {"source": "graphs/configs/atr_closed_loop.yaml"}


def test_legacy_owners_are_explicit_and_missing_owner_fails():
    svc, draft = service(), payload()
    draft["graph"]["nodes"][0].update(handler="agent.orchestrator_agent", module_id="orchestrator")
    result = svc.export_experimental(draft)
    assert result["ok"], result
    assert result["package"]["external_owners"] == [{"handler": "agent.orchestrator_agent", "module_id": "orchestrator"}]
    result["package"]["external_owners"] = []
    assert svc.import_experimental(result["package"])["ok"] is False


def test_removing_membership_does_not_remove_installed_packages_or_storage():
    svc, draft = service(), payload()
    before = svc.catalog()
    draft["agent_packages"] = []
    result = svc.export_experimental(draft)
    assert result["ok"] and result["package"]["bridge_modules"] == []
    assert svc.catalog() == before
    assert len(result["package"]["external_owners"]) == 2


def test_size_limit_rejects_before_validation_and_never_echoes_private_values():
    from packages.service import MAX_PACKAGE_BYTES
    draft = payload()
    draft["graph"]["metadata"] = {"notes": "x" * MAX_PACKAGE_BYTES}
    rejected = service().import_experimental(draft)
    assert not rejected["ok"] and rejected["draft"] is None
    private = payload()
    private["graph"]["metadata"] = {"api_key": "do-not-echo-this"}
    assert "do-not-echo-this" not in str(service().import_experimental(private))


@pytest.mark.parametrize("field,value", [
    ("connection_settings", {"address": "10.0.0.7"}),
    ("printer_ip", "10.0.0.7"), ("mqtt_port", 1883),
    ("device_address", "10.0.0.7"), ("value", "10.0.0.7"),
    ("value", "my-host.local"), ("python_code", "print(1)"),
    ("startup_command", "touch marker"),
])
def test_nested_connection_and_executable_aliases_fail_closed(field, value):
    svc = service()
    package = svc.export_experimental(payload())["package"]
    package["graph"]["metadata"] = {"settings": {field: value}}
    assert not svc.import_experimental(package)["ok"]


def test_graph_preserves_repository_relative_module_references():
    draft = payload()
    draft["graph"]["nodes"][0]["module_id"] = "modules/design"
    exported = service().export_experimental(draft)
    assert exported["ok"]
    assert exported["package"]["graph"]["nodes"][0]["module_id"] == "modules/design"
    assert exported["package"]["external_owners"] == []


def test_graph_cannot_rebind_installed_module_to_another_registered_owner():
    svc = service()
    package = svc.export_experimental(payload())["package"]
    package["graph"]["nodes"][0]["handler"] = "agent.specimen_agent"
    package["external_owners"] = [{"handler": "agent.specimen_agent", "module_id": "design"}]
    assert not svc.import_experimental(package)["ok"]


def test_strict_agent_manifest_rejects_machine_path_even_without_reading_target():
    from packages.contracts import AgentPackage
    from pydantic import ValidationError
    manifest = service().catalog()["agent_packages"][0]
    manifest["module_reference"] = "/private/modules/example.yaml"
    with pytest.raises(ValidationError):
        AgentPackage.model_validate(manifest)


def test_module_configuration_unknown_nested_execution_fields_are_rejected():
    svc = service()
    package = svc.export_experimental(payload())["package"]
    package["module_configurations"] = {"design": {"module": {"id": "design", "handler": "agent.design_agent",
                                                             "metadata": {"shell": "printf bad"}}}}
    assert not svc.import_experimental(package)["ok"]


def test_bridge_descriptor_does_not_import_providers_or_read_memory(monkeypatch):
    import builtins
    from device_bridges.printer_fleet import module
    original_import = builtins.__import__
    def checked_import(name, *args, **kwargs):
        if name.startswith(("device_bridges.bambu", "device_bridges.prusa")):
            raise AssertionError("descriptor must not import providers")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("descriptor must not read files"))
    assert importlib.reload(module).MODULE.describe()["tools"] == ["printer.prepare", "device.health"]


def test_bambu_autoejection_flat_import_preserves_grouped_module_identity():
    assert importlib.import_module("device_bridges.bambu_autoejection") is importlib.import_module("device_bridges.bambu.autoejection")


@pytest.mark.parametrize("provider", ["bambu", "prusa"])
def test_relocated_provider_keeps_flat_import_identity_and_repository_root(provider, monkeypatch):
    flat = importlib.import_module(f"device_bridges.{provider}_bridge")
    nested = importlib.import_module(f"device_bridges.{provider}.bridge")
    assert flat is nested
    assert nested.REPO_ROOT == Path(__file__).resolve().parents[2]
    monkeypatch.setattr(flat, "REPO_ROOT", Path("sentinel"))
    assert nested.REPO_ROOT == Path("sentinel")
