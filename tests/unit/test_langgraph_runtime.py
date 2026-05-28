"""Tests for config-driven LangGraph runtime wiring."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import app.main as app_main
from graphs import ATRLangGraphCompiler, GraphConfig, HandlerRegistry, ModuleConfig, load_graph_config, load_module_config
from orchestrator.graph import OrchestrationGraph
from orchestrator.router import stage_to_agent
from orchestrator.transitions import default_next_stage, ordered_stages


def _noop_registry() -> HandlerRegistry:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    registry = HandlerRegistry()

    async def _noop(runtime_state: dict[str, object]) -> dict[str, object]:
        return runtime_state

    for handler_id in config.handler_ids:
        registry.register(handler_id, _noop)
    return registry


def _event_cursor() -> int:
    return len(app_main.controller.recent_events())


def _assert_runtime_event_since(cursor: int, event_type: str, action: str) -> dict[str, object]:
    events = app_main.controller.recent_events()[cursor:]
    matched = [
        event
        for event in events
        if event.get("type") == event_type and isinstance(event.get("payload"), dict) and event["payload"].get("action") == action
    ]
    assert matched, f"missing {event_type} action={action}; saw={[event.get('type') for event in events]}"
    return matched[-1]


def _set_graph_default_transition(payload: dict[str, object], source: str, target: str) -> None:
    """Update transitions plus the matching logical edge in a graph JSON payload."""
    transitions = payload.setdefault("transitions", {})
    assert isinstance(transitions, dict)
    transitions[source] = target
    edges = payload.get("edges")
    assert isinstance(edges, list)
    default_edge = next(
        edge
        for edge in edges
        if isinstance(edge, dict)
        and isinstance(edge.get("metadata"), dict)
        and edge["metadata"].get("runtime_edge") == "logical_transition"
        and edge["metadata"].get("from_stage") == source
        and edge["metadata"].get("default_transition") is True
    )
    default_edge["target"] = target
    default_edge["label"] = f"default transition: {source} -> {target}"
    default_edge["metadata"]["to_stage"] = target




def _add_graph_transition_candidate(
    payload: dict[str, object],
    source: str,
    target: str,
    condition: str,
) -> None:
    """Append a Runtime IDE-style logical transition candidate without changing the default route."""
    edges = payload.setdefault("edges", [])
    assert isinstance(edges, list)
    edges.append(
        {
            "source": source,
            "target": target,
            "condition": condition,
            "label": f"candidate transition: {source} -> {target}",
            "metadata": {
                "runtime_edge": "logical_transition",
                "from_stage": source,
                "to_stage": target,
                "condition": condition,
                "transition_condition": condition,
                "default_transition": False,
                "auto_ports": True,
            },
        }
    )


def test_atr_graph_config_validates_and_compiles() -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    compiler = ATRLangGraphCompiler(config, _noop_registry())

    assert compiler.validate() == []
    assert config.stage_dispatch["bo"] == "bo"
    assert config.transitions["knowledge"] == "bo"
    assert config.transitions["bo"] == "guardian"
    assert config.nodes[0].position["x"] >= 0
    assert config.nodes[0].metadata["icon"]
    transition_edges = [edge for edge in config.edges if edge.metadata.get("runtime_edge") == "logical_transition"]
    assert any(edge.metadata.get("from_stage") == "knowledge" and edge.metadata.get("to_stage") == "bo" for edge in transition_edges)
    assert compiler.compile() is not None


def test_logical_transition_candidates_drive_runtime_next_stage() -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")

    guardian_candidates = config.transition_candidates("guardian")
    assert {candidate["to_stage"] for candidate in guardian_candidates} >= {"design", "complete", "error"}
    assert config.next_stage("guardian", guardian_decision="continue") == "design"
    assert config.next_stage("guardian", guardian_decision="stop") == "complete"
    assert config.next_stage("guardian", guardian_decision="error") == "error"

    payload = config.model_dump(mode="json")
    _add_graph_transition_candidate(payload, "design", "guardian", "next_stage:guardian")
    candidate_config = GraphConfig.model_validate(payload)
    assert candidate_config.next_stage("design") == "specimen"
    assert candidate_config.next_stage("design", state_metadata={"agent_result": {"next_stage": "guardian"}}) == "guardian"


def test_module_config_schema_validates_active_modules() -> None:
    module_paths = sorted(Path("graphs/modules").glob("*/module.yaml"))
    assert module_paths
    module_ids = set()
    for module_path in module_paths:
        config = load_module_config(module_path)
        module_ids.add(config.id)
        assert config.handler.startswith("agent.")
        assert config.safety.dry_run_supported is True
        assert config.internal_graph
        assert all(step.id for step in config.internal_graph)

    assert {"design", "specimen", "vision", "manipulation", "equipment", "analysis", "knowledge", "bo", "guardian"}.issubset(module_ids)
    design = load_module_config("graphs/modules/design/module.yaml")
    assert design.pre_execution[0].id == "orchestrator_plan"
    assert design.pre_execution[0].handler == "agent.orchestrator_agent"

    with pytest.raises(Exception):
        ModuleConfig.model_validate({"id": "", "handler": "agent.design_agent"})
    with pytest.raises(Exception):
        ModuleConfig.model_validate({"id": "bad", "handler": ""})
    with pytest.raises(Exception):
        ModuleConfig.model_validate({"id": "bad", "handler": "agent.design_agent", "tools": [""]})


def test_legacy_compatibility_helpers_derive_from_graph_and_module_config(tmp_path: Path) -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")

    assert ordered_stages[:3] == [Stage.DESIGN, Stage.SPECIMEN, Stage.VISION]
    assert Stage.BO in ordered_stages
    assert default_next_stage(Stage.KNOWLEDGE) == Stage.BO
    assert default_next_stage(Stage.BO) == Stage.GUARDIAN
    assert default_next_stage(Stage.GUARDIAN, guardian_decision="stop") == Stage.COMPLETE
    assert stage_to_agent(Stage.DESIGN) == "design_agent"

    payload = config.model_dump(mode="json")
    payload["transitions"]["design"] = "guardian"
    for node in payload["nodes"]:
        if node.get("stage") == "design":
            node["handler"] = "agent.guardian_agent"
            node["module_id"] = None
            break
    graph_path = tmp_path / "compat_graph.yaml"
    graph_path.write_text(yaml.safe_dump({"graph": payload}, sort_keys=False), encoding="utf-8")

    assert default_next_stage(Stage.DESIGN, graph_config_path=graph_path) == Stage.GUARDIAN
    assert OrchestrationGraph(graph_path).next_stage(Stage.DESIGN) == Stage.GUARDIAN
    assert stage_to_agent(Stage.DESIGN, graph_config_path=graph_path) == "guardian_agent"


def test_graph_validator_rejects_missing_handler_missing_edge_node_duplicate_and_unguarded_cycle() -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    registry = _noop_registry()

    bad_handler_payload = config.model_dump(mode="json")
    bad_handler_payload["nodes"][0]["handler"] = "runtime.not_registered"
    bad_handler = ATRLangGraphCompiler(GraphConfig.model_validate(bad_handler_payload), registry).validate()
    assert any("unregistered handler" in error for error in bad_handler)

    bad_edge_payload = config.model_dump(mode="json")
    bad_edge_payload["edges"].append({"source": "design", "target": "missing_node", "condition": None})
    bad_edge = ATRLangGraphCompiler(GraphConfig.model_validate(bad_edge_payload), registry).validate()
    assert "edge target is unknown: missing_node" in bad_edge

    duplicate_payload = config.model_dump(mode="json")
    duplicate_payload["nodes"].append(dict(duplicate_payload["nodes"][2]))
    duplicate = ATRLangGraphCompiler(GraphConfig.model_validate(duplicate_payload), registry).validate()
    assert "duplicate node id: design" in duplicate

    cycle_payload = config.model_dump(mode="json")
    cycle_payload["transitions"] = {"design": "specimen", "specimen": "design"}
    cycle = ATRLangGraphCompiler(GraphConfig.model_validate(cycle_payload), registry).validate()
    assert any("transition cycle without guardian/terminal" in error for error in cycle)

    orphan_payload = config.model_dump(mode="json")
    orphan_payload["nodes"].append(
        {
            "id": "orphan",
            "label": "Orphan",
            "handler": "runtime.terminal",
            "stage": None,
            "kind": "runtime",
            "position": {"x": 0, "y": 0},
            "metadata": {},
        }
    )
    orphan_errors = ATRLangGraphCompiler(GraphConfig.model_validate(orphan_payload), registry).validate()
    assert "node is disconnected from entry_node: orphan" in orphan_errors

    module_ids = {str(node.module_id).split("/")[-1] for node in config.nodes if node.module_id}
    bad_module_payload = config.model_dump(mode="json")
    bad_module_payload["nodes"][2]["module_id"] = "modules/missing_module"
    bad_module = ATRLangGraphCompiler(
        GraphConfig.model_validate(bad_module_payload),
        registry,
        module_ids=module_ids,
    ).validate()
    assert "node=design references unknown module=modules/missing_module" in bad_module

    unsafe_payload = config.model_dump(mode="json")
    unsafe_payload["stage_dispatch"].pop("guardian", None)
    unsafe = ATRLangGraphCompiler(GraphConfig.model_validate(unsafe_payload), registry).validate()
    assert "safety.guardian_required is true but guardian stage is not dispatchable" in unsafe

    stage_mismatch_payload = config.model_dump(mode="json")
    stage_mismatch_payload["stage_dispatch"]["design"] = "specimen"
    stage_mismatch = ATRLangGraphCompiler(GraphConfig.model_validate(stage_mismatch_payload), registry).validate()
    assert "stage_dispatch[design] points to node=specimen with stage=specimen" in stage_mismatch

    missing_dispatch_payload = config.model_dump(mode="json")
    missing_dispatch_payload["edges"] = [
        edge
        for edge in missing_dispatch_payload["edges"]
        if not (edge.get("source") == "dispatch" and edge.get("condition") == "design")
    ]
    missing_dispatch = ATRLangGraphCompiler(GraphConfig.model_validate(missing_dispatch_payload), registry).validate()
    assert "runtime.dispatch edge for stage=design must target node=design" in missing_dispatch

    missing_module_ref_payload = config.model_dump(mode="json")
    missing_module_ref_payload["nodes"][2]["module_id"] = None
    missing_module_ref = ATRLangGraphCompiler(GraphConfig.model_validate(missing_module_ref_payload), registry).validate()
    assert "agent node=design must reference module_id" in missing_module_ref

    bad_logical_payload = config.model_dump(mode="json")
    first_logical = next(edge for edge in bad_logical_payload["edges"] if edge.get("metadata", {}).get("runtime_edge") == "logical_transition")
    first_logical["metadata"]["from_stage"] = "missing_stage"
    bad_logical = ATRLangGraphCompiler(GraphConfig.model_validate(bad_logical_payload), registry).validate()
    assert "logical_transition[1] from_stage is not dispatchable or terminal: missing_stage" in bad_logical

    missing_stop_payload = config.model_dump(mode="json")
    missing_stop_payload["edges"] = [
        edge
        for edge in missing_stop_payload["edges"]
        if edge.get("metadata", {}).get("transition_condition") != "guardian_decision:stop"
    ]
    missing_stop = ATRLangGraphCompiler(GraphConfig.model_validate(missing_stop_payload), registry).validate()
    assert "safety.guardian_required is true but guardian stop route to terminal stage is missing" in missing_stop


def test_handler_registry_metadata_and_signature_validation() -> None:
    registry = HandlerRegistry()

    async def good_handler(runtime_state: dict[str, object]) -> dict[str, object]:
        return runtime_state

    def no_args_handler() -> dict[str, object]:
        return {}

    def too_many_required(first: dict[str, object], second: object) -> dict[str, object]:
        return first

    registry.register("runtime.good", good_handler)
    registry.register("runtime.bad_no_args", no_args_handler)
    registry.register("runtime.bad_too_many", too_many_required)

    good = registry.metadata("runtime.good")
    assert good["handler_id"] == "runtime.good"
    assert good["is_async"] is True
    assert good["accepts_runtime_state"] is True
    assert "runtime_state" in good["signature"]
    assert good["errors"] == []

    errors = registry.validation_errors({"runtime.good", "runtime.bad_no_args", "runtime.bad_too_many"})
    assert "handler must accept one runtime_state positional argument" in errors["runtime.bad_no_args"]
    assert any("too many required positional" in error for error in errors["runtime.bad_too_many"])
    assert "runtime.good" not in errors

    with pytest.raises(ValueError):
        registry.register("runtime.not_callable", object())  # type: ignore[arg-type]


def test_graph_validator_rejects_registered_handler_with_invalid_signature() -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    registry = _noop_registry()

    def invalid_handler() -> dict[str, object]:
        return {}

    registry.register("runtime.invalid_signature", invalid_handler)
    payload = config.model_dump(mode="json")
    payload["nodes"][0]["handler"] = "runtime.invalid_signature"
    errors = ATRLangGraphCompiler(GraphConfig.model_validate(payload), registry).validate()

    assert "handler=runtime.invalid_signature invalid runtime signature: handler must accept one runtime_state positional argument" in errors


def test_graph_runtime_api_exposes_validate_and_dry_run() -> None:
    client = TestClient(app_main.app)

    graphs = client.get("/api/graphs").json()
    assert graphs["ok"] is True
    assert graphs["active_graph_id"] == "atr_closed_loop"
    graph_ids = [item["id"] for item in graphs["graphs"]]
    assert graph_ids[0] == "atr_closed_loop"
    assert {"printer_pipeline", "lerobot_pick_place", "utm_test_flow"}.issubset(graph_ids)
    assert all("path" in item and "executable_from_runtime_ide" in item for item in graphs["graphs"])

    validation = client.post("/api/graphs/atr_closed_loop/validate").json()
    assert validation == {"ok": True, "graph_id": "atr_closed_loop", "errors": []}

    graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    cursor = _event_cursor()
    draft_validation = client.post(
        "/api/graphs/atr_closed_loop/validate-draft",
        json={"graph": graph, "reason": "unit-draft", "author": "pytest", "activate": False},
    ).json()
    assert draft_validation["ok"] is True
    assert draft_validation["compiled"] is True
    assert draft_validation["errors"] == []
    assert draft_validation["compiled_graph"]["entry_node"] == "dispatch"
    compiled_event = _assert_runtime_event_since(cursor, "graph.compiled", "validate-draft")
    assert compiled_event["payload"]["compiled_graph"]["entry_node"] == "dispatch"

    bad_graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    bad_graph["nodes"][0]["handler"] = "runtime.not_registered"
    cursor = _event_cursor()
    bad_draft = client.post(
        "/api/graphs/atr_closed_loop/validate-draft",
        json={"graph": bad_graph, "reason": "bad-draft", "author": "pytest", "activate": False},
    ).json()
    assert bad_draft["ok"] is False
    failed_event = _assert_runtime_event_since(cursor, "graph.validation_failed", "validate-draft")
    assert any("unregistered handler" in error for error in failed_event["payload"]["errors"])

    cursor = _event_cursor()
    dry_run = client.post("/api/graphs/atr_closed_loop/dry-run").json()
    assert dry_run["ok"] is True
    _assert_runtime_event_since(cursor, "graph.compiled", "dry-run")
    sequence = dry_run["sequence"]
    stages = [item["stage"] for item in sequence]
    assert stages[-3:] == ["knowledge", "bo", "guardian"]
    design_step = next(item for item in sequence if item["stage"] == "design")
    assert design_step["graph_handler"] == "agent.design_agent"
    assert design_step["module_id"] == "design"
    assert design_step["module_handler"] == "agent.design_agent"
    assert design_step["effective_handler"] == "agent.design_agent"
    assert design_step["module_runtime"]["pre_execution_count"] == 1
    assert design_step["module_runtime"]["internal_graph_count"] >= 1
    specimen_step = next(item for item in sequence if item["stage"] == "specimen")
    assert specimen_step["module_runtime"]["tool_count"] >= 1

    replay_dry_run = client.post("/api/graphs/atr_closed_loop/dry-run", json={"start_stage": "analysis", "max_steps": 4}).json()
    assert replay_dry_run["ok"] is True
    assert replay_dry_run["start_stage"] == "analysis"
    assert [item["stage"] for item in replay_dry_run["sequence"]] == ["analysis", "knowledge", "bo", "guardian"]
    draft_dry_run = client.post(
        "/api/graphs/atr_closed_loop/dry-run",
        json={"graph": graph, "start_stage": "design", "max_steps": 3},
    ).json()
    assert draft_dry_run["ok"] is True
    assert draft_dry_run["draft"] is True
    assert draft_dry_run["dry_run_record"]["live_gate_recorded"] is False
    assert [item["stage"] for item in draft_dry_run["sequence"]] == ["design", "specimen", "vision"]

    cursor = _event_cursor()
    printer_compile = client.post("/api/graphs/printer_pipeline/compile").json()
    assert printer_compile["ok"] is True
    assert printer_compile["compiled_graph"]["transitions"]["idle"] == "specimen"
    _assert_runtime_event_since(cursor, "graph.compiled", "compile")

    printer_dry_run = client.post("/api/graphs/printer_pipeline/dry-run").json()
    assert printer_dry_run["ok"] is True
    assert [item["stage"] for item in printer_dry_run["sequence"]] == ["idle", "specimen"]

    lerobot_dry_run = client.post("/api/graphs/lerobot_pick_place/dry-run").json()
    assert lerobot_dry_run["ok"] is True
    assert [item["stage"] for item in lerobot_dry_run["sequence"]] == ["idle", "vision", "manipulation"]

    utm_dry_run = client.post("/api/graphs/utm_test_flow/dry-run").json()
    assert utm_dry_run["ok"] is True
    assert [item["stage"] for item in utm_dry_run["sequence"]] == ["idle", "equipment", "analysis", "knowledge"]


def test_graph_runtime_api_exposes_handlers_modules_and_compile() -> None:
    client = TestClient(app_main.app)

    handlers = client.get("/api/handlers").json()
    assert handlers["ok"] is True
    assert "agent.design_agent" in handlers["handlers"]
    assert "runtime.dispatch" in handlers["handlers"]
    handler_metadata = {item["handler_id"]: item for item in handlers["handler_metadata"]}
    assert set(handlers["handlers"]).issubset(handler_metadata)
    assert handler_metadata["runtime.dispatch"]["accepts_runtime_state"] is True
    assert handler_metadata["runtime.dispatch"]["errors"] == []
    assert "runtime_state" in handler_metadata["runtime.dispatch"]["signature"]

    tools = client.get("/api/tools").json()
    assert tools["ok"] is True
    assert tools["count"] == len(tools["tools"])
    assert "geometry.generate_metamaterial_stl" in tools["tools"]

    modules = client.get("/api/modules").json()
    assert modules["ok"] is True
    module_ids = {item["id"] for item in modules["modules"]}
    assert {"design", "specimen", "bo", "guardian"}.issubset(module_ids)

    design = client.get("/api/modules/design").json()
    assert design["ok"] is True
    assert design["module"]["module"]["handler"] == "agent.design_agent"
    assert design["module"]["module"]["internal_graph"]

    load_result = client.post("/api/modules/design/load").json()
    assert load_result["ok"] is True
    assert load_result["loaded"] is True
    assert "design" in load_result["loaded_module_ids"]
    state_result = client.get("/api/modules/management-state").json()
    assert "design" in state_result["loaded_module_ids"]
    unload_result = client.post("/api/modules/design/unload").json()
    assert unload_result["ok"] is True
    assert unload_result["loaded"] is False
    assert "design" not in unload_result["loaded_module_ids"]

    compiled = client.post("/api/graphs/atr_closed_loop/compile").json()
    assert compiled["ok"] is True
    assert compiled["compiled"] is True
    assert compiled["errors"] == []
    assert compiled["compiled_graph"]["transitions"]["knowledge"] == "bo"
    assert compiled["compiled_graph"]["logical_edge_count"] >= 1
    dispatch_node = next(node for node in compiled["compiled_graph"]["nodes"] if node["id"] == "dispatch")
    assert dispatch_node["handler_signature"]
    assert dispatch_node["handler_accepts_runtime_state"] is True

    module_validation = client.post("/api/modules/design/validate").json()
    assert module_validation == {"ok": True, "module_id": "design", "errors": []}

    module_dry_run = client.post("/api/modules/design/dry-run").json()
    assert module_dry_run["ok"] is True
    assert module_dry_run["sequence"][0]["id"] == "orchestrator_plan"
    assert module_dry_run["sequence"][0]["phase"] == "pre_execution"
    assert module_dry_run["sequence"][0]["executable"] is True
    assert [item["id"] for item in module_dry_run["sequence"][1:3]] == [
        "01_intake_constraints",
        "02_generate_candidate_spec",
    ]
    assert module_dry_run["sequence"][1]["handler_configured"] is False
    assert module_dry_run["sequence"][1]["executable"] is False
    assert module_dry_run["summary"]["step_count"] == len(module_dry_run["sequence"])
    assert module_dry_run["summary"]["pre_execution_count"] == 1
    assert module_dry_run["summary"]["internal_graph_count"] >= 1
    assert module_dry_run["summary"]["executable_count"] >= 1
    assert module_dry_run["summary"]["ordered_step_ids"][0] == "orchestrator_plan"

    saved_module = client.put(
        "/api/modules/design",
        json={"module": design["module"], "reason": "unit-version-detail", "author": "pytest", "activate": False},
    ).json()
    assert saved_module["ok"] is True
    assert saved_module["dry_run"]["ok"] is True
    assert saved_module["dry_run"]["summary"]["pre_execution_count"] == 1
    assert saved_module["dry_run"]["summary"]["internal_graph_count"] >= 1
    assert saved_module["dry_run"]["summary"]["ordered_step_ids"][0] == "orchestrator_plan"
    module_versions = client.get("/api/modules/design/versions").json()
    assert module_versions["ok"] is True
    assert any(item["version_id"] == saved_module["version"]["version_id"] for item in module_versions["versions"])
    module_version = client.get(f"/api/modules/design/versions/{saved_module['version']['version_id']}").json()
    assert module_version["ok"] is True
    assert module_version["version"]["module"]["module"]["id"] == "design"
    missing_graph_version = client.get("/api/graphs/atr_closed_loop/versions/not-a-real-version")
    assert missing_graph_version.status_code == 404


def test_graph_runtime_api_exports_and_imports_yaml_drafts() -> None:
    client = TestClient(app_main.app)
    graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]

    exported = client.post(
        "/api/graphs/atr_closed_loop/export-yaml",
        json={"graph": graph, "reason": "unit-export", "author": "pytest", "activate": False},
    )

    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/x-yaml")
    assert "graph:" in exported.text
    assert "atr_closed_loop" in exported.text

    cursor = _event_cursor()
    imported = client.post("/api/graphs/atr_closed_loop/import-yaml", json={"yaml_text": exported.text}).json()
    assert imported["ok"] is True
    assert imported["compiled"] is True
    assert imported["graph"]["id"] == "atr_closed_loop"
    assert imported["graph"]["nodes"][0]["position"]
    _assert_runtime_event_since(cursor, "graph.compiled", "import-yaml")

    cursor = _event_cursor()
    invalid = client.post("/api/graphs/atr_closed_loop/import-yaml", json={"yaml_text": "- not-an-object"}).json()
    assert invalid["ok"] is False
    assert invalid["errors"] == ["YAML root must be an object"]
    _assert_runtime_event_since(cursor, "graph.validation_failed", "import-yaml")


def test_runtime_run_artifact_event_compatibility_api_exposes_current_run() -> None:
    client = TestClient(app_main.app)
    snapshot = client.get("/api/state").json()
    resources = snapshot["system_resources"]
    assert "ram" in resources
    assert "gpu" in resources
    assert "status" in resources["ram"]
    assert "status" in resources["gpu"]
    run_id = snapshot["state"]["run_id"]

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["ok"] is True
    assert run["run_id"] == run_id
    assert run["active"] is True

    events = client.get(f"/api/runs/{run_id}/events").json()
    assert events["ok"] is True
    assert events["run_id"] == run_id
    assert isinstance(events["events"], list)

    approval = client.post(
        f"/api/runs/{run_id}/approvals",
        json={"title": "Unit approval", "reason": "test gate", "stage": "guardian", "safety_class": "unit"},
    ).json()
    assert approval["ok"] is True
    approval_id = approval["approval_id"]
    assert approval["pending"][0]["approval_id"] == approval_id

    listed = client.get(f"/api/runs/{run_id}/approvals").json()
    assert listed["ok"] is True
    assert any(item["approval_id"] == approval_id for item in listed["pending"])

    app_main.controller._state.run_metadata["runtime_approvals"] = {
        "unit-gate": {"approval_id": approval_id, "status": "pending", "stage": "guardian"}
    }
    app_main.controller._state.run_metadata["approval_blocked_stage"] = {"approval_id": approval_id}
    app_main.controller._state.is_paused = True
    resolved = client.post(
        f"/api/runs/{run_id}/approvals/{approval_id}/resolve",
        json={"decision": "approved", "operator": "pytest", "note": "unit pass"},
    ).json()
    assert resolved["ok"] is True
    assert not any(item["approval_id"] == approval_id for item in resolved["pending"])
    assert any(item["approval_id"] == approval_id and item["decision"] == "approved" for item in resolved["resolved"])
    assert app_main.controller._state.run_metadata["runtime_approvals"]["unit-gate"]["status"] == "approved"
    assert app_main.controller._state.is_paused is False
    app_main.controller._state.run_metadata.pop("runtime_approvals", None)

    run_dir = Path(str(run["run_dir"]))
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_file = run_dir / "runtime_ide_preview_test.txt"
    artifact_file.write_text("artifact preview body", encoding="utf-8")
    try:
        artifacts = client.get(f"/api/runs/{run_id}/artifacts").json()
        assert artifacts["ok"] is True
        assert artifacts["run_id"] == run_id
        assert isinstance(artifacts["artifacts"], list)
        artifact = next(item for item in artifacts["artifacts"] if item["path"] == "runtime_ide_preview_test.txt")
        assert artifact["preview_kind"] == "text"
        assert artifact["previewable"] is True
        assert artifact["url"].endswith("/runtime_ide_preview_test.txt")
        assert artifact["download_url"].endswith("/runtime_ide_preview_test.txt?download=1")

        preview = client.get(str(artifact["url"]))
        assert preview.status_code == 200
        assert preview.text == "artifact preview body"

        download = client.get(str(artifact["download_url"]))
        assert download.status_code == 200
        assert "attachment" in download.headers.get("content-disposition", "")
    finally:
        artifact_file.unlink(missing_ok=True)


def test_graph_run_endpoint_compile_checks_then_delegates_controller_start(monkeypatch) -> None:
    async def _fake_start(**kwargs: object) -> dict[str, object]:
        return {"ok": True, "message": "fake started", "run_id": "run-fake", "received": kwargs}

    monkeypatch.setattr(app_main.controller, "start", _fake_start)
    app_main._RUNTIME_GRAPH_DRY_RUN_RECORDS.clear()
    client = TestClient(app_main.app)

    cursor = _event_cursor()
    result = client.post("/api/graphs/atr_closed_loop/run", json={"mode": "test", "goal": "unit graph run"}).json()

    assert result["ok"] is True
    _assert_runtime_event_since(cursor, "graph.compiled", "run")
    assert result["graph_id"] == "atr_closed_loop"
    assert result["errors"] == []
    assert result["run"]["run_id"] == "run-fake"
    assert result["run"]["received"]["mode"] == "test"
    assert result["run"]["received"]["graph_id"] == "atr_closed_loop"
    assert str(result["run"]["received"]["graph_config_path"]).endswith("graphs/configs/atr_closed_loop.yaml")

    live_without_dry_run = client.post("/api/graphs/atr_closed_loop/run", json={"mode": "live", "goal": "unit live gate"})
    assert live_without_dry_run.status_code == 409
    assert live_without_dry_run.json()["detail"]["code"] == "GRAPH_DRY_RUN_REQUIRED"
    gate_before = client.get("/api/graphs/atr_closed_loop/dry-run-gate").json()
    assert gate_before["ok"] is True
    assert gate_before["gate_ok"] is False
    assert gate_before["has_record"] is False

    dry_run = client.post("/api/graphs/atr_closed_loop/dry-run").json()
    assert dry_run["ok"] is True
    assert dry_run["dry_run_record"]["graph_id"] == "atr_closed_loop"
    assert dry_run["dry_run_record"]["digest"]
    assert dry_run["dry_run_record"]["live_gate_recorded"] is True

    gate_after = client.get("/api/graphs/atr_closed_loop/dry-run-gate").json()
    assert gate_after["gate_ok"] is True
    assert gate_after["dry_run_record"]["digest"] == dry_run["dry_run_record"]["digest"]

    live_result = client.post("/api/graphs/atr_closed_loop/run", json={"mode": "live", "goal": "unit live after dry run"}).json()
    assert live_result["ok"] is True
    assert live_result["run"]["received"]["mode"] == "live"
    assert live_result["dry_run_record"]["digest"] == dry_run["dry_run_record"]["digest"]

    app_main._RUNTIME_GRAPH_DRY_RUN_RECORDS.clear()
    legacy_live_without_dry_run = client.post("/api/run/start", json={"mode": "live", "goal": "legacy live gate"})
    assert legacy_live_without_dry_run.status_code == 409
    client.post("/api/graphs/atr_closed_loop/dry-run")
    legacy_live_result = client.post("/api/run/start", json={"mode": "live", "goal": "legacy live after dry run"}).json()
    assert legacy_live_result["ok"] is True
    assert legacy_live_result["received"]["mode"] == "live"

    template_result = client.post("/api/graphs/printer_pipeline/run", json={"mode": "test", "goal": "unit template run"}).json()
    assert template_result["ok"] is True
    assert template_result["graph_id"] == "printer_pipeline"
    assert template_result["run"]["received"]["graph_id"] == "printer_pipeline"
    assert str(template_result["run"]["received"]["graph_config_path"]).endswith("graphs/configs/printer_pipeline.yaml")

    template_live = client.post("/api/graphs/printer_pipeline/run", json={"mode": "live", "goal": "unit template live"})
    assert template_live.status_code == 400
    assert "live run is disabled" in template_live.json()["detail"]


def test_graph_runtime_api_saves_version_without_activating(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_main, "RUNTIME_GRAPH_VERSION_ROOT", tmp_path / "graph_versions")
    client = TestClient(app_main.app)
    graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]

    cursor = _event_cursor()
    saved = client.put(
        "/api/graphs/atr_closed_loop",
        json={"graph": graph, "reason": "unit-test", "author": "pytest", "activate": False},
    ).json()

    assert saved["ok"] is True
    _assert_runtime_event_since(cursor, "graph.compiled", "save")
    assert saved["activated"] is False
    assert saved["dry_run"]["ok"] is True
    assert saved["dry_run"]["dry_run_record"]["live_gate_recorded"] is False
    assert saved["dry_run"]["dry_run_record"]["digest"]
    assert saved["dry_run"]["dry_run_record"] == saved["dry_run_record"]
    assert [item["stage"] for item in saved["dry_run"]["sequence"][:3]] == ["idle", "design", "specimen"]
    version = saved["version"]
    assert version["reason"] == "unit-test"
    assert (tmp_path / "graph_versions" / "atr_closed_loop" / f"{version['version_id']}.yaml").exists()

    versions = client.get("/api/graphs/atr_closed_loop/versions").json()
    assert versions["ok"] is True
    assert versions["versions"][0]["version_id"] == version["version_id"]

    printer_graph = client.get("/api/graphs/printer_pipeline").json()["graph"]
    printer_saved = client.put(
        "/api/graphs/printer_pipeline",
        json={"graph": printer_graph, "reason": "unit-template-test", "author": "pytest", "activate": False},
    ).json()
    assert printer_saved["ok"] is True
    assert (tmp_path / "graph_versions" / "printer_pipeline" / f"{printer_saved['version']['version_id']}.yaml").exists()


def test_activated_graph_version_becomes_saved_run_target(tmp_path, monkeypatch) -> None:
    config_root = tmp_path / "graph_configs"
    config_root.mkdir()
    active_graph_path = config_root / "atr_closed_loop.yaml"
    active_graph_path.write_text(Path("graphs/configs/atr_closed_loop.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(app_main, "RUNTIME_GRAPH_CONFIG_ROOT", config_root)
    monkeypatch.setattr(app_main, "RUNTIME_GRAPH_VERSION_ROOT", tmp_path / "graph_versions")
    app_main._RUNTIME_GRAPH_DRY_RUN_RECORDS.clear()

    async def _fake_start(**kwargs: object) -> dict[str, object]:
        return {"ok": True, "message": "fake active graph started", "run_id": "run-active-graph", "received": kwargs}

    monkeypatch.setattr(app_main.controller, "start", _fake_start)
    client = TestClient(app_main.app)
    graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    _set_graph_default_transition(graph, "design", "guardian")

    cursor = _event_cursor()
    saved = client.put(
        "/api/graphs/atr_closed_loop",
        json={"graph": graph, "reason": "activate-design-to-guardian", "author": "pytest", "activate": True},
    ).json()

    assert saved["ok"] is True
    assert saved["activated"] is True
    assert saved["compiled_graph"]["transitions"]["design"] == "guardian"
    assert saved["dry_run"]["dry_run_record"]["live_gate_recorded"] is True
    assert [item["stage"] for item in saved["dry_run"]["sequence"][:3]] == ["idle", "design", "guardian"]
    _assert_runtime_event_since(cursor, "graph.compiled", "save")

    active = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    assert active["transitions"]["design"] == "guardian"
    assert "design: guardian" in active_graph_path.read_text(encoding="utf-8")

    gate = client.get("/api/graphs/atr_closed_loop/dry-run-gate").json()
    assert gate["gate_ok"] is True
    assert gate["dry_run_record"]["digest"] == saved["dry_run_record"]["digest"]

    dry_run = client.post("/api/graphs/atr_closed_loop/dry-run", json={"max_steps": 5}).json()
    assert dry_run["ok"] is True
    assert dry_run["compiled_graph"]["transitions"]["design"] == "guardian"
    assert [item["stage"] for item in dry_run["sequence"][:3]] == ["idle", "design", "guardian"]

    run = client.post("/api/graphs/atr_closed_loop/run", json={"mode": "live", "goal": "active config route"}).json()
    assert run["ok"] is True
    assert run["compiled_graph"]["transitions"]["design"] == "guardian"
    assert run["dry_run_record"]["digest"] == dry_run["dry_run_record"]["digest"]
    assert run["run"]["received"]["graph_config_path"] == str(active_graph_path)
    assert run["run"]["received"]["mode"] == "live"


def test_module_runtime_api_saves_version_without_activating(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_main, "RUNTIME_MODULE_VERSION_ROOT", tmp_path / "module_versions")
    client = TestClient(app_main.app)
    module = client.get("/api/modules/design").json()["module"]

    saved = client.put(
        "/api/modules/design",
        json={"module": module, "reason": "unit-module-test", "author": "pytest", "activate": False},
    ).json()

    assert saved["ok"] is True
    assert saved["activated"] is False
    assert saved["dry_run"]["ok"] is True
    assert saved["dry_run"]["summary"]["step_count"] == len(saved["dry_run"]["sequence"])
    assert saved["dry_run"]["summary"]["first_step_id"] == "orchestrator_plan"
    version = saved["version"]
    assert version["reason"] == "unit-module-test"
    assert (tmp_path / "module_versions" / "design" / f"{version['version_id']}.yaml").exists()

    versions = client.get("/api/modules/design/versions").json()
    assert versions["ok"] is True
    assert versions["versions"][0]["version_id"] == version["version_id"]


def test_activated_module_version_changes_runtime_handler(tmp_path, monkeypatch) -> None:
    graph_root = tmp_path / "graphs"
    config_root = graph_root / "configs"
    module_root = graph_root / "modules"
    config_root.mkdir(parents=True)
    (config_root / "atr_closed_loop.yaml").write_text(Path("graphs/configs/atr_closed_loop.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(Path("graphs/modules"), module_root)
    monkeypatch.setattr(app_main, "RUNTIME_MODULE_ROOT", module_root)
    monkeypatch.setattr(app_main, "RUNTIME_MODULE_VERSION_ROOT", tmp_path / "module_versions")

    client = TestClient(app_main.app)
    module = client.get("/api/modules/design").json()["module"]
    module["module"]["handler"] = "agent.guardian_agent"

    saved = client.put(
        "/api/modules/design",
        json={"module": module, "reason": "activate-handler-override", "author": "pytest", "activate": True},
    ).json()

    assert saved["ok"] is True
    assert saved["activated"] is True
    assert saved["dry_run"]["summary"]["internal_graph_count"] == 4
    active = client.get("/api/modules/design").json()["module"]
    assert active["module"]["handler"] == "agent.guardian_agent"
    assert "agent.guardian_agent" in (module_root / "design" / "module.yaml").read_text(encoding="utf-8")

    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {"plan_text": "module api plan"})
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "wrong-module"}})
    guardian = _StaticAgent("guardian_agent", {"experiment_spec": {"specimen_id": "active-module-handler"}})
    registry.register(orchestrator)
    registry.register(design)
    registry.register(guardian)
    bundle = build_logger_bundle(run_id="run-module-api-active", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-module-api-active",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path=config_root / "atr_closed_loop.yaml",
        module_root=graph_root,
        on_event=events.append,
    )

    asyncio.run(loop.step())

    assert orchestrator.run_count == 1
    assert design.run_count == 0
    assert guardian.run_count == 1
    assert state.current_experiment_spec == {"specimen_id": "active-module-handler"}
    started = [event for event in events if event["type"] == "node.started" and event["node_id"] == "design"]
    assert started[-1]["agent"] == "guardian_agent"
    assert started[-1]["payload"]["module_runtime"]["effective_handler"] == "agent.guardian_agent"


def test_module_runtime_api_rejects_unregistered_handler(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_main, "RUNTIME_MODULE_VERSION_ROOT", tmp_path / "module_versions")
    client = TestClient(app_main.app)
    module = client.get("/api/modules/design").json()["module"]
    module["module"]["handler"] = "agent.not_registered"

    saved = client.put(
        "/api/modules/design",
        json={"module": module, "reason": "bad-handler", "author": "pytest", "activate": False},
    ).json()

    assert saved["ok"] is False
    assert saved["errors"] == ["unregistered handler: agent.not_registered"]
    assert saved["dry_run"]["ok"] is False
    assert saved["dry_run"]["summary"]["step_count"] == 0


def test_module_runtime_api_validates_llm_prompt_tool_safety_config() -> None:
    client = TestClient(app_main.app)
    module = client.get("/api/modules/design").json()["module"]
    module["module"].update(
        {
            "llm_role": "design_reasoning",
            "llm": {"backend": "vllm", "model": "gemma4:e4b-it-nvfp4", "temperature": 0.2, "max_tokens": 1024},
            "prompt": {"path": "docs/runtime/design_prompt.md", "system": "Generate printable TPMS specimens."},
            "tools": ["experiment.evaluate", "geometry.generate_metamaterial_stl"],
            "timeout_s": 120,
            "retry": {"max_attempts": 2, "backoff_s": 1.5},
            "safety": {"live_requires_validation": True, "dry_run_supported": True, "requires_human_approval": False},
        }
    )
    module["module"]["internal_graph"][0]["handler"] = "agent.design_agent"

    valid = client.post(
        "/api/modules/design/validate",
        json={"module": module, "reason": "valid-config", "author": "pytest", "activate": False},
    ).json()
    assert valid == {"ok": True, "module_id": "design", "errors": []}

    bad = client.get("/api/modules/design").json()["module"]
    bad["module"].update(
        {
            "llm": {"backend": 7, "max_tokens": 0},
            "prompt": {"path": 12},
            "tools": ["experiment.evaluate", "", "missing.tool"],
            "timeout_s": -1,
            "retry": {"max_attempts": 99},
            "safety": {"live_requires_validation": "yes"},
        }
    )
    bad["module"]["internal_graph"][0]["handler"] = "agent.not_registered"

    invalid = client.post(
        "/api/modules/design/validate",
        json={"module": bad, "reason": "invalid-config", "author": "pytest", "activate": False},
    ).json()
    assert invalid["ok"] is False
    assert "llm.backend must be a string" in invalid["errors"]
    assert "llm.max_tokens must be a positive integer" in invalid["errors"]
    assert "prompt.path must be a string" in invalid["errors"]
    assert "tools[2] must be a non-empty string" in invalid["errors"]
    assert "unregistered tool: missing.tool" in invalid["errors"]
    assert "timeout_s must be a non-negative number" in invalid["errors"]
    assert "retry.max_attempts must be an integer between 0 and 10" in invalid["errors"]
    assert "safety.live_requires_validation must be boolean" in invalid["errors"]
    assert "unregistered internal_graph step handler at 1: agent.not_registered" in invalid["errors"]


def test_runtime_ide_page_and_main_entry_render() -> None:
    client = TestClient(app_main.app)

    home = client.get("/")
    assert home.status_code == 200
    assert "Open Runtime IDE" in home.text

    ide = client.get("/ide")
    assert ide.status_code == 200
    assert "ATR Runtime IDE" in ide.text
    assert "/static/runtime_ide.js" in ide.text
    assert "runtime_ide.js?v=atr-ui-20260526-83" in ide.text
    assert "ide-run-status" in ide.text
    assert "ide-run-id" in ide.text
    assert "ide-active-agent" in ide.text
    assert "ide-current-stage" in ide.text
    assert "ide-node-search" in ide.text
    assert "ide-node-list" in ide.text
    assert "ide-infra-list" in ide.text
    assert "ide-template-list" in ide.text
    assert "Modules" in ide.text
    assert "runtime_ide.css?v=atr-ui-20260526-84" in ide.text
    assert "ide-module-management-open-btn" in ide.text
    assert "data-open-module-management" in ide.text
    assert "Open Module Management Tool" in ide.text
    assert "ide-agent-status" in ide.text
    assert "ide-device-status" in ide.text
    assert "ide-metrics-panel" in ide.text
    assert "ide-approval-queue" in ide.text
    assert "Approvals" in ide.text
    assert "ide-pause-run-btn" in ide.text
    assert "ide-resume-run-btn" in ide.text
    assert "ide-stop-run-btn" in ide.text
    assert "ide-node-inspector" in ide.text
    assert "ide-transition-source" in ide.text
    assert "ide-transition-target" in ide.text
    assert "ide-transition-condition-preset" in ide.text
    assert "ide-transition-condition" in ide.text
    assert "ide-edge-route-preview" in ide.text
    assert "Request next stage" in ide.text
    assert "ide-edge-connect-btn" in ide.text
    assert "ide-edge-delete-btn" in ide.text
    assert "ide-live-status" in ide.text
    assert "ide-runtime-readiness" in ide.text
    assert "Readiness" in ide.text
    assert "ide-minimap" in ide.text
    assert "ide-zoom-in-btn" in ide.text
    assert "ide-fit-graph-btn" in ide.text
    assert "ide-draft-safety-strip" in ide.text
    assert "ide-run-launcher-drawer" in ide.text
    assert "ide-run-target-summary" in ide.text
    assert "Run saved test graph" in ide.text
    assert "Run saved live graph" in ide.text
    assert "runtime-draft-safety-strip" in ide.text
    assert "ide-canvas-view-hint" in ide.text
    assert "ide-export-yaml-btn" in ide.text
    assert "ide-import-yaml-btn" in ide.text
    assert "ide-yaml-import-file" in ide.text
    assert "ide-live-preflight" in ide.text
    assert "ide-run-timeline" in ide.text
    assert "ide-event-detail" in ide.text
    assert "Event Detail" in ide.text
    assert "runtime-ide-runtime-detail-grid" in ide.text
    assert "ide-artifact-lineage" in ide.text
    assert "ide-artifact-preview" in ide.text
    assert "ide-replay-output" in ide.text
    assert "Event Log" in ide.text
    assert "data-event-filter=\"all\"" in ide.text
    assert "data-event-filter=\"warn\"" in ide.text
    assert "ide-module-graph" in ide.text
    assert "Module Runtime Steps" in ide.text

    management = client.get("/module-management")
    assert management.status_code == 200
    assert "Module Management Tool" in management.text
    assert "mm-load-btn" in management.text
    assert "mm-unload-btn" in management.text
    assert "mm-config-summary" in management.text
    assert "mm-config-steps" in management.text
    assert "mm-config-json" in management.text
    assert "mm-versions-btn" in management.text
    assert "mm-version-output" in management.text
    assert "mm-dry-run-evidence" in management.text
    assert "Dry-run Evidence" in management.text
    assert "Module Version History" in management.text
    assert "mm-register-generated-btn" in management.text
    assert "Register Generated" in management.text
    assert "Module Configuration Workspace" in management.text
    assert "module-management-config-nav" in management.text
    assert "data-mm-config-jump" in management.text
    assert "edit config below, then validate/dry-run before Save Version" in management.text
    assert "/static/module_management.js" in management.text
    assert "module_management.js?v=atr-ui-20260526-82" in management.text

    js = Path("web/static/runtime_ide.js").read_text(encoding="utf-8")
    module_js = Path("web/static/module_management.js").read_text(encoding="utf-8")
    css = Path("web/static/runtime_ide.css").read_text(encoding="utf-8")
    planning_js = Path("web/static/planning.js").read_text(encoding="utf-8")
    browser_audit = Path("tests/ui/runtime_ide_browser_audit.py").read_text(encoding="utf-8")
    planning_browser_audit = Path("tests/ui/planning_browser_audit.py").read_text(encoding="utf-8")
    module_management_browser_audit = Path("tests/ui/module_management_browser_audit.py").read_text(encoding="utf-8")
    assert "GRAPH_GRID = 16" in js
    assert "beginNodeDrag" in js
    assert "handleGraphNodeClick" in js
    assert "toggleEdgeConnectMode" in js
    assert "deleteSelectedEdge" in js
    assert "expandedNodeElementFromPoint" in js
    assert "highlightEdgeDragTarget" in js
    assert "connect-target" in js
    assert "handleRuntimeIdeKeydown" in js
    assert "transitionConditionSpec" in js
    assert "conditionPresetFromCondition" in js
    assert "setTransitionConditionControls" in js
    assert "renderEdgeRoutePreview" in js
    assert "routeConditionExplanation" in js
    assert "defaultTargetAlreadyRepresented" in js
    assert "simpleDefaultLabel" in js
    assert "runtime-ide-node-route-count" in js
    assert "next_stage:${targetStage}" in js
    assert "next_stage:${stage}" in js
    assert "renderMiniMap" in js
    assert "fitGraphToCanvas" in js
    assert "graphViewportCoverage" in js
    assert "graphRouteDiff" in js
    assert "routeDiffMarkup" in js
    assert "baselineGraph" in js
    assert "Draft route changes" in js
    assert "renderModuleGraph" in js
    assert "normalizeGraphTabId" in js
    assert "runtimeIdeStateSnapshot" in js
    assert "selectedNodeExists" in js
    assert "nodes.some((node) => node.id === selectedNodeId)" in js
    assert "syncRuntimeIdeState" in js
    assert "window.atrRuntimeIdeState" in js
    assert "graphTabsOutput.dataset.activeGraphTab" in js
    assert "data-tab-active" in js
    assert "aria-selected" in js
    assert 'role="tab"' in js
    assert 'clean === "main"' in js
    assert "`${MODULE_TAB_PREFIX}${clean}`" in js
    assert "runtime-module-tab-copy" in js
    assert "runtime-module-agent-title" in js
    assert "compactBoParamValue" in planning_js
    assert "renderBoTraceSvg" in planning_js
    assert "renderBoCollapsedBody" in planning_js
    assert "bo-graph-toggle" in planning_js
    assert "renderBoResultCard(msg, `chat-${messageIndex}`)" in planning_js
    assert "renderFemContourCard(msg)" in planning_js
    assert "BO Surrogate / Acquisition Trace" in planning_js
    assert "FEM / CAE Contour" in planning_js
    assert "planning_browser_audit_live_artifacts.png" in planning_browser_audit
    assert "boSvgCount" in planning_browser_audit
    assert "fem-contour-preview" in planning_browser_audit
    assert "module_management_browser_audit.png" in module_management_browser_audit
    assert "registerGeneratedSelected" in module_js
    assert "/register-generated" in module_js
    assert "generated_adapter_approved" in module_js
    assert "Module Designer controls missing" in module_management_browser_audit
    assert "runtime.step_complete missing from designer handler options" in module_management_browser_audit
    assert "dry-run action did not report OK" in module_management_browser_audit
    assert "openModuleManagementTool" in js
    assert "window.open(\"/module-management\", \"_blank\")" in js
    assert "[data-open-module-management]" in js
    assert "Pre-Execution" in js
    assert "moduleStepsForPhase" in js
    assert "updateModuleStepField" in js
    assert "Cross-phase drag is disabled" in js
    assert "data-module-step-field" in js
    assert "pre_execution" in js
    assert "reorderModuleStep" in js
    assert "exportGraphYaml" in js
    assert "importGraphYamlFile" in js
    assert "updateModuleHandler" in js
    assert "updateModuleStepHandler" in js
    assert "updateModuleConfigFromForm" in js
    assert "ide-module-tools" in js
    assert "ide-module-llm-backend" in js
    assert "ide-module-prompt-system" in js
    assert "renderRuntimeHeader" in js
    assert "systemResources" in js
    assert "resourceMetricLevel" in js
    assert "Host RAM" in js
    assert "GPU / VRAM" in js
    assert 'metricCard("VRAM"' in js
    assert "renderGraphExplorer" in js
    assert "renderInfraList" in js
    assert "renderAgentStatusPanel" in js
    assert "renderDeviceStatusPanel" in js
    assert "renderMetricsPanel" in js
    assert "renderApprovalQueue" in js
    assert "renderDashboardPanels" in js
    assert "renderRuntimeReadinessPanel" in js
    assert "refreshRuntimeReadinessViews" in js
    assert "runtimeReadinessHandlerCard" in js
    assert "runtimeReadinessModuleCard" in js
    assert "runtimeReadinessStatus" in js
    assert "moduleDraftReady" in js
    assert "modulePreflight" in js
    assert "modulePayloadForGraphDraft(draft)" in js
    assert "setModulePreflightEvidence" in js
    assert "markModulePreflightDirty" in js
    assert "renderRuntimeReadinessPanel();" in js
    assert "!status.moduleTab && !status.preflight.gateOk" in js
    assert "module draft only" in js
    assert "save-module" in js
    assert "Validate Module" in js
    assert "Dry Run Module" in js
    assert "entryStages" in js
    assert "needsIncoming" in js
    assert "needsOutgoing" in js
    assert "finishNode ? [finishNode.id] : []" in js
    assert "terminal_stages: finishNode ? [finishNode.stage] : []" in js
    assert "runtimeReadinessNodeIssueMap" in js
    assert "runtimeReadinessIssueLabel" in js
    assert "executeRuntimeReadinessAction" in js
    assert "focusRuntimeReadinessIssue" in js
    assert "focusTransitionEditorForNode" in js
    assert "routeRepairTargetForStage" in js
    assert "transitionTargetOptionExists" in js
    assert "focusModuleManagementEntryForNode" in js
    assert "data-readiness-kind" in js
    assert "data-readiness-node" in js
    assert "renderSelectedEventDetail" in js
    assert "nodeRouteAuditMarkup" in js
    assert "nodeRuntimeRecoveryMarkup" in js
    assert "nodeRecoveryStatus" in js
    assert "bindNodeRecoveryActions" in js
    assert "Runtime Recovery" in js
    assert "data-node-recovery-action" in js
    assert "bindNodeRouteAuditActions" in js
    assert "Runtime Routes" in js
    assert "effectiveMakeDefault" in js
    assert "already targets" in js
    assert "runtime-ide-tab-state" in css
    assert "grid-template-columns: minmax(0, 1fr) auto auto" in css
    assert "runtime-node-route-audit" in css
    assert "runtime-node-recovery" in css
    assert "runtime-node-recovery-actions" in css
    assert "runtime-readiness-panel" in css
    assert "runtime-readiness-kpis" in css
    assert "runtime-node-readiness-badge" in css
    assert "readiness-error" in css
    assert "runtime-readiness-focus" in css
    assert "eventRemediationMarkup" in js
    assert "focusApprovalQueueItem" in js
    assert "approvalResolutionForEvent" in js
    assert "preserveSelectedEventId" in js
    assert "Approval Status" in js
    assert "Focus Approval Queue" in js
    assert "data-approval-item-id" in js
    assert "runtime-remediation-focus-approval" in css
    assert "runtime-event-approval-status" in css
    assert "module-management-list-state" in css
    assert "Select only" in module_js
    assert "chips refocus a loaded module" in module_js
    assert "jumpToConfigSection" in module_js
    assert "module-management-jump-focus" in css
    assert "module-management-config-nav" in css
    assert "Recommended next actions" in js
    assert "runtime-event-remediation" in css
    assert "runtime-event-console-inspect" in css
    assert "selectedEventDecisionStripMarkup" in js
    assert "selectedTransitionSummary" in js
    assert "Route Decision" in js
    assert "Replay Basis" in js
    assert "replayValidationMarkup" in js
    assert "Replay matches selected event" in js
    assert "runtime-replay-validation" in css
    assert "renderModuleTraceMarkup" in js
    assert "moduleTraceEventsForStage" in js
    assert "mergeRuntimeEventState" in js
    assert "activeEvent = recentRuntimeEvents.find((event) => eventUpdatesActiveStage(event))" in js
    assert "if (activeGraph) renderGraph(parseGraphEditor())" in js
    assert "eventUpdatesActiveStage" in js
    assert "type.startsWith(\"graph.\")" in js
    assert "Module Step Trace" in js
    assert "active module step" in js
    assert "nodeSchemaStatus" in js
    assert "nodeCodeMapping" in js
    assert "I/O Contract" in js
    assert "Code Mapping" in js
    assert "handlerMetadataStatus" in js
    assert "handlerSignatureText" in js
    assert "availableHandlerMetadata" in js
    assert "handler_metadata" in js
    assert "Graph signature" in js
    assert "Effective signature" in js
    assert "Invalid graph handler signature" in js
    assert "runtime-handler-signature" in css
    assert "runtime-handler-row" in css
    assert "data-node-dry-run-stage" in js
    assert "timelineStats" in js
    assert "renderEventLog" in js
    assert "eventConsoleSeverity" in js
    assert "runtimeEventConsoleRows" in js
    assert "data-event-log-event-id" in js
    assert "artifactStageFromPath" in js
    assert "workspaceStages" in js
    assert 'bo: "bo"' in js
    assert 'cae: "analysis"' in js
    assert "artifactRelatedEvent" in js
    assert "artifactProvenanceMarkup" in js
    assert "Replay Producer Stage" in js
    assert "runtime-artifact-provenance-strip" in css
    assert "loadGraphVersions" in js
    assert "loadGraphVersionDraft" in js
    assert "renderActivationChecklist" in js
    assert "activationCompiledGraphDetailMarkup" in js
    assert "activationDryRunDetailMarkup" in js
    assert "runtime-activation-table" in js
    assert "Default Runtime Routes" in js
    assert "markActivationDirty" in js
    assert "runtime_ide_compile_draft" in js
    assert "recordActiveDryRunGate" in js
    assert "server save preflight" in js
    assert "dry-run gate" in js
    assert "loadGraphDryRunGate" in js
    assert "livePreflightStatus" in js
    assert "runPreflightTargetStripMarkup" in js
    assert "syncRunLauncherControls" in js
    assert "Preflight status remains authoritative" in js
    assert "Execution Target" in js
    assert "runTestBtn.disabled" in js
    assert "runLiveBtn.disabled" in js
    assert "recordLiveGateBtn.disabled = !canRecordGate" in js
    assert "Run is only available from the Main System graph tab." in js
    assert "Unsaved draft route/config changes are present. Validate and Save Version first." in js
    assert "Run will execute the saved active graph config, not unsaved editor drafts." in js
    assert "Run buttons never execute unsaved editor JSON. Save Version first when the draft changes." in js
    assert "deepLinkGraphId" in js
    assert "deepLinkNodeRef" in js
    assert "focusGraphNodeInCanvas" in js
    assert "modulePayloadFetches" in js
    assert "ensureModulePayloadForInspector" in js
    assert "/api/modules/${encodeURIComponent(clean)}" in js
    assert "Node Quick Actions" in js
    assert "runtime-node-quick-actions" in css
    assert "Skipped loading ${requested}; ${activeTab.moduleId} module tab is active." in js
    assert 'activeTab?.kind === "module"' in js
    assert "openModuleGraphTab(moduleSelect.value || activeModuleId)" in js
    assert 'moduleSelect.addEventListener("change", () => openModuleGraphTab(moduleSelect.value || activeModuleId)' in js
    assert "graphConfigFingerprint" in js
    assert "activeDraftConfigDiff" in js
    assert "readableFitMinZoom" in js
    assert '`V${percent}%' in js
    assert "Fit graph viewport to readable" in js
    assert "runtime-ide-minimap-viewport" in js
    assert "centerCanvasOnWorldPoint" in js
    assert "beginMiniMapPan" in js
    assert "updateMiniMapViewport" in js
    assert "dropTargetFromEvent" in js
    assert "canvasPortElementFromPoint" in js
    assert "expandedNodeElementFromPoint" in js
    assert "next_stage:${targetStage}" in js
    assert "Added candidate ${sourceStage} -> ${targetStage}; default remains" in js
    assert "Draft config changes" in js
    assert "renderDraftSafetyStrip" in js
    assert "executeDraftSafetyAction" in js
    assert "data-draft-safety-action" in js
    assert "Open Run Launcher" in js
    assert "Record Gate" in js
    assert "draftSafetyStripStatus" in js
    assert "Validate + Dry Run, then Save Version" in js
    assert "Record Active Dry-run Gate before live" in js
    assert "runtime-draft-safety-strip" in css
    assert "keep the graph canvas above the fold" in css
    assert "repeat(6, minmax(0, 1fr))" in css
    assert "prevent the canvas toolbar and draft gate from turning into tall form rows" in css
    assert "runtime-canvas-view-hint" in css
    assert "closed operator drawers are launch controls" in css
    assert "runtime-version-history-panel summary small" in css
    assert "scenario_evidence" in browser_audit
    assert "scenario_graph_switch" in browser_audit
    assert "scenario_canvas_interactions" in browser_audit
    assert "scenario_workspace_artifacts" in browser_audit
    assert "workspace-artifacts" in browser_audit
    assert "runtime_ide_browser_audit_workspace_artifacts.png" in browser_audit
    assert "BO progress artifact.created event missing" in browser_audit
    assert "CAE contour artifact.created event missing" in browser_audit
    assert "scenario_saved_test_run" in browser_audit
    assert "runtime_ide_browser_audit_saved_test_run.png" in browser_audit
    assert "Run Saved Test did not create a new run id" in browser_audit
    assert "saved test run missing node.started event" in browser_audit
    assert "pre-existing active run is present" in browser_audit
    assert "scenario_invalid_handler" in browser_audit
    assert "scenario_invalid_module" in browser_audit
    assert "scenario_invalid_route" in browser_audit
    assert "runtime_ide_browser_audit_evidence_vcd.png" in browser_audit
    assert "runtime_ide_browser_audit_graph_switch.png" in browser_audit
    assert "runtime_ide_browser_audit_canvas_interactions.png" in browser_audit
    assert "runtime_ide_browser_audit_invalid_handler.png" in browser_audit
    assert "runtime_ide_browser_audit_invalid_module.png" in browser_audit
    assert "runtime_ide_browser_audit_invalid_route.png" in browser_audit
    assert "graph canvas starts too low" in browser_audit
    assert "graph JSON did not switch" in browser_audit
    assert "minimap node count does not match JSON" in browser_audit
    assert "double-click did not open design module tab" in browser_audit
    assert "module internal graph edges missing module-flow styling" in browser_audit
    assert "module internal graph edges are not visibly styled" in browser_audit
    assert "module internal graph edge label text is empty" in browser_audit
    assert "module internal graph arrows are not using the module-flow marker" in browser_audit
    assert "moduleFlowLabelMinWidth" in browser_audit
    assert "edge-module-flow" in js
    assert "MODULE_GRAPH_COLUMN_GAP" in js
    assert "const MODULE_GRAPH_COLUMN_GAP = 560" in js
    assert "defaultModuleNodePosition" in js
    assert "module internal graph node spacing is too tight for edge labels" in browser_audit
    assert "ide-arrow-module" in js
    assert "fill=\"context-stroke\"" in js
    assert "v120: make agent internal module graph connections explicit" in css
    assert "v121: tighten module-flow arrow alignment" in css
    assert "marker-end: url(#ide-arrow-module)" in css
    assert "minimap pan did not change canvas scroll" in browser_audit
    assert "edge drag did not add design -> vision candidate" in browser_audit
    assert "node drag did not update graph JSON position" in browser_audit
    assert "dry-run did not produce VCD evidence" in browser_audit
    assert "runtime-readiness-panel .runtime-readiness-output" in css
    assert "Runtime Readiness is an operational gate" in css
    assert "runtime-draft-safety-action" in css
    assert "runtime-run-target-summary-card" in css
    assert "Full graph config differs from active baseline" in js
    assert "yaml import draft" in js
    assert "activeTabDirty" in js
    assert "tabDirtyState" in js
    assert "graphConfigDiff(item?.baselineGraph || null, item?.graph || {})" in js
    assert "Run preflight blocked" in js
    assert "Active dry-run gate is missing or stale" in js
    assert "startRuntimeGraphFromIde" in js
    assert "runLauncherPayload" in js
    assert "runTargetSummaryMarkup" in js
    assert "Saved active graph execution" in js
    assert "Run buttons never execute unsaved editor JSON" in js
    assert "runTargetSummaryOutput" in js
    assert "run blocked" in js
    assert "data-graph-version-load" in js
    assert "resolveApproval" in js
    assert "/approvals/" in js
    module_management_js = Path("web/static/module_management.js").read_text(encoding="utf-8")
    assert "module-management-item-copy" in module_management_js
    assert "module-management-title-wrap" in module_management_js
    assert "runtimeNodeIconMarkup(moduleIconName(module))" in module_management_js
    assert "applyConfigFormToPayload" in module_management_js
    assert "saveConfigSelected" in module_management_js
    assert "loadModuleVersions" in module_management_js
    assert "loadModuleVersionDraft" in module_management_js
    assert "renderDryRunEvidence" in module_management_js
    assert "module-management-evidence-step" in module_management_js
    assert "modulePreflightStatus" in module_management_js
    assert "Module save preflight blocked" in module_management_js
    assert "requireAppliedModuleDraft" in module_management_js
    assert "runtimeIdeUsageLink" in module_management_js
    assert "Open Node" in module_management_js
    assert "data-mm-version-load" in module_management_js
    assert "mm-config-handler-select" in module_management_js
    assert "data-mm-module-step-field" in module_management_js

    assert "stageDisplayLabel" in js
    assert "displayCondition" in js
    assert "Module Draft Changed" in js
    assert "validate and dry-run before saving" in js
    assert "moduleValidationResultMarkup" in js
    assert "moduleDryRunResultMarkup" in js
    assert "modulePayloadForGraphDraft" in js
    assert "persistModuleTabPayload" in js
    assert "moduleSavePreflightStatus" in js
    assert "moduleSavePreflightBlockedMarkup" in js
    assert "markModulePreflightDirty" in js
    assert 'dirty: false, reason: "not checked"' in js
    assert "Module save blocked" in js
    assert "Module validation ${ok ?" in js
    assert "handler/tool/safety schema check" in js
    assert "Module dry-run ${ok ?" in js
    assert "no hardware calls" in js
    assert "steps[index].metadata = { ...(steps[index].metadata || {}), position:" in js
    assert "renderModuleActivationChecklist" in js
    assert "moduleActivationEvidenceDetailsMarkup" in js
    assert "Validate Module Draft" in js
    assert "Save Module Version" in js
    assert "saveModule({ enforcePreflight: true })" in js
    assert "validateModule(dryRunOutput)" in js
    assert "dryRunModule(dryRunOutput)" in js
    assert "Module dry-run" in js
    css = Path("web/static/runtime_ide.css").read_text(encoding="utf-8")
    assert "runtime-run-target-strip" in css
    assert "runtime-run-message" in css
    assert "runtime-module-evidence-card" in css
    assert "runtime-module-save-gate-list" in css
    assert "pre_execution" in js and "internal_graph" in js
    assert "controlRuntimeRun" in js

from agents.base_agent import AgentResult, BaseAgent
from agents.registry import AgentRegistry
from logging_system.logger_factory import build_logger_bundle
from orchestrator.run_loop import RunLoop
from orchestrator.state import Mode, OrchestratorState, Stage


class _StaticAgent(BaseAgent):
    """Tiny agent used to prove graph-config transitions affect runtime execution."""

    def __init__(self, name: str, data: dict[str, object]) -> None:
        self.name = name
        self._data = data
        self.run_count = 0

    async def run(self, state: OrchestratorState, ctx: object) -> AgentResult:
        self.run_count += 1
        return AgentResult(success=True, summary=f"{self.name} done", data=dict(self._data))


class _FailingAgent(BaseAgent):
    """Agent that always fails so retry policy can be tested."""

    def __init__(self, name: str, message: str = "planned failure") -> None:
        self.name = name
        self.message = message
        self.run_count = 0

    async def run(self, state: OrchestratorState, ctx: object) -> AgentResult:
        self.run_count += 1
        raise RuntimeError(self.message)


class _ContextProbeAgent(BaseAgent):
    """Agent that records module runtime context visible during internal-step execution."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.run_count = 0
        self.seen_module_config: dict[str, object] = {}

    async def run(self, state: OrchestratorState, ctx: object) -> AgentResult:
        self.run_count += 1
        if hasattr(ctx, "runtime_module_config"):
            self.seen_module_config = ctx.runtime_module_config()  # type: ignore[assignment,attr-defined]
        else:
            self.seen_module_config = {"active_internal_step": state.run_metadata.get("active_module_step", {}).get("step", {})}
        return AgentResult(success=True, summary=f"{self.name} probe", data={"step_output": {"agent": self.name}})


def test_runtime_handler_registry_exposes_new_registered_agents_to_graph_and_module_validation() -> None:
    app_main.controller._deps.agent_registry.register(_StaticAgent("experimental_agent", {}))
    client = TestClient(app_main.app)

    handlers = client.get("/api/handlers").json()["handlers"]
    assert "agent.experimental_agent" in handlers

    graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    graph["nodes"][2]["handler"] = "agent.experimental_agent"
    graph_validation = client.post(
        "/api/graphs/atr_closed_loop/validate-draft",
        json={"graph": graph, "reason": "experimental-handler", "author": "pytest", "activate": False},
    ).json()
    assert graph_validation["ok"] is True
    assert graph_validation["compiled"] is True
    assert graph_validation["errors"] == []
    assert graph_validation["compiled_graph"]["nodes"][2]["handler"] == "agent.experimental_agent"

    module = client.get("/api/modules/design").json()["module"]
    module["module"]["handler"] = "agent.experimental_agent"
    module["module"]["internal_graph"][0]["handler"] = "agent.experimental_agent"
    module_validation = client.post(
        "/api/modules/design/validate",
        json={"module": module, "reason": "experimental-handler", "author": "pytest", "activate": False},
    ).json()
    assert module_validation == {"ok": True, "module_id": "design", "errors": []}


def _retry_test_loop(
    tmp_path: Path,
    *,
    module_retry: dict[str, object],
    global_max_retry: int,
) -> tuple[RunLoop, OrchestratorState, _FailingAgent, list[dict[str, object]]]:
    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {})
    design = _FailingAgent("design_agent")
    registry.register(orchestrator)
    registry.register(design)
    bundle = build_logger_bundle(run_id="run-langgraph-retry", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-retry",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        max_retry_per_stage=global_max_retry,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "handler": "agent.design_agent",
        "retry": dict(module_retry),
        "tools": [],
    }
    return loop, state, design, events


@pytest.mark.asyncio
async def test_saved_transition_candidate_routes_actual_langgraph_run_loop(tmp_path) -> None:
    """A Runtime IDE candidate edge must survive save/compile and drive actual runtime routing."""
    payload = load_graph_config("graphs/configs/atr_closed_loop.yaml").model_dump(mode="json")
    _add_graph_transition_candidate(payload, "design", "guardian", "next_stage:guardian")
    config = GraphConfig.model_validate(payload)

    assert config.transitions["design"] == "specimen"
    assert config.next_stage("design") == "specimen"
    assert config.next_stage("design", state_metadata={"agent_result": {"next_stage": "guardian"}}) == "guardian"

    graph_path = tmp_path / "atr_closed_loop_candidate.yaml"
    graph_path.write_text(yaml.safe_dump({"graph": config.model_dump(mode="json")}, sort_keys=False), encoding="utf-8")

    registry_for_compile = _noop_registry()
    compiler = ATRLangGraphCompiler(config, registry_for_compile)
    assert compiler.validate() == []
    summary = compiler.summary()
    design_candidates = summary["transition_candidates"]["design"]
    assert any(
        item["to_stage"] == "guardian" and item["condition"] == "next_stage:guardian" and item["default"] is False
        for item in design_candidates
    )

    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {"plan_text": "candidate route preflight"})
    design = _StaticAgent(
        "design_agent",
        {
            "experiment_spec": {"specimen_id": "candidate-route"},
            "next_stage": "guardian",
        },
    )
    registry.register(orchestrator)
    registry.register(design)
    bundle = build_logger_bundle(run_id="run-langgraph-candidate-route", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-candidate-route",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path=graph_path,
        on_event=events.append,
    )

    await loop.step()

    assert orchestrator.run_count == 1
    assert design.run_count == 1
    assert state.stage == Stage.GUARDIAN
    transition_events = [event for event in events if event["type"] == "edge.traversed" and event["node_id"] == "design"]
    assert transition_events
    payload = transition_events[-1]["payload"]
    assert payload["from_stage"] == "design"
    assert payload["to_stage"] == "guardian"
    assert payload["selected_transition"]["to_stage"] == "guardian"
    assert payload["selected_transition"]["condition"] == "next_stage:guardian"
    assert payload["selected_transition"]["default"] is False
    assert any(
        item["to_stage"] == "specimen" and item["default"] is True
        for item in payload["transition_candidates"]
    )


@pytest.mark.asyncio
async def test_workspace_template_graph_executes_through_langgraph_run_loop(tmp_path) -> None:
    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    specimen = _StaticAgent("specimen_agent", {"specimen_result": {"ok": True, "status": "prepared"}})
    registry.register(specimen)
    bundle = build_logger_bundle(run_id="run-langgraph-printer-template", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-printer-template",
        mode=Mode.TEST,
        stage=Stage.IDLE,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path="graphs/configs/printer_pipeline.yaml",
        on_event=events.append,
    )

    await loop.step()
    assert state.stage == Stage.SPECIMEN
    await loop.step()

    assert specimen.run_count == 1
    assert state.stage == Stage.COMPLETE
    assert any(event["graph_id"] == "printer_pipeline" for event in events)
    assert any(event["type"] == "node.completed" and event["node_id"] == "specimen" for event in events)


@pytest.mark.asyncio
async def test_module_retry_policy_overrides_global_retry_budget(tmp_path) -> None:
    loop, state, design, events = _retry_test_loop(
        tmp_path,
        module_retry={"max_attempts": 1, "backoff_s": 0},
        global_max_retry=0,
    )

    await loop.step()

    assert design.run_count == 1
    assert state.stage == Stage.DESIGN
    assert state.retry_counters["design"] == 1
    retry_events = [event for event in events if event["type"] == "node.retrying"]
    assert retry_events
    assert retry_events[-1]["payload"]["retry_policy"] == {"max_attempts": 1, "backoff_s": 0.0}

    await loop.step()

    assert design.run_count == 2
    assert state.stage == Stage.ERROR
    failed_events = [event for event in events if event["type"] == "node.failed"]
    assert failed_events[-1]["payload"]["retry_policy"] == {"max_attempts": 1, "backoff_s": 0.0}


@pytest.mark.asyncio
async def test_module_retry_policy_zero_attempts_fails_without_retry(tmp_path) -> None:
    loop, state, design, events = _retry_test_loop(
        tmp_path,
        module_retry={"max_attempts": 0, "backoff_s": 0},
        global_max_retry=3,
    )

    await loop.step()

    assert design.run_count == 1
    assert state.stage == Stage.ERROR
    assert state.retry_counters.get("design", 0) == 0
    assert not [event for event in events if event["type"] == "node.retrying"]


def _approval_test_loop(tmp_path: Path) -> tuple[RunLoop, OrchestratorState, _StaticAgent, list[dict[str, object]]]:
    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {})
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "approval-gated"}})
    registry.register(orchestrator)
    registry.register(design)
    bundle = build_logger_bundle(run_id="run-langgraph-approval", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-approval",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "handler": "agent.design_agent",
        "safety": {"requires_human_approval": True},
        "tools": [],
    }
    return loop, state, design, events


@pytest.mark.asyncio
async def test_module_human_approval_gate_blocks_stage_until_approved(tmp_path) -> None:
    loop, state, design, events = _approval_test_loop(tmp_path)

    await loop.step()

    assert state.stage == Stage.DESIGN
    assert state.is_paused is True
    assert design.run_count == 0
    approvals = state.run_metadata["runtime_approvals"]
    gate_key, gate = next(iter(approvals.items()))
    assert gate["status"] == "pending"
    assert gate["stage"] == "design"
    assert any(event["type"] == "approval.requested" for event in events)

    approvals[gate_key]["status"] = "approved"
    state.is_paused = False
    await loop.step()

    assert design.run_count == 1
    assert state.stage == Stage.SPECIMEN
    assert any(event["type"] == "node.completed" and event["node_id"] == "design" for event in events)


@pytest.mark.asyncio
async def test_module_human_approval_rejection_stops_stage(tmp_path) -> None:
    loop, state, design, events = _approval_test_loop(tmp_path)

    await loop.step()
    approvals = state.run_metadata["runtime_approvals"]
    gate_key, _gate = next(iter(approvals.items()))
    approvals[gate_key]["status"] = "rejected"
    state.is_paused = False

    await loop.step()

    assert design.run_count == 0
    assert state.stage == Stage.ERROR
    assert any(event["type"] == "node.failed" and event["payload"].get("decision") == "rejected" for event in events)


@pytest.mark.asyncio
async def test_missing_module_handler_fails_as_routing_error(tmp_path) -> None:
    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    bundle = build_logger_bundle(run_id="run-langgraph-missing-handler", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-missing-handler",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "handler": "agent.missing_agent",
        "tools": [],
    }

    await loop.step()

    assert state.stage == Stage.ERROR
    failed = [event for event in events if event["type"] == "node.failed"]
    assert failed[-1]["payload"]["handler"] == "agent.missing_agent"
    assert failed[-1]["payload"]["agent"] == "missing_agent"


@pytest.mark.asyncio
async def test_module_handler_override_changes_actual_agent_execution(tmp_path) -> None:
    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {})
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "wrong-agent"}})
    guardian = _StaticAgent("guardian_agent", {"experiment_spec": {"specimen_id": "handler-override"}})
    registry.register(orchestrator)
    registry.register(design)
    registry.register(guardian)
    bundle = build_logger_bundle(run_id="run-langgraph-handler", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-handler",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "label": "Design Override Module",
        "handler": "agent.guardian_agent",
        "tools": [],
    }

    await loop.step()

    assert design.run_count == 0
    assert guardian.run_count == 1
    assert state.current_experiment_spec == {"specimen_id": "handler-override"}
    assert state.stage == Stage.SPECIMEN
    started = [event for event in events if event["type"] == "node.started" and event["node_id"] == "design"]
    assert started[-1]["agent"] == "guardian_agent"
    assert started[-1]["payload"]["module_runtime"]["label"] == "Design Override Module"
    assert started[-1]["payload"]["module_runtime"]["effective_handler"] == "agent.guardian_agent"


@pytest.mark.asyncio
async def test_module_pre_execution_runs_orchestrator_before_design_from_config(tmp_path) -> None:
    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {"plan_text": "pre plan", "model": "unit"})
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "pre-exec"}})
    registry.register(orchestrator)
    registry.register(design)
    bundle = build_logger_bundle(run_id="run-langgraph-pre-exec", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-pre-exec",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )

    await loop.step()

    assert orchestrator.run_count == 1
    assert design.run_count == 1
    assert state.current_experiment_spec == {"specimen_id": "pre-exec"}
    assert state.run_metadata["orchestrator_plan"] == {"plan_text": "pre plan", "model": "unit"}
    assert any(event["type"] == "module.pre_step.started" for event in events)
    assert any(event["type"] == "module.pre_step.completed" for event in events)
    legacy = [event for event in events if event["event_type"] == "orchestrator_plan"]
    assert legacy
    assert legacy[-1]["type"] == "node.completed"
    assert legacy[-1]["node_id"] == "orchestrator_plan"


@pytest.mark.asyncio
async def test_module_pre_execution_can_be_skipped_for_live_planning_handoff(tmp_path) -> None:
    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {"plan_text": "duplicate"})
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "handoff-design"}})
    registry.register(orchestrator)
    registry.register(design)
    bundle = build_logger_bundle(run_id="run-langgraph-pre-exec-skip", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-pre-exec-skip",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        run_orchestrator_before_design=False,
        on_event=events.append,
    )

    await loop.step()

    assert orchestrator.run_count == 0
    assert design.run_count == 1
    assert state.current_experiment_spec == {"specimen_id": "handoff-design"}
    assert "orchestrator_plan" not in state.run_metadata
    assert not [event for event in events if event["type"].startswith("module.pre_step")]


@pytest.mark.asyncio
async def test_module_internal_graph_emits_runtime_trace_events(tmp_path) -> None:
    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    registry.register(_StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "internal-graph"}}))
    bundle = build_logger_bundle(run_id="run-langgraph-internal", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-internal",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "handler": "agent.design_agent",
        "internal_graph": [
            {"id": "01_intake", "label": "Intake", "kind": "internal_step"},
            {"id": "02_generate", "label": "Generate", "kind": "internal_step", "handler": "agent.design_agent"},
        ],
        "tools": [],
    }

    await loop.step()

    event_types = [event["type"] for event in events]
    assert "module.graph.started" in event_types
    assert event_types.count("module.step.planned") == 2
    assert "module.graph.completed" in event_types
    planned = [event for event in events if event["type"] == "module.step.planned"]
    assert [event["payload"]["module_step"]["id"] for event in planned] == ["01_intake", "02_generate"]
    completed = [event for event in events if event["type"] == "module.graph.completed"][-1]
    assert completed["payload"]["result_keys"] == ["experiment_spec"]
    assert completed["payload"]["step_count"] == 2


@pytest.mark.asyncio
async def test_module_internal_graph_executes_configured_step_handlers(tmp_path) -> None:
    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "internal-handler"}})
    probe = _ContextProbeAgent("step_agent")
    registry.register(design)
    registry.register(probe)
    bundle = build_logger_bundle(run_id="run-langgraph-internal-handler", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-internal-handler",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "handler": "agent.design_agent",
        "internal_graph": [
            {"id": "01_checkpoint", "label": "Checkpoint", "kind": "internal_step"},
            {"id": "02_probe", "label": "Probe", "kind": "internal_step", "handler": "agent.step_agent"},
        ],
        "tools": [],
    }

    await loop.step()

    assert probe.run_count == 1
    assert design.run_count == 1
    assert state.current_experiment_spec == {"specimen_id": "internal-handler"}
    assert probe.seen_module_config["active_internal_step"]["id"] == "02_probe"
    assert state.run_metadata["module_step_results"]["design"]["02_probe"] == {"step_output": {"agent": "step_agent"}}
    assert "active_module_step" not in state.run_metadata
    started = [event for event in events if event["type"] == "module.step.started"]
    completed = [event for event in events if event["type"] == "module.step.completed"]
    assert [event["payload"]["module_step"]["id"] for event in started] == ["01_checkpoint", "02_probe"]
    assert [event["payload"]["executable"] for event in completed] == [False, True]


@pytest.mark.asyncio
async def test_module_internal_graph_emits_failure_event(tmp_path) -> None:
    loop, state, design, events = _retry_test_loop(
        tmp_path,
        module_retry={"max_attempts": 0, "backoff_s": 0},
        global_max_retry=0,
    )
    loop._module_configs["design"]["internal_graph"] = [  # type: ignore[index]
        {"id": "01_fail", "label": "Fail", "kind": "internal_step"}
    ]

    await loop.step()

    assert design.run_count == 1
    assert state.stage == Stage.ERROR
    failed = [event for event in events if event["type"] == "module.graph.failed"]
    assert failed
    assert failed[-1]["payload"]["step_count"] == 1
    assert "planned failure" in failed[-1]["payload"]["error"]


@pytest.mark.asyncio
async def test_configured_transition_changes_actual_langgraph_runtime(tmp_path) -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    payload = config.model_dump(mode="json")
    payload["transitions"]["design"] = "guardian"
    design_default_edge = next(
        edge
        for edge in payload["edges"]
        if edge.get("metadata", {}).get("runtime_edge") == "logical_transition"
        and edge.get("metadata", {}).get("from_stage") == "design"
        and edge.get("metadata", {}).get("default_transition") is True
    )
    design_default_edge["target"] = "guardian"
    design_default_edge["label"] = "default transition: design -> guardian"
    design_default_edge["metadata"]["to_stage"] = "guardian"
    graph_path = tmp_path / "graph.yaml"
    graph_path.write_text(yaml.safe_dump({"graph": payload}, sort_keys=False), encoding="utf-8")

    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    registry.register(
        _StaticAgent(
            "design_agent",
            {
                "experiment_spec": {"specimen_id": "cfg-transition-test"},
                "artifacts": {"preview_url": "/api/planning/artifacts/run/specimen/specimen_preview.svg"},
            },
        )
    )
    registry.register(_StaticAgent("guardian_agent", {"guardian": {"decision": "stop"}}))

    bundle = build_logger_bundle(run_id="run-langgraph-transition", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-transition",
        mode=Mode.TEST,
        stage=Stage.IDLE,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path=graph_path,
        on_event=events.append,
    )

    await loop.step()
    assert state.stage == Stage.DESIGN
    await loop.step()
    assert state.stage == Stage.GUARDIAN
    await loop.step()
    assert state.stage == Stage.COMPLETE
    assert state.loop_count == 1
    assert "specimen_agent" not in state.agent_status
    event_types = [event["type"] for event in events]
    assert "node.started" in event_types
    assert "edge.traversed" in event_types

from backends.llm_backend import BaseLLMBackend, LLMResponse
from backends.model_router import ModelRouter
from orchestrator.langgraph_runtime import ModuleRuntimeContext


class _CaptureBackend(BaseLLMBackend):
    """LLM backend that records the exact request received from ModuleRuntimeContext."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, object] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "metadata": metadata or {},
            }
        )
        return LLMResponse(text="module-routed", model=model, raw={"metadata": metadata or {}})


class _FakeToolRegistry:
    """Small ToolRegistry-compatible object for module allowlist tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def call(self, name: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append({"name": name, "payload": payload or {}})
        return {"ok": True, "tool": name, "payload": payload or {}}

    def list_tools(self) -> list[str]:
        return ["blocked.tool", "experiment.evaluate", "geometry.generate_metamaterial_stl"]

    def queue_status(self) -> dict[str, object]:
        return {"ok": True, "queues": []}


class _FakeAgentContext:
    """Minimal AgentContext-compatible object for module routing tests."""

    def __init__(self, backend: _CaptureBackend) -> None:
        router = ModelRouter(
            {
                "models": {"e4b": {"primary": "router-primary", "fallback": "router-fallback"}},
                "task_routes": {"module_reasoning": "e4b", "design_reasoning": "e4b"},
            }
        )
        self.active_backend = "ollama"
        self.model_router = router
        self.model_routers = {"ollama": router, "vllm": router}
        self.primary_backend = backend
        self.primary_backends = {"ollama": backend, "vllm": backend}
        self.fallback_backend = backend
        self.fallback_backends = {"ollama": backend, "vllm": backend}
        self.tools = _FakeToolRegistry()
        self.notifications: list[dict[str, str]] = []
        self.model_call_events: list[dict[str, str]] = []

    async def _notify_model_call(self, task_type: str, model: str, role: str) -> None:
        self.notifications.append({"task_type": task_type, "model": model, "role": role})

    async def on_model_call(self, *, task_type: str, model: str, role: str, backend: str) -> None:
        self.model_call_events.append({"task_type": task_type, "model": model, "role": role, "backend": backend})


@pytest.mark.asyncio
async def test_module_runtime_context_applies_llm_model_prompt_and_metadata() -> None:
    backend = _CaptureBackend()
    base_ctx = _FakeAgentContext(backend)
    module_ctx = ModuleRuntimeContext(
        base_ctx,  # type: ignore[arg-type]
        {
            "id": "design",
            "llm_role": "module_reasoning",
            "llm": {"backend": "vllm", "model": "module-model", "fallback": "module-fallback"},
            "prompt": {"system": "module system prompt", "developer": "module developer prompt"},
            "timeout_s": 10,
        },
        Stage.DESIGN,
    )

    response = await module_ctx.complete("design_reasoning", "original user prompt")

    assert response.model == "module-model"
    assert backend.calls == [
        {
            "model": "module-model",
            "system_prompt": "module system prompt",
            "user_prompt": "[Module developer guidance: module developer prompt]\n\noriginal user prompt",
            "metadata": {
                "task_type": "module_reasoning",
                "requested_task_type": "design_reasoning",
                "role": "e4b",
                "stage": "design",
                "module_id": "design",
                "module_config_applied": True,
            },
        }
    ]
    assert base_ctx.model_call_events == [
        {"task_type": "module_reasoning", "model": "module-model", "role": "e4b", "backend": "vllm"}
    ]
    assert base_ctx.notifications == []


def test_module_runtime_context_filters_tools_by_module_allowlist() -> None:
    backend = _CaptureBackend()
    base_ctx = _FakeAgentContext(backend)
    module_ctx = ModuleRuntimeContext(
        base_ctx,  # type: ignore[arg-type]
        {
            "id": "specimen",
            "tools": ["geometry.generate_metamaterial_stl", "experiment.evaluate"],
        },
        Stage.SPECIMEN,
    )

    assert module_ctx.tools.list_tools() == ["experiment.evaluate", "geometry.generate_metamaterial_stl"]
    assert module_ctx.tools.call("geometry.generate_metamaterial_stl", {"size": 30}) == {
        "ok": True,
        "tool": "geometry.generate_metamaterial_stl",
        "payload": {"size": 30},
    }
    with pytest.raises(PermissionError) as exc_info:
        module_ctx.tools.call("blocked.tool", {})
    assert "Tool not allowed for stage=specimen: blocked.tool" in str(exc_info.value)
    assert module_ctx.tools.queue_status() == {"ok": True, "queues": []}


def test_generated_module_adapter_executes_as_stage_handler(tmp_path) -> None:
    graph_root = tmp_path / "graphs"
    config_root = graph_root / "configs"
    modules_root = graph_root / "modules"
    module_dir = modules_root / "design"
    config_root.mkdir(parents=True)
    shutil.copytree(Path("graphs/modules"), modules_root)
    (config_root / "atr_closed_loop.yaml").write_text(
        Path("graphs/configs/atr_closed_loop.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (module_dir / "handler.py").write_text(
        "from agents.base_agent import AgentResult\n\n"
        "async def run(state, ctx):\n"
        "    return AgentResult(success=True, summary='generated design ok', data={'experiment_spec': {'specimen_id': 'generated-module'}})\n",
        encoding="utf-8",
    )
    (module_dir / "module.yaml").write_text(
        """
module:
  id: design
  label: Generated Design Module
  handler: module.generated_adapter
  metadata:
    pending_handler_registration: false
    generated_adapter_approved: true
    generated_adapter_handler_id: module.generated_adapter
    generated_adapter_path: handler.py
  safety:
    live_requires_validation: true
    dry_run_supported: true
    requires_human_approval: false
  internal_graph:
    - id: 01_generated_checkpoint
      label: Generated adapter checkpoint
      kind: internal_step
""".strip()
        + "\n",
        encoding="utf-8",
    )

    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    bundle = build_logger_bundle(run_id="run-generated-module", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-generated-module",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path=config_root / "atr_closed_loop.yaml",
        module_root=graph_root,
        on_event=events.append,
    )

    asyncio.run(loop.step())

    assert state.current_experiment_spec == {"specimen_id": "generated-module"}
    started = [event for event in events if event["type"] == "node.started" and event["node_id"] == "design"]
    assert started[-1]["agent"] == "generated:design"
    assert started[-1]["payload"]["module_runtime"]["effective_handler"] == "module.generated_adapter"
    completed = [event for event in events if event["type"] == "node.completed" and event["node_id"] == "design"]
    assert completed[-1]["agent"] == "generated:design"
