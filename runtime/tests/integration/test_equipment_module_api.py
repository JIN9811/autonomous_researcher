"""Installed Equipment frontend and report ownership under the no-effects guard."""
from copy import deepcopy
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.integration.test_agent_execution_graph_api import actual_controller, module_api


def test_equipment_frontend_asset_catalog_and_report_evidence_use_installed_owner(module_api):
    client, _, controller, guard, _ = module_api
    module = client.get("/api/modules/equipment").json()
    assert module["implementation"] == controller._deps.agent_registry.get_module("equipment").describe()
    assert module["execution_catalog"]["implementation_structure"]["operations"]["equipment.task"]

    manifest = next(item for item in client.get("/api/runtime/agent-manifests").json()["agents"] if item["id"] == "equipment")
    frontend = manifest["implementation"]["frontend"]
    assert frontend == {
        "host": "/live",
        "descriptor": "graphs/modules/equipment/ui.yaml",
        "asset_url": "/module-assets/equipment/live_report.js",
        "namespace": "AX4LABEquipmentUI",
        "factory": "createFrontend",
        "report_api": "/api/agents/equipment/report",
    }
    assert {key: manifest["renderer"][key] for key in ("dashboard", "report", "fallback")} == {
        "dashboard": "module", "report": "module", "fallback": "descriptor"
    }
    assert [card["id"] for card in manifest["cards"]] == [
        "equipment_bridge_runtime",
        "equipment_active_program_skill",
        "equipment_recovery_boundary",
        "equipment_agentic_progress",
        "equipment_method_values",
        "equipment_screen_transitions",
        "equipment_raw_data_next_specimen",
        "equipment_execution_evidence",
        "equipment_handoff",
    ]
    asset = client.get(frontend["asset_url"])
    assert asset.status_code == 200
    assert "AX4LABEquipmentUI" in asset.text

    state = controller._state
    state.run_metadata.update(
        equipment_report={
            "task_id": "utm-cycle-current",
            "screen_checks": [{"checkpoint": "after_test", "ok": True, "screenshot_artifact": "utm-after-frame.png"}],
            "artifact_records": [{"artifact_id": "raw-current", "linux_path": "/runs/current/raw.csv"}],
            "control_plan": {"program_id": "utm_cycle"},
            "decision": {"handoff_status": "ready_for_analysis"},
        },
        equipment_result={"status": "ok", "result_file": "/runs/current/raw.csv"},
        equipment_handoff={"status": "ready_for_analysis", "next_agent": "analysis"},
        equipment_metrics={"rows": 42},
    )
    before = deepcopy(state.run_metadata)
    sections = client.get("/api/agents/equipment/report").json()["report"]["sections"]
    assert sections["equipment_report"]["screen_checks"][0]["screenshot_artifact"] == "utm-after-frame.png"
    assert sections["equipment_report"]["artifact_records"][0]["artifact_id"] == "raw-current"
    assert sections["equipment_result"]["result_file"] == "/runs/current/raw.csv"
    assert sections["equipment_handoff"]["next_agent"] == "analysis"
    assert sections["metrics"] == {"rows": 42}
    assert {key: state.run_metadata[key] for key in before} == before
    assert "_projection_state" not in state.run_metadata
    assert guard.physical_call_count == 0
    assert guard.denied == []


def test_inactive_equipment_owner_cannot_serve_its_module_asset(module_api):
    client, _, controller, guard, _ = module_api
    registry = controller._deps.agent_registry
    active = set(registry.active_names()) - {"equipment_agent"}
    registry.bind_activation(lambda: active)
    assert client.get("/module-assets/equipment/live_report.js").status_code == 404
    assert guard.physical_call_count == 0
    assert guard.denied == []


@pytest.mark.parametrize(
    ("host", "asset_path"),
    [("/live", "/static/planning.js"), ("/ide", "/static/runtime_ide.js")],
)
def test_equipment_frontend_hosts_publish_versioned_loadable_assets(module_api, host, asset_path):
    client, _, _, guard, _ = module_api

    class ScriptSources(HTMLParser):
        def __init__(self):
            super().__init__()
            self.sources = []

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.sources.append(dict(attrs).get("src", ""))

    page = client.get(host)
    assert page.status_code == 200
    parser = ScriptSources()
    parser.feed(page.text)
    sources = [src for src in parser.sources if urlsplit(src).path == asset_path]
    assert len(sources) == 1
    assert parse_qs(urlsplit(sources[0]).query).get("v")
    asset = client.get(sources[0])
    assert asset.status_code == 200
    assert "javascript" in asset.headers["content-type"]
    assert asset.content
    assert guard.physical_call_count == 0
    assert guard.denied == []
