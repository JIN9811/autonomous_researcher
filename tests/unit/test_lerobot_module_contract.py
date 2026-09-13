"""Consumer contracts for the installed LeRobot bridge and its agent packages."""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


def test_discovery_exposes_one_inactive_lerobot_bridge_package():
    from device_bridges.module_discovery import discover_bridge_modules

    modules = {module.module_id: module.describe() for module in discover_bridge_modules()}
    assert "lerobot" in modules
    descriptor = modules["lerobot"]
    assert descriptor["version"] == "1.0.0"
    assert descriptor["runtime_bridge_ids"] == ["lerobot_bridge"]
    assert descriptor["root"] == "device_bridges/lerobot"
    assert descriptor["registration"] == "device_bridges.lerobot.tools.register_lerobot_tools"
    assert descriptor["ui"] == {
        "workspace": "/lerobot",
        "api": "/api/lerobot/config",
        "assets": "web/static/lerobot.js",
    }
    assert {"rollout", "replay", "teleoperation", "recording", "active_robot_cam"} <= {
        component["id"] for component in descriptor["providers"]
    }
    assert {"lerobot.rollout.start", "lerobot.replay.stop", "lerobot.active_robot_cam.capture"} <= set(
        descriptor["tools"]
    )
    root = Path(__file__).resolve().parents[2]
    for key in ("requirements", "documentation", "configuration"):
        assert (root / descriptor[key]).is_file()
    assert importlib.util.find_spec("device_bridges.lerobot.bridge") is not None
    assert importlib.util.find_spec("device_bridges.lerobot.tools") is not None


def test_legacy_bridge_and_tool_imports_are_exact_canonical_module_aliases(monkeypatch):
    assert importlib.util.find_spec("device_bridges.lerobot") is not None
    canonical_bridge = importlib.import_module("device_bridges.lerobot.bridge")
    legacy_bridge = importlib.import_module("device_bridges.lerobot_bridge")
    canonical_tools = importlib.import_module("device_bridges.lerobot.tools")
    legacy_tools = importlib.import_module("mcp_tools.lerobot_tools")

    assert legacy_bridge is canonical_bridge
    assert legacy_tools is canonical_tools
    monkeypatch.setattr(canonical_bridge, "_package_probe", "shared-bridge-runtime", raising=False)
    monkeypatch.setattr(canonical_tools, "_package_probe", "shared-tool-runtime", raising=False)
    assert legacy_bridge._package_probe == "shared-bridge-runtime"
    assert legacy_tools._package_probe == "shared-tool-runtime"


def test_relocated_bridge_resolves_repository_runner_scripts_without_launch(tmp_path, monkeypatch):
    assert importlib.util.find_spec("device_bridges.lerobot") is not None
    from device_bridges.lerobot.bridge import LeRobotBridge, LeRobotBridgeConfig
    from mcp_tools.lerobot_schemas import LeRobotSessionRequest

    repo_root = Path(__file__).resolve().parents[2]
    config = LeRobotBridgeConfig.from_config(
        {
            "default_profile_id": "fake_omx_ai",
            "session_log_root": str(tmp_path / "sessions"),
            "profiles": {
                "fake_omx_ai": {
                    "profile_id": "fake_omx_ai",
                    "display_name": "Fake OMX",
                    "robot_family": "robotis_omx",
                    "robot_type": "omx_follower",
                    "teleop_type": "omx_leader",
                    "robot_port": "/dev/ttyUSB_FAKE_FOLLOWER",
                    "teleop_port": "/dev/ttyUSB_FAKE_LEADER",
                    "robot_id": "omx_follower_arm",
                    "teleop_id": "omx_leader_arm",
                    "command_templates": {"replay": ["unused"]},
                }
            },
        },
        repo_root=repo_root,
    )
    bridge = LeRobotBridge(config)
    profile = bridge._profile("fake_omx_ai")  # noqa: SLF001
    request = LeRobotSessionRequest.model_validate({"mode": "test", "profile_id": "fake_omx_ai"})
    replay_command = bridge._workflow_command(profile, "replay", request, [])  # noqa: SLF001
    assert Path(replay_command[6]) == repo_root / "scripts" / "lerobot_managed_replay.py"

    launched = []

    class Process:
        pid = 4242

        @staticmethod
        def poll():
            return None

    def fake_popen(command, **kwargs):
        launched.append((command, kwargs))
        return Process()

    monkeypatch.setattr("device_bridges.lerobot.bridge.subprocess.Popen", fake_popen)
    monkeypatch.setattr("device_bridges.lerobot.bridge.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(bridge, "_process_start_ticks", lambda _pid: 1)
    started = bridge._start_live_process(session_id="runner-path", command=["train"], background=True)  # noqa: SLF001
    assert started["ok"]
    assert Path(launched[0][0][1]) == repo_root / "scripts" / "lerobot_background_train_runner.py"


def test_manipulation_and_vision_share_one_lerobot_dependency_during_detached_roundtrip(monkeypatch):
    assert importlib.util.find_spec("device_bridges.lerobot") is not None
    from agents.manipulation.module import MODULE as manipulation
    from agents.vision.module import MODULE as vision
    from device_bridges.lerobot.bridge import LeRobotBridge
    from device_bridges.module_discovery import discover_bridge_modules
    from packages.service import PackageService, installed_agent_packages

    monkeypatch.setattr(
        LeRobotBridge,
        "__init__",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("package inspection activated LeRobot")),
    )
    installed = installed_agent_packages([manipulation.describe(), vision.describe()])
    bridges = [module.describe() for module in discover_bridge_modules()]
    service = PackageService(
        agent_packages=installed,
        bridge_modules=bridges,
        installed_handlers=["agent.manipulation_agent", "agent.vision_agent"],
        installed_module_ids=["manipulation", "vision"],
        validate_graph=lambda _raw: [],
        validate_module=lambda _ident, _raw: [],
    )

    catalog = service.catalog()
    assert catalog["ok"], catalog
    packages = {item["id"]: item for item in catalog["agent_packages"]}
    assert packages["manipulation"]["bridge_modules"] == [{"id": "lerobot", "version": "1.0.0"}]
    assert packages["vision"]["bridge_modules"] == [
        {"id": "camera_vision", "version": "1.0.0"},
        {"id": "lerobot", "version": "1.0.0"},
    ]
    bridge = next(item for item in catalog["bridge_modules"] if item["id"] == "lerobot")
    assert bridge["package_owners"] == [
        {"id": "vision", "version": "1.0.0"},
        {"id": "manipulation", "version": "1.0.0"},
    ]

    draft = {
        "schema": "ax4lab.experimental_package.v1",
        "id": "shared_robot_observation",
        "version": "1.0.0",
        "graph": {
            "id": "shared_robot_observation",
            "name": "Shared robot observation",
            "version": "1.0.0",
            "entry_node": "manipulation",
            "finish_nodes": ["vision"],
            "nodes": [
                {"id": "manipulation", "label": "Manipulation", "handler": "agent.manipulation_agent", "module_id": "manipulation", "stage": "manipulation"},
                {"id": "vision", "label": "Vision", "handler": "agent.vision_agent", "module_id": "vision", "stage": "vision"},
            ],
            "edges": [{"source": "manipulation", "target": "vision"}],
        },
        "agent_packages": [
            {"id": "manipulation", "version": "1.0.0"},
            {"id": "vision", "version": "1.0.0"},
        ],
        "module_configurations": {},
        "bindings": [],
    }
    exported = service.export_experimental(draft)
    assert exported["ok"], exported
    assert exported["package"]["bridge_modules"] == [
        {"id": "camera_vision", "version": "1.0.0"},
        {"id": "lerobot", "version": "1.0.0"},
    ]
    imported = service.import_experimental(exported["package"])
    assert imported["ok"], imported
    assert imported["draft"] == exported["package"]
    assert not imported["activated"] and not imported["persisted"]


def test_agent_and_camera_metadata_point_to_the_canonical_shared_bridge():
    from agents.manipulation.module import MODULE as manipulation
    from agents.manipulation.structure import manipulation_implementation_structure
    from agents.vision.module import MODULE as vision
    from agents.vision.structure import vision_implementation_structure
    from device_bridges.camera_vision.module import MODULE as camera_vision

    canonical = "device_bridges/lerobot/bridge.py"
    assert manipulation.describe()["dependencies"]["shared_bridge_sources"] == [canonical]
    assert vision.describe()["dependencies"]["shared_bridge_sources"] == [canonical]
    assert camera_vision.describe()["shared_dependencies"]["bridge_sources"] == [canonical]
    manipulation_sources = {
        item["source"]["path"]
        for operation in manipulation_implementation_structure()["operations"].values()
        for item in operation["nodes"]
    }
    vision_sources = {
        item["source"]["path"]
        for operation in vision_implementation_structure()["operations"].values()
        for item in operation["nodes"]
    }
    assert canonical in manipulation_sources
    assert canonical in vision_sources
