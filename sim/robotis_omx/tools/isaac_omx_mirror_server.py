#!/usr/bin/env python3
"""HTTP bridge for mirroring ROBOTIS OMX follower joint state into Isaac Sim.

Run this inside Isaac Sim Python when the GUI stage is open, or with Isaac Sim's
python.sh against a USD file for offline target updates. The ATR LeRobot bridge
POSTs follower joint samples to /joints.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
DEFAULT_SCENE = Path(__file__).resolve().parents[1] / "scene" / "omx_table_layout.usda"
LATEST_STATE_PATH = Path("/tmp/atr_isaac_omx_mirror_latest.json")


def _load_usd_modules() -> tuple[Any, Any, Any]:
    try:
        from pxr import Usd, UsdPhysics, UsdGeom  # type: ignore
    except Exception:
        return None, None, None
    return Usd, UsdPhysics, UsdGeom


def _current_isaac_stage() -> Any:
    try:
        import omni.usd  # type: ignore

        return omni.usd.get_context().get_stage()
    except Exception:
        return None


def _joint_targets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for item in payload.get("joint_state") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("isaac_joint_path") or "").strip()
        if not path:
            continue
        value = item.get("target_value", item.get("position_deg", 0.0))
        try:
            target_value = float(value)
        except (TypeError, ValueError):
            target_value = 0.0
        targets.append(
            {
                "path": path,
                "mimic_path": str(item.get("mimic_joint_path") or "").strip(),
                "name": str(item.get("isaac_joint_name") or ""),
                "motor_id": item.get("motor_id"),
                "target_value": target_value,
                "unit": str(item.get("unit") or "deg"),
            }
        )
    return targets


class IsaacMirrorState:
    def __init__(
        self,
        scene_path: Path,
        *,
        use_current_stage: bool = True,
        defer_apply: bool = False,
        stage_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.scene_path = scene_path
        self.use_current_stage = use_current_stage
        self.defer_apply = defer_apply
        self.stage_provider = stage_provider
        self.lock = threading.Lock()
        self.last_payload: dict[str, Any] = {}
        self.pending_payload: dict[str, Any] | None = None
        self.last_apply_result: dict[str, Any] = {}
        self.last_error = ""
        self.last_scene_open_status = ""
        self.scene_open_request_count = 0
        self._last_scene_open_attempt_s = 0.0
        self.sample_count = 0
        self.stage = None

    def stage_or_open(self) -> Any:
        if self.stage_provider is not None:
            stage = self.stage_provider()
            if stage is not None:
                self.stage = stage
                return stage
        if self.use_current_stage:
            stage = _current_isaac_stage()
            if stage is not None:
                self.stage = stage
                return stage
        if self.stage is not None:
            return self.stage
        Usd, _UsdPhysics, _UsdGeom = _load_usd_modules()
        if Usd is None:
            return None
        self.stage = Usd.Stage.Open(str(self.scene_path))
        return self.stage

    def receive(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Accept a mirror sample from HTTP; apply now or queue for Isaac's update tick."""
        if not self.defer_apply:
            return self.apply(payload)
        with self.lock:
            self.sample_count += 1
            self.last_payload = self._received_payload(payload)
            self.pending_payload = dict(self.last_payload)
            self._write_latest_state(self.last_payload)
            return {
                "ok": True,
                "status": "queued",
                "sample_count": self.sample_count,
                "target_count": len(_joint_targets(payload)),
                "latest_state_path": str(LATEST_STATE_PATH),
            }

    def apply_latest_pending(self) -> dict[str, Any]:
        """Apply the most recent queued sample. Intended for Isaac Kit update callbacks."""
        with self.lock:
            payload = dict(self.pending_payload or {})
            self.pending_payload = None
        if not payload:
            return {
                "ok": True,
                "status": "idle",
                "sample_count": self.sample_count,
                "target_count": 0,
                "latest_state_path": str(LATEST_STATE_PATH),
            }
        return self.apply(payload, record_received=False)

    def apply(self, payload: dict[str, Any], *, record_received: bool = True) -> dict[str, Any]:
        targets = _joint_targets(payload)
        with self.lock:
            if record_received:
                self.sample_count += 1
                self.last_payload = self._received_payload(payload)
                self._write_latest_state(self.last_payload)
            else:
                self.last_payload = dict(payload)
            stage = self.stage_or_open()
            if stage is None:
                self.last_error = "pxr/omni stage unavailable; latest JSON state was written only"
                self.last_apply_result = {
                    "ok": False,
                    "status": "stage_unavailable",
                    "message": self.last_error,
                    "sample_count": self.sample_count,
                    "target_count": len(targets),
                    "latest_state_path": str(LATEST_STATE_PATH),
                }
                return dict(self.last_apply_result)
            stage_summary = self._stage_summary(stage)
            applied = []
            missing = []
            for target in targets:
                if self._apply_joint_target(stage, target):
                    applied.append(target["path"])
                else:
                    missing.append(target["path"])
                mimic_path = target.get("mimic_path") or ""
                if mimic_path:
                    mimic = {**target, "path": mimic_path}
                    if self._apply_joint_target(stage, mimic):
                        applied.append(mimic_path)
                    else:
                        missing.append(mimic_path)
            try:
                stage.GetRootLayer().Save()
            except Exception:
                pass
            self.last_apply_result = {
                "ok": True,
                "status": "applied",
                "sample_count": self.sample_count,
                "target_count": len(targets),
                "applied_count": len(applied),
                "applied_paths": applied[:12],
                "missing_paths": missing[:12],
                "stage_summary": stage_summary,
                "latest_state_path": str(LATEST_STATE_PATH),
            }
            return dict(self.last_apply_result)

    def _received_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            **payload,
            "server_received_at": datetime.now(timezone.utc).isoformat(),
            "server_sample_count": self.sample_count,
        }

    @staticmethod
    def _write_latest_state(payload: dict[str, Any]) -> None:
        LATEST_STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def status_payload(self) -> dict[str, Any]:
        with self.lock:
            return {
                "ok": True,
                "status": "ready",
                "apply_mode": "deferred_update_tick" if self.defer_apply else "direct_http_thread",
                "pending_sample": self.pending_payload is not None,
                "sample_count": self.sample_count,
                "scene_path": str(self.scene_path),
                "last_scene_open_status": self.last_scene_open_status,
                "scene_open_request_count": self.scene_open_request_count,
                "latest_state_path": str(LATEST_STATE_PATH),
                "last_error": self.last_error,
                "last_apply_result": dict(self.last_apply_result),
                "last_payload_summary": self._last_payload_summary_locked(),
            }

    def _last_payload_summary_locked(self) -> dict[str, Any]:
        payload = dict(self.last_payload or {})
        if not payload:
            return {}
        joint_state = payload.get("joint_state") if isinstance(payload.get("joint_state"), list) else []
        return {
            "session_id": str(payload.get("session_id") or ""),
            "sample_index": payload.get("sample_index"),
            "timestamp": str(payload.get("timestamp") or ""),
            "joint_count": len(joint_state),
            "target_count": len(_joint_targets(payload)),
        }

    @staticmethod
    def _stage_summary(stage: Any) -> dict[str, Any]:
        try:
            root_layer = stage.GetRootLayer() if stage is not None else None
        except Exception:
            root_layer = None
        try:
            default_prim = stage.GetDefaultPrim() if stage is not None else None
        except Exception:
            default_prim = None
        root_paths: list[str] = []
        joint_paths: list[str] = []
        physics_scene_paths: list[str] = []
        collision_paths: list[str] = []
        rigid_body_paths: list[str] = []
        try:
            root_paths = [str(prim.GetPath()) for prim in stage.GetPseudoRoot().GetChildren()]
        except Exception:
            root_paths = []
        try:
            for prim in stage.Traverse():
                name = prim.GetName()
                type_name = prim.GetTypeName()
                schemas = []
                try:
                    schemas = [str(item) for item in prim.GetAppliedSchemas()]
                except Exception:
                    schemas = []
                type_name_text = str(type_name)
                if type_name_text == "PhysicsScene":
                    physics_scene_paths.append(str(prim.GetPath()))
                if "PhysicsCollisionAPI" in schemas:
                    collision_paths.append(str(prim.GetPath()))
                if "PhysicsRigidBodyAPI" in schemas:
                    rigid_body_paths.append(str(prim.GetPath()))
                if "Joint" in str(type_name) or name in {"Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper", "Gripper_mimic"}:
                    joint_paths.append(str(prim.GetPath()))
                if len(joint_paths) >= 16 and len(collision_paths) >= 32 and len(rigid_body_paths) >= 16:
                    break
        except Exception:
            joint_paths = []
            physics_scene_paths = []
            collision_paths = []
            rigid_body_paths = []
        return {
            "root_layer_identifier": str(getattr(root_layer, "identifier", "") or ""),
            "default_prim_path": str(default_prim.GetPath()) if default_prim else "",
            "root_paths": root_paths,
            "joint_paths": joint_paths,
            "physics_scene_paths": physics_scene_paths[:8],
            "collision_paths": collision_paths[:32],
            "rigid_body_paths": rigid_body_paths[:16],
            "physics_ready": bool(physics_scene_paths and collision_paths and rigid_body_paths),
        }

    def ensure_gui_scene_open(self) -> None:
        """Keep the requested scene loaded in Isaac's GUI context."""
        if not self.use_current_stage or not self.scene_path.exists():
            return
        stage = _current_isaac_stage()
        try:
            prim = stage.GetPrimAtPath("/World/Robot/Geometry/link0/link1/Joint1") if stage is not None else None
            if prim and prim.IsValid():
                self.last_scene_open_status = "ready:/World/Robot"
                return
        except Exception:
            pass
        now = time.monotonic()
        if now - self._last_scene_open_attempt_s < 1.0:
            return
        self._last_scene_open_attempt_s = now
        self.scene_open_request_count += 1
        try:
            import omni.usd  # type: ignore

            context = omni.usd.get_context()
            result = context.open_stage(str(self.scene_path))
            self.last_scene_open_status = f"requested:{result}"
        except Exception as exc:
            self.last_scene_open_status = f"failed:{exc.__class__.__name__}: {exc}"

    @staticmethod
    def _apply_joint_target(stage: Any, target: dict[str, Any]) -> bool:
        prim = stage.GetPrimAtPath(target["path"])
        if not prim or not prim.IsValid():
            return False
        value = float(target["target_value"])
        applied = False
        for attr_name in ("drive:angular:physics:targetPosition", "state:angular:physics:position"):
            try:
                attr = prim.GetAttribute(attr_name)
                if attr:
                    attr.Set(value)
                    applied = True
            except Exception:
                continue
        if applied:
            return True
        # Isaac/UsdPhysics drive targetPosition is the least invasive target for
        # a live articulation. Fall back to authored joint state attrs for offline USD inspection.
        try:
            from pxr import UsdPhysics  # type: ignore

            drive = UsdPhysics.DriveAPI.Apply(prim, "angular")
            drive.CreateTargetPositionAttr(value).Set(value)
            drive.CreateStiffnessAttr(1000.0)
            drive.CreateDampingAttr(100.0)
            applied = True
        except Exception:
            pass
        for attr_name in ("drive:angular:physics:targetPosition", "state:angular:physics:position"):
            try:
                from pxr import Sdf  # type: ignore

                attr = prim.GetAttribute(attr_name)
                if not attr:
                    attr = prim.CreateAttribute(attr_name, Sdf.ValueTypeNames.Double)
                attr.Set(value)
                applied = True
            except Exception:
                continue
        return applied


def install_kit_update_subscription(state: IsaacMirrorState) -> Any:
    """Apply queued mirror samples on Isaac Kit's update stream when available."""
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        stream = app.get_update_event_stream()

        def _on_update(_event: Any) -> None:
            state.ensure_gui_scene_open()
            state.apply_latest_pending()

        subscription = stream.create_subscription_to_pop(_on_update, name="atr-isaac-omx-mirror-apply")
        state.defer_apply = True
        return subscription
    except Exception as exc:
        state.last_error = f"Kit update subscription unavailable: {exc.__class__.__name__}: {exc}"
        return None


def make_handler(state: IsaacMirrorState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json_response(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/", "/health", "/state"}:
                self._json_response(404, {"ok": False, "error": "not_found"})
                return
            self._json_response(200, state.status_payload())

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/joints":
                self._json_response(404, {"ok": False, "error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be an object")
                result = state.receive(payload)
                self._json_response(200 if result.get("ok") else 503, result)
            except Exception as exc:
                self._json_response(400, {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"})

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[isaac-omx-mirror] {self.address_string()} {fmt % args}")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve ROBOTIS OMX Isaac mirror joint target updates.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--scene", default=str(DEFAULT_SCENE))
    parser.add_argument("--no-current-stage", action="store_true", help="Do not use the active Isaac GUI stage; open --scene instead.")
    args = parser.parse_args()

    state = IsaacMirrorState(Path(args.scene).expanduser().resolve(), use_current_stage=not args.no_current_stage)
    subscription = install_kit_update_subscription(state)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    print(f"[isaac-omx-mirror] listening on http://{args.host}:{args.port}/joints")
    print(f"[isaac-omx-mirror] scene={state.scene_path}")
    if subscription is not None:
        print("[isaac-omx-mirror] Isaac Kit update subscription active; samples apply on update ticks")
    else:
        print(f"[isaac-omx-mirror] direct apply mode active; {state.last_error}")
    server.serve_forever()


if __name__ == "__main__":
    main()
