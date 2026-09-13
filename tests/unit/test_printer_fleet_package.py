"""The fleet is one package; legacy imports must share its runtime state."""
import importlib
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("legacy,canonical", [
    ("bambu_bridge", "bridge"),
    ("bambu.bridge", "bridge"),
    ("prusa_bridge", "providers.prusa"),
    ("prusa.bridge", "providers.prusa"),
    ("bambu_autoejection", "providers.bambu_autoejection"),
    ("bambu.autoejection", "providers.bambu_autoejection"),
])
def test_fleet_imports_keep_existing_callers_and_patches_on_one_runtime(legacy, canonical, monkeypatch):
    target = f"device_bridges.printer_fleet.{canonical}"
    assert importlib.util.find_spec("device_bridges.printer_fleet.bridge") is not None
    actual = importlib.import_module(target)
    old = importlib.import_module(f"device_bridges.{legacy}")
    assert old is actual
    monkeypatch.setattr(actual, "_package_probe", "same-runtime", raising=False)
    assert old._package_probe == "same-runtime"
    if hasattr(actual, "REPO_ROOT"):
        assert actual.REPO_ROOT == Path(__file__).resolve().parents[2]


def test_catalog_provider_components_and_requirements_resolve_inside_fleet():
    from device_bridges.printer_fleet.module import MODULE
    descriptor = MODULE.describe()
    root = Path(__file__).resolve().parents[2]
    assert descriptor["manager"] == "device_bridges.printer_fleet.bridge.PrinterDeviceBridgeManager"
    assert descriptor["runtime_bridge_ids"] == ["prusa_bridge"]
    assert {p["id"] for p in descriptor["providers"]} == {"bambu", "prusa"}
    for provider in descriptor["providers"]:
        assert provider["component"].startswith("device_bridges.printer_fleet.providers.")
        assert importlib.util.find_spec(provider["component"]) is not None
        assert provider["requirements"].startswith("device_bridges/printer_fleet/")
        assert (root / provider["requirements"]).is_file()
