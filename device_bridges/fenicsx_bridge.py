"""
File purpose:
- Optional FEniCSx/DOLFINx bridge for Analysis Agent FEM evidence.

Key classes/functions:
- FEniCSxBridgeConfig
- FEniCSxBridge

Inputs/outputs:
- Input: validated FEM request payload from Analysis Agent or CAE workspace
- Output: FEM result, cache manifest, metrics, and artifacts

Dependencies:
- hashlib/json/math/shutil/subprocess/pathlib
- device_bridges.base_bridge.BaseBridge

Modification guide:
- Safe places to edit: deterministic template metrics and cache metadata.
- Risky places to edit: tool names and result keys consumed by Analysis/BO.
- Related files: mcp_tools/fenicsx_tools.py, agents/analysis_agent.py.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from device_bridges.base_bridge import BaseBridge
from utils.paths import resolve_path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: Any, default: str = "specimen") -> str:
    text = str(value or default)
    slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text).strip("_")
    return slug[:120] or default


@dataclass(slots=True)
class FEniCSxBridgeConfig:
    """Configuration for the FEniCSx bridge."""

    enabled: bool = True
    mode: str = "test"
    execution_backend: str = "auto"  # auto | deterministic | conda | docker
    runtime_solver_enabled: bool = False
    require_runtime_in_live: bool = False
    conda_env: str = "fenicsx"
    docker_image: str = "dolfinx/dolfinx:stable"
    timeout_sec: float = 120.0
    artifact_dir: Path = field(default_factory=lambda: resolve_path("artifacts/fenicsx"))
    solver_script_path: Path = field(default_factory=lambda: resolve_path("scripts/fenicsx_linear_elasticity_template.py"))
    allow_deterministic_fallback: bool = True
    template_version: str = "atr_linear_elasticity_template_v1"
    default_material: dict[str, float] = field(
        default_factory=lambda: {
            "elastic_modulus_mpa": 1800.0,
            "poisson_ratio": 0.35,
            "yield_strength_mpa": 35.0,
        }
    )
    default_loading: dict[str, float | int | str] = field(
        default_factory=lambda: {
            "load_type": "cyclic_compression",
            "load_max_n": 500.0,
            "load_min_ratio": 0.1,
            "cycles": 10,
            "frequency_hz": 1.0,
        }
    )

    @staticmethod
    def _bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "n", "off", "disabled"}:
            return False
        return default

    @classmethod
    def from_devices_config(
        cls,
        devices_config: dict[str, Any] | None = None,
        *,
        repo_root: Path | None = None,
    ) -> "FEniCSxBridgeConfig":
        raw = devices_config or {}
        devices = raw.get("devices", raw) if isinstance(raw, dict) else {}
        fenics_raw = devices.get("fenicsx", {}) if isinstance(devices, dict) and isinstance(devices.get("fenicsx"), dict) else {}
        cae_raw = devices.get("cae", {}) if isinstance(devices, dict) and isinstance(devices.get("cae"), dict) else {}
        nested = cae_raw.get("fenicsx") if isinstance(cae_raw.get("fenicsx"), dict) else {}
        merged = {**nested, **fenics_raw}
        defaults = cls()
        artifact = Path(str(merged.get("artifact_dir", defaults.artifact_dir))).expanduser()
        if not artifact.is_absolute():
            artifact = (repo_root or resolve_path(".")).joinpath(artifact).resolve()
        solver_script = Path(str(merged.get("solver_script_path", defaults.solver_script_path))).expanduser()
        if not solver_script.is_absolute():
            solver_script = (repo_root or resolve_path(".")).joinpath(solver_script).resolve()
        material = dict(defaults.default_material)
        if isinstance(merged.get("default_material"), dict):
            material.update(merged["default_material"])
        if isinstance(cae_raw.get("default_material"), dict):
            material.update(cae_raw["default_material"])
        loading = dict(defaults.default_loading)
        if isinstance(cae_raw.get("default_loading"), dict):
            loading.update(cae_raw["default_loading"])
        if isinstance(merged.get("default_loading"), dict):
            loading.update(merged["default_loading"])
        return cls(
            enabled=bool(merged.get("enabled", defaults.enabled)),
            mode=str(merged.get("mode", cae_raw.get("mode", defaults.mode))),
            execution_backend=str(merged.get("execution_backend", defaults.execution_backend)).lower(),
            runtime_solver_enabled=cls._bool(merged.get("runtime_solver_enabled", defaults.runtime_solver_enabled), defaults.runtime_solver_enabled),
            require_runtime_in_live=bool(merged.get("require_runtime_in_live", defaults.require_runtime_in_live)),
            conda_env=str(merged.get("conda_env", defaults.conda_env)),
            docker_image=str(merged.get("docker_image", defaults.docker_image)),
            timeout_sec=float(merged.get("timeout_sec", defaults.timeout_sec)),
            artifact_dir=artifact,
            solver_script_path=solver_script,
            allow_deterministic_fallback=bool(merged.get("allow_deterministic_fallback", defaults.allow_deterministic_fallback)),
            template_version=str(merged.get("template_version", defaults.template_version)),
            default_material={key: float(value) for key, value in material.items()},
            default_loading={**loading},
        )


class FEniCSxBridge(BaseBridge):
    """Validated-template bridge for optional FEniCSx FEM evidence."""

    def __init__(self, config: FEniCSxBridgeConfig) -> None:
        self.config = config
        self._runtime_probe_cache: dict[str, Any] | None = None

    @staticmethod
    def defaults() -> dict[str, Any]:
        cfg = FEniCSxBridgeConfig()
        return {
            "execution_backend": cfg.execution_backend,
            "runtime_solver_enabled": cfg.runtime_solver_enabled,
            "conda_env": cfg.conda_env,
            "docker_image": cfg.docker_image,
            "solver_script_path": str(cfg.solver_script_path),
            "material": cfg.default_material,
            "loading": cfg.default_loading,
            "boundary_condition": "bottom_fixed_support",
            "loading_mode": "top_cyclic_loading",
            "specimen_size_mm": [20.0, 20.0, 20.0],
            "mesh_size_mm": 2.0,
        }

    @staticmethod
    def _bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "n", "off", "disabled"}:
            return False
        return default

    @staticmethod
    def _float(value: Any, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if math.isfinite(parsed) else default

    @staticmethod
    def _int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(1, parsed)

    @staticmethod
    def _vector3(value: Any, default: list[float]) -> list[float]:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return [max(FEniCSxBridge._float(value[i], default[i]), 1e-6) for i in range(3)]
        return list(default)

    def _runtime_probe(self, *, force: bool = False) -> dict[str, Any]:
        if self._runtime_probe_cache is not None and not force:
            return dict(self._runtime_probe_cache)
        conda = shutil.which("conda")
        docker = shutil.which("docker")
        probe: dict[str, Any] = {
            "conda": {"available": bool(conda), "path": conda or "", "env": self.config.conda_env, "import_ok": False},
            "docker": {"available": bool(docker), "path": docker or "", "image": self.config.docker_image, "import_ok": False},
        }
        if conda:
            try:
                proc = subprocess.run(
                    [
                        conda,
                        "run",
                        "-n",
                        self.config.conda_env,
                        "python",
                        "-c",
                        "import dolfinx, basix, ufl, ffcx; print(getattr(dolfinx, '__version__', 'unknown'))",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=min(max(self.config.timeout_sec, 5.0), 30.0),
                )
                probe["conda"].update(
                    {
                        "import_ok": proc.returncode == 0,
                        "returncode": proc.returncode,
                        "version": proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "",
                        "stderr_tail": proc.stderr.strip()[-300:],
                    }
                )
            except Exception as exc:
                probe["conda"].update({"import_ok": False, "error": f"{exc.__class__.__name__}: {exc}"})
        if docker:
            # Avoid pulling or running the image in health; image availability is checked lazily by run.
            probe["docker"].update({"import_ok": False, "note": "Docker runtime is available; image execution is lazy."})
        self._runtime_probe_cache = dict(probe)
        return probe

    def health(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = dict(payload or {})
        force_probe = self._bool(raw.get("force_probe", False), False)
        if self.config.runtime_solver_enabled or force_probe:
            probe = self._runtime_probe(force=force_probe)
        else:
            probe = {
                "conda": {"available": False, "import_ok": False, "skipped": "runtime_solver_enabled=false"},
                "docker": {"available": False, "import_ok": False, "skipped": "runtime_solver_enabled=false"},
            }
        return {
            "ok": self.config.enabled,
            "tool": "fenicsx.health",
            "status": "ready" if self.config.enabled else "disabled",
            "mode": self.config.mode,
            "execution_backend": self.config.execution_backend,
            "runtime_solver_enabled": self.config.runtime_solver_enabled,
            "artifact_dir": str(self.config.artifact_dir),
            "solver_script_path": str(self.config.solver_script_path),
            "allow_deterministic_fallback": self.config.allow_deterministic_fallback,
            "template_version": self.config.template_version,
            "runtime_probe": probe,
            "defaults": self.defaults(),
        }

    def set_runtime_solver(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = dict(payload or {})
        if "enabled" in raw:
            self.config.runtime_solver_enabled = self._bool(raw["enabled"], self.config.runtime_solver_enabled)
        elif "runtime_solver_enabled" in raw:
            self.config.runtime_solver_enabled = self._bool(raw["runtime_solver_enabled"], self.config.runtime_solver_enabled)

        if raw.get("execution_backend"):
            backend = str(raw["execution_backend"]).lower()
            if backend not in {"auto", "deterministic", "conda", "docker"}:
                return {
                    "ok": False,
                    "tool": "fenicsx.set_runtime_solver",
                    "status": "blocked",
                    "failure_code": "FENICSX_BACKEND_UNSUPPORTED",
                    "message": f"Unsupported execution_backend: {backend}",
                }
            self.config.execution_backend = backend

        if "allow_deterministic_fallback" in raw:
            self.config.allow_deterministic_fallback = self._bool(raw["allow_deterministic_fallback"], self.config.allow_deterministic_fallback)
        if "require_runtime_in_live" in raw:
            self.config.require_runtime_in_live = self._bool(raw["require_runtime_in_live"], self.config.require_runtime_in_live)
        if "timeout_sec" in raw:
            self.config.timeout_sec = self._float(raw["timeout_sec"], self.config.timeout_sec)

        if self._bool(raw.get("clear_probe_cache", True), True):
            self._runtime_probe_cache = None

        probe = self._runtime_probe(force=self._bool(raw.get("force_probe", False), False)) if self.config.runtime_solver_enabled else {
            "conda": {"available": False, "import_ok": False, "skipped": "runtime_solver_enabled=false"},
            "docker": {"available": False, "import_ok": False, "skipped": "runtime_solver_enabled=false"},
        }
        return {
            "ok": True,
            "tool": "fenicsx.set_runtime_solver",
            "status": "updated",
            "runtime_solver_enabled": self.config.runtime_solver_enabled,
            "execution_backend": self.config.execution_backend,
            "allow_deterministic_fallback": self.config.allow_deterministic_fallback,
            "require_runtime_in_live": self.config.require_runtime_in_live,
            "timeout_sec": self.config.timeout_sec,
            "runtime_probe": probe,
        }

    def _normalize_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        material = dict(self.config.default_material)
        if isinstance(payload.get("material"), dict):
            material.update(payload["material"])
        loading = dict(self.config.default_loading)
        if isinstance(payload.get("loading"), dict):
            loading.update(payload["loading"])
        for key in ("load_max_n", "load_max_N", "load_min_ratio", "cycles", "frequency_hz"):
            if key in payload:
                loading["load_max_n" if key == "load_max_N" else key] = payload[key]
        design = payload.get("design_parameters") if isinstance(payload.get("design_parameters"), dict) else {}
        size = self._vector3(payload.get("specimen_size_mm") or payload.get("size_mm"), [20.0, 20.0, 20.0])
        boundary = payload.get("boundary") if isinstance(payload.get("boundary"), dict) else {}
        return {
            "schema": "fem_request.v1",
            "specimen_id": str(payload.get("specimen_id") or "manual-specimen"),
            "stl_path": str(payload.get("stl_path") or ""),
            "specimen_size_mm": size,
            "mesh_size_mm": self._float(payload.get("mesh_size_mm"), 2.0),
            "material": {
                "elastic_modulus_mpa": self._float(material.get("elastic_modulus_mpa"), 1800.0),
                "poisson_ratio": self._float(material.get("poisson_ratio"), 0.35),
                "yield_strength_mpa": self._float(material.get("yield_strength_mpa"), 35.0),
            },
            "loading": {
                "load_type": str(loading.get("load_type") or "cyclic_compression"),
                "load_max_n": self._float(loading.get("load_max_n"), 500.0),
                "load_min_ratio": self._float(loading.get("load_min_ratio"), 0.1),
                "cycles": self._int(loading.get("cycles"), 10),
                "frequency_hz": self._float(loading.get("frequency_hz"), 1.0),
            },
            "boundary": {
                "bottom": str(boundary.get("bottom") or "fixed_support"),
                "top": str(boundary.get("top") or "cyclic_loading"),
            },
            "boundary_condition": str(payload.get("boundary_condition") or "bottom_fixed_support"),
            "loading_mode": str(payload.get("loading_mode") or "top_cyclic_loading"),
            "analysis_platens": payload.get("analysis_platens") if isinstance(payload.get("analysis_platens"), dict) else {"bottom": True, "top": True, "applies_to": "cae_only_not_generated_stl"},
            "design_parameters": {
                "geometry_type": str(design.get("geometry_type") or payload.get("geometry_type") or "gyroid"),
                "relative_density": self._float(design.get("relative_density", payload.get("relative_density")), 0.32),
                "wall_thickness_mm": self._float(design.get("wall_thickness_mm", payload.get("wall_thickness_mm")), 1.2),
                "cell_size_mm": self._float(design.get("cell_size_mm", payload.get("cell_size_mm")), 5.0),
            },
            "run_id": str(payload.get("run_id") or ""),
            "experiment_id": str(payload.get("experiment_id") or ""),
            "mode": str(payload.get("runtime_mode") or payload.get("mode") or self.config.mode),
            "template_version": self.config.template_version,
        }

    def _runtime_solver_enabled(self, payload: dict[str, Any]) -> bool:
        for key in ("runtime_solver_enabled", "use_runtime_solver", "enable_runtime_solver"):
            if key in payload:
                return self._bool(payload[key], self.config.runtime_solver_enabled)
        return self.config.runtime_solver_enabled

    def _backend_for_mode(self, payload: dict[str, Any], *, runtime_solver_enabled: bool) -> str:
        if not runtime_solver_enabled:
            return "deterministic"
        override = payload.get("execution_backend")
        if override:
            return str(override).lower()
        return self.config.execution_backend

    def _cache_key(self, request: dict[str, Any]) -> str:
        relevant = {
            key: request.get(key)
            for key in (
                "specimen_id",
                "stl_path",
                "specimen_size_mm",
                "mesh_size_mm",
                "material",
                "loading",
                "boundary",
                "boundary_condition",
                "loading_mode",
                "analysis_platens",
                "design_parameters",
                "template_version",
                "runtime_solver_enabled",
                "active_execution_backend",
            )
        }
        return hashlib.sha256(json.dumps(relevant, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()

    def _template_metrics(self, request: dict[str, Any], runtime_validated: bool) -> dict[str, Any]:
        size = request["specimen_size_mm"]
        material = request["material"]
        loading = request["loading"]
        design = request["design_parameters"]
        area = max(float(size[0]) * float(size[1]), 1e-6)
        height = max(float(size[2]), 1e-6)
        load_max = max(float(loading["load_max_n"]), 0.0)
        load_min = load_max * min(max(float(loading["load_min_ratio"]), 0.0), 1.0)
        cycles = max(int(loading["cycles"]), 1)
        rel_density = min(max(float(design.get("relative_density", 0.32)), 0.05), 0.90)
        wall = max(float(design.get("wall_thickness_mm", 1.2)), 0.05)
        cell = max(float(design.get("cell_size_mm", 5.0)), wall * 2.0)
        modulus = max(float(material["elastic_modulus_mpa"]), 1e-6)
        yield_strength = max(float(material["yield_strength_mpa"]), 1e-6)
        effective_modulus = modulus * max(0.035, rel_density**1.75)
        effective_yield = yield_strength * max(0.04, rel_density**1.45)
        tpms_factor = 1.0 + 0.35 * (wall / cell) + 0.55 * (1.0 - rel_density)
        nominal_stress = load_max / area
        max_von_mises = nominal_stress * tpms_factor / max(rel_density, 0.08)
        max_displacement = load_max * height / max(effective_modulus * area, 1e-9)
        stiffness = load_max / max(max_displacement, 1e-9)
        energy = 0.5 * load_max * max_displacement
        safety = effective_yield / max(max_von_mises, 1e-9)
        fatigue = min(1.0, (max_von_mises / max(effective_yield, 1e-9)) ** 3 * math.log10(cycles + 1.0) * 0.16)
        reaction_curve = []
        for index, scale in enumerate((0.0, 0.25, 0.5, 0.75, 1.0)):
            reaction_curve.append(
                {
                    "step": index,
                    "displacement_mm": round(max_displacement * scale, 9),
                    "reaction_force_N": round(load_max * scale, 6),
                }
            )
        return {
            "predicted_peak_force_N": round(load_max, 6),
            "predicted_initial_stiffness_N_per_mm": round(stiffness, 6),
            "predicted_energy_absorption_mJ": round(energy, 6),
            "max_displacement_mm": round(max_displacement, 9),
            "max_von_mises_MPa": round(max_von_mises, 6),
            "stress_concentration_factor": round(tpms_factor, 6),
            "reaction_force_curve": reaction_curve,
            "solver_converged": True,
            "mesh_quality_score": round(max(0.35, min(0.98, 1.0 - request["mesh_size_mm"] / max(min(size), 1e-6))), 6),
            "fem_confidence": 0.78 if runtime_validated else 0.52,
            "effective_modulus_MPa": round(effective_modulus, 6),
            "effective_yield_strength_MPa": round(effective_yield, 6),
            "nominal_top_stress_MPa": round(nominal_stress, 6),
            "safety_factor_yield": round(safety, 6),
            "fatigue_damage_proxy": round(fatigue, 6),
            "structural_score": round(max(0.0, min(1.0, (1.0 - fatigue) * min(safety / 2.0, 1.0))), 6),
            "load_min_N": round(load_min, 6),
            "cycles": cycles,
        }

    def _artifact_paths(self, request: dict[str, Any], cache_key: str) -> dict[str, Path]:
        specimen = _safe_slug(request.get("specimen_id"))
        run = _safe_slug(request.get("run_id") or "manual-run", "manual-run")
        base = self.config.artifact_dir / run / specimen
        base.mkdir(parents=True, exist_ok=True)
        stem = f"{specimen}_{cache_key[:12]}"
        return {
            "request": base / f"{stem}_fem_request.json",
            "result": base / f"{stem}_fem_result.json",
            "solver_output": base / f"{stem}_fenicsx_solver_output.json",
            "cache_manifest": base / f"{stem}_fem_cache_manifest.json",
        }

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _conda_solver_command(self, request_path: Path, output_path: Path) -> list[str]:
        conda = shutil.which("conda") or "conda"
        return [
            conda,
            "run",
            "-n",
            self.config.conda_env,
            "python",
            str(self.config.solver_script_path),
            str(request_path),
            str(output_path),
        ]

    def _docker_solver_command(self, request_path: Path, output_path: Path) -> list[str]:
        docker = shutil.which("docker") or "docker"
        run_dir = request_path.parent.resolve()
        script_path = self.config.solver_script_path.resolve()
        return [
            docker,
            "run",
            "--rm",
            "--entrypoint",
            "python3",
            "-v",
            f"{script_path}:/work/template.py:ro",
            "-v",
            f"{run_dir}:/work/run",
            "-w",
            "/work",
            self.config.docker_image,
            "/work/template.py",
            f"/work/run/{request_path.name}",
            f"/work/run/{output_path.name}",
        ]

    def _execute_solver_template(self, request: dict[str, Any], paths: dict[str, Path], backend: str) -> dict[str, Any]:
        script_path = self.config.solver_script_path
        if not script_path.exists():
            return {
                "ok": False,
                "status": "error",
                "failure_code": "FENICSX_SOLVER_TEMPLATE_MISSING",
                "message": f"Solver template does not exist: {script_path}",
            }
        self._write_json(paths["request"], request)
        output_path = paths["solver_output"]
        if output_path.exists():
            output_path.unlink()
        command_backend = "docker" if backend == "docker" else "conda"
        command = self._docker_solver_command(paths["request"], output_path) if command_backend == "docker" else self._conda_solver_command(paths["request"], output_path)
        try:
            proc = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(float(self.config.timeout_sec), 5.0),
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": "error",
                "failure_code": "FENICSX_SOLVER_EXECUTION_EXCEPTION",
                "message": f"{exc.__class__.__name__}: {exc}",
                "backend": command_backend,
                "command_preview": command[:8],
            }
        if proc.returncode != 0:
            return {
                "ok": False,
                "status": "error",
                "failure_code": "FENICSX_SOLVER_PROCESS_FAILED",
                "message": "FEniCSx solver process returned non-zero exit code.",
                "backend": command_backend,
                "returncode": proc.returncode,
                "stdout_tail": proc.stdout.strip()[-1200:],
                "stderr_tail": proc.stderr.strip()[-2000:],
                "command_preview": command[:8],
            }
        if not output_path.exists():
            return {
                "ok": False,
                "status": "error",
                "failure_code": "FENICSX_SOLVER_OUTPUT_MISSING",
                "message": f"Solver completed but did not write {output_path}",
                "backend": command_backend,
                "stdout_tail": proc.stdout.strip()[-1200:],
                "stderr_tail": proc.stderr.strip()[-2000:],
            }
        try:
            solver_output = self._read_json(output_path)
        except Exception as exc:
            return {
                "ok": False,
                "status": "error",
                "failure_code": "FENICSX_SOLVER_OUTPUT_INVALID",
                "message": f"{exc.__class__.__name__}: {exc}",
                "backend": command_backend,
                "output_path": str(output_path),
            }
        solver_output.setdefault("ok", True)
        solver_output.setdefault("backend", command_backend)
        solver_output["process"] = {
            "backend": command_backend,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout.strip()[-1200:],
            "stderr_tail": proc.stderr.strip()[-1200:],
        }
        return solver_output

    def _build_fem_result(
        self,
        *,
        request: dict[str, Any],
        paths: dict[str, Path],
        cache_key: str,
        probe: dict[str, Any],
        solver_backend: str,
        metrics: dict[str, Any],
        solver_output: dict[str, Any] | None = None,
        fallback_reason: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifacts = {
            "fem_request": str(paths["request"]),
            "fem_result": str(paths["result"]),
            "fem_cache_manifest": str(paths["cache_manifest"]),
        }
        if paths.get("solver_output"):
            artifacts["fenicsx_solver_output"] = str(paths["solver_output"])
        if isinstance(solver_output, dict):
            solver_artifacts = solver_output.get("artifacts") if isinstance(solver_output.get("artifacts"), dict) else {}
            for key, value in solver_artifacts.items():
                if value:
                    artifacts[f"solver_{key}"] = str(value)
        confidence = float(metrics.get("fem_confidence", 0.5))
        result = {
            "ok": True,
            "tool": "fenicsx.run_linear_elasticity",
            "schema": "fem_result.v1",
            "status": "completed",
            "mode": request.get("mode", self.config.mode),
            "solver_backend": solver_backend,
            "template_version": self.config.template_version,
            "specimen_id": request["specimen_id"],
            "run_id": request.get("run_id", ""),
            "experiment_id": request.get("experiment_id", ""),
            "cache_key": cache_key,
            "cache_status": "cache_miss_computed",
            "runtime_probe": probe,
            "request": request,
            "metrics": metrics,
            "fem_metrics": metrics,
            "solver_output": solver_output or {},
            "fallback_reason": fallback_reason or {},
            "artifacts": artifacts,
            "fidelity_record": {
                "fidelity": "fem_low",
                "source": solver_backend,
                "cost_class": "cheap_compute",
                "metrics": metrics,
                "uncertainty": round(1.0 - confidence, 4),
                "cache_key": cache_key,
            },
            "created_at": _now_iso(),
            "step_trace": [
                {"step": "NORMALIZE", "status": "ok", "detail": "fem_request.v1"},
                {"step": "RUNTIME_PROBE", "status": "ok" if solver_backend.startswith("dolfinx") else "warning", "detail": solver_backend},
                {"step": "SOLVE", "status": "ok", "detail": "validated DOLFINx linear-elasticity template" if solver_backend.startswith("dolfinx") else "deterministic fallback template"},
                {"step": "POSTPROCESS", "status": "ok", "detail": "fem_result.v1 metrics"},
            ],
            "failure_code": None,
        }
        if fallback_reason:
            result["step_trace"].insert(2, {"step": "SOLVER_FALLBACK", "status": "warning", "detail": fallback_reason.get("failure_code", "fallback")})
        return result

    def run_linear_elasticity(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {
                "ok": False,
                "tool": "fenicsx.run_linear_elasticity",
                "status": "blocked",
                "failure_code": "FENICSX_BRIDGE_DISABLED",
            }
        raw_payload = dict(payload or {})
        request = self._normalize_request(raw_payload)
        mode = str(request.get("mode") or self.config.mode)
        runtime_solver_enabled = self._runtime_solver_enabled(raw_payload)
        backend = self._backend_for_mode(raw_payload, runtime_solver_enabled=runtime_solver_enabled)
        request["runtime_solver_enabled"] = runtime_solver_enabled
        request["active_execution_backend"] = backend
        cache_key = self._cache_key(request)
        paths = self._artifact_paths(request, cache_key)
        force_rerun = bool(raw_payload.get("force_rerun"))
        if paths["result"].exists() and paths["cache_manifest"].exists() and not force_rerun:
            cached = json.loads(paths["result"].read_text(encoding="utf-8"))
            cached["cache_status"] = "cache_hit_exact"
            cached["step_trace"] = list(cached.get("step_trace", [])) + [
                {"step": "CACHE", "status": "ok", "detail": "cache_hit_exact"}
            ]
            return cached

        probe = {
            "conda": {"available": False, "import_ok": False, "skipped": "execution_backend=deterministic"},
            "docker": {"available": False, "import_ok": False, "skipped": "execution_backend=deterministic"},
        }
        solver_output: dict[str, Any] | None = None
        fallback_reason: dict[str, Any] | None = None
        solver_backend = "deterministic_fenicsx_template"
        runtime_validated = False
        actual_backend = "deterministic"

        if backend != "deterministic":
            probe = self._runtime_probe(force=False)
            conda_ok = bool(probe.get("conda", {}).get("import_ok"))
            docker_ok = bool(probe.get("docker", {}).get("available"))
            if backend == "conda" or (backend == "auto" and conda_ok):
                actual_backend = "conda"
            elif backend == "docker" or (backend == "auto" and docker_ok):
                actual_backend = "docker"
            else:
                actual_backend = "unavailable"
            if actual_backend in {"conda", "docker"}:
                solver_output = self._execute_solver_template(request, paths, actual_backend)
                runtime_validated = bool(solver_output.get("ok"))
                if runtime_validated:
                    raw_metrics = solver_output.get("metrics") if isinstance(solver_output.get("metrics"), dict) else {}
                    metrics = dict(raw_metrics)
                    solver_backend = str(solver_output.get("solver_backend") or f"{actual_backend}_dolfinx_linear_elasticity_template")
                else:
                    fallback_reason = dict(solver_output)
            else:
                fallback_reason = {
                    "ok": False,
                    "status": "blocked",
                    "failure_code": "FENICSX_RUNTIME_UNAVAILABLE",
                    "message": "No usable conda/docker FEniCSx runtime was available.",
                    "backend": backend,
                }

        if mode == "live" and self.config.require_runtime_in_live and not runtime_validated:
            return {
                "ok": False,
                "tool": "fenicsx.run_linear_elasticity",
                "mode": mode,
                "status": "blocked",
                "failure_code": (fallback_reason or {}).get("failure_code") or "FENICSX_RUNTIME_REQUIRED",
                "runtime_probe": probe,
                "cache_key": cache_key,
                "solver_failure": fallback_reason or {},
            }

        if not runtime_validated:
            if backend in {"conda", "docker"} and not self.config.allow_deterministic_fallback:
                return {
                    "ok": False,
                    "tool": "fenicsx.run_linear_elasticity",
                    "mode": mode,
                    "status": "error",
                    "failure_code": (fallback_reason or {}).get("failure_code") or "FENICSX_SOLVER_FAILED",
                    "runtime_probe": probe,
                    "cache_key": cache_key,
                    "solver_failure": fallback_reason or {},
                }
            metrics = self._template_metrics(request, runtime_validated=False)
            solver_backend = "deterministic_fenicsx_template"
        # Keep a normalized request artifact for both real-solver and fallback paths.
        self._write_json(paths["request"], request)

        result = self._build_fem_result(
            request=request,
            paths=paths,
            cache_key=cache_key,
            probe=probe,
            solver_backend=solver_backend,
            metrics=metrics,
            solver_output=solver_output if runtime_validated else None,
            fallback_reason=fallback_reason if not runtime_validated else None,
        )
        manifest = {
            "schema": "fem_cache_manifest.v1",
            "cache_key": cache_key,
            "hit": False,
            "cache_status": "cache_miss_computed",
            "reuse_reason": "new request computed by validated FEniCSx template" if runtime_validated else "new request computed by deterministic fallback template",
            "invalidations": [],
            "source_result": str(paths["result"]),
            "solver": {"backend": solver_backend, "template_version": self.config.template_version, "actual_backend": actual_backend},
            "fallback_reason": fallback_reason or {},
            "created_at": result["created_at"],
        }
        self._write_json(paths["cache_manifest"], manifest)
        self._write_json(paths["result"], result)
        return result

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command in {"health", "fenicsx.health"}:
            return self.health(payload)
        if command in {"set_runtime_solver", "configure_runtime", "fenicsx.set_runtime_solver", "fenicsx.configure_runtime"}:
            return self.set_runtime_solver(payload)
        if command in {"run_linear_elasticity", "run_fem", "fenicsx.run_linear_elasticity", "fenicsx.run_fem"}:
            return self.run_linear_elasticity(payload)
        return {
            "ok": False,
            "tool": f"fenicsx.{command}",
            "status": "blocked",
            "failure_code": "FENICSX_COMMAND_UNSUPPORTED",
            "message": f"Unsupported FEniCSx command: {command}",
        }
