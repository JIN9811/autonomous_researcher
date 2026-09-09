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
import hashlib
import math
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from device_bridges.base_bridge import BaseBridge
from utils.calculix_fields import postprocess_fields, _parse_inp, _mesh_contract, _read_ascii, _FieldError, MAX_FIELD_FILE_BYTES
from utils.calculix_last_frame import select_last_complete_frame
from utils.calculix_quasistatic import build_compression_deck, parse_reaction_history
from utils.cae_surface_mesh import normalize_profile
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
        for key in ("loop_key", "job_id", "attempt_id"):
            if payload.get(key):
                path /= self._slug(payload[key], key)
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

    def _subprocess_env(self, *, threads: int | None = None,
                        equation_solver_threads: int | None = None) -> dict[str, str]:
        env = dict(os.environ)
        library_path = str(self.config.library_path or "").strip()
        if library_path:
            existing = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = library_path if not existing else f"{library_path}:{existing}"
        if threads is not None:
            env["OMP_NUM_THREADS"] = str(threads)
        if equation_solver_threads is not None:
            env["CCX_NPROC_EQUATION_SOLVER"] = str(equation_solver_threads)
        return env

    def _computation_limits(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested = payload.get("computation_limits")
        nested = requested if isinstance(requested, dict) else {}
        raw_timeout = nested.get("timeout_s", payload.get("timeout_s", self.config.timeout_s))
        timeout = None
        if raw_timeout is not None:
            try:
                timeout = float(raw_timeout)
            except (TypeError, ValueError):
                timeout = float(self.config.timeout_s)
            if not math.isfinite(timeout) or timeout <= 0.0:
                timeout = float(self.config.timeout_s)
            timeout = min(timeout, float(self.config.timeout_s))
        limits: dict[str, Any] = {"timeout_s": timeout}
        if "threads" in nested:
            try:
                threads = int(nested["threads"])
            except (TypeError, ValueError):
                threads = 1
            limits["threads"] = min(max(threads, 1), 64)
        if "equation_solver_threads" in nested:
            try:
                equation_threads = int(nested["equation_solver_threads"])
            except (TypeError, ValueError, OverflowError):
                equation_threads = 1
            limits["equation_solver_threads"] = min(max(equation_threads, 1), limits.get("threads", 64))
        if "max_mesh_elements" in nested:
            try:
                max_elements = int(nested["max_mesh_elements"])
            except (TypeError, ValueError):
                max_elements = 1
            limits["max_mesh_elements"] = max(max_elements, 1)
        return limits

    @staticmethod
    def _tail(path: Path, limit: int = 2000) -> str:
        if not path.is_file():
            return ""
        with path.open("rb") as stream:
            stream.seek(max(path.stat().st_size - limit, 0))
            return stream.read(limit).decode("utf-8", errors="replace")

    def _run_process(self, command: list[str], *, workdir: Path, payload: dict[str, Any],
                     phase: str, timeout: float | None, env: dict[str, str]) -> dict[str, Any]:
        """Own one native process group, with disk-backed logs and cooperative cancellation."""
        stdout_path = workdir / f"{phase}.stdout.log"
        stderr_path = workdir / f"{phase}.stderr.log"
        cancel = payload.get("_cancel_event")
        callback = payload.get("_progress_callback")
        if cancel is not None and not isinstance(cancel, threading.Event):
            raise ValueError("_cancel_event is an in-process threading.Event only")
        if callback is not None and not callable(callback):
            raise ValueError("_progress_callback is an in-process callable only")
        started = time.monotonic()
        status = "running"
        observation: dict[str, Any] = {"phase": phase, "pid": None, "elapsed_s": 0.0,
                                       "cpu_time_s": None, "rss_bytes": None}

        def emit() -> None:
            observation.update(status=status, elapsed_s=time.monotonic() - started)
            if callable(callback):
                try:
                    callback(dict(observation))
                except Exception:
                    # Telemetry must never orphan an owned computation.
                    pass

        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            if cancel is not None and cancel.is_set():
                status = "cancelled"
                returncode = None
            else:
                process = subprocess.Popen(command, cwd=str(workdir), env=env, stdout=stdout,
                                           stderr=stderr, start_new_session=True)
                observation["pid"] = process.pid
                while process.poll() is None:
                    try:
                        stat = Path(f"/proc/{process.pid}/stat").read_text().rsplit(")", 1)[1].split()
                        observation["cpu_time_s"] = (int(stat[11]) + int(stat[12])) / os.sysconf("SC_CLK_TCK")
                        observation["rss_bytes"] = int(stat[21]) * os.sysconf("SC_PAGE_SIZE")
                    except (OSError, ValueError, IndexError):
                        pass
                    sta_path = workdir / f"{command[-1]}.sta"
                    if phase == "solve" and sta_path.is_file():
                        rows = [line.split() for line in self._tail(sta_path).splitlines() if line.strip()]
                        for row in reversed(rows):
                            if len(row) >= 3 and all(token.isdigit() for token in row[:3]):
                                observation["solver_increment"] = int(row[1])
                                observation["solver_step"] = int(row[0])
                                break
                    emit()
                    if cancel is not None and cancel.is_set():
                        status = "cancelled"
                    elif timeout is not None and time.monotonic() - started >= timeout:
                        status = "timeout"
                    if status != "running":
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        try:
                            process.wait(timeout=0.5)
                        except subprocess.TimeoutExpired:
                            pass
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                        break
                    time.sleep(0.05)
                returncode = process.returncode
                if status == "running":
                    status = "completed" if returncode == 0 else "failed"
        emit()
        return {"returncode": returncode, "status": status, "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path), "stdout_tail": self._tail(stdout_path),
                "stderr_tail": self._tail(stderr_path), "progress": dict(observation)}

    def _version(self, executable: str, *args: str) -> str:
        if not executable:
            return ""
        try:
            with tempfile.TemporaryDirectory(prefix="atr-calculix-version-") as probe_dir:
                completed = self._run_process([executable, *args], workdir=Path(probe_dir),
                                              payload={}, phase="version", env=self._subprocess_env(), timeout=3.0)
                output = ""
                for key in ("stdout_path", "stderr_path"):
                    with Path(completed[key]).open("rb") as stream:
                        output = stream.read(1024).decode("utf-8", errors="replace").strip()
                    if output:
                        break
        except (OSError, subprocess.SubprocessError):
            return ""
        return output.splitlines()[0][:240] if output else ""

    @staticmethod
    def _inp_element_count(text: str) -> int:
        count = 0
        in_elements = False
        for raw in text.replace("\r", "").splitlines():
            line = raw.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                in_elements = line.upper().startswith("*ELEMENT")
            elif in_elements:
                count += 1
        return count

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
        computation_limits = self._computation_limits(payload)
        conditioning = None
        if payload.get("surface_remesh") is not None:
            try:
                profile = normalize_profile(payload["surface_remesh"])
            except ValueError:
                return {"ok": False, "status": "blocked", "failure_code": "CAE_SURFACE_REMESH_PROFILE_INVALID"}
            surface_request = job_dir / "surface_request.json"
            surface_request.write_text(json.dumps({"source": str(stl_path.resolve()), "output_dir": str(job_dir.resolve()),
                                                   "profile": profile}), encoding="utf-8")
            conditioned = self._run_process(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "utils" / "cae_surface_mesh.py"), str(surface_request.resolve())],
                workdir=job_dir, payload=payload, phase="surface_remesh", timeout=computation_limits["timeout_s"],
                env=self._subprocess_env(threads=computation_limits.get("threads")),
            )
            report_path = job_dir / "surface_geometry_check.json"
            if conditioned["status"] != "completed":
                return {**conditioned, "ok": False,
                        "failure_code": {"cancelled": "CAE_SURFACE_REMESH_CANCELLED", "timeout": "CAE_SURFACE_REMESH_TIMEOUT"}.get(conditioned["status"], "CAE_SURFACE_REMESH_REJECTED"),
                        "geometry_check_path": str(report_path) if report_path.is_file() else "",
                        "computation_limits": computation_limits}
            conditioning = json.loads(report_path.read_text())
            if not conditioning.get("accepted"):
                return {"ok": False, "status": "blocked", "failure_code": "CAE_SURFACE_REMESH_REJECTED", "surface_remesh": conditioning}
            stl_path = Path(conditioning["surface_path"])
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
                    *(["Mesh.Algorithm3D = 10;", "Mesh.OptimizeThreshold = 0.5;", "Mesh.ElementOrder = 1;"] if conditioning else []),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        timeout = computation_limits["timeout_s"]
        if timeout is not None:
            timeout = min(float(payload.get("mesh_timeout_s", timeout) or timeout), timeout)
        completed = self._run_process(
            [gmsh, str(geo_path), "-3", "-format", "inp", "-o", str(mesh_path)],
            workdir=job_dir, payload=payload, phase="mesh", timeout=timeout,
            env=self._subprocess_env(threads=computation_limits.get("threads")),
        )
        if completed["status"] in {"timeout", "cancelled"}:
            return {
                **completed,
                "ok": False,
                "tool": "calculix.mesh_stl",
                "status": "cancelled" if completed["status"] == "cancelled" else "failed",
                "failure_code": "CAE_MESH_CANCELLED" if completed["status"] == "cancelled" else "CAE_MESH_TIMEOUT",
                "geo_path": str(geo_path),
                "mesh_inp_path": str(mesh_path) if mesh_path.is_file() else "",
                "computation_limits": computation_limits,
            }
        ok = completed["returncode"] == 0 and mesh_path.exists() and mesh_path.stat().st_size > 0
        mesh_element_count = (
            self._inp_element_count(mesh_path.read_text(encoding="utf-8", errors="strict")) if ok else 0
        )
        maximum_elements = computation_limits.get("max_mesh_elements")
        if maximum_elements is not None and mesh_element_count > maximum_elements:
            return {
                **completed,
                "ok": False,
                "tool": "calculix.mesh_stl",
                "status": "blocked",
                "failure_code": "CAE_MESH_ELEMENT_LIMIT_EXCEEDED",
                "stl_path": str(stl_path),
                "geo_path": str(geo_path),
                "mesh_inp_path": str(mesh_path),
                "mesh_element_count": mesh_element_count,
                "computation_limits": computation_limits,
            }
        return {
            **completed,
            "ok": ok,
            "tool": "calculix.mesh_stl",
            "status": "completed" if ok else "failed",
            "failure_code": None if ok else "CAE_MESH_FAILED",
            "stl_path": str(stl_path),
            "geo_path": str(geo_path),
            "mesh_inp_path": str(mesh_path) if mesh_path.exists() else "",
            "mesh_element_count": mesh_element_count,
            "computation_limits": computation_limits,
            "surface_remesh": conditioning,
        }

    def prepare_quasistatic_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build a displacement-controlled nonlinear compression deck from STL."""
        meshed = self.mesh_stl(payload)
        if not meshed.get("ok"):
            return meshed
        mesh_path = Path(str(meshed["mesh_inp_path"]))
        try:
            mesh_text, _ = _read_ascii(mesh_path, "INP")
            _, mesh_quality = _mesh_contract(*_parse_inp(mesh_text))
            mesh_quality["quality"].pop("below_threshold_element_ids", None)
        except _FieldError as exc:
            return {**meshed, "ok": False, "status": "blocked", "failure_code": exc.code,
                    "mesh_quality": {"validity": {"status": "invalid"}, "failure_code": exc.code}}
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
        prepared = {
            "ok": True,
            "tool": "calculix.prepare_quasistatic_input",
            "status": "prepared",
            "inp_path": str(inp_path),
            "mesh_inp_path": str(mesh_path),
            "geo_path": meshed.get("geo_path", ""),
            "manifest_path": str(manifest_path),
            "manifest": manifest,
            "target_displacement_mm": target_displacement,
            "mesh_quality": mesh_quality,
            "surface_remesh": meshed.get("surface_remesh"),
        }
        request = self._prepared_request(payload)
        receipt = {**prepared, "schema": "calculix_prepared_input.v1",
                   "request_sha256": self._json_hash(request),
                   "source_stl_path": str(Path(payload["stl_path"]).resolve()),
                   "source_sha256": self._file_hash(Path(payload["stl_path"])),
                   "mesh_sha256": self._file_hash(mesh_path), "deck_sha256": self._file_hash(inp_path),
                   "receipt_path": str(job_dir / f"{specimen_id}.prepared.json")}
        Path(receipt["receipt_path"]).write_text(json.dumps({"prepared_input": receipt, "request": request}, indent=2), encoding="utf-8")
        return {**prepared, "prepared_input": receipt}

    @staticmethod
    def _json_hash(data: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    @staticmethod
    def _file_hash(path: Path) -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    @staticmethod
    def _prepared_request(payload: dict[str, Any]) -> dict[str, Any]:
        keys = ("run_id", "loop_key", "specimen_id", "job_id", "attempt_id", "mode", "analysis_type",
                "specimen_size_mm", "mesh_size_mm", "material", "target_strain", "increments", "boundary",
                "loading", "loading_control", "surface_remesh", "boundary_tolerance_mm",
                "initial_increment", "minimum_increment", "maximum_increment", "max_increments")
        return {key: payload[key] for key in keys if key in payload}

    def _validate_prepared(self, payload: dict[str, Any]) -> dict[str, Any]:
        receipt = payload.get("prepared_input")
        try:
            if not isinstance(receipt, dict) or receipt.get("schema") != "calculix_prepared_input.v1":
                raise ValueError("receipt schema")
            job_dir = self._job_dir(payload).resolve()
            for key in ("receipt_path", "inp_path", "mesh_inp_path"):
                if Path(receipt[key]).resolve().parent != job_dir:
                    raise ValueError("receipt scope")
            saved = json.loads(Path(receipt["receipt_path"]).read_text())["prepared_input"]
            if saved != receipt or receipt["request_sha256"] != self._json_hash(self._prepared_request(payload)):
                raise ValueError("request mismatch")
            for key, digest in (("mesh_inp_path", "mesh_sha256"), ("inp_path", "deck_sha256"),
                                ("source_stl_path", "source_sha256")):
                if self._file_hash(Path(receipt[key])) != receipt[digest]:
                    raise ValueError("artifact changed")
            if Path(str(payload.get("stl_path") or "")).resolve() != Path(receipt["source_stl_path"]):
                raise ValueError("source mismatch")
            if receipt["mesh_quality"]["validity"]["status"] != "valid":
                raise ValueError("invalid mesh")
        except (OSError, ValueError, KeyError, TypeError):
            return {"ok": False, "status": "blocked", "failure_code": "CALCULIX_PREPARED_INPUT_MISMATCH"}
        return dict(receipt)

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
        serializable = {key: value for key, value in data.items() if not key.startswith("_")}
        request_path.write_text(json.dumps({"schema": "calculix_request.v1", "payload": serializable, "inp_path": str(inp_path)}, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
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
        computation_limits = self._computation_limits(data)
        completed = self._run_process(
            [ccx, job_name], workdir=workdir, payload=data, phase="solve",
            env=self._subprocess_env(threads=computation_limits.get("threads"),
                                     equation_solver_threads=computation_limits.get("equation_solver_threads")),
            timeout=computation_limits["timeout_s"],
        )
        ok = completed["status"] == "completed"
        return {
            **completed,
            "ok": ok,
            "tool": "calculix.solve",
            "status": "failed" if completed["status"] == "timeout" else completed["status"],
            "inp_path": str(inp_path),
            "request_path": prepared["request_path"],
            "dat_path": str(dat_path) if dat_path.exists() else "",
            "frd_path": str(frd_path) if frd_path.exists() else "",
            "computation_limits": computation_limits,
            "failure_code": None if ok else {
                "timeout": "CALCULIX_TIMEOUT", "cancelled": "CALCULIX_CANCELLED",
            }.get(completed["status"], "CALCULIX_SOLVE_FAILED"),
        }

    def postprocess(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        inp_path = Path(str(data.get("inp_path") or "")).expanduser() if data.get("inp_path") else None
        dat_path = Path(str(data.get("dat_path") or "")).expanduser() if data.get("dat_path") else None
        frd_path = Path(str(data.get("frd_path") or "")).expanduser() if data.get("frd_path") else None
        available = bool(dat_path and dat_path.exists()) or bool(frd_path and frd_path.exists())
        field_manifest: dict[str, Any] = {}
        field_selection: dict[str, Any] = {}
        if inp_path and inp_path.is_file() and frd_path and frd_path.is_file():
            try:
                selected_frd = frd_path
                if frd_path.stat().st_size > MAX_FIELD_FILE_BYTES:
                    selected_frd = frd_path.with_name(f"{frd_path.stem}.last-frame.frd")
                    field_selection = select_last_complete_frame(frd_path, selected_frd, max_bytes=MAX_FIELD_FILE_BYTES)
                field_manifest = postprocess_fields(inp_path, selected_frd, frd_path.parent / f"{frd_path.stem}.fields")
                if field_selection:
                    field_manifest["field_selection"] = field_selection
                    if field_manifest.get("field_asset_path"):
                        Path(field_manifest["field_asset_path"]).write_text(json.dumps(field_manifest, separators=(",", ":"), allow_nan=False), encoding="utf-8")
            except _FieldError as exc:
                field_manifest = {"status": "failed", "failure_code": exc.code, "errors": [exc.detail]}
            except OSError as exc:
                field_manifest = {"status": "failed", "failure_code": "CALCULIX_FIELD_IO_FAILED", "errors": [str(exc)]}
        field_status = str(field_manifest.get("status") or "unavailable")
        return {
            "ok": available,
            "tool": "calculix.postprocess",
            "status": "postprocessed" if field_status == "complete" else "partial" if available else "unavailable",
            "inp_path": str(inp_path) if inp_path and inp_path.exists() else "",
            "dat_path": str(dat_path) if dat_path and dat_path.exists() else "",
            "frd_path": str(frd_path) if frd_path and frd_path.exists() else "",
            "curve_json_path": "",
            "field_status": field_status,
            "field_failure_code": field_manifest.get("failure_code") or (
                "CALCULIX_FIELD_INPUTS_UNAVAILABLE" if available and not field_manifest else None
            ),
            "field_manifest": field_manifest,
            "field_selection": field_selection,
            "field_asset_path": str(field_manifest.get("field_asset_path") or ""),
            "geometry_path": str(field_manifest.get("geometry_path") or ""),
            "frames_path": str(field_manifest.get("frames_path") or ""),
            "mesh_evidence": field_manifest.get("mesh_evidence") or {},
            "failure_code": None if available else "CALCULIX_RESULT_ARTIFACTS_UNAVAILABLE",
        }

    def run_job(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        if str(data.get("analysis_type") or "").strip().lower() == "quasistatic_compression":
            prepared = self._validate_prepared(data) if "prepared_input" in data else self.prepare_quasistatic_input(data)
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
                        fields = self.postprocess(solved)
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
                            "field_asset_path": fields.get("field_asset_path", ""),
                            "geometry_path": fields.get("geometry_path", ""),
                            "frames_path": fields.get("frames_path", ""),
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
                            "field_status": fields.get("field_status", "unavailable"),
                            "field_failure_code": fields.get("field_failure_code"),
                            "field_manifest": fields.get("field_manifest", {}),
                            "mesh_evidence": fields.get("mesh_evidence", {}),
                            "computation_limits": solved.get("computation_limits", self._computation_limits(data)),
                            "artifacts": artifacts,
                            "prepared": prepared,
                            "solve": solved,
                            "failure_code": solved.get("failure_code") or "CALCULIX_ENDPOINT_NOT_REACHED",
                            "step_trace": [
                                {"step": "MESH_AND_PREPARE", "status": "ok"},
                                {"step": "SOLVE", "status": "partial", "detail": solved.get("failure_code")},
                                {"step": "POSTPROCESS", "status": "partial"},
                                {
                                    "step": "FIELD_POSTPROCESS",
                                    "status": fields.get("field_status", "unavailable"),
                                    "detail": fields.get("field_failure_code"),
                                },
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
            fields = self.postprocess(solved)
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
                "field_asset_path": fields.get("field_asset_path", ""),
                "geometry_path": fields.get("geometry_path", ""),
                "frames_path": fields.get("frames_path", ""),
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
                "field_status": fields.get("field_status", "unavailable"),
                "field_failure_code": fields.get("field_failure_code"),
                "field_manifest": fields.get("field_manifest", {}),
                "mesh_evidence": fields.get("mesh_evidence", {}),
                "computation_limits": solved.get("computation_limits", self._computation_limits(data)),
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
                    {
                        "step": "FIELD_POSTPROCESS",
                        "status": fields.get("field_status", "unavailable"),
                        "detail": fields.get("field_failure_code"),
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
