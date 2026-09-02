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
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from device_bridges.base_bridge import BaseBridge
from utils.calculix_quasistatic import build_compression_deck, parse_reaction_history
from utils.paths import resolve_path


@dataclass(slots=True)
class CalculiXBridgeConfig:
    """Configuration for real CalculiX jobs."""

    enabled: bool = True
    mode: str = "test"
    executable_path: str = ""
    gmsh_path: str = ""
    library_path: str = ""
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
                        "gmsh_path": cae.get("mesher_path") or cae.get("gmsh_path") or "",
                        "library_path": cae.get("library_path") or "",
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
            gmsh_path=_path("gmsh_path"),
            library_path=_path("library_path"),
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
        gmsh = self._existing_executable(self.config.gmsh_path) or shutil.which("gmsh")
        ccx2paraview = self._existing_executable(self.config.ccx2paraview_path) or shutil.which("ccx2paraview")
        frd2vtu = self._existing_executable(self.config.frd2vtu_path) or shutil.which("frd2vtu")
        return {
            "ok": True,
            "tool": "calculix.health",
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "runtime_solver_enabled": self.config.runtime_solver_enabled,
            "calculix": {
                "available": bool(ccx),
                "path": ccx or "",
                "version": self._version(str(ccx or ""), "-v"),
            },
            "gmsh": {
                "available": bool(gmsh),
                "path": gmsh or "",
                "version": self._version(str(gmsh or ""), "--version"),
            },
            "ccx2paraview": {"available": bool(ccx2paraview), "path": ccx2paraview or ""},
            "frd2vtu": {"available": bool(frd2vtu), "path": frd2vtu or ""},
            "artifact_dir": str(self.config.artifact_dir),
        }

    def _subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        library_path = str(self.config.library_path or "").strip()
        if library_path:
            existing = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = library_path if not existing else f"{library_path}:{existing}"
        return env

    def _version(self, executable: str, *args: str) -> str:
        if not executable:
            return ""
        try:
            with tempfile.TemporaryDirectory(prefix="atr-calculix-version-") as probe_dir:
                completed = subprocess.run(
                    [executable, *args],
                    cwd=probe_dir,
                    text=True,
                    capture_output=True,
                    env=self._subprocess_env(),
                    timeout=3.0,
                    check=False,
                )
        except (OSError, subprocess.SubprocessError):
            return ""
        output = (completed.stdout or completed.stderr or "").strip()
        return output.splitlines()[0][:240] if output else ""

    def mesh_stl(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Tetrahedralize a closed STL through Gmsh's discrete-surface workflow."""
        stl_path = Path(str(payload.get("stl_path") or "")).expanduser()
        if not stl_path.exists() or not stl_path.is_file():
            return {
                "ok": False,
                "tool": "calculix.mesh_stl",
                "status": "blocked",
                "failure_code": "CAE_STL_REQUIRED",
                "stl_path": str(stl_path),
            }
        gmsh = str(self.health().get("gmsh", {}).get("path") or "")
        if not gmsh:
            return {
                "ok": False,
                "tool": "calculix.mesh_stl",
                "status": "blocked",
                "failure_code": "CAE_GMSH_REQUIRED",
                "stl_path": str(stl_path),
            }
        job_dir = self._job_dir(payload)
        specimen_id = self._slug(payload.get("specimen_id"), "specimen")
        geo_path = job_dir / f"{specimen_id}.geo"
        mesh_path = job_dir / f"{specimen_id}.mesh.inp"
        mesh_size = max(float(payload.get("mesh_size_mm", 2.0) or 2.0), 0.05)
        escaped_stl = str(stl_path.resolve()).replace("\\", "\\\\").replace('"', '\\"')
        geo_path.write_text(
            "\n".join(
                [
                    f'Merge "{escaped_stl}";',
                    "surface_ids() = Surface{:};",
                    "Surface Loop(1) = {surface_ids()};",
                    "Volume(1) = {1};",
                    'Physical Volume("VOLUME") = {1};',
                    f"Mesh.MeshSizeMin = {mesh_size:g};",
                    f"Mesh.MeshSizeMax = {mesh_size:g};",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [gmsh, str(geo_path), "-3", "-format", "inp", "-o", str(mesh_path)],
                cwd=str(job_dir),
                text=True,
                capture_output=True,
                env=self._subprocess_env(),
                timeout=float(payload.get("mesh_timeout_s", self.config.timeout_s) or self.config.timeout_s),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "tool": "calculix.mesh_stl",
                "status": "failed",
                "failure_code": "CAE_MESH_TIMEOUT",
                "geo_path": str(geo_path),
            }
        ok = completed.returncode == 0 and mesh_path.exists() and mesh_path.stat().st_size > 0
        return {
            "ok": ok,
            "tool": "calculix.mesh_stl",
            "status": "completed" if ok else "failed",
            "failure_code": None if ok else "CAE_MESH_FAILED",
            "stl_path": str(stl_path),
            "geo_path": str(geo_path),
            "mesh_inp_path": str(mesh_path) if mesh_path.exists() else "",
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
            "returncode": completed.returncode,
        }

    def prepare_quasistatic_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build a displacement-controlled nonlinear compression deck from STL."""
        meshed = self.mesh_stl(payload)
        if not meshed.get("ok"):
            return meshed
        mesh_path = Path(str(meshed["mesh_inp_path"]))
        size = payload.get("specimen_size_mm") if isinstance(payload.get("specimen_size_mm"), (list, tuple)) else [20.0, 20.0, 20.0]
        height = float(size[2]) if len(size) >= 3 else 20.0
        target_strain = min(max(float(payload.get("target_strain", 0.5) or 0.5), 1e-6), 0.8)
        target_displacement = height * target_strain
        increments = payload.get("increments") if isinstance(payload.get("increments"), dict) else {}
        deck, manifest = build_compression_deck(
            mesh_path.read_text(encoding="utf-8", errors="replace"),
            material=payload.get("material") if isinstance(payload.get("material"), dict) else {},
            target_displacement_mm=target_displacement,
            increments={
                "initial": increments.get("initial", payload.get("initial_increment", 0.01)),
                "time_period": increments.get("time_period", 1.0),
                "minimum": increments.get("minimum", payload.get("minimum_increment", 1e-7)),
                "maximum": increments.get("maximum", payload.get("maximum_increment", 0.02)),
                "max_increments": increments.get("max_increments", payload.get("max_increments", 500)),
            },
            boundary_tolerance_mm=float(payload.get("boundary_tolerance_mm", max(height * 1e-5, 1e-6))),
        )
        job_dir = self._job_dir(payload)
        specimen_id = self._slug(payload.get("specimen_id"), "specimen")
        inp_path = job_dir / f"{specimen_id}.inp"
        inp_path.write_text(deck, encoding="utf-8")
        manifest_path = job_dir / f"{specimen_id}.deck_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
        return {
            "ok": True,
            "tool": "calculix.prepare_quasistatic_input",
            "status": "prepared",
            "inp_path": str(inp_path),
            "mesh_inp_path": str(mesh_path),
            "geo_path": meshed.get("geo_path", ""),
            "manifest_path": str(manifest_path),
            "manifest": manifest,
            "target_displacement_mm": target_displacement,
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
        dat_path = workdir / f"{job_name}.dat"
        frd_path = workdir / f"{job_name}.frd"
        try:
            completed = subprocess.run(
                [ccx, job_name],
                cwd=str(workdir),
                text=True,
                capture_output=True,
                env=self._subprocess_env(),
                timeout=float(data.get("timeout_s", self.config.timeout_s) or self.config.timeout_s),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
            return {
                "ok": False,
                "tool": "calculix.solve",
                "status": "failed",
                "failure_code": "CALCULIX_TIMEOUT",
                "inp_path": str(inp_path),
                "dat_path": str(dat_path) if dat_path.exists() else "",
                "frd_path": str(frd_path) if frd_path.exists() else "",
                "stdout_tail": stdout[-2000:],
                "stderr_tail": stderr[-2000:],
            }
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
        if str(data.get("analysis_type") or "").strip().lower() == "quasistatic_compression":
            prepared = self.prepare_quasistatic_input(data)
            if not prepared.get("ok"):
                return {
                    **prepared,
                    "step_trace": [{"step": "MESH_AND_PREPARE", "status": prepared.get("status", "failed"), "detail": prepared.get("failure_code")}],
                }
            solved = self.solve({**data, "inp_path": prepared["inp_path"]})
            if not solved.get("ok"):
                partial_dat = Path(str(solved.get("dat_path") or ""))
                if partial_dat.is_file():
                    parsed = parse_reaction_history(
                        partial_dat.read_text(encoding="utf-8", errors="replace"),
                        target_displacement_mm=float(prepared["target_displacement_mm"]),
                        endpoint_tolerance_mm=float(data.get("endpoint_tolerance_mm", 1e-5) or 1e-5),
                    )
                    metrics = parsed.get("metrics") if isinstance(parsed.get("metrics"), dict) else {}
                    if int(metrics.get("converged_increment_count", 0) or 0) > 0:
                        job_dir = Path(str(prepared["inp_path"])).parent
                        specimen_id = self._slug(data.get("specimen_id"), "specimen")
                        curve_path = job_dir / f"{specimen_id}.curve.json"
                        curve_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=True), encoding="utf-8")
                        artifacts = {
                            "stl_path": str(data.get("stl_path") or ""),
                            "geo_path": prepared.get("geo_path", ""),
                            "mesh_inp_path": prepared.get("mesh_inp_path", ""),
                            "inp_path": solved.get("inp_path", prepared.get("inp_path", "")),
                            "dat_path": solved.get("dat_path", ""),
                            "frd_path": solved.get("frd_path", ""),
                            "curve_json_path": str(curve_path),
                            "manifest_path": prepared.get("manifest_path", ""),
                        }
                        return {
                            "ok": False,
                            "tool": "calculix.run_job",
                            "status": "partial",
                            "analysis_type": "quasistatic_compression",
                            "loading_control": "displacement",
                            "solver_mode": "calculix_quasistatic",
                            "target_strain": float(data.get("target_strain", 0.5) or 0.5),
                            "target_displacement_mm": float(prepared["target_displacement_mm"]),
                            "reaction_force_displacement_curve": parsed.get("curve", []),
                            "metrics": metrics,
                            "artifacts": artifacts,
                            "prepared": prepared,
                            "solve": solved,
                            "failure_code": solved.get("failure_code") or "CALCULIX_ENDPOINT_NOT_REACHED",
                            "step_trace": [
                                {"step": "MESH_AND_PREPARE", "status": "ok"},
                                {"step": "SOLVE", "status": "partial", "detail": solved.get("failure_code")},
                                {"step": "POSTPROCESS", "status": "partial"},
                            ],
                        }
                return {
                    **solved,
                    "prepared": prepared,
                    "step_trace": [
                        {"step": "MESH_AND_PREPARE", "status": "ok"},
                        {"step": "SOLVE", "status": solved.get("status", "failed"), "detail": solved.get("failure_code")},
                    ],
                }
            dat_path = Path(str(solved.get("dat_path") or ""))
            if not dat_path.exists():
                return {
                    "ok": False,
                    "tool": "calculix.run_job",
                    "status": "failed",
                    "failure_code": "CALCULIX_RESULT_PARSE_FAILED",
                    "prepared": prepared,
                    "solve": solved,
                }
            parsed = parse_reaction_history(
                dat_path.read_text(encoding="utf-8", errors="replace"),
                target_displacement_mm=float(prepared["target_displacement_mm"]),
                endpoint_tolerance_mm=float(data.get("endpoint_tolerance_mm", 1e-5) or 1e-5),
            )
            job_dir = Path(str(prepared["inp_path"])).parent
            specimen_id = self._slug(data.get("specimen_id"), "specimen")
            curve_path = job_dir / f"{specimen_id}.curve.json"
            curve_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=True), encoding="utf-8")
            endpoint_reached = bool(parsed.get("endpoint_reached"))
            parsed_metrics = parsed.get("metrics") if isinstance(parsed.get("metrics"), dict) else {}
            history_parsed = int(parsed_metrics.get("converged_increment_count", 0) or 0) > 0
            artifacts = {
                "stl_path": str(data.get("stl_path") or ""),
                "geo_path": prepared.get("geo_path", ""),
                "mesh_inp_path": prepared.get("mesh_inp_path", ""),
                "inp_path": solved.get("inp_path", ""),
                "dat_path": solved.get("dat_path", ""),
                "frd_path": solved.get("frd_path", ""),
                "curve_json_path": str(curve_path),
                "manifest_path": prepared.get("manifest_path", ""),
            }
            return {
                "ok": endpoint_reached and history_parsed,
                "tool": "calculix.run_job",
                "status": "complete" if endpoint_reached and history_parsed else "partial" if history_parsed else "failed",
                "analysis_type": "quasistatic_compression",
                "loading_control": "displacement",
                "solver_mode": "calculix_quasistatic",
                "target_strain": float(data.get("target_strain", 0.5) or 0.5),
                "target_displacement_mm": float(prepared["target_displacement_mm"]),
                "reaction_force_displacement_curve": parsed.get("curve", []),
                "metrics": parsed_metrics,
                "artifacts": artifacts,
                "prepared": prepared,
                "solve": solved,
                "failure_code": (
                    None
                    if endpoint_reached and history_parsed
                    else "CALCULIX_ENDPOINT_NOT_REACHED"
                    if history_parsed
                    else "CALCULIX_RESULT_PARSE_FAILED"
                ),
                "step_trace": [
                    {"step": "MESH_AND_PREPARE", "status": "ok"},
                    {"step": "SOLVE", "status": "ok"},
                    {
                        "step": "POSTPROCESS",
                        "status": "ok" if endpoint_reached and history_parsed else "partial" if history_parsed else "failed",
                    },
                ],
            }
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
