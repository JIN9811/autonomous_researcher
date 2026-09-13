"""Package endpoints must remain detached under physical/process denial."""
from copy import deepcopy
from pathlib import Path
import pytest
import yaml

from tests.integration.test_agent_execution_graph_api import module_api as module_api
from tests.integration.test_orchestrator_setup_loop import actual_controller as actual_controller


def draft_from_repository():
    return {"schema": "ax4lab.experimental_package.v1", "id": "full_cycle", "version": "1.0.0",
            "graph": yaml.safe_load(Path("graphs/configs/atr_closed_loop.yaml").read_text())["graph"],
            "agent_packages": [{"id": "design", "version": "1.0.0"}, {"id": "specimen", "version": "1.0.0"}],
            "module_configurations": {p.parent.name: yaml.safe_load(p.read_text())
                                      for p in Path("graphs/modules").glob("*/module.yaml")}, "bindings": []}


def test_full_graph_package_roundtrip_is_detached_and_catalog_never_reads_private_memory(module_api, monkeypatch):
    client, app_main, controller, guard, module_root = module_api
    before = {p: p.read_bytes() for p in module_root.rglob("*") if p.is_file()}
    graph_path = Path("graphs/configs/atr_closed_loop.yaml")
    graph_before = graph_path.read_bytes()
    loaded_before = set(app_main._RUNTIME_MODULE_MANAGEMENT_LOADED)
    draft = draft_from_repository()
    draft["graph"]["nodes"].reverse()
    draft["module_configurations"]["specimen"]["module"]["execution_graph"]["nodes"].reverse()
    calls_before = guard.physical_call_count
    def deny(*args, **kwargs):
        raise AssertionError("Package endpoint must not invoke execution or storage mutation")
    from graphs import ModuleConfigStore, GraphVersionStore
    monkeypatch.setattr(ModuleConfigStore, "write_active", deny)
    monkeypatch.setattr(ModuleConfigStore, "save_version", deny)
    monkeypatch.setattr(GraphVersionStore, "save_version", deny)
    monkeypatch.setattr(controller, "start", deny)
    original_read = Path.read_text
    def no_private_read(path, *args, **kwargs):
        if path.suffix == ".json" and "memory" in path.parts:
            deny(path)
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", no_private_read)

    catalog_response = client.get("/api/packages")
    assert catalog_response.status_code == 200
    catalog = catalog_response.json()
    assert catalog["ok"] and len(catalog["bridge_modules"]) == 1
    exported = client.post("/api/packages/experimental/export", json=draft)
    assert exported.status_code == 200
    assert exported.json()["ok"], exported.json()
    package = exported.json()["package"]
    assert package["graph"] == draft["graph"]
    assert package["module_configurations"] == draft["module_configurations"]
    assert any(o["handler"] == "agent.orchestrator_agent" for o in package["external_owners"])
    imported = client.post("/api/packages/experimental/import", json=package)
    assert imported.status_code == 200
    result = imported.json()
    assert result["ok"], result
    assert result["draft"] == package
    assert not result["activated"] and not result["persisted"]
    assert result["unresolved_bindings"][0]["owner_id"] == "printer_fleet"
    assert {p: p.read_bytes() for p in module_root.rglob("*") if p.is_file()} == before
    assert graph_path.read_bytes() == graph_before
    assert set(app_main._RUNTIME_MODULE_MANAGEMENT_LOADED) == loaded_before
    assert guard.physical_call_count == calls_before == 0


@pytest.mark.parametrize("change", ["missing_graph", "changed_handler"])
def test_registered_specimen_module_validator_pins_execution_owner_without_writes(module_api, change):
    client, app_main, controller, guard, module_root = module_api
    path = module_root / "specimen" / "module.yaml"
    before = path.read_bytes()
    payload = client.get("/api/modules/specimen").json()["module"]
    if change == "missing_graph":
        payload["module"].pop("execution_graph")
    else:
        payload["module"]["handler"] = "agent.guardian_agent"
    result = client.put("/api/modules/specimen", json={"module": payload, "activate": True}).json()
    assert not result["ok"], result
    assert path.read_bytes() == before
    assert guard.physical_call_count == 0


def test_package_api_rejects_invalid_modules_private_values_and_oversized_body(module_api):
    client, app_main, controller, guard, module_root = module_api
    draft = draft_from_repository()
    export = client.post("/api/packages/experimental/export", json=draft)
    assert export.status_code == 200 and export.json()["ok"], export.text
    package = export.json()["package"]
    invalid = deepcopy(package)
    invalid["module_configurations"]["specimen"]["module"]["execution_graph"]["nodes"][0]["handler"] = "python.run"
    rejected = client.post("/api/packages/experimental/import", json=invalid)
    assert rejected.status_code == 200 and not rejected.json()["ok"]
    assert rejected.json()["draft"] is None
    private = deepcopy(package)
    private["connection"] = {"password": "never-echo"}
    rejected = client.post("/api/packages/experimental/import", json=private)
    assert not rejected.json()["ok"] and "never-echo" not in rejected.text
    oversized = client.post("/api/packages/experimental/import", content=b"x" * 1_048_577,
                            headers={"content-type": "application/json"})
    assert oversized.status_code == 413 and not oversized.json()["ok"]
    malformed = client.post("/api/packages/experimental/import", content=b'{"id": 1, "id": 2}',
                            headers={"content-type": "application/json"})
    assert malformed.status_code == 400 and not malformed.json()["ok"]
    assert guard.physical_call_count == 0
