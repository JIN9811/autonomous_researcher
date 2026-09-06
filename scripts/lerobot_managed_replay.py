"""Bounded local OMX episode replay using native action sends, without configuration writes.

Unlike the installed ``lerobot.replay`` entry point, this runner always attempts
cleanup and emits measured final-state evidence. It never constructs a dataset
object (which can download/write cache metadata), calibrates, or configures motors.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import signal
import time


def load_episode(root: Path, episode_index: int) -> dict:
    """Read and validate one local v2 episode; never download or alter the source."""
    import pyarrow.parquet as pq

    root = Path(root).expanduser().resolve()
    info = json.loads((root / "meta/info.json").read_text())
    if not str(info.get("codebase_version", "")).startswith("v2."):
        raise ValueError("Managed replay requires a local LeRobot v2 episode.")
    if episode_index < 0 or episode_index >= int(info["total_episodes"]):
        raise ValueError("Replay episode is outside the dataset.")
    fps = float(info["fps"])
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("Dataset FPS must be finite and positive.")
    episodes = [json.loads(line) for line in (root / "meta/episodes.jsonl").read_text().splitlines() if line.strip()]
    matches = [row for row in episodes if row.get("episode_index") == episode_index]
    if len(matches) != 1 or int(matches[0].get("length", 0)) <= 0:
        raise ValueError("Replay episode metadata is missing or incomplete.")
    template = info.get("data_path", "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet")
    path = (root / template.format(episode_chunk=episode_index // int(info.get("chunks_size", 1000)),
                                  episode_index=episode_index)).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Episode data path must remain inside the local dataset.")
    rows = pq.read_table(path, columns=["action", "observation.state", "episode_index", "frame_index"]).to_pylist()
    if len(rows) != int(matches[0]["length"]):
        raise ValueError("Replay episode frame count does not match its metadata.")
    features = info["features"]
    names = {key: features[key]["names"] for key in ("action", "observation.state")}
    for key, values in names.items():
        if not values or len(set(values)) != len(values) or not all(isinstance(v, str) and v.endswith(".pos") for v in values):
            raise ValueError(f"Invalid replay joint names: {key}")
    if set(names["action"]) != set(names["observation.state"]):
        raise ValueError("Action and observed joint sets differ.")
    actions = []
    for index, row in enumerate(rows):
        if row["episode_index"] != episode_index or row["frame_index"] != index:
            raise ValueError("Replay episode frames are missing, unordered, or from another episode.")
        for key, joint_names in names.items():
            if len(row[key]) != len(joint_names) or not all(math.isfinite(float(v)) for v in row[key]):
                raise ValueError(f"Invalid replay values: {key}")
        actions.append(dict(zip(names["action"], map(float, row["action"]))))
    return {"dataset_path": str(root), "replay_episode": episode_index, "fps": fps,
            "num_frames": len(rows), "robot_type": info.get("robot_type", ""), "actions": actions,
            "target_state": dict(zip(names["observation.state"], map(float, rows[-1]["observation.state"]))) }


def run_episode(robot, episode: dict, *, sleep=time.sleep, home_timeout_s=None) -> dict:
    """Execute unchanged recorded actions and separately verify observed end pose."""
    # Same measured resume policy used by ActiveRobotCamTracker, in native units.
    tolerance = float(os.environ.get("ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_TOLERANCE_DEG", "5.0"))
    timeout = float(os.environ.get("ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_TIMEOUT_S", "4.0")) if home_timeout_s is None else home_timeout_s
    poll = float(os.environ.get("ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_POLL_S", "0.05"))
    if not all(math.isfinite(v) and v >= 0 for v in (tolerance, timeout, poll)):
        raise ValueError("Invalid existing home readback policy.")
    result = {"ok": False, "replay_home_verified": False, "frames_sent": 0,
              "follower_closed": False, "home_evidence": {"target_state": episode["target_state"],
              "reference": "recorded_end_observation.state", "tolerance": tolerance}}
    try:
        if not robot.calibration:
            raise ValueError("Saved follower calibration is required; interactive calibration is forbidden.")
        if robot.cameras:
            raise ValueError("Managed replay must not own cameras.")
        if set(robot.action_features) != set(episode["target_state"]):
            raise ValueError("The recorded joints do not match the selected follower.")
        # robot.connect() in this installed OMX version rewrites calibration and
        # position limits. Connect the already configured bus only; native send
        # and read methods retain the saved normalization and firmware limits.
        robot.bus.connect()
        robot.bus.enable_torque()
        for action in episode["actions"]:
            started = time.monotonic()
            robot.send_action(action)
            result["frames_sent"] += 1
            sleep(max(0.0, 1.0 / episode["fps"] - (time.monotonic() - started)))
        result["ok"] = True
        deadline = time.monotonic() + timeout
        while True:
            measured = robot.get_observation()
            target = episode["target_state"]
            current = {key: float(measured[key]) for key in target if key in measured}
            errors = [abs(current.get(key, float("inf")) - value) for key, value in target.items()]
            valid = len(current) == len(target) and all(math.isfinite(v) for v in current.values())
            max_error = max(errors)
            result["home_evidence"].update({"measured_state": current,
                "max_error": max_error if math.isfinite(max_error) else None})
            if valid and max_error <= tolerance:
                result["replay_home_verified"] = True
                break
            if time.monotonic() >= deadline:
                break
            sleep(poll)
    except BaseException as exc:
        result.update(ok=False, replay_home_verified=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            if robot.bus.is_connected:
                robot.bus.disconnect(disable_torque=True)
            result["follower_closed"] = not robot.bus.is_connected
        except BaseException as exc:
            result.update(ok=False, replay_home_verified=False, cleanup_error=f"{type(exc).__name__}: {exc}")
            # Native disconnect stops its sequential disable loop at the first
            # failed motor. Make one bounded independent attempt per motor so
            # an early failure cannot leave every later motor unattempted.
            # Keep the original failure even if these fallback attempts work.
            try:
                attempts = result["torque_disable_attempts"] = []
                for motor in getattr(robot.bus, "motors", {}):
                    attempt = {"motor": motor, "ok": False}
                    attempts.append(attempt)
                    try:
                        robot.bus.disable_torque(motors=motor, num_retry=0)
                        attempt["ok"] = True
                    except BaseException as disable_exc:
                        attempt["error"] = f"{type(disable_exc).__name__}: {disable_exc}"
            except BaseException as cleanup_exc:
                result["torque_cleanup_error"] = f"{type(cleanup_exc).__name__}: {cleanup_exc}"
            finally:
                # Serial ownership must be released even if torque-disable
                # or fallback bookkeeping fails; failure remains unverified.
                try:
                    robot.bus.port_handler.closePort()
                    result["follower_closed"] = not robot.bus.is_connected
                except BaseException:
                    pass
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset.root", "dataset.repo_id", "robot.type", "robot.port", "robot.id", "result_path", "session_id", "evidence_token"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--dataset.episode", type=int, default=0)
    parser.add_argument("--robot.calibration_dir", default="")
    parser.add_argument("--max_duration_s", type=float, required=True)
    args = vars(parser.parse_args(argv))
    identity = {"session_id": args["session_id"], "evidence_token": args["evidence_token"],
        "dataset_repo_id": args["dataset.repo_id"], "dataset_path": str(Path(args["dataset.root"]).resolve()),
        "replay_episode": args["dataset.episode"]}
    def interrupted(signum, _frame):
        raise InterruptedError(f"Managed replay interrupted by signal {signum}")
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM):
        signal.signal(sig, interrupted)
    result = {"ok": False, "replay_home_verified": False}
    try:
        if not math.isfinite(args["max_duration_s"]) or args["max_duration_s"] <= 0:
            raise ValueError("Replay duration must be finite and positive.")
        signal.setitimer(signal.ITIMER_REAL, args["max_duration_s"])
        episode = load_episode(Path(args["dataset.root"]), args["dataset.episode"])
        if args["robot.type"] != "omx_follower" or episode["robot_type"] not in ("", "omx_follower"):
            raise ValueError("This managed runner supports only the configured OMX follower.")
        from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
        from lerobot.robots.omx_follower.omx_follower import OmxFollower
        config = OmxFollowerConfig(port=args["robot.port"], id=args["robot.id"],
            calibration_dir=Path(args["robot.calibration_dir"]) if args["robot.calibration_dir"] else None,
            cameras={})
        result = run_episode(OmxFollower(config), episode)
    except BaseException as exc:
        result.update(ok=False, replay_home_verified=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        result.update(identity)
        output = Path(args["result_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
        temporary.replace(output)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
