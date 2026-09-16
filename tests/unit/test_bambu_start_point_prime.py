import pytest
import hashlib
import zipfile

from device_bridges.printer_fleet.bridge import BambuStudioSlicerRunner, BambuSlicerConfig


SOURCE = """;===== nozzle load line =====
M1002 gcode_claim_action : 51
G29.2 S1
G90
M83
M400 P50
M500 D1
M400 S3
M109 S220
G0 X100 Y0 F24000
M400
G130 O0 X100 Y-0.2 Z0.6 F4.36536 L40 E12 D4
G90
M83
G1 Z1
M400
;===== noozle load line end =====
; MACHINE_START_GCODE_END
G90
G21
M83
; CHANGE_LAYER
G1 E-.4 F1800
; OBJECT_ID: 25
G1 X172.75 Y69.2 F60000
G1 Z.4
G1 Z.2
G1 E.4 F1800
; FEATURE: Outer wall
G1 F600
M204 S500
G1 X172.555 Y69.383 E.00994
G1 X172.015 Y69.772 E.02481
"""


def test_start_point_prime_preserves_preparation_and_adds_only_once():
    patched, count = BambuStudioSlicerRunner._remove_front_test_line_from_gcode(SOURCE)
    assert count == 1
    for command in ("G29.2 S1", "M109 S220", "M500 D1", "M400 S3"):
        assert command in patched
    assert not any(line.strip().startswith("G130 ") for line in patched.splitlines())
    assert "G0 X100 Y0" not in patched
    assert "G1 Z1\n" not in patched
    assert "G1 E.4 F1800" in patched
    expected = "G1 E0.1 F60\nG1 F600\nG1 X172.555 Y69.383 E.00994"
    assert expected in patched
    assert patched.count("G1 E0.1 F60") == 1
    assert patched.index("G1 Z.2") < patched.index("G1 E0.1 F60")
    assert BambuStudioSlicerRunner._remove_front_test_line_from_gcode(patched) == (patched, 0)


def test_start_point_prime_can_be_disabled():
    patched, _ = BambuStudioSlicerRunner._remove_front_test_line_from_gcode(SOURCE, start_point_prime_mm=0)
    assert not any(line.strip().startswith("G130 ") for line in patched.splitlines())
    assert "G1 E0.1" not in patched
    assert "M109 S220" in patched


@pytest.mark.parametrize("source", [SOURCE.replace("M83", "M82"), SOURCE.replace("G1 Z.2", "G1 Z2"), SOURCE.replace("; OBJECT_ID: 25", ""), SOURCE.replace("G21", "G20")])
def test_start_point_prime_rejects_unsupported_context(source):
    with pytest.raises(ValueError, match="start-point prime"):
        BambuStudioSlicerRunner._remove_front_test_line_from_gcode(source)


def test_archive_prime_updates_checksum_and_uses_config(tmp_path):
    path = tmp_path / "trial.gcode.3mf"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", SOURCE)
        archive.writestr("Metadata/plate_1.gcode.md5", "old")
        archive.writestr("Metadata/unrelated.txt", "unchanged")
    runner = BambuStudioSlicerRunner(BambuSlicerConfig.from_dict({"start_point_prime_mm": 0.01}), repo_root=tmp_path)
    assert runner._postprocess_front_test_line_artifact(path)["removed"]
    with zipfile.ZipFile(path) as archive:
        data = archive.read("Metadata/plate_1.gcode")
        assert b"G1 E0.01 F60" in data
        assert archive.read("Metadata/plate_1.gcode.md5").decode() == hashlib.md5(data).hexdigest()
        assert archive.read("Metadata/unrelated.txt") == b"unchanged"
    assert not runner._postprocess_front_test_line_artifact(path)["removed"]


@pytest.mark.parametrize("amount", [-1, 1, float("nan"), float("inf")])
def test_start_point_prime_rejects_excessive_or_invalid_amount(amount):
    with pytest.raises(ValueError, match="start-point prime"):
        BambuStudioSlicerRunner._remove_front_test_line_from_gcode(SOURCE, start_point_prime_mm=amount)
