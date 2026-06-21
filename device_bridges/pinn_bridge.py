"""
File purpose:
- Improvement 15 PINN bridge contract for surrogate model registry, training, and inference.

Key classes/functions:
- PINNBridgeConfig
- PINNBridge

Inputs/outputs:
- Input: UTM/FEA evidence payloads, model registry metadata, optional active model id.
- Output: dataset/model/prediction status with explicit unavailable states.

Dependencies:
- utils.paths.resolve_path

Modification guide:
- Safe places to edit: registry metadata, dataset serialization, prediction adapters.
- Risky places to edit: failure codes and return keys consumed by Analysis/GUI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from device_bridges.base_bridge import BaseBridge
from utils.paths import resolve_path


@dataclass(slots=True)
class PINNBridgeConfig:
    """Configuration for optional PINN surrogate workflows."""

    enabled: bool = True
    mode: str = "test"
    active_model_id: str = ""
    runtime_training_enabled: bool = False
    artifact_dir: Path = field(default_factory=lambda: resolve_path("artifacts/pinn"))

    @classmethod
    def from_devices_config(cls, devices_config: dict[str, Any] | None = None, *, repo_root: Path | None = None) -> "PINNBridgeConfig":
        raw = devices_config or {}
        devices = raw.get("devices", raw) if isinstance(raw, dict) else {}
        config: dict[str, Any] = {}
        if isinstance(devices, dict) and isinstance(devices.get("pinn"), dict):
            config.update(devices["pinn"])
        base_root = repo_root or resolve_path(".")
        artifact = Path(str(config.get("artifact_dir", "artifacts/pinn"))).expanduser()
        if not artifact.is_absolute():
            artifact = base_root.joinpath(artifact).resolve()
        return cls(
            enabled=bool(config.get("enabled", True)),
            mode=str(config.get("mode", "test")),
            active_model_id=str(config.get("active_model_id", "")),
            runtime_training_enabled=bool(config.get("runtime_training_enabled", False)),
            artifact_dir=artifact,
        )


class PINNBridge(BaseBridge):
    """Expose PINN contract endpoints without pretending a model exists."""

    def __init__(self, config: PINNBridgeConfig) -> None:
        self.config = config
        self.config.artifact_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _slug(value: Any, default: str = "pinn_job") -> str:
        text = str(value or default)
        slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text).strip("_")
        return slug[:96] or default

    def _registry_path(self) -> Path:
        return self.config.artifact_dir / "model_registry.json"

    def _load_registry(self) -> dict[str, Any]:
        path = self._registry_path()
        if not path.exists():
            return {"schema": "pinn_registry.v1", "models": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"schema": "pinn_registry.v1", "models": {}}
        return data if isinstance(data, dict) else {"schema": "pinn_registry.v1", "models": {}}

    def _save_registry(self, registry: dict[str, Any]) -> Path:
        path = self._registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(registry, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
        return path

    def health(self) -> dict[str, Any]:
        registry = self._load_registry()
        models = registry.get("models") if isinstance(registry.get("models"), dict) else {}
        active_model_id = self.config.active_model_id
        return {
            "ok": True,
            "tool": "pinn.health",
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "runtime_training_enabled": self.config.runtime_training_enabled,
            "active_model_id": active_model_id,
            "active_model_available": bool(active_model_id and active_model_id in models),
            "model_count": len(models),
            "artifact_dir": str(self.config.artifact_dir),
            "registry_path": str(self._registry_path()),
        }

    def build_dataset(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        specimen_id = self._slug(data.get("specimen_id"), "specimen")
        dataset_id = self._slug(data.get("dataset_id") or f"dataset-{specimen_id}", "dataset")
        path = self.config.artifact_dir / "datasets" / f"{dataset_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": "pinn_dataset.v1",
                    "dataset_id": dataset_id,
                    "specimen_id": specimen_id,
                    "utm_curve": data.get("utm_curve") or data.get("utm_records") or [],
                    "fea_records": data.get("fea_records") or [],
                    "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
                },
                indent=2,
                ensure_ascii=True,
                default=str,
            ),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "tool": "pinn.dataset.build",
            "status": "dataset_ready",
            "dataset_id": dataset_id,
            "dataset_path": str(path),
            "step_trace": [{"step": "BUILD_DATASET", "status": "ok"}],
        }

    def train(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        if not self.config.enabled:
            return {"ok": False, "tool": "pinn.train", "status": "blocked", "failure_code": "PINN_BRIDGE_DISABLED"}
        if not bool(data.get("runtime_training_enabled", self.config.runtime_training_enabled)):
            return {
                "ok": False,
                "tool": "pinn.train",
                "status": "blocked",
                "failure_code": "PINN_RUNTIME_TRAINING_DISABLED",
                "message": "PINN training is optional; enable runtime_training_enabled only for an explicit training run.",
            }
        model_id = self._slug(data.get("model_id") or "pinn-model", "pinn-model")
        registry = self._load_registry()
        models = registry.setdefault("models", {})
        models[model_id] = {
            "schema": "pinn_model_record.v1",
            "model_id": model_id,
            "family": data.get("family", "pinn"),
            "train_dataset_ids": data.get("train_dataset_ids", []),
            "metrics": data.get("metrics", {}),
            "checkpoints": data.get("checkpoints", {}),
            "deployment_meta": {"status": "registered", "mode": self.config.mode},
        }
        registry_path = self._save_registry(registry)
        return {
            "ok": True,
            "tool": "pinn.train",
            "status": "registered",
            "model_id": model_id,
            "registry_path": str(registry_path),
            "step_trace": [{"step": "REGISTER_MODEL", "status": "ok"}],
        }

    def predict(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        if not self.config.enabled:
            return {"ok": False, "tool": "pinn.predict", "status": "blocked", "failure_code": "PINN_BRIDGE_DISABLED"}
        registry = self._load_registry()
        models = registry.get("models") if isinstance(registry.get("models"), dict) else {}
        model_id = str(data.get("model_id") or self.config.active_model_id or "")
        if not model_id or model_id not in models:
            return {
                "ok": False,
                "tool": "pinn.predict",
                "status": "unavailable",
                "failure_code": "PINN_MODEL_UNAVAILABLE",
                "message": "No active PINN model is registered; Analysis should mark PINN as unavailable, not failed.",
                "available_models": sorted(models.keys()),
            }
        return {
            "ok": True,
            "tool": "pinn.predict",
            "status": "predicted",
            "model_id": model_id,
            "specimen_id": str(data.get("specimen_id", "")),
            "prediction": {
                "source": "registered_pinn_contract",
                "curve": data.get("fixture_prediction_curve", []),
                "uncertainty": data.get("fixture_uncertainty", {}),
            },
            "step_trace": [{"step": "PREDICT", "status": "ok"}],
        }

    def registry(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"ok": True, "tool": "pinn.registry", "status": "ready", **self._load_registry()}

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command in {"health", "pinn.health"}:
            return self.health()
        if command in {"dataset.build", "pinn.dataset.build", "build_dataset"}:
            return self.build_dataset(payload)
        if command in {"train", "pinn.train"}:
            return self.train(payload)
        if command in {"predict", "pinn.predict"}:
            return self.predict(payload)
        if command in {"registry", "pinn.registry"}:
            return self.registry(payload)
        return {"ok": False, "tool": f"pinn.{command}", "status": "blocked", "failure_code": "PINN_COMMAND_UNSUPPORTED"}
