"""Contracts for the installed Camera/Vision observation bridge package."""
import importlib
from pathlib import Path


def test_camera_vision_descriptor_groups_observation_components_and_runtime_alias():
    from device_bridges.camera_vision.module import MODULE

    descriptor = MODULE.describe()
    assert (descriptor["id"], descriptor["version"]) == ("camera_vision", "1.0.0")
    assert descriptor["runtime_bridge_ids"] == ["camera_utm_bridge"]
    assert set(descriptor["tools"]) == {
        "camera.capture", "vision.utm_runtime.start", "vision.utm_runtime.status",
        "vision.utm_runtime.stop", "vision.utm_specimen_presence.capture",
        "vision.specimen_pose_snapshot", "vision.specimen_pose.release",
        "vision.equipment_cross_check",
    }
    assert {item["id"] for item in descriptor["providers"]} == {
        "utm_runtime", "utm_state_observer", "specimen_pose_tracker", "realsense"
    }
    assert descriptor["ui"] == {
        "workspace": "/device-bridge/vision-utm",
        "api": "/api/equipment/utm-runtime",
        "assets": "web/static/vision_utm_device_bridge.js",
    }
    assert descriptor["apis"] == ["/api/equipment/utm-runtime", "/api/vision/specimen-pose"]
    assert descriptor["shared_dependencies"]["runtime_bridge_ids"] == ["lerobot_bridge"]
    assert descriptor["shared_dependencies"]["bridge_sources"] == ["device_bridges/lerobot/bridge.py"]
    assert not set(descriptor["shared_dependencies"]["tools"]) & set(descriptor["tools"])


def test_legacy_observation_imports_share_canonical_module_identity():
    aliases = {
        "device_bridges.utm_runtime_bridge": "device_bridges.camera_vision.utm_runtime_bridge",
        "device_bridges.utm_state_observer": "device_bridges.camera_vision.utm_state_observer",
        "device_bridges.specimen_pose_tracker": "device_bridges.camera_vision.specimen_pose_tracker",
        "device_bridges.realsense_bridge": "device_bridges.camera_vision.realsense_bridge",
        "mcp_tools.camera_tools": "device_bridges.camera_vision.tools",
    }
    for legacy, canonical in aliases.items():
        assert importlib.import_module(legacy) is importlib.import_module(canonical)


def test_camera_tool_registration_keeps_injected_resources():
    from device_bridges.camera_vision.tools import register_camera_tools
    from mcp_tools.tool_registry import ToolRegistry

    class Runtime:
        def status(self):
            return {"ok": True, "sentinel": "same-runtime"}

    class Pose:
        def snapshot(self, payload):
            return {"ok": True, "payload": payload, "sentinel": "same-pose"}

        def release(self, payload):
            return {"ok": True, "payload": payload}

    registry = ToolRegistry()
    register_camera_tools(registry, utm_runtime_manager=Runtime(), specimen_pose_tracker=Pose())
    assert registry.call("vision.utm_runtime.status", {})["sentinel"] == "same-runtime"
    assert registry.call("vision.specimen_pose_snapshot", {"frame": "x"}) == {
        "ok": True, "payload": {"frame": "x"}, "sentinel": "same-pose"
    }
    assert registry.call("camera.capture", {})["source"] == "simulator"


def test_installed_discovery_and_vision_package_membership():
    from agents.vision.module import MODULE as vision
    from device_bridges.module_discovery import discover_bridge_modules
    from packages.service import installed_agent_packages

    bridges = {module.module_id: module.describe() for module in discover_bridge_modules()}
    packages = installed_agent_packages([vision.describe()])
    assert packages[0]["bridge_modules"] == [
        {"id": "camera_vision", "version": "1.0.0"},
        {"id": "lerobot", "version": "1.0.0"},
    ]
    assert bridges["camera_vision"]["root"] == "device_bridges/camera_vision"


def test_camera_vision_default_utm_checkout_uses_current_home():
    from device_bridges.camera_vision.utm_runtime_bridge import DEFAULT_UTM_REPO
    from device_bridges.camera_vision.specimen_pose_tracker import SpecimenPoseTrackerConfig

    assert DEFAULT_UTM_REPO == Path.home() / "external_repos" / "UTM"
    expected_rsusb = str(Path.home() / "librealsense-rsusb" / "build-rsusb-system" / "Release")
    assert SpecimenPoseTrackerConfig().rsusb_pythonpath == expected_rsusb
    assert SpecimenPoseTrackerConfig().rsusb_library_path == expected_rsusb
