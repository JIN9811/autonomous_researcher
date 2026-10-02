"""Historical evidence loader must retain source identities and bytes."""
import hashlib
from pathlib import Path


def test_probe_cases_keep_original_evidence_and_label_perturbations():
    from scripts.verify_manipulation_decisions import load_cases
    root = Path("runs/run-20260906T122533Z-c0effd/runtime/loops/loop-000001")
    if not root.exists():
        import pytest
        pytest.skip("local historical artifact is not tracked")
    path = root / "vision_agent/attempt-000012/result.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    cases = load_cases(root)
    assert len(cases) == 4
    assert cases[2]["capture"]["detected"] is True
    assert cases[3]["capture"]["detected"] is False
    assert cases[3]["synthetic_perturbation"] is True
    assert cases[2]["capture"]["timestamp"] == "2026-09-06T12:41:58.013892+00:00"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
