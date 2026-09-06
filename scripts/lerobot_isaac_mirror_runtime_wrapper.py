#!/usr/bin/env python3
"""
Run LeRobot teleoperate/record with ATR Isaac mirror publication in the same process.

The wrapper patches the OMX follower send_action path instead of opening a second
Dynamixel connection. This keeps teleop/record hardware ownership identical to
normal LeRobot usage while still streaming joint targets to Isaac Sim.
"""

from __future__ import annotations

import json
import inspect
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.isaac_omx_mirror_mapping import (  # noqa: E402
    action_to_joint_state,
    default_isaac_omx_mirror_calibration_path,
    load_isaac_omx_mirror_calibration,
)

DEFAULT_ISAAC_RGBD_RENDER_CAMERAS = "top,front,right"
DEFAULT_ISAAC_MIRROR_POST_TIMEOUT_S = 0.5
DEFAULT_ISAAC_RGBD_RENDER_POST_TIMEOUT_S = 0.5
LEADER_SAG_DOWN_SIGN_BY_JOINT = {
    "shoulder_lift.pos": -1.0,
    "elbow_flex.pos": 1.0,
    "wrist_flex.pos": 1.0,
}


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _env_capped_post_timeout(post_name: str, legacy_name: str, legacy_default: float, cap: float) -> float:
    legacy_value = _env_float(legacy_name, legacy_default, minimum=0.05)
    return _env_float(post_name, min(legacy_value, cap), minimum=0.02)


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _mirror_source_from_env() -> str:
    raw = os.getenv("ATR_ISAAC_MIRROR_SOURCE", "leader_action").strip().lower().replace("-", "_")
    aliases = {
        "leader": "leader_action",
        "leader_action": "leader_action",
        "teleop": "leader_action",
        "teleop_action": "leader_action",
        "action": "leader_action",
        "present": "follower_present_position",
        "present_position": "follower_present_position",
        "follower_present": "follower_present_position",
        "follower_present_position": "follower_present_position",
        "sent": "sent_action",
        "sent_action": "sent_action",
        "goal": "sent_action",
        "goal_position": "sent_action",
    }
    return aliases.get(raw, "leader_action")


def _normalize_pos_action(raw: dict[str, Any]) -> dict[str, float]:
    action: dict[str, float] = {}
    for key, value in dict(raw).items():
        name = str(key)
        if not name.endswith(".pos"):
            name = f"{name}.pos"
        try:
            action[name] = float(value)
        except (TypeError, ValueError):
            continue
    return action


class IsaacMirrorPublisher:
    def __init__(self) -> None:
        self.enabled = os.getenv("ATR_ISAAC_MIRROR_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
        self.endpoint = os.getenv("ATR_ISAAC_MIRROR_ENDPOINT", "http://127.0.0.1:8766/joints").strip()
        self.timeout_s = _env_capped_post_timeout(
            "ATR_ISAAC_MIRROR_POST_TIMEOUT_S",
            "ATR_ISAAC_MIRROR_TIMEOUT_S",
            0.5,
            DEFAULT_ISAAC_MIRROR_POST_TIMEOUT_S,
        )
        self.sample_hz = _env_float("ATR_ISAAC_MIRROR_SAMPLE_HZ", 15.0, minimum=0.1)
        self.period_s = 1.0 / self.sample_hz
        self.min_period_ratio = min(1.0, _env_float("ATR_ISAAC_MIRROR_MIN_PERIOD_RATIO", 0.9, minimum=0.1))
        self.source = _mirror_source_from_env()
        self.leader_sag_enabled = _env_bool("ATR_ISAAC_MIRROR_LEADER_SAG_COMPENSATION_ENABLED", True)
        self.leader_sag_min_delta = _env_float("ATR_ISAAC_MIRROR_LEADER_SAG_MIN_DELTA", 0.25, minimum=0.0)
        self.session_id = os.getenv("ATR_ISAAC_MIRROR_SESSION_ID", "").strip()
        self.attached_to_session_id = os.getenv("ATR_ISAAC_MIRROR_ATTACHED_TO_SESSION_ID", "").strip()
        self.profile_id = os.getenv("ATR_ISAAC_MIRROR_PROFILE_ID", "").strip()
        self.record_path = Path(os.getenv("ATR_ISAAC_MIRROR_RECORD_PATH", "").strip()).expanduser()
        calibration_path = os.getenv("ATR_ISAAC_MIRROR_CALIBRATION_PATH", "").strip()
        self.calibration = load_isaac_omx_mirror_calibration(calibration_path or default_isaac_omx_mirror_calibration_path(REPO_ROOT))
        self.render_context = IsaacRgbdRenderContext()
        self.render_worker = IsaacRgbdRenderWorker(self.render_context, mirror_endpoint=self.endpoint, default_timeout_s=self.timeout_s)
        self._last_post_monotonic = 0.0
        self._sample_count = 0
        self._async_enabled = _env_bool("ATR_ISAAC_MIRROR_ASYNC_ENABLED", True)
        self.record_frame_sync_enabled = _env_bool("ATR_ISAAC_MIRROR_RECORD_FRAME_SYNC_ENABLED", True)
        self._jobs: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._worker_started = False
        self._worker_active = False
        self._worker_lock = threading.Lock()
        self._collection_enabled = True
        self._record_collection_active = False
        self._publish_enabled = True

    def should_publish(self) -> bool:
        if not self.enabled or not self._publish_enabled:
            return False
        if self.record_frame_sync_enabled and self._record_collection_active:
            return True
        now = time.monotonic()
        if self._last_post_monotonic and now - self._last_post_monotonic < self.period_s * self.min_period_ratio:
            return False
        return True

    def action_from_follower(
        self,
        follower: Any,
        sent_action: dict[str, Any],
        *,
        leader_action: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
        if self.source == "leader_action":
            if isinstance(leader_action, dict) and leader_action:
                return _normalize_pos_action(leader_action), "in_process_leader_action", "", {}
            return (
                _normalize_pos_action(sent_action),
                "in_process_send_action_fallback",
                "leader_action_unavailable",
                {},
            )
        if self.source == "sent_action":
            return _normalize_pos_action(sent_action), "in_process_send_action", "", {}
        if self.source != "follower_present_position":
            return _normalize_pos_action(sent_action), "in_process_send_action", "", {}
        cached = getattr(follower, "_atr_latest_present_position_action", None)
        if isinstance(cached, dict) and cached:
            follower_action = _normalize_pos_action(cached)
            mirror_action, selection = self._leader_sag_compensated_action(follower_action, leader_action)
            if selection.get("leader_selected_count", 0):
                return mirror_action, "in_process_hybrid_follower_present_position_leader_sag", "", selection
            return mirror_action, "in_process_follower_present_position", "", selection
        return (
            sent_action,
            "in_process_send_action_fallback",
            "cached_follower_present_position_unavailable",
            {"mode": "sent_action_fallback"},
        )

    def _leader_sag_compensated_action(
        self,
        follower_action: dict[str, float],
        leader_action: dict[str, Any] | None,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        selected = dict(follower_action)
        source_by_joint = {key: "follower" for key in selected}
        deltas: dict[str, dict[str, float]] = {}
        if not self.leader_sag_enabled or not isinstance(leader_action, dict) or not leader_action:
            return selected, {
                "mode": "follower_present_position",
                "leader_selected_count": 0,
                "min_delta": self.leader_sag_min_delta,
                "selected_source_by_joint": source_by_joint,
            }
        leader = _normalize_pos_action(leader_action)
        leader_selected_count = 0
        for key, down_sign in LEADER_SAG_DOWN_SIGN_BY_JOINT.items():
            if key not in leader or key not in follower_action:
                continue
            leader_value = float(leader[key])
            follower_value = float(follower_action[key])
            lower_delta = float(down_sign) * (leader_value - follower_value)
            deltas[key] = {
                "leader": leader_value,
                "follower": follower_value,
                "lower_delta": lower_delta,
            }
            if lower_delta > self.leader_sag_min_delta:
                selected[key] = leader_value
                source_by_joint[key] = "leader"
                leader_selected_count += 1
        return selected, {
            "mode": "leader_when_lower_than_follower",
            "leader_selected_count": leader_selected_count,
            "min_delta": self.leader_sag_min_delta,
            "down_sign_by_joint": dict(LEADER_SAG_DOWN_SIGN_BY_JOINT),
            "selected_source_by_joint": source_by_joint,
            "leader_follower_delta_by_joint": deltas,
        }

    def maybe_publish(
        self,
        sent_action: dict[str, Any],
        *,
        source: str = "in_process_send_action",
        source_error: str = "",
        source_selection: dict[str, Any] | None = None,
    ) -> None:
        if not self.should_publish():
            return
        self.publish_action(sent_action, source=source, source_error=source_error, source_selection=source_selection)

    def publish_action(
        self,
        action: dict[str, Any],
        *,
        source: str,
        source_error: str = "",
        source_selection: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or not self._publish_enabled:
            return
        joint_state = action_to_joint_state(action, calibration=self.calibration)
        if not joint_state:
            return
        self._last_post_monotonic = time.monotonic()
        self._sample_count += 1
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "session_id": self.session_id or self.attached_to_session_id,
            "attached_to_session_id": self.attached_to_session_id,
            "sample_index": self._sample_count,
            "timestamp": timestamp,
            "elapsed_s": 0.0,
            "mode": "live",
            "profile_id": self.profile_id,
            "scene_path": "",
            "articulation_root": "/World/Robot/Geometry/link0",
            "follower_port": source,
            "calibration": self.calibration,
            "joint_state": joint_state,
        }
        record_attempt_id = os.getenv("ATR_RECORD_ATTEMPT_ID", "").strip()
        if record_attempt_id:
            payload["record_attempt_id"] = record_attempt_id
            payload["record_episode_index"] = _env_int("ATR_RECORD_ATTEMPT_EPISODE_INDEX", 0, minimum=0)
        if isinstance(source_selection, dict) and source_selection:
            payload["source_selection"] = source_selection
        collection_enabled = self.collection_enabled
        render_queue = self.render_worker.enqueue(payload, self._sample_count, timestamp) if collection_enabled else {}
        post_started = time.monotonic()
        job = {
            "payload": payload,
            "source": source,
            "source_error": source_error,
            "post_started": post_started,
            "render_queue": render_queue,
            "collection_enabled": collection_enabled,
            "record_collection_active": self._record_collection_active,
        }
        if self._async_enabled:
            self._enqueue_job(job)
        else:
            self._process_job(job)

    @property
    def collection_enabled(self) -> bool:
        return bool(self._collection_enabled)

    @contextmanager
    def publish_scope(self, enabled: bool, *, reason: str = "") -> Iterator[None]:
        previous = self._publish_enabled
        self._publish_enabled = bool(enabled)
        try:
            yield
        finally:
            self._publish_enabled = previous

    @contextmanager
    def collection_scope(self, enabled: bool, *, reason: str = "") -> Iterator[None]:
        previous = self._collection_enabled
        previous_record = self._record_collection_active
        self._collection_enabled = bool(enabled)
        self._record_collection_active = bool(
            enabled and self.record_frame_sync_enabled and str(reason or "") == "record_episode"
        )
        try:
            yield
        finally:
            self._collection_enabled = previous
            self._record_collection_active = previous_record

    def reset_collection_frame_context(self) -> None:
        self.render_context.reset_frame_context()

    def discard_collection_for_attempt(self, *, attempt_id: str, episode_index: int | None = None) -> bool:
        if not attempt_id:
            return False
        self.flush(timeout_s=2.0)
        self.reset_collection_frame_context()
        if not self.record_path or not self.record_path.is_file():
            return True
        kept: list[str] = []
        removed = False
        try:
            lines = self.record_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if isinstance(row, dict) and self._record_row_matches_attempt(
                row,
                attempt_id=attempt_id,
                episode_index=episode_index,
            ):
                removed = True
                continue
            kept.append(json.dumps(row, ensure_ascii=False) if isinstance(row, dict) else line)
        if not removed:
            return True
        try:
            if kept:
                tmp_path = self.record_path.with_suffix(self.record_path.suffix + ".tmp")
                tmp_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
                tmp_path.replace(self.record_path)
            else:
                self.record_path.unlink(missing_ok=True)
        except OSError:
            return False
        return True

    @staticmethod
    def _record_row_matches_attempt(
        row: dict[str, Any],
        *,
        attempt_id: str,
        episode_index: int | None,
    ) -> bool:
        render_queue = row.get("render_queue") if isinstance(row.get("render_queue"), dict) else {}
        request = render_queue.get("render_request") if isinstance(render_queue.get("render_request"), dict) else {}
        row_attempt_id = str(
            request.get("attempt_id")
            or render_queue.get("attempt_id")
            or row.get("record_attempt_id")
            or ""
        ).strip()
        if row_attempt_id != attempt_id:
            return False
        if episode_index is None:
            return True
        try:
            row_episode_index = int(float(request.get("episode_index", row.get("record_episode_index", 0))))
        except (TypeError, ValueError):
            row_episode_index = 0
        return row_episode_index == int(episode_index)

    def _enqueue_job(self, job: dict[str, Any]) -> None:
        self._ensure_worker()
        if bool(job.get("record_collection_active")):
            self._jobs.put(job)
            return
        try:
            self._jobs.put_nowait(job)
            return
        except queue.Full:
            pass
        try:
            self._jobs.get_nowait()
            self._jobs.task_done()
        except queue.Empty:
            pass
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            pass

    def _ensure_worker(self) -> None:
        if self._worker_started:
            return
        with self._worker_lock:
            if self._worker_started:
                return
            worker = threading.Thread(target=self._worker_loop, name="atr-isaac-mirror-publisher", daemon=True)
            worker.start()
            self._worker_started = True

    def _worker_loop(self) -> None:
        while True:
            job = self._jobs.get()
            with self._worker_lock:
                self._worker_active = True
            try:
                self._process_job(job)
            finally:
                with self._worker_lock:
                    self._worker_active = False
                self._jobs.task_done()

    def _process_job(self, job: dict[str, Any]) -> None:
        payload = dict(job["payload"])
        post_started = time.monotonic()
        post_result = self._post(payload)
        source_error = str(job.get("source_error") or "")
        sync_metrics = {
            "target_sample_hz": self.sample_hz,
            "sample_period_s": self.period_s,
            "sample_index": payload.get("sample_index"),
            "post_latency_ms": round((time.monotonic() - post_started) * 1000.0, 3),
            "receiver_accepted": bool(post_result.get("ok")),
            "receiver_status_code": post_result.get("status_code"),
            "source": str(job.get("source") or ""),
        }
        if source_error:
            sync_metrics["source_error"] = source_error
        record = {
            **payload,
            "sync_metrics": sync_metrics,
            "isaac_post": post_result,
        }
        render_queue = job.get("render_queue")
        if isinstance(render_queue, dict) and render_queue:
            record["render_queue"] = render_queue
        if bool(job.get("collection_enabled", True)) and self.record_path:
            self.record_path.parent.mkdir(parents=True, exist_ok=True)
            with self.record_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def flush(self, timeout_s: float = 2.0) -> bool:
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while time.monotonic() <= deadline:
            with self._worker_lock:
                active = self._worker_active
            if self._jobs.unfinished_tasks == 0 and not active:
                return self.render_worker.flush(timeout_s=max(0.0, deadline - time.monotonic()))
            time.sleep(0.005)
        return False

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = Request(self.endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                body = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(body) if body else {}
                return {"ok": 200 <= response.status < 300, "status_code": response.status, "response": parsed}
        except Exception as exc:
            return {"ok": False, "status_code": None, "error": f"{exc.__class__.__name__}: {exc}"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _isaac_mirror_timeline_play_url(endpoint: str) -> str:
    parsed = urlparse(str(endpoint or "http://127.0.0.1:8766/joints").strip())
    if not parsed.scheme or not parsed.netloc:
        return "http://127.0.0.1:8766/timeline/play"
    return parsed._replace(path="/timeline/play", params="", query="", fragment="").geturl()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class RecordAttemptSidecar:
    def __init__(self) -> None:
        raw_dataset = os.getenv("ATR_RECORD_ATTEMPT_DATASET_PATH", "").strip()
        self.dataset_path = Path(raw_dataset).expanduser() if raw_dataset else None
        self.enabled = _env_bool("ATR_RECORD_ATTEMPT_ENABLED", False) and self.dataset_path is not None
        self.session_id = os.getenv("ATR_RECORD_ATTEMPT_SESSION_ID", "").strip()
        generated_attempt_id = "attempt_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.base_attempt_id = self._strip_episode_suffix(os.getenv("ATR_RECORD_ATTEMPT_ID", generated_attempt_id).strip() or generated_attempt_id)
        self.attempt_id = self.base_attempt_id
        self.episode_index = _env_int("ATR_RECORD_ATTEMPT_EPISODE_INDEX", 0, minimum=0)
        self.target_fps = _env_float("ATR_RECORD_ATTEMPT_TARGET_FPS", 15.0, minimum=0.1)
        self.overwrite = _env_bool("ATR_RECORD_ATTEMPT_OVERWRITE", True)
        self.root = self.dataset_path / "sidecar" / "attempts" if self.dataset_path is not None else Path()
        self.attempt_dir = self.root / f"episode_{self.episode_index:03d}" / self.attempt_id
        self.manifest_path = self.root / "manifest.jsonl"
        self.status_path = self.attempt_dir / "status.json"
        self.render_output_dir = self._render_output_dir_for(self.episode_index, self.attempt_id)
        self._started_attempts: set[tuple[int, str]] = set()

    @staticmethod
    def _strip_episode_suffix(attempt_id: str) -> str:
        if len(attempt_id) > 6 and attempt_id[-6:-3] == "_ep" and attempt_id[-3:].isdigit():
            return attempt_id[:-6]
        return attempt_id

    def _attempt_id_for_episode(self, episode_index: int) -> str:
        return f"{self.base_attempt_id}_ep{int(episode_index):03d}"

    def _render_output_dir_for(self, episode_index: int, attempt_id: str) -> Path:
        if self.dataset_path is None:
            raw_render_output = os.getenv("ATR_ISAAC_RGBD_RENDER_OUTPUT_DIR", "").strip()
            return Path(raw_render_output).expanduser() if raw_render_output else Path()
        return self.dataset_path / "sidecar" / "isaac_rgbd" / f"episode_{int(episode_index):03d}" / attempt_id

    def _set_episode_context(self, episode_index: int) -> None:
        self.episode_index = max(0, int(episode_index))
        self.attempt_id = self._attempt_id_for_episode(self.episode_index)
        self.attempt_dir = self.root / f"episode_{self.episode_index:03d}" / self.attempt_id
        self.status_path = self.attempt_dir / "status.json"
        self.render_output_dir = self._render_output_dir_for(self.episode_index, self.attempt_id)
        os.environ["ATR_RECORD_ATTEMPT_ID"] = self.attempt_id
        os.environ["ATR_RECORD_ATTEMPT_EPISODE_INDEX"] = str(self.episode_index)
        if self.render_output_dir:
            os.environ["ATR_ISAAC_RGBD_RENDER_OUTPUT_DIR"] = str(self.render_output_dir)

    def begin_episode(self, *, episode_index: int, reason: str = "record_start") -> dict[str, Any]:
        self._set_episode_context(episode_index)
        return self.begin(reason=reason)

    def begin(self, *, reason: str = "record_start") -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "status": "disabled"}
        if self.overwrite:
            self._reset_attempt_outputs()
            self._started_attempts.discard((self.episode_index, self.attempt_id))
        self.attempt_dir.mkdir(parents=True, exist_ok=True)
        status = self._status_payload("started", reason=reason)
        self.status_path.write_text(json.dumps(status, indent=2, ensure_ascii=True), encoding="utf-8")
        attempt_key = (self.episode_index, self.attempt_id)
        if attempt_key not in self._started_attempts:
            self._append_event("record_attempt_started", {"reason": reason})
            self._started_attempts.add(attempt_key)
        return {"ok": True, "status": "started", "attempt_dir": str(self.attempt_dir), "attempt_id": self.attempt_id}

    def write_active_cam_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "status": "disabled"}
        if (self.episode_index, self.attempt_id) not in self._started_attempts:
            self.begin(reason="record_start")
        self.attempt_dir.mkdir(parents=True, exist_ok=True)
        result_path = self.attempt_dir / "active_cam_result.json"
        result_path.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
        snapshot = self._extract_snapshot(result)
        specimen_pose_path = ""
        if snapshot:
            pose_path = self.attempt_dir / "specimen_pose.json"
            pose_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True), encoding="utf-8")
            specimen_pose_path = str(pose_path)
        status = self._status_payload(
            "active_cam_result_written",
            result_path=str(result_path),
            specimen_pose_path=specimen_pose_path,
            active_cam_ok=bool(result.get("ok")),
        )
        self.status_path.write_text(json.dumps(status, indent=2, ensure_ascii=True), encoding="utf-8")
        self._append_event(
            "active_cam_result_written",
            {
                "result_path": str(result_path),
                "specimen_pose_path": specimen_pose_path,
                "active_cam_ok": bool(result.get("ok")),
            },
        )
        return {
            "ok": True,
            "status": "active_cam_result_written",
            "attempt_dir": str(self.attempt_dir),
            "result_path": str(result_path),
            "specimen_pose_path": specimen_pose_path,
        }

    def _status_payload(self, status: str, **extra: Any) -> dict[str, Any]:
        return {
            "schema": "atr.record_attempt.status.v1",
            "status": status,
            "session_id": self.session_id,
            "attempt_id": self.attempt_id,
            "episode_index": self.episode_index,
            "target_fps": self.target_fps,
            "dataset_path": str(self.dataset_path or ""),
            "attempt_dir": str(self.attempt_dir),
            "isaac_rgbd_render_output_dir": str(self.render_output_dir),
            "overwrite": self.overwrite,
            "updated_at": _utc_timestamp(),
            **extra,
        }

    def _reset_attempt_outputs(self) -> None:
        if not self.attempt_id or self.dataset_path is None:
            return
        self._remove_attempt_scoped_path(self.attempt_dir, allowed_root=self.root)
        self._remove_attempt_scoped_path(self.render_output_dir, allowed_root=self.dataset_path / "sidecar" / "isaac_rgbd")
        self._remove_manifest_rows_for_attempt()

    def _remove_attempt_scoped_path(self, path: Path, *, allowed_root: Path) -> None:
        if not str(path):
            return
        try:
            resolved = path.resolve(strict=False)
            allowed = allowed_root.resolve(strict=False)
        except OSError:
            return
        if path.name != self.attempt_id:
            return
        if resolved == allowed or allowed not in resolved.parents:
            return
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except OSError:
            return

    def _remove_manifest_rows_for_attempt(self) -> None:
        if not self.manifest_path.is_file():
            return
        kept: list[str] = []
        try:
            lines = self.manifest_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if isinstance(row, dict) and self._is_current_attempt_row(row):
                continue
            kept.append(json.dumps(row, ensure_ascii=True) if isinstance(row, dict) else line)
        try:
            tmp_path = self.manifest_path.with_suffix(self.manifest_path.suffix + ".tmp")
            tmp_path.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
            tmp_path.replace(self.manifest_path)
        except OSError:
            return

    def _is_current_attempt_row(self, row: dict[str, Any]) -> bool:
        if str(row.get("attempt_id") or "") != self.attempt_id:
            return False
        try:
            episode_index = int(float(row.get("episode_index", self.episode_index)))
        except (TypeError, ValueError):
            episode_index = self.episode_index
        return episode_index == self.episode_index

    def _append_event(self, event: str, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        row = {
            "schema": "atr.record_attempt.event.v1",
            "event": event,
            "timestamp": _utc_timestamp(),
            "session_id": self.session_id,
            "attempt_id": self.attempt_id,
            "episode_index": self.episode_index,
            **payload,
        }
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    @staticmethod
    def _extract_snapshot(result: dict[str, Any]) -> dict[str, Any]:
        direct = result.get("snapshot")
        if isinstance(direct, dict):
            return dict(direct)
        attempts = result.get("attempts")
        if isinstance(attempts, list):
            for attempt in attempts:
                if not isinstance(attempt, dict):
                    continue
                nested_result = attempt.get("result")
                if isinstance(nested_result, dict) and isinstance(nested_result.get("snapshot"), dict):
                    return dict(nested_result["snapshot"])
                if isinstance(attempt.get("snapshot"), dict):
                    return dict(attempt["snapshot"])
        return {}


class IsaacRgbdRenderContext:
    def __init__(self) -> None:
        self.dataset_path: Path | None = None
        self.enabled = False
        self.session_id = ""
        self.attempt_id = ""
        self.episode_index = 0
        self.target_fps = 15.0
        self.cameras: list[str] = []
        self.output_dir: Path | None = None
        self._context_key = ""
        self._sample_base = 0
        self._refresh_from_env(sample_index=1)

    def _refresh_from_env(self, *, sample_index: int) -> None:
        raw_dataset = os.getenv("ATR_RECORD_ATTEMPT_DATASET_PATH", "").strip()
        self.dataset_path = Path(raw_dataset).expanduser() if raw_dataset else None
        self.enabled = _env_bool("ATR_ISAAC_RGBD_RENDER_ENABLED", False)
        self.session_id = os.getenv("ATR_RECORD_ATTEMPT_SESSION_ID", "").strip()
        self.attempt_id = os.getenv("ATR_RECORD_ATTEMPT_ID", "").strip()
        self.episode_index = _env_int("ATR_RECORD_ATTEMPT_EPISODE_INDEX", 0, minimum=0)
        self.target_fps = _env_float(
            "ATR_ISAAC_RGBD_RENDER_TARGET_FPS",
            _env_float("ATR_RECORD_ATTEMPT_TARGET_FPS", 15.0, minimum=0.1),
            minimum=0.1,
        )
        self.cameras = [
            item.strip()
            for item in os.getenv("ATR_ISAAC_RGBD_RENDER_CAMERAS", DEFAULT_ISAAC_RGBD_RENDER_CAMERAS).split(",")
            if item.strip()
        ]
        raw_output = os.getenv("ATR_ISAAC_RGBD_RENDER_OUTPUT_DIR", "").strip()
        if raw_output:
            self.output_dir = Path(raw_output).expanduser()
        elif self.dataset_path is not None and self.attempt_id:
            self.output_dir = self.dataset_path / "sidecar" / "isaac_rgbd" / f"episode_{self.episode_index:03d}" / self.attempt_id
        else:
            self.output_dir = None
        context_key = f"{self.session_id}|{self.attempt_id}|{self.episode_index}|{self.output_dir}"
        if context_key != self._context_key:
            self._context_key = context_key
            self._sample_base = max(0, int(sample_index) - 1)

    def reset_frame_context(self) -> None:
        self._context_key = ""
        self._sample_base = 0

    def request_for_sample(self, sample_index: int, timestamp: str) -> dict[str, Any] | None:
        self._refresh_from_env(sample_index=sample_index)
        if not self.enabled or not self.attempt_id or self.output_dir is None:
            return None
        frame_index = max(0, int(sample_index) - self._sample_base - 1)
        return {
            "schema": "atr.isaac_rgbd.render_request.v1",
            "enabled": True,
            "session_id": self.session_id,
            "attempt_id": self.attempt_id,
            "episode_index": self.episode_index,
            "sample_index": int(sample_index),
            "frame_index": frame_index,
            "timestamp": timestamp,
            "target_fps": self.target_fps,
            "cameras": list(self.cameras),
            "output_dir": str(self.output_dir),
        }


class IsaacRgbdRenderWorker:
    """Asynchronously submits Isaac RGB-D render snapshots outside the mirror loop."""

    def __init__(self, context: IsaacRgbdRenderContext, *, mirror_endpoint: str, default_timeout_s: float) -> None:
        self.context = context
        self.enabled = _env_bool("ATR_ISAAC_RGBD_RENDER_SEPARATE_LOOP", True)
        self.mode = os.getenv("ATR_ISAAC_RGBD_RENDER_MODE", "live").strip().lower() or "live"
        self.endpoint = self._render_endpoint_for(mirror_endpoint)
        self.timeout_s = _env_capped_post_timeout(
            "ATR_ISAAC_RGBD_RENDER_POST_TIMEOUT_S",
            "ATR_ISAAC_RGBD_RENDER_TIMEOUT_S",
            default_timeout_s,
            DEFAULT_ISAAC_RGBD_RENDER_POST_TIMEOUT_S,
        )
        maxsize = _env_int("ATR_ISAAC_RGBD_RENDER_QUEUE_SIZE", 1, minimum=1)
        self._jobs: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=maxsize)
        self._worker_started = False
        self._worker_active = False
        self._worker_lock = threading.Lock()

    @staticmethod
    def _render_endpoint_for(mirror_endpoint: str) -> str:
        configured = os.getenv("ATR_ISAAC_RGBD_RENDER_ENDPOINT", "").strip()
        if configured:
            return configured
        endpoint = (mirror_endpoint or "http://127.0.0.1:8766/joints").strip()
        trimmed = endpoint.rstrip("/")
        if trimmed.endswith("/joints"):
            return trimmed[: -len("/joints")] + "/render"
        return trimmed + "/render"

    def enqueue(self, payload: dict[str, Any], sample_index: int, timestamp: str) -> dict[str, Any]:
        if not self.enabled:
            return {}
        render_request = self.context.request_for_sample(sample_index, timestamp)
        if not render_request:
            return {}
        render_payload = {
            **payload,
            "joint_state": [dict(item) for item in payload.get("joint_state", []) if isinstance(item, dict)],
            "render_request": render_request,
        }
        if self.mode in {"deferred", "deferred_after_record", "post_record", "after_record"}:
            return {
                "status": "deferred_after_record",
                "attempt_id": render_request.get("attempt_id"),
                "episode_index": render_request.get("episode_index"),
                "sample_index": render_request.get("sample_index"),
                "frame_index": render_request.get("frame_index"),
                "endpoint": self.endpoint,
                "render_request": render_request,
            }
        job = {
            "payload": render_payload,
            "request": render_request,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        self._ensure_worker()
        status = "queued"
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            try:
                self._jobs.get_nowait()
                self._jobs.task_done()
                status = "queued_replaced_stale"
            except queue.Empty:
                status = "queued_after_empty_race"
            try:
                self._jobs.put_nowait(job)
            except queue.Full:
                return {
                    "status": "queue_full",
                    "attempt_id": render_request.get("attempt_id"),
                    "sample_index": render_request.get("sample_index"),
                    "frame_index": render_request.get("frame_index"),
                    "endpoint": self.endpoint,
                }
        return {
            "status": status,
            "attempt_id": render_request.get("attempt_id"),
            "episode_index": render_request.get("episode_index"),
            "sample_index": render_request.get("sample_index"),
            "frame_index": render_request.get("frame_index"),
            "endpoint": self.endpoint,
        }

    def _ensure_worker(self) -> None:
        if self._worker_started:
            return
        with self._worker_lock:
            if self._worker_started:
                return
            worker = threading.Thread(target=self._worker_loop, name="atr-isaac-rgbd-render-worker", daemon=True)
            worker.start()
            self._worker_started = True

    def _worker_loop(self) -> None:
        while True:
            job = self._jobs.get()
            with self._worker_lock:
                self._worker_active = True
            try:
                self._process_job(job)
            finally:
                with self._worker_lock:
                    self._worker_active = False
                self._jobs.task_done()

    def _process_job(self, job: dict[str, Any]) -> None:
        payload = dict(job["payload"])
        result = self._post(payload)
        self._write_job_result(job, result)

    def _write_job_result(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        request = job.get("request") if isinstance(job.get("request"), dict) else {}
        output_dir = Path(str(request.get("output_dir") or "")).expanduser()
        if not str(output_dir):
            return
        row = {
            "schema": "atr.isaac_rgbd.render_worker_job.v1",
            "queued_at": job.get("queued_at"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": self.endpoint,
            "attempt_id": request.get("attempt_id"),
            "episode_index": request.get("episode_index"),
            "sample_index": request.get("sample_index"),
            "frame_index": request.get("frame_index"),
            "ok": bool(result.get("ok")),
            "status_code": result.get("status_code"),
            "response_status": (result.get("response") or {}).get("status") if isinstance(result.get("response"), dict) else "",
            "error": result.get("error", ""),
        }
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            with (output_dir / "render_jobs.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            return

    def flush(self, timeout_s: float = 2.0) -> bool:
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while time.monotonic() <= deadline:
            with self._worker_lock:
                active = self._worker_active
            if self._jobs.unfinished_tasks == 0 and not active:
                return True
            time.sleep(0.005)
        return False

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = Request(self.endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                body = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(body) if body else {}
                return {"ok": 200 <= response.status < 300, "status_code": response.status, "response": parsed}
        except Exception as exc:
            return {"ok": False, "status_code": None, "error": f"{exc.__class__.__name__}: {exc}"}


class LatestFrameSidecar:
    def __init__(self) -> None:
        self.enabled = _env_bool("ATR_LEROBOT_LATEST_FRAME_ENABLED", True)
        self.root = Path(os.getenv("ATR_LEROBOT_LATEST_FRAME_DIR", "/tmp/atr_lerobot_latest_frame")).expanduser()
        self.camera_key = os.getenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "top").strip() or "top"
        self.color_space = os.getenv("ATR_LEROBOT_LATEST_FRAME_COLOR_SPACE", "rgb").strip().lower() or "rgb"
        self.max_hz = _env_float("ATR_LEROBOT_LATEST_FRAME_HZ", 3.0, minimum=0.1)
        self.period_s = 1.0 / self.max_hz
        self.manifest_path = self.root / "latest_frame.json"
        self._last_write_monotonic = 0.0
        self._frame_index = 0
        self.raw_depth_root = self.root / "raw_depth"
        self._async_enabled = _env_bool("ATR_LEROBOT_LATEST_FRAME_ASYNC_ENABLED", True)
        self._jobs: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._worker_started = False
        self._worker_active = False
        self._worker_lock = threading.Lock()
        self._write_lock = threading.Lock()

    def should_write(self, *, force: bool = False) -> bool:
        if not self.enabled:
            return False
        if force:
            return True
        now = time.monotonic()
        return not self._last_write_monotonic or now - self._last_write_monotonic >= self.period_s

    def write_observation(
        self,
        observation: dict[str, Any],
        *,
        force: bool = False,
        reason: str = "latest",
        depth_scale_m_per_unit: float | None = None,
    ) -> Path:
        if not self.should_write(force=force):
            return self.manifest_path
        job = self._snapshot_write_job(
            observation,
            reason=reason,
            depth_scale_m_per_unit=depth_scale_m_per_unit,
        )
        if job is None:
            return self.manifest_path
        if force or not self._async_enabled:
            return self._write_job(job)
        self._last_write_monotonic = time.monotonic()
        self._enqueue_job(job)
        return self.manifest_path

    def _snapshot_write_job(
        self,
        observation: dict[str, Any],
        *,
        reason: str,
        depth_scale_m_per_unit: float | None,
    ) -> dict[str, Any] | None:
        if not isinstance(observation, dict) or self.camera_key not in observation:
            return None
        try:
            import numpy as np
        except Exception:
            return None

        color = np.array(observation[self.camera_key], copy=True)
        if color.ndim != 3 or color.shape[-1] < 3:
            return None

        frame_index = self._frame_index
        self._frame_index += 1
        depth_key = f"{self.camera_key}_depth"
        depth = np.array(observation[depth_key], copy=True) if depth_key in observation else None
        depth_scale = (
            float(depth_scale_m_per_unit)
            if depth_scale_m_per_unit is not None and float(depth_scale_m_per_unit) > 0.0
            else _env_float("ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT", 0.001, minimum=0.0)
        )
        return {
            "frame_index": frame_index,
            "reason": reason,
            "color": color,
            "depth": depth,
            "depth_scale": depth_scale,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "time_unix_s": time.time(),
        }

    def _enqueue_job(self, job: dict[str, Any]) -> None:
        self._ensure_worker()
        try:
            self._jobs.put_nowait(job)
            return
        except queue.Full:
            pass
        try:
            self._jobs.get_nowait()
            self._jobs.task_done()
        except queue.Empty:
            pass
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            pass

    def _ensure_worker(self) -> None:
        if self._worker_started:
            return
        with self._worker_lock:
            if self._worker_started:
                return
            worker = threading.Thread(target=self._worker_loop, name="atr-latest-frame-sidecar", daemon=True)
            worker.start()
            self._worker_started = True

    def _worker_loop(self) -> None:
        while True:
            job = self._jobs.get()
            with self._worker_lock:
                self._worker_active = True
            try:
                self._write_job(job)
            except Exception:
                pass
            finally:
                with self._worker_lock:
                    self._worker_active = False
                self._jobs.task_done()

    def flush(self, timeout_s: float = 2.0) -> bool:
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while time.monotonic() <= deadline:
            with self._worker_lock:
                active = self._worker_active
            if self._jobs.unfinished_tasks == 0 and not active:
                return True
            time.sleep(0.005)
        return False

    def _tmp_path_for(self, final_path: Path, job: dict[str, Any]) -> Path:
        token = f"{os.getpid()}.{threading.get_ident()}.{int(job.get('frame_index', 0))}.{time.time_ns()}"
        return final_path.with_name(f"{final_path.stem}.{token}.tmp{final_path.suffix}")

    def _write_job(self, job: dict[str, Any]) -> Path:
        try:
            import numpy as np
            from PIL import Image
        except Exception:
            return self.manifest_path

        with self._write_lock:
            return self._write_job_locked(job, np=np, Image=Image)

    def _write_job_locked(self, job: dict[str, Any], *, np: Any, Image: Any) -> Path:
        color = np.asarray(job["color"])
        color_u8 = color[..., :3]
        if color_u8.dtype != np.uint8:
            color_u8 = np.clip(color_u8, 0, 255).astype(np.uint8)
        if self.color_space == "bgr":
            color_u8 = color_u8[..., ::-1]

        self.root.mkdir(parents=True, exist_ok=True)
        color_path = self.root / "top_color.png"
        tmp_color_path = self._tmp_path_for(color_path, job)
        Image.fromarray(color_u8, mode="RGB").save(tmp_color_path)
        tmp_color_path.replace(color_path)

        depth_visual_path = ""
        depth = job.get("depth")
        if depth is not None:
            depth_visual = np.asarray(depth)
            if depth_visual.ndim == 2:
                depth_visual_u8 = np.clip(depth_visual, 0, 255).astype(np.uint8)
                image = Image.fromarray(depth_visual_u8, mode="L")
            elif depth_visual.ndim == 3:
                depth_visual_u8 = np.clip(depth_visual[..., :3], 0, 255).astype(np.uint8)
                image = Image.fromarray(depth_visual_u8, mode="RGB")
            else:
                image = None
            if image is not None:
                visual_path = self.root / "top_depth_visual.png"
                tmp_visual_path = self._tmp_path_for(visual_path, job)
                image.save(tmp_visual_path)
                tmp_visual_path.replace(visual_path)
                depth_visual_path = str(visual_path)

        raw_depth_path = self._latest_raw_depth_path()
        manifest = {
            "schema": "atr_lerobot_latest_frame.v1",
            "camera_key": self.camera_key,
            "reason": str(job.get("reason") or "latest"),
            "frame_index": int(job.get("frame_index", 0)),
            "timestamp": str(job.get("timestamp") or datetime.now(timezone.utc).isoformat()),
            "time_unix_s": float(job.get("time_unix_s") or time.time()),
            "color_image_path": str(color_path),
            "depth_visual_image_path": depth_visual_path,
            "raw_depth_image_path": str(raw_depth_path) if raw_depth_path else "",
            "color_space": "rgb",
            "image_shape": [int(color_u8.shape[0]), int(color_u8.shape[1]), int(color_u8.shape[2])],
            "depth_scale_m_per_unit": float(job.get("depth_scale") or 0.001),
            "camera_depth_scale_m_per_unit": {self.camera_key: float(job.get("depth_scale") or 0.001)},
            "depth_clip_min_mm": _env_float("ATR_LEROBOT_DEPTH_CLIP_MIN_MM", 0.0, minimum=0.0),
            "depth_clip_max_mm": _env_float("ATR_LEROBOT_DEPTH_CLIP_MAX_MM", 2000.0, minimum=1.0),
        }
        tmp_manifest_path = self._tmp_path_for(self.manifest_path, job)
        tmp_manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
        tmp_manifest_path.replace(self.manifest_path)
        self._last_write_monotonic = time.monotonic()
        return self.manifest_path

    def _latest_raw_depth_path(self) -> Path | None:
        root = Path(os.getenv("ATR_LEROBOT_RAW_DEPTH_DIR", str(self.root / "raw_depth"))).expanduser() / self.camera_key
        try:
            candidates = sorted(root.glob("frame_*.png"), key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError:
            return None
        return candidates[0] if candidates else None

    @contextmanager
    def raw_depth_capture_env(self) -> Iterator[None]:
        keys = ("ATR_LEROBOT_RAW_DEPTH_DIR", "ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS", "ATR_LEROBOT_RAW_DEPTH_FORMAT")
        previous = {key: os.environ.get(key) for key in keys}
        os.environ["ATR_LEROBOT_RAW_DEPTH_DIR"] = str(self.raw_depth_root)
        os.environ["ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS"] = self.camera_key
        os.environ["ATR_LEROBOT_RAW_DEPTH_FORMAT"] = "png16"
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class SpecimenPoseFrameUpdater:
    def __init__(self) -> None:
        self.enabled = _env_bool("ATR_SPECIMEN_POSE_RECORD_START_ENABLED", True)
        self.script_path = Path(
            os.getenv("ATR_SPECIMEN_POSE_FRAME_SCRIPT", str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"))
        ).expanduser()
        self.output_dir = Path(os.getenv("ATR_SPECIMEN_POSE_FRAME_OUTPUT_DIR", "/tmp/atr_specimen_pose_from_lerobot")).expanduser()
        # Allow detector process startup/CPU contention without changing pose,
        # freshness, motor movement, or return-to-home acceptance thresholds.
        self.timeout_s = _env_float("ATR_SPECIMEN_POSE_FRAME_TIMEOUT_S", 15.0, minimum=0.5)
        self.endpoint = self._specimen_endpoint(os.getenv("ATR_ISAAC_MIRROR_ENDPOINT", "http://127.0.0.1:8766/joints"))
        self.specimen_id = os.getenv("ATR_SPECIMEN_POSE_RECORD_SPECIMEN_ID", "redcube-record-start").strip() or "redcube-record-start"
        self.pending_path = Path(
            os.getenv("ATR_SPECIMEN_POSE_PENDING_PATH", "/tmp/atr_specimen_pose_pending/latest_specimen_pose_payload.json")
        ).expanduser()

    @staticmethod
    def _specimen_endpoint(joint_endpoint: str) -> str:
        endpoint = joint_endpoint.strip() or "http://127.0.0.1:8766/joints"
        if endpoint.endswith("/joints"):
            return endpoint[: -len("/joints")] + "/specimen_pose"
        return endpoint.rstrip("/") + "/specimen_pose"

    def update_from_manifest(
        self,
        manifest_path: Path,
        *,
        reason: str,
        pose_payload_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": True, "status": "disabled"}
        if not self.script_path.is_file():
            return {"ok": False, "failure_code": "SPECIMEN_POSE_FRAME_SCRIPT_NOT_FOUND", "message": str(self.script_path)}
        if not manifest_path.is_file():
            return {"ok": False, "failure_code": "LEROBOT_LATEST_FRAME_MISSING", "message": str(manifest_path)}
        payload = {
            "specimen_id": self.specimen_id,
            "frame_manifest_path": str(manifest_path),
            "output_dir": str(self.output_dir),
            "confidence_threshold": _env_float("ATR_SPECIMEN_POSE_FRAME_CONFIDENCE_THRESHOLD", 0.05, minimum=0.0),
            "autostart_realsense": False,
        }
        if pose_payload_overrides:
            payload.update(dict(pose_payload_overrides))
        try:
            completed = subprocess.run(
                [str(self.script_path), json.dumps(payload, ensure_ascii=True)],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "failure_code": "SPECIMEN_POSE_FRAME_TIMEOUT", "message": f"timeout after {self.timeout_s:.1f}s"}
        snapshot = self._json_object_from_stdout(completed.stdout)
        if not snapshot:
            return {
                "ok": False,
                "failure_code": "SPECIMEN_POSE_FRAME_OUTPUT_INVALID",
                "message": "frame detector did not return JSON",
                "stderr": completed.stderr,
            }
        if completed.returncode != 0 or not bool(snapshot.get("ok")):
            return {"ok": False, "failure_code": str(snapshot.get("failure_code") or "SPECIMEN_POSE_FRAME_FAILED"), "snapshot": snapshot}
        if not self._snapshot_has_world_position(snapshot):
            return {
                "ok": False,
                "failure_code": "SPECIMEN_POSE_FRAME_POSITION_MISSING",
                "message": "frame detector returned ok=true without pose.position_isaac_world_mm x/y/z",
                "snapshot": snapshot,
            }
        post_payload = {**snapshot, "reason": reason, "frame_manifest_path": str(manifest_path)}
        pending_path = self._write_pending_pose(post_payload)
        post_result = self._post_json(self.endpoint, post_payload)
        if not bool(post_result.get("ok", True)):
            return {
                "ok": True,
                "status": "pose_saved_pending_isaac",
                "snapshot": snapshot,
                "isaac_post": post_result,
                "pending_pose_path": str(pending_path),
            }
        return {
            "ok": True,
            "status": "pose_posted",
            "snapshot": snapshot,
            "isaac_post": post_result,
            "pending_pose_path": str(pending_path),
        }

    def _write_pending_pose(self, payload: dict[str, Any]) -> Path:
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending = {
            **payload,
            "pending_pose_path": str(self.pending_path),
            "pending_written_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp_path = self.pending_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(pending, ensure_ascii=True, indent=2), encoding="utf-8")
        tmp_path.replace(self.pending_path)
        return self.pending_path

    @staticmethod
    def _snapshot_has_world_position(snapshot: dict[str, Any]) -> bool:
        pose = snapshot.get("pose") if isinstance(snapshot.get("pose"), dict) else {}
        world_mm = pose.get("position_isaac_world_mm") if isinstance(pose.get("position_isaac_world_mm"), dict) else {}
        for axis in ("x", "y", "z"):
            try:
                float(world_mm.get(axis))
            except (TypeError, ValueError):
                return False
        return True

    @staticmethod
    def _json_object_from_stdout(stdout: str) -> dict[str, Any] | None:
        for line in reversed((stdout or "").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        request = Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=1.0) as response:
                body = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(body) if body else {}
                return {"ok": 200 <= response.status < 300, "status_code": response.status, "response": parsed}
        except Exception as exc:
            return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}


class ActiveRobotCamTracker:
    """Move the already-connected follower to a saved D405 pose and update specimen pose."""

    D405_DIRECT_OVERRIDES = {
        "camera_id": "active_robot_cam_d405",
        "a4_camera_to_isaac_transform": "direct",
        "a4_width_mm": 170.0,
        "a4_height_mm": 250.0,
        "a4_isaac_width_mm": 170.0,
        "a4_isaac_height_mm": 250.0,
        "a4_world_min_x_mm": 230.0,
        "a4_world_min_y_mm": 120.0,
    }
    D455F_RIGHT_PLANE_OVERRIDES = {
        "camera_id": "d455f_global",
        "a4_camera_to_isaac_transform": "robot_right_plane",
        "a4_width_mm": 250.0,
        "a4_height_mm": 170.0,
        "a4_isaac_width_mm": 170.0,
        "a4_isaac_height_mm": 250.0,
        "a4_world_min_x_mm": 230.0,
        "a4_world_min_y_mm": 120.0,
    }

    @staticmethod
    def _pose_overrides_with_world_offset(base: dict[str, Any], env_prefix: str) -> dict[str, Any]:
        overrides = dict(base)
        offset_x_name = f"{env_prefix}_A4_WORLD_OFFSET_X_MM"
        offset_y_name = f"{env_prefix}_A4_WORLD_OFFSET_Y_MM"
        if os.getenv(offset_x_name) is not None:
            overrides["a4_world_offset_x_mm"] = _env_float(offset_x_name, 0.0, minimum=-1000.0)
        if os.getenv(offset_y_name) is not None:
            overrides["a4_world_offset_y_mm"] = _env_float(offset_y_name, 0.0, minimum=-1000.0)
        return overrides

    def __init__(self, sidecar: LatestFrameSidecar, updater: SpecimenPoseFrameUpdater) -> None:
        self.enabled = _env_bool("ATR_ACTIVE_ROBOT_CAM_ENABLED", False)
        self.record_start_enabled = _env_bool("ATR_ACTIVE_ROBOT_CAM_RECORD_START_ENABLED", True)
        self.trigger_on_first_action = _env_bool("ATR_ACTIVE_ROBOT_CAM_TRIGGER_ON_FIRST_ACTION", True)
        self.fallback_enabled = _env_bool("ATR_ACTIVE_ROBOT_CAM_D455F_FALLBACK_ENABLED", True)
        self.camera_priority = [
            item.strip().lower()
            for item in os.getenv("ATR_ACTIVE_ROBOT_CAM_CAMERA_PRIORITY", "d405,d455f").split(",")
            if item.strip()
        ] or ["d405", "d455f"]
        self.resume_mode = os.getenv("ATR_ACTIVE_ROBOT_CAM_RESUME_MODE", "auto").strip().lower() or "auto"
        self.capture_pose_path = Path(
            os.getenv(
                "ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH",
                str(REPO_ROOT / "runs" / "active_robot_cam" / "latest_follower_capture_pose.json"),
            )
        ).expanduser()
        self.home_pose_path = Path(
            os.getenv(
                "ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH",
                str(REPO_ROOT / "runs" / "active_robot_cam" / "latest_follower_home_pose.json"),
            )
        ).expanduser()
        self.d455f_manifest_path = Path(
            os.getenv("ATR_ACTIVE_ROBOT_CAM_D455F_MANIFEST_PATH", "/tmp/atr_lerobot_latest_frame/latest_frame.json")
        ).expanduser()
        self.request_path = Path(
            os.getenv("ATR_ACTIVE_ROBOT_CAM_REQUEST_PATH", "/tmp/atr_active_robot_cam_request/request.json")
        ).expanduser()
        self.request_ttl_s = _env_float("ATR_ACTIVE_ROBOT_CAM_REQUEST_TTL_S", 15.0, minimum=0.0)
        self.result_dir = Path(
            os.getenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(REPO_ROOT / "runs" / "active_robot_cam"))
        ).expanduser()
        self.max_step = _env_float("ATR_ACTIVE_ROBOT_CAM_MAX_STEP", 5.0, minimum=0.1)
        self.min_steps = _env_int("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", 8, minimum=1)
        self.speed_scale = _env_float("ATR_ACTIVE_ROBOT_CAM_SPEED_SCALE", 0.7, minimum=0.05)
        self.resume_speed_scale = _env_float("ATR_ACTIVE_ROBOT_CAM_RESUME_SPEED_SCALE", 0.5, minimum=0.05)
        self.teleop_transition_max_step = _env_float("ATR_ACTIVE_ROBOT_CAM_TELEOP_TRANSITION_MAX_STEP", 3.0, minimum=0.1)
        self.resume_wait_timeout_s = _env_float("ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_TIMEOUT_S", 4.0, minimum=0.0)
        self.resume_wait_poll_s = _env_float("ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_POLL_S", 0.05, minimum=0.0)
        self.resume_wait_tolerance_deg = _env_float("ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_TOLERANCE_DEG", 5.0, minimum=0.0)
        self.capture_wait_timeout_s = _env_float("ATR_ACTIVE_ROBOT_CAM_CAPTURE_WAIT_TIMEOUT_S", 0.0, minimum=0.0)
        self.capture_wait_poll_s = _env_float(
            "ATR_ACTIVE_ROBOT_CAM_CAPTURE_WAIT_POLL_S",
            self.resume_wait_poll_s,
            minimum=0.0,
        )
        self.capture_wait_tolerance_deg = _env_float(
            "ATR_ACTIVE_ROBOT_CAM_CAPTURE_WAIT_TOLERANCE_DEG",
            self.resume_wait_tolerance_deg,
            minimum=0.0,
        )
        self.resume_wait_soft_tolerance_deg = _env_float(
            "ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_SOFT_TOLERANCE_DEG",
            max(3.0, self.resume_wait_tolerance_deg),
            minimum=0.0,
        )
        self.step_sleep_s = _env_float("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", 0.05, minimum=0.0)
        self.settle_s = _env_float("ATR_ACTIVE_ROBOT_CAM_SETTLE_S", 1.0, minimum=0.0)
        self.hold_after_capture_s = _env_float("ATR_ACTIVE_ROBOT_CAM_HOLD_AFTER_CAPTURE_S", 1.0, minimum=0.0)
        self.sidecar = sidecar
        self.updater = updater
        self._ran = False
        self._active = False
        self._hold_action: dict[str, float] = {}
        self._teleop_transition_action: dict[str, float] = {}

    def should_run_on_action(self) -> bool:
        return bool(
            self.enabled
            and self.trigger_on_first_action
            and not self._ran
            and not self._active
            and not self._pending_pose_exists()
        )

    def suppress_first_action_capture(self) -> None:
        if self.enabled:
            self._ran = True

    def held_action(self) -> dict[str, float]:
        return dict(self._hold_action)

    def clear_hold(self) -> None:
        self._hold_action = {}

    def present_action(self, robot: Any) -> dict[str, float]:
        return self._present_action(robot)

    def limit_teleop_action(self, target_action: dict[str, Any]) -> dict[str, float]:
        target = self._normalize_action(target_action)
        if not self._teleop_transition_action or not target:
            return target
        previous = self._normalize_action(self._teleop_transition_action)
        limited: dict[str, float] = {}
        complete = True
        for key, target_value in target.items():
            start_value = float(previous.get(key, target_value))
            delta = float(target_value) - start_value
            if abs(delta) > self.teleop_transition_max_step:
                limited[key] = start_value + math.copysign(self.teleop_transition_max_step, delta)
                complete = False
            else:
                limited[key] = float(target_value)
        if complete:
            self._teleop_transition_action = {}
        else:
            self._teleop_transition_action = dict(limited)
        return limited

    def _pending_pose_exists(self) -> bool:
        pending_path = getattr(self.updater, "pending_path", None)
        if pending_path is None:
            return False
        try:
            return Path(pending_path).expanduser().is_file()
        except TypeError:
            return False

    def consume_capture_request_reason(self) -> str:
        if not self.enabled or self._active or not self.request_path.is_file():
            return ""
        try:
            request = json.loads(self.request_path.read_text(encoding="utf-8"))
        except Exception:
            request = {}
        expired = self._request_expired(request) if isinstance(request, dict) else False
        try:
            self.request_path.unlink(missing_ok=True)
        except Exception:
            pass
        if expired:
            return ""
        raw_reason = request.get("reason") if isinstance(request, dict) else ""
        reason = str(raw_reason or "isaac_timeline").strip()
        return reason or "isaac_timeline"

    def _request_expired(self, request: dict[str, Any]) -> bool:
        now = time.time()
        try:
            expires_at = float(request.get("expires_at") or 0.0)
        except (TypeError, ValueError):
            expires_at = 0.0
        if expires_at > 0.0:
            return now > expires_at
        try:
            requested_at = float(request.get("requested_at") or 0.0)
        except (TypeError, ValueError):
            requested_at = 0.0
        return bool(self.request_ttl_s > 0.0 and requested_at > 0.0 and now > requested_at + self.request_ttl_s)

    def capture_once(
        self,
        robot: Any,
        *,
        send_action: Callable[[Any, dict[str, float]], dict[str, float]],
        current_action: dict[str, Any] | None = None,
        reason: str = "manual",
        force: bool = False,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": True, "status": "disabled"}
        if self._active:
            return {"ok": False, "status": "busy", "failure_code": "ACTIVE_ROBOT_CAM_BUSY"}
        if self._ran and not force:
            return {"ok": True, "status": "skipped", "reason": "already_ran"}
        self._active = True
        self._ran = True
        result: dict[str, Any] = {"ok": False, "status": "not_started"}
        fallback_used = False
        resume_action: dict[str, float] = {}
        capture_wait_result: dict[str, Any] = {}
        try:
            capture_action = self._load_pose_action(self.capture_pose_path)
            pre_capture_action = self._present_action(robot)
            self._move_to_action(robot, send_action, capture_action)
            capture_wait_result = self._wait_until_capture_pose_reached(robot, capture_action)
            if capture_wait_result and not capture_wait_result.get("ok"):
                result = {
                    "ok": False,
                    "status": "failed",
                    "failure_code": "ACTIVE_ROBOT_CAM_CAPTURE_POSE_NOT_REACHED",
                    "capture_wait": capture_wait_result,
                }
                resume_action = self._resume_action(current_action, pre_capture_action, resume_mode="home_pose")
                resume_waypoint_action = self._move_through_resume_waypoint(robot, send_action, resume_action)
                if resume_action:
                    self._move_to_action(robot, send_action, resume_action, speed_scale=self.resume_speed_scale)
                self._hold_action = {}
                self._teleop_transition_action = dict(resume_action)
                result["resume_mode"] = "home_pose"
                result["resume_action"] = dict(resume_action)
                result["resume_waypoint_action"] = dict(resume_waypoint_action)
                result["resume_speed_scale"] = self.resume_speed_scale
                self._write_result(result)
                return result
            if self.settle_s > 0:
                time.sleep(self.settle_s)

            d405_manifest_path: Path | None = None
            if "d405" in self.camera_priority:
                raw_depth_capture_env = getattr(self.sidecar, "raw_depth_capture_env", None)
                capture_context = raw_depth_capture_env() if callable(raw_depth_capture_env) else nullcontext()
                with capture_context:
                    observation = robot.get_observation()
                d405_depth_scale = self._camera_depth_scale_m_per_unit(
                    robot,
                    self.sidecar.camera_key,
                    default=_env_float("ATR_ACTIVE_ROBOT_CAM_D405_DEPTH_SCALE_M_PER_UNIT", 0.0001, minimum=0.0),
                )
                d405_manifest_path = self.sidecar.write_observation(
                    observation,
                    force=True,
                    reason=f"active_robot_cam_{reason}",
                    depth_scale_m_per_unit=d405_depth_scale,
                )

            attempts: list[dict[str, Any]] = []
            for camera in self.camera_priority:
                if camera == "d405":
                    if d405_manifest_path is None:
                        continue
                    attempt = self.updater.update_from_manifest(
                        d405_manifest_path,
                        reason="active_robot_cam_d405",
                        pose_payload_overrides=self._pose_overrides_with_world_offset(
                            self.D405_DIRECT_OVERRIDES,
                            "ATR_ACTIVE_ROBOT_CAM_D405",
                        ),
                    )
                elif camera in {"d455f", "d455", "top"}:
                    if not self.fallback_enabled or not self.d455f_manifest_path.is_file():
                        continue
                    fallback_used = True
                    attempt = self.updater.update_from_manifest(
                        self.d455f_manifest_path,
                        reason="active_robot_cam_d455f_fallback",
                        pose_payload_overrides=self._pose_overrides_with_world_offset(
                            self.D455F_RIGHT_PLANE_OVERRIDES,
                            "ATR_ACTIVE_ROBOT_CAM_D455F",
                        ),
                    )
                else:
                    continue
                attempts.append({"camera": camera, "result": attempt})
                if attempt.get("ok"):
                    result = {
                        "ok": True,
                        "status": "applied",
                        "camera": camera,
                        "fallback_used": fallback_used and camera != "d405",
                        "attempts": attempts,
                    }
                    break
            if not result.get("ok"):
                result = {
                    "ok": False,
                    "status": "failed",
                    "failure_code": "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED",
                    "fallback_used": fallback_used,
                    "attempts": attempts,
                }
            if self.hold_after_capture_s > 0:
                time.sleep(self.hold_after_capture_s)
            resume_mode = self._resolved_resume_mode(current_action, capture_ok=bool(result.get("ok")))
            resume_action = self._resume_action(current_action, pre_capture_action, resume_mode=resume_mode)
            resume_waypoint_action = self._move_through_resume_waypoint(robot, send_action, resume_action)
            if resume_action:
                self._move_to_action(robot, send_action, resume_action, speed_scale=self.resume_speed_scale)
            if result.get("ok"):
                self._hold_action = {}
                self._teleop_transition_action = dict(resume_action)
            elif resume_action:
                self._hold_action = {}
                self._teleop_transition_action = dict(resume_action)
            if capture_wait_result:
                result["capture_wait"] = dict(capture_wait_result)
            result["resume_mode"] = resume_mode
            result["resume_action"] = dict(resume_action)
            result["resume_waypoint_action"] = dict(resume_waypoint_action)
            result["resume_speed_scale"] = self.resume_speed_scale
            self._write_result(result)
            return result
        except Exception as exc:
            resume_action = self._home_action_after_failure(robot, send_action)
            if resume_action:
                self._hold_action = {}
                self._teleop_transition_action = dict(resume_action)
            result = {
                "ok": False,
                "status": "failed",
                "failure_code": "ACTIVE_ROBOT_CAM_ERROR",
                "message": f"{exc.__class__.__name__}: {exc}",
                "resume_mode": "home_pose",
                "resume_action": dict(resume_action),
                "resume_waypoint_action": self._resume_waypoint_action(resume_action),
            }
            self._write_result(result)
            return result
        finally:
            self._active = False

    def _resolved_resume_mode(self, current_action: dict[str, Any] | None, *, capture_ok: bool = True) -> str:
        if not capture_ok:
            return "home_pose"
        if self.resume_mode == "auto":
            return "leader_current" if current_action else "home_pose"
        return self.resume_mode

    def _resume_action(
        self,
        current_action: dict[str, Any] | None,
        pre_capture_action: dict[str, float],
        *,
        resume_mode: str | None = None,
    ) -> dict[str, float]:
        mode = resume_mode or self._resolved_resume_mode(current_action)
        if mode in {"leader_current", "teleop", "current"} and current_action:
            return self._normalize_action(current_action)
        if mode in {"pre_capture", "previous"}:
            return pre_capture_action
        if mode in {"home", "home_pose", "origin"}:
            return self._load_pose_action(self.home_pose_path)
        if current_action:
            return self._normalize_action(current_action)
        return self._load_pose_action(self.home_pose_path)

    def _wait_until_capture_pose_reached(self, robot: Any, capture_action: dict[str, Any]) -> dict[str, Any]:
        if self.capture_wait_timeout_s <= 0:
            return {"ok": True, "status": "disabled", "reason": "active_cam_capture_pose"}
        return self.wait_until_action_reached(
            robot,
            capture_action,
            reason="active_cam_capture_pose",
            timeout_s=self.capture_wait_timeout_s,
            poll_s=self.capture_wait_poll_s,
            tolerance_deg=self.capture_wait_tolerance_deg,
            failure_code="ACTIVE_ROBOT_CAM_CAPTURE_POSE_NOT_REACHED",
        )

    def _resume_waypoint_action(self, home_action: dict[str, float] | None = None) -> dict[str, float]:
        action = dict(home_action) if home_action is not None else self._load_pose_action(self.home_pose_path)
        if "wrist_flex.pos" not in action:
            return {}
        action["wrist_flex.pos"] = 0.0
        return action

    def _move_through_resume_waypoint(
        self,
        robot: Any,
        send_action: Callable[[Any, dict[str, float]], dict[str, float]],
        resume_action: dict[str, float],
    ) -> dict[str, float]:
        try:
            waypoint_action = self._resume_waypoint_action()
        except Exception:
            return {}
        if not waypoint_action or waypoint_action == resume_action:
            return {}
        self._move_to_action(robot, send_action, waypoint_action, speed_scale=self.resume_speed_scale)
        return waypoint_action

    def _home_action_after_failure(
        self,
        robot: Any,
        send_action: Callable[[Any, dict[str, float]], dict[str, float]],
    ) -> dict[str, float]:
        try:
            resume_action = self._load_pose_action(self.home_pose_path)
        except Exception:
            return {}
        if resume_action:
            waypoint_action = self._resume_waypoint_action(resume_action)
            if waypoint_action and waypoint_action != resume_action:
                self._move_to_action(robot, send_action, waypoint_action, speed_scale=self.resume_speed_scale)
            self._move_to_action(robot, send_action, resume_action, speed_scale=self.resume_speed_scale)
        return resume_action

    def _move_to_action(
        self,
        robot: Any,
        send_action: Callable[[Any, dict[str, float]], dict[str, float]],
        target_action: dict[str, float],
        *,
        speed_scale: float | None = None,
    ) -> None:
        if not target_action:
            return
        start_action = self._present_action(robot)
        keys = list(dict.fromkeys([*start_action.keys(), *target_action.keys()]))
        max_delta = max((abs(float(target_action.get(key, start_action.get(key, 0.0))) - float(start_action.get(key, 0.0))) for key in keys), default=0.0)
        steps = max(self.min_steps, int(max_delta / self.max_step) + 1)
        scale = self.speed_scale if speed_scale is None else max(0.05, float(speed_scale))
        steps = max(1, int(math.ceil(steps / scale)))
        for step in range(1, steps + 1):
            linear_alpha = step / steps
            alpha = 0.5 - 0.5 * math.cos(math.pi * linear_alpha)
            action = {}
            for key in keys:
                if key not in target_action:
                    continue
                start = float(start_action.get(key, target_action[key]))
                target = float(target_action[key])
                action[key] = start + (target - start) * alpha
            send_action(robot, action)
            if self.step_sleep_s > 0:
                time.sleep(self.step_sleep_s)

    def _present_action(self, robot: Any) -> dict[str, float]:
        try:
            present = robot.bus.sync_read("Present_Position")
        except Exception:
            return {}
        return {f"{str(key).removesuffix('.pos')}.pos": float(value) for key, value in dict(present).items()}

    def wait_until_action_reached(
        self,
        robot: Any,
        target_action: dict[str, Any],
        *,
        reason: str,
        timeout_s: float | None = None,
        poll_s: float | None = None,
        tolerance_deg: float | None = None,
        failure_code: str = "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED",
    ) -> dict[str, Any]:
        target = self._normalize_action(target_action)
        if not target:
            return {"ok": True, "status": "no_target", "reason": reason}
        timeout = self.resume_wait_timeout_s if timeout_s is None else max(0.0, float(timeout_s))
        poll = self.resume_wait_poll_s if poll_s is None else max(0.0, float(poll_s))
        tolerance = self.resume_wait_tolerance_deg if tolerance_deg is None else max(0.0, float(tolerance_deg))
        deadline = time.monotonic() + timeout
        best_error = float("inf")
        latest_action: dict[str, float] = {}
        while True:
            latest_action = self.present_action(robot)
            errors = [abs(float(latest_action.get(key, float("inf"))) - float(value)) for key, value in target.items()]
            max_error = max(errors, default=0.0)
            best_error = min(best_error, max_error)
            if errors and max_error <= tolerance:
                return {
                    "ok": True,
                    "status": "reached",
                    "reason": reason,
                    "max_error_deg": round(max_error, 4),
                    "target_action": target,
                    "current_action": latest_action,
                }
            if time.monotonic() >= deadline:
                return {
                    "ok": False,
                    "status": "timeout",
                    "failure_code": failure_code,
                    "reason": reason,
                    "max_error_deg": round(best_error, 4) if math.isfinite(best_error) else None,
                    "tolerance_deg": tolerance,
                    "target_action": target,
                    "current_action": latest_action,
                }
            if poll > 0:
                time.sleep(poll)

    @staticmethod
    def _camera_depth_scale_m_per_unit(robot: Any, camera_key: str, *, default: float) -> float:
        cameras = getattr(robot, "cameras", {})
        camera = cameras.get(camera_key) if isinstance(cameras, dict) else None
        for candidate in (
            ActiveRobotCamTracker._sdk_depth_scale_m_per_unit(camera),
            getattr(camera, "depth_scale_m_per_unit", None),
        ):
            try:
                value = float(candidate)
            except (TypeError, ValueError):
                continue
            if value > 0.0:
                return value
        return default

    @staticmethod
    def _sdk_depth_scale_m_per_unit(camera: Any) -> float | None:
        profile = getattr(camera, "rs_profile", None)
        if profile is None:
            return None
        try:
            device = profile.get_device()
            sensor = device.first_depth_sensor()
            return float(sensor.get_depth_scale())
        except Exception:
            return None

    def _load_pose_action(self, path: Path) -> dict[str, float]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        raw = data.get("present_position_lerobot") if isinstance(data, dict) else {}
        if not isinstance(raw, dict) or not raw:
            raise ValueError(f"pose file has no present_position_lerobot: {path}")
        return self._normalize_action(raw)

    @staticmethod
    def _normalize_action(raw: dict[str, Any]) -> dict[str, float]:
        action: dict[str, float] = {}
        for key, value in dict(raw).items():
            name = str(key)
            if not name.endswith(".pos"):
                name = f"{name}.pos"
            action[name] = float(value)
        return action

    def _write_result(self, result: dict[str, Any]) -> None:
        try:
            self.result_dir.mkdir(parents=True, exist_ok=True)
            path = self.result_dir / "latest_active_robot_cam_result.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            pass


def patch_omx_observation(sidecar: LatestFrameSidecar) -> None:
    if not sidecar.enabled:
        return
    from lerobot.robots.omx_follower.omx_follower import OmxFollower

    if getattr(OmxFollower, "_atr_latest_frame_patched", False):
        return
    original_get_observation = OmxFollower.get_observation

    def mirrored_get_observation(self):  # type: ignore[no-untyped-def]
        observation = original_get_observation(self)
        present_action: dict[str, float] = {}
        for key, value in dict(observation).items():
            if not str(key).endswith(".pos"):
                continue
            try:
                present_action[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        if present_action:
            self._atr_latest_present_position_action = present_action
        depth_scale = ActiveRobotCamTracker._camera_depth_scale_m_per_unit(
            self,
            sidecar.camera_key,
            default=_env_float("ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT", 0.001, minimum=0.0),
        )
        sidecar.write_observation(observation, depth_scale_m_per_unit=depth_scale)
        return observation

    OmxFollower.get_observation = mirrored_get_observation
    OmxFollower._atr_latest_frame_patched = True


def patch_omx_send_action(publisher: IsaacMirrorPublisher, active_robot_cam: ActiveRobotCamTracker | None = None) -> None:
    active_enabled = bool(active_robot_cam and active_robot_cam.enabled)
    if not publisher.enabled and not active_enabled:
        return
    from lerobot.robots.omx_follower.omx_follower import OmxFollower

    original_send_action = OmxFollower.send_action

    def _held_action_from_active_cam(result: dict[str, Any] | None = None) -> dict[str, float]:
        if active_robot_cam is not None:
            held_action = getattr(active_robot_cam, "held_action", None)
            if callable(held_action):
                try:
                    held = held_action()
                    if isinstance(held, dict) and held:
                        return ActiveRobotCamTracker._normalize_action(held)
                except Exception:
                    pass
        if isinstance(result, dict) and isinstance(result.get("resume_action"), dict):
            return ActiveRobotCamTracker._normalize_action(result["resume_action"])
        return {}

    def mirrored_send_action(self, action):  # type: ignore[no-untyped-def]
        if active_robot_cam is not None and bool(getattr(active_robot_cam, "_active", False)):
            return original_send_action(self, action)
        leader_action_for_mirror = dict(action)
        request_reason = active_robot_cam.consume_capture_request_reason() if active_robot_cam is not None else ""
        if active_robot_cam is not None and (request_reason or active_robot_cam.should_run_on_action()):
            capture_result = active_robot_cam.capture_once(
                self,
                send_action=original_send_action,
                current_action=dict(action),
                reason=request_reason or "teleop",
                force=bool(request_reason),
            )
            held_action = _held_action_from_active_cam(capture_result)
            resume_action = _held_action_from_active_cam(capture_result)
            if held_action and not bool(capture_result.get("ok")):
                clear_hold = getattr(active_robot_cam, "clear_hold", None)
                if callable(clear_hold):
                    clear_hold()
                sent_action = held_action
            else:
                sent_action = resume_action or dict(action)
        else:
            held_action = _held_action_from_active_cam() if active_robot_cam is not None else {}
            if held_action:
                outgoing_action = held_action
            elif active_robot_cam is not None:
                outgoing_action = active_robot_cam.limit_teleop_action(dict(action))
            else:
                outgoing_action = dict(action)
            sent_action = original_send_action(self, outgoing_action)
        if publisher.should_publish():
            mirror_action, source, source_error, source_selection = publisher.action_from_follower(
                self,
                sent_action,
                leader_action=leader_action_for_mirror,
            )
            publisher.publish_action(mirror_action, source=source, source_error=source_error, source_selection=source_selection)
        return sent_action

    OmxFollower.send_action = mirrored_send_action


def patch_record_loop(
    sidecar: LatestFrameSidecar,
    updater: SpecimenPoseFrameUpdater,
    active_robot_cam: ActiveRobotCamTracker | None = None,
    attempt_sidecar: RecordAttemptSidecar | None = None,
    *,
    publisher: IsaacMirrorPublisher | None = None,
) -> None:
    attempt_enabled = bool(attempt_sidecar and attempt_sidecar.enabled)
    publisher_enabled = bool(publisher and publisher.enabled)
    preflight_available = bool(updater.enabled or (active_robot_cam and active_robot_cam.enabled))
    if not (sidecar.enabled or attempt_enabled or publisher_enabled) or (not preflight_available and not publisher_enabled):
        return
    import lerobot.record as record_module

    if getattr(record_module, "_atr_record_start_frame_patched", False):
        return
    original_record_loop = record_module.record_loop

    def _record_loop_context(
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[Any | None, Any | None, Any | None, bool]:
        robot = kwargs.get("robot")
        dataset = kwargs.get("dataset")
        events = kwargs.get("events")
        display_data = kwargs.get("display_data")
        try:
            bound = inspect.signature(original_record_loop).bind_partial(*args, **kwargs)
        except (TypeError, ValueError):
            return (
                robot if robot is not None else (args[0] if args else None),
                dataset,
                events if events is not None else (args[1] if len(args) > 1 else None),
                _display_data_enabled(display_data if display_data is not None else (args[8] if len(args) > 8 else False)),
            )
        robot = bound.arguments.get("robot", robot)
        dataset = bound.arguments.get("dataset", dataset)
        events = bound.arguments.get("events", events)
        display_data = bound.arguments.get("display_data", display_data)
        varargs = bound.arguments.get("args")
        varkwargs = bound.arguments.get("kwargs")
        if isinstance(varkwargs, dict):
            robot = varkwargs.get("robot", robot)
            dataset = varkwargs.get("dataset", dataset)
            events = varkwargs.get("events", events)
            display_data = varkwargs.get("display_data", display_data)
        if robot is None and isinstance(varargs, tuple) and varargs:
            robot = varargs[0]
        if events is None and isinstance(varargs, tuple) and len(varargs) > 1:
            events = varargs[1]
        if dataset is None and isinstance(varargs, tuple):
            if len(varargs) >= 7:
                dataset = varargs[6]
            elif len(varargs) == 4:
                dataset = varargs[3]
        if display_data is None and isinstance(varargs, tuple) and len(varargs) > 8:
            display_data = varargs[8]
        return robot, dataset, events, _display_data_enabled(display_data)

    def _display_data_enabled(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _episode_index_for_dataset(dataset: Any) -> int:
        try:
            return max(0, int(getattr(dataset, "num_episodes", 0)))
        except (TypeError, ValueError):
            return 0

    class RecordStartPreflightError(RuntimeError):
        pass

    def _record_start_preflight_error(result: Any) -> RecordStartPreflightError:
        failure_code = "RECORD_START_PREFLIGHT_FAILED"
        message = ""
        if isinstance(result, dict):
            failure_code = str(result.get("failure_code") or failure_code)
            message = str(result.get("message") or result.get("status") or failure_code)
        else:
            message = str(result)
        return RecordStartPreflightError(f"{failure_code}: {message}")

    def _collection_scope(enabled: bool, *, reason: str) -> Iterator[None]:
        if publisher is not None and hasattr(publisher, "collection_scope"):
            return publisher.collection_scope(enabled, reason=reason)
        return nullcontext()

    def _publish_scope(enabled: bool, *, reason: str) -> Iterator[None]:
        if publisher is not None and hasattr(publisher, "publish_scope"):
            return publisher.publish_scope(enabled, reason=reason)
        return nullcontext()

    def _reset_collection_frame_context() -> None:
        if publisher is not None and hasattr(publisher, "reset_collection_frame_context"):
            publisher.reset_collection_frame_context()

    def _flush_collection() -> None:
        if publisher is not None and hasattr(publisher, "flush"):
            publisher.flush(timeout_s=2.0)

    def _events_request_rerecord(events: Any) -> bool:
        return bool(isinstance(events, dict) and events.get("rerecord_episode"))

    def _discard_rejected_attempt(episode_index: int) -> None:
        if publisher is None or not hasattr(publisher, "discard_collection_for_attempt"):
            return
        attempt_id = ""
        if attempt_sidecar is not None:
            attempt_id = str(getattr(attempt_sidecar, "attempt_id", "") or "")
        if not attempt_id:
            attempt_id = os.getenv("ATR_RECORD_ATTEMPT_ID", "").strip()
        if attempt_id:
            publisher.discard_collection_for_attempt(attempt_id=attempt_id, episode_index=episode_index)

    def _resume_wait_failure_is_soft(wait_result: dict[str, Any]) -> tuple[bool, float | None]:
        if str(wait_result.get("failure_code") or "") != "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED":
            return False, None
        soft_tolerance = getattr(active_robot_cam, "resume_wait_soft_tolerance_deg", None)
        try:
            soft_tolerance_float = float(soft_tolerance)
            max_error = float(wait_result.get("max_error_deg"))
        except (TypeError, ValueError):
            return False, None
        return max_error <= soft_tolerance_float, soft_tolerance_float

    def _active_cam_specimen_pose_failure_is_soft(result: dict[str, Any]) -> bool:
        return str(result.get("failure_code") or "") == "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED"

    rerun_blueprint_sent = False

    def _send_recording_rerun_blueprint(*, display_data: bool) -> None:
        nonlocal rerun_blueprint_sent
        if not display_data or rerun_blueprint_sent:
            return
        try:
            import rerun as rr
            import rerun.blueprint as rrb
        except Exception:
            return
        try:
            blueprint = rrb.Blueprint(
                rrb.Vertical(
                    rrb.Horizontal(
                        rrb.Spatial2DView(origin="observation.top", name="observation.top"),
                        rrb.Spatial2DView(origin="observation.wrist", name="observation.wrist"),
                        column_shares=[1.0, 1.0],
                    ),
                    rrb.Horizontal(
                        rrb.Spatial2DView(origin="observation.top_depth", name="observation.top_depth"),
                        rrb.Spatial2DView(origin="observation.wrist_depth", name="observation.wrist_depth"),
                        column_shares=[1.0, 1.0],
                    ),
                    rrb.TimeSeriesView(origin="/", name="state_action"),
                    row_shares=[3.0, 2.0, 2.0],
                ),
                auto_layout=False,
                auto_views=False,
                collapse_panels=False,
            )
            rr.send_blueprint(blueprint, make_active=True, make_default=True)
        except Exception:
            return
        rerun_blueprint_sent = True

    def _seed_rerun_observation(robot: Any, action: dict[str, Any], *, display_data: bool) -> None:
        if not display_data or robot is None:
            return
        log_rerun_data = getattr(record_module, "log_rerun_data", None)
        if not callable(log_rerun_data):
            return
        try:
            observation = robot.get_observation()
        except Exception:
            return
        if not isinstance(observation, dict):
            return
        try:
            log_rerun_data(observation, dict(action))
        except Exception:
            return

    def _post_record_start_timeline_play() -> dict[str, Any] | None:
        if not _env_bool("ATR_ISAAC_TIMELINE_PLAY_RECORD_START_ENABLED", False):
            return None
        endpoint = str(getattr(publisher, "endpoint", "") or os.getenv("ATR_ISAAC_MIRROR_ENDPOINT", "")).strip()
        if not endpoint:
            return None
        play_url = _isaac_mirror_timeline_play_url(endpoint)
        payload = {"reason": "record_start"}
        data = json.dumps(payload).encode("utf-8")
        request = Request(play_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        timeout_s = _env_capped_post_timeout(
            "ATR_ISAAC_TIMELINE_PLAY_POST_TIMEOUT_S",
            "ATR_ISAAC_MIRROR_POST_TIMEOUT_S",
            DEFAULT_ISAAC_MIRROR_POST_TIMEOUT_S,
            1.0,
        )
        try:
            with urlopen(request, timeout=timeout_s) as response:
                body = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(body) if body else {}
                return {
                    "ok": 200 <= response.status < 300,
                    "status_code": response.status,
                    "timeline_play_url": play_url,
                    "response": parsed,
                }
        except Exception as exc:
            return {
                "ok": False,
                "status_code": None,
                "timeline_play_url": play_url,
                "message": f"{exc.__class__.__name__}: {exc}",
            }

    def record_loop_with_specimen_frame(*args, **kwargs):  # type: ignore[no-untyped-def]
        robot, dataset, events, display_data = _record_loop_context(args, kwargs)
        if dataset is None:
            with _collection_scope(False, reason="reset"):
                with _publish_scope(False, reason="record_reset"):
                    return original_record_loop(*args, **kwargs)

        episode_index = _episode_index_for_dataset(dataset)
        blocking_preflight = bool(active_robot_cam is not None and active_robot_cam.enabled and active_robot_cam.record_start_enabled)
        passive_preflight = bool(sidecar.enabled and updater.enabled)
        if robot is not None and (blocking_preflight or passive_preflight):
            try:
                if attempt_sidecar is not None:
                    attempt_sidecar.begin_episode(episode_index=episode_index, reason="record_start")
                with _collection_scope(False, reason="record_start_preflight"):
                    if blocking_preflight:
                        with _publish_scope(False, reason="active_robot_cam_preflight"):
                            current_action_reader = getattr(active_robot_cam, "present_action", None)
                            record_start_action = current_action_reader(robot) if callable(current_action_reader) else {}
                            _send_recording_rerun_blueprint(display_data=display_data)
                            _seed_rerun_observation(robot, record_start_action, display_data=display_data)
                            result = active_robot_cam.capture_once(
                                robot,
                                send_action=lambda active_robot, action: active_robot.send_action(action),
                                current_action=record_start_action,
                                reason="record_start",
                                force=True,
                            )
                        if isinstance(result, dict) and bool(result.get("ok", True)):
                            resume_action = (
                                result.get("resume_action")
                                if isinstance(result.get("resume_action"), dict)
                                else record_start_action
                            )
                            wait_until_action_reached = getattr(active_robot_cam, "wait_until_action_reached", None)
                            wait_result = (
                                wait_until_action_reached(robot, resume_action, reason="record_start")
                                if callable(wait_until_action_reached)
                                else {"ok": True, "status": "unsupported"}
                            )
                            result["resume_wait"] = wait_result
                            if isinstance(wait_result, dict) and not bool(wait_result.get("ok", True)):
                                soft_ok, soft_tolerance = _resume_wait_failure_is_soft(wait_result)
                                if soft_ok:
                                    result = {
                                        **result,
                                        "ok": True,
                                        "warning_only": True,
                                        "resume_wait": wait_result,
                                        "resume_wait_soft_tolerance_deg": soft_tolerance,
                                    }
                                else:
                                    result = {
                                        **result,
                                        "ok": False,
                                        "failure_code": str(
                                            wait_result.get("failure_code")
                                            or "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED"
                                        ),
                                        "resume_wait": wait_result,
                                    }
                    else:
                        if active_robot_cam is not None and hasattr(active_robot_cam, "suppress_first_action_capture"):
                            active_robot_cam.suppress_first_action_capture()
                        observation = robot.get_observation()
                        manifest_path = sidecar.write_observation(observation, force=True, reason="record_start")
                        result = updater.update_from_manifest(manifest_path, reason="record_start")
                if isinstance(result, dict) and not bool(result.get("ok", True)):
                    if not blocking_preflight or _active_cam_specimen_pose_failure_is_soft(result):
                        result = {**result, "warning_only": True}
                sidecar.root.mkdir(parents=True, exist_ok=True)
                result_path = sidecar.root / "record_start_specimen_pose_result.json"
                result_path.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
                if attempt_sidecar is not None:
                    attempt_sidecar.write_active_cam_result(result)
                if (
                    blocking_preflight
                    and isinstance(result, dict)
                    and not bool(result.get("ok", True))
                    and not bool(result.get("warning_only"))
                ):
                    raise _record_start_preflight_error(result)
            except RecordStartPreflightError:
                raise
            except Exception as exc:
                result = {
                    "ok": False,
                    "failure_code": "SPECIMEN_POSE_RECORD_START_ERROR",
                    "message": f"{exc.__class__.__name__}: {exc}",
                }
                if not blocking_preflight:
                    result["warning_only"] = True
                sidecar.root.mkdir(parents=True, exist_ok=True)
                (sidecar.root / "record_start_specimen_pose_result.json").write_text(
                    json.dumps(result, ensure_ascii=True),
                    encoding="utf-8",
                )
                if blocking_preflight:
                    raise _record_start_preflight_error(result) from exc
        timeline_play_result = _post_record_start_timeline_play()
        if timeline_play_result is not None and sidecar.enabled:
            sidecar.root.mkdir(parents=True, exist_ok=True)
            (sidecar.root / "record_start_isaac_timeline_play_result.json").write_text(
                json.dumps(timeline_play_result, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
        _reset_collection_frame_context()
        with _collection_scope(True, reason="record_episode"):
            loop_result = original_record_loop(*args, **kwargs)
        _flush_collection()
        if _events_request_rerecord(events):
            _discard_rejected_attempt(episode_index)
        return loop_result

    record_module.record_loop = record_loop_with_specimen_frame
    record_module._atr_record_start_frame_patched = True


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"teleoperate", "record"}:
        raise SystemExit("usage: lerobot_isaac_mirror_runtime_wrapper.py {teleoperate|record} [lerobot args...]")
    workflow = sys.argv[1]
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    sidecar = LatestFrameSidecar()
    updater = SpecimenPoseFrameUpdater()
    publisher = IsaacMirrorPublisher()
    active_robot_cam = ActiveRobotCamTracker(sidecar, updater)
    attempt_sidecar = RecordAttemptSidecar()
    patch_omx_observation(sidecar)
    patch_omx_send_action(publisher, active_robot_cam)
    if workflow == "teleoperate":
        from lerobot.teleoperate import main as lerobot_main
    else:
        import lerobot.record as record_module

        patch_record_loop(sidecar, updater, active_robot_cam, attempt_sidecar, publisher=publisher)
        lerobot_main = record_module.main
    try:
        lerobot_main()
    finally:
        flush_timeout_s = _env_float("ATR_ISAAC_RGBD_RENDER_FLUSH_TIMEOUT_S", 120.0, minimum=0.0)
        publisher.flush(timeout_s=flush_timeout_s)
        sidecar.flush(timeout_s=2.0)


if __name__ == "__main__":
    main()
