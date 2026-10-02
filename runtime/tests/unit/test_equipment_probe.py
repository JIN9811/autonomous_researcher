"""Offline probe construction and opt-in guards, never external model calls."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PIL import Image


@pytest.fixture
def screen(tmp_path):
    path = tmp_path / "historical-screen.png"
    Image.new("RGB", (32, 24), "white").save(path)
    block_ids = ["prepare_next_specimen", "start_test", "monitor_contact_and_run", "await_auto_return",
                 "save_raw_data", "validate_raw_data", "advance_without_save", "restore_robot_clearance"]
    archive = {"status": "completed", "summary": "Equipment Skill Flow completed", "data": {
        "equipment_skill_flow_execution": {"flow_id": "utm_windows_v1", "status": "completed",
            "run_id": "historical-run", "flow_execution_id": "historical-flow",
            "transitions": [{"block_id": key, "phase": "skill", "outcome": "completed", "success": True,
                             "summary": "Actual archived step log"} for key in block_ids]},
        "raw_data_export": {"validated": True, "parse_ok": True, "stable": True,
            "same_artifact": True, "identity_ok": True, "row_count": 123, "specimen_id": "historical-specimen"},
        "verified": True, "required_entry_gate": {"ok": True},
        "utm_data_ready": {"status": "ready"},
        "next_specimen_readiness": {"ready": True, "clearance_restored": True},
        "handoff_eligibility": {"eligible": True, "missing_requirements": []},
        "equipment_report": {"status": "verified_complete", "blocking_reasons": []},
        "tool_results": [{"kind": "screen_png", "artifact_id": "historical-screen",
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}}
    (tmp_path / "result.json").write_text(json.dumps(archive))
    return path


def test_cases_preserve_source_bytes_and_clearly_label_synthetic_claims(screen):
    from scripts.verify_equipment_decisions import build_cases
    original = screen.read_bytes()
    cases, hashes = build_cases(screen)
    assert len(cases) == 8
    assert hashes[str(screen.resolve())] == hashlib.sha256(original).hexdigest()
    assert screen.read_bytes() == original
    selection = cases[0]
    assert selection["phase"] == "select" and selection["expected_tool"] == "execute_stacked_workflow"
    assert selection["context"]["flow"]["flow_id"] == "utm_windows_v1"
    assert selection["images"] == []
    for case in cases[2:]:
        assert case["synthetic_perturbation"] is True
        assert case["context"]["evidence_origin"]["execution"] == "synthetic_offline_fixture"
        assert case["images"][0].data == original
        assert case["context"]["screen"]["historical_only"] is True
    assert len(hashes) == 3  # screen, archived result, registered Flow source


def test_synthetic_success_is_not_scored_as_historical_success(screen):
    from scripts.verify_equipment_decisions import build_cases
    cases, _ = build_cases(screen)
    success = next(case for case in cases if case["case"] == "synthetic_success_terminal")
    assert success["expected_tool"] is None
    assert success["context"]["success"] is True
    assert success["context"]["execution"]["csv"]["valid"] is True
    assert success["context"]["execution"]["completed_blocks"]
    assert set(success["proposals"]) == {"accept_workflow_result", "request_operator"}


def test_recovery_cases_are_separate_and_never_offer_retry_after_uncertain_effects(screen):
    from scripts.verify_equipment_decisions import build_cases
    cases, _ = build_cases(screen)
    by_name = {case["case"]: case for case in cases}
    wait = by_name["zero_action_ui_error"]
    assert wait["expected_tool"] == "recover_wait"
    assert wait["context"]["execution"]["no_action_proven"] is True
    assert "resume_failed_block" not in wait["proposals"]
    resume = by_name["post_recovery_resume"]
    assert resume["phase"] == "recovery_review"
    assert resume["context"]["diagnostics"]["post_recovery_observation"] is True
    assert resume["context"]["execution"]["failed_block_completed_segments"] == []
    assert resume["expected_tool"] == "resume_failed_block"
    for name in ("partial_action_failure", "unknown_effect_failure"):
        assert set(by_name[name]["proposals"]) == {"request_operator"}
        assert by_name[name]["expected_tool"] == "request_operator"
    contradiction = by_name["contradictory_terminal"]
    assert contradiction["context"]["success"] is True
    assert contradiction["context"]["execution"]["csv"]["valid"] is False
    assert contradiction["expected_tool"] == "request_operator"


def test_case_mutation_does_not_change_another_case(screen):
    from scripts.verify_equipment_decisions import build_cases
    cases, _ = build_cases(screen)
    cases[1]["context"]["flow"]["blocks"].clear()
    cases[1]["proposals"]["request_operator"]["proposal_id"] = "different"
    assert cases[0]["context"]["flow"]["blocks"]
    assert cases[2]["context"]["flow"]["blocks"]
    assert cases[2]["proposals"]["request_operator"]["proposal_id"] != "different"


def test_historical_terminal_preserves_real_result_logs_gates_and_image_binding(screen):
    from scripts.verify_equipment_decisions import build_cases
    result_path = screen.parent / "result.json"
    before = result_path.read_bytes()
    cases, hashes = build_cases(screen)
    history = cases[1]
    assert history["case"] == "historical_terminal"
    assert history["synthetic_perturbation"] is False
    assert history["expected_tool"] == "accept_workflow_result"
    assert history["context"]["execution"]["raw_data_export"]["row_count"] == 123
    assert history["context"]["execution"]["equipment_skill_flow_execution"]["transitions"][0]["summary"] == "Actual archived step log"
    assert history["context"]["evidence_origin"]["execution"] == "archived_equipment_result"
    assert history["context"]["screen"]["same_invocation_verified"] is True
    assert history["identity"] == {"run_id": "historical-run", "specimen_id": "historical-specimen"}
    assert hashes[str(result_path.resolve())] == hashlib.sha256(before).hexdigest()
    assert result_path.read_bytes() == before


def test_historical_context_reuses_production_secret_and_raster_filter(screen):
    from scripts.verify_equipment_decisions import build_cases
    result_path = screen.parent / "result.json"
    result = json.loads(result_path.read_text())
    result["data"]["equipment_result"] = {"token": "private-token", "api_key": "private-key",
                                         "frame_base64": "private-raster", "status": "recorded"}
    result_path.write_text(json.dumps(result))
    cases, _ = build_cases(screen)
    evidence = cases[1]["context"]["execution"]
    assert evidence["equipment_result"] == {"status": "recorded"}
    assert "private-" not in json.dumps(cases[1]["context"])


@pytest.mark.parametrize("change", ["csv", "readiness", "entry", "image", "missing", "step_failure"])
def test_historical_acceptance_is_conditional_on_actual_archived_gates(screen, change):
    from scripts.verify_equipment_decisions import build_cases
    result_path = screen.parent / "result.json"
    result = json.loads(result_path.read_text())
    if change == "csv": result["data"]["raw_data_export"]["validated"] = False
    if change == "readiness": result["data"]["next_specimen_readiness"]["ready"] = False
    if change == "entry": result["data"]["required_entry_gate"]["ok"] = False
    if change == "image": result["data"]["tool_results"][0]["sha256"] = "unrelated"
    if change == "missing": del result["data"]["handoff_eligibility"]
    if change == "step_failure": result["data"]["equipment_skill_flow_execution"]["transitions"][0]["success"] = False
    result_path.write_text(json.dumps(result))
    cases, _ = build_cases(screen)
    history = cases[1]
    assert history["expected_tool"] == "request_operator"
    assert set(history["proposals"]) == {"request_operator"}


def test_result_must_be_explicit_or_adjacent_to_the_selected_image(tmp_path):
    from scripts.verify_equipment_decisions import build_cases
    path = tmp_path / "image.png"
    Image.new("RGB", (4, 4)).save(path)
    with pytest.raises(ValueError, match="result"):
        build_cases(path)


def test_invalid_image_is_rejected_without_model_setup(tmp_path):
    from scripts.verify_equipment_decisions import build_cases
    path = tmp_path / "not-an-image.png"
    path.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="image"):
        build_cases(path)


@pytest.mark.asyncio
async def test_main_without_explicit_execute_returns_before_loading_config_or_credentials():
    from scripts.verify_equipment_decisions import main
    with pytest.raises(ValueError, match="execute"):
        await main(SimpleNamespace(execute=False))


def test_cli_without_execute_cannot_call_models(screen):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "scripts/verify_equipment_decisions.py"),
                             "--image", str(screen)], cwd=root, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "--execute" in result.stderr
    assert "started" not in result.stdout


def test_cli_requires_explicit_image_even_with_execute():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "scripts/verify_equipment_decisions.py"),
                             "--execute"], cwd=root, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "--image" in result.stderr


@pytest.mark.parametrize("timeout", ["0", "-1", "601", "nan", "inf"])
def test_cli_rejects_invalid_deadline_before_models(screen, timeout):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "scripts/verify_equipment_decisions.py"),
        "--execute", "--image", str(screen), "--timeout-s", timeout], cwd=root,
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "timeout" in result.stderr


def test_report_evaluation_requires_real_accepted_protocol_not_just_matching_tool():
    from scripts.verify_equipment_decisions import evaluate_decision
    case = {"expected_tool": "execute_stacked_workflow"}
    assert evaluate_decision(case, {"status": "accepted", "scope_valid": True,
        "llm_used": True, "request": {"tool": "execute_stacked_workflow"}}) is True
    assert evaluate_decision(case, {"status": "review_required", "scope_valid": False,
        "llm_used": True, "request": {"tool": "execute_stacked_workflow"}}) is False
    assert evaluate_decision(case, {"status": "deterministic_test", "scope_valid": True,
        "llm_used": False, "request": {"tool": "execute_stacked_workflow"}}) is False
    assert evaluate_decision({"expected_tool": None}, {}) is None
