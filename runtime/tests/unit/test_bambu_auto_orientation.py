"""Local orientation defaults on, precedes placement, and never edits the STL."""
import shutil
from pathlib import Path
from types import SimpleNamespace

from device_bridges.bambu_bridge import BambuSlicerConfig, BambuStudioSlicerRunner


def test_orientation_precedes_slice_and_preserves_input(tmp_path, monkeypatch):
    source = tmp_path / "source.stl"
    source.write_text("original mesh")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        out = Path(command[command.index("--outputdir") + 1])
        if "--orient" in command:
            shutil.copyfile(source, out / "oriented.stl")
        else:
            (out / "model.gcode.3mf").write_bytes(b"slice fixture")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("device_bridges.printer_fleet.bridge.subprocess.run", run)
    runner = BambuStudioSlicerRunner(BambuSlicerConfig(enabled=True,
        executable_path="/bin/true", output_dir=str(tmp_path / "out"),
        auto_no_skirt_profile=False), repo_root=tmp_path)
    result = runner.slice(source)
    assert result["ok"]
    assert len(calls) == 2
    assert "--orient" in calls[0] and "--slice" in calls[1]
    assert calls[1][-1] == result["orientation"]["oriented_source_path"]
    assert result["source_path"] == str(source)
    assert source.read_text() == "original mesh"


def test_orientation_failure_does_not_slice(tmp_path, monkeypatch):
    source = tmp_path / "source.stl"
    source.write_text("original mesh")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stdout="", stderr="orientation failed")

    monkeypatch.setattr("device_bridges.printer_fleet.bridge.subprocess.run", run)
    runner = BambuStudioSlicerRunner(BambuSlicerConfig(enabled=True,
        executable_path="/bin/true", output_dir=str(tmp_path / "out"),
        auto_no_skirt_profile=False), repo_root=tmp_path)
    result = runner.slice(source, auto_orient=True)
    assert result["failure_code"] == "BAMBU_AUTO_ORIENT_FAILED"
    assert len(calls) == 1
