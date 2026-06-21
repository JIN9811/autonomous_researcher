"""
File purpose:
- Improvement 15 CalculiX bridge contract for real-solver jobs and safe preflight.

Key classes/functions:
- CalculiXBridgeConfig
- CalculiXBridge

Inputs/outputs:
- Input: .inp deck text/path, specimen/run metadata, runtime_solver_enabled gate
- Output: CalculiX job status, artifact paths, solver/postprocessor health

Dependencies:
- subprocess
- utils.paths.resolve_path

Modification guide:
- Safe places to edit: preflight, artifact naming, parser/postprocess metadata.
- Risky places to edit: execution gate and return keys consumed by Analysis/GUI.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from device_bridges.base_bridge import BaseBridge
from utils.paths import resolve_path


@dataclass(slots=True)
class CalculiXBridgeConfig:
    """Configuration for real CalculiX jobs."""

    enabled: bool = True
    mode: str = "test"
    executable_path: str = ""
    ccx2paraview_path: str = ""
    frd2vtu_path: str = ""
    runtime_solver_enabled: bool = False
    timeout_s: float = 600.0
    artifact_dir: Path = field(default_factory=lambda: resolve_path("artifacts/calculix"))

    @classmethod
    def from_devices_config(cls, devices_config: dict[str, Any] | None = None, *, repo_root: Path | None = None) -> "CalculiXBridgeConfig":
        raw = devices_config or {}
        devices = raw.get("devices", raw) if isinstance(raw, dict) else {}
        config = {}
        if isinstance(devices, dict):
            if isinstance(devices.get("calculix"), dict):
                config.update(devices["calculix"])
            elif isinstance(devices.get("cae"), dict):
                cae = devices["cae"]
                config.update(
                    {
                        "enabled": cae.get("enabled", True),
                        "mode": cae.get("mode", devices.get("mode", "test")),
                        "executable_path": cae.get("solver_path") or cae.get("calculix_path") or cae.get("ccx_path") or "",
                        "runtime_solver_enabled": cae.get("runtime_solver_enabled", False),
                        "artifact_dir": cae.get("calculix_artifact_dir") or cae.get("artifact_dir") or "artifacts/calculix",
                    }
                )
        base_root = repo_root or resolve_path(".")
        artifact = Path(str(config.get("artifact_dir", "artifacts/calculix"))).expanduser()
        if not artifact.is_absolute():
            artifact = base_root.joinpath(artifact).resolve()

        def _path(key: str) -> str:
            value = str(config.get(key) or "").strip()
            if not value:
                return ""
            path = Path(value).expanduser()
            return str(path if path.is_absolute() else base_root.joinpath(path).resolve())

        return cls(
            enabled=bool(config.get("enabled", True)),
            mode=str(config.get("mode", "test")),
            executable_path=_path("executable_path"),
            ccx2paraview_path=_path("ccx2paraview_path"),
            frd2vtu_path=_path("frd2vtu_path"),
            runtime_solver_enabled=bool(config.get("runtime_solver_enabled", False)),
            timeout_s=float(config.get("timeout_s", 600.0) or 600.0),
            artifact_dir=artifact,
        )


class CalculiXBridge(BaseBridge):
    """Run or preflight CalculiX jobs behind an explicit execution gate."""

    def __init__(self, config: CalculiXBridgeConfig) -> None:
        self.config = config

    @staticmethod
    def _existing_executable(path_text: str) -> str:
        if not path_text:
            return ""
        path = Path(path_text).expanduser()
        return str(path) if path.exists() and path.is_file() else ""

    @staticmethod
    def _slug(value: Any, default: str = "calculix_job") -> str:
        text = str(value or default)
        slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text).strip("_")
        return slug[:96] or default

    def _job_dir(self, payload: dict[str, Any]) -> Path:
        run_id = self._slug(payload.get("run_id"), "run")
        specimen_id = self._slug(payload.get("specimen_id") or payload.get("job_id"), "specimen")
        path = self.config.artifact_dir / run_id / specimen_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def health(self) -> dict[str, Any]:
        ccx = self._existing_executable(self.config.executable_path) or shutil.which("ccx") or shutil.which("calculix")
        ccx2paraview = self._existing_executable(self.config.ccx2paraview_path) or shutil.which("ccx2paraview")
        frd2vtu = self._existing_executable(self.config.frd2vtu_path) or shutil.which("frd2vtu")
        return {
            "ok": True,
            "tool": "calculix.health",
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "runtime_solver_enabled": self.config.runtime_solver_enabled,
            "calculix": {"available": bool(ccx), "path": ccx or ""},
            "ccx2paraview": {"available": bool(ccx2paraview), "path": ccx2paraview or ""},
            "frd2vtu": {"available": bool(frd2vtu), "path": frd2vtu or ""},
            "artifact_dir": str(self.config.artifact_dir),
        }

    def prepare_input(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        job_dir = self._job_dir(data)
        specimen_id = self._slug(data.get("specimen_id"), "specimen")
        source_path = Path(str(data.get("inp_path") or "")).expanduser() if data.get("inp_path") else None
        if source_path and source_path.exists():
            inp_path = source_path
            copied = False
        else:
            inp_path = job_dir / f"{specimen_id}.inp"
            inp_text = str(data.get("inp_text") or data.get("input_deck") or "*Heading\nATR CalculiX job placeholder\n*End Step\n")
            inp_path.write_text(inp_text, encoding="utf-8")
            copied = True
        request_path = job_dir / f"{specimen_id}.request.json"
        request_path.write_text(json.dumps({"schema": "calculix_request.v1", "payload": data, "inp_path": str(inp_path)}, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
        return {
            "ok": True,
            "tool": "calculix.prepare_input",
            "status": "prepared",
            "job_dir": str(job_dir),
            "inp_path": str(inp_path),
            "request_path": str(request_path),
            "copied_from_existing": not copied,
        }

    def solve(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        if not self.config.enabled:
            return {"ok": False, "tool": "calculix.solve", "status": "blocked", "failure_code": "CALCULIX_BRIDGE_DISABLED"}
        if not bool(data.get("runtime_solver_enabled", self.config.runtime_solver_enabled)):
            return {
                "ok": False,
                "tool": "calculix.solve",
                "status": "blocked",
                "failure_code": "CALCULIX_RUNTIME_SOLVER_DISABLED",
                "message": "Set runtime_solver_enabled=true only when the operator intends to run ccx.",
            }
        health = self.health()
        ccx = str(health.get("calculix", {}).get("path") or "")
        if not ccx:
            return {
                "ok": False,
                "tool": "calculix.solve",
                "status": "blocked",
                "failure_code": "CALCULIX_EXECUTABLE_REQUIRED",
                "solver_status": health,
            }
        prepared = self.prepare_input(data)
        inp_path = Path(str(prepared["inp_path"]))
        job_name = inp_path.with_suffix("").name
        workdir = inp_path.parent
        try:
            completed = subprocess.run(
                [ccx, job_name],
                cwd=str(workdir),
                text=True,
                capture_output=True,
                timeout=float(data.get("timeout_s", self.config.timeout_s) or self.config.timeout_s),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "tool": "calculix.solve", "status": "failed", "failure_code": "CALCULIX_TIMEOUT", "inp_path": str(inp_path)}
        dat_path = workdir / f"{job_name}.dat"
        frd_path = workdir / f"{job_name}.frd"
        return {
            "ok": completed.returncode == 0,
            "tool": "calculix.solve",
            "status": "completed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "inp_path": str(inp_path),
            "dat_path": str(dat_path) if dat_path.exists() else "",
            "frd_path": str(frd_path) if frd_path.exists() else "",
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
            "failure_code": None if completed.returncode == 0 else "CALCULIX_SOLVE_FAILED",
        }

    def postprocess(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        dat_path = Path(str(data.get("dat_path") or "")).expanduser() if data.get("dat_path") else None
        frd_path = Path(str(data.get("frd_path") or "")).expanduser() if data.get("frd_path") else None
        available = bool(dat_path and dat_path.exists()) or bool(frd_path and frd_path.exists())
        return {
            "ok": available,
            "tool": "calculix.postprocess",
            "status": "postprocessed" if available else "unavailable",
            "dat_path": str(dat_path) if dat_path and dat_path.exists() else "",
            "frd_path": str(frd_path) if frd_path and frd_path.exists() else "",
            "curve_json_path": "",
            "field_asset_path": "",
            "failure_code": None if available else "CALCULIX_RESULT_ARTIFACTS_UNAVAILABLE",
        }

    def run_job(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        prepared = self.prepare_input(data)
        solved = self.solve({**data, "inp_path": prepared.get("inp_path")})
        if not solved.get("ok"):
            return {**solved, "prepared": prepared, "step_trace": [{"step": "PREPARE_INPUT", "status": "ok"}, {"step": "SOLVE", "status": solved.get("status", "blocked"), "detail": solved.get("failure_code")}]}
        post = self.postprocess(solved)
        return {
            "ok": bool(post.get("ok")),
            "tool": "calculix.run_job",
            "status": "complete" if post.get("ok") else "failed",
            "prepared": prepared,
            "solve": solved,
            "postprocess": post,
            "inp_path": solved.get("inp_path"),
            "dat_path": solved.get("dat_path"),
            "frd_path": solved.get("frd_path"),
            "failure_code": post.get("failure_code"),
            "step_trace": [
                {"step": "PREPARE_INPUT", "status": "ok"},
                {"step": "SOLVE", "status": "ok"},
                {"step": "POSTPROCESS", "status": post.get("status", "unavailable")},
            ],
        }

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command in {"health", "calculix.health"}:
            return self.health()
        if command in {"prepare_input", "calculix.prepare_input"}:
            return self.prepare_input(payload)
        if command in {"solve", "calculix.solve"}:
            return self.solve(payload)
        if command in {"postprocess", "calculix.postprocess"}:
            return self.postprocess(payload)
        if command in {"run_job", "calculix.run_job"}:
            return self.run_job(payload)
        return {"ok": False, "tool": f"calculix.{command}", "status": "blocked", "failure_code": "CALCULIX_COMMAND_UNSUPPORTED"}
