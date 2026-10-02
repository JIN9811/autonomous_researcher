"""Portable Isaac defaults; only build commands and resolve paths, never launch."""
from pathlib import Path
from types import SimpleNamespace
import sys

from device_bridges.lerobot_bridge import LeRobotBridge
from mcp_tools.lerobot_schemas import IsaacLabSyntheticRequest


def test_isaac_command_defaults_follow_home_and_keep_explicit_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    bridge = object.__new__(LeRobotBridge)
    bridge.config = SimpleNamespace(repo_root=tmp_path, conda_env_name="test-env")
    request = IsaacLabSyntheticRequest(dataset_path=str(tmp_path / "dataset"))
    command = bridge._isaac_lab_live_e2e_command(request)
    assert command[command.index("--isaac-lab-path") + 1] == str(tmp_path / "IsaacLab")
    assert command[command.index("--isaac-sim-python") + 1] == str(tmp_path / "IsaacSim/python.sh")
    explicit = request.model_copy(update={"isaac_lab_path": "/opt/lab", "isaac_sim_python": "/opt/sim/python.sh"})
    command = bridge._isaac_lab_live_e2e_command(explicit)
    assert command[command.index("--isaac-lab-path") + 1] == "/opt/lab"
    assert command[command.index("--isaac-sim-python") + 1] == "/opt/sim/python.sh"


def test_isaac_receiver_paths_keep_override_home_and_missing_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for resolve, key, env, filename, fallback in (
        (LeRobotBridge._isaac_mirror_receiver_isaac_sim_executable,
         "isaac_mirror_receiver_isaac_sim_executable", "ATR_ISAAC_SIM_EXECUTABLE", "isaac-sim.sh", "isaac-sim.sh"),
        (LeRobotBridge._isaac_mirror_receiver_python,
         "isaac_mirror_receiver_python", "ATR_ISAAC_MIRROR_RECEIVER_PYTHON", "python.sh", sys.executable),
    ):
        monkeypatch.delenv(env, raising=False)
        assert resolve({}) == fallback
        executable = tmp_path / "IsaacSim" / filename
        executable.parent.mkdir(exist_ok=True)
        executable.touch()
        assert resolve({}) == str(executable)
        monkeypatch.setenv(env, "/opt/environment-command")
        assert resolve({}) == "/opt/environment-command"
        assert resolve({key: "/opt/explicit-command"}) == "/opt/explicit-command"
