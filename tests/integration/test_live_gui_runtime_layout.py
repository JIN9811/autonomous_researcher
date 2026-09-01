"""Integration checks for the Live GUI Runtime IDE shell."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app, controller, _package_runtime_event


TINY_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"atr-test-screen-evidence"


def test_skill_workflow_editor_preserves_step_rows_inside_scroll_viewport() -> None:
    css = TestClient(app).get("/static/styles.css").text

    step_list_rule = css.split(".skill-workflow-step-list {", 1)[1].split("}", 1)[0]
    step_card_rule = css.split(".skill-workflow-step-card {", 1)[1].split("}", 1)[0]
    assert "grid-auto-rows: max-content" in step_list_rule
    assert "overflow-y: auto" in step_list_rule
    assert "min-height: 54px" in step_card_rule


def test_skill_workflow_editor_exposes_manual_target_crop_controls() -> None:
    client = TestClient(app)
    template = Path("web/templates/equipment_skill_workflow_editor.html").read_text(encoding="utf-8")
    script = client.get("/static/equipment_skill_workflow_editor.js").text

    for element_id in (
        "workflow-crop-dialog",
        "workflow-crop-source",
        "workflow-crop-box",
        "workflow-crop-preview",
        "workflow-crop-reset",
        "workflow-crop-apply",
        "workflow-crop-cancel",
    ):
        assert f'id="{element_id}"' in template
    assert "Edit Crop" in script
    assert "/locator-source" in script
    assert '"locator_origin"' in script
    assert '"manual_crop"' in script
    assert '"ai_target_bbox_norm"' in script
    assert 'crop_origin' in script
    assert 'confidence: 0.9' in script


def test_equipment_locator_confidence_defaults_to_point_nine() -> None:
    template = Path("web/templates/windows_equipment.html").read_text(encoding="utf-8")
    script = Path("web/static/windows_equipment.js").read_text(encoding="utf-8")

    assert 'id="equipment-locator-confidence" class="text-input" value="0.9"' in template
    assert "locatorConfidenceInput.value : 0.9" in script
    assert "|| 0.9" in script


def test_completed_test_run_keeps_its_final_live_gui_snapshot() -> None:
    client = TestClient(app)

    script_response = client.get("/static/planning.js")

    assert script_response.status_code == 200
    script = script_response.text
    assert "function shouldFreezeCompletedTestRun" in script
    assert 'String(cycleContract.mode || missionContract.mode || "").toLowerCase() === "test"' in script
    assert 'String(state.stage || "").toLowerCase() === "complete"' in script
    assert "completedCycles >= totalCycles" in script
    assert "background && shouldFreezeCompletedTestRun(liveLastSession)" in script
    assert "!shouldFreezeCompletedTestRun(liveLastSession)" in script
    assert "sameCompletedRunEvent" in script


def test_common_equipment_profiles_expose_token_safe_utm_profile() -> None:
    client = TestClient(app)

    response = client.get("/api/equipment/profiles")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_profile_id"] == "utm_windows_v1"
    assert payload["profiles"][0]["profile_id"] == "utm_windows_v1"
    assert '"token":' not in json.dumps(payload).lower()


def test_common_equipment_profile_state_and_unknown_profile() -> None:
    client = TestClient(app)

    state = client.get("/api/equipment/profiles/utm_windows_v1/state")
    missing = client.get("/api/equipment/profiles/not-registered/state")

    assert state.status_code == 200
    assert state.json()["profile"]["label"] == "UTM"
    assert '"token":' not in json.dumps(state.json()).lower()
    assert missing.status_code == 404


def test_windows_equipment_page_exposes_common_profile_workspace() -> None:
    client = TestClient(app)

    response = client.get("/equipment/windows")

    assert response.status_code == 200
    for element_id in (
        "equipment-profile-list",
        "equipment-profile-items",
        "equipment-profile-connection",
        "equipment-profile-runtime",
        "equipment-profile-evidence",
        "btn-equipment-profile-preflight",
        "btn-equipment-profile-test",
    ):
        assert f'id="{element_id}"' in response.text
    script = client.get("/static/windows_equipment.js").text
    assert "/api/equipment/profiles" in script
    assert "selectedEquipmentProfileId" in script


def test_windows_equipment_profile_is_a_utm_default_select_without_provider_copy() -> None:
    client = TestClient(app)

    response = client.get("/equipment/windows")
    script = client.get("/static/windows_equipment.js").text

    assert response.status_code == 200
    assert '<select id="equipment-profile-items"' in response.text
    assert '<option value="utm_windows_v1" selected>UTM</option>' in response.text
    assert "data-equipment-profile" not in script
    assert "${profile.label} · ${profile.bridge_provider}" not in script


def test_equipment_skill_flow_is_shared_by_workspace_and_runtime_ide(tmp_path: Path, monkeypatch) -> None:
    from app import main as main_module

    monkeypatch.setattr(main_module, "EQUIPMENT_SKILL_FLOW_PATH", tmp_path / "equipment_skill_flows.json")
    monkeypatch.setattr(
        main_module,
        "_equipment_skill_registry",
        lambda: SimpleNamespace(
            list=lambda: [
                {
                    "skill_id": "utm_test",
                    "version": "1.0.0",
                    "name": "UTM Test",
                    "lifecycle": "deployed",
                    "enabled": True,
                    "target_profile": "utm_windows_v1",
                }
            ]
        ),
    )
    client = TestClient(app)
    flow = {
        "schema": "atr.equipment_skill_flow.v1",
        "flow_id": "utm_windows_v1",
        "profile_id": "utm_windows_v1",
        "version": 1,
        "blocks": [
            {
                "id": "run_test",
                "label": "Run test",
                "skill": {"skill_id": "utm_test", "skill_version": "1.0.0"},
                "agentic": {"completed": "__complete__", "failed": "__blocked__"},
                "vision": {
                    "enabled": True,
                    "task_id": "utm_motion_confirm",
                    "detected": "__complete__",
                    "not_detected": "__blocked__",
                    "timeout": "__blocked__",
                    "error": "__blocked__",
                },
            }
        ],
    }

    saved = client.put("/api/equipment/profiles/utm_windows_v1/skill-flow", json={"flow": flow})
    workspace = client.get("/api/equipment/profiles/utm_windows_v1/skill-flow")
    runtime = client.get("/api/modules/equipment/equipment-skill-flow?profile_id=utm_windows_v1")

    assert saved.status_code == 200
    assert workspace.json()["flow"]["blocks"][0]["skill"]["skill_id"] == "utm_test"
    assert [item["task_id"] for item in workspace.json()["vision_tasks"]] == [
        "utm_pre_start",
        "utm_motion_confirm",
        "utm_test_complete",
    ]
    assert workspace.json()["readiness"]["blocks"][0]["vision_task_id"] == "utm_motion_confirm"
    assert workspace.json()["readiness"]["blocks"][0]["vision_task_label"] == "UTM Motion Confirmation"
    assert runtime.json()["flow"] == workspace.json()["flow"]
    assert runtime.json()["graph"]["metadata"]["ide_tab_kind"] == "equipment_skill_flow"
    assert workspace.json()["readiness"]["blocks"][0]["ready"] is True


def test_equipment_skill_flow_exposes_the_code_owned_utm_cycle_template(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app import main as main_module

    monkeypatch.setattr(main_module, "EQUIPMENT_SKILL_FLOW_PATH", tmp_path / "equipment_skill_flows.json")
    client = TestClient(main_module.app)

    response = client.get("/api/equipment/profiles/utm_windows_v1/skill-flow")

    assert response.status_code == 200
    payload = response.json()
    task = next(item for item in payload["agentic_tasks"] if item["task_id"] == "run_utm_compression_cycle")
    template = next(item for item in payload["flow_templates"] if item["agentic_task_id"] == task["task_id"])
    assert task["entry_gate"] == {
        "id": "verified_specimen_utm_handoff",
        "label": "Verified specimen / UTM handoff",
        "locked": True,
    }
    assert [block["id"] for block in template["blocks"]] == [
        "prepare_next_specimen",
        "start_test",
        "monitor_contact_and_run",
        "await_auto_return",
        "save_raw_data",
        "validate_raw_data",
        "advance_without_save",
        "restore_robot_clearance",
    ]
    assert all(block["skill"] == {"skill_id": "", "skill_version": ""} for block in template["blocks"])
    assert all(block["vision"]["enabled"] is False for block in template["blocks"])


def test_equipment_skill_flow_execution_is_filtered_to_requested_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app import main as main_module

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "utm_windows_v1.json").write_text(
        json.dumps(
            {
                "schema": "atr.equipment_skill_flow_execution.v1",
                "profile_id": "utm_windows_v1",
                "run_id": "run-current",
                "active_block": "start_test",
                "terminal": "",
                "transitions": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module, "EQUIPMENT_SKILL_FLOW_PATH", tmp_path / "equipment_skill_flows.json")
    monkeypatch.setattr(main_module, "EQUIPMENT_SKILL_FLOW_RUNTIME_ROOT", runtime_root)
    client = TestClient(main_module.app)

    matching = client.get(
        "/api/equipment/profiles/utm_windows_v1/skill-flow?run_id=run-current"
    )
    mismatched = client.get(
        "/api/equipment/profiles/utm_windows_v1/skill-flow?run_id=run-other"
    )

    assert matching.status_code == 200
    assert matching.json()["execution"]["run_id"] == "run-current"
    assert mismatched.status_code == 200
    assert mismatched.json()["execution"] == {}


def test_equipment_agent_manager_saved_status_distinguishes_ready_from_unbound() -> None:
    client = TestClient(app)

    script = client.get("/static/equipment_agent_manager.js").text

    assert 'hasUnboundSlot ? "Profile flow is saved. Unbound Skill Slots remain non-executable."' in script
    assert ': "Profile flow is saved and ready for Agent execution."' in script


def test_equipment_skill_flow_accepts_an_unbound_draft_block(tmp_path: Path, monkeypatch) -> None:
    from app import main as main_module

    monkeypatch.setattr(main_module, "EQUIPMENT_SKILL_FLOW_PATH", tmp_path / "equipment_skill_flows.json")
    monkeypatch.setattr(main_module, "_equipment_skill_registry", lambda: SimpleNamespace(list=lambda: []))
    client = TestClient(app)
    flow = {
        "schema": "atr.equipment_skill_flow.v1",
        "flow_id": "utm_windows_v1",
        "profile_id": "utm_windows_v1",
        "version": 1,
        "blocks": [
            {
                "id": "empty_block",
                "label": "Unbound block",
                "skill": {"skill_id": "", "skill_version": ""},
                "agentic": {"completed": "__complete__", "failed": "__blocked__"},
                "vision": {
                    "enabled": False,
                    "task_id": "",
                    "detected": "__complete__",
                    "not_detected": "__blocked__",
                    "timeout": "__blocked__",
                    "error": "__blocked__",
                },
            }
        ],
    }

    saved = client.put("/api/equipment/profiles/utm_windows_v1/skill-flow", json={"flow": flow})

    assert saved.status_code == 200
    payload = saved.json()
    assert payload["flow"]["blocks"][0]["skill"] == {"skill_id": "", "skill_version": ""}
    assert payload["readiness"]["ready"] is False
    assert payload["readiness"]["blocks"][0]["reason"] == "Skill Slot is unbound"


def test_equipment_skill_flow_rejects_unknown_vision_task_atomically(tmp_path: Path, monkeypatch) -> None:
    from app import main as main_module

    monkeypatch.setattr(main_module, "EQUIPMENT_SKILL_FLOW_PATH", tmp_path / "equipment_skill_flows.json")
    monkeypatch.setattr(main_module, "_equipment_skill_registry", lambda: SimpleNamespace(list=lambda: []))
    client = TestClient(app)
    original = {
        "schema": "atr.equipment_skill_flow.v1",
        "flow_id": "utm_windows_v1",
        "profile_id": "utm_windows_v1",
        "version": 1,
        "blocks": [],
    }
    assert client.put("/api/equipment/profiles/utm_windows_v1/skill-flow", json={"flow": original}).status_code == 200
    invalid = {
        **original,
        "blocks": [
            {
                "id": "bad_vision",
                "label": "Invalid Vision",
                "skill": {"skill_id": "", "skill_version": ""},
                "agentic": {"task": "Invalid Vision", "completed": "__complete__", "failed": "__blocked__"},
                "vision": {
                    "enabled": True,
                    "task_id": "missing_task",
                    "detected": "__complete__",
                    "not_detected": "__blocked__",
                    "timeout": "__blocked__",
                    "error": "__blocked__",
                },
            }
        ],
    }

    rejected = client.put("/api/equipment/profiles/utm_windows_v1/skill-flow", json={"flow": invalid})

    assert rejected.status_code == 422
    assert "unknown Equipment Vision task" in rejected.json()["detail"]
    assert client.get("/api/equipment/profiles/utm_windows_v1/skill-flow").json()["flow"]["blocks"] == []


def test_agent_manager_is_the_only_equipment_skill_flow_editor() -> None:
    client = TestClient(app)
    manager = client.get("/equipment/agent-manager?profile_id=utm_windows_v1")
    workspace = client.get("/equipment/windows").text
    runtime = client.get("/ide").text
    workspace_script = client.get("/static/windows_equipment.js").text
    runtime_script = client.get("/static/runtime_ide.js").text
    live_script = client.get("/static/planning.js").text

    assert manager.status_code == 200
    for element_id in ("equipment-manager-add-skill", "equipment-manager-blocks", "equipment-manager-save"):
        assert f'id="{element_id}"' in manager.text
    assert "equipment-manager-add-vision" not in manager.text
    assert "equipment-manager-skill-slot" in manager.text
    assert "equipment-manager-agentic-slot" in manager.text
    assert "equipment-manager-vision-slot" in manager.text
    assert ">+ Block<" in manager.text
    manager_script = client.get("/static/equipment_agent_manager.js").text
    assert "addButton.disabled = !catalogReady" not in manager_script

    assert 'id="equipment-skill-flow-progress"' in workspace
    assert 'id="btn-open-equipment-agent-manager"' in workspace
    assert "btn-equipment-flow-add-skill" not in workspace
    assert "btn-equipment-flow-add-vision" not in workspace
    assert "btn-equipment-flow-save" not in workspace
    assert "/skill-flow" in workspace_script
    assert "equipment-skill-flow" in runtime_script
    assert 'id="ide-equipment-flow-workspace"' in runtime
    assert runtime.index('id="ide-equipment-flow-workspace"') < runtime.index("runtime-ide-compat-module-config")
    assert "showRuntimeEquipmentFlowWorkspace" in runtime_script
    assert 'id="ide-open-equipment-agent-manager"' in runtime
    assert "ide-equipment-flow-add-skill" not in runtime_script
    assert "ide-equipment-flow-add-vision" not in runtime_script
    assert "ide-equipment-flow-save" not in runtime_script
    assert "block.vision.condition" not in runtime_script
    assert "payload.vision_tasks" in runtime_script
    assert "equipmentVisionTasks" in workspace_script
    assert "block.vision.condition" not in live_script
    assert "visionTasks" in live_script
    for script in (workspace_script, runtime_script, live_script):
        assert "vision_task_id" in script
        assert "vision_task_label" in script


def test_agent_manager_exposes_locked_entry_gate_and_utm_cycle_draft_action() -> None:
    client = TestClient(app)

    page = client.get("/equipment/agent-manager").text
    script = client.get("/static/equipment_agent_manager.js").text

    assert 'id="equipment-manager-agentic-task"' in page
    assert 'id="equipment-manager-load-utm-cycle"' in page
    assert "Verified specimen / UTM handoff" in page
    assert "LOCKED" in page
    assert "flowTemplates" in script
    assert "applyTemplate" in script


def test_equipment_agent_manager_exposes_raw_csv_preview_and_test_contract() -> None:
    client = TestClient(app)

    page = client.get("/equipment/agent-manager").text
    script = client.get("/static/equipment_agent_manager.js").text
    for element_id in (
        "equipment-raw-csv-panel",
        "equipment-raw-csv-mode",
        "equipment-raw-csv-session",
        "equipment-raw-csv-specimen",
        "equipment-raw-csv-loop",
        "equipment-raw-csv-repeat",
        "equipment-raw-csv-preview",
        "equipment-raw-csv-execute",
        "equipment-raw-csv-status",
        "equipment-raw-csv-path",
    ):
        assert f'id="{element_id}"' in page
    assert 'runtime_mode: "dry_run"' in script
    assert "confirm_execute: false" in script
    assert 'runtime_mode: "test"' in script
    assert "confirm_execute: true" in script
    assert "utm_save_raw_data" in script
    assert "rawCsvPreview" in script
    assert "window.confirm" in script


def test_windows_equipment_page_uses_general_lab_equipment_bridge_structure() -> None:
    client = TestClient(app)

    response = client.get("/equipment/windows")

    assert response.status_code == 200
    html = response.text
    for element_id in (
        "equipment-runtime-overview",
        "equipment-connection-workspace",
        "equipment-skill-recording",
        "equipment-skill-management",
        "equipment-main-progress",
        "equipment-error-recovery",
        "equipment-evidence-workspace",
        "equipment-agentic-progress",
        "equipment-agentic-progress-stages",
        "equipment-skill-list",
        "equipment-selected-skill",
        "btn-equipment-skill-workflow-editor",
        "equipment-worker-recordings",
        "btn-equipment-refresh-recordings",
        "btn-open-equipment-agent-manager",
        "equipment-skill-flow-progress",
    ):
        assert f'id="{element_id}"' in html
    for text in (
        "Skill Recording",
        "Skill Management",
        "Main Progress",
        "Equipment execution projection",
        "Error Recovery",
        "Evidence &amp; Data Transfer",
    ):
        assert text in html
    assert "4. Test Selected Bridge" not in html
    assert "UTM Proof Gates" not in html

    script = client.get("/static/windows_equipment.js").text
    for endpoint in (
        "/api/equipment/runtime/current",
        "/api/equipment/skills",
        "/api/equipment/recordings/",
        "/api/equipment/workers/",
        "/recordings",
        "/import-skill",
    ):
        assert endpoint in script
    assert "renderEquipmentRuntimeOverview" in script
    assert "renderEquipmentSkills" in script
    assert "renderEquipmentAgenticProgress" in script
    assert 'btnImportRecording.addEventListener("click", importEquipmentRecording)' in script
    assert 'btnRefreshRecordings.addEventListener("click", refreshWorkerRecordings)' in script
    assert 'btnSkillRefresh.addEventListener("click", refreshEquipmentSkills)' in script
    assert 'id="btn-equipment-skill-compile"' not in html
    assert 'id="btn-equipment-skill-validate"' not in html
    assert "function openSelectedSkillWorkflowEditor()" in script
    assert 'window.open(url, `atr-skill-${skillId}-${version}`' in script
    assert 'id="equipment-recording-id"' not in html
    assert 'let selectedRecordingId = "";' in script
    assert "function escapeHtml(value)" in script
    assert "equipment-skill-row equipment-skill-item" in script
    assert 'const recordingId = String(selectedRecordingId || "").trim();' in script
    assert "refreshWorkerRecordings({ silent: true })" in script
    assert "RECORDING_LIST_REFRESH_MS" in script
    assert 'id="equipment-skill-authoring-progress"' in html
    assert 'id="equipment-skill-authoring-progress-bar"' in html
    assert 'id="equipment-skill-authoring-status"' in html
    assert 'id="btn-equipment-stop-skill-authoring"' in html
    assert 'id="equipment-skill-storyboard-preview"' in html
    assert 'id="equipment-skill-storyboard-image"' in html
    assert 'id="btn-equipment-skill-storyboard-previous"' in html
    assert 'id="btn-equipment-skill-storyboard-next"' in html
    assert 'id="btn-equipment-skill-annotate"' not in html
    assert 'id="equipment-skill-deployment-progress"' in html
    assert 'id="equipment-skill-deployment-progress-bar"' in html
    assert 'id="btn-equipment-stop-skill-deployment"' in html
    assert "/import-skill/start" in script
    assert "/api/equipment/skill-authoring/jobs/" in script
    assert "/storyboards?cursor=" in script
    assert "renderSkillStoryboardPage" in script
    assert 'selectedSkillPath("deploy/start")' in script
    assert "/api/equipment/skill-deployment/jobs/" in script
    assert "/stop" in script
    assert "btnImportRecording.disabled = !selectedRecordingId || Boolean(activeSkillAuthoringJobId);" in script
    assert "runEquipmentSkillAction" not in script
    assert "COMPILING" in Path("app/main.py").read_text(encoding="utf-8")
    assert "VALIDATING" in Path("app/main.py").read_text(encoding="utf-8")
    assert "refreshEquipmentSkills()" in script.split("Promise.all", 1)[-1]


def test_windows_equipment_opens_the_saved_windows_bridge_console_in_a_separate_window() -> None:
    client = TestClient(app)

    response = client.get("/equipment/windows")

    assert response.status_code == 200
    assert 'id="btn-equipment-open-bridge-gui"' in response.text
    assert response.text.count("Open Windows GUI") == 1
    assert 'data-equipment-proxy="btn-equipment-open-bridge-gui"' not in response.text
    assert 'id="equipment-saved-candidates" class="equipment-candidates equipment-saved-candidates-scroll"' in response.text
    assert 'id="equipment-bridge-console-frame"' not in response.text
    script = client.get("/static/windows_equipment.js").text
    assert 'window.open("/equipment/windows/console", "_blank", "noopener,noreferrer")' in script


def test_windows_equipment_saved_workers_expose_bounded_update_controls() -> None:
    client = TestClient(app)

    script = client.get("/static/windows_equipment.js").text

    for label in ("Check Update", "Update", "Rollback"):
        assert label in script
    assert "/api/equipment/windows/workers/${encodeURIComponent(candidateAlias)}/update" in script
    assert "/api/equipment/windows/workers/${encodeURIComponent(candidateAlias)}/rollback" in script
    assert 'data-action="check-update"' in script
    assert 'data-action="apply-update"' in script
    assert 'data-action="rollback-update"' in script


def test_windows_equipment_console_renders_locally_without_contacting_selected_bridge(monkeypatch) -> None:
    client = TestClient(app)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("The local operator console must not contact the selected bridge while rendering.")

    monkeypatch.setattr("app.main._equipment_bridge", fail_if_called)

    response = client.get("/equipment/windows/console")

    assert response.status_code == 200
    assert "ATR Windows PyAutoGUI Bridge" in response.text
    assert 'id="programManagerPanel"' in response.text
    assert "/equipment/windows/bridge-ui" in response.text
    assert 'localStorage.setItem("bridgeToken","atr-proxy-session")' in response.text
    assert "server-only-token" not in response.text


def test_windows_equipment_keeps_bridge_controls_in_the_primary_dashboard() -> None:
    client = TestClient(app)

    response = client.get("/equipment/windows")

    assert response.status_code == 200
    html = response.text
    assert 'class="equipment-workspace-actions"' not in html
    assert html.count('id="btn-equipment-open-bridge-gui"') == 1
    assert html.index('id="equipment-connection-workspace"') < html.index('id="btn-equipment-open-bridge-gui"')
    assert 'id="equipment-inline-controls"' in html
    assert 'id="equipment-advanced-controls"' not in html
    assert "Advanced Bridge Setup &amp; Audit" not in html
    assert html.index('id="equipment-inline-controls"') < html.index('id="equipment-subnet-input"')


def test_windows_equipment_uses_equal_profile_overview_cards() -> None:
    client = TestClient(app)

    response = client.get("/equipment/windows")

    assert response.status_code == 200
    assert 'class="panel equipment-profile-overview"' in response.text


def test_windows_equipment_bridge_ui_proxy_keeps_token_server_side(monkeypatch) -> None:
    class FakeBridge:
        def proxy_ui_request(self, *, method, resource_path, query_string, body, content_type):
            assert method == "GET"
            assert resource_path == ""
            assert query_string == ""
            assert body == b""
            assert content_type == ""
            return {
                "ok": True,
                "status_code": 200,
                "content_type": "text/html; charset=utf-8",
                "content": b"<html><body>Windows Bridge Console</body></html>",
            }

    monkeypatch.setattr("app.main._equipment_bridge", lambda: FakeBridge())
    client = TestClient(app)

    response = client.get("/equipment/windows/bridge-ui/")

    assert response.status_code == 200
    assert "Windows Bridge Console" in response.text
    assert "'/equipment/windows/bridge-ui'+input" in response.text
    assert "server-only-token" not in response.text


def test_windows_equipment_bridge_ui_proxy_offloads_bridge_request(monkeypatch) -> None:
    offloaded: list[str] = []
    original_to_thread = asyncio.to_thread

    async def tracked_to_thread(func, /, *args, **kwargs):
        offloaded.append(getattr(func, "__name__", "callable"))
        return await original_to_thread(func, *args, **kwargs)

    class FakeBridge:
        def proxy_ui_request(self, **kwargs):
            return {
                "ok": True,
                "status_code": 200,
                "content_type": "application/json; charset=utf-8",
                "content": b'{"ok":true}',
            }

    monkeypatch.setattr("app.main._equipment_bridge", lambda: FakeBridge())
    monkeypatch.setattr("app.main.asyncio.to_thread", tracked_to_thread)
    client = TestClient(app)

    response = client.get("/equipment/windows/bridge-ui/skills")

    assert response.status_code == 200
    assert offloaded == ["proxy_ui_request"]


def test_windows_equipment_bridge_ui_proxy_forwards_delete(monkeypatch) -> None:
    forwarded: list[dict[str, object]] = []

    class FakeBridge:
        def proxy_ui_request(self, **kwargs):
            forwarded.append(dict(kwargs))
            return {
                "ok": True,
                "status_code": 200,
                "content_type": "application/json; charset=utf-8",
                "content": b'{"ok":true,"status":"deleted"}',
            }

    monkeypatch.setattr("app.main._equipment_bridge", lambda: FakeBridge())
    client = TestClient(app)

    response = client.delete(
        "/equipment/windows/bridge-ui/programs/custom-probe?source=atr",
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "deleted"}
    assert forwarded == [
        {
            "method": "DELETE",
            "resource_path": "programs/custom-probe",
            "query_string": "source=atr",
            "body": b"",
            "content_type": "",
        }
    ]


def test_common_equipment_profile_test_generates_simulated_analysis_ready_evidence() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/equipment/profiles/utm_windows_v1/test",
        json={"confirm_execute": True, "vision_link_enabled": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["profile"]["simulate_utm_protocol"] is True
    assert payload["vision_link_request"] == {
        "requested": True,
        "profile_enabled": True,
        "required": False,
        "effective": True,
    }
    assert payload["analysis_handoff"]["status"] == "ready"
    assert all(payload["evidence"][key] for key in ("screenshot", "request_log", "csv"))


def test_equipment_profile_preflight_preserves_frontend_vision_link_selection() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/equipment/profiles/utm_windows_v1/preflight",
        json={"vision_link_enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["vision_link_request"] == {
        "requested": True,
        "profile_enabled": True,
        "required": False,
        "effective": True,
    }


def test_equipment_profile_vision_link_selection_persists_per_profile(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "equipment_workspace_settings.json"
    monkeypatch.setattr("app.main.EQUIPMENT_WORKSPACE_SETTINGS_PATH", settings_path)
    client = TestClient(app)

    disabled = client.post(
        "/api/equipment/profiles/utm_windows_v1/settings",
        json={"vision_link_enabled": False},
    )
    reloaded = client.get("/api/equipment/profiles/utm_windows_v1/state")

    assert disabled.status_code == 200
    assert disabled.json()["workspace_settings"] == {
        "vision_link_enabled": False,
        "vision_link_source": "stored",
    }
    assert reloaded.status_code == 200
    assert reloaded.json()["workspace_settings"] == {
        "vision_link_enabled": False,
        "vision_link_source": "stored",
    }
    assert json.loads(settings_path.read_text(encoding="utf-8"))["profiles"]["utm_windows_v1"] == {
        "vision_link_enabled": False,
    }


def test_equipment_profile_preflight_uses_persisted_vision_link_selection(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "equipment_workspace_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "schema": "atr.equipment_workspace_settings.v1",
                "profiles": {"utm_windows_v1": {"vision_link_enabled": False}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.main.EQUIPMENT_WORKSPACE_SETTINGS_PATH", settings_path)
    client = TestClient(app)

    response = client.post("/api/equipment/profiles/utm_windows_v1/preflight", json={})

    assert response.status_code == 200
    assert response.json()["vision_link_request"] == {
        "requested": False,
        "profile_enabled": True,
        "required": False,
        "effective": False,
    }


def test_equipment_agent_manager_owns_vision_link_selection() -> None:
    client = TestClient(app)
    manager = client.get("/equipment/agent-manager?profile_id=utm_windows_v1").text
    bridge = client.get("/equipment/windows").text

    assert "equipment-manager-vision-slot" in manager
    manager_script = client.get("/static/equipment_agent_manager.js").text
    assert 'data-field="vision.enabled"' in manager_script
    assert 'data-field="vision.task_id"' in manager_script
    assert 'data-field="vision.condition"' not in manager_script
    assert "payload.vision_tasks" in manager_script
    assert "Agentic Task" in manager_script
    assert 'data-field="agentic.task"' in manager_script
    assert "Operator label" not in manager_script
    assert "equipment-vision-link-enabled" not in bridge


def test_live_gui_runtime_shell_contains_operational_panels() -> None:
    client = TestClient(app)
    response = client.get("/live")

    assert response.status_code == 200
    html = response.text
    required_ids = [
        "live-agent-binder-list",
        "live-binder-context-menu",
        "live-report-panel",
        "live-backend-panel",
        "live-graph-panel",
        "live-artifact-panel",
        "live-timeline-detail-panel",
        "live-chat-target",
        "live-chat-mode",
        "live-chat-context-strip",
        "live-focus-strip",
        "live-stream-chip",
        "live-sync-chip",
        "live-fault-chip",
        "live-approval-panel",
        "live-quick-actions",
        "live-hover-tooltip",
        "live-shortcut-overlay",
        "btn-live-shortcuts-close",
        "live-timeline-strip",
        "live-device-strip",
        "btn-live-safe-stop",
        "live-emergency-recovery",
        "btn-live-emergency-resume",
        "btn-live-emergency-reset",
        "btn-live-bottom-collapse",
        "planning-chat-log",
        "planning-message-input",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in html
    assert "planning-live-body" in html
    assert "/static/styles.css?v=20260527-live-focus" in html
    assert "/static/planning.js?v=20260613-clean-stl-render-1" in html
    assert 'href="/static/styles.css?v=20260825-plc-safety-lifecycle-5"' in html
    assert 'src="/static/planning.js?v=20260901-equipment-overlay-1"' in html
    assert "Runtime Chat" in html
    assert "Safe Stop" in html
    assert "Pause Run" in html
    assert "Resume Run" in html
    assert "Handoff" in html
    assert "Graph" in html
    script_text = client.get("/static/planning.js").text
    for label in ["Overview / Summary", "Key Decisions", "Tool Calls Summary", "Validation / Quality Check", "Next Action"]:
        assert label in script_text
    for role_label in [
        "Orchestration Plan / Handoff Control",
        "Design Geometry / Manufacturability",
        "Manufacturing Digital Thread / Printer Runtime",
        "Lab Perception Signal Bus / Visual Evidence",
        "Lab Equipment / UTM Visual Control",
        "Bayesian Optimization / Candidate Selection",
        "Safety Gate / Continue-Stop Decision",
    ]:
        assert role_label in script_text


def test_live_gui_specimen_report_uses_live_print_job_cards() -> None:
    client = TestClient(app)
    script_text = client.get("/static/planning.js").text

    for card_title in [
        "Build Intent",
        "Printer Telemetry",
        "Readiness Gate",
        "Slice Profile",
        "Thermal / Material",
        "Transfer Queue",
        "Live Job Monitor",
        "Layer Preview",
        "Camera Evidence",
        "Post-Print Automation",
        "G-code Validation",
        "Handoff / Artifacts",
    ]:
        assert card_title in script_text

    assert "ar-spc-live-job-monitor-card" in script_text


def test_live_gui_specimen_agentic_progress_uses_current_run_completion_evidence() -> None:
    client = TestClient(app)
    script_text = client.get("/static/planning.js").text

    assert "function specimenCurrentPrintProgressStatus(" in script_text
    assert "function specimenCurrentAutoejectionProgressStatus(" in script_text
    assert "ctx.printerCompletionWait.status" in script_text
    assert "ctx.activeCamArtifact.spc_autoejection_confirmed === true" in script_text
    assert "specimenMonitorMatchesCurrentJob(ctx)" in script_text
    assert "ctx.autoejectionGate.status, ctx.monitor.snapshot.auto_ejection" not in script_text


def test_live_gui_chat_expand_keys_are_stable_across_rerenders() -> None:
    client = TestClient(app)
    script_text = client.get("/static/planning.js").text

    assert "function planningStableTextHash(" in script_text
    assert "function planningMessageStableToken(" in script_text
    assert "msg?.message_id" in script_text
    assert "msg?.event_id" in script_text
    assert "content:" in script_text
    assert 'key: `loop:${cycle}:${planningMessageStableToken(entry.msg, entry.index)}`' in script_text
    assert 'key: `loop:${cycleStartIndex}:${cycle}`' not in script_text


def test_live_gui_specimen_pending_input_is_not_rendered_as_hard_error() -> None:
    client = TestClient(app)
    script_text = client.get("/static/planning.js").text

    assert "function eventRequiresOperatorInput(event)" in script_text
    assert 'if (eventRequiresOperatorInput(event)) return "warning";' in script_text
    assert "const pendingInput = agentEvents.some(eventRequiresOperatorInput)" in script_text
    assert 'if (pendingInput) return running && activeAgent === agentId ? "running" : "waiting";' in script_text


def test_gui_favicon_is_available_to_all_runtime_pages() -> None:
    client = TestClient(app)
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in response.content

    for route in ["/", "/live", "/ide", "/evolution-lab", "/module-management"]:
        page = client.get(route)
        assert page.status_code == 200
        assert 'rel="icon" type="image/svg+xml" href="/static/favicon.svg"' in page.text


def test_live_gui_static_script_exposes_runtime_ide_adapters() -> None:
    client = TestClient(app)
    response = client.get("/static/planning.js")

    assert response.status_code == 200
    script = response.text
    for symbol in [
        "DEFAULT_LIVE_AGENTS",
        "refreshLiveAgentManifest",
        "/api/runtime/agent-manifests",
        "renderAgentDescriptorCards",
        "renderAgentDescriptorReportSections",
        "renderDescriptorChart",
        "renderDescriptorScatterPlot",
        "renderDescriptorLineChart",
        "renderDescriptorTableChart",
        "renderDescriptorHeatmapChart",
        "renderDescriptorCompoundChart",
        "renderDescriptorActions",
        "descriptorLayoutClass",
        "LIVE_RENDERER_PROFILES",
        "liveAgentRendererProfile",
        "presentation_only",
        "unsupported_renderer_id",
        "runDescriptorAction",
        "openDescriptorWorkspaceHandoff",
        "descriptorSelectorValue",
        "descriptor.chart",
        "descriptor.actions",
        "mini_bar_chart",
        "scatter_plot",
        "line_chart",
        "compound_chart",
        "ar-scatter-plot",
        "ar-line-chart",
        "ar-descriptor-table",
        "ar-descriptor-heatmap",
        "ar-descriptor-compound",
        "density-compact",
        "priority-high",
        "mobile-stack",
        "data-descriptor-action-url",
        "data-descriptor-api-action",
        "data-descriptor-workspace-handoff",
        "descriptor_action.workspace_handoff",
        "read_only_api",
        "workspace_handoff",
        "reportSections",
        "module descriptor report",
        "LIVE_AGENTS",
        "renderAgentBinder",
        "renderReportPanel",
        "renderBackendPanel",
        "renderBackendTraceSections",
        "renderGraphMiniPanel",
        "renderSelectedGraphNodeView",
        "renderArtifactPanel",
        "renderTimelinePanels",
        "eventTimelineKind",
        "isResolvedEmergencyLifecycleEvent",
        "eventStableKey",
        "renderSelectedEventCard",
        "runSelectedEventAction",
        "renderApprovalPanel",
        "pendingAgentQuestions",
        "handleQuestionAction",
        "answerAgentQuestion",
        "isRuntimeFaultEvent",
        "liveFaultEvents",
        "renderFaultCard",
        "updateLiveFaultChip",
        "handleFaultAction",
        "recordLiveAttentionAction",
        "clearLiveGraphSelection",
        "clearLiveTimelineSelection",
        "renderDeviceStrip",
        "liveBridgeContracts",
        "renderBridgeContractDeviceCards",
        "bridgeContractStatus",
        "bridgeContractActionSummary",
        "openBridgeContractWorkspace",
        "bridgeContractSafeActions",
        "bridgeContractWorkspaceHandoffActions",
        "runBridgeContractAction",
        "workspace_handoff",
        "handoff_required",
        "refreshLiveRunDetails",
        "resolveLiveApproval",
        "refreshLiveGraphPayload",
        "runLiveQuickAction",
        "setLiveQuickActionBusy",
        "setLiveBackendPlanningBusy",
        "liveBackendPlanningBusy",
        "fetchJsonOrThrow",
        "relativeTimeLabel",
        "compactRunId",
        "liveAgentShort",
        "setCompactTextWithTitle",
        "liveTokenUsageFromObject",
        "collectLiveTokenUsage",
        "updateLiveTokenChip",
        "setRuntimeChip",
        "updateLiveConnectionChips",
        "liveChatTargetForAgent",
        "markLiveSyncRefreshStart",
        "markLiveSyncComplete",
        "markLiveSyncError",
        "liveSyncIsStale",
        "markLiveStreamState",
        "LIVE_AUTO_REFRESH_MS",
        "LIVE_SYNC_STALE_MS",
        "LIVE_SYNC_ERROR_MS",
        "runLiveReportAction",
        "blockLiveExecutionForPendingApproval",
        "recordLiveOperatorEvent",
        "recordLiveIntentEvent",
        "liveNotificationCountsByAgent",
        "markLiveAgentRead",
        "syncOperatorReportStateFromEvents",
        "normalizePinnedFindingFromEvent",
        "operator_report_state_run_id",
        "liveSelectedTraceContext",
        "liveChatContextSummary",
        "liveModeShort",
        "liveRunningFlag",
        "renderLiveChatContextStrip",
        "renderLiveFocusStrip",
        "liveFocusChip",
        "focusDeviceEventFromCard",
        "selectLiveReportSection",
        "selectedReportSectionText",
        "selectedReportSectionPayload",
        "selectedReportSectionExportText",
        "selected_report_section",
        "live_selected_trace_id",
        "renderAcademicReportSections",
        "renderReportSection",
        "renderAgentSpecificReportSection",
        "agentSpecificReportProfile",
        "latestReportBoResult",
        "latestReportArtifacts",
        "selectedReportModel",
        "handleContextAction",
        "openBinderContextMenu",
        "pinAgentReportFromBinder",
        "evolutionTargetForAgent",
        "evolutionLabUrl",
        "openEvolutionLab",
        "liveSessionStorage",
        "persistPlanningSessionId",
        "LIVE_UI_STATE_KEY",
        "knownLiveAgent",
        "validLiveChatTarget",
        "resolveLiveChatTarget",
        "LIVE_CHAT_TARGET_SPECIALS",
        "liveUiStatePayload",
        "persistLiveUiState",
        "restoreLiveUiState",
        "LIVE_TOOLTIP_SELECTOR",
        "liveTooltipTarget",
        "liveTooltipText",
        "showLiveHoverTooltip",
        "hideLiveHoverTooltip",
        "isLiveEditableTarget",
        "toggleLiveShortcutOverlay",
        "setLiveBottomCollapsed",
        "liveShortcutKey",
        "runLiveKeyboardShortcut",
        "__liveGuiDebugSetState",
        "__liveGuiDebugSnapshot",
        "__liveGuiDebugRestoreOperatorReportState",
    ]:
        assert symbol in script


def test_live_gui_analysis_report_exposes_multifidelity_contract() -> None:
    client = TestClient(app)
    script = client.get("/static/planning.js").text
    runtime_script = client.get("/static/runtime_ide.js").text

    for token in [
        "renderAnalysisTrustScore",
        "renderAnalysisProvenance",
        "renderAnalysisCurveOverlay",
        "Trust Score / Gate",
        "UTM-FEA Agreement",
        "PINN Prediction",
        "Provenance",
        "multifidelity_comparison",
        "trust_score",
        "analysis_bo_handoff_v2",
    ]:
        assert token in script

    notification_source = script[
        script.index("function isAgentNotificationEvent"):
        script.index("function renderBackendRawSection")
    ]
    assert "isResolvedEmergencyLifecycleEvent(event)" in notification_source

    emergency_source = script[
        script.index("function isResolvedEmergencyLifecycleEvent"):
        script.index("function isAgentNotificationEvent")
    ]
    assert 'eventType === "run_complete"' in emergency_source
    assert "hasLaterEmergencyRecovery" in emergency_source
    assert "currentRunEventSources()" in emergency_source

    agent_status_source = script[
        script.index("function eventStatusForAgent"):
        script.index("function liveAgentIconHtml")
    ]
    assert "isResolvedEmergencyLifecycleEvent(event)" in agent_status_source

    fault_source = script[
        script.index("function isRuntimeFaultEvent"):
        script.index("function liveFaultEvents")
    ]
    assert "isResolvedEmergencyLifecycleEvent(event)" in fault_source

    for token in [
        "trust_score",
        "Trust",
        "latestAnalysisPayload",
    ]:
        assert token in runtime_script
    assert "const rendererProfile = liveAgentRendererProfile(liveSelectedAgent);" in script
    assert 'const reportAgentId = rendererProfile.reportAgent || String(liveSelectedAgent || "").toLowerCase();' in script
    assert 'reportAgentId === "design"' in script
    assert "const rendererProfile = liveAgentRendererProfile(agentId);" in script
    assert "const dashboardAgentId = rendererProfile.dashboardAgent && cardsByAgent[rendererProfile.dashboardAgent]" in script
    assert "cardsByAgent[dashboardAgentId]" in script
    assert "window.localStorage || window.sessionStorage" in script
    assert "autonomousLiveGuiUiState" in script
    assert 'new EventSource("/api/events/stream")' in script
    assert 'source.onopen = () => {' in script
    assert 'markLiveStreamState("live", eventTime);' in script
    assert 'markLiveSyncComplete();' in script
    assert 'markLiveSyncError(err);' in script
    assert 'refreshPlanningState({ background: true })' in script
    assert 'liveSyncIsStale()' in script
    assert 'liveRefreshInFlight' in script
    assert "restoreLiveUiState();" in script
    assert "persistLiveUiState();" in script
    assert 'setCompactTextWithTitle(planningStageLabel, `S:${stageLabel}`' in script
    assert 'setCompactTextWithTitle(liveActiveAgentChip, `A:${liveAgentShort(activeAgent)}`' in script
    assert 'setLiveBackendPlanningBusy(Boolean(liveLastSession.is_planning_busy));' in script
    assert 'planningThinkingCount <= 0 && !liveBackendPlanningBusy && !liveQuickActionBusy' in script
    assert 'backend_planning_busy: liveBackendPlanningBusy' in script
    assert "chat_context: liveChatContextSummary()" in script
    assert "`R:${liveModeShort(ctx.mode)}:${ctx.is_running ? \"ON\" : \"IDLE\"}`" in script
    assert "`Ref:${compactText(anchor || \"-\", 14)}`" in script
    assert "const snapshot = liveLastSnapshot || {};" in script
    assert "const state = session.state || snapshot.state || {};" in script
    assert "const state = liveLastSession.state || snapshot.state || {};" in script
    assert "runtime_ide_contract.device_bridges" in script
    assert "health_endpoint" in script
    assert "preflight_endpoint" in script
    assert "evidence_contracts" in script
    assert "open_workspace" in script
    assert 'data-bridge-action="open_workspace"' in script
    assert 'data-bridge-action="health_check"' in script
    assert "bridge_contract.open_workspace" in script
    assert "bridge_contract.health_check" in script
    assert "bridge_contract.preflight" in script
    assert "is_running: liveRunningFlag(session, snapshot, state)" in script
    assert "active_goal: state.active_goal ||" in script
    assert "running=${ctx.is_running ? \"true\" : \"false\"}" in script
    assert "goal=${ctx.active_goal ||" in script
    assert "live_chat_target_mode" in script
    assert "live_chat_target_resolved" in script
    assert "live_run_id" in script
    assert "live_mode" in script
    assert "live_stage" in script
    assert "live_is_running" in script
    assert "live_is_running: liveRunningFlag(session, snapshot, state)" in script
    assert "Boolean(session.is_running || snapshot.is_running)" not in script
    assert "const running = liveRunningFlag(liveLastSession, snapshot, state);" in script
    assert "live_active_goal" in script
    assert "setLiveChatTargetMode(liveChatTargetForAgent(liveSelectedAgent));" in script
    assert "event.ctrlKey || event.metaKey" in script
    assert "operator.binder.report_pinned" in script
    assert "binder.ctrl_click" in script
    assert "approval.blocked_execution" in script
    assert "requires_operator_approval" in script
    assert "live_graph.run_test" in script
    assert "liveNotificationCountsByAgent(session)" in script
    assert "currentRunEventSources()" in script
    assert "mergeRuntimeEventSources(liveRunEvents, liveRecentEvents)" in script
    assert "dedupeRuntimeEvents" in script
    assert "function renderPrinterDeviceStatusCard()" in script
    assert "payload.monitor_snapshot" in script
    assert 'snapshot.tool === "printer.status"' in script
    assert "async function refreshLivePrinterMonitorStatus(session = liveLastSession, options = {})" in script
    assert "function liveSpecimenAgentWorking(" in script
    assert "if (!options.force && !liveSpecimenAgentWorking(session)) return null;" in script
    assert 'fetchJsonOrThrow("/api/printer/status?mode=live&emit=1")' in script
    assert "workspace_monitor_snapshot" in script
    assert "function renderSpecimenPrintControlPanel(" in script
    assert "function renderSpecimenAgenticProgress(" in script
    assert "function openSpecimenProgressDetail(" in script
    assert 'let liveSpecimenProgressDetailStep = "";' in script
    assert "function renderSpecimenProgressDetailOverlay(" in script
    assert 'liveSpecimenProgressDetailStep = step;' in script
    assert 'liveSpecimenProgressDetailStep = "";' in script
    assert "renderSpecimenProgressDetailOverlay();" in script
    assert 'querySelector(".ar-design-gallery-overlay:not(.ar-spm-progress-detail-overlay)")' in script
    assert "renderDashboardCard(\"Now printing\"" in script
    assert "renderDashboardCard(\"Printing Progress\"" in script
    assert "renderDashboardCard(\"Print Monitoring\"" in script
    assert "renderDashboardCard(\"Printer Status\"" in script
    assert "renderDashboardCard(\"Print Connection\"" in script
    assert "renderDashboardCard(\"Agentic Progress\"" in script
    assert 'renderDashboardCard("Print Monitoring", renderSpecimenPrintMonitoringBody(ctx), { span: 4' in script
    assert 'renderDashboardCard("Printer Status", renderSpecimenPrinterStatusBody(ctx), { span: 4' in script
    assert 'renderDashboardCard("Print Connection", renderSpecimenPrintConnectionBody(ctx), { span: 4' in script
    assert 'renderDashboardCard("Agentic Progress", renderSpecimenAgenticProgressBody(ctx), { span: 12' in script
    assert 'data: { "spm-progress-step": "print_connection" }' in script
    assert "print_connection: \"Print Connection\"" in script
    assert "function renderSpecimenAgenticProgressNode(" in script
    assert "function specimenProgressActionLabel(" in script
    assert "function specimenProgressToneClass(" in script
    assert "function specimenAgenticOrchestratorMessages(" in script
    assert "function renderSpecimenAgenticOrchestratorMessagePanel(" in script
    assert "ar-spm-progress-node-rail" in script
    assert "ar-spm-orchestrator-message-panel" in script
    assert "ar-spm-progress-action" in script
    assert "tone-active" in script
    assert "tone-done" in script
    assert "ar-spm-progress-edge" in script
    assert "function renderMeaningfulDashboardRows(" in script
    assert "function specimenConnectionEvidenceRows(" in script
    assert "No current connection evidence." in script
    assert "const dataAttrs = options.data" in script
    assert "className: \"ar-spm-panel-card" in script
    assert "ar-spm-control-card" not in script
    assert "function specimenMaterialSlotColor(" in script
    assert "function renderSpecimenThermalDonut(" in script
    assert "function renderSpecimenThermalDonuts(" in script
    assert "ar-spm-thermal-donuts" in script
    assert "ar-spm-thermal-donut" in script
    assert "renderMiniBarChart(thermalRows" not in script
    assert "slot.tray_color" in script
    assert "ar-spm-material-swatch" in script
    assert "slice(0, 4)" in script
    assert "let liveSpecimenVideoPlaying = false" in script
    assert "let liveSpecimenVideoStartedAt = 0" in script
    assert "let liveSpecimenVideoStartSeq = 0" in script
    assert "let livePrinterMonitorOverride = null" in script
    assert "let livePrinterVideoOverride = null" in script
    assert "function specimenVideoPreviewUrl(" in script
    assert "function specimenVideoStreamUrl(" in script
    assert "function specimenVideoUrlWithCacheBuster(" in script
    assert 'fetchJsonOrThrow("/api/printer/video-status")' in script
    assert "function printerVideoCameraPanel(" in script
    assert "const cameraPanel = printerVideoCameraPanel(screen.camera_panel || screen.camera || {});" in script
    assert "function applyPrinterVideoStatusResult(" in script
    assert "livePrinterVideoOverride = {" in script
    assert "mergePrinterMonitorVideoStatusResult(" not in script
    assert "livePrinterMonitorOverride = event" in script
    assert "livePrinterMonitorOverride && eventMatchesCurrentRun(livePrinterMonitorOverride, runId)" in script
    assert "const frameSrc = active ? specimenVideoUrlWithCacheBuster(frameUrl) : frameUrl;" in script
    assert 'const loadingAttr = active ? "" : " loading=\\"lazy\\"";' in script
    assert 'data-spm-video-action="stop" aria-label="Stop 3DP video" title="Stop 3DP video"><span aria-hidden="true">■</span></button>' in script
    assert "const requestSeq = liveSpecimenVideoStartSeq + 1;" in script
    assert "if (!liveSpecimenVideoPlaying || requestSeq !== liveSpecimenVideoStartSeq) return;" in script
    assert "const statusResult = await refreshLivePrinterMonitorStatus(liveLastSession, { force: true });" in script
    assert "applyPrinterMonitorSnapshotResult(statusResult);" in script
    assert "const videoResult = await refreshLivePrinterVideoStatus();" in script
    assert "applyPrinterVideoStatusResult(videoResult);" in script
    assert "function renderSpecimenConnectionTestHeaderAction(" in script
    assert 'data-spm-connection-action="test"' in script
    assert 'action: renderSpecimenConnectionTestHeaderAction(ctx)' in script
    assert "async function runSpecimenConnectionTest(" in script
    assert "SPC CONNECTION TEST" in script
    assert 'tool: "printer.bambu.video_status"' in script
    assert "function renderSpecimenVideoHeaderControls(" in script
    assert 'data-spm-video-action="play"' in script
    assert 'data-spm-video-action="stop"' in script
    assert 'aria-label="Play 3DP video"' in script
    assert 'aria-label="Stop 3DP video"' in script
    assert 'action: renderSpecimenVideoHeaderControls(ctx)' in script
    assert 'refreshLivePrinterMonitorStatus(liveLastSession, { force: true })' in script
    assert "applyPrinterMonitorSnapshotResult(result)" in script
    assert "function startSpecimenVideoPlayback(" in script
    assert "function stopSpecimenVideoPlayback(" in script
    assert 'if (liveSelectedAgent !== "specimen") stopSpecimenVideoPlayback("agent_page_change", { render: false });' in script
    assert "data-spm-video-action" in script
    assert "data-spm-progress-step" in script
    assert "Print Monitoring" in script
    assert "Printer Status" in script
    assert "Agentic Progress" in script
    assert "isAgentNotificationEvent(event)" in script
    assert "eventMatchesCurrentRun(event)" in script
    assert "markLiveAgentRead(liveSelectedAgent, liveLastSession);" in script
    assert '<option value="current_agent">Current Agent</option>' in script
    assert '<option value="selected_agent">Selected Agent</option>' in script
    assert '<optgroup label="Specific Agent">' in script
    assert 'updateLiveTokenChip(session);' in script
    assert 'token_usage: collectLiveTokenUsage(liveLastSession)' in script
    assert '".runtime-chip[title]"' in script
    assert '".live-runtime-metrics span[title]"' in script
    assert 'document.addEventListener("mouseover", (event) => showLiveHoverTooltip(event.target));' in script
    assert 'document.addEventListener("keydown", (event) => {' in script
    assert 'runLiveKeyboardShortcut(event);' in script
    assert 'if (editable && !safetyShortcut) return false;' in script
    assert "persistPlanningSessionId(liveLastSession.planning_session_id)" in script
    assert "/api/events/recent" in script
    app_source = Path("app/main.py").read_text(encoding="utf-8")
    assert "stream.connected" in app_source
    assert "stream.heartbeat" in app_source
    assert "asyncio.wait_for(queue.get(), timeout=15.0)" in app_source
    assert "/api/runs/" in script
    assert "/api/run/safe-stop" in script
    assert "liveQuickActionBusy && action !== \"safe_stop\"" in script
    assert "setLiveQuickActionBusy(liveQuickActionBusy)" in script
    assert "armLiveSafeStop" in script
    assert "resetLiveSafeStopArm" in script
    assert "double_click_within_6s" in script
    assert "SAFE STOP ERROR" in script
    assert "/api/runtime/operator-event" in script
    assert "operator.report." in script
    assert "operator.context" in script
    assert "operator.attention" in script
    assert "attention_event_key" in script
    assert "/api/knowledge/relations/summary" in script
    assert "knowledge_relation_review" in script
    assert 'href="/knowledge#relations"' in script
    assert "Relation Reconciliation" in script
    assert '<div class="binder-title binder-title-att" title="Operator Attention">ATT</div>' in script
    assert '<div class="binder-title binder-title-att" title="Operator Attention">ATTENTION</div>' not in script
    assert "Operator attention is surfaced only through the ATT binder/report page." in script
    assert "Last-commit behavior: ATT content is rendered only after opening the ATT page." in script
    assert "Waiting for operator input:" not in script
    assert "Runtime attention required:" not in script
    assert "recordLiveAttentionAction(\"question\", \"answer\", event)" in script
    assert "recordLiveAttentionAction(\"fault\", \"backend\", event)" in script
    assert "operator.timeline" in script
    assert "report_rewrite_requested" in script
    assert "runtime_command_requested" in script
    assert "node_rerun_requested" in script
    assert "renderGraphGateControls" in script
    assert "runLiveGraphGateAction" in script
    assert "graph_change_requested" in script
    assert "graph_run_requested" in script
    assert "graph_run_test" in script
    assert "live_graph.run_test" in script
    assert "live_gui_graph_gate_save_version" in script
    assert "/api/graphs/${encodeURIComponent(graphId)}/validate" in script
    assert "/api/graphs/${encodeURIComponent(graphId)}/compile" in script
    assert "/api/graphs/${encodeURIComponent(graphId)}/save-version" in script
    assert "/api/graphs/${encodeURIComponent(graphId)}/run" in script
    assert "data-live-ide-link" in script
    assert "source=live_graph" in script
    assert "encodeURIComponent(ideNodeRef)" in script
    assert "recordLiveContextAction" in script
    assert "pinned_finding" in script
    assert "reviewed_at" in script
    assert "pinned_findings" in script
    assert "reviewed_agents" in script
    assert "iconPath" in script
    assert "/static/live_gui_icons/orchestrator.svg" in script
    assert "liveAgentIconHtml" in script
    assert 'join("\\n")' in script
    assert 'class="live-report-list">\\n' in script
    assert "live-report-section-body" in script
    assert "data-report-section-title" in script
    assert "live_selected_report_section" in script
    assert "live_selected_report_section_text" in script
    assert 'export_scope: "selected_report_section"' in script
    assert 'ask_scope: "selected_report_section"' in script
    assert "selected_report_section_key" in script
    assert 'renderReportSection("Artifacts"' in script
    styles = Path("web/static/styles.css").read_text(encoding="utf-8")
    assert "live-ide-sheen" in styles
    assert "live-ide-chip-sweep" in styles
    assert "live-report-section.selected" in styles
    assert "live-pinned-compare" in styles
    assert "live-pinned-compare-grid" in styles
    assert "live-pinned-finding-action" in styles
    assert ".ar-spm-panel-card" in styles
    assert ".ar-spm-monitoring-card .ar-spm-video-frame" in styles
    assert "aspect-ratio: 16 / 9" in styles
    assert "min-height: 280px" in styles
    assert ".ar-spm-thermal-donuts" in styles
    assert ".ar-spm-thermal-donut" in styles
    assert "conic-gradient" in styles
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in styles
    assert ".ar-spm-material-chip" in styles
    assert ".ar-spm-material-swatch" in styles
    assert ".ar-spm-video-header-controls" in styles
    assert ".ar-spm-video-icon-button" in styles
    assert ".ar-spm-progress-node-rail" in styles
    assert ".ar-spm-progress-edge" in styles
    assert ".ar-spm-progress-detail-overlay" in styles
    assert "position: fixed" in styles
    assert "100dvh" in styles
    assert ".ar-spm-control-card" not in styles
    assert "Runtime IDE visual effects" in styles or "IDE-effect unification" in styles
    icon_response = client.get("/static/live_gui_icons/orchestrator.svg")
    assert icon_response.status_code == 200
    assert "<svg" in icon_response.text
    live_html = client.get("/live").text
    assert "planning-live-body" in live_html
    assert "live-hover-tooltip" in live_html
    assert 'role="tooltip"' in live_html
    assert "live-shortcut-overlay" in live_html
    assert "live-chat-context-strip" in live_html
    assert "live-focus-strip" in live_html
    assert "selected runtime focus" in live_html
    assert "runtime chat context" in live_html
    assert "live-stream-chip" in live_html
    assert "live-sync-chip" in live_html
    assert "live-fault-chip" in live_html
    assert "SSE ..." in live_html
    assert "Sync -" in live_html
    assert "btn-live-bottom-collapse" in live_html
    assert "aria-keyshortcuts" in live_html
    assert 'aria-keyshortcuts="Alt+Shift+X"' in live_html
    assert 'aria-keyshortcuts="Control+Enter"' in live_html
    assert 'live-timeline-filter-label' in live_html
    assert 'data-timeline-filter="warning" title="Warning and approval events"' in live_html
    required_quick_actions = [
        "approve_next_step",
        "revise",
        "reject_next_step",
        "pause_run",
        "resume_run",
        "safe_stop",
        "dry_run",
    ]
    for action in required_quick_actions:
        assert f'data-quick-action="{action}"' in live_html
    removed_debug_quick_actions = [
        "explain_current_node",
        "rewrite_report_section",
        "open_backend",
        "run_node_test",
        "open_graph",
        "open_evolution",
    ]
    for action in removed_debug_quick_actions:
        assert f'data-quick-action="{action}"' not in live_html
    assert 'data-decision="cancelled">Revise' in script
    assert 'resolveLiveApproval(state.run_id, pending.approval_id, "cancelled")' in script
    assert 'data-report-action="evolve"' in script
    live_css = client.get("/static/styles.css").text
    assert "live-bottom-collapsed" in live_css
    assert "Live bottom dock containment" in live_css
    assert "Runtime Focus Strip" in live_css
    assert "Device trace focus" in live_css
    assert "live-device-inline-action" in live_css
    audit_script_for_layout = Path("tests/ui/live_runtime_ide_browser_audit.py").read_text(encoding="utf-8")
    assert "bottomDockContainment" in audit_script_for_layout
    assert "blankGraphSelection" in audit_script_for_layout
    assert "focusContextText" in audit_script_for_layout
    assert "deviceFocus" in audit_script_for_layout
    assert "pinnedCompareText" in audit_script_for_layout
    assert "pinnedFocusProbe" in audit_script_for_layout
    assert "blankTimelineSelection" in audit_script_for_layout
    assert "graphSelectionCleared" in script
    assert "live-fault-card" in live_css
    assert "live-ide-edge-dash" in live_css


    audit_script = Path("tests/ui/live_runtime_ide_browser_audit.py").read_text(encoding="utf-8")
    for symbol in ["LIVE_REFERENCE_IMAGE", "image_visual_metrics", "rgb_distance", "titleContrastOnPanel", "bright_ratio"]:
        assert symbol in audit_script


def test_live_gui_loop_archive_preserves_agent_messages() -> None:
    client = TestClient(app)
    script = client.get("/static/planning.js").text

    for token in [
        "isLoopArchiveAgentMessage",
        "isLoopArchiveVisibleMessage",
        "renderPlanningLoopArchiveMessageDetail",
        "group.messages.filter(isLoopArchiveVisibleMessage)",
        "isLoopSummary ? renderPlanningLoopArchiveMessageDetail",
        "loop-archive-system",
    ]:
        assert token in script


def test_live_gui_specimen_runtime_uses_generic_spc_bridge_labels() -> None:
    client = TestClient(app)
    script = client.get("/static/planning.js").text

    assert "Slicer / Artifact Settings" in script
    assert "Printer Bridge / SPC Readiness" in script
    assert "selected_printer" in script
    assert "preprint_gate" in script
    assert "readiness_levels" in script
    assert "autoejection" in script
    assert "autoejection_handoff" in script
    assert "recommended_consumer_agent" in script
    assert "requires_guardian_approval" in script
    assert "motion_started" in script
    assert "PrusaSlicer Settings" not in script
    assert "PrusaLink / Bridge" not in script
    assert "PrusaLink runtime evidence" not in script


def test_evolution_lab_supports_live_gui_query_prefill() -> None:
    client = TestClient(app)
    response = client.get("/evolution-lab?target_type=prompt&target_id=design&run_id=run-demo&source=live_gui")
    assert response.status_code == 200
    assert "ATR Self-Evolution Lab" in response.text
    assert "evolution-pipeline-output" in response.text
    assert "evolution-leaderboard-output" in response.text
    assert "evolution-history-output" in response.text
    assert "evolution-lineage-output" in response.text
    assert "evolution-evidence-output" in response.text
    assert "Knowledge Evidence Pack" in response.text
    assert "Candidate Leaderboard" in response.text

    script = client.get("/static/evolution_lab.js").text
    for symbol in [
        "queryParams",
        "applyQueryPrefill",
        "renderTaskHistory",
        "renderLineage",
        "renderPipeline",
        "renderLeaderboard",
        "renderEvidencePacks",
        "refreshEvidencePacks",
        "knowledge_evidence_pack_id",
        "refreshVariantsForTarget",
        "gateChecklistMarkup",
        "replayEvalMarkup",
        "Replay / Held-out Evaluation",
        "replay_eval",
        "loadTaskVariants",
        "loadVariant",
        "target_type",
        "target_id",
        "run_id",
        "No hardware is executed",
    ]:
        assert symbol in script

    packs = client.get("/api/knowledge/evolution-packs?target_type=prompt&target_id=design").json()
    assert packs["ok"] is True
    assert packs["target_type"] == "prompt"
    assert packs["target_id"] == "design"
    assert isinstance(packs["packs"], list)

    variants = client.get("/api/evolution/variants?target_type=prompt&target_id=design").json()
    assert variants["ok"] is True
    assert variants["target_type"] == "prompt"
    assert variants["target_id"] == "design"
    assert isinstance(variants["variants"], list)

    planning_script = client.get("/static/planning.js").text
    for symbol in [
        "renderKnowledgeReportDetails",
        "latestKnowledgeReport",
        "Knowledge Memory / Self-Evolution Evidence",
        "Self-Evolution Evidence Packs",
        "Agent Performance Ledger",
        "Evolution Outcome Attribution",
    ]:
        assert symbol in planning_script



def test_live_gui_package_compatibility_endpoints_expose_existing_runtime_contract() -> None:
    client = TestClient(app)

    route_paths = {getattr(route, "path", "") for route in app.routes}
    for path in [
        "/api/runtime/state",
        "/api/runtime/events",
        "/api/runtime/start",
        "/api/runtime/pause",
        "/api/runtime/resume",
        "/api/runtime/stop",
        "/api/runtime/safe-stop",
        "/api/runtime/emergency-stop",
        "/api/runtime/emergency-resume",
        "/api/runtime/emergency-reset",
        "/api/devices/state",
        "/api/agents",
        "/api/agents/{agent_id}/report",
        "/api/agents/{agent_id}/backend-trace",
        "/api/agents/{agent_id}/message",
        "/api/artifacts",
        "/api/artifacts/{artifact_id:path}",
        "/api/graphs/{graph_id}/save-version",
        "/api/approvals/{approval_id}/approve",
        "/api/approvals/{approval_id}/revise",
        "/api/approvals/{approval_id}/reject",
    ]:
        assert path in route_paths

    runtime_state = client.get("/api/runtime/state").json()
    assert runtime_state["ok"] is True
    assert runtime_state["compatibility"] == "atr_live_gui_package"
    assert "state" in runtime_state
    assert "system_resources" in runtime_state
    run_id = runtime_state["state"]["run_id"]

    devices = client.get("/api/devices/state").json()
    assert devices["ok"] is True
    assert devices["run_id"] == run_id
    assert any(item["device_id"] == "gpu" for item in devices["devices"])

    agents = client.get("/api/agents").json()
    assert agents["ok"] is True
    assert len(agents["agents"]) >= 11
    assert any(item["agent_id"] == "design" for item in agents["agents"])
    equipment_agent = next(item for item in agents["agents"] if item["agent_id"] == "equipment")
    assert equipment_agent["stage"] == "equipment"
    assert equipment_agent["module_id"] == "equipment"
    assert "Lab Equipment" in equipment_agent["label"]

    report = client.get("/api/agents/design/report").json()
    assert report["ok"] is True
    assert report["report"]["agent_id"] == "design"
    assert "sections" in report["report"]
    assert report["report"]["role_specific"]["title"] == "Design Geometry / Manufacturability"
    assert report["report"]["sections"]["role_specific"]["title"] == "Design Geometry / Manufacturability"
    assert any(row["label"] == "Geometry" for row in report["report"]["role_specific"]["focus_rows"])
    assert isinstance(report["report"]["process_steps"], list)
    assert isinstance(report["report"]["tool_calls"], list)
    assert isinstance(report["report"]["artifacts"], list)
    assert report["report"]["handoff"]["agent_stage"] == "design"

    orchestrator_report = client.get("/api/agents/orchestrator/report").json()["report"]
    assert orchestrator_report["role_specific"]["title"] == "Orchestration Supervisor / Follow-up Control"
    assert "followup_timeline" in orchestrator_report["role_specific"]
    assert "decision_register" in orchestrator_report["role_specific"]
    assert "handoff_registry" in orchestrator_report["role_specific"]

    specimen_report = client.get("/api/agents/specimen/report").json()["report"]
    assert specimen_report["role_specific"]["title"] == "Manufacturing Digital Thread / Printer Runtime"
    vision_report = client.get("/api/agents/vision/report").json()["report"]
    assert vision_report["role_specific"]["title"] == "Lab Perception Signal Bus / Visual Evidence"
    assert "vision_report" in vision_report["sections"]
    manipulation_report = client.get("/api/agents/manipulation/report").json()["report"]
    assert manipulation_report["role_specific"]["title"] == "Manipulation Agent / Runtime Supervision"
    assert "Pi0.5" not in manipulation_report["role_specific"]["title"]
    assert "manipulation_report" in manipulation_report["sections"]
    assert "robot_task_result" in manipulation_report["sections"]
    bo_report = client.get("/api/agents/bo/report").json()["report"]
    assert bo_report["role_specific"]["title"] == "Bayesian Optimization / Candidate Selection"
    guardian_report = client.get("/api/agents/guardian/report").json()["report"]
    assert guardian_report["role_specific"]["title"] == "Safety Gate / Continue-Stop Decision"

    trace = client.get("/api/agents/design/backend-trace").json()
    assert trace["ok"] is True
    assert trace["agent"]["agent_id"] == "design"
    assert isinstance(trace["events"], list)

    artifacts = client.get("/api/artifacts").json()
    assert artifacts["ok"] is True
    assert artifacts["run_id"] == run_id
    assert isinstance(artifacts["artifacts"], list)

    graph_payload = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    saved_graph = client.post(
        "/api/graphs/atr_closed_loop/save-version",
        json={"graph": graph_payload, "activate": False, "reason": "compatibility_test", "author": "pytest"},
    ).json()
    assert saved_graph["ok"] is True
    assert saved_graph["compatibility"] == "atr_live_gui_package"
    assert saved_graph["save_version_endpoint"] is True
    assert saved_graph["activated"] is False
    assert saved_graph["version"]["version_id"]

    approval = client.post(
        f"/api/runs/{run_id}/approvals",
        json={"title": "Compat approval", "reason": "package endpoint", "stage": "guardian", "safety_class": "compat"},
    ).json()
    approval_id = approval["approval_id"]
    package_request_event = _package_runtime_event(approval["event"])
    assert package_request_event["type"] == "approval_requested"
    assert package_request_event["event_type_internal"] == "approval.requested"
    assert package_request_event["timestamp"]
    assert package_request_event["stage"] == "guardian"
    assert package_request_event["graph_id"] == "atr_closed_loop"

    resolved = client.post(f"/api/approvals/{approval_id}/approve", json={"note": "compat route"}).json()
    assert resolved["ok"] is True
    assert resolved["approval_id"] == approval_id
    assert any(item["approval_id"] == approval_id for item in resolved["resolved"])
    package_resolved_event = _package_runtime_event(resolved["event"])
    assert package_resolved_event["type"] == "approval_granted"
    assert package_resolved_event["event_type_internal"] == "approval.resolved"
    assert package_resolved_event["severity"] == "info"

    rejected_approval = client.post(
        f"/api/runs/{run_id}/approvals",
        json={"title": "Compat reject approval", "reason": "package reject endpoint", "stage": "guardian", "safety_class": "compat"},
    ).json()
    rejected = client.post(f"/api/approvals/{rejected_approval['approval_id']}/reject", json={"note": "compat reject route"}).json()
    package_rejected_event = _package_runtime_event(rejected["event"])
    assert package_rejected_event["type"] == "approval_rejected"
    assert package_rejected_event["event_type_internal"] == "approval.resolved"
    assert package_rejected_event["severity"] == "warning"



def test_live_graph_run_records_graph_version_hash_evidence() -> None:
    client = TestClient(app)
    pre_state = client.get("/api/state").json()
    if pre_state.get("is_running"):
        pre_run_id = pre_state.get("state", {}).get("run_id")
        if pre_run_id:
            client.post(f"/api/runs/{pre_run_id}/stop")

    result = client.post(
        "/api/graphs/atr_closed_loop/run",
        json={"mode": "test", "goal": "pytest graph evidence run", "backend": None},
    ).json()
    run_id = str((result.get("run") or {}).get("run_id") or "")
    try:
        assert result["ok"] is True
        assert run_id
        assert result["graph_id"] == "atr_closed_loop"
        assert result["graph_hash"]
        assert result["graph_version"]
        assert (result["run"] or {}).get("graph_hash") == result["graph_hash"]
        assert (result["run"] or {}).get("graph_version") == result["graph_version"]

        snapshot = client.get("/api/state").json()
        runtime_graph = snapshot["state"]["run_metadata"]["runtime_graph"]
        assert runtime_graph["graph_id"] == "atr_closed_loop"
        assert runtime_graph["graph_hash"] == result["graph_hash"]
        assert runtime_graph["graph_version"] == result["graph_version"]

        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        created = next(event for event in events if event.get("event_type") == "run.created")
        compiled = next(event for event in events if event.get("event_type") == "graph.compiled")
        assert created["payload"]["graph_hash"] == result["graph_hash"]
        assert created["payload"]["graph_version"] == result["graph_version"]
        assert compiled["payload"]["graph_hash"] == result["graph_hash"]
        assert compiled["payload"]["graph_version"] == result["graph_version"]

        package_compiled = _package_runtime_event(compiled)
        assert package_compiled["type"] == "graph_compiled"
        assert package_compiled["graph_id"] == "atr_closed_loop"
        assert package_compiled["graph_version"] == result["graph_version"]
    finally:
        if run_id:
            client.post(f"/api/runs/{run_id}/stop")


def test_live_gui_operator_report_action_is_recorded_as_runtime_trace_event() -> None:
    client = TestClient(app)
    run_id = client.get("/api/state").json()["state"]["run_id"]

    response = client.post(
        f"/api/runs/{run_id}/operator-events",
        json={
            "event_type": "operator.report.exported",
            "message": "Design Agent report exported from Live GUI.",
            "action": "exported",
            "agent_id": "design",
            "node_id": "design",
            "trace_id": "trace-report-action-test",
            "event_key": "evt-report-action-test",
            "payload": {"selected_view": "report", "export_format": "txt"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["event"]["event_type"] == "operator.report.exported"
    assert payload["event"]["payload"]["operator_source"] == "live_gui"

    trace = client.get(f"/api/agents/design/backend-trace?run_id={run_id}").json()
    assert trace["ok"] is True
    assert any(event["event_type"] == "operator.report.exported" for event in trace["events"])


def test_live_gui_operator_report_pin_review_payloads_are_auditable() -> None:
    client = TestClient(app)
    run_id = client.get("/api/state").json()["state"]["run_id"]

    pin_response = client.post(
        f"/api/runs/{run_id}/operator-events",
        json={
            "event_type": "operator.report.pinned",
            "message": "Design Agent report finding pinned.",
            "action": "pinned",
            "agent_id": "design",
            "node_id": "design",
            "payload": {
                "pinned_finding": {
                    "agent_id": "design",
                    "label": "Design Agent",
                    "pinned_at": "2026-05-26T10:00:00Z",
                    "text": "Printable TPMS candidate selected.",
                    "run_id": run_id,
                },
                "pinned_at": "2026-05-26T10:00:00Z",
            },
        },
    )
    review_response = client.post(
        f"/api/runs/{run_id}/operator-events",
        json={
            "event_type": "operator.report.reviewed",
            "message": "Design Agent report marked reviewed.",
            "action": "reviewed",
            "agent_id": "design",
            "node_id": "design",
            "payload": {"reviewed_at": "2026-05-26T10:01:00Z"},
        },
    )

    assert pin_response.status_code == 200
    assert review_response.status_code == 200
    trace = client.get(f"/api/agents/design/backend-trace?run_id={run_id}").json()
    events = trace["events"]
    pinned = [event for event in events if event.get("event_type") == "operator.report.pinned"]
    reviewed = [event for event in events if event.get("event_type") == "operator.report.reviewed"]
    assert pinned
    assert reviewed
    assert pinned[-1]["payload"]["pinned_finding"]["text"] == "Printable TPMS candidate selected."
    assert reviewed[-1]["payload"]["reviewed_at"] == "2026-05-26T10:01:00Z"


def test_live_gui_operator_reply_is_recorded_as_runtime_trace_event() -> None:
    client = TestClient(app)
    cursor = len(controller.recent_events())

    response = client.post(
        "/api/planning/message",
        json={
            "message": "실험 수행",
            "session_id": "trace-contract-test",
            "constraints": {
                "live_chat_target": "specimen",
                "live_selected_agent": "specimen",
                "live_chat_mode": "command",
                "live_selected_trace_id": "trace-question-contract",
                "live_selected_event_key": "evt-question-contract",
            },
        },
    )

    assert response.status_code == 200
    new_events = controller.recent_events()[cursor:]
    user_reply_events = [event for event in new_events if event.get("event_type") == "user_reply"]
    assert user_reply_events
    event = user_reply_events[-1]
    assert event["payload"]["source"] == "live_gui"
    assert event["payload"]["agent_id"] == "specimen"
    assert event["payload"]["trace_id"] == "trace-question-contract"
    assert event["payload"]["event_key"] == "evt-question-contract"
    assert event["payload"]["latest"]["content"] == "실험 수행"

    trace = client.get("/api/agents/specimen/backend-trace").json()
    assert trace["ok"] is True
    assert any(item.get("event_type") == "user_reply" for item in trace["events"])
    assert event["payload"]["target_agent_id"] == "specimen"
    assert event["payload"]["selected_agent_id"] == "specimen"
    assert event["payload"]["selected_trace_id"] == "trace-question-contract"
    assert event["payload"]["selected_event_key"] == "evt-question-contract"


def test_live_gui_operator_reply_separates_target_agent_from_selected_context() -> None:
    client = TestClient(app)
    cursor = len(controller.recent_events())

    response = client.post(
        "/api/planning/message",
        json={
            "message": "테스트 모드",
            "session_id": "trace-target-context-test",
            "constraints": {
                "live_chat_target": "specimen",
                "live_chat_target_resolved": "specimen",
                "live_chat_target_mode": "selected_agent",
                "live_selected_agent": "orchestrator",
                "live_selected_graph_node_id": "specimen",
                "live_selected_node_id": "specimen",
                "live_selected_trace_id": "trace-specimen-question",
                "live_selected_event_key": "evt-specimen-question",
                "live_selected_event_id": "evt-specimen-question",
                "live_selected_event_type": "agent_question",
                "live_selected_report_section": "Specimen Bridge Prompt",
                "live_selected_report_section_text": "Specimen bridge mode required. Options: virtual bridge, installed printer, or actual print.",
                "live_run_id": "run-context-contract",
                "live_mode": "live",
                "live_stage": "specimen",
                "live_is_running": True,
                "live_active_goal": "Verify run-state preservation",
                "live_chat_mode": "command",
            },
        },
    )

    assert response.status_code == 200
    new_events = controller.recent_events()[cursor:]
    user_reply_events = [event for event in new_events if event.get("event_type") == "user_reply"]
    assert user_reply_events
    event = user_reply_events[-1]
    payload = event["payload"]
    assert payload["agent_id"] == "specimen"
    assert payload["target_agent_id"] == "specimen"
    assert payload["selected_agent_id"] == "orchestrator"
    assert payload["node_id"] == "specimen"
    assert payload["selected_node_id"] == "specimen"
    assert payload["selected_graph_node_id"] == "specimen"
    assert payload["trace_id"] == "trace-specimen-question"
    assert payload["selected_trace_id"] == "trace-specimen-question"
    assert payload["event_key"] == "evt-specimen-question"
    assert payload["selected_event_key"] == "evt-specimen-question"
    assert payload["selected_event_type"] == "agent_question"
    assert payload["selected_report_section"] == "Specimen Bridge Prompt"
    assert payload["selected_report_section_text"] == "Specimen bridge mode required. Options: virtual bridge, installed printer, or actual print."
    assert payload["selected_report_section_text_excerpt"] == "Specimen bridge mode required. Options: virtual bridge, installed printer, or actual print."
    assert payload["run_context"] == {
        "run_id": "run-context-contract",
        "mode": "live",
        "stage": "specimen",
        "is_running": True,
        "active_goal": "Verify run-state preservation",
    }
    assert payload["live_run_id"] == "run-context-contract"
    assert payload["live_mode"] == "live"
    assert payload["live_stage"] == "specimen"
    assert payload["live_is_running"] is True
    assert payload["live_active_goal"] == "Verify run-state preservation"
    assert payload["chat_target_mode"] == "selected_agent"

    trace = client.get("/api/agents/specimen/backend-trace").json()
    assert trace["ok"] is True
    assert any(
        item.get("event_type") == "user_reply"
        and (item.get("payload") or {}).get("trace_id") == "trace-specimen-question"
        for item in trace["events"]
    )


def test_live_gui_equipment_report_recovers_incident_from_hardware_alert() -> None:
    client = TestClient(app)
    original_metadata = dict(controller._state.run_metadata)
    incident = {
        "schema": "incident_record.v1",
        "incident_id": "incident-live-report-001",
        "device_class": "utm",
        "component": "utm_data_export",
        "failure_code": "UTM_DATA_TIMEOUT",
        "corrective_action": "Verify UTM CSV export and retry.",
    }
    alert = {
        "schema": "hardware_alert.v1",
        "alert_id": "alert-live-report-001",
        "device_class": "utm",
        "component": "utm_data_export",
        "severity": "blocking",
        "failure_code": "UTM_DATA_TIMEOUT",
        "status": "blocked",
        "blocks_workflow": True,
        "requires_ack": True,
        "guardian_route_hint": "stop",
        "guardian_decision": {
            "schema": "guardian_decision.v1",
            "decision": "safe_stop",
            "requires_human_approval": True,
            "risk_score": 0.91,
        },
        "guardian_contract": {"ok_for_next_stage": False, "requires_human_approval": True, "risk_flags": ["data_timeout"]},
        "incident_record": incident,
    }
    try:
        controller._state.run_metadata.update(
            {
                "hardware_alerts": [],
                "incident_records": [],
                "guardian_gates": [],
                "latest_guardian_gate": {},
                "latest_guardian_gate_decision": {},
                "equipment_result": {
                    "tool": "equipment.pyautogui.run",
                    "status": "blocked",
                    "program_id": "utm_compression_start_v1",
                    "failure_code": "UTM_DATA_TIMEOUT",
                },
                "equipment_report": {
                    "schema": "equipment_report.v1",
                    "bridge": {"provider": "windows_pyautogui", "connection_status": "ready"},
                    "control_plan": {"program_id": "utm_compression_start_v1"},
                    "screen_checks": [],
                    "vision_cross_checks": {"all_required_ok": False},
                    "physical_checks": {},
                    "data_acquisition": {"status": "timeout"},
                    "cross_checks": {"data_parse_probe_ok": False, "save_export_responsibility_ok": False},
                    "decision": {
                        "equipment_status": "blocked",
                        "handoff_status": "blocked",
                        "failure_code": "UTM_DATA_TIMEOUT",
                        "blocking_reasons": ["UTM_DATA_TIMEOUT"],
                    },
                    "hardware_alert": alert,
                },
                "utm_data_ready": {"schema": "utm_data_ready.v1", "status": "blocked", "guardian_status": "block"},
                "equipment_handoff": {"schema": "utm_data_ready.v1", "status": "blocked"},
            }
        )

        response = client.get("/api/agents/equipment/report")
        assert response.status_code == 200
        role_specific = response.json()["report"]["role_specific"]
        safety_gate = role_specific["safety_gate"]
        assert safety_gate["guardian_status"] == "block"
        assert safety_gate["hardware_alert_count"] == 1
        assert safety_gate["incident_count"] == 1
        assert safety_gate["incident_records"][0]["incident_id"] == "incident-live-report-001"
        assert safety_gate["blocks_workflow"] is True
        assert safety_gate["emergency_stop_evidence"]["corrective_action"] == "Verify UTM CSV export and retry."
    finally:
        controller._state.run_metadata.clear()
        controller._state.run_metadata.update(original_metadata)


def test_live_gui_equipment_report_exposes_utm_visual_control_contract() -> None:
    client = TestClient(app)
    original_metadata = dict(controller._state.run_metadata)
    csv_path = Path("/tmp/atr/utm.csv")
    try:
        controller._state.run_metadata.update(
            {
                "hardware_alerts": [],
                "incident_records": [],
                "guardian_gates": [],
                "latest_guardian_gate": {},
                "latest_guardian_gate_decision": {},
                "equipment_result": {
                    "tool": "equipment.pyautogui.run",
                    "status": "verified_complete",
                    "program_id": "utm_compression_start_v1",
                    "result_file": str(csv_path),
                },
                "equipment_report": {
                    "schema": "equipment_report.v1",
                    "report_version": "lab_equipment_utm_visual_control_v1",
                    "task_id": "utm_compression_test",
                    "bridge": {
                        "provider": "windows_pyautogui",
                        "connection_status": "ready",
                        "pyautogui_available": True,
                        "live_execute_enabled": True,
                    },
                    "preconditions": {"fixture_ready": True},
                    "control_plan": {
                        "program_id": "utm_compression_start_v1",
                        "macro_version": "v1",
                        "locator_backend": "image",
                        "profile": {
                            "program_id": "utm_compression_start_v1",
                            "profile_memory_path": "memory/equipment_utm_profile.json",
                            "profile_memory_applied": True,
                            "locator_count": 4,
                        },
                    },
                    "vision_requests": [{"check_id": "utm_pre_start"}],
                    "vision_cross_checks": {
                        "required": ["utm_pre_start", "utm_motion_confirm", "utm_test_complete"],
                        "checks": {
                            "utm_pre_start": {"ok": True, "source": "test"},
                            "utm_motion_confirm": {"ok": True, "source": "test"},
                            "utm_test_complete": {"ok": True, "source": "test"},
                        },
                        "all_required_ok": True,
                        "blocking_reasons": [],
                        "evidence_frame_ids": ["frame-1"],
                    },
                    "screen_checks": [
                        {"checkpoint": "before_start", "ok": True, "state": "ready", "screenshot_artifact": "screen-before"},
                        {"checkpoint": "after_start", "ok": True, "state": "running", "screenshot_artifact": "screen-running"},
                        {"checkpoint": "after_complete", "ok": True, "state": "complete", "screenshot_artifact": "screen-complete"},
                    ],
                    "artifact_records": [
                        {"kind": "screen_png", "artifact_id": "screen-before", "local_path": "artifacts/equipment/run-test/screens/before.png"},
                        {"kind": "screen_png", "artifact_id": "screen-running", "local_path": "artifacts/equipment/run-test/screens/running.png"},
                        {"kind": "utm_csv", "artifact_id": "utm-csv-1", "local_path": str(csv_path), "row_count_probe": 80},
                    ],
                    "artifact_refs": ["artifacts/equipment/run-test/screens/before.png", "artifacts/equipment/run-test/screens/running.png", str(csv_path)],
                    "screen_evidence_refs": ["artifacts/equipment/run-test/screens/before.png", "artifacts/equipment/run-test/screens/running.png"],
                    "data_evidence_refs": [str(csv_path)],
                    "live_evidence_audit": {
                        "required_for_handoff": True,
                        "screen_evidence": {
                            "ok": True,
                            "required_checkpoints": ["before_start", "after_start", "after_complete"],
                            "observed_checkpoints": ["before_start", "after_start", "after_complete"],
                            "missing_checkpoints": [],
                        },
                        "linux_artifact_pull": {
                            "ok": True,
                            "status": "pulled_to_linux",
                            "linux_path": str(csv_path),
                            "data_path_exists": True,
                            "parse_probe_ok": True,
                        },
                        "save_export": {
                            "ok": True,
                            "save_method": "windows_export_watch",
                            "save_attempted_by_agent": True,
                            "save_confirmation_screen_ok": True,
                            "windows_path": "C:/ATR/utm_exports/specimen.csv",
                            "linux_path": str(csv_path),
                            "recognized_save_method": True,
                        },
                        "vision_evidence": {
                            "ok": True,
                            "all_required_ok": True,
                            "evidence_frame_ids": ["frame-1"],
                        },
                        "request_audit_log": {
                            "ok": True,
                            "path": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                            "event_count": 4,
                            "recent_paths": ["/health", "/programs", "/execute", "/request-log"],
                            "execute_event_seen": True,
                            "execute_event_count": 1,
                            "execute_payload_event_count": 1,
                            "execute_run_ids": [controller._state.run_id],
                            "execute_sequence_ids": ["seq-live-utm"],
                            "execute_specimen_ids": ["specimen-test"],
                            "execute_program_ids": ["utm_compression_start_v1"],
                            "execute_identity_required": True,
                            "execute_identity_present": True,
                            "execute_identity_match": True,
                            "last_execute_at": "2026-05-30T00:00:00Z",
                        },
                    },
                    "failure_retry_table": [
                        {"step": "SAVE_EXPORT", "status": "warning", "detail": "checked", "fallback_macro": "utm_manual_save_csv_v1", "recommended_action": "none"}
                    ],
                    "recovery": {
                        "status": "not_required",
                        "retry_count": 1,
                        "fallback_macros": ["utm_manual_save_csv_v1"],
                        "operator_intervention_required": False,
                        "recommended_action": "analysis_agent"
                    },
                    "physical_checks": {
                        "vision_motion_confirmed": True,
                        "specimen_alignment_ok": True,
                        "fixture_safe_to_access": True,
                        "evidence_frame_ids": ["frame-1"],
                    },
                    "data_acquisition": {
                        "status": "pulled_to_linux",
                        "save_method": "windows_export_watch",
                        "save_attempted_by_agent": True,
                        "save_confirmation_screen_ok": True,
                        "windows_path": "C:/ATR/utm_exports/specimen.csv",
                        "linux_path": str(csv_path),
                        "sha256": "abc123",
                        "size_bytes": 1234,
                        "row_count_probe": 80,
                        "columns_probe": ["time_s", "displacement_mm", "force_N"],
                    },
                    "cross_checks": {
                        "screen_started": True,
                        "physical_motion_started": True,
                        "save_completed": True,
                        "data_file_created": True,
                        "data_parse_probe_ok": True,
                        "save_export_responsibility_ok": True,
                    },
                    "decision": {
                        "equipment_status": "verified_complete",
                        "handoff_status": "ready_for_analysis",
                        "failure_code": None,
                        "blocking_reasons": [],
                        "recommended_next_agent": "analysis_agent",
                    },
                },
                "utm_data_ready": {
                    "schema": "utm_data_ready.v1",
                    "status": "ready",
                    "guardian_status": "allow",
                    "result_file": str(csv_path),
                    "evidence_refs": [str(csv_path)],
                },
                "equipment_handoff": {
                    "schema": "utm_data_ready.v1",
                    "status": "ready_for_analysis",
                    "program_id": "utm_compression_start_v1",
                    "result_file": str(csv_path),
                },
            }
        )

        response = client.get("/api/agents/equipment/report")
        assert response.status_code == 200
        role_specific = response.json()["report"]["role_specific"]
        assert role_specific["title"] == "Lab Equipment / UTM Visual Control"
        assert role_specific["control_trace"]["program_id"] == "utm_compression_start_v1"
        assert role_specific["visual_assertion"]["screen_checks_passed"] == 3
        assert role_specific["physical_verification"]["all_required_ok"] is True
        assert role_specific["data_ledger"]["linux_path"] == str(csv_path)
        assert role_specific["data_ledger"]["parse_ready"] is True
        assert role_specific["data_ledger"]["save_export_responsibility_ok"] is True
        assert role_specific["data_ledger"]["save_attempted_by_agent"] is True
        assert role_specific["data_ledger"]["save_confirmation_screen_ok"] is True
        assert role_specific["handoff_gate"]["handoff_status"] == "ready_for_analysis"
        assert role_specific["handoff_gate"]["save_export_responsibility_ok"] is True
        assert role_specific["artifact_ledger"]["screen_evidence_count"] == 2
        assert role_specific["artifact_ledger"]["data_evidence_refs"] == [str(csv_path)]
        assert role_specific["live_evidence_audit"]["screen_evidence"]["ok"] is True
        assert role_specific["handoff_gate"]["live_evidence_audit"]["linux_artifact_pull"]["ok"] is True
        assert role_specific["failure_recovery"]["retry_count"] == 1
        assert role_specific["failure_recovery"]["fallback_macros"] == ["utm_manual_save_csv_v1"]
        assert role_specific["safety_gate"]["guardian_status"] == "allow"
        assert role_specific["safety_gate"]["hardware_alert_count"] == 0
        assert role_specific["safety_gate"]["blocks_workflow"] is False
        assert role_specific["live_evidence_audit"]["request_audit_log"]["execute_event_seen"] is True
        assert role_specific["live_evidence_audit"]["save_export"]["ok"] is True

        script = client.get("/static/planning.js").text
        for token in [
            "latestEquipmentReport",
            "renderEquipmentReportDetails",
            "renderEquipmentRuntimeCard",
            "Lab Equipment Runtime Event",
            "Macro Command",
            "Visual Assertion",
            "Data Acquisition",
            "target_ui",
            "screenshot_artifact",
            "failure_code",
            "artifact_pull_status",
            "Screen-State Assertions",
            "Vision Physical Cross-Checks",
            "UTM Data Ledger",
            "Handoff Gate / Blocking Reasons",
            "Safety Gate / Guardian",
            "Artifact / Evidence Ledger",
            "Failure / Recovery",
            "Live Evidence Audit",
            "screen_evidence_complete",
            "live_evidence_audit",
            "screen_evidence_refs",
            "failure_retry_table",
            "request_log_execute_seen",
            "request_log_last_execute_at",
            "bridge_host",
            "remote_server_version",
            "remote_script_version",
            "latestEquipmentSkillExecution",
            "Equipment Skill Execution",
            "Recovery Boundary",
            "completed_segments",
            "client_latency_ms",
            "pyautogui_failsafe",
            "pyautogui_pause",
            "data_parse_probe_ok",
            "save_export_responsibility_ok",
            "save_export_ok",
            "Save/Export",
            "renderGuardianReportDetails",
            "liveGuardianStatusPayload",
            "guardian_status_report.v1",
            "/guardian/status",
            "Graph-Wide Risk Map",
            "Safety Budget",
            "Live Device Heartbeat",
            "Safe-Stop Verification",
            "Evidence Completeness",
            "Self-Evolution Gate",
            "guardian_safety_budget.v1",
            "guardian_safe_stop_verification.v1",
            "guardian_evidence_completeness.v1",
            "guardian_self_evolution_gate.v1",
            "/guardian/incidents/",
            "Blocked Actions",
            "Approval Queue",
            "Incident / Near-Miss Ledger",
            "Policy / Version Panel",
            "Device / Data Integrity",
            "live-guardian-note-action",
        ]:
            assert token in script
        css = client.get("/static/styles.css").text
        for token in [
            "live-guardian-risk-grid",
            "live-guardian-risk-card",
            "live-guardian-incident-card",
        ]:
            assert token in css
    finally:
        controller._state.run_metadata.clear()
        controller._state.run_metadata.update(original_metadata)


def test_live_gui_equipment_dashboard_uses_operational_card_layout() -> None:
    client = TestClient(app)

    script = client.get("/static/planning.js").text

    for token in (
        'renderDashboardCard("Bridge / Runtime", renderEquipmentBridgeRuntime',
        'renderDashboardCard("Active Program / Skill", renderEquipmentActiveExecution',
        'renderDashboardCard("Recovery Boundary", renderEquipmentRecoveryBoundary',
        'renderDashboardCard("Agentic Progress", renderEquipmentAgenticProgress',
        'renderDashboardCard("Execution Evidence", renderEquipmentExecutionEvidence',
        'renderDashboardCard("Handoff", renderEquipmentHandoff',
        "function equipmentProgressSteps(",
        'class="ar-vis-agentic-progress"',
    ):
        assert token in script
    assert 'renderEquipmentAgenticProgress(ctx), { span: 12' in script
    assert 'renderEquipmentExecutionEvidence(ctx), { span: 8' in script


def test_live_gui_equipment_dashboard_projects_recorded_cycle_overlay() -> None:
    client = TestClient(app)

    script = client.get("/static/planning.js").text

    for token in (
        "ATREquipmentAgenticTaskModel",
        "function equipmentCycleContext(",
        "function renderEquipmentCycleHeader(",
        "function renderEquipmentMethodValues(",
        "function renderEquipmentScreenTransitions(",
        "function renderEquipmentRawDataReadiness(",
        'renderDashboardCard("Method Values", renderEquipmentMethodValues',
        'renderDashboardCard("Screen Transitions", renderEquipmentScreenTransitions',
        'renderDashboardCard("Raw Data / Next Specimen", renderEquipmentRawDataReadiness',
        "workflow_agentic_task",
        "required_entry_gate",
    ):
        assert token in script

    html = client.get("/live").text
    assert "/static/equipment_agentic_task_model.js" in html


def test_live_gui_equipment_cycle_overlay_has_no_direct_test_execution_action() -> None:
    client = TestClient(app)

    script = client.get("/static/planning.js").text
    overlay_start = script.index("function renderEquipmentCycleHeader(")
    overlay_end = script.index("function renderEquipmentDashboardCards(", overlay_start)
    overlay = script[overlay_start:overlay_end]

    assert "Start Test" not in overlay
    assert "runEquipmentLiveAction" not in overlay
    assert 'data-equipment-live-action="execute"' not in overlay


def test_live_gui_equipment_screen_transition_card_renders_bounded_evidence_fields() -> None:
    client = TestClient(app)

    script = client.get("/static/planning.js").text
    start = script.index("function renderEquipmentScreenTransitions(")
    end = script.index("function renderEquipmentRawDataReadiness(", start)
    renderer = script[start:end]

    for token in ("before_frame", "after_frame", "locator_id", "postcondition"):
        assert token in renderer


def test_live_gui_equipment_cycle_cards_are_additive_only_when_overlay_exists() -> None:
    client = TestClient(app)

    script = client.get("/static/planning.js").text
    start = script.index("function renderEquipmentDashboardCards(")
    end = script.index("function renderAnalysisDashboardCards(", start)
    renderer = script[start:end]

    assert "const cycleAvailable = equipmentCycleContext(ctx).available" in renderer
    assert "cycleAvailable ?" in renderer


def test_live_gui_equipment_cycle_uses_active_profile_and_inflight_flow_checkpoint() -> None:
    client = TestClient(app)

    script = client.get("/static/planning.js").text
    refresh_start = script.index("async function refreshEquipmentRuntimeSnapshot(")
    refresh_end = script.index("function ensureEquipmentRuntimeSnapshot(", refresh_start)
    refresh = script[refresh_start:refresh_end]
    context_start = script.index("function equipmentCycleContext(")
    context_end = script.index("function equipmentCanonicalProgressSteps(", context_start)
    context = script[context_start:context_end]

    assert "activeEquipmentProfileId" in refresh
    assert 'profiles/utm_windows_v1/skill-flow' not in refresh
    assert "run_id=${encodeURIComponent(activeRunId)}" in refresh
    for token in (
        "skillFlowExecution",
        "active_block",
        "transitions",
        "flowExecutionMatchesRun",
        "flowExecutionIsActive",
    ):
        assert token in context
    assert context.index("activeFlowExecution.workflow_agentic_task") < context.index("equipment.workflow_agentic_task")


def test_live_gui_run_transition_clears_equipment_run_scoped_snapshots() -> None:
    client = TestClient(app)

    script = client.get("/static/planning.js").text
    start = script.index("function resetLiveRunScopedStateForAuthoritativeSession(")
    end = script.index("function restoreLiveUiState(", start)
    reset = script[start:end]

    for token in (
        "liveEquipmentRuntimeSnapshot = null",
        "liveEquipmentSkillFlowSnapshot = null",
        "liveEquipmentRuntimeRefreshedAt = 0",
        'liveEquipmentRuntimeError = ""',
        "liveEquipmentRuntimeRefreshSeq += 1",
        "liveEquipmentRuntimeRefreshInFlight = null",
    ):
        assert token in reset

    refresh_start = script.index("async function refreshEquipmentRuntimeSnapshot(")
    refresh_end = script.index("function ensureEquipmentRuntimeSnapshot(", refresh_start)
    refresh = script[refresh_start:refresh_end]
    assert "const refreshSeq = ++liveEquipmentRuntimeRefreshSeq" in refresh
    assert "refreshSeq !== liveEquipmentRuntimeRefreshSeq" in refresh
    assert "requestedRunId !== liveCurrentRunId()" in refresh


def test_live_gui_equipment_cycle_header_renders_execution_identity_and_csv_artifact_link() -> None:
    client = TestClient(app)

    script = client.get("/static/planning.js").text
    header_start = script.index("function renderEquipmentCycleHeader(")
    header_end = script.index("function equipmentCycleDisplayValue(", header_start)
    header = script[header_start:header_end]
    raw_start = script.index("function renderEquipmentRawDataReadiness(")
    raw_end = script.index("function renderEquipmentDashboardCards(", raw_start)
    raw = script[raw_start:raw_end]

    for token in ("profile_id", "flow_version", "run_id", "specimen_id"):
        assert token in header
    assert "equipmentArtifactUrl" in raw
    assert 'target="_blank"' in raw


def test_live_gui_equipment_actions_are_passive_and_reuse_existing_routes() -> None:
    client = TestClient(app)

    script = client.get("/static/planning.js").text

    for token in (
        'data-equipment-live-action="test"',
        'data-equipment-live-action="open"',
        'data-equipment-live-action="refresh"',
        '"/api/equipment/windows/config"',
        '"/api/equipment/windows/test"',
        'window.open("/equipment/windows", "_blank", "noopener,noreferrer")',
    ):
        assert token in script
    action_start = script.index("async function runEquipmentLiveAction")
    action_end = script.index("function renderEquipmentLiveHeaderActions", action_start)
    assert "/execute" not in script[action_start:action_end]


def test_live_gui_equipment_progress_uses_canonical_runtime_projection() -> None:
    client = TestClient(app)

    script = client.get("/static/planning.js").text

    assert '"/api/equipment/runtime/current"' in script
    assert "run_id=${encodeURIComponent(activeRunId)}" in script
    assert "canonicalExecution" in script
    assert "canonicalProjection" in script
    assert "equipmentCanonicalProgressSteps" in script
    progress_start = script.index("function equipmentProgressSteps(")
    progress_end = script.index("function renderEquipmentAgenticProgress", progress_start)
    assert "equipmentCanonicalProgressSteps" in script[progress_start:progress_end]


def test_equipment_runtime_projection_is_shared_by_state_workspace_and_runtime_ide(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.main as main_module
    from utils.equipment_runtime_service import EquipmentRuntimeService

    runtime_root = tmp_path / "equipment_runtime"
    monkeypatch.setattr(main_module, "EQUIPMENT_RUNTIME_ROOT", runtime_root)
    runtime = EquipmentRuntimeService(runtime_root).begin(
        sequence_id="projection-sequence",
        run_id="projection-run",
        experiment_id="projection-experiment",
        specimen_id="projection-specimen",
        profile_id="windows_desktop_v1",
        mode="test",
        worker={"worker_id": "local-bridge", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "program1"},
        metadata={"agentic_progress": "TRANSFERRING"},
    )
    monkeypatch.setattr(
        main_module.controller,
        "snapshot",
        lambda: {"state": {"run_id": "projection-run"}},
    )
    client = TestClient(app)

    current = client.get("/api/equipment/runtime/current").json()
    state = client.get("/api/state").json()
    workspace_script = client.get("/static/windows_equipment.js").text
    ide_script = client.get("/static/runtime_ide.js").text

    assert state["equipment_runtime"]["execution"]["execution_id"] == runtime["execution_id"]
    assert state["equipment_runtime"]["projection"] == current["projection"]
    assert '"/api/equipment/runtime/current"' in workspace_script
    assert "equipmentRuntime" in ide_script
    assert "execution_id" in ide_script


def test_runtime_state_scopes_equipment_projection_to_controller_run(tmp_path: Path, monkeypatch) -> None:
    import app.main as main_module
    from utils.equipment_runtime_service import EquipmentRuntimeService

    runtime_root = tmp_path / "equipment_runtime"
    monkeypatch.setattr(main_module, "EQUIPMENT_RUNTIME_ROOT", runtime_root)
    service = EquipmentRuntimeService(runtime_root)
    active = service.begin(
        sequence_id="active-sequence",
        run_id="active-run",
        experiment_id="active-experiment",
        specimen_id="active-specimen",
        profile_id="windows_desktop_v1",
        mode="test",
        worker={"worker_id": "active-worker", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "program1"},
    )
    service.begin(
        sequence_id="newer-other-sequence",
        run_id="other-run",
        experiment_id="other-experiment",
        specimen_id="other-specimen",
        profile_id="windows_desktop_v1",
        mode="test",
        worker={"worker_id": "other-worker", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "program1"},
    )
    monkeypatch.setattr(main_module.controller, "snapshot", lambda: {"state": {"run_id": "active-run"}})

    state = TestClient(app).get("/api/state").json()

    assert state["equipment_runtime"]["execution"]["execution_id"] == active["execution_id"]


def test_windows_equipment_workspace_uses_four_digit_pairing_instead_of_token_entry() -> None:
    root = Path(__file__).resolve().parents[2]
    template = (root / "web" / "templates" / "windows_equipment.html").read_text(encoding="utf-8")
    script = (root / "web" / "static" / "windows_equipment.js").read_text(encoding="utf-8")
    app_source = (root / "app" / "main.py").read_text(encoding="utf-8")

    discover_section = template[template.index("<h3>Discover Worker</h3>"):template.index("<h3>Candidates</h3>")]
    assert "Pairing Code" not in discover_section
    assert 'class="text-input equipment-pairing-code-input"' in script
    assert 'inputmode="numeric"' in script
    assert 'maxlength="4"' in script
    assert 'id="equipment-token-input"' not in template
    assert "/api/equipment/windows/pair" in script
    assert "pairing_code" in script
    assert '@app.post("/api/equipment/windows/pair")' in app_source


def test_live_gui_skill_authoring_progress_uses_runtime_metadata_not_lifecycle_aliases() -> None:
    client = TestClient(app)
    script = client.get("/static/planning.js").text

    start = script.index("function equipmentCanonicalProgressSteps")
    end = script.index("function equipmentBridgeState", start)
    progress_source = script[start:end]

    assert "agentic_progress" in progress_source
    for state in (
        "RECORDING",
        "TRANSFERRING",
        "ANNOTATING",
        "BUILDING_SKILL",
        "VALIDATING",
        "AWAITING_APPROVAL",
        "DEPLOYING",
        "READY",
        "FAILED",
    ):
        assert state in progress_source


def test_live_gui_equipment_runtime_progress_uses_backend_lifecycle_contract() -> None:
    client = TestClient(app)
    script = client.get("/static/planning.js").text
    start = script.index("function equipmentCanonicalProgressSteps")
    end = script.index("function equipmentBridgeState", start)
    progress_source = script[start:end]

    assert "execution.lifecycle_contract" in progress_source
    assert 'label: "Resolve"' not in progress_source
    assert 'label: "Preflight"' not in progress_source
    assert 'label: "Execute"' not in progress_source
    assert 'label: "Verify"' not in progress_source


def test_windows_equipment_gui_exposes_utm_calibration_controls() -> None:
    client = TestClient(app)
    response = client.get("/equipment/windows")

    assert response.status_code == 200
    html = response.text
    for element_id in [
        "equipment-action-dot",
        "equipment-action-label",
        "equipment-action-detail",
        "equipment-command-banner",
        "equipment-command-title",
        "equipment-command-detail",
        "equipment-command-pill",
        "equipment-proof-dashboard",
        "equipment-gate-windows-bridge",
        "equipment-gate-windows-bridge-status",
        "equipment-gate-windows-bridge-detail",
        "equipment-gate-utm-program",
        "equipment-gate-utm-program-status",
        "equipment-gate-utm-program-detail",
        "equipment-gate-vision-preconditions",
        "equipment-gate-vision-preconditions-status",
        "equipment-gate-vision-preconditions-detail",
        "equipment-gate-screen-state",
        "equipment-gate-screen-state-status",
        "equipment-gate-screen-state-detail",
        "equipment-gate-physical-crosscheck",
        "equipment-gate-physical-crosscheck-status",
        "equipment-gate-physical-crosscheck-detail",
        "equipment-gate-data-artifact",
        "equipment-gate-data-artifact-status",
        "equipment-gate-data-artifact-detail",
        "equipment-gate-analysis-handoff",
        "equipment-gate-analysis-handoff-status",
        "equipment-gate-analysis-handoff-detail",
        "equipment-utm-export-glob",
        "equipment-utm-robot-entry-clearance-mm",
        "equipment-utm-timeout",
        "equipment-utm-stable-sec",
        "equipment-utm-expected-export-path",
        "equipment-utm-target-window",
        "equipment-utm-require-focus",
        "equipment-utm-manual-save",
        "equipment-utm-require-screen",
        "equipment-utm-simulate",
        "equipment-utm-locators",
        "equipment-locator-program",
        "equipment-locator-name",
        "equipment-locator-confidence",
        "equipment-locator-x",
        "equipment-locator-y",
        "equipment-locator-width",
        "equipment-locator-height",
        "btn-equipment-screenshot",
        "btn-equipment-list-locators",
        "btn-equipment-capture-locator",
        "btn-equipment-load-utm-profile",
        "btn-equipment-save-utm-profile",
        "btn-equipment-open-bridge-gui",
        "btn-equipment-readiness",
        "btn-equipment-live-preflight",
        "btn-equipment-live-validation",
        "btn-equipment-vision-proof-draft",
        "btn-equipment-live-physical-validation",
        "equipment-live-preflight-screenshot",
        "equipment-live-physical-safe",
        "equipment-live-vision-proof",
        "equipment-utm-profile-status",
        "equipment-utm-readiness-card",
        "equipment-utm-readiness-status",
        "equipment-utm-readiness-detail",
        "equipment-utm-live-validation-card",
        "equipment-utm-live-validation-status",
        "equipment-utm-live-validation-detail",
        "equipment-utm-live-validation-gates",
        "equipment-utm-evidence-card",
        "equipment-utm-evidence-status",
        "equipment-utm-evidence-detail",
        "equipment-utm-proof-checklist",
        "btn-equipment-evidence-audit",
        "btn-equipment-proof-package",
        "btn-equipment-verify-proof-package",
        "btn-equipment-completion-audit",
        "equipment-proof-verify-card",
        "equipment-proof-verify-status",
        "equipment-proof-verify-detail",
        "equipment-completion-audit-card",
        "equipment-completion-audit-status",
        "equipment-completion-audit-detail",
        "equipment-request-audit-card",
        "equipment-request-audit-status",
        "equipment-request-audit-detail",
        "btn-equipment-request-log",
        "btn-equipment-utm",
        "btn-equipment-abort",
    ]:
        assert f'id="{element_id}"' in html
    assert 'data-equipment-proxy="btn-equipment-open-bridge-gui"' not in html
    for label in [
        "Evidence &amp; Data Transfer",
    ]:
        assert label in html
    script = client.get("/static/windows_equipment.js").text
    for token in [
        "require_screen_assertions",
        "simulate_utm_protocol",
        "export_glob",
        "robot_entry_clearance_mm",
        "artifact_timeout_s",
        "stable_for_sec",
        "expected_export_path",
        "require_window_focus",
        "manual_save_required_if_no_artifact",
        "target_window",
        "target_window_regex",
        "missing_required_locators",
        "required_locator_names",
        "required_locators_complete",
        "locators",
        "/api/equipment/windows/screenshot",
        "/api/equipment/windows/locators",
        "/api/equipment/windows/capture-locator",
        "/api/equipment/windows/utm-profile",
        "/api/equipment/windows/readiness",
        "/api/equipment/windows/live-preflight",
        "/api/equipment/windows/live-validation",
        "/api/equipment/windows/vision-proof-draft",
        "/api/equipment/windows/evidence-audit",
        "/api/equipment/windows/proof-package",
        "/api/equipment/windows/proof-package/verify",
        "/api/equipment/windows/completion-audit",
        "/api/equipment/windows/request-log",
        "runLivePreflight",
        "buildLiveValidationReport",
        "loadVisionProofDraft",
        "renderVisionProofDraft",
        "latestVisionProofDraft",
        "renderUtmLiveValidation",
        "latestUtmLiveValidation",
        "confirm_non_actuating",
        "confirm_live_execute",
        "confirm_physical_setup_safe",
        "collectLiveValidationPayload",
        "runPhysicalLiveValidation",
        "checkRequestLog",
        "renderRequestAudit",
        "checkEvidenceAudit",
        "buildProofPackage",
        "verifyProofPackage",
        "renderProofPackageVerification",
        "runCompletionAudit",
        "renderCompletionAudit",
        "latestCompletionAudit",
        "latestProofPackagePath",
        "package_artifact",
        "proof_package",
        "renderUtmEvidenceAudit",
        "confirm_preflight",
        "include_request_log",
        "request_audit_log_available",
        "execute_event_seen",
        "proof_checklist",
        "proof_ready",
        "utmProofChecklist",
        "collectUtmProfilePayload",
        "hydrateUtmProfile",
            "openSelectedBridgeGui",
            "selectedBridgeUrl",
            'window.open("/equipment/windows/console"',
        "mergeLocatorOverride",
        "renderUtmReadiness",
        "checkReadiness",
        "data-equipment-proxy",
        "commandBanner",
        "commandPill",
        "proofGates",
        "updateProofDashboard",
        "setProofGate",
        "physical_motion_started",
        "runUtmAbort",
        "utm_stop_or_abort_v1",
    ]:
        assert token in script



def test_windows_equipment_vision_proof_draft_api_contract() -> None:
    client = TestClient(app)
    original_metadata = dict(controller._state.run_metadata)
    original_observations = dict(controller._state.latest_observations)
    try:
        controller._state.run_metadata.clear()
        controller._state.latest_observations.clear()

        missing = client.post(
            "/api/equipment/windows/vision-proof-draft",
            json={"run_id": "vision-run-001", "specimen_id": "specimen-001"},
        )
        assert missing.status_code == 200
        missing_payload = missing.json()
        assert missing_payload["tool"] == "equipment.pyautogui.vision_proof_draft"
        assert missing_payload["non_actuating"] is True
        assert missing_payload["ok"] is False
        assert missing_payload["status"] == "incomplete"
        assert "VISION_FRAME_IDS_REQUIRED" in missing_payload["blockers"]
        assert missing_payload["vision_proof"]["ok"] is False
        assert missing_payload["vision_proof"]["run_id"] == "vision-run-001"
        assert missing_payload["vision_proof"]["specimen_id"] == "specimen-001"
        assert missing_payload["vision_proof"]["checks"]["utm_pre_start"]["ok"] is False

        controller._state.run_metadata["latest_vision_observation"] = {
            "equipment_vision_check_results": [
                {
                    "check_id": "utm_pre_start",
                    "ok": True,
                    "confidence": 0.95,
                    "run_id": "vision-run-001",
                    "specimen_id": "specimen-001",
                    "evidence": {"frame_ids": ["frame-pre-001"]},
                },
                {
                    "check_id": "utm_motion_confirm",
                    "ok": True,
                    "confidence": 0.91,
                    "run_id": "vision-run-001",
                    "specimen_id": "specimen-001",
                    "evidence": {"frame_ids": ["frame-motion-001"]},
                },
                {
                    "check_id": "utm_test_complete",
                    "ok": True,
                    "confidence": 0.9,
                    "run_id": "vision-run-001",
                    "specimen_id": "specimen-001",
                    "evidence": {"frame_ids": ["frame-complete-001"]},
                },
            ]
        }
        ready = client.post(
            "/api/equipment/windows/vision-proof-draft",
            json={"run_id": "vision-run-001", "specimen_id": "specimen-001"},
        )
        assert ready.status_code == 200
        payload = ready.json()
        assert payload["ok"] is True
        assert payload["status"] == "ready"
        assert payload["vision_proof"]["ok"] is True
        assert payload["vision_proof"]["checks"]["utm_pre_start"]["source"].endswith("check_id")
        assert payload["vision_proof"]["evidence"]["frame_ids"] == ["frame-pre-001", "frame-motion-001", "frame-complete-001"]
        assert payload["candidate_counts"]["utm_motion_confirm"] >= 1
        assert controller._state.run_metadata["last_windows_utm_vision_proof_draft"]["status"] == "ready"

        config = client.get("/api/equipment/windows/config").json()


        controller._state.run_metadata["latest_vision_observation"] = {
            "equipment_vision_check_results": [
                {"check_id": "utm_pre_start", "ok": True, "confidence": 0.95, "run_id": "vision-run-001", "specimen_id": "specimen-001", "evidence": {"frame_ids": ["same-frame"]}},
                {"check_id": "utm_motion_confirm", "ok": True, "confidence": 0.91, "run_id": "vision-run-001", "specimen_id": "specimen-001", "evidence": {"frame_ids": ["same-frame"]}},
                {"check_id": "utm_test_complete", "ok": True, "confidence": 0.9, "run_id": "vision-run-001", "specimen_id": "specimen-001", "evidence": {"frame_ids": ["same-frame"]}},
            ]
        }
        duplicate_frame_draft = client.post(
            "/api/equipment/windows/vision-proof-draft",
            json={"run_id": "vision-run-001", "specimen_id": "specimen-001"},
        ).json()
        assert duplicate_frame_draft["ok"] is False
        assert duplicate_frame_draft["status"] == "incomplete"
        assert "VISION_FRAME_IDS_REQUIRED" in duplicate_frame_draft["blockers"]
        assert duplicate_frame_draft["vision_proof"]["evidence"]["frame_ids"] == ["same-frame"]
        assert config["utm_vision_proof_draft"]["status"] == "ready"
    finally:
        controller._state.run_metadata.clear()
        controller._state.run_metadata.update(original_metadata)
        controller._state.latest_observations.clear()
        controller._state.latest_observations.update(original_observations)


def test_windows_equipment_evidence_audit_api_contract(tmp_path: Path) -> None:
    client = TestClient(app)
    original_metadata = dict(controller._state.run_metadata)
    created_proof_package_paths: list[Path] = []
    csv_path = tmp_path / "utm.csv"
    csv_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0.2,310\n", encoding="utf-8")
    screen_paths = []
    for name in ("before", "running", "complete"):
        path = tmp_path / f"{name}.png"
        path.write_bytes(TINY_PNG_BYTES)
        screen_paths.append(path)
    try:
        controller._state.run_metadata.clear()
        missing = client.get("/api/equipment/windows/evidence-audit")
        assert missing.status_code == 200
        assert missing.json()["status"] == "missing"
        assert "EQUIPMENT_REPORT_NOT_AVAILABLE" in missing.json()["blockers"]
        missing_completion = client.post("/api/equipment/windows/completion-audit", json={"use_current": False}).json()
        assert missing_completion["ok"] is False
        assert missing_completion["status"] == "incomplete"
        assert "PROOF_PACKAGE_PATH_REQUIRED" in missing_completion["blockers"]

        controller._state.run_metadata.update(
            {
                "equipment_result": {"status": "verified_complete", "program_id": "utm_compression_start_v1"},
                "equipment_report": {
                    "schema": "equipment_report.v1",
                    "run_id": controller._state.run_id,
                    "specimen_id": "specimen-test",
                    "sequence_id": "seq-live-utm",
                    "bridge": {
                        "provider": "windows_pyautogui",
                        "request_log_path": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                        "request_log_event_count": 3,
                        "request_log_recent_paths": ["/health", "/execute"],
                    },
                    "control_plan": {"program_id": "utm_compression_start_v1"},
                    "cross_checks": {
                        "screen_started": True,
                        "physical_motion_started": True,
                        "save_completed": True,
                        "data_file_created": True,
                        "data_parse_probe_ok": True,
                        "screen_evidence_complete": True,
                        "linux_artifact_pulled": True,
                        "save_export_responsibility_ok": True,
                        "vision_evidence_complete": True,
                    },
                    "data_acquisition": {
                        "status": "pulled_to_linux",
                        "linux_path": str(csv_path),
                        "local_path": str(csv_path),
                        "save_method": "windows_export_watch",
                        "save_attempted_by_agent": True,
                        "save_confirmation_screen_ok": True,
                        "windows_path": "C:/ATR/utm_exports/run-test/specimen-test.csv",
                        "row_count_probe": 2,
                    },
                    "artifact_records": [
                        {"kind": "screen_png", "artifact_id": "screen-before", "local_path": str(screen_paths[0])},
                        {"kind": "screen_png", "artifact_id": "screen-running", "local_path": str(screen_paths[1])},
                        {"kind": "screen_png", "artifact_id": "screen-complete", "local_path": str(screen_paths[2])},
                        {"kind": "utm_csv", "artifact_id": "utm-csv", "local_path": str(csv_path), "row_count_probe": 2},
                    ],
                    "screen_evidence_refs": [str(path) for path in screen_paths],
                    "data_evidence_refs": [str(csv_path)],
                    "artifact_refs": [*[str(path) for path in screen_paths], str(csv_path)],
                    "live_evidence_audit": {
                        "required_for_handoff": True,
                        "screen_evidence": {"ok": True, "missing_checkpoints": []},
                        "linux_artifact_pull": {"ok": True},
                        "save_export": {
                            "ok": True,
                            "save_method": "windows_export_watch",
                            "save_attempted_by_agent": True,
                            "save_confirmation_screen_ok": True,
                            "windows_path": "C:/ATR/utm_exports/run-test/specimen-test.csv",
                            "linux_path": str(csv_path),
                            "recognized_save_method": True,
                        },
                        "vision_evidence": {"ok": True, "evidence_frame_ids": ["fixture-frame-001", "motion-frame-001", "complete-frame-001"]},
                        "request_audit_log": {
                            "ok": True,
                            "path": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                            "event_count": 3,
                            "recent_paths": ["/health", "/execute"],
                            "execute_event_seen": True,
                            "execute_event_count": 1,
                            "execute_payload_event_count": 1,
                            "execute_run_ids": [controller._state.run_id],
                            "execute_sequence_ids": ["seq-live-utm"],
                            "execute_specimen_ids": ["specimen-test"],
                            "execute_program_ids": ["utm_compression_start_v1"],
                            "execute_identity_required": True,
                            "execute_identity_present": True,
                            "execute_identity_match": True,
                        },
                    },
                    "decision": {"handoff_status": "ready_for_analysis", "equipment_status": "verified_complete", "blocking_reasons": []},
                },
                "equipment_handoff": {"status": "ready_for_analysis", "program_id": "utm_compression_start_v1", "sequence_id": "seq-live-utm", "specimen_id": "specimen-test"},
                "utm_data_ready": {"specimen_id": "specimen-test"},
            }
        )
        ready = client.get("/api/equipment/windows/evidence-audit")
        assert ready.status_code == 200
        payload = ready.json()
        assert payload["ok"] is False
        assert payload["status"] == "blocked"
        assert "UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED" in payload["blockers"]
        assert payload["gates"]["physical_live_execute"] is False

        physical_validation_packet = {
            "schema": "lab_equipment_utm_live_validation.v1",
            "ok": True,
            "status": "verified_complete",
            "run_id": controller._state.run_id,
            "sequence_id": "seq-live-utm",
            "specimen_id": "specimen-test",
            "program_id": "utm_compression_start_v1",
            "requested_physical_execute": True,
            "execute_sent": True,
            "non_actuating": False,
        }
        missing_identity_packet = dict(physical_validation_packet)
        missing_identity_packet.pop("program_id")
        controller._state.run_metadata["last_windows_utm_physical_validation"] = missing_identity_packet
        missing_identity = client.get("/api/equipment/windows/evidence-audit").json()
        assert missing_identity["ok"] is False
        assert "UTM_PHYSICAL_LIVE_EXECUTE_IDENTITY_REQUIRED" in missing_identity["blockers"]
        assert missing_identity["gates"]["physical_live_execute"] is False
        missing_identity_package = client.get("/api/equipment/windows/proof-package").json()
        assert missing_identity_package["manifest"]["physical_execution"]["ok"] is False
        assert "program_id" in missing_identity_package["manifest"]["physical_execution"]["missing_identity_fields"]

        mismatched_identity_packet = dict(physical_validation_packet)
        mismatched_identity_packet["program_id"] = "wrong_program"
        controller._state.run_metadata["last_windows_utm_physical_validation"] = mismatched_identity_packet
        mismatched_identity = client.get("/api/equipment/windows/evidence-audit").json()
        assert mismatched_identity["ok"] is False
        assert "UTM_PHYSICAL_LIVE_EXECUTE_IDENTITY_MISMATCH" in mismatched_identity["blockers"]
        assert mismatched_identity["gates"]["physical_live_execute"] is False
        mismatched_identity_package = client.get("/api/equipment/windows/proof-package").json()
        assert mismatched_identity_package["manifest"]["physical_execution"]["ok"] is False
        assert "program_id" in mismatched_identity_package["manifest"]["physical_execution"]["mismatched_identity_fields"]

        controller._state.run_metadata["last_windows_utm_physical_validation"] = physical_validation_packet
        ready = client.get("/api/equipment/windows/evidence-audit")
        assert ready.status_code == 200
        payload = ready.json()
        assert payload["ok"] is True
        assert payload["status"] == "ready_for_analysis"
        assert payload["gates"]["linux_artifact_pulled"] is True
        assert payload["gates"]["save_export_responsibility_ok"] is True
        assert payload["gates"]["request_audit_log_available"] is True
        assert payload["gates"]["physical_live_execute"] is True
        assert payload["request_audit_log"]["path"].endswith("bridge_requests.jsonl")
        assert payload["request_audit_log"]["execute_event_seen"] is True
        assert payload["proof_ready"] is True
        checklist_by_id = {item["id"]: item for item in payload["proof_checklist"]}
        assert checklist_by_id["request_log_execute"]["ok"] is True
        assert checklist_by_id["physical_live_execute"]["ok"] is True
        assert checklist_by_id["screen_evidence"]["ok"] is True
        assert checklist_by_id["linux_artifact_pull"]["ok"] is True
        assert checklist_by_id["save_export_responsibility"]["ok"] is True
        assert payload["screen_evidence_refs"] == [str(path) for path in screen_paths]

        screen_paths[1].write_text("not an image", encoding="utf-8")
        invalid_screen_audit = client.get("/api/equipment/windows/evidence-audit").json()
        assert invalid_screen_audit["ok"] is False
        assert "UTM_SCREEN_EVIDENCE_FILES_REQUIRED" in invalid_screen_audit["blockers"]
        assert invalid_screen_audit["gates"]["screen_evidence_complete"] is False
        screen_paths[1].write_bytes(TINY_PNG_BYTES)

        csv_path.unlink()
        missing_data_audit = client.get("/api/equipment/windows/evidence-audit").json()
        assert missing_data_audit["ok"] is False
        assert "UTM_DATA_EVIDENCE_FILES_REQUIRED" in missing_data_audit["blockers"]
        assert missing_data_audit["gates"]["linux_artifact_pulled"] is False
        csv_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0.2,310\n", encoding="utf-8")

        csv_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0.2,0\n2,0.4,0\n", encoding="utf-8")
        bad_signal_audit = client.get("/api/equipment/windows/evidence-audit").json()
        assert bad_signal_audit["ok"] is False
        assert "UTM_DATA_NO_FORCE_SIGNAL" in bad_signal_audit["blockers"]
        assert bad_signal_audit["gates"]["data_parse_probe_ok"] is False
        csv_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0.2,310\n", encoding="utf-8")

        report = controller._state.run_metadata["equipment_report"]
        report["live_evidence_audit"]["request_audit_log"]["recent_paths"] = ["/health", "/request-log"]
        report["live_evidence_audit"]["request_audit_log"]["execute_event_seen"] = True
        report["live_evidence_audit"]["request_audit_log"]["execute_event_count"] = 1
        report["live_evidence_audit"]["request_audit_log"]["execute_payload_event_count"] = 1
        report["live_evidence_audit"]["request_audit_log"]["execute_run_ids"] = [controller._state.run_id]
        report["live_evidence_audit"]["request_audit_log"]["execute_sequence_ids"] = ["seq-live-utm"]
        report["live_evidence_audit"]["request_audit_log"]["execute_specimen_ids"] = ["specimen-test"]
        report["live_evidence_audit"]["request_audit_log"]["execute_program_ids"] = ["utm_compression_start_v1"]
        report["live_evidence_audit"]["request_audit_log"]["execute_identity_match"] = True
        report["live_evidence_audit"]["request_audit_log"]["last_execute_at"] = "2026-05-30T00:00:00Z"
        summary_ready = client.get("/api/equipment/windows/evidence-audit").json()
        assert summary_ready["ok"] is True
        assert summary_ready["request_audit_log"]["execute_event_seen"] is True
        assert summary_ready["request_audit_log"]["execute_event_count"] == 1
        assert summary_ready["request_audit_log"]["last_execute_at"] == "2026-05-30T00:00:00Z"
        assert summary_ready["proof_ready"] is True

        config = client.get("/api/equipment/windows/config").json()
        assert config["utm_evidence_audit"]["status"] == "ready_for_analysis"

        proof_package = client.get("/api/equipment/windows/proof-package").json()
        assert proof_package["tool"] == "equipment.pyautogui.live_proof_package"
        assert proof_package["ok"] is True
        assert proof_package["ready_for_analysis"] is True
        assert proof_package["status"] == "ready_for_analysis"
        assert proof_package["proof_ready"] is True
        assert proof_package["missing_required_item_count"] == 0
        assert proof_package["manifest"]["screen_evidence_count"] == 3
        assert proof_package["manifest"]["data_evidence_count"] == 1
        assert proof_package["manifest"]["physical_execution"]["ok"] is True
        assert proof_package["manifest"]["physical_execution"]["dispatch_ok"] is True
        assert proof_package["manifest"]["physical_execution"]["identity_ok"] is True
        assert proof_package["manifest"]["physical_execution"]["execute_sent"] is True
        assert proof_package["manifest"]["physical_execution"]["non_actuating"] is False
        assert proof_package["manifest"]["request_log"]["execute_event_seen"] is True
        assert proof_package["manifest"]["request_log"]["execute_identity_match"] is True
        assert proof_package["manifest"]["save_export"]["ok"] is True
        assert proof_package["manifest"]["save_export"]["save_method"] == "windows_export_watch"
        assert proof_package["evidence_audit"]["status"] == "ready_for_analysis"
        assert "passive_readiness" in proof_package
        package_artifact = proof_package["package_artifact"]
        assert package_artifact["kind"] == "windows_utm_proof_package"
        assert package_artifact["content_type"] == "application/json"
        proof_path = Path(package_artifact["path"])
        created_proof_package_paths.append(proof_path)
        assert proof_path.exists()
        persisted = json.loads(proof_path.read_text(encoding="utf-8"))
        assert persisted["tool"] == "equipment.pyautogui.live_proof_package"
        assert persisted["manifest"]["proof_package_path"] == str(proof_path)
        verification = client.post("/api/equipment/windows/proof-package/verify", json={"path": str(proof_path)}).json()
        assert verification["tool"] == "equipment.pyautogui.live_proof_package.verify"
        assert verification["ok"] is True
        assert verification["status"] == "verified"
        assert verification["csv_probe"]["row_count"] == 2
        assert verification["csv_probe"]["has_force_column"] is True
        assert verification["csv_probe"]["has_displacement_column"] is True
        gate_summary = {item["key"]: item for item in verification["gate_summary"]}
        assert set(gate_summary) == {
            "windows_bridge",
            "utm_program",
            "vision_preconditions",
            "physical_execution",
            "screen_state",
            "physical_crosscheck",
            "data_artifact",
            "analysis_handoff",
        }
        assert all(item["ok"] is True for item in gate_summary.values())
        assert gate_summary["windows_bridge"]["label"] == "Windows Bridge"
        assert gate_summary["physical_execution"]["label"] == "Physical Execute"
        assert gate_summary["data_artifact"]["label"] == "Data Artifact"
        assert any(item["name"] == "request_log_execute" and item["status"] == "ok" for item in verification["checks"])
        assert any(item["name"] == "request_log_execute_identity" and item["status"] == "ok" for item in verification["checks"])
        assert any(item["name"] == "save_export_responsibility" and item["status"] == "ok" for item in verification["checks"])
        assert any(item["name"] == "screen_evidence_files" and item["status"] == "ok" for item in verification["checks"])
        assert any(item["name"] == "vision_frame_refs" and item["status"] == "ok" for item in verification["checks"])
        assert controller._state.run_metadata["last_windows_utm_proof_package_verification"]["status"] == "verified"

        completion = client.post("/api/equipment/windows/completion-audit", json={"path": str(proof_path), "use_current": False}).json()
        assert completion["tool"] == "equipment.pyautogui.improvement05_completion_audit"
        assert completion["ok"] is True
        assert completion["status"] == "complete_evidence_verified"
        assert completion["verification"]["status"] == "verified"
        assert completion["proof_package_path"] == str(proof_path)
        completion_path = Path(completion["audit_artifact"]["path"])
        created_proof_package_paths.append(completion_path)
        assert completion_path.exists()
        persisted_completion = json.loads(completion_path.read_text(encoding="utf-8"))
        assert persisted_completion["status"] == "complete_evidence_verified"
        assert persisted_completion["audit_artifact"]["kind"] == "windows_utm_completion_audit"
        assert controller._state.run_metadata["last_windows_utm_completion_audit"]["status"] == "complete_evidence_verified"
        assert controller._state.run_metadata["last_windows_utm_completion_audit"]["audit_artifact"]["path"] == str(completion_path)

        csv_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0.2,0\n2,0.4,0\n", encoding="utf-8")
        bad_signal_verification = client.post("/api/equipment/windows/proof-package/verify", json={"path": str(proof_path)}).json()
        assert bad_signal_verification["ok"] is False
        assert bad_signal_verification["status"] == "blocked"
        assert bad_signal_verification["csv_probe"]["failure_code"] == "UTM_DATA_NO_FORCE_SIGNAL"
        assert bad_signal_verification["csv_probe"]["data_quality"]["force_changes"] is False
        assert "UTM_DATA_NO_FORCE_SIGNAL" in bad_signal_verification["blockers"]
        bad_signal_gates = {item["key"]: item for item in bad_signal_verification["gate_summary"]}
        assert bad_signal_gates["data_artifact"]["ok"] is False
        assert bad_signal_gates["analysis_handoff"]["ok"] is False
        assert any(item["name"] == "linux_csv_parse_probe" and item["status"] == "blocked" and item.get("code") == "UTM_DATA_NO_FORCE_SIGNAL" for item in bad_signal_verification["checks"])
        csv_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0.2,310\n", encoding="utf-8")

        screen_paths[0].unlink()
        missing_screen_verification = client.post("/api/equipment/windows/proof-package/verify", json={"path": str(proof_path)}).json()
        assert missing_screen_verification["ok"] is False
        assert "UTM_SCREEN_EVIDENCE_FILES_REQUIRED" in missing_screen_verification["blockers"]
        screen_paths[0].write_bytes(TINY_PNG_BYTES)

        screen_paths[1].write_bytes(b"not-an-image")
        invalid_screen_verification = client.post("/api/equipment/windows/proof-package/verify", json={"path": str(proof_path)}).json()
        assert invalid_screen_verification["ok"] is False
        assert "UTM_SCREEN_EVIDENCE_FILES_REQUIRED" in invalid_screen_verification["blockers"]
        assert "invalid_image" in next(item["detail"] for item in invalid_screen_verification["checks"] if item["name"] == "screen_evidence_files")
        screen_paths[1].write_bytes(TINY_PNG_BYTES)

        duplicate_screen_package = json.loads(proof_path.read_text(encoding="utf-8"))
        duplicate_screen_package["manifest"]["screen_evidence_refs"] = [str(screen_paths[0]), str(screen_paths[0]), str(screen_paths[0])]
        duplicate_screen_package["manifest"]["screen_evidence_count"] = 3
        duplicate_screen_path = proof_path.parent / "duplicate_screen_proof_package.json"
        duplicate_screen_path.write_text(json.dumps(duplicate_screen_package, ensure_ascii=False, indent=2), encoding="utf-8")
        created_proof_package_paths.append(duplicate_screen_path)
        duplicate_screen_verification = client.post("/api/equipment/windows/proof-package/verify", json={"path": str(duplicate_screen_path)}).json()
        assert duplicate_screen_verification["ok"] is False
        assert "UTM_SCREEN_EVIDENCE_FILES_REQUIRED" in duplicate_screen_verification["blockers"]
        assert "duplicate screen files" in next(item["detail"] for item in duplicate_screen_verification["checks"] if item["name"] == "screen_evidence_files")

        missing_physical_source_package = json.loads(proof_path.read_text(encoding="utf-8"))
        missing_physical_source_package["source_packets"]["last_windows_utm_physical_validation"] = {}
        missing_physical_source_path = proof_path.parent / "missing_physical_source_proof_package.json"
        missing_physical_source_path.write_text(json.dumps(missing_physical_source_package, ensure_ascii=False, indent=2), encoding="utf-8")
        created_proof_package_paths.append(missing_physical_source_path)
        missing_physical_source_verification = client.post("/api/equipment/windows/proof-package/verify", json={"path": str(missing_physical_source_path)}).json()
        assert missing_physical_source_verification["ok"] is False
        assert "UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED" in missing_physical_source_verification["blockers"]
        assert "source_ok=False" in next(item["detail"] for item in missing_physical_source_verification["checks"] if item["name"] == "physical_live_execute")

        mismatched_physical_source_package = json.loads(proof_path.read_text(encoding="utf-8"))
        mismatched_physical_source_package["source_packets"]["last_windows_utm_physical_validation"]["program_id"] = "wrong_utm_program"
        mismatched_physical_source_path = proof_path.parent / "mismatched_physical_source_proof_package.json"
        mismatched_physical_source_path.write_text(json.dumps(mismatched_physical_source_package, ensure_ascii=False, indent=2), encoding="utf-8")
        created_proof_package_paths.append(mismatched_physical_source_path)
        mismatched_physical_source_verification = client.post("/api/equipment/windows/proof-package/verify", json={"path": str(mismatched_physical_source_path)}).json()
        assert mismatched_physical_source_verification["ok"] is False
        assert "UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED" in mismatched_physical_source_verification["blockers"]
        assert "identity_match=False" in next(item["detail"] for item in mismatched_physical_source_verification["checks"] if item["name"] == "physical_live_execute")

        report = controller._state.run_metadata["equipment_report"]
        report["cross_checks"]["save_export_responsibility_ok"] = False
        report["live_evidence_audit"]["save_export"]["ok"] = False
        missing_save = client.get("/api/equipment/windows/evidence-audit").json()
        assert missing_save["ok"] is False
        assert missing_save["gates"]["save_export_responsibility_ok"] is False
        assert "UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED" in missing_save["blockers"]
        missing_save_checklist = {item["id"]: item for item in missing_save["proof_checklist"]}
        assert missing_save_checklist["save_export_responsibility"]["ok"] is False
        missing_save_package = client.get("/api/equipment/windows/proof-package").json()
        assert missing_save_package["manifest"]["save_export"]["ok"] is False
        assert any(item["id"] == "save_export_responsibility" for item in missing_save_package["missing_required_items"])
        missing_save_path = Path(missing_save_package["package_artifact"]["path"])
        created_proof_package_paths.append(missing_save_path)
        missing_save_verification = client.post("/api/equipment/windows/proof-package/verify", json={"path": str(missing_save_path)}).json()
        assert "UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED" in missing_save_verification["blockers"]
        missing_save_completion = client.post("/api/equipment/windows/completion-audit", json={"path": str(missing_save_path), "use_current": False}).json()
        assert missing_save_completion["ok"] is False
        assert missing_save_completion["status"] == "incomplete"
        assert "UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED" in missing_save_completion["blockers"]
        missing_save_completion_path = Path(missing_save_completion["audit_artifact"]["path"])
        created_proof_package_paths.append(missing_save_completion_path)
        assert missing_save_completion_path.exists()
        missing_save_gates = {item["key"]: item for item in missing_save_verification["gate_summary"]}
        assert missing_save_gates["data_artifact"]["ok"] is False
        assert missing_save_gates["analysis_handoff"]["ok"] is False
        report["cross_checks"]["save_export_responsibility_ok"] = True
        report["live_evidence_audit"]["save_export"]["ok"] = True

        report["bridge"]["request_log_recent_paths"] = ["/health", "/programs", "/request-log"]
        report["live_evidence_audit"]["request_audit_log"].pop("execute_event_seen", None)
        report["live_evidence_audit"]["request_audit_log"].pop("execute_event_count", None)
        report["live_evidence_audit"]["request_audit_log"].pop("last_execute_at", None)
        report["live_evidence_audit"]["request_audit_log"]["recent_paths"] = ["/health", "/programs", "/request-log"]
        missing_execute = client.get("/api/equipment/windows/evidence-audit")
        assert missing_execute.status_code == 200
        blocked_payload = missing_execute.json()
        assert blocked_payload["ok"] is False
        assert blocked_payload["status"] == "blocked"
        assert blocked_payload["gates"]["request_audit_log_available"] is False
        assert blocked_payload["request_audit_log"]["execute_event_seen"] is False
        assert blocked_payload["proof_ready"] is False
        assert "UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED" in blocked_payload["blockers"]
        blocked_package = client.get("/api/equipment/windows/proof-package").json()
        assert blocked_package["ok"] is False
        assert blocked_package["status"] == "incomplete"
        assert blocked_package["missing_required_item_count"] >= 1
        assert any(item["id"] == "request_log_execute" for item in blocked_package["missing_required_items"])
        assert "UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED" in blocked_package["blockers"]
        blocked_proof_path = Path(blocked_package["package_artifact"]["path"])
        created_proof_package_paths.append(blocked_proof_path)
        assert blocked_proof_path.exists()
        blocked_verification = client.post("/api/equipment/windows/proof-package/verify", json={"path": str(blocked_proof_path)}).json()
        assert blocked_verification["ok"] is False
        assert blocked_verification["status"] == "blocked"
        assert "UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED" in blocked_verification["blockers"]
        blocked_gates = {item["key"]: item for item in blocked_verification["gate_summary"]}
        assert blocked_gates["windows_bridge"]["ok"] is False
        assert blocked_gates["analysis_handoff"]["ok"] is False
    finally:
        for proof_path in created_proof_package_paths:
            proof_path.unlink(missing_ok=True)
        controller._state.run_metadata.clear()
        controller._state.run_metadata.update(original_metadata)


def test_windows_equipment_run_program_updates_raw_utm_evidence_audit(monkeypatch, tmp_path: Path) -> None:
    import app.main as app_main

    csv_path = tmp_path / "utm.csv"
    csv_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0.1,2.5\n", encoding="utf-8")

    class _FakeBridge:
        def connection_status(self):
            return {"selected": True, "token_configured": True}

        def list_programs(self, payload):
            return {"ok": True, "programs": [{"program_id": "utm_compression_start_v1"}]}

        def health(self, payload):
            return {"ok": True, "status": "ready", "pyautogui": {"available": True, "failsafe": True}}

        def list_locators(self, payload):
            return {
                "ok": True,
                "locators": [
                    {"name": "ready_state"},
                    {"name": "start_button"},
                    {"name": "running_state"},
                    {"name": "complete_state"},
                ],
            }

        def request_log(self, payload):
            return {
                "ok": True,
                "request_log": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                "event_count": 4,
                "recent_paths": ["/health", "/execute", "/request-log"],
                "execute_event_seen": True,
                "execute_event_count": 1,
                "execute_payload_event_count": 1,
                "execute_run_ids": [controller._state.run_id],
                "execute_sequence_ids": ["setup-utm_compression_start_v1"],
                "execute_specimen_ids": ["specimen-test"],
                "execute_program_ids": ["utm_compression_start_v1"],
                "last_execute_context": {
                    "audit_kind": "execute_payload",
                    "run_id": controller._state.run_id,
                    "sequence_id": "setup-utm_compression_start_v1",
                    "specimen_id": "specimen-test",
                    "program_id": "utm_compression_start_v1",
                },
                "last_execute_at": "2026-05-30T00:00:00Z",
            }

        def utm_profile_status(self):
            return {
                "source": "memory",
                "profile": {
                    "program_id": "utm_compression_start_v1",
                    "export_glob": "*.csv",
                    "require_screen_assertions": True,
                    "simulate_utm_protocol": False,
                    "locators": {
                        "ready_state": {"image_path": "ready.png"},
                        "start_button": {"image_path": "start.png"},
                        "running_state": {"image_path": "running.png"},
                        "complete_state": {"image_path": "complete.png"},
                    },
                },
            }

        def run(self, payload):
            return {
                "ok": True,
                "tool": "equipment.pyautogui.run",
                "status": "verified_complete",
                "bridge": "windows_pyautogui",
                "program_id": "utm_compression_start_v1",
                "sequence_id": "setup-utm_compression_start_v1",
                "result_file": str(csv_path),
                "utm_csv_path": str(csv_path),
                "screen_checks": [
                    {"checkpoint": "before_start", "ok": True, "state": "ready", "screenshot_artifact": "screen-before"},
                    {"checkpoint": "after_start", "ok": True, "state": "running", "screenshot_artifact": "screen-running"},
                    {"checkpoint": "after_complete", "ok": True, "state": "complete", "screenshot_artifact": "screen-complete"},
                ],
                "output_artifacts": [
                    {"kind": "screen_png", "artifact_id": "screen-before", "local_path": "before.png"},
                    {"kind": "screen_png", "artifact_id": "screen-running", "local_path": "running.png"},
                    {"kind": "screen_png", "artifact_id": "screen-complete", "local_path": "complete.png"},
                    {"kind": "utm_csv", "artifact_id": "utm-csv", "local_path": str(csv_path), "row_count_probe": 2},
                ],
                "data_acquisition": {
                    "status": "pulled_to_linux",
                    "linux_path": str(csv_path),
                    "local_path": str(csv_path),
                    "row_count_probe": 2,
                    "save_method": "windows_export_watch",
                    "save_attempted_by_agent": True,
                    "save_confirmation_screen_ok": True,
                    "windows_path": "C:/ATR/utm_exports/run-test/specimen-test.csv",
                },
                "bridge_request_log_ref": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                "request_log_event_count": 4,
                "request_log_recent_paths": ["/health", "/programs", "/execute", "/request-log"],
                "cross_checks": {
                    "screen_started": True,
                    "physical_motion_started": True,
                    "save_completed": True,
                    "data_file_created": True,
                    "data_parse_probe_ok": True,
                    "save_export_responsibility_ok": True,
                },
            }

    original_metadata = dict(controller._state.run_metadata)
    monkeypatch.setattr(app_main, "_equipment_bridge", lambda: _FakeBridge())
    client = TestClient(app)
    try:
        controller._state.run_metadata.clear()
        response = client.post(
            "/api/equipment/windows/run-program",
            json={"program_id": "utm_compression_start_v1", "confirm_execute": True, "require_screen_assertions": True},
        )
        assert response.status_code == 200
        result_payload = response.json()
        assert result_payload["pre_execution_preflight"]["non_actuating"] is True
        assert result_payload["pre_execution_preflight"]["ready_for_autonomous_profile"] is True
        assert controller._state.run_metadata["last_windows_utm_protocol_result"]["program_id"] == "utm_compression_start_v1"

        audit = client.get("/api/equipment/windows/evidence-audit").json()
        assert audit["status"] == "blocked"
        assert audit["gates"]["screen_evidence_complete"] is True
        assert audit["gates"]["linux_artifact_pulled"] is True
        assert audit["gates"]["vision_evidence_complete"] is False
        assert audit["request_audit_log"]["path"].endswith("bridge_requests.jsonl")
        assert audit["request_audit_log"]["execute_event_seen"] is True
        assert audit["gates"]["request_audit_log_available"] is True
        assert audit["gates"]["save_export_responsibility_ok"] is True
        assert audit["proof_ready"] is False
        raw_checklist = {item["id"]: item for item in audit["proof_checklist"]}
        assert raw_checklist["request_log_execute"]["ok"] is True
        assert raw_checklist["save_export_responsibility"]["ok"] is True
        assert raw_checklist["vision_evidence_frames"]["ok"] is False
        assert "UTM_VISION_EVIDENCE_FRAMES_REQUIRED" in audit["blockers"]
        assert audit["data_evidence_refs"] == [str(csv_path)]
        assert len(audit["screen_evidence_refs"]) == 3
    finally:
        controller._state.run_metadata.clear()
        controller._state.run_metadata.update(original_metadata)


def test_windows_equipment_run_program_passes_utm_export_controls(monkeypatch) -> None:
    import app.main as app_main

    captured = {}

    class _FakeBridge:
        def connection_status(self):
            return {"selected": True, "token_configured": True}

        def list_programs(self, payload):
            return {"ok": True, "programs": [{"program_id": "utm_compression_start_v1"}]}

        def health(self, payload):
            return {"ok": True, "status": "ready", "pyautogui": {"available": True, "failsafe": True}}

        def list_locators(self, payload):
            return {
                "ok": True,
                "locators": [
                    {"name": "ready_state"},
                    {"name": "start_button"},
                    {"name": "running_state"},
                    {"name": "complete_state"},
                ],
            }

        def request_log(self, payload):
            return {
                "ok": True,
                "request_log": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                "event_count": 2,
                "recent_paths": ["/health", "/request-log"],
                "execute_event_seen": False,
            }

        def utm_profile_status(self):
            return {
                "source": "memory",
                "profile": {
                    "program_id": "utm_compression_start_v1",
                    "export_glob": "*.csv",
                    "require_screen_assertions": True,
                    "simulate_utm_protocol": False,
                    "locators": {
                        "ready_state": {"image_path": "ready.png"},
                        "start_button": {"image_path": "start.png"},
                        "running_state": {"image_path": "running.png"},
                        "complete_state": {"image_path": "complete.png"},
                    },
                },
            }

        def run(self, payload):
            captured.update(payload)
            return {
                "ok": True,
                "tool": "equipment.pyautogui.run",
                "status": "verified_complete",
                "bridge": "windows_pyautogui",
                "program_id": payload.get("program_id"),
                "sequence_id": payload.get("sequence_id"),
                "step_trace": [],
            }

    monkeypatch.setattr(app_main, "_equipment_bridge", lambda: _FakeBridge())
    client = TestClient(app)

    response = client.post(
        "/api/equipment/windows/run-program",
        json={
            "program_id": "utm_compression_start_v1",
            "command": "Run UTM compression protocol and export CSV",
            "confirm_execute": True,
            "export_glob": "specimen*.csv",
            "artifact_timeout_s": 123,
            "stable_for_sec": 3.5,
            "expected_export_path": "C:/ATR/utm_exports/run/specimen.csv",
            "require_window_focus": True,
            "manual_save_required_if_no_artifact": False,
            "target_window_regex": ".*UTM.*",
            "require_screen_assertions": True,
            "simulate_utm_protocol": False,
        },
    )

    assert response.status_code == 200
    assert captured["runtime_mode"] == "live"
    assert captured["force_live_bridge"] is True
    assert captured["export_glob"] == "specimen*.csv"
    assert captured["artifact_timeout_s"] == 123
    assert captured["stable_for_sec"] == 3.5
    assert captured["expected_export_path"].endswith("specimen.csv")
    assert captured["require_window_focus"] is True
    assert captured["manual_save_required_if_no_artifact"] is False
    assert captured["target_window_regex"] == ".*UTM.*"
    assert captured["require_screen_assertions"] is True
    assert response.json()["pre_execution_preflight"]["ready_for_autonomous_profile"] is True


def test_windows_equipment_utm_abort_bypasses_readiness_and_preflight(monkeypatch) -> None:
    import app.main as app_main

    calls = {"run": 0, "health": 0, "list_programs": 0, "list_locators": 0}

    class _AbortBridge:
        def connection_status(self):
            return {"selected": True, "token_configured": True}

        def list_programs(self, payload):
            calls["list_programs"] += 1
            raise AssertionError("abort recovery must not require program-readiness listing before run")

        def health(self, payload):
            calls["health"] += 1
            raise AssertionError("abort recovery must not require live preflight health before run")

        def list_locators(self, payload):
            calls["list_locators"] += 1
            raise AssertionError("abort recovery must not require locator readiness before run")

        def request_log(self, payload):
            return {
                "ok": True,
                "request_log": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                "event_count": 1,
                "recent_paths": ["/execute"],
                "execute_event_seen": True,
                "execute_event_count": 1,
            }

        def run(self, payload):
            calls["run"] += 1
            return {
                "ok": True,
                "tool": "equipment.pyautogui.run",
                "status": "recovery_macro_dispatched",
                "program_id": payload.get("program_id"),
                "sequence_id": payload.get("sequence_id"),
                "step_trace": [{"step": "RECOVERY_ABORT_MACRO", "status": "ok", "detail": "dispatched"}],
            }

    monkeypatch.setattr(app_main, "_equipment_bridge", lambda: _AbortBridge())
    client = TestClient(app)

    response = client.post(
        "/api/equipment/windows/run-program",
        json={"program_id": "utm_stop_or_abort_v1", "confirm_execute": True, "require_screen_assertions": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["program_id"] == "utm_stop_or_abort_v1"
    assert payload["recovery_macro"] is True
    assert payload["pre_execution_readiness"]["status"] == "bypassed_for_recovery_macro"
    assert payload["request_audit_log"]["execute_event_seen"] is True
    assert calls == {"run": 1, "health": 0, "list_programs": 0, "list_locators": 0}


def test_windows_equipment_run_program_blocks_utm_when_live_preflight_fails(monkeypatch) -> None:
    import app.main as app_main

    called = {"run": False}

    class _PreflightBlockedBridge:
        def connection_status(self):
            return {"selected": True, "token_configured": True}

        def list_programs(self, payload):
            return {"ok": True, "programs": [{"program_id": "utm_compression_start_v1"}]}

        def health(self, payload):
            return {"ok": False, "failure_code": "LIVE_BRIDGE_UNREACHABLE", "message": "offline"}

        def list_locators(self, payload):
            return {"ok": True, "locators": []}

        def request_log(self, payload):
            return {"ok": False, "failure_code": "REQUEST_LOG_UNREACHABLE"}

        def utm_profile_status(self):
            return {
                "source": "memory",
                "profile": {
                    "program_id": "utm_compression_start_v1",
                    "export_glob": "*.csv",
                    "require_screen_assertions": True,
                    "simulate_utm_protocol": False,
                    "locators": {
                        "ready_state": {"image_path": "ready.png"},
                        "start_button": {"image_path": "start.png"},
                        "running_state": {"image_path": "running.png"},
                        "complete_state": {"image_path": "complete.png"},
                    },
                },
            }

        def run(self, payload):  # pragma: no cover - this must remain uncalled
            called["run"] = True
            return {"ok": True}

    monkeypatch.setattr(app_main, "_equipment_bridge", lambda: _PreflightBlockedBridge())
    client = TestClient(app)

    response = client.post(
        "/api/equipment/windows/run-program",
        json={
            "program_id": "utm_compression_start_v1",
            "confirm_execute": True,
            "require_screen_assertions": True,
            "simulate_utm_protocol": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["failure_code"] == "UTM_LIVE_PREFLIGHT_BLOCKED"
    assert payload["bridge_not_called"] is True
    assert payload["non_actuating"] is True
    assert payload["required_gate"] == "live_preflight.ready_for_autonomous_profile"
    assert "LIVE_BRIDGE_HEALTH_FAILED" in payload["preflight"]["blockers"]
    assert "UTM_LIVE_PREFLIGHT_NOT_READY" in payload["blockers"]
    assert called["run"] is False


def test_windows_equipment_run_program_blocks_utm_when_readiness_incomplete(monkeypatch) -> None:
    import app.main as app_main

    called = {"run": False}

    class _BlockedBridge:
        def connection_status(self):
            return {"selected": True, "token_configured": True}

        def list_programs(self, payload):
            return {"ok": True, "programs": [{"program_id": "utm_compression_start_v1"}]}

        def health(self, payload):
            return {"ok": True, "status": "ready", "pyautogui": {"available": True, "failsafe": True}}

        def list_locators(self, payload):
            return {
                "ok": True,
                "locators": [
                    {"name": "ready_state"},
                    {"name": "start_button"},
                    {"name": "running_state"},
                    {"name": "complete_state"},
                ],
            }

        def request_log(self, payload):
            return {
                "ok": True,
                "request_log": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                "event_count": 2,
                "recent_paths": ["/health", "/request-log"],
                "execute_event_seen": False,
            }

        def utm_profile_status(self):
            return {
                "source": "memory",
                "profile": {
                    "program_id": "utm_compression_start_v1",
                    "export_glob": "*.csv",
                    "require_screen_assertions": True,
                    "simulate_utm_protocol": False,
                    "locators": {"ready_state": {"image_path": "ready.png"}},
                },
            }

        def run(self, payload):  # pragma: no cover - this must remain uncalled
            called["run"] = True
            return {"ok": True}

    monkeypatch.setattr(app_main, "_equipment_bridge", lambda: _BlockedBridge())
    client = TestClient(app)

    response = client.post(
        "/api/equipment/windows/run-program",
        json={
            "program_id": "utm_compression_start_v1",
            "confirm_execute": True,
            "require_screen_assertions": True,
            "simulate_utm_protocol": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["failure_code"] == "UTM_PRE_EXECUTION_READINESS_BLOCKED"
    assert payload["bridge_not_called"] is True
    assert payload["non_actuating"] is True
    assert payload["required_gate"] == "ready_for_autonomous_profile"
    assert "UTM_REQUIRED_LOCATORS_MISSING" in payload["readiness"]["blockers"]
    assert "UTM_AUTONOMOUS_PROFILE_NOT_READY" in payload["blockers"]
    assert called["run"] is False


def test_windows_equipment_locator_calibration_api_contracts(monkeypatch, tmp_path: Path) -> None:
    import app.main as app_main
    from device_bridges.windows_pyautogui_bridge import WindowsPyAutoGUIBridge, WindowsPyAutoGUIBridgeConfig

    cfg = WindowsPyAutoGUIBridgeConfig.from_devices_config(
        {
            "devices": {
                "equipment": {
                    "mode": "live",
                    "windows_pyautogui": {"connection_memory_path": str(tmp_path / "empty_windows_bridge.json")},
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.delenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", raising=False)
    monkeypatch.delenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", raising=False)
    monkeypatch.setattr(app_main, "_equipment_bridge", lambda: WindowsPyAutoGUIBridge(cfg))
    client = TestClient(app)

    locators = client.get("/api/equipment/windows/locators")
    assert locators.status_code == 200
    assert locators.json()["tool"] == "equipment.pyautogui.list_locators"

    profile = client.get("/api/equipment/windows/utm-profile")
    assert profile.status_code == 200
    assert profile.json()["tool"] == "equipment.pyautogui.utm_profile"

    saved_profile = client.post(
        "/api/equipment/windows/utm-profile",
        json={
            "program_id": "utm_compression_start_v1",
            "export_glob": "contract*.csv",
            "artifact_timeout_s": 33,
            "stable_for_sec": 1.5,
            "require_screen_assertions": True,
            "robot_entry_clearance_mm": 150,
            "locators": {"ready_state": {"image_path": "C:/ATR/locators/ready.png", "confidence": 0.8}},
        },
    )
    assert saved_profile.status_code == 200
    assert saved_profile.json()["tool"] == "equipment.pyautogui.save_utm_profile"
    assert saved_profile.json()["profile"]["export_glob"] == "contract*.csv"
    assert saved_profile.json()["profile"]["robot_entry_clearance_mm"] == 150.0

    readiness_blocked = client.get("/api/equipment/windows/readiness")
    assert readiness_blocked.status_code == 200
    assert readiness_blocked.json()["tool"] == "equipment.pyautogui.utm_readiness"
    assert readiness_blocked.json()["status"] == "blocked"
    assert "PYAUTOGUI_BRIDGE_NOT_SELECTED" in readiness_blocked.json()["blockers"]

    saved_connection = client.post(
        "/api/equipment/windows/connect",
        json={
            "candidate_alias": "utm_pc",
            "bridge_url": "http://192.168.50.58:8765",
            "token": "test-token",
        },
    )
    assert saved_connection.status_code == 200

    readiness_incomplete = client.get("/api/equipment/windows/readiness")
    assert readiness_incomplete.status_code == 200
    incomplete_payload = readiness_incomplete.json()
    assert incomplete_payload["status"] == "blocked"
    assert incomplete_payload["ready_for_setup_test"] is False
    assert incomplete_payload["ready_for_autonomous_profile"] is False
    assert "UTM_REQUIRED_LOCATORS_MISSING" in incomplete_payload["blockers"]
    assert incomplete_payload["gates"]["locator_count"] == 1
    assert incomplete_payload["gates"]["required_locator_names"] == ["ready_state", "start_button", "running_state", "complete_state"]
    assert incomplete_payload["gates"]["missing_required_locators"] == ["start_button", "running_state", "complete_state"]

    full_profile = client.post(
        "/api/equipment/windows/utm-profile",
        json={
            "program_id": "utm_compression_start_v1",
            "export_glob": "contract*.csv",
            "artifact_timeout_s": 33,
            "stable_for_sec": 1.5,
            "require_screen_assertions": True,
            "locators": {
                "ready_state": {"image_path": "C:/ATR/locators/ready.png", "confidence": 0.8},
                "start_button": {"image_path": "C:/ATR/locators/start.png", "confidence": 0.8},
                "running_state": {"image_path": "C:/ATR/locators/running.png", "confidence": 0.8},
                "complete_state": {"image_path": "C:/ATR/locators/complete.png", "confidence": 0.8},
            },
        },
    )
    assert full_profile.status_code == 200

    readiness_ready = client.get("/api/equipment/windows/readiness")
    assert readiness_ready.status_code == 200
    assert readiness_ready.json()["status"] == "ready"
    assert readiness_ready.json()["ready_for_setup_test"] is True
    assert readiness_ready.json()["ready_for_autonomous_profile"] is True
    assert readiness_ready.json()["gates"]["locator_count"] == 4
    assert readiness_ready.json()["gates"]["missing_required_locators"] == []
    assert readiness_ready.json()["gates"]["required_locators_complete"] is True

    missing_confirm = client.post("/api/equipment/windows/screenshot", json={"checkpoint": "manual"})
    assert missing_confirm.status_code == 400

    screenshot = client.post(
        "/api/equipment/windows/screenshot",
        json={"checkpoint": "manual", "run_id": "contract-test", "confirm_capture": True},
    )
    assert screenshot.status_code == 200
    assert screenshot.json()["tool"] == "equipment.pyautogui.screenshot"

    missing_capture_confirm = client.post(
        "/api/equipment/windows/capture-locator",
        json={"program_id": "utm_compression_start_v1", "name": "ready_state", "region": [0, 0, 10, 10]},
    )
    assert missing_capture_confirm.status_code == 400

    invalid_region = client.post(
        "/api/equipment/windows/capture-locator",
        json={"program_id": "utm_compression_start_v1", "name": "ready_state", "confirm_capture": True},
    )
    assert invalid_region.status_code == 200
    assert invalid_region.json()["failure_code"] == "PYAUTOGUI_LOCATOR_REGION_REQUIRED"


def test_windows_equipment_live_preflight_api_contract(monkeypatch) -> None:
    import app.main as app_main

    class FakeWindowsBridge:
        def connection_status(self) -> dict[str, object]:
            return {
                "ok": True,
                "selected": True,
                "token_configured": True,
                "selected_candidate": "utm_pc",
                "bridge_url": "http://192.168.50.58:8765",
            }

        def utm_profile_status(self) -> dict[str, object]:
            return {
                "ok": True,
                "tool": "equipment.pyautogui.utm_profile",
                "status": "ready",
                "source": "memory",
                "profile_memory_path": "memory/equipment_utm_profile.json",
                "profile": {
                    "program_id": "utm_compression_start_v1",
                    "export_glob": "*.csv",
                    "artifact_timeout_s": 60,
                    "stable_for_sec": 2.0,
                    "require_screen_assertions": True,
                    "simulate_utm_protocol": False,
                    "locators": {
                        "ready_state": {"image_path": "C:/ATR/locators/ready.png"},
                        "start_button": {"image_path": "C:/ATR/locators/start.png"},
                        "running_state": {"image_path": "C:/ATR/locators/running.png"},
                        "complete_state": {"image_path": "C:/ATR/locators/complete.png"},
                    },
                },
            }

        def list_programs(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            return {
                "ok": True,
                "tool": "equipment.pyautogui.list_programs",
                "status": "ready",
                "programs": [{"program_id": "utm_compression_start_v1", "program_type": "utm_protocol"}],
            }

        def health(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            return {
                "ok": True,
                "tool": "equipment.pyautogui.health",
                "mode": "live",
                "status": "ready",
                "pyautogui": {"available": True, "failsafe": True},
            }

        def list_locators(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            return {
                "ok": True,
                "tool": "equipment.pyautogui.list_locators",
                "mode": "live",
                "status": "ready",
                "locators": [
                    {"program_id": "utm_compression_start_v1", "name": "ready_state"},
                    {"program_id": "utm_compression_start_v1", "name": "start_button"},
                    {"program_id": "utm_compression_start_v1", "name": "running_state"},
                    {"program_id": "utm_compression_start_v1", "name": "complete_state"},
                ],
            }

        def request_log(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            return {
                "ok": True,
                "tool": "equipment.pyautogui.request_log",
                "mode": "live",
                "status": "ready",
                "request_log": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                "event_count": 2,
                "events": [
                    {"path": "/health", "token_header_present": True, "auth_ok": True},
                    {"path": "/programs", "token_auth_enabled": True, "auth_ok": True},
                ],
            }

        def screenshot(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            return {
                "ok": True,
                "tool": "equipment.pyautogui.screenshot",
                "mode": "live",
                "status": "captured",
                "artifact_path": "/tmp/atr/preflight.png",
            }

    monkeypatch.setattr(app_main, "_equipment_bridge", lambda: FakeWindowsBridge())
    client = TestClient(app)

    missing_confirm = client.post("/api/equipment/windows/live-preflight", json={})
    assert missing_confirm.status_code == 400

    preflight = client.post(
        "/api/equipment/windows/live-preflight",
        json={"confirm_preflight": True, "include_locators": True, "include_screenshot": True},
    )
    assert preflight.status_code == 200
    data = preflight.json()
    assert data["tool"] == "equipment.pyautogui.live_preflight"
    assert data["status"] == "ready"
    assert data["non_actuating"] is True
    assert data["ready_for_autonomous_profile"] is True
    assert "/execute" not in data["touched_endpoints"]
    assert data["touched_endpoints"] == ["/health", "/programs", "/locators", "/request-log", "/screenshot"]
    assert data["request_audit_log"]["ok"] is True
    assert data["request_audit_log"]["path"].endswith("bridge_requests.jsonl")
    assert data["checks"][-1]["name"] == "preflight_screenshot"
    assert data["evidence_refs"] == ["/tmp/atr/preflight.png"]


def test_windows_equipment_live_validation_api_contract(monkeypatch) -> None:
    import app.main as app_main

    class FakeWindowsBridge:
        def health(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            assert payload is not None
            assert payload.get("runtime_mode") == "live"
            assert payload.get("force_live_bridge") is True
            return {
                "ok": True,
                "tool": "equipment.pyautogui.health",
                "mode": "live",
                "status": "ready",
                "bridge_url": "http://192.168.50.58:8765",
                "bridge_host": "192.168.50.58",
                "pyautogui": {"available": True, "failsafe": True},
            }

        def list_programs(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            assert payload is not None
            assert payload.get("runtime_mode") == "live"
            assert payload.get("force_live_bridge") is True
            return {
                "ok": True,
                "tool": "equipment.pyautogui.list_programs",
                "mode": "live",
                "status": "ready",
                "programs": [{"program_id": "utm_compression_start_v1", "program_type": "utm_protocol"}],
            }

        def request_log(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            assert payload is not None
            assert payload.get("runtime_mode") == "live"
            assert payload.get("force_live_bridge") is True
            return {
                "ok": True,
                "tool": "equipment.pyautogui.request_log",
                "mode": "live",
                "status": "ready",
                "request_log": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                "event_count": 2,
                "events": [
                    {"path": "/health", "token_header_present": True, "auth_ok": True},
                    {"path": "/programs", "token_auth_enabled": True, "auth_ok": True},
                ],
            }

    monkeypatch.setattr(app_main, "_equipment_bridge", lambda: FakeWindowsBridge())
    client = TestClient(app)

    blocked = client.post("/api/equipment/windows/live-validation", json={})
    assert blocked.status_code == 400

    response = client.post(
        "/api/equipment/windows/live-validation",
        json={
            "confirm_non_actuating": True,
            "run_id": "unit-live-validation",
            "sequence_id": "unit-live-validation",
            "specimen_id": "specimen-unit",
            "program_id": "utm_compression_start_v1",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tool"] == "equipment.pyautogui.live_validation"
    assert data["schema"] == "lab_equipment_utm_live_validation.v1"
    assert data["status"] == "preflight_passed"
    assert data["non_actuating"] is True
    assert data["ready_for_physical_live_run"] is True
    assert "/execute" not in data["touched_endpoints"]
    assert data["report_artifact"]["path"].endswith("lab_equipment_utm_live_validation.json")
    assert any(item["name"] == "execution_not_sent" and item["required"] is False for item in data["gates"])


def test_windows_equipment_physical_live_validation_api_contract(monkeypatch, tmp_path: Path) -> None:
    import app.main as app_main

    csv_path = tmp_path / "utm_live.csv"
    csv_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0.2,320\n", encoding="utf-8")
    screen_paths = []
    for name in ("before", "running", "complete"):
        path = tmp_path / f"utm_live_{name}.png"
        path.write_bytes(TINY_PNG_BYTES)
        screen_paths.append(path)

    class FakeWindowsBridge:
        def __init__(self) -> None:
            self.executed = False

        def connection_status(self) -> dict[str, object]:
            return {
                "ok": True,
                "selected": True,
                "token_configured": True,
                "selected_candidate": "utm_pc",
                "bridge_url": "http://192.168.50.58:8765",
            }

        def utm_profile_status(self) -> dict[str, object]:
            return {
                "ok": True,
                "status": "ready",
                "source": "memory",
                "profile_memory_path": "memory/equipment_utm_profile.json",
                "profile": {
                    "program_id": "utm_compression_start_v1",
                    "export_glob": "*.csv",
                    "require_screen_assertions": True,
                    "simulate_utm_protocol": False,
                    "locators": {
                        "ready_state": {"image_path": "C:/ATR/locators/ready.png"},
                        "start_button": {"image_path": "C:/ATR/locators/start.png"},
                        "running_state": {"image_path": "C:/ATR/locators/running.png"},
                        "complete_state": {"image_path": "C:/ATR/locators/complete.png"},
                    },
                },
            }

        def health(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            return {
                "ok": True,
                "tool": "equipment.pyautogui.health",
                "mode": "live",
                "status": "ready",
                "bridge_url": "http://192.168.50.58:8765",
                "bridge_host": "192.168.50.58",
                "pyautogui": {"available": True, "failsafe": True},
            }

        def list_programs(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            return {
                "ok": True,
                "tool": "equipment.pyautogui.list_programs",
                "mode": (payload or {}).get("runtime_mode", "test"),
                "status": "ready",
                "programs": [{"program_id": "utm_compression_start_v1", "program_type": "utm_protocol"}],
            }

        def list_locators(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            return {
                "ok": True,
                "tool": "equipment.pyautogui.list_locators",
                "mode": "live",
                "status": "ready",
                "locators": [
                    {"program_id": "utm_compression_start_v1", "name": "ready_state"},
                    {"program_id": "utm_compression_start_v1", "name": "start_button"},
                    {"program_id": "utm_compression_start_v1", "name": "running_state"},
                    {"program_id": "utm_compression_start_v1", "name": "complete_state"},
                ],
            }

        def request_log(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            events = [{"path": "/health", "auth_ok": True}]
            result: dict[str, object] = {
                "ok": True,
                "tool": "equipment.pyautogui.request_log",
                "mode": "live",
                "status": "ready",
                "request_log": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                "event_count": len(events),
                "events": events,
            }
            if self.executed:
                execute_event = {
                    "path": "/execute",
                    "audit_kind": "execute_payload",
                    "run_id": "unit-physical-validation",
                    "sequence_id": "unit-physical-validation",
                    "specimen_id": "specimen-unit",
                    "program_id": "utm_compression_start_v1",
                }
                events.append(execute_event)
                result.update(
                    {
                        "event_count": len(events),
                        "execute_event_seen": True,
                        "execute_event_count": 1,
                        "execute_run_ids": ["unit-physical-validation"],
                        "execute_sequence_ids": ["unit-physical-validation"],
                        "execute_specimen_ids": ["specimen-unit"],
                        "execute_program_ids": ["utm_compression_start_v1"],
                    }
                )
            return result

        def run(self, payload: dict[str, object]) -> dict[str, object]:
            assert payload["confirm_setup_gui_execute"] is True
            assert payload["run_id"] == "unit-physical-validation"
            self.executed = True
            return {
                "ok": True,
                "tool": "equipment.pyautogui.run",
                "status": "verified_complete",
                "run_id": "unit-physical-validation",
                "sequence_id": "unit-physical-validation",
                "specimen_id": "specimen-unit",
                "program_id": "utm_compression_start_v1",
                "result_file": str(csv_path),
                "utm_csv_path": str(csv_path),
                "screen_checks": [
                    {"checkpoint": "before_start", "ok": True, "screenshot_artifact": "screen-before"},
                    {"checkpoint": "after_start", "ok": True, "screenshot_artifact": "screen-running"},
                    {"checkpoint": "after_complete", "ok": True, "screenshot_artifact": "screen-complete"},
                ],
                "artifact_records": [
                    {"kind": "screen_png", "artifact_id": "screen-before", "local_path": str(screen_paths[0])},
                    {"kind": "screen_png", "artifact_id": "screen-running", "local_path": str(screen_paths[1])},
                    {"kind": "screen_png", "artifact_id": "screen-complete", "local_path": str(screen_paths[2])},
                ],
                "data_acquisition": {
                    "status": "pulled_to_linux",
                    "save_method": "manual_save_dialog",
                    "save_attempted_by_agent": True,
                    "save_confirmation_screen_ok": True,
                    "windows_path": "C:/ATR/utm_exports/unit/specimen.csv",
                    "linux_path": str(csv_path),
                    "row_count_probe": 2,
                    "columns_probe": ["time_s", "displacement_mm", "force_N"],
                    "local_parse_ok": True,
                },
                "artifact_pull": {"status": "complete", "data_artifact_pulled": True, "data_artifact_parse_ok": True},
                "cross_checks": {"save_export_responsibility_ok": True, "data_parse_probe_ok": True},
                "step_trace": [{"step": "DONE", "status": "ok"}],
            }

    bridge = FakeWindowsBridge()
    monkeypatch.setattr(app_main, "_equipment_bridge", lambda: bridge)
    client = TestClient(app)
    original_metadata = dict(controller._state.run_metadata)
    controller._state.run_metadata.clear()

    missing_safety = client.post("/api/equipment/windows/live-validation", json={"confirm_live_execute": True})
    assert missing_safety.status_code == 400

    try:
        response = client.post(
        "/api/equipment/windows/live-validation",
        json={
            "confirm_live_execute": True,
            "confirm_physical_setup_safe": True,
            "run_id": "unit-physical-validation",
            "sequence_id": "unit-physical-validation",
            "specimen_id": "specimen-unit",
            "program_id": "utm_compression_start_v1",
            "require_screen_assertions": True,
            "vision_proof": {
                "ok": True,
                "run_id": "unit-physical-validation",
                "specimen_id": "specimen-unit",
                "checks": {
                    "utm_pre_start": {"ok": True, "evidence": {"frame_ids": ["frame-pre-unit"]}},
                    "utm_motion_confirm": {"ok": True, "evidence": {"frame_ids": ["frame-motion-unit"]}},
                    "utm_test_complete": {"ok": True, "evidence": {"frame_ids": ["frame-complete-unit"]}},
                },
                "evidence": {"frame_ids": ["frame-pre-unit", "frame-motion-unit", "frame-complete-unit"]},
            },
        },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["status"] == "verified_complete"
        assert data["requested_physical_execute"] is True
        assert data["execute_sent"] is True
        assert data["non_actuating"] is False
        assert "/execute" in data["touched_endpoints"]
        assert data["summary"]["physical_live_evidence_captured"] is True
        assert data["report_artifact"]["path"].endswith("lab_equipment_utm_live_validation.json")
        gate_names = {item["name"] for item in data["gates"]}
        assert {"pre_execution_readiness", "pre_execution_live_preflight", "physical_setup_confirmation", "vision_physical_cross_check", "utm_csv_parse_probe"} <= gate_names

        audit = client.get("/api/equipment/windows/evidence-audit").json()
        assert audit["status"] == "ready_for_analysis"
        assert audit["source_live_validation_report"]["execute_sent"] is True
        assert audit["gates"]["vision_evidence_complete"] is True
        assert audit["proof_ready"] is True

        proof_package = client.get("/api/equipment/windows/proof-package").json()
        assert proof_package["status"] == "ready_for_analysis"
        assert proof_package["ready_for_analysis"] is True
        assert proof_package["last_windows_utm_physical_validation"]["execute_sent"] is True
        assert proof_package["source_packets"]["last_windows_utm_physical_validation"]["execute_sent"] is True

        assert data["runtime_promotion"]["verified"] is True
        assert data["runtime_promotion"]["analysis_handoff_status"] == "ready_for_analysis"
        metadata = controller._state.run_metadata
        assert metadata["equipment_result"]["result_file"] == str(csv_path)
        assert metadata["equipment_result"]["utm_csv_path"] == str(csv_path)
        assert metadata["equipment_result"]["equipment_report"]["live_evidence_audit"]["required_for_handoff"] is True
        assert metadata["equipment_report"]["cross_checks"]["request_audit_execute_identity_match"] is True
        assert metadata["equipment_handoff"]["status"] == "ready_for_analysis"
        assert metadata["equipment_handoff"]["result_file"] == str(csv_path)
        assert metadata["utm_data_ready"]["status"] == "ready"
        assert metadata["utm_data_ready"]["result_file"] == str(csv_path)
        assert metadata["last_windows_utm_runtime_promotion"]["verified"] is True
    finally:
        controller._state.run_metadata.clear()
        controller._state.run_metadata.update(original_metadata)


def test_windows_equipment_request_log_api_contract(monkeypatch) -> None:
    import app.main as app_main

    class FakeWindowsBridge:
        def request_log(self, payload: dict[str, object] | None = None) -> dict[str, object]:
            assert payload is not None
            assert payload.get("runtime_mode") == "live"
            assert payload.get("force_live_bridge") is True
            return {
                "ok": True,
                "tool": "equipment.pyautogui.request_log",
                "mode": "live",
                "status": "ready",
                "request_log": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                "event_count": 1,
                "events": [
                    {
                        "path": "/execute",
                        "auth_ok": True,
                        "token_header_present": True,
                        "token_value": "secret-should-not-return",
                    }
                ],
            }

    monkeypatch.setattr(app_main, "_equipment_bridge", lambda: FakeWindowsBridge())
    client = TestClient(app)

    blocked = client.post("/api/equipment/windows/request-log", json={"runtime_mode": "live"})
    assert blocked.status_code == 200
    assert blocked.json()["failure_code"] == "PYAUTOGUI_REQUEST_LOG_CONFIRMATION_REQUIRED"

    response = client.post("/api/equipment/windows/request-log", json={"runtime_mode": "live", "confirm_live": True})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["non_actuating"] is True
    assert data["request_log"].endswith("bridge_requests.jsonl")
    assert data["events"][0]["token_header_present"] is True
    assert "token_value" not in data["events"][0]


def test_live_gui_emergency_stop_controls_are_distinct_from_safe_stop() -> None:
    client = TestClient(app)
    html = client.get("/live").text
    script = client.get("/static/planning.js").text
    styles = client.get("/static/styles.css").text

    assert 'id="btn-live-safe-stop"' in html
    assert 'id="live-emergency-recovery"' in html
    assert 'id="btn-live-emergency-resume"' in html
    assert 'id="btn-live-emergency-reset"' in html
    assert "/api/run/emergency-stop" in script
    assert "/api/run/emergency-resume" in script
    assert "/api/run/emergency-reset" in script
    assert "function updateLiveEmergencyStopControls" in script
    assert "emergency_stop_requested" in script
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) !important;" in styles
    assert "body.planning-live-body .mission-status-stop #btn-live-safe-stop" in styles
    assert "place-self: stretch !important;" in styles


def test_live_gui_recovery_controls_are_gated_by_estop_source_not_plc_connection() -> None:
    client = TestClient(app)
    html = client.get("/live").text
    script = client.get("/static/planning.js").text

    assert 'id="live-plc-emergency-guidance"' in html
    assert '<strong>PLC E-STOP</strong>' not in html
    assert "ONLINE · pymcprotocol" not in html
    assert "PB1 short: Resume" in html
    assert "PB1 long: Reset" in html
    assert 'id="btn-live-emergency-resume" class="btn live-emergency-resume" hidden disabled' in html
    assert 'id="btn-live-emergency-reset" class="btn live-emergency-reset" hidden disabled' in html
    assert 'fetchJsonOrThrowWithTimeout(\n        "/api/plc/status"' in script
    assert "function updateLiveEmergencyStopControls" in script
    assert "function liveEmergencySourceSet" in script
    assert 'activeSources.has("plc_pb2")' in script
    assert 'activeSources.has("gui_estop") || activeSources.has("gui")' in script
    assert "const sourcePending = latched && !plcSourceLocked && !guiSourceLatched;" in script
    assert "btnLiveEmergencyResume.hidden = plcSourceLocked || sourcePending;" in script
    assert "btnLiveEmergencyReset.hidden = plcSourceLocked || sourcePending;" in script
    assert "btnLiveEmergencyResume.disabled = plcSourceLocked || sourcePending" in script
    assert "btnLiveEmergencyReset.disabled = plcSourceLocked || sourcePending" in script
    assert "const plcRecoveryLocked = plcSourceLocked || livePLCOnline;" not in script
    assert "LIVE_PLC_STATUS_REFRESH_MS" in script
    assert "LIVE_PLC_STATUS_FETCH_TIMEOUT_MS" in script
    assert "refreshLivePLCStatus" in script
    assert "refreshLivePLCStatus({ force: true }).catch(() => {});" in script
    assert "plc_status_refresh_in_flight: Boolean(livePLCStatusRefreshInFlight)" in script


def test_runtime_ide_projects_plc_as_device_bridge_not_executable_stage() -> None:
    client = TestClient(app)

    bridge_response = client.get("/api/bridges")
    graph_response = client.get("/api/graphs/atr_closed_loop")

    assert bridge_response.status_code == 200
    assert graph_response.status_code == 200
    bridges = bridge_response.json()["bridges"]
    plc_bridge = next(bridge for bridge in bridges if bridge["id"] == "plc_bridge")
    assert plc_bridge["workspace"] == "/plc"
    assert plc_bridge["config"] == "configs/plc.yaml"
    assert "D100-D102" in plc_bridge["live_boundary"]

    graph = graph_response.json()["graph"]
    assert all(node.get("id") != "plc_bridge" for node in graph["nodes"])
    assert all(
        edge.get("source") != "plc_bridge" and edge.get("target") != "plc_bridge"
        for edge in graph["edges"]
    )


def test_mouse_emergency_stop_resume_reset_runtime_contract_remains_gui_controlled() -> None:
    client = TestClient(app)

    stop_response = client.post("/api/run/emergency-stop")
    assert stop_response.status_code == 200
    stop_payload = stop_response.json()
    assert stop_payload["ok"] is True
    stop_state = stop_payload["state"]
    assert stop_state["emergency_stop_requested"] is True
    assert stop_state["stop_requested"] is True
    assert stop_state["safe_stop_requested"] is False
    planning_state = client.get("/api/planning/session").json()["state"]
    assert set(planning_state["run_metadata"]["active_safety_sources"]) == {
        "gui_estop"
    }

    resume_response = client.post("/api/run/emergency-resume")
    assert resume_response.status_code == 200
    assert resume_response.json()["ok"] is True
    resume_state = controller.snapshot()["state"]
    assert resume_state["emergency_stop_requested"] is False
    assert resume_state["stop_requested"] is False
    assert resume_state["safe_stop_requested"] is False

    stop_response = client.post("/api/run/emergency-stop")
    assert stop_response.status_code == 200
    reset_response = client.post("/api/run/emergency-reset")
    assert reset_response.status_code == 200
    assert reset_response.json()["ok"] is True
    reset_state = controller.snapshot()["state"]
    assert reset_state["emergency_stop_requested"] is False
    assert reset_state["stop_requested"] is False
    assert reset_state["safe_stop_requested"] is False


def test_run_scoped_mouse_emergency_resume_reset_remains_gui_controlled() -> None:
    client = TestClient(app)
    run_id = controller.snapshot()["state"]["run_id"]

    stop_response = client.post(f"/api/runs/{run_id}/emergency-stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["state"]["emergency_stop_requested"] is True

    resume_response = client.post(f"/api/runs/{run_id}/emergency-resume")
    assert resume_response.status_code == 200
    assert resume_response.json()["ok"] is True
    assert controller.snapshot()["state"]["emergency_stop_requested"] is False

    stop_response = client.post(f"/api/runs/{run_id}/emergency-stop")
    assert stop_response.status_code == 200
    reset_response = client.post(f"/api/runs/{run_id}/emergency-reset")
    assert reset_response.status_code == 200
    assert reset_response.json()["ok"] is True
    assert controller.snapshot()["state"]["emergency_stop_requested"] is False


def test_live_gui_emergency_controls_use_run_scoped_endpoints_and_clear_stale_cache() -> None:
    client = TestClient(app)
    script = client.get("/static/planning.js").text

    assert "liveEmergencyEndpoint" in script
    assert 'liveEmergencyEndpoint("emergency-stop", "/api/run/emergency-stop")' in script
    assert 'liveEmergencyEndpoint("emergency-resume", "/api/run/emergency-resume")' in script
    assert 'liveEmergencyEndpoint("emergency-reset", "/api/run/emergency-reset")' in script
    assert "resetLiveRunScopedStateForAuthoritativeSession" in script
    assert "discardStaleLivePlanningCache" not in script
    assert "liveBrowserCacheRestoredRunId" in script


def test_live_gui_emergency_reset_uses_one_authoritative_run_transition_path() -> None:
    client = TestClient(app)
    script = client.get("/static/planning.js").text

    assert "function resetLiveRunScopedStateForAuthoritativeSession" in script
    assert "resetLiveRunScopedStateForAuthoritativeSession(authoritativeSession)" in script
    assert "liveAppliedAuthoritativeRunId" in script
    assert "liveRunEvents = []" in script
    assert "liveRecentEvents = []" in script
    assert "liveRunArtifacts = []" in script
    assert "liveApprovals = { approvals: [], pending: [], resolved: [] }" in script
    assert "const runTransitionReset = resetLiveRunScopedStateForAuthoritativeSession" in script
    assert "messages: []" in script
    assert "message_total: 0" in script
    assert "function resetPlanningSessionIdForEmergencyReset" not in script

    reset_function = script.split("async function requestLiveEmergencyReset()", 1)[1].split(
        "\ndocument.addEventListener", 1
    )[0]
    assert "const result = await fetchJsonOrThrow(endpoint" in reset_function
    assert "applyPlanningSession({ ...(liveLastSession || {}), state: result.state })" in reset_function
    assert "clearLiveBoVisualization()" not in reset_function
    assert "resetPlanningMessageDisplayState()" not in reset_function
    assert "resetPlanningSessionIdForEmergencyReset()" not in reset_function


def test_live_gui_manipulation_agent_uses_current_supervisor_language() -> None:
    client = TestClient(app)
    script = client.get("/static/planning.js").text
    report = client.get("/api/agents/manipulation/report").json()["report"]

    assert "Runtime Execution" in script
    assert "Runtime Interlocks" in script
    assert "Completion Verification" in script
    assert "Run Result" in script
    assert "Run Metrics" in script
    assert "Task Success Rate" in script
    assert "Grasp Success Rate" in script
    assert 'renderDashboardCard("Policy Runtime"' not in script
    assert 'renderDashboardCard("Execution Supervision"' not in script
    assert 'renderDashboardCard("Vision / UTM Verification"' not in script
    assert 'renderDashboardCard("Safety Gate / Object Pose"' not in script
    assert "Home Pose" not in script
    assert "Current Manipulation Report Missing" not in script
    for stale_label in [
        "Policy / Pi0.5",
        "Pi0.5 / LeRobot Boundary",
        "SARM Progress",
        "SARM / Preflight",
        "manipulation SARM scores",
        "Pi0.5/LeRobot preflight",
        "Run bounded LeRobot/Pi0.5 rollout",
        "Use SARM risk/recovery gate",
        "Bounded Pi0.5/LeRobot skill execution",
    ]:
        assert stale_label not in script
        assert stale_label not in json.dumps(report, ensure_ascii=False)


def test_live_gui_manipulation_pose_and_policy_tracking_cards_are_locally_bundled() -> None:
    client = TestClient(app)

    html = client.get("/live").text
    script = client.get("/static/planning.js").text
    styles = client.get("/static/styles.css").text
    bundle_response = client.get("/static/omx_telemetry_viewer.bundle.js")

    assert '/static/styles.css?v=20260825-plc-safety-lifecycle-5' in html
    assert '/static/omx_telemetry_viewer.bundle.js?v=20260720-manipulation-grounded-1' in html
    assert '/static/planning.js?v=20260901-equipment-overlay-1' in html
    assert bundle_response.status_code == 200
    bundle = bundle_response.text
    for required in [
        "Live Robot Pose",
        "Robot motion state :",
        "Policy Tracking",
        "Runtime State Strip",
        "Runtime Execution",
        "Runtime Interlocks",
        "Completion Verification",
        "Run Result",
        "Run Metrics",
        "data-atr-robot-pose",
        "data-atr-robot-motion-state",
        "data-atr-policy-tracking",
        "data-atr-motion-state",
        "Joint selector",
        "Home Gate",
        "Grasp Result",
        "data-atr-grasp-outcome",
        "data-atr-grasp-status",
        "data-atr-grasp-gap",
        'data-atr-motion-summary="${channel}"',
        'motionSummary("measured", "Measured follower")',
        'motionSummary("policy", "Policy target")',
        "ar-man-motion-unified",
        "Policy tracking artifacts",
        "ATRRobotTelemetryCards.hydrate",
        "data-atr-runtime-execution",
        "data-atr-runtime-interlocks",
        "data-atr-runtime-completion",
        "data-atr-runtime-result",
        "data-atr-runtime-metrics",
        'data-atr-runtime-donut="task"',
        'data-atr-runtime-donut="grasp"',
        "Task Success Rate",
        "Grasp Success Rate",
    ]:
        assert required in script
    assert '["Joint1", -15, -6.5]' in script
    for required in [
        "/ws/lerobot/joint-telemetry",
        "/assets/robotis-omx/omx.xml",
        "/assets/robotis-omx/scene/omx_table_layout.web.json",
        "/api/lerobot/active-robot-cam/specimen-pose",
        "STLLoader",
        "EdgesGeometry",
        "environmentGroup",
        "RedSpecimenBlock",
        "measuredRobot",
        "policyTargetGhost",
        "Measured follower",
        "Policy target",
        "Elapsed time (s)",
        "LeRobot joint value",
        "actual_source",
        "target_source",
        "compactHistory",
        "normalizedElapsed",
        "stableYDomains",
        "formatAxisValue",
        "motion_state",
        "base_state",
        "gripper_state",
        "grasp_outcome",
        "applyGraspOutcome",
        "applyRobotMotionLabel",
        "applySpecimenGraspVisualization",
        "attachSpecimenToGripper",
        "releaseSpecimenFromGripper",
        "setGripperOutcomeGlow",
        "graspAnchor",
        "specimenGraspState",
        "#22c55e",
        "#ef4444",
        "is-measured",
        "is-policy",
        "home",
        "moving",
        "grasping",
        "ungrasping",
        "#ffffff",
        "MAX_HISTORY_SAMPLES",
        "CAMERA_FIT_PADDING",
        "buildBoxSurfaceGrid",
        "buildCylinderSurfaceGrid",
        "environment-surface-grid-5mm",
        "replaceJointHistory",
        "telemetry_artifacts",
        "latest_grasp_outcome",
        "applyGraspOutcome(runtime.artifacts.latest_grasp_outcome)",
        "settleSpecimenOnSupport",
        "RightDiskAluminumTop",
        "supportTop",
    ]:
        assert required in bundle
    assert 'BASE_MOTION_STATES = ["home", "moving"]' in bundle
    assert "Joint position (deg)" not in bundle
    for required in [
        ".ar-man-motion-state",
        ".ar-man-motion-unified",
        ".ar-man-motion-legend",
        ".ar-man-motion-segments",
        ".is-measured",
        ".is-policy",
        ".is-measured.is-policy",
        ".ar-man-home-gate",
        ".ar-man-home-grid",
        ".ar-man-grasp-outcome",
        '[data-status="pending"]',
        '[data-status="success"]',
        '[data-status="failed"]',
        '[data-pass="yes"]',
        '[data-pass="no"]',
    ]:
        assert required in styles
    assert "Environment mesh 5 mm" not in script
    assert ".ar-man-pose-legend i.environment" not in styles
    assert "ar-man-motion-channels" not in script
    assert "data-atr-task-success-rate" in script
    assert "data-atr-grasp-success-rate" in script
    for conceptual_title in [
        "Execution Control",
        "Performance KPIs",
        "Grasp / Path Plan",
        "Active Camera / Workspace",
        "Safety Gate / Object Pose",
        "Motion Trace",
        "Task Route",
        "Policy Runtime",
        "Preflight Gates",
        "Execution Supervision",
    ]:
        assert f'renderDashboardCard("{conceptual_title}"' not in script
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in styles


def test_live_gui_knowledge_activity_uses_preserved_realtime_histogram() -> None:
    client = TestClient(app)

    html = client.get("/live").text
    script = client.get("/static/planning.js").text
    styles = client.get("/static/styles.css").text

    assert "/static/styles.css?v=20260825-plc-safety-lifecycle-5" in html
    for required in [
        "Knowledge Activity",
        "data-atr-knowledge-activity",
        "knowledgeActivityChartOption",
        "/api/knowledge/activity",
        "Collected",
        "Updated",
        "Retrieved",
        "Used",
        '"live-preserve": "knowledge-activity"',
    ]:
        assert required in script
    assert "ar-knw-activity-chart" in styles
    assert "background: #ffffff" in styles


def test_live_robot_pose_has_repeatable_zoom_to_fit_control() -> None:
    client = TestClient(app)

    html = client.get("/live").text
    script = client.get("/static/planning.js").text
    styles = client.get("/static/styles.css").text
    bundle = client.get("/static/omx_telemetry_viewer.bundle.js").text

    assert 'data-atr-pose-fit' in script
    assert 'aria-label="Zoom to fit"' in script
    assert "CAMERA_FIT_DISTANCE_SCALE = 1.34" in bundle
    assert "CAMERA_FIT_VERTICAL_OFFSET_M = -0.115" in bundle
    assert "new Vector3(0.03, 0, CAMERA_FIT_VERTICAL_OFFSET_M)" in bundle
    assert "zoomToFit" in bundle
    assert "bindPoseFitButtons" in bundle
    assert ".ar-man-pose-fit" in styles
    assert '/static/styles.css?v=20260825-plc-safety-lifecycle-5' in html
    assert '/static/omx_telemetry_viewer.bundle.js?v=20260720-manipulation-grounded-1' in html
    assert '/static/planning.js?v=20260901-equipment-overlay-1' in html


def test_live_gui_serves_repository_omx_model_assets() -> None:
    client = TestClient(app)

    model = client.get("/assets/robotis-omx/omx.xml")
    mesh = client.get("/assets/robotis-omx/assets/follower_01_base.stl")

    assert model.status_code == 200
    assert '<mujoco model="omx">' in model.text
    assert mesh.status_code == 200
    assert len(mesh.content) > 100


def test_live_gui_serves_lightweight_omx_environment_manifest() -> None:
    client = TestClient(app)

    response = client.get("/assets/robotis-omx/scene/omx_table_layout.web.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "atr.omx_web_scene.v1"
    assert payload["source"] == "omx_table_layout.usda"
    assert payload["meters_per_unit"] == 1.0
    assert payload["up_axis"] == "Z"
    assert payload["robot_anchor"] == {
        "position": [0.315, 0.06, -0.02],
        "rotation_z_deg": 90.0,
    }
    assert payload["grid"]["spacing_m"] == 0.005
    assert payload["grid"]["major_spacing_m"] == 0.05
    assert payload["wireframe"]["spacing_m"] == 0.005
    assert payload["wireframe"]["color"] == "#8fb7cc"
    names = {item["name"] for item in payload["objects"]}
    assert {
        "TableTop",
        "A4Sheet",
        "RightDiskAluminumTop",
        "RedSpecimenBlock",
    }.issubset(names)
    assert "Robot" not in names


def test_live_gui_active_robot_cam_specimen_pose_endpoint(monkeypatch) -> None:
    import app.main as main_module

    pose = {
        "schema": "specimen_pose.v1",
        "frame_id": "record-frame-9",
        "position_isaac_world_mm": {"x": 250.0, "y": 300.0, "z": 15.0},
        "orientation_deg": {"yaw": 8.0},
    }
    monkeypatch.setattr(main_module, "_recording_active_cam_specimen_pose", lambda: pose)
    client = TestClient(app)

    response = client.get("/api/lerobot/active-robot-cam/specimen-pose")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "source": "recording_active_robot_cam",
        "pose": pose,
    }


def test_joint_telemetry_snapshot_reports_idle_without_rollout(monkeypatch) -> None:
    import app.main as main_module

    monkeypatch.setattr(main_module, "_joint_telemetry_session_context", lambda: None)
    client = TestClient(app)

    response = client.get("/api/lerobot/joint-telemetry/snapshot")

    assert response.status_code == 200
    payload = response.json()
    runtime_view = payload.pop("runtime_view")
    assert payload == {
        "ok": True,
        "schema": "atr.robot_joint_telemetry.v1",
        "type": "telemetry_state",
        "status": "idle",
        "session": {},
        "packet": None,
        "artifacts": {},
    }
    assert runtime_view["schema"] == "manipulation_runtime_view.v1"
    assert runtime_view["status"] == "not_started"
    assert runtime_view["metrics"]["task_cycle"]["success_rate"] is None


def test_grasp_outcomes_api_reports_idle_without_rollout(monkeypatch) -> None:
    import app.main as main_module

    monkeypatch.setattr(main_module, "_joint_telemetry_session_context", lambda: None)
    client = TestClient(app)

    response = client.get("/api/lerobot/grasp-outcomes")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "schema": "atr.grasp_outcomes.v1",
        "status": "idle",
        "session": {},
        "attempts": [],
        "summary": {
            "total_attempts": 0,
            "completed_attempts": 0,
            "success_count": 0,
            "failed_count": 0,
            "pending_count": 0,
            "success_rate": None,
        },
        "artifact_path": "",
        "artifact_url": "",
    }


def test_grasp_outcomes_api_exposes_current_session_artifact(tmp_path, monkeypatch) -> None:
    import app.main as main_module

    log_path = tmp_path / "rollout-grasp-api" / "motor_events.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("{}\n", encoding="utf-8")
    artifact_path = log_path.with_name("grasp_outcomes.json")
    artifact_path.write_text("{}", encoding="utf-8")
    context = {
        "session": {
            "session_id": "rollout-grasp-api",
            "workflow": "rollout",
            "status": "COMPLETED",
            "mode": "live",
        },
        "log_path": log_path,
    }
    aggregate = {
        "total_attempts": 4,
        "completed_attempts": 4,
        "success_count": 3,
        "failed_count": 1,
        "pending_count": 0,
        "success_rate": 0.75,
    }
    monkeypatch.setattr(main_module, "_joint_telemetry_session_context", lambda: context)
    monkeypatch.setattr(
        main_module,
        "finalize_grasp_outcome_artifact",
        lambda path, session: {
            "ok": True,
            "schema": "atr.grasp_outcomes.v1",
            "attempts": [{"attempt_index": 1, "status": "success"}],
            "summary": aggregate,
            "artifact_path": str(artifact_path),
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.get("/api/lerobot/grasp-outcomes")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["session"]["session_id"] == "rollout-grasp-api"
    assert payload["attempts"] == [{"attempt_index": 1, "status": "success"}]
    assert payload["summary"] == aggregate
    assert payload["artifact_path"] == str(artifact_path)
    assert payload["artifact_url"].startswith("/api/lerobot/visualization/file?path=")


def test_joint_telemetry_snapshot_reads_existing_rollout_action_log(tmp_path, monkeypatch) -> None:
    import app.main as main_module

    log_path = tmp_path / "runs" / "lerobot_action_logs" / "rollout-api-test" / "motor_events.jsonl"
    log_path.parent.mkdir(parents=True)
    event = {
        "event": "action",
        "sequence": 9,
        "session_id": "rollout-api-test",
        "timestamp": "2026-07-13T00:00:00+00:00",
        "monotonic_s": 10.0,
        "latest_observation": {
            "shoulder_pan.pos": 5.0,
            "shoulder_lift.pos": 0.0,
            "elbow_flex.pos": 0.0,
            "wrist_flex.pos": 0.0,
            "wrist_roll.pos": 0.0,
            "gripper.pos": 50.0,
        },
        "requested_action": {
            "shoulder_pan.pos": 7.0,
            "shoulder_lift.pos": 0.0,
            "elbow_flex.pos": 0.0,
            "wrist_flex.pos": 0.0,
            "wrist_roll.pos": 0.0,
            "gripper.pos": 50.0,
        },
        "sent_action": {
            "shoulder_pan.pos": 6.5,
            "shoulder_lift.pos": 0.0,
            "elbow_flex.pos": 0.0,
            "wrist_flex.pos": 0.0,
            "wrist_roll.pos": 0.0,
            "gripper.pos": 50.0,
        },
    }
    log_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    context = {
        "session": {
            "session_id": "rollout-api-test",
            "workflow": "rollout",
            "status": "POLICY_ACTIVE",
            "mode": "live",
        },
        "log_path": log_path,
    }
    monkeypatch.setattr(main_module, "_joint_telemetry_session_context", lambda: context)
    client = TestClient(app)

    response = client.get("/api/lerobot/joint-telemetry/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "live"
    assert payload["session"]["session_id"] == "rollout-api-test"
    assert payload["packet"]["sequence"] == 9
    assert payload["packet"]["actual_deg"]["Joint1"] == pytest.approx(5.0)
    assert payload["packet"]["target_deg"]["Joint1"] == pytest.approx(7.0)
    assert payload["runtime_view"]["schema"] == "manipulation_runtime_view.v1"
    assert payload["runtime_view"]["metrics"]["sample_count"] == 9


def test_joint_telemetry_context_prefers_active_rollout(tmp_path, monkeypatch) -> None:
    import app.main as main_module

    class FakeBridge:
        def __init__(self, sessions):
            self._sessions = sessions

        def sessions_recent(self):
            return list(self._sessions)

    active = {
        "session_id": "rollout-active",
        "workflow": "rollout",
        "status": "POLICY_ACTIVE",
        "mode": "live",
        "created_at": "2026-07-13T00:00:00+00:00",
    }
    newer_terminal = {
        "session_id": "rollout-complete",
        "workflow": "rollout",
        "status": "COMPLETED",
        "mode": "live",
        "created_at": "2026-07-13T01:00:00+00:00",
    }
    backend = FakeBridge([active, newer_terminal])
    registered = FakeBridge([dict(active)])
    monkeypatch.setattr(main_module, "_lerobot_bridge", lambda: backend)
    monkeypatch.setattr(main_module, "_registered_lerobot_bridge", lambda: registered)
    monkeypatch.setattr(main_module, "LEROBOT_ACTION_LOG_ROOT", tmp_path)

    context = main_module._joint_telemetry_session_context()

    assert context is not None
    assert context["session"]["session_id"] == "rollout-active"
    assert context["log_path"] == tmp_path / "rollout-active" / "motor_events.jsonl"


def test_joint_telemetry_websocket_emits_existing_history(tmp_path, monkeypatch) -> None:
    import app.main as main_module

    log_path = tmp_path / "rollout-ws-test" / "motor_events.jsonl"
    log_path.parent.mkdir(parents=True)
    event = {
        "event": "action",
        "sequence": 3,
        "session_id": "rollout-ws-test",
        "timestamp": "2026-07-13T00:00:00+00:00",
        "monotonic_s": 20.0,
        "latest_observation": {
            "shoulder_pan.pos": 1.0,
            "shoulder_lift.pos": 2.0,
            "elbow_flex.pos": 3.0,
            "wrist_flex.pos": 4.0,
            "wrist_roll.pos": 5.0,
            "gripper.pos": 50.0,
        },
        "requested_action": {
            "shoulder_pan.pos": 1.5,
            "shoulder_lift.pos": 2.5,
            "elbow_flex.pos": 3.5,
            "wrist_flex.pos": 4.5,
            "wrist_roll.pos": 5.5,
            "gripper.pos": 55.0,
        },
        "sent_action": {
            "shoulder_pan.pos": 1.25,
            "shoulder_lift.pos": 2.25,
            "elbow_flex.pos": 3.25,
            "wrist_flex.pos": 4.25,
            "wrist_roll.pos": 5.25,
            "gripper.pos": 52.5,
        },
    }
    log_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    context = {
        "session": {
            "session_id": "rollout-ws-test",
            "workflow": "rollout",
            "status": "POLICY_ACTIVE",
            "mode": "live",
        },
        "log_path": log_path,
    }
    monkeypatch.setattr(main_module, "_joint_telemetry_session_context", lambda: context)
    client = TestClient(app)

    with client.websocket_connect("/ws/lerobot/joint-telemetry") as websocket:
        payload = websocket.receive_json()

    assert payload["schema"] == "atr.robot_joint_telemetry.v1"
    assert payload["type"] == "joint_history"
    assert payload["session"]["session_id"] == "rollout-ws-test"
    assert payload["samples"][0]["sequence"] == 3
    assert payload["runtime_view"]["schema"] == "manipulation_runtime_view.v1"


def test_joint_telemetry_terminal_snapshot_finalizes_artifacts(tmp_path, monkeypatch) -> None:
    import app.main as main_module

    log_path = tmp_path / "rollout-finished" / "motor_events.jsonl"
    log_path.parent.mkdir(parents=True)
    event = {
        "event": "action",
        "sequence": 1,
        "session_id": "rollout-finished",
        "timestamp": "2026-07-13T00:00:00+00:00",
        "monotonic_s": 1.0,
        "latest_observation": {
            "shoulder_pan.pos": 1.0,
            "shoulder_lift.pos": 2.0,
            "elbow_flex.pos": 3.0,
            "wrist_flex.pos": 4.0,
            "wrist_roll.pos": 5.0,
            "gripper.pos": 50.0,
        },
        "requested_action": {
            "shoulder_pan.pos": 2.0,
            "shoulder_lift.pos": 3.0,
            "elbow_flex.pos": 4.0,
            "wrist_flex.pos": 5.0,
            "wrist_roll.pos": 6.0,
            "gripper.pos": 55.0,
        },
        "sent_action": {
            "shoulder_pan.pos": 1.5,
            "shoulder_lift.pos": 2.5,
            "elbow_flex.pos": 3.5,
            "wrist_flex.pos": 4.5,
            "wrist_roll.pos": 5.5,
            "gripper.pos": 52.5,
        },
    }
    log_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        main_module,
        "_joint_telemetry_session_context",
        lambda: {
            "session": {
                "session_id": "rollout-finished",
                "workflow": "rollout",
                "status": "COMPLETED",
                "mode": "live",
            },
            "log_path": log_path,
        },
    )
    client = TestClient(app)

    payload = client.get("/api/lerobot/joint-telemetry/snapshot").json()

    assert payload["status"] == "complete"
    assert payload["artifacts"]["ok"] is True
    assert Path(payload["artifacts"]["plot_png_path"]).is_file()
    assert payload["artifacts"]["plot_png_url"].startswith("/api/lerobot/visualization/file?path=")


def test_live_gui_contains_compact_objective_runtime_card() -> None:
    client = TestClient(app)

    html = client.get("/live").text
    script = client.get("/static/planning.js").text

    for element_id in (
        "live-objective-runtime-card",
        "live-objective-identity",
        "live-objective-hash",
        "live-objective-equation",
        "live-objective-score",
        "live-objective-feasibility",
        "live-objective-contributions",
        "live-objective-readiness",
    ):
        assert f'id="{element_id}"' in html
    assert "/api/objectives/status" in script
    assert "refreshLiveObjectiveState" in script
def test_live_gui_loads_shared_bo_visualization_before_planning_runtime() -> None:
    html = TestClient(app).get("/live").text

    assert html.index('<script src="/static/bo_visualization.js') < html.index('<script src="/static/planning.js')
