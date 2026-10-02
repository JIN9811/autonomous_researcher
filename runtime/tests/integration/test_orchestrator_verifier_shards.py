"""Pure verifier partition/aggregation tests; never construct providers."""
from copy import deepcopy
import hashlib
import json

import pytest

from scripts import verify_orchestrator_setup as verifier


def digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def test_partition_expanded_contexts_and_decisions_exactly_once():
    full = verifier.case_selection()
    ids = full["expected_case_ids"]
    assert len(ids) == len(set(ids)) == 78
    assert ids[-6:] == ["ready", "busy", "unknown_stale", "supported_proposal", "unsupported_setup", "completed_defer_resume"]
    assert [name for name in ids if name.startswith("I09-")] == ["I09-N", "I09-P", "I09-B", "I09-I", "I09-R", "I09-V", "I09-S", "I09-M", "I09-specimen"]
    assert full["selected_case_ids"] == ids
    first = verifier.case_selection(0, 2)
    second = verifier.case_selection(1, 2)
    assert first["selected_case_ids"] == ids[::2]
    assert second["selected_case_ids"] == ids[1::2]
    assert len(first["selected_case_ids"]) == len(second["selected_case_ids"]) == 39
    assert full["expected_case_ids_sha256"] == digest(ids)
    assert first["selected_case_ids_sha256"] == digest(ids[::2])


@pytest.mark.parametrize("index,count", [(0, 0), (0, 3), (-1, 2), (2, 2), (False, 1), (0, 1.0)])
def test_invalid_shards_rejected_before_any_provider(index, count):
    with pytest.raises(ValueError):
        verifier.case_selection(index, count)


def report(backend="vllm", index=0, count=2):
    selection = verifier.case_selection(index, count)
    intake_cases = {case["id"]: case for case in verifier.fixtures()}
    rows = []
    for name in selection["selected_case_ids"]:
        row = {"backend": backend, "case": name, "status": "passed", "physical_call_count": 0,
            "served_model": "served-test", "requested_models": ["served-test"], "served_models": ["served-test"],
            "raw_attempts": [{"requested_model": "served-test", "served_model": "served-test", "text": "{}"}]}
        intake = intake_cases.get(name.split("-", 1)[0])
        if intake is not None:
            row.update(classification={"intent": intake["allowed_intents"][0]}, allowed_intents=intake["allowed_intents"],
                effect={"expectation_met": True, "execution_status": "completed"})
        else:
            row.update(expectation_met=True, decision={"status": "prepared"})
        rows.append(row)
    return {"schema": "verification_report.v1", "run_status": "complete", "selection": selection,
        "fixture_sha256": "fixture-epoch", "code_sha256": "verifier-epoch", "prompt_sha256": "prompt-epoch",
        "source_sha256": {"app/controller.py": "source-epoch"}, "physical_call_count": 0,
        "denied_attempts": [], "cases": rows}


def test_aggregate_requires_complete_unique_coverage_for_each_provider():
    result = verifier.aggregate_reports([report("openai", 0, 1), report(), report(index=1)])
    assert result["status"] == "passed"
    assert result["providers"]["openai"]["case_count"] == 78
    assert result["providers"]["vllm"]["case_count"] == 78


@pytest.mark.parametrize("mutation", [None, "invalid_intent", "invalid_effect", "unknown_holdout"])
def test_holdout_intake_rows_use_intake_contract_not_decision_fields(mutation):
    captured = report("openai", 0, 1)
    holdouts = [row for row in captured["cases"] if row["case"].startswith("H")]
    assert [row["case"] for row in holdouts] == [f"H{number:02d}" for number in range(1, 13)]
    assert all("decision" not in row and "expectation_met" not in row for row in holdouts)
    row = holdouts[0]
    if mutation == "invalid_intent":
        row["classification"]["intent"] = "invalid_intent"
    elif mutation == "invalid_effect":
        row["effect"]["expectation_met"] = False
    elif mutation == "unknown_holdout":
        row["case"] = "H99"
    assert row["status"] == "passed"  # The consumer must verify the underlying contract.
    result = verifier.aggregate_reports([captured])
    if mutation is None:
        assert result["status"] == "passed", result["errors"]
        assert result["errors"] == []
    else:
        assert result["status"] == "failed"
        assert result["errors"]
        assert not any("H02" in error for error in result["errors"]), "Valid neighboring holdouts remain valid"


@pytest.mark.parametrize("mutation", ["missing_shard", "missing_case", "duplicate_case", "duplicate_shard", "unknown_case",
    "incomplete", "prompt_epoch", "source_epoch", "fixture_epoch", "failed", "blocked", "denied", "physical", "identity", "invalid_effect", "selection"])
def test_aggregate_never_promotes_incomplete_or_failed_evidence(mutation):
    reports = [report(), report(index=1)]
    changed = reports[1]
    if mutation == "missing_shard":
        reports.pop()
    elif mutation == "missing_case":
        changed["cases"].pop()
    elif mutation == "duplicate_case":
        changed["cases"].append(deepcopy(changed["cases"][0]))
    elif mutation == "duplicate_shard":
        reports.append(deepcopy(changed))
    elif mutation == "unknown_case":
        changed["cases"][0]["case"] = "unknown"
    elif mutation == "incomplete":
        changed["run_status"] = "running"
    elif mutation in {"prompt_epoch", "fixture_epoch"}:
        changed[mutation.replace("_epoch", "_sha256")] = "other-epoch"
    elif mutation == "source_epoch":
        changed["source_sha256"]["app/controller.py"] = "other-epoch"
    elif mutation in {"failed", "blocked"}:
        changed["cases"][0]["status"] = mutation
    elif mutation == "denied":
        changed["denied_attempts"] = [["unexpected boundary"]]
    elif mutation == "physical":
        changed["cases"][0]["physical_call_count"] = 1
    elif mutation == "identity":
        changed["cases"][0]["served_model"] = None
    elif mutation == "invalid_effect":
        changed["cases"][0]["effect"]["execution_status"] = "failed"
    else:
        changed["selection"]["selected_case_ids"].reverse()
    result = verifier.aggregate_reports(reports)
    assert result["status"] != "passed"
    assert result["errors"]


def test_no_execute_shard_listing_never_calls_verify(monkeypatch, capsys):
    async def forbidden(*args, **kwargs):
        pytest.fail("Listing a shard constructed a provider")
    monkeypatch.setattr(verifier, "verify", forbidden)
    monkeypatch.setattr("sys.argv", ["verify_orchestrator_setup.py", "--shard-count", "2", "--shard-index", "1"])
    assert verifier.main() == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["execution"] is False
    assert len(listing["selection"]["selected_case_ids"]) == 39


@pytest.mark.asyncio
async def test_verifier_owns_and_records_nonactuating_background_lifecycle(tmp_path):
    from types import SimpleNamespace
    from scripts.orchestrator_verification_guard import VerificationGuard
    with VerificationGuard() as guard:
        simulated = []
        controller = verifier.controller_for(SimpleNamespace(active_backend="vllm"), tmp_path,
            lifecycle_requests=simulated)
        controller._schedule_post_run_vllm_transition()
        await verifier.settle_verification_controller(controller)
        assert len(simulated) == 1
        assert simulated[0]["boundary"] == "model_lifecycle.scale_down_idle_models"
        assert simulated[0]["run_id"] == controller._state.run_id
        assert simulated[0]["actual_effect"] is False
        assert controller._vllm_transition_task is None
        assert guard.denied == []
        assert guard.physical_call_count == 0
