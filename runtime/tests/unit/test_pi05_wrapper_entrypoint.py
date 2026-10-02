"""Resolve the RTC entrypoint without importing drivers or starting a robot."""
import runpy
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.mark.parametrize("override", [None, "/tmp/atr-fixture/custom_rtc.py"])
def test_pi05_wrapper_resolves_user_home_and_explicit_entrypoint(monkeypatch, tmp_path, override):
    calls = []
    for module_name, installer in (
        ("scripts.lerobot_live_depth_observation_patch", "install_live_depth_observation_patch"),
        ("scripts.lerobot_omx_runtime_units_patch", "install_omx_follower_runtime_units_patch"),
        ("scripts.lerobot_linear_interpolation", "install_linear_if_enabled"),
        ("scripts.lerobot_rtc_queue_alignment", "install_rtc_queue_alignment"),
    ):
        module = ModuleType(module_name)
        setattr(module, installer, lambda: None)
        monkeypatch.setitem(sys.modules, module_name, module)
    robots = ModuleType("lerobot.robots")
    robots.omx_follower = ModuleType("omx_follower")
    monkeypatch.setitem(sys.modules, "lerobot.robots", robots)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("ATR_PI05_ACTION_LOG_INTERVAL", "0")
    monkeypatch.delenv("ATR_PI05_RTC_SCRIPT", raising=False)
    if override is not None:
        monkeypatch.setenv("ATR_PI05_RTC_SCRIPT", override)
    execute = runpy.run_path
    monkeypatch.setattr(runpy, "run_path", lambda path, **kwargs: calls.append((path, kwargs)))

    execute("scripts/lerobot_pi05_rollout_wrapper.py", run_name="__main__")

    expected = override or str(tmp_path / "lerobot_pi05/examples/rtc/eval_with_real_robot.py")
    assert calls == [(expected, {"run_name": "__main__"})]
