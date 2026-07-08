"""Tests for the official Isaac Lab Mimic per-episode wrapper."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np

from scripts import lerobot_isaac_lab_official_mimic_generate as official_mimic_wrapper


def _write_source_hdf5(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as handle:
        handle.attrs["format_version"] = 1
        data = handle.create_group("data")
        data.attrs["env_args"] = json.dumps({"env_name": "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0"})
        for index, xyz in enumerate(([0.4, 0.3, 0.0152], [0.41, 0.32, 0.0152])):
            demo = data.create_group(f"demo_{index:06d}")
            demo.attrs["num_samples"] = 2
            demo.create_dataset("actions", data=np.zeros((2, 7), dtype=np.float32))
            initial = demo.create_group("initial_state")
            rigid = initial.create_group("rigid_object")
            cube = rigid.create_group("red_cube")
            cube.create_dataset("root_pose", data=np.asarray([[*xyz, 0.0, 0.0, 0.0, 1.0]], dtype=np.float32))
            cube.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
            obs = demo.create_group("obs")
            datagen = obs.create_group("datagen_info")
            object_pose = datagen.create_group("object_pose")
            pose = np.eye(4, dtype=np.float32).reshape(1, 4, 4).repeat(2, axis=0)
            pose[:, :3, 3] = np.asarray(xyz, dtype=np.float32)
            object_pose.create_dataset("red_cube", data=pose)


def test_official_mimic_wrapper_dry_run_creates_one_shard_per_source_demo(tmp_path: Path) -> None:
    source = tmp_path / "source.hdf5"
    output = tmp_path / "generated_dataset.hdf5"
    shard_dir = tmp_path / "official_per_episode"
    success_manifest = tmp_path / "successes.jsonl"
    failure_manifest = tmp_path / "failures.jsonl"
    summary_file = tmp_path / "summary.json"
    annotate_script = tmp_path / "annotate_demos.py"
    generate_script = tmp_path / "generate_dataset.py"
    isaac_python = tmp_path / "isaaclab.sh"
    annotate_script.write_text("print('annotate')\n", encoding="utf-8")
    generate_script.write_text("print('generate')\n", encoding="utf-8")
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_source_hdf5(source)

    completed = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/lerobot_isaac_lab_official_mimic_generate.py")),
            "--isaac-python",
            str(isaac_python),
            "--annotate-script",
            str(annotate_script),
            "--generate-script",
            str(generate_script),
            "--annotation-mode",
            "auto",
            "--task",
            "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0",
            "--input-file",
            str(source),
            "--output-file",
            str(output),
            "--shard-dir",
            str(shard_dir),
            "--success-manifest",
            str(success_manifest),
            "--failure-manifest",
            str(failure_manifest),
            "--summary-file",
            str(summary_file),
            "--trials-per-episode",
            "3",
            "--num-envs",
            "1",
            "--external-callback",
            "integrations.isaac_lab_robotis_omx.external_callback.register",
            "--robotis-domain-randomization-profile",
            "off",
            "--robotis-camera-mode",
            "off",
            "--dry-run",
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in success_manifest.read_text(encoding="utf-8").splitlines()]
    assert summary["dry_run"] is True
    assert summary["selected_demo_count"] == 2
    assert len(rows) == 2
    assert failure_manifest.read_text(encoding="utf-8") == ""
    assert (shard_dir / "demo_000000" / "source.hdf5").is_file()
    assert (shard_dir / "demo_000001" / "source.hdf5").is_file()
    assert rows[0]["status"] == "dry_run_ready"
    assert rows[0]["reset"]["xyz_m"] == [0.4, 0.3, 0.0152]
    assert rows[1]["reset"]["xyz_m"] == [0.41, 0.32, 0.0152]
    assert rows[0]["annotation_mode"] == "auto"
    assert rows[0]["annotation_command"][:3] == [str(isaac_python), "-p", str(annotate_script)]
    assert "--auto" in rows[0]["annotation_command"]
    assert "--robotis-cube-reset-xyz" in rows[0]["annotation_command"]
    assert rows[0]["annotation_command"][rows[0]["annotation_command"].index("--robotis-cube-reset-xyz") + 1] == (
        "0.4,0.3,0.0152"
    )
    assert rows[1]["annotation_command"][
        rows[1]["annotation_command"].index("--robotis-cube-reset-xyz") + 1
    ] == "0.41,0.32,0.0152"
    assert "--robotis-cube-reset-yaw" in rows[0]["annotation_command"]
    assert rows[0]["annotation_path"].endswith("official_per_episode/demo_000000/annotated.hdf5")
    assert rows[0]["command"][:3] == [str(isaac_python), "-p", str(generate_script)]
    assert rows[0]["command"][rows[0]["command"].index("--input_file") + 1].endswith(
        "official_per_episode/demo_000000/annotated.hdf5"
    )
    assert "--robotis-cube-reset-xyz" in rows[0]["command"]
    assert rows[0]["command"][rows[0]["command"].index("--robotis-cube-reset-xyz") + 1] == "0.4,0.3,0.0152"
    assert rows[1]["command"][rows[1]["command"].index("--robotis-cube-reset-xyz") + 1] == "0.41,0.32,0.0152"


def test_official_mimic_wrapper_retries_auto_annotation_until_demo_exists(tmp_path: Path) -> None:
    source = tmp_path / "source.hdf5"
    output = tmp_path / "generated_dataset.hdf5"
    shard_dir = tmp_path / "official_per_episode"
    success_manifest = tmp_path / "successes.jsonl"
    failure_manifest = tmp_path / "failures.jsonl"
    summary_file = tmp_path / "summary.json"
    counter = tmp_path / "annotate_count.txt"
    annotate_script = tmp_path / "annotate.py"
    generate_script = tmp_path / "generate.py"
    _write_source_hdf5(source)

    annotate_script.write_text(
        """
import argparse
from pathlib import Path
import h5py
p = argparse.ArgumentParser()
p.add_argument('--input_file')
p.add_argument('--output_file')
args, _ = p.parse_known_args()
counter = Path(__file__).with_name('annotate_count.txt')
count = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(count + 1))
with h5py.File(args.output_file, 'w') as handle:
    if count > 0:
        data = handle.create_group('data')
        data.create_group('demo_0')
""",
        encoding="utf-8",
    )
    generate_script.write_text(
        """
import argparse
import h5py
p = argparse.ArgumentParser()
p.add_argument('--output_file')
args, _ = p.parse_known_args()
with h5py.File(args.output_file, 'w') as handle:
    data = handle.create_group('data')
    data.create_group('demo_0')
""",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/lerobot_isaac_lab_official_mimic_generate.py")),
            "--isaac-python",
            sys.executable,
            "--annotate-script",
            str(annotate_script),
            "--generate-script",
            str(generate_script),
            "--annotation-mode",
            "auto",
            "--annotation-retries",
            "1",
            "--generation-retries",
            "0",
            "--process-cooldown-sec",
            "0",
            "--task",
            "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0",
            "--input-file",
            str(source),
            "--output-file",
            str(output),
            "--shard-dir",
            str(shard_dir),
            "--success-manifest",
            str(success_manifest),
            "--failure-manifest",
            str(failure_manifest),
            "--summary-file",
            str(summary_file),
            "--episode-indices",
            "0",
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in success_manifest.read_text(encoding="utf-8").splitlines()]
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    assert rows[0]["annotation_count"] == 1
    assert len(rows[0]["annotation_attempts"]) == 2
    assert rows[0]["schema"] == "atr.lerobot.isaac_lab_mimic.success.v1"
    assert rows[0]["source_type"] == "isaac_lab_mimic"
    assert rows[0]["source_episode_index"] == 0
    assert rows[0]["generated_demo"] == "demo_0"
    assert rows[0]["local_generated_demo"] == "demo_0"
    assert rows[0]["metrics"]["success"] is True
    assert rows[0]["metrics"]["official_mimic"] is True
    assert rows[0]["metrics"]["replay_required"] is True
    assert rows[0]["training"]["eligible"] is False
    assert rows[0]["training"]["exclusion_reason"] == "official_replay_validation_required"
    assert rows[0]["artifacts"]["hdf5_path"] == str(output)
    assert summary["status"] == "success"
    assert summary["annotation_failure_count"] == 0


def test_official_mimic_wrapper_run_command_applies_process_cooldown(tmp_path: Path, monkeypatch) -> None:
    slept: list[float] = []
    launched: list[list[str]] = []

    class Completed:
        returncode = 7

    def fake_run(command, **kwargs):
        launched.append(list(command))
        kwargs["stdout"].write("ran\n")
        return Completed()

    monkeypatch.setattr(official_mimic_wrapper.subprocess, "run", fake_run)
    monkeypatch.setattr(official_mimic_wrapper.time, "sleep", lambda seconds: slept.append(seconds))

    returncode = official_mimic_wrapper._run_command(  # noqa: SLF001
        ["fake-python", "fake-script.py"],
        tmp_path / "run.log",
        cooldown_sec=2.5,
    )

    assert returncode == 7
    assert launched == [["fake-python", "fake-script.py"]]
    assert slept == [2.5]
    assert (tmp_path / "run.log").read_text(encoding="utf-8") == "ran\n"


def test_official_mimic_replay_promoter_marks_only_replay_passed_rows_trainable(tmp_path: Path) -> None:
    generated_dataset = tmp_path / "generated_dataset.hdf5"
    success_manifest = tmp_path / "successes.jsonl"
    replay_success_manifest = tmp_path / "replay_successes.jsonl"
    replay_failure_manifest = tmp_path / "replay_failures.jsonl"
    summary_file = tmp_path / "replay_summary.json"
    log_dir = tmp_path / "replay_logs"
    replay_script = tmp_path / "replay_demos.py"
    generated_dataset.write_text("placeholder hdf5 path is enough for fake replay\n", encoding="utf-8")
    success_manifest.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                        "source_type": "isaac_lab_mimic",
                        "trajectory_id": "official_mimic_demo_000000_demo_0",
                        "source_episode_index": 0,
                        "generated_demo": "demo_0",
                        "frame_count": 100,
                        "metrics": {"success": True, "official_mimic": True, "replay_required": True},
                        "artifacts": {"hdf5_path": str(generated_dataset)},
                        "training": {"eligible": False, "exclusion_reason": "official_replay_validation_required"},
                    }
                ),
                json.dumps(
                    {
                        "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                        "source_type": "isaac_lab_mimic",
                        "trajectory_id": "official_mimic_demo_000002_demo_0",
                        "source_episode_index": 2,
                        "generated_demo": "demo_1",
                        "frame_count": 80,
                        "metrics": {"success": True, "official_mimic": True, "replay_required": True},
                        "artifacts": {"hdf5_path": str(generated_dataset)},
                        "training": {"eligible": False, "exclusion_reason": "official_replay_validation_required"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    replay_script.write_text(
        """
import argparse
p = argparse.ArgumentParser()
p.add_argument('--select_episodes', nargs='+')
args, _ = p.parse_known_args()
episode = args.select_episodes[0]
print(f'Loading #{episode} episode to env_0')
if episode == '0':
    print('Successfully replayed: 1/1')
else:
    print('Successfully replayed: 0/1')
    print('Failed demo IDs (1 total):')
    print(f'  [{episode}]')
""",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/lerobot_isaac_lab_official_mimic_replay_promote.py")),
            "--isaac-python",
            sys.executable,
            "--replay-script",
            str(replay_script),
            "--task",
            "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0",
            "--dataset-file",
            str(generated_dataset),
            "--success-manifest",
            str(success_manifest),
            "--replay-success-manifest",
            str(replay_success_manifest),
            "--replay-failure-manifest",
            str(replay_failure_manifest),
            "--summary-file",
            str(summary_file),
            "--log-dir",
            str(log_dir),
            "--external-callback",
            "integrations.isaac_lab_robotis_omx.external_callback.register",
            "--headless",
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    updated_rows = [json.loads(line) for line in success_manifest.read_text(encoding="utf-8").splitlines()]
    replay_successes = [json.loads(line) for line in replay_success_manifest.read_text(encoding="utf-8").splitlines()]
    replay_failures = [json.loads(line) for line in replay_failure_manifest.read_text(encoding="utf-8").splitlines()]
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert summary["candidate_count"] == 2
    assert summary["replay_success_count"] == 1
    assert summary["replay_failure_count"] == 1
    assert updated_rows[0]["training"]["eligible"] is True
    assert updated_rows[0]["metrics"]["lab_step_replay"] is True
    assert updated_rows[0]["metrics"]["replay_required"] is False
    assert updated_rows[1]["training"]["eligible"] is False
    assert updated_rows[1]["training"]["exclusion_reason"] == "official_replay_validation_failed"
    assert updated_rows[1]["metrics"]["lab_step_replay"] is False
    assert [row["generated_demo"] for row in replay_successes] == ["demo_0"]
    assert [row["generated_demo"] for row in replay_failures] == ["demo_1"]
