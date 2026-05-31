"""Unit tests for the optional FEniCSx Device Bridge."""

from __future__ import annotations

from pathlib import Path

from device_bridges.fenicsx_bridge import FEniCSxBridge, FEniCSxBridgeConfig


def test_fenicsx_bridge_deterministic_template_writes_artifacts_and_cache(tmp_path: Path) -> None:
    bridge = FEniCSxBridge(
        FEniCSxBridgeConfig(
            enabled=True,
            mode="test",
            execution_backend="deterministic",
            artifact_dir=tmp_path / "fenicsx",
        )
    )
    payload = {
        "run_id": "run-fem",
        "experiment_id": "exp-fem",
        "specimen_id": "specimen-fem",
        "specimen_size_mm": [20.0, 20.0, 20.0],
        "material": {"elastic_modulus_mpa": 1800.0, "poisson_ratio": 0.35, "yield_strength_mpa": 35.0},
        "loading": {"load_type": "cyclic_compression", "load_max_n": 500.0, "load_min_ratio": 0.1, "cycles": 10, "frequency_hz": 1.0},
        "design_parameters": {"geometry_type": "gyroid", "relative_density": 0.32, "wall_thickness_mm": 1.2, "cell_size_mm": 5.0},
    }

    first = bridge.run_linear_elasticity(payload)
    second = bridge.run_linear_elasticity(payload)

    assert first["ok"] is True
    assert first["schema"] == "fem_result.v1"
    assert first["solver_backend"] == "deterministic_fenicsx_template"
    assert first["request"]["runtime_solver_enabled"] is False
    assert first["request"]["active_execution_backend"] == "deterministic"
    assert first["metrics"]["predicted_peak_force_N"] == 500.0
    assert first["fidelity_record"]["fidelity"] == "fem_low"
    assert Path(first["artifacts"]["fem_request"]).exists()
    assert Path(first["artifacts"]["fem_result"]).exists()
    assert Path(first["artifacts"]["fem_cache_manifest"]).exists()
    assert second["cache_status"] == "cache_hit_exact"


def test_fenicsx_bridge_runs_actual_dolfinx_template_when_conda_available(tmp_path: Path) -> None:
    import shutil
    import subprocess

    conda = shutil.which("conda")
    if not conda:
        import pytest

        pytest.skip("conda is not available")
    probe = subprocess.run(
        [conda, "run", "-n", "fenicsx", "python", "-c", "import dolfinx"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if probe.returncode != 0:
        import pytest

        pytest.skip("fenicsx conda environment is not available")

    bridge = FEniCSxBridge(
        FEniCSxBridgeConfig(
            enabled=True,
            mode="test",
            execution_backend="conda",
            runtime_solver_enabled=True,
            allow_deterministic_fallback=False,
            timeout_sec=90,
            artifact_dir=tmp_path / "fenicsx",
            solver_script_path=Path("scripts/fenicsx_linear_elasticity_template.py").resolve(),
        )
    )
    payload = {
        "run_id": "run-real-fem",
        "experiment_id": "exp-real-fem",
        "specimen_id": "specimen-real-fem",
        "specimen_size_mm": [10.0, 10.0, 10.0],
        "mesh_size_mm": 5.0,
        "material": {"elastic_modulus_mpa": 1800.0, "poisson_ratio": 0.35, "yield_strength_mpa": 35.0},
        "loading": {"load_type": "cyclic_compression", "load_max_n": 100.0, "load_min_ratio": 0.1, "cycles": 5},
        "design_parameters": {"geometry_type": "gyroid", "relative_density": 0.32, "wall_thickness_mm": 1.2, "cell_size_mm": 5.0},
        "force_rerun": True,
    }

    result = bridge.run_linear_elasticity(payload)

    assert result["ok"] is True
    assert result["solver_backend"] == "dolfinx_linear_elasticity_template"
    assert result["request"]["runtime_solver_enabled"] is True
    assert result["request"]["active_execution_backend"] == "conda"
    assert result["solver_output"]["schema"] == "fenicsx_solver_output.v1"
    assert result["metrics"]["max_von_mises_MPa"] > 0
    assert result["metrics"]["max_displacement_mm"] > 0
    assert result["metrics"]["solver_converged"] is True
    assert Path(result["artifacts"]["fenicsx_solver_output"]).exists()
    assert Path(result["artifacts"]["solver_xdmf"]).exists()


def test_fenicsx_bridge_runtime_solver_can_be_enabled_per_payload(tmp_path: Path) -> None:
    bridge = FEniCSxBridge(
        FEniCSxBridgeConfig(
            enabled=True,
            mode="test",
            execution_backend="conda",
            runtime_solver_enabled=False,
            artifact_dir=tmp_path / "fenicsx",
        )
    )
    payload = {
        "run_id": "run-toggle",
        "experiment_id": "exp-toggle",
        "specimen_id": "specimen-toggle",
        "specimen_size_mm": [10.0, 10.0, 10.0],
        "execution_backend": "deterministic",
        "runtime_solver_enabled": True,
        "force_rerun": True,
    }

    result = bridge.run_linear_elasticity(payload)

    assert result["ok"] is True
    assert result["solver_backend"] == "deterministic_fenicsx_template"
    assert result["request"]["runtime_solver_enabled"] is True
    assert result["request"]["active_execution_backend"] == "deterministic"


def test_fenicsx_bridge_set_runtime_solver_updates_bridge_state(tmp_path: Path) -> None:
    bridge = FEniCSxBridge(
        FEniCSxBridgeConfig(
            enabled=True,
            mode="test",
            execution_backend="auto",
            runtime_solver_enabled=False,
            artifact_dir=tmp_path / "fenicsx",
        )
    )

    updated = bridge.set_runtime_solver({"enabled": True, "execution_backend": "deterministic"})
    result = bridge.run_linear_elasticity({"specimen_id": "set-runtime", "force_rerun": True})
    disabled = bridge.set_runtime_solver({"enabled": False})

    assert updated["ok"] is True
    assert updated["runtime_solver_enabled"] is True
    assert updated["execution_backend"] == "deterministic"
    assert result["request"]["runtime_solver_enabled"] is True
    assert result["request"]["active_execution_backend"] == "deterministic"
    assert disabled["runtime_solver_enabled"] is False
