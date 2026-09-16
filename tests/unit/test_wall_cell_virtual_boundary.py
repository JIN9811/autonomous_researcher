"""A resolved all-virtual profile never authorizes physical clearance."""
from copy import deepcopy

import pytest

from orchestrator.state import Mode, OrchestratorState
from utils.test_mode_execution_profiles import TestModeExecutionProfileStore as ProfileStore
from utils.utm_clear_cycle import _explicit_virtual, _physical_execution


@pytest.mark.parametrize("real_agent", [None, "specimen", "vision", "manipulation", "lab_equipment"])
def test_clearance_only_simulates_a_fully_virtual_profile(tmp_path, real_agent):
    profile = ProfileStore(tmp_path / "profiles.json").resolve("virtual_bridge")
    state = OrchestratorState(run_id="virtual-boundary", experiment_id="test", mode=Mode.TEST)
    state.current_experiment_spec = {
        "test_mode_profile": deepcopy(profile),
        "printer_test_path": "virtual_bridge", "test_printer_transport": "virtual",
    }
    if real_agent:
        state.current_experiment_spec["test_mode_profile"]["agents"][real_agent]["device_mode"] = "real"
    assert _explicit_virtual(state) is (real_agent is None)
    if real_agent is None:
        assert _physical_execution(state) is False
