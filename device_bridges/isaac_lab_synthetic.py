"""Validation-first Isaac Lab synthetic pipeline helpers for LeRobot datasets.

This module is intentionally non-actuating: it does not start teleoperation,
recording, Isaac Sim, or robot hardware. It writes the manifest and validation
contracts that later Isaac Lab/Replicator workers consume.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcp_tools.lerobot_schemas import (
    IsaacLabSyntheticRequest,
    IsaacSyntheticPipelineMode,
    IsaacSyntheticRunStatus,
    IsaacSyntheticSourceIntent,
    IsaacSyntheticSourceType,
)
from utils.isaac_omx_mirror_mapping import ISAAC_OMX_JOINT_MAP


VALIDATION_SCHEMA = "atr.lerobot.isaac_lab.validation.v1"
RESPONSE_SCHEMA = "atr.lerobot.isaac_lab_synthetic.response.v1"
SUMMARY_SCHEMA = "atr.lerobot.isaac_lab_synthetic.summary.v1"
CANONICAL_FRAME_SCHEMA = "atr.lerobot.canonical_episode_frame.v1"
TRAINING_IMPORT_SCHEMA = "atr.lerobot.training_import_row.v1"
REPLICATOR_SUMMARY_SCHEMA = "atr.lerobot.replicator_synthetic.summary.v1"
MIMIC_SUMMARY_SCHEMA = "atr.lerobot.isaac_lab_mimic.summary.v1"
RL_TEACHER_SUMMARY_SCHEMA = "atr.lerobot.isaac_lab_rl_teacher.summary.v1"
MIMIC_REQUIRED_SUBTASKS = ["approach", "grasp", "lift", "place", "release"]
MIMIC_SUCCESS_CRITERIA = ["object_grasped", "object_lifted", "object_placed", "gripper_released"]
RL_TEACHER_SUCCESS_CRITERIA = ["bounded_workspace", "grasp_stable", "place_success", "simulation_only"]
ISAAC_LAB_OMX_ENV_HELPERS = [
    "get_robot_eef_pose",
    "target_eef_pose_to_action",
    "action_to_target_eef_pose",
    "actions_to_gripper_actions",
    "get_object_poses",
    "get_subtask_term_signals",
]
REPLICATOR_REQUIRED_MODULES = ["omni.replicator.core"]
REPLICATOR_WRITER_TYPE = "BasicWriter"
REPLICATOR_ANNOTATORS = ["rgb", "distance_to_image_plane", "semantic_segmentation"]
REPLICATOR_RENDER_RESOLUTION = [640, 480]
DEFAULT_ISAAC_SIM_PYTHON = Path("/home/jin/IsaacSim/python.sh")
ISAAC_LAB_SYNTHETIC_AGGREGATE_SOURCE = "isaac_lab_synthetic"
MIMIC_SCRIPT_RELATIVE_PATHS = {
    "generate_dataset": "scripts/imitation_learning/isaaclab_mimic/generate_dataset.py",
    "annotate_demos": "scripts/imitation_learning/isaaclab_mimic/annotate_demos.py",
    "record_demos": "scripts/tools/record_demos.py",
}
ROBOMIMIC_TRAIN_RELATIVE_PATH = "scripts/imitation_learning/robomimic/train.py"
RL_WRAPPER_RELATIVE_PATHS = {
    "rsl_rl_train": "scripts/reinforcement_learning/rsl_rl/train.py",
    "skrl_train": "scripts/reinforcement_learning/skrl/train.py",
    "rl_games_train": "scripts/reinforcement_learning/rl_games/train.py",
    "sb3_train": "scripts/reinforcement_learning/sb3/train.py",
}


@dataclass(frozen=True)
class ValidationCheck:
    id: str
    group: str
    status: str
    severity: str
    message: str
    evidence: dict[str, Any]
    blocker_code: str | None = None
    docs: list[str] | None = None
    artifacts: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "group": self.group,
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
            "docs": list(self.docs or []),
            "artifacts": dict(self.artifacts or {}),
        }
        if self.blocker_code:
            payload["blocker_code"] = self.blocker_code
        return payload


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(text, encoding="utf-8")
    try:
        with tmp_path.open("r+", encoding="utf-8") as handle:
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass
    tmp_path.replace(path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n" for row in rows))


def _atomic_copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(f"{destination.name}.tmp.{os.getpid()}")
    tmp_path.write_bytes(source.read_bytes())
    try:
        with tmp_path.open("rb") as handle:
            os.fsync(handle.fileno())
    except OSError:
        pass
    tmp_path.replace(destination)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _safe_int(value: Any, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _safe_float(value: Any, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "ok", "passed", "success", "succeeded"}:
        return True
    if text in {"0", "false", "no", "n", "failed", "failure", "aborted", "abort", "cancelled", "canceled", "timeout", "error"}:
        return False
    return default


class IsaacLabSyntheticPipeline:
    """File-backed non-actuating implementation of the synthetic pipeline contract."""

    def __init__(self, *, repo_root: Path, allowed_roots: list[Path]) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.allowed_roots = [root.expanduser().resolve() for root in allowed_roots]

    def validate(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        dataset_path = self._dataset_path(request)
        output_root = self._output_root(request, dataset_path)
        checks = self._run_preflight_checks(request, dataset_path, output_root)
        report = self._validation_report(
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            stage="validation",
            checks=checks,
        )
        if dataset_path.exists() and self._path_allowed(output_root):
            _atomic_write_json(output_root / "validation_report.json", report)
        return self._response(
            tool="lerobot.isaac_lab.validate",
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            status=IsaacSyntheticRunStatus.BLOCKED if report["blockers"] else IsaacSyntheticRunStatus.READY_TO_BUILD,
            validation_report=report,
            compatibility=self._compatibility_summary(request, output_root=output_root),
            digital_twin=self._digital_twin_summary(request),
            replicator=self._replicator_summary(request, dataset_path, output_root, report),
        )

    def prepare(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        dataset_path = self._dataset_path(request)
        output_root = self._output_root(request, dataset_path)
        checks = self._run_preflight_checks(request, dataset_path, output_root)
        report = self._validation_report(
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            stage="prepare",
            checks=checks,
        )
        compatibility = self._compatibility_summary(request, output_root=output_root)
        digital_twin = self._digital_twin_summary(request, output_root=output_root, write_snapshot=self._path_allowed(output_root))
        depth = self._depth_summary(dataset_path)
        physics = self._static_group_summary(checks, "physics")
        articulation = self._static_group_summary(checks, "articulation")
        replicator_summary = self._replicator_summary(request, dataset_path, output_root, report)
        if self._path_allowed(output_root):
            _atomic_write_json(output_root / "request.json", request.model_dump(mode="json"))
            _atomic_write_json(output_root / "validation_report.json", report)
            _atomic_write_json(output_root / "compatibility.json", compatibility)
            _atomic_write_json(output_root / "digital_twin_preflight.json", digital_twin)
            _atomic_write_json(output_root / "depth_preflight.json", depth)
            _atomic_write_json(output_root / "physics_preflight.json", physics)
            _atomic_write_json(output_root / "articulation_preflight.json", articulation)
            self._write_replicator_artifacts(output_root, replicator_summary)
            _atomic_write_json(output_root / "summary.json", self._summary(request, dataset_path, output_root, "READY_TO_BUILD" if not report["blockers"] else "BLOCKED"))
        return self._response(
            tool="lerobot.isaac_lab.prepare",
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            status=IsaacSyntheticRunStatus.BLOCKED if report["blockers"] else IsaacSyntheticRunStatus.READY_TO_BUILD,
            validation_report=report,
            compatibility=compatibility,
            digital_twin=digital_twin,
            replicator=replicator_summary,
        )

    def build_synthetic(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        prepared = self.prepare(request)
        if not prepared.get("ok"):
            prepared["tool"] = "lerobot.isaac_lab.build_synthetic"
            return prepared
        dataset_path = self._dataset_path(request)
        output_root = self._output_root(request, dataset_path)
        canonical_rows = self._build_canonical_index(request, dataset_path)
        generated_rows = self._generated_success_rows(output_root)
        canonical_summary = {
            "schema": "atr.lerobot.canonical_episode_index.summary.v1",
            "status": "passed",
            "episode_count": len({row["episode_index"] for row in canonical_rows}),
            "frame_count": len(canonical_rows),
            "manifest_path": str(output_root / "canonical_episode_index" / "manifest.jsonl"),
        }
        canonical_summary = self._canonical_index_summary_with_paths(
            dataset_path=dataset_path,
            output_root=output_root,
            canonical_summary=canonical_summary,
        )
        validation_report = _read_json(output_root / "validation_report.json")
        replicator_summary = self._replicator_summary(
            request,
            dataset_path,
            output_root,
            validation_report,
            canonical_rows=canonical_rows,
        )
        if replicator_summary.get("status") == "blocked":
            validation_report = self._validation_report_with_replicator_blocker(validation_report, replicator_summary)
        replicator_rows = self._replicator_manifest_rows(output_root, valid_only=True)
        source_labels = self._source_labels(request, canonical_rows, replicator_rows=replicator_rows, generated_rows=generated_rows)
        training_rows: list[dict[str, Any]] = []
        if request.source_intent == IsaacSyntheticSourceIntent.TRAIN_READY_SUCCESS_ONLY:
            training_rows = self._training_import_rows(request, dataset_path, canonical_rows)
            training_rows.extend(self._generated_training_import_rows(request, dataset_path, output_root, generated_rows))
        failed_episode_indices = self._failed_episode_indices(canonical_rows)
        source_config = self._training_source_config(
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            source_labels=source_labels,
            training_rows=training_rows,
            replicator_summary=replicator_summary,
        )
        training_validation = self._training_import_validation(
            request=request,
            output_root=output_root,
            training_rows=training_rows,
        )
        exposed_training_rows = training_rows if training_validation.get("train_exposed") else []
        training_summary = {
            "schema": "atr.lerobot.training_import.summary.v1",
            "status": "passed" if training_validation.get("ok") else "blocked",
            "row_count": len(exposed_training_rows),
            "candidate_row_count": len(training_rows),
            "exposed_row_count": len(exposed_training_rows),
            "blocked_row_count": len(training_rows) - len(exposed_training_rows),
            "source_counts": self._count_by(exposed_training_rows, "source_type"),
            "candidate_source_counts": self._count_by(training_rows, "source_type"),
            "excluded_failed_episode_count": len(failed_episode_indices),
            "excluded_failed_episodes": failed_episode_indices,
            "manifest_path": str(output_root / "training_import" / "manifest.jsonl"),
            "source_config_path": str(output_root / "training_import" / "lerobot_source_config.json"),
            "validation_path": str(output_root / "training_import" / "training_import_validation.json"),
        }
        training_summary["validation_status"] = training_validation["status"]
        training_summary["validation_ok"] = bool(training_validation.get("ok"))
        training_summary["train_exposed"] = bool(training_validation.get("train_exposed"))
        training_summary["blockers"] = list(training_validation.get("blockers") or [])
        source_labels = self._source_labels_with_training_config(
            source_labels,
            source_config=source_config,
            training_summary=training_summary,
        )
        validation_report = self._validation_report_with_build_checks(
            validation_report,
            canonical_summary=canonical_summary,
            training_validation=training_validation,
        )
        if training_validation.get("status") == "blocked":
            validation_report = self._validation_report_with_training_blockers(validation_report, training_validation)
        self._write_canonical_index_artifacts(
            dataset_path=dataset_path,
            output_root=output_root,
            canonical_rows=canonical_rows,
            canonical_summary=canonical_summary,
        )
        _atomic_write_json(output_root / "source_labels.json", source_labels)
        self._write_replicator_artifacts(output_root, replicator_summary)
        if exposed_training_rows:
            _atomic_write_jsonl(output_root / "training_import" / "manifest.jsonl", exposed_training_rows)
        else:
            self._remove_path(output_root / "training_import" / "manifest.jsonl")
        _atomic_write_json(output_root / "training_import" / "lerobot_source_config.json", source_config)
        _atomic_write_json(output_root / "training_import" / "training_import_validation.json", training_validation)
        _atomic_write_json(output_root / "training_import" / "summary.json", training_summary)
        _atomic_write_json(output_root / "validation_report.json", validation_report)
        status = (
            IsaacSyntheticRunStatus.BLOCKED
            if validation_report.get("blockers") or training_validation.get("status") == "blocked"
            else
            IsaacSyntheticRunStatus.READY_FOR_TRAINING
            if training_rows and training_validation.get("train_exposed")
            else IsaacSyntheticRunStatus.READY_FOR_PREVIEW
        )
        mimic_summary, rl_teacher_summary = self._write_lab_hook_summaries(request, dataset_path, output_root)
        summary = self._summary(request, dataset_path, output_root, status.value)
        summary["counts"].update(
            {
                "canonical_frames": len(canonical_rows),
                "training_rows": len(training_rows),
            }
        )
        _atomic_write_json(output_root / "summary.json", summary)
        return self._response(
            tool="lerobot.isaac_lab.build_synthetic",
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            status=status,
            validation_report=validation_report,
            compatibility=_read_json(output_root / "compatibility.json"),
            digital_twin=_read_json(output_root / "digital_twin_preflight.json"),
            canonical_episode_index=canonical_summary,
            replicator=replicator_summary,
            source_labels=source_labels,
            training_exposure=training_summary,
            mimic=mimic_summary,
            rl_teacher=rl_teacher_summary,
        )

    def preview(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        dataset_path = self._dataset_path(request)
        output_root = self._output_root(request, dataset_path)
        run_summary = _read_json(output_root / "summary.json")
        rows = _read_jsonl(output_root / "canonical_episode_index" / "manifest.jsonl")
        preview_limit = _safe_int(request.isaac_data_augmentation_preview_count, 20, minimum=1, maximum=200)
        real_cards = [
            self._real_preview_card(row)
            for row in rows[: min(len(rows), preview_limit)]
        ]
        replicator_cards = [
            self._replicator_preview_card(row, output_root=output_root)
            for row in self._replicator_manifest_rows(output_root)
        ]
        generated_cards = [
            self._generated_preview_card(row, output_root=output_root)
            for row in self._generated_preview_rows(output_root)
        ]
        cards = (real_cards + replicator_cards + generated_cards)[:preview_limit]
        if cards:
            _atomic_write_jsonl(output_root / "previews" / "cards.jsonl", cards)
        preview_status = IsaacSyntheticRunStatus.READY_FOR_PREVIEW if cards or run_summary else IsaacSyntheticRunStatus.BLOCKED
        return self._response(
            tool="lerobot.isaac_lab.preview",
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            status=preview_status,
            validation_report=_read_json(output_root / "validation_report.json"),
            canonical_episode_index=_read_json(output_root / "canonical_episode_index" / "summary.json"),
            replicator=_read_json(output_root / "replicator" / "summary.json"),
            source_labels={
                "preview_count": len(cards),
                "requested_count": preview_limit,
                "run_summary": run_summary,
                "cards": cards,
            },
        )

    def export_hdf5(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        dataset_path = self._dataset_path(request)
        output_root = self._output_root(request, dataset_path)
        canonical_summary = _read_json(output_root / "canonical_episode_index" / "summary.json")
        canonical_manifest_path = output_root / "canonical_episode_index" / "manifest.jsonl"
        canonical_rows = _read_jsonl(canonical_manifest_path)
        canonical_frame_count = _safe_int(canonical_summary.get("frame_count"), 0, minimum=0)
        output_path = output_root / "hdf5" / "exported_successful_real_episodes.hdf5"
        if not canonical_summary or not canonical_rows:
            export_summary = self._blocked_hdf5_summary(
                blocker="HDF5_EXPORT_CANONICAL_INDEX_MISSING",
                message="Canonical episode index is missing; build synthetic artifacts before exporting HDF5.",
                canonical_manifest_path=canonical_manifest_path,
                canonical_frame_count=canonical_frame_count,
                output_path=output_path,
                skipped_episodes=[],
            )
            return self._hdf5_response(request, dataset_path, output_root, export_summary)
        missing_dependencies = self._missing_hdf5_dependencies()
        if missing_dependencies:
            export_summary = self._blocked_hdf5_summary(
                blocker="HDF5_EXPORT_DEPENDENCY_MISSING",
                message="HDF5 export requires pyarrow and h5py in the active Python environment.",
                canonical_manifest_path=canonical_manifest_path,
                canonical_frame_count=canonical_frame_count,
                output_path=output_path,
                skipped_episodes=[],
                extra={"missing_dependencies": missing_dependencies},
            )
            return self._hdf5_response(request, dataset_path, output_root, export_summary)
        export_summary = self._export_canonical_to_hdf5(
            dataset_path=dataset_path,
            canonical_manifest_path=canonical_manifest_path,
            canonical_rows=canonical_rows,
            output_path=output_path,
        )
        return self._hdf5_response(request, dataset_path, output_root, export_summary)

    def run_mimic_smoke(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        dataset_path = self._dataset_path(request)
        output_root = self._output_root(request, dataset_path)
        mimic_summary, rl_teacher_summary = self._write_lab_hook_summaries(request, dataset_path, output_root)
        if mimic_summary.get("status") != "ready":
            self._remove_smoke_summary(output_root / "mimic")
            validation_report = self._hook_blocked_validation_report(
                request=request,
                dataset_path=dataset_path,
                output_root=output_root,
                stage="mimic",
                blocker=str(mimic_summary.get("blocker") or "MIMIC_NOT_READY"),
                message=str(mimic_summary.get("message") or "Mimic smoke is not ready."),
            )
            return self._response(
                tool="lerobot.isaac_lab.run_mimic_smoke",
                request=request,
                dataset_path=dataset_path,
                output_root=output_root,
                status=IsaacSyntheticRunStatus.BLOCKED,
                validation_report=validation_report,
                canonical_episode_index=_read_json(output_root / "canonical_episode_index" / "summary.json"),
                hdf5=_read_json(output_root / "hdf5" / "export_summary.json"),
                mimic=mimic_summary,
                rl_teacher=rl_teacher_summary,
            )
        smoke_summary = self._mimic_smoke_summary(request, output_root, mimic_summary)
        generation_summary = self._write_mimic_generation_manifests(request, output_root, mimic_summary)
        mimic_summary = {
            **mimic_summary,
            **generation_summary,
            "smoke": smoke_summary,
            "smoke_summary_path": str(output_root / "mimic" / "smoke_summary.json"),
        }
        _atomic_write_json(output_root / "mimic" / "smoke_summary.json", smoke_summary)
        _atomic_write_json(output_root / "mimic" / "summary.json", mimic_summary)
        return self._response(
            tool="lerobot.isaac_lab.run_mimic_smoke",
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            status=IsaacSyntheticRunStatus.READY_FOR_TRAINING,
            validation_report=_read_json(output_root / "validation_report.json"),
            canonical_episode_index=_read_json(output_root / "canonical_episode_index" / "summary.json"),
            hdf5=_read_json(output_root / "hdf5" / "export_summary.json"),
            mimic=mimic_summary,
            rl_teacher=rl_teacher_summary,
        )

    def run_mimic(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        response = self.run_mimic_smoke(request)
        response["tool"] = "lerobot.isaac_lab.run_mimic"
        if response.get("ok"):
            output_root = Path(str(response.get("output_root") or ""))
            mimic_summary = dict(response.get("mimic") or {})
            mimic_summary["runner"] = self._runner_summary(
                request,
                kind="mimic",
                operation="mimic_generate_dataset",
                hook_summary=mimic_summary,
            )
            response["mimic"] = mimic_summary
            if output_root:
                _atomic_write_json(output_root / "mimic" / "summary.json", mimic_summary)
                _atomic_write_json(output_root / "mimic" / "runner.json", mimic_summary["runner"])
                _atomic_write_json(output_root / "mimic" / "generation_config.json", mimic_summary["runner"]["generation_config"])
        return response

    def run_rl_teacher_smoke(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        dataset_path = self._dataset_path(request)
        output_root = self._output_root(request, dataset_path)
        mimic_summary, rl_teacher_summary = self._write_lab_hook_summaries(request, dataset_path, output_root)
        if rl_teacher_summary.get("status") != "ready":
            self._remove_smoke_summary(output_root / "rl_teacher")
            validation_report = self._hook_blocked_validation_report(
                request=request,
                dataset_path=dataset_path,
                output_root=output_root,
                stage="rl_teacher",
                blocker=str(rl_teacher_summary.get("blocker") or "RL_TEACHER_NOT_READY"),
                message=str(rl_teacher_summary.get("message") or "RL teacher smoke is not ready."),
            )
            return self._response(
                tool="lerobot.isaac_lab.run_rl_teacher_smoke",
                request=request,
                dataset_path=dataset_path,
                output_root=output_root,
                status=IsaacSyntheticRunStatus.BLOCKED,
                validation_report=validation_report,
                canonical_episode_index=_read_json(output_root / "canonical_episode_index" / "summary.json"),
                hdf5=_read_json(output_root / "hdf5" / "export_summary.json"),
                mimic=mimic_summary,
                rl_teacher=rl_teacher_summary,
            )
        smoke_summary = self._rl_teacher_smoke_summary(request, output_root, rl_teacher_summary)
        generation_summary = self._write_rl_teacher_generation_manifests(request, output_root, rl_teacher_summary)
        rl_teacher_summary = {
            **rl_teacher_summary,
            **generation_summary,
            "smoke": smoke_summary,
            "smoke_summary_path": str(output_root / "rl_teacher" / "smoke_summary.json"),
        }
        _atomic_write_json(output_root / "rl_teacher" / "smoke_summary.json", smoke_summary)
        _atomic_write_json(output_root / "rl_teacher" / "summary.json", rl_teacher_summary)
        return self._response(
            tool="lerobot.isaac_lab.run_rl_teacher_smoke",
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            status=IsaacSyntheticRunStatus.READY_FOR_TRAINING,
            validation_report=_read_json(output_root / "validation_report.json"),
            canonical_episode_index=_read_json(output_root / "canonical_episode_index" / "summary.json"),
            hdf5=_read_json(output_root / "hdf5" / "export_summary.json"),
            mimic=mimic_summary,
            rl_teacher=rl_teacher_summary,
        )

    def run_rl_teacher(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        response = self.run_rl_teacher_smoke(request)
        response["tool"] = "lerobot.isaac_lab.run_rl_teacher"
        if response.get("ok"):
            output_root = Path(str(response.get("output_root") or ""))
            rl_teacher_summary = dict(response.get("rl_teacher") or {})
            rl_teacher_summary["runner"] = self._runner_summary(
                request,
                kind="rl_teacher",
                operation="rl_teacher_generate_dataset",
                hook_summary=rl_teacher_summary,
            )
            response["rl_teacher"] = rl_teacher_summary
            if output_root:
                _atomic_write_json(output_root / "rl_teacher" / "summary.json", rl_teacher_summary)
                _atomic_write_json(output_root / "rl_teacher" / "runner.json", rl_teacher_summary["runner"])
                _atomic_write_json(output_root / "rl_teacher" / "generation_config.json", rl_teacher_summary["runner"]["generation_config"])
        return response

    def _runner_summary(
        self,
        request: IsaacLabSyntheticRequest,
        *,
        kind: str,
        operation: str,
        hook_summary: dict[str, Any],
    ) -> dict[str, Any]:
        smoke = hook_summary.get("smoke") if isinstance(hook_summary.get("smoke"), dict) else {}
        dry_run = bool(request.dry_run or request.mode != "live")
        command = self._runner_command(request, kind=kind, hook_summary=hook_summary, smoke_summary=smoke)
        script_path = command[1] if len(command) > 1 else ""
        isaac_python = command[0] if command else ""
        output_root = Path(str(smoke.get("output_root") or ""))
        generation_config = self._runner_generation_config(
            request,
            kind=kind,
            output_root=output_root,
            hook_summary=hook_summary,
        )
        return {
            "schema": f"atr.lerobot.isaac_lab_{kind}.runner.v1",
            "status": "completed" if dry_run else "ready_to_launch",
            "dry_run": dry_run,
            "operation": operation,
            "generated_at": _now(),
            "generation_config": generation_config,
            "generation_config_path": str(output_root / kind / "generation_config.json") if str(output_root) else "",
            "command": command,
            "script_path": script_path,
            "script_exists": Path(script_path).is_file() if script_path else False,
            "isaac_sim_python": isaac_python,
            "isaac_sim_python_exists": Path(isaac_python).is_file() if isaac_python else False,
            "command_preview": dict(smoke.get("command_preview") or {}),
            "runtime_smoke": dict(smoke.get("runtime_smoke") or {}),
            "candidate_count": _safe_int(hook_summary.get("candidate_count"), 0, minimum=0),
            "success_count": _safe_int(hook_summary.get("success_count"), 0, minimum=0),
            "failure_count": _safe_int(hook_summary.get("failure_count"), 0, minimum=0),
            "generated_dataset_path": str(hook_summary.get("generated_dataset_path") or ""),
            "success_manifest_path": str(hook_summary.get("success_manifest_path") or ""),
            "job_lifecycle": "file_backed_sidecar_manifest",
            "external_launch_required": not dry_run,
        }

    def _runner_generation_config(
        self,
        request: IsaacLabSyntheticRequest,
        *,
        kind: str,
        output_root: Path,
        hook_summary: dict[str, Any],
    ) -> dict[str, Any]:
        if kind == "mimic":
            return {
                "schema": "atr.lerobot.isaac_lab_mimic.generation_config.v1",
                "workspace": "a4_sheet",
                "object_pose_randomization": {
                    "workspace": "a4_sheet",
                    "bounds_m": {"x": [-0.105, 0.105], "y": [-0.1485, 0.1485]},
                    "yaw_bounds_rad": [-0.785398, 0.785398],
                    "source": "a4_bounded_cube_pose_randomization",
                },
                "success_filter": {
                    "success_only": True,
                    "success_manifest": str(output_root / "mimic" / "successes.jsonl") if str(output_root) else "",
                    "excluded_manifest": str(output_root / "mimic" / "failures.jsonl") if str(output_root) else "",
                    "criteria": list(hook_summary.get("success_criteria") or MIMIC_SUCCESS_CRITERIA),
                },
                "trials": request.mimic_trials,
                "num_envs": request.mimic_num_envs,
            }
        return {
            "schema": "atr.lerobot.isaac_lab_rl_teacher.generation_config.v1",
            "workspace": "a4_sheet",
            "observations": ["eef_pose", "joint_pos", "gripper_state", "object_pose"],
            "state_policy": "conservative_state_observations_only",
            "success_metrics": list(hook_summary.get("success_criteria") or RL_TEACHER_SUCCESS_CRITERIA),
            "success_filter": {
                "success_only": True,
                "success_manifest": str(output_root / "rl_teacher" / "successes.jsonl") if str(output_root) else "",
                "excluded_manifest": str(output_root / "rl_teacher" / "failures.jsonl") if str(output_root) else "",
                "criteria": list(hook_summary.get("success_criteria") or RL_TEACHER_SUCCESS_CRITERIA),
            },
            "steps": request.rl_teacher_steps,
            "simulation_only": True,
        }

    def _runner_command(
        self,
        request: IsaacLabSyntheticRequest,
        *,
        kind: str,
        hook_summary: dict[str, Any],
        smoke_summary: dict[str, Any],
    ) -> list[str]:
        isaac_python = Path(request.isaac_sim_python).expanduser() if request.isaac_sim_python else DEFAULT_ISAAC_SIM_PYTHON
        isaac_lab_root = Path(request.isaac_lab_path).expanduser() if request.isaac_lab_path else Path("")
        output_root = Path(str(smoke_summary.get("output_root") or self._output_root(request, self._dataset_path(request))))
        env_wrapper_manifest = str(smoke_summary.get("env_wrapper_manifest") or "")
        hdf5_path = str(hook_summary.get("hdf5_path") or smoke_summary.get("hdf5_path") or "")
        if kind == "mimic":
            script = isaac_lab_root / MIMIC_SCRIPT_RELATIVE_PATHS["generate_dataset"]
            return [
                str(isaac_python),
                str(script),
                "--hdf5",
                hdf5_path,
                "--env-wrapper",
                env_wrapper_manifest,
                "--output-dir",
                str(output_root / "mimic"),
                "--trials",
                str(request.mimic_trials),
                "--num-envs",
                str(request.mimic_num_envs),
                "--seed",
                str(request.seed),
            ]
        script = isaac_lab_root / RL_WRAPPER_RELATIVE_PATHS["rsl_rl_train"]
        return [
            str(isaac_python),
            str(script),
            "--env-wrapper",
            env_wrapper_manifest,
            "--output-dir",
            str(output_root / "rl_teacher"),
            "--steps",
            str(request.rl_teacher_steps),
            "--seed",
            str(request.seed),
            "--headless",
        ]

    def _hdf5_response(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        export_summary: dict[str, Any],
    ) -> dict[str, Any]:
        _atomic_write_json(output_root / "hdf5" / "export_summary.json", export_summary)
        status = IsaacSyntheticRunStatus.READY_FOR_HDF5 if export_summary.get("ok") else IsaacSyntheticRunStatus.BLOCKED
        if not export_summary.get("ok"):
            output_path = Path(str(export_summary.get("output_path") or "")).expanduser()
            try:
                if output_path.is_file():
                    output_path.unlink()
            except OSError:
                pass
        mimic_summary, rl_teacher_summary = self._write_lab_hook_summaries(request, dataset_path, output_root)
        validation_report = _read_json(output_root / "validation_report.json")
        validation_report = self._validation_report_with_hdf5_check(validation_report, export_summary)
        _atomic_write_json(output_root / "validation_report.json", validation_report)
        return self._response(
            tool="lerobot.isaac_lab.export_hdf5",
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            status=status,
            validation_report=validation_report,
            hdf5=export_summary,
            mimic=mimic_summary,
            rl_teacher=rl_teacher_summary,
        )

    @staticmethod
    def _missing_hdf5_dependencies() -> list[str]:
        return [name for name in ("pyarrow", "h5py") if find_spec(name) is None]

    @staticmethod
    def _blocked_hdf5_summary(
        *,
        blocker: str,
        message: str,
        canonical_manifest_path: Path,
        canonical_frame_count: int,
        output_path: Path,
        skipped_episodes: list[dict[str, Any]],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema": "atr.lerobot.isaac_lab_hdf5_export.summary.v1",
            "ok": False,
            "status": "blocked",
            "blocker": blocker,
            "hdf5_available": False,
            "message": message,
            "canonical_manifest_path": str(canonical_manifest_path),
            "canonical_frame_count": max(0, int(canonical_frame_count)),
            "output_path": str(output_path),
            "exported_episode_count": 0,
            "exported_frame_count": 0,
            "skipped_episodes": skipped_episodes,
            "required_next_parser_fields": [
                "observation.state",
                "action",
                "episode_index",
                "frame_index",
                "timestamp",
                "success",
            ],
            **dict(extra or {}),
        }

    def _export_canonical_to_hdf5(
        self,
        *,
        dataset_path: Path,
        canonical_manifest_path: Path,
        canonical_rows: list[dict[str, Any]],
        output_path: Path,
    ) -> dict[str, Any]:
        import h5py
        import numpy as np
        import pyarrow.parquet as pq

        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in canonical_rows:
            grouped[_safe_int(row.get("episode_index"), 0, minimum=0)].append(row)
        exported: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        parsed_episodes: dict[int, dict[str, Any]] = {}
        for episode_index, episode_rows in sorted(grouped.items()):
            if any(row.get("episode_success") is False for row in episode_rows):
                skipped.append({"episode_index": episode_index, "reason": "EPISODE_MARKED_FAILED"})
                continue
            episode_path = dataset_path / "data" / "chunk-000" / f"episode_{episode_index:06d}.parquet"
            if not episode_path.is_file():
                skipped.append({"episode_index": episode_index, "reason": "PARQUET_MISSING", "path": str(episode_path)})
                continue
            try:
                table = pq.read_table(episode_path)
            except Exception as exc:  # noqa: BLE001 - pyarrow raises several concrete exception types.
                skipped.append(
                    {
                        "episode_index": episode_index,
                        "reason": "PARQUET_READ_FAILED",
                        "path": str(episode_path),
                        "detail": f"{exc.__class__.__name__}: {exc}",
                    }
                )
                continue
            data = table.to_pydict()
            missing_columns = [
                column
                for column in ("observation.state", "action")
                if column not in data
            ]
            if missing_columns:
                skipped.append(
                    {
                        "episode_index": episode_index,
                        "reason": "REQUIRED_COLUMNS_MISSING",
                        "path": str(episode_path),
                        "missing_columns": missing_columns,
                    }
                )
                continue
            try:
                parsed = self._parse_episode_for_hdf5(
                    data=data,
                    canonical_rows=episode_rows,
                    episode_index=episode_index,
                )
            except ValueError as exc:
                skipped.append(
                    {
                        "episode_index": episode_index,
                        "reason": "EPISODE_PARSE_FAILED",
                        "path": str(episode_path),
                        "detail": str(exc),
                    }
                )
                continue
            parsed_episodes[episode_index] = parsed
            exported.append(
                {
                    "episode_index": episode_index,
                    "frame_count": int(parsed["actions"].shape[0]),
                    "parquet_path": str(episode_path),
                }
            )
        canonical_frame_count = len(canonical_rows)
        if not exported:
            blocker_by_reason = {
                "PARQUET_READ_FAILED": "HDF5_EXPORT_PARQUET_READ_FAILED",
                "PARQUET_MISSING": "HDF5_EXPORT_PARQUET_MISSING",
                "REQUIRED_COLUMNS_MISSING": "HDF5_EXPORT_REQUIRED_COLUMNS_MISSING",
            }
            first_reason = str(skipped[0].get("reason") if skipped else "")
            return self._blocked_hdf5_summary(
                blocker=blocker_by_reason.get(first_reason, "HDF5_EXPORT_NO_TRAIN_READY_EPISODES"),
                message="No canonical real episodes could be exported to HDF5.",
                canonical_manifest_path=canonical_manifest_path,
                canonical_frame_count=canonical_frame_count,
                output_path=output_path,
                skipped_episodes=skipped,
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_name(f"{output_path.name}.tmp.{os.getpid()}")
        if tmp_path.exists():
            tmp_path.unlink()
        with h5py.File(tmp_path, "w") as handle:
            handle.attrs["schema"] = "atr.lerobot.isaac_lab_hdf5_export.v1"
            handle.attrs["dataset_path"] = str(dataset_path)
            handle.attrs["canonical_manifest_path"] = str(canonical_manifest_path)
            handle.attrs["total"] = sum(int(item["frame_count"]) for item in exported)
            data_group = handle.create_group("data")
            for episode_index, parsed in sorted(parsed_episodes.items()):
                demo = data_group.create_group(f"demo_{episode_index:06d}")
                demo.attrs["episode_index"] = episode_index
                demo.attrs["num_samples"] = int(parsed["actions"].shape[0])
                demo.create_dataset("actions", data=parsed["actions"])
                demo.create_dataset("states", data=parsed["states"])
                demo.create_dataset("timestamps", data=parsed["timestamps"])
                demo.create_dataset("frame_indices", data=parsed["frame_indices"])
                obs = demo.create_group("obs")
                obs.create_dataset("robot_state", data=parsed["states"])
                canonical = demo.create_group("canonical")
                canonical.attrs["schema"] = "atr.lerobot.canonical_episode_hdf5_sidecar.v1"
                string_dtype = h5py.string_dtype(encoding="utf-8")
                canonical.create_dataset("grasp_event_labels", data=parsed["grasp_event_labels"], dtype=string_dtype)
                canonical.create_dataset("missing_sources", data=parsed["missing_sources"], dtype=string_dtype)
                canonical.create_dataset("raw_depth_paths", data=parsed["raw_depth_paths"], dtype=string_dtype)
                availability = canonical.create_group("source_availability")
                for source, values in parsed["source_availability"].items():
                    availability.create_dataset(source, data=np.asarray(values, dtype=np.bool_))
        tmp_path.replace(output_path)
        exported_frame_count = sum(int(item["frame_count"]) for item in exported)
        return {
            "schema": "atr.lerobot.isaac_lab_hdf5_export.summary.v1",
            "ok": True,
            "status": "passed",
            "blocker": "",
            "hdf5_available": True,
            "message": "Exported canonical successful real episodes to Isaac Lab/robomimic HDF5.",
            "canonical_manifest_path": str(canonical_manifest_path),
            "canonical_frame_count": canonical_frame_count,
            "output_path": str(output_path),
            "exported_episode_count": len(exported),
            "exported_frame_count": exported_frame_count,
            "exported_episodes": exported,
            "skipped_episodes": skipped,
            "required_next_parser_fields": [],
        }

    def _parse_episode_for_hdf5(
        self,
        *,
        data: dict[str, list[Any]],
        canonical_rows: list[dict[str, Any]],
        episode_index: int,
    ) -> dict[str, Any]:
        import numpy as np

        frame_values = data.get("frame_index") or list(range(len(data["action"])))
        row_by_frame = {_safe_int(frame, index, minimum=0): index for index, frame in enumerate(frame_values)}
        ordered_rows = sorted(canonical_rows, key=lambda item: _safe_int(item.get("frame_index"), 0, minimum=0))
        actions: list[list[float]] = []
        states: list[list[float]] = []
        timestamps: list[float] = []
        frame_indices: list[int] = []
        source_availability: dict[str, list[bool]] = defaultdict(list)
        grasp_event_labels: list[str] = []
        missing_sources: list[str] = []
        raw_depth_paths: list[str] = []
        for row in ordered_rows:
            frame_index = _safe_int(row.get("frame_index"), 0, minimum=0)
            if frame_index not in row_by_frame:
                raise ValueError(f"episode {episode_index} missing frame_index {frame_index} in parquet")
            table_index = row_by_frame[frame_index]
            action = self._numeric_vector(data["action"][table_index], field="action", frame_index=frame_index)
            state = self._numeric_vector(data["observation.state"][table_index], field="observation.state", frame_index=frame_index)
            actions.append(action)
            states.append(state)
            timestamp_values = data.get("timestamp")
            timestamp = float(timestamp_values[table_index]) if timestamp_values is not None else round(frame_index / 15.0, 6)
            timestamps.append(timestamp)
            frame_indices.append(frame_index)
            availability = row.get("source_availability") if isinstance(row.get("source_availability"), dict) else {}
            for source in (
                "real_rgb",
                "raw_depth",
                "isaac_rgbd",
                "active_robot_cam",
                "grasp_diagnostics",
                "lerobot_action",
            ):
                source_availability[source].append(bool(availability.get(source)))
            grasp = row.get("grasp_diagnostics") if isinstance(row.get("grasp_diagnostics"), dict) else {}
            grasp_event_labels.append(str(row.get("grasp_event_label") or grasp.get("event_label") or grasp.get("state") or ""))
            missing = row.get("missing_sources") if isinstance(row.get("missing_sources"), list) else []
            missing_sources.append(",".join(str(item) for item in missing))
            raw_depth = row.get("raw_depth") if isinstance(row.get("raw_depth"), dict) else {}
            raw_depth_paths.append(str(raw_depth.get("path") or ""))
        return {
            "actions": np.asarray(actions, dtype=np.float64),
            "states": np.asarray(states, dtype=np.float64),
            "timestamps": np.asarray(timestamps, dtype=np.float64),
            "frame_indices": np.asarray(frame_indices, dtype=np.int64),
            "source_availability": dict(source_availability),
            "grasp_event_labels": grasp_event_labels,
            "missing_sources": missing_sources,
            "raw_depth_paths": raw_depth_paths,
        }

    @staticmethod
    def _numeric_vector(value: Any, *, field: str, frame_index: int) -> list[float]:
        if value is None:
            raise ValueError(f"{field} is missing at frame {frame_index}")
        if hasattr(value, "tolist"):
            value = value.tolist()
        if not isinstance(value, (list, tuple)):
            value = [value]
        try:
            vector = [float(item) for item in value]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} is not numeric at frame {frame_index}") from exc
        if not vector:
            raise ValueError(f"{field} is empty at frame {frame_index}")
        return vector

    def status(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        dataset_path = self._dataset_path(request)
        output_root = self._output_root(request, dataset_path)
        summary = _read_json(output_root / "summary.json")
        status = IsaacSyntheticRunStatus(summary.get("status", "IDLE")) if summary.get("status") in IsaacSyntheticRunStatus._value2member_map_ else IsaacSyntheticRunStatus.IDLE
        return self._response(
            tool="lerobot.isaac_lab.status",
            request=request,
            dataset_path=dataset_path,
            output_root=output_root,
            status=status,
            validation_report=_read_json(output_root / "validation_report.json"),
            compatibility=_read_json(output_root / "compatibility.json"),
            digital_twin=_read_json(output_root / "digital_twin_preflight.json"),
            canonical_episode_index=_read_json(output_root / "canonical_episode_index" / "summary.json"),
            replicator=_read_json(output_root / "replicator" / "summary.json"),
            source_labels=_read_json(output_root / "source_labels.json"),
            training_exposure=_read_json(output_root / "training_import" / "summary.json"),
            hdf5=_read_json(output_root / "hdf5" / "export_summary.json"),
            mimic=_read_json(output_root / "mimic" / "summary.json"),
            rl_teacher=_read_json(output_root / "rl_teacher" / "summary.json"),
        )

    def _replicator_summary(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        validation_report: dict[str, Any],
        *,
        canonical_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        manifest_path = output_root / "replicator" / "manifest.jsonl"
        manifest_rows = _read_jsonl(manifest_path)
        render_file_validation = self._replicator_render_file_validation(output_root, manifest_rows)
        canonical_frame_count = len(canonical_rows or [])
        if canonical_rows is None:
            canonical_summary = _read_json(output_root / "canonical_episode_index" / "summary.json")
            canonical_frame_count = _safe_int(canonical_summary.get("frame_count"), 0, minimum=0)
        expected_render_rows = canonical_frame_count * request.attempts_per_source_frame * len(request.cameras)
        render_output_counts = self._replicator_render_output_counts(output_root, manifest_rows)
        runtime_probe = self._replicator_runtime_probe(request, blocker=None)
        post_render_augmentation = self._replicator_post_render_augmentation(request, output_root)
        isaac_sim_smoke = self._isaac_sim_smoke_summary(
            request,
            runtime_probe=runtime_probe,
            post_render_augmentation=post_render_augmentation,
            expected_render_rows=expected_render_rows,
        )
        action_consistency_validation = self._replicator_action_consistency_validation(output_root, manifest_rows)
        base = {
            "schema": REPLICATOR_SUMMARY_SCHEMA,
            "enabled": bool(request.enable_replicator),
            "generated_at": _now(),
            "replicator_available": bool(manifest_rows) or runtime_probe.get("status") == "passed",
            "writer_type": REPLICATOR_WRITER_TYPE,
            "annotators": list(REPLICATOR_ANNOTATORS),
            "post_render_augmentation": post_render_augmentation,
            "render_products": {
                "requested_count": expected_render_rows,
                "created_count": len(manifest_rows),
                "resolution": list(REPLICATOR_RENDER_RESOLUTION),
                "camera_names": list(request.cameras),
            },
            "camera_names": list(request.cameras),
            **render_output_counts,
            "depth_units_replicator": {
                "annotator": "distance_to_image_plane",
                "unit": "meters",
                "conversion": "identity",
            },
            "teleop_sdg_replay_used": False,
            "teleop_sdg_replay_boundary": "render_only_not_physics_rollout",
            "dataset_path": str(dataset_path),
            "output_root": str(output_root),
            "stage_path": str(self._stage_path(request)),
            "isaac_sim_python": self._isaac_sim_python_value(request),
            "cameras": list(request.cameras),
            "attempts_per_source_frame": request.attempts_per_source_frame,
            "canonical_frame_count": canonical_frame_count,
            "expected_render_rows": expected_render_rows,
            "manifest_path": str(manifest_path),
            "render_manifest_available": manifest_path.is_file(),
            "rendered_count": len(manifest_rows),
            "valid_rendered_count": render_file_validation["valid_row_count"],
            "render_file_validation": render_file_validation,
            "action_consistency_validation": action_consistency_validation,
            "source_type": IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value,
            "source_weight": request.replicator_render_weight,
            "fidelity_weight": 1.0,
            "runtime_probe": runtime_probe,
            "isaac_sim_smoke": isaac_sim_smoke,
        }
        if not request.enable_replicator:
            return {
                **base,
                "runtime_probe": self._replicator_runtime_probe(request, blocker=None),
                "status": "skipped",
                "blocker": "",
                "message": "Replicator branch is disabled for this request.",
                "checks": [{"id": "replicator_enabled", "status": "skipped"}],
            }
        blocker = self._replicator_blocker(validation_report)
        if blocker:
            return {
                **base,
                "runtime_probe": self._replicator_runtime_probe(request, blocker=blocker),
                "status": "blocked",
                "blocker": blocker.get("code", "REPLICATOR_UNAVAILABLE"),
                "message": blocker.get("message", "Replicator validation is blocked."),
                "checks": [
                    {"id": "replicator_enabled", "status": "passed"},
                    {
                        "id": "replicator_runtime",
                        "status": "blocked",
                        "blocker": blocker.get("code", "REPLICATOR_UNAVAILABLE"),
                    },
                ],
            }
        if manifest_rows and not render_file_validation["ok"]:
            return {
                **base,
                "status": "blocked",
                "blocker": "REPLICATOR_OUTPUT_FILES_MISSING",
                "message": "Replicator manifest rows must reference existing RGB and depth files.",
                "checks": [
                    {"id": "replicator_enabled", "status": "passed"},
                    {"id": "replicator_runtime", "status": "passed"},
                    {
                        "id": "replicator_import_probe",
                        "status": "satisfied_by_manifest",
                        "required_modules": list(REPLICATOR_REQUIRED_MODULES),
                    },
                    {"id": "render_manifest", "status": "passed"},
                    {
                        "id": "render_rgb_depth_pairs",
                        "status": "blocked",
                        "blocker": "REPLICATOR_OUTPUT_FILES_MISSING",
                    },
                ],
            }
        if manifest_rows and render_file_validation["ok"] and not action_consistency_validation["ok"]:
            return {
                **base,
                "status": "blocked",
                "blocker": "ACTION_LABEL_MISMATCH_RISK",
                "message": "Render-only object pose changes exceed sidecar-safe bounds without a matching generated trajectory.",
                "checks": [
                    {"id": "replicator_enabled", "status": "passed"},
                    {"id": "replicator_runtime", "status": "passed"},
                    {
                        "id": "replicator_import_probe",
                        "status": "satisfied_by_manifest",
                        "required_modules": list(REPLICATOR_REQUIRED_MODULES),
                    },
                    {"id": "render_manifest", "status": "passed"},
                    {"id": "render_rgb_depth_pairs", "status": "passed"},
                    {
                        "id": "action_label_consistency",
                        "status": "blocked",
                        "blocker": "ACTION_LABEL_MISMATCH_RISK",
                    },
                ],
            }
        status = "completed" if manifest_rows else "ready"
        message = (
            "Replicator manifest is present and ready for preview/import."
            if manifest_rows
            else "Replicator runtime is configured; render worker can create RGB/depth variants from this build plan."
        )
        return {
            **base,
            "status": status,
            "blocker": "",
            "message": message,
            "checks": [
                {"id": "replicator_enabled", "status": "passed"},
                {"id": "replicator_runtime", "status": "passed"},
                {
                    "id": "replicator_import_probe",
                    "status": "pending" if not manifest_rows else "satisfied_by_manifest",
                    "required_modules": list(REPLICATOR_REQUIRED_MODULES),
                },
                {"id": "render_manifest", "status": "passed" if manifest_rows else "pending"},
                {"id": "render_rgb_depth_pairs", "status": "passed" if manifest_rows else "pending"},
                {"id": "action_label_consistency", "status": "passed" if manifest_rows else "pending"},
            ],
        }

    def _replicator_action_consistency_validation(self, output_root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
        generated_rows = self._generated_success_rows(output_root)
        generated_keys = {
            (
                _safe_int(row.get("source_episode_index"), -1),
                _safe_int(row.get("source_frame_index"), -1),
            )
            for row in generated_rows
        }
        any_generated_success = bool(generated_rows)
        blocked_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            risk = self._replicator_action_mismatch_risk(row)
            if not risk["requires_generated_trajectory"]:
                continue
            episode_index = _safe_int(row.get("episode_index"), _safe_int(row.get("canonical_episode_index"), -1))
            frame_index = _safe_int(row.get("frame_index"), _safe_int(row.get("canonical_frame_index"), -1))
            matching_generated = (episode_index, frame_index) in generated_keys if episode_index >= 0 and frame_index >= 0 else any_generated_success
            if matching_generated:
                continue
            blocked_rows.append(
                {
                    "row_index": index,
                    "episode_index": row.get("episode_index", row.get("canonical_episode_index")),
                    "frame_index": row.get("frame_index", row.get("canonical_frame_index")),
                    "camera": row.get("camera") or row.get("camera_name") or "",
                    "variant_index": row.get("variant_index"),
                    **risk,
                }
            )
        return {
            "schema": "atr.lerobot.replicator.action_consistency_validation.v1",
            "ok": not blocked_rows,
            "sidecar_safe_xy_m": 0.01,
            "sidecar_safe_yaw_rad": 0.174,
            "row_count": len(rows),
            "generated_success_count": len(generated_rows),
            "blocked_row_count": len(blocked_rows),
            "blocked_rows": blocked_rows[:50],
        }

    @classmethod
    def _replicator_action_mismatch_risk(cls, row: dict[str, Any]) -> dict[str, Any]:
        action_consistency = row.get("action_consistency") if isinstance(row.get("action_consistency"), dict) else {}
        delta = action_consistency.get("object_pose_delta") if isinstance(action_consistency.get("object_pose_delta"), dict) else {}
        randomization = row.get("randomization") if isinstance(row.get("randomization"), dict) else {}
        object_pose = row.get("object_pose_randomization") if isinstance(row.get("object_pose_randomization"), dict) else {}
        xy_delta_m = max(
            cls._abs_float(delta.get("xy_m")),
            cls._abs_float(action_consistency.get("object_pose_delta_xy_m")),
            cls._xy_norm(delta),
            cls._xy_norm(object_pose),
            cls._abs_float(randomization.get("object_xy_jitter_m")),
        )
        yaw_delta_rad = max(
            cls._abs_float(delta.get("yaw_rad")),
            cls._abs_float(action_consistency.get("object_pose_delta_yaw_rad")),
            cls._abs_float(object_pose.get("yaw_rad")),
            cls._abs_float(object_pose.get("yaw_jitter_rad")),
            cls._abs_float(randomization.get("object_yaw_jitter_rad")),
        )
        object_pose_changed = _safe_bool(action_consistency.get("object_pose_changed"), False) or xy_delta_m > 0.0 or yaw_delta_rad > 0.0
        uses_original_action = _safe_bool(action_consistency.get("uses_original_action"), True)
        marked_trainable = bool(row.get("train_eligible")) or _safe_bool(action_consistency.get("trainable"), False)
        exceeds_sidecar_bound = xy_delta_m > 0.01 or yaw_delta_rad > 0.174
        requires_generated = bool(object_pose_changed and uses_original_action and marked_trainable and exceeds_sidecar_bound)
        if _safe_bool(action_consistency.get("requires_generated_trajectory"), False) and marked_trainable:
            requires_generated = True
        return {
            "requires_generated_trajectory": requires_generated,
            "object_pose_changed": object_pose_changed,
            "uses_original_action": uses_original_action,
            "marked_trainable": marked_trainable,
            "xy_delta_m": xy_delta_m,
            "yaw_delta_rad": yaw_delta_rad,
            "exceeds_sidecar_bound": exceeds_sidecar_bound,
        }

    @staticmethod
    def _abs_float(value: Any) -> float:
        return abs(_safe_float(value, 0.0))

    @staticmethod
    def _xy_norm(values: dict[str, Any]) -> float:
        x = _safe_float(values.get("x_m", values.get("dx_m", 0.0)), 0.0)
        y = _safe_float(values.get("y_m", values.get("dy_m", 0.0)), 0.0)
        return (x * x + y * y) ** 0.5

    @staticmethod
    def _replicator_post_render_augmentation(request: IsaacLabSyntheticRequest, output_root: Path) -> dict[str, Any]:
        return {
            "schema": "atr.lerobot.replicator.post_render_augmentation.v1",
            "owner": "isaac_sim_replicator_writer_annotators",
            "execution_stage": "replicator_writer_annotator",
            "manifest_path": str(output_root / "replicator" / "post_render_augmentation.json"),
            "rgb": {
                "enabled": request.rgb_strength > 0.0,
                "annotator": "rgb",
                "strength": request.rgb_strength,
                "operations": ["exposure_jitter", "color_jitter", "sensor_noise"],
            },
            "depth": {
                "enabled": request.depth_strength > 0.0,
                "annotator": "distance_to_image_plane",
                "strength": request.depth_strength,
                "source_profile": "d405_raw_depth_profile",
                "unit": "meters",
                "operations": ["quantization_noise", "dropout", "range_noise"],
            },
            "render": {
                "enabled": request.render_strength > 0.0,
                "strength": request.render_strength,
                "operations": ["lighting", "material", "texture"],
            },
            "camera_pose": {
                "enabled": request.camera_pose_strength > 0.0,
                "strength": request.camera_pose_strength,
                "cameras": list(request.cameras),
                "operations": ["pose_jitter", "intrinsics_jitter"],
            },
            "trajectory_boundary": "render_only_not_action_trajectory",
            "train_boundary": "render_only_same_action",
        }

    def _isaac_sim_smoke_summary(
        self,
        request: IsaacLabSyntheticRequest,
        *,
        runtime_probe: dict[str, Any],
        post_render_augmentation: dict[str, Any],
        expected_render_rows: int,
    ) -> dict[str, Any]:
        runtime_ready = bool(self._isaac_sim_python_value(request))
        status = "ready_to_probe" if runtime_ready else "blocked"
        reason = "" if runtime_ready else "isaac_sim_python_missing"
        return {
            "schema": "atr.lerobot.isaac_sim.smoke_checks.v1",
            "status": status,
            "runtime_probe": dict(runtime_probe),
            "checks": [
                {
                    "id": "replicator_rgb_render_product",
                    "status": status,
                    "annotator": "rgb",
                    "expected_rows": expected_render_rows,
                    "resolution": list(REPLICATOR_RENDER_RESOLUTION),
                    "reason": reason,
                },
                {
                    "id": "replicator_depth_render_product",
                    "status": status,
                    "annotator": "distance_to_image_plane",
                    "expected_rows": expected_render_rows,
                    "depth_units": "meters",
                    "reason": reason,
                },
                {
                    "id": "replicator_writer_output",
                    "status": status,
                    "writer_type": REPLICATOR_WRITER_TYPE,
                    "annotators": list(REPLICATOR_ANNOTATORS),
                    "reason": reason,
                },
                {
                    "id": "scene_randomization",
                    "status": status,
                    "owner": "isaac_sim_replicator_writer_annotators",
                    "rgb_strength": (post_render_augmentation.get("rgb") or {}).get("strength", 0.0),
                    "depth_strength": (post_render_augmentation.get("depth") or {}).get("strength", 0.0),
                    "render_strength": (post_render_augmentation.get("render") or {}).get("strength", 0.0),
                    "camera_pose_strength": (post_render_augmentation.get("camera_pose") or {}).get("strength", 0.0),
                    "reason": reason,
                },
                {
                    "id": "physics_collider_debug",
                    "status": status,
                    "backend": "PhysX",
                    "debug_visualization": "deferred_to_isaac_runtime",
                    "reason": reason,
                },
            ],
            "blockers": [
                {
                    "code": "ISAAC_SIM_SMOKE_RUNTIME_MISSING",
                    "message": "Isaac Sim smoke checks require isaac_sim_python.",
                }
            ]
            if not runtime_ready
            else [],
        }

    @staticmethod
    def _replicator_blocker(validation_report: dict[str, Any]) -> dict[str, Any]:
        for blocker in list((validation_report or {}).get("blockers") or []):
            code = str(blocker.get("code") or "")
            check = str(blocker.get("check") or "")
            if code.startswith("REPLICATOR_") or check == "validate_replicator_runtime":
                return blocker
        return {}

    def _write_replicator_artifacts(self, output_root: Path, summary: dict[str, Any]) -> None:
        _atomic_write_json(output_root / "replicator" / "summary.json", summary)
        _atomic_write_json(
            output_root / "replicator" / "post_render_augmentation.json",
            dict(summary.get("post_render_augmentation") or {}),
        )
        _atomic_write_json(
            output_root / "replicator" / "isaac_sim_smoke.json",
            dict(summary.get("isaac_sim_smoke") or {}),
        )
        _atomic_write_json(output_root / "replicator" / "build_plan.json", self._replicator_build_plan(summary))

    @staticmethod
    def _replicator_artifact_path(output_root: Path, raw_path: Any) -> Path:
        path = Path(str(raw_path or "")).expanduser()
        return path if path.is_absolute() else output_root / path

    def _replicator_render_file_validation(self, output_root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
        invalid_rows: list[dict[str, Any]] = []
        missing_rgb_count = 0
        missing_depth_count = 0
        missing_metadata_count = 0
        valid_row_count = 0
        for index, row in enumerate(rows):
            rgb_path = self._replicator_artifact_path(output_root, row.get("rgb_path"))
            depth_path = self._replicator_artifact_path(output_root, row.get("depth_path"))
            metadata_raw = str(row.get("metadata_path") or "").strip()
            metadata_path = self._replicator_artifact_path(output_root, metadata_raw) if metadata_raw else Path()
            missing: list[str] = []
            if not rgb_path.is_file():
                missing.append("rgb_path")
                missing_rgb_count += 1
            if not depth_path.is_file():
                missing.append("depth_path")
                missing_depth_count += 1
            if metadata_raw and not metadata_path.is_file():
                missing.append("metadata_path")
                missing_metadata_count += 1
            if missing:
                invalid_rows.append(
                    {
                        "row_index": index,
                        "episode_index": row.get("episode_index"),
                        "frame_index": row.get("frame_index"),
                        "camera": row.get("camera") or row.get("camera_name") or "",
                        "variant_index": row.get("variant_index"),
                        "missing": missing,
                    }
                )
            else:
                valid_row_count += 1
        return {
            "schema": "atr.lerobot.replicator.render_file_validation.v1",
            "ok": not invalid_rows,
            "row_count": len(rows),
            "valid_row_count": valid_row_count,
            "invalid_row_count": len(invalid_rows),
            "missing_rgb_count": missing_rgb_count,
            "missing_depth_count": missing_depth_count,
            "missing_metadata_count": missing_metadata_count,
            "invalid_rows": invalid_rows[:50],
        }

    def _replicator_render_output_counts(self, output_root: Path, rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"rgb_output_count": 0, "depth_output_count": 0, "segmentation_output_count": 0}
        for row in rows:
            rgb_raw = str(row.get("rgb_path") or "").strip()
            depth_raw = str(row.get("depth_path") or "").strip()
            segmentation_raw = str(row.get("segmentation_path") or "").strip()
            if rgb_raw and self._replicator_artifact_path(output_root, rgb_raw).is_file():
                counts["rgb_output_count"] += 1
            if depth_raw and self._replicator_artifact_path(output_root, depth_raw).is_file():
                counts["depth_output_count"] += 1
            if segmentation_raw and self._replicator_artifact_path(output_root, segmentation_raw).is_file():
                counts["segmentation_output_count"] += 1
        return counts

    def _replicator_runtime_probe(self, request: IsaacLabSyntheticRequest, *, blocker: dict[str, Any] | None) -> dict[str, Any]:
        python_path = self._isaac_sim_python_path(request)
        resolved_python = ""
        if python_path and str(python_path) != ".":
            try:
                resolved_python = str(python_path.resolve())
            except OSError:
                resolved_python = str(python_path)
        if not request.enable_replicator:
            return {
                "status": "skipped",
                "import_checked": False,
                "required_modules": list(REPLICATOR_REQUIRED_MODULES),
                "python_path": resolved_python,
                "reason": "Replicator branch is disabled.",
            }
        if blocker:
            return {
                "status": "blocked",
                "import_checked": False,
                "required_modules": list(REPLICATOR_REQUIRED_MODULES),
                "python_path": resolved_python,
                "reason": str(blocker.get("message") or "Replicator runtime is blocked before import probe."),
            }
        return {
            "status": "pending",
            "import_checked": False,
            "required_modules": list(REPLICATOR_REQUIRED_MODULES),
            "python_path": resolved_python,
            "reason": "Runtime path is configured, but Replicator import is deferred to the Isaac Sim worker.",
        }

    @staticmethod
    def _replicator_build_plan(summary: dict[str, Any]) -> dict[str, Any]:
        repo_root = Path(__file__).resolve().parents[1]
        worker_script = repo_root / "scripts" / "lerobot_isaac_replicator_synthetic.py"
        output_root = Path(str(summary.get("output_root") or ""))
        replicator_output = output_root / "replicator"
        canonical_index = output_root / "canonical_episode_index" / "manifest.jsonl"
        isaac_sim_python = str(summary.get("isaac_sim_python") or "").strip()
        post_render_augmentation = dict(summary.get("post_render_augmentation") or {})
        command = [
            isaac_sim_python or "<isaac-sim-python>",
            str(worker_script),
            "--canonical-index",
            str(canonical_index),
            "--stage-url",
            str(summary.get("stage_path", "")),
            "--output-dir",
            str(replicator_output),
            "--augmentation-config",
            str(replicator_output / "post_render_augmentation.json"),
            "--cameras",
            ",".join(str(camera) for camera in list(summary.get("cameras") or [])),
            "--variants",
            str(summary.get("attempts_per_source_frame", 1)),
            "--rgb-strength",
            str((post_render_augmentation.get("rgb") or {}).get("strength", 0.0)),
            "--depth-strength",
            str((post_render_augmentation.get("depth") or {}).get("strength", 0.0)),
            "--render-strength",
            str((post_render_augmentation.get("render") or {}).get("strength", 0.0)),
            "--camera-pose-strength",
            str((post_render_augmentation.get("camera_pose") or {}).get("strength", 0.0)),
        ]
        return {
            "schema": "atr.lerobot.replicator_synthetic.build_plan.v1",
            "status": summary.get("status", "skipped"),
            "enabled": bool(summary.get("enabled")),
            "blocker": summary.get("blocker", ""),
            "replicator_available": bool(summary.get("replicator_available")),
            "writer_type": summary.get("writer_type", REPLICATOR_WRITER_TYPE),
            "annotators": list(summary.get("annotators") or REPLICATOR_ANNOTATORS),
            "post_render_augmentation": post_render_augmentation,
            "render_products": dict(summary.get("render_products") or {}),
            "depth_units_replicator": dict(summary.get("depth_units_replicator") or {}),
            "teleop_sdg_replay_used": bool(summary.get("teleop_sdg_replay_used")),
            "teleop_sdg_replay_boundary": summary.get("teleop_sdg_replay_boundary", ""),
            "dataset_path": summary.get("dataset_path", ""),
            "stage_path": summary.get("stage_path", ""),
            "isaac_sim_python": summary.get("isaac_sim_python", ""),
            "canonical_frame_count": summary.get("canonical_frame_count", 0),
            "expected_render_rows": summary.get("expected_render_rows", 0),
            "manifest_path": summary.get("manifest_path", ""),
            "cameras": list(summary.get("cameras") or []),
            "attempts_per_source_frame": summary.get("attempts_per_source_frame", 1),
            "runtime_probe": dict(summary.get("runtime_probe") or {}),
            "isaac_sim_smoke": dict(summary.get("isaac_sim_smoke") or {}),
            "worker": {
                "script": str(worker_script),
                "python": isaac_sim_python or "<isaac-sim-python>",
                "command": command,
            },
            "outputs": {
                "rgb_root": "rgb",
                "depth_root": "depth",
                "segmentation_root": "segmentation",
                "metadata_root": "metadata",
            },
        }

    def _write_lab_hook_summaries(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        hdf5_summary = _read_json(output_root / "hdf5" / "export_summary.json")
        env_wrapper = self._write_omx_lab_env_wrapper(request, dataset_path, output_root)
        mimic_summary = self._mimic_hook_summary(request, dataset_path, output_root, hdf5_summary, env_wrapper)
        rl_teacher_summary = self._rl_teacher_hook_summary(request, dataset_path, output_root, hdf5_summary, env_wrapper)
        self._write_hook_artifacts(output_root / "mimic", mimic_summary)
        self._write_hook_artifacts(output_root / "rl_teacher", rl_teacher_summary)
        return mimic_summary, rl_teacher_summary

    def _write_omx_lab_env_wrapper(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
    ) -> dict[str, Any]:
        manifest_path = output_root / "lab_env" / "robotis_omx_pick_place_env.json"
        event_config_path = output_root / "lab_env" / "domain_randomization_events.json"
        event_config = self._isaac_lab_domain_randomization_events(request, dataset_path, output_root, event_config_path)
        _atomic_write_json(event_config_path, event_config)
        manifest = self._omx_lab_env_wrapper_manifest(
            request,
            dataset_path,
            output_root,
            manifest_path,
            event_config_path=event_config_path,
        )
        _atomic_write_json(manifest_path, manifest)
        return {
            "schema": "atr.lerobot.isaac_lab_omx_env_wrapper.status.v1",
            "status": "ready" if manifest.get("ready") else "blocked",
            "blocker": "" if manifest.get("ready") else "LAB_ENV_CONTRACT_INCOMPLETE",
            "manifest_path": str(manifest_path),
            "domain_randomization_events_path": str(event_config_path),
            "task_name": manifest["task_name"],
            "required_helpers": list(manifest["required_helpers"]),
            "required_subtasks": list(manifest["subtask_termination_signals"]),
            "reward_terms": [str(term.get("id") or "") for term in manifest["reward_terms"]],
            "checks": list(manifest["checks"]),
        }

    def _omx_lab_env_wrapper_manifest(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        manifest_path: Path,
        event_config_path: Path,
    ) -> dict[str, Any]:
        stage_path = self._stage_path(request)
        checks = [
            {"id": "required_helpers_declared", "status": "passed"},
            {"id": "object_pose_contract_declared", "status": "passed"},
            {"id": "action_conversion_contract_declared", "status": "passed"},
            {"id": "gripper_action_extraction_declared", "status": "passed"},
            {"id": "subtask_termination_signals_declared", "status": "passed"},
            {"id": "reset_events_declared", "status": "passed"},
            {"id": "reward_terms_declared", "status": "passed"},
        ]
        return {
            "schema": "atr.lerobot.isaac_lab_omx_env_wrapper.v1",
            "ready": True,
            "generated_at": _now(),
            "task_name": "RobotisOMXPickPlaceLabEnv",
            "dataset_path": str(dataset_path),
            "output_root": str(output_root),
            "manifest_path": str(manifest_path),
            "domain_randomization_events_path": str(event_config_path),
            "stage_path": str(stage_path),
            "isaac_lab_path": str(self._isaac_lab_path(request)),
            "source_contracts": {
                "canonical_index": str(output_root / "canonical_episode_index" / "manifest.jsonl"),
                "hdf5_demonstrations": str(output_root / "hdf5" / "exported_successful_real_episodes.hdf5"),
                "grasp_events": "canonical.grasp_event_labels",
            },
            "required_helpers": list(ISAAC_LAB_OMX_ENV_HELPERS),
            "object_pose_contract": {
                "frame": "robot_base",
                "object_name": "red_cube",
                "source": "active_robot_cam_when_available_else_stage_cube_pose",
                "fields": ["x_m", "y_m", "z_m", "yaw_rad"],
                "workspace": "a4_sheet",
                "a4_size_m": {"x": 0.210, "y": 0.297},
            },
            "action_space": {
                "control_mode": "eef_delta_pose_plus_gripper",
                "eef_pose_fields": ["x_m", "y_m", "z_m", "qx", "qy", "qz", "qw"],
                "action_fields": ["dx_m", "dy_m", "dz_m", "droll_rad", "dpitch_rad", "dyaw_rad", "gripper"],
                "target_eef_pose_to_action": "target_eef_pose_to_action",
                "action_to_target_eef_pose": "action_to_target_eef_pose",
            },
            "gripper_action": {
                "source": "canonical_grasp_event_labels",
                "extractor": "actions_to_gripper_actions",
                "labels": ["not_near_object", "near_closed_without_contact", "grasp_candidate", "lifted", "released"],
            },
            "subtask_termination_signals": list(MIMIC_REQUIRED_SUBTASKS),
            "subtask_signal_sources": {
                "approach": "distance_to_object_threshold",
                "grasp": "grasp_candidate_or_two_finger_contact",
                "lift": "object_lifted",
                "place": "object_pose_in_place_region",
                "release": "grasp_event_label_released",
            },
            "reset_events": {
                "object_pose_randomization": {
                    "workspace": "a4_sheet",
                    "xy_bounds_m": {"x": [-0.105, 0.105], "y": [-0.1485, 0.1485]},
                    "yaw_bounds_rad": [-3.14159265, 3.14159265],
                    "attempts_per_source_frame": request.attempts_per_source_frame,
                },
                "physics_material_randomization": {
                    "enabled": request.render_strength > 0.0,
                    "strength": request.render_strength,
                    "objects": ["red_cube", "paper_table", "gripper_inner_pad"],
                },
                "camera_randomization": {
                    "enabled": request.camera_pose_strength > 0.0,
                    "strength": request.camera_pose_strength,
                    "cameras": list(request.cameras),
                },
                "sensor_noise": {
                    "rgb_strength": request.rgb_strength,
                    "depth_strength": request.depth_strength,
                },
            },
            "reward_terms": [
                {"id": "reach_object", "type": "dense", "source": "eef_object_distance"},
                {"id": "grasp_candidate", "type": "sparse", "source": "grasp_event_label"},
                {"id": "lift_object", "type": "sparse", "source": "object_lifted"},
                {"id": "place_object", "type": "sparse", "source": "object_pose_in_place_region"},
                {"id": "safety_limits", "type": "penalty", "source": "joint_velocity_torque_bounds"},
            ],
            "success_criteria": {
                "mimic": list(MIMIC_SUCCESS_CRITERIA),
                "rl_teacher": list(RL_TEACHER_SUCCESS_CRITERIA),
            },
            "checks": checks,
        }

    def _isaac_lab_domain_randomization_events(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        event_config_path: Path,
    ) -> dict[str, Any]:
        return {
            "schema": "atr.lerobot.isaac_lab_domain_randomization_events.v1",
            "owner": "isaac_lab_reset_events",
            "generated_at": _now(),
            "dataset_path": str(dataset_path),
            "output_root": str(output_root),
            "manifest_path": str(event_config_path),
            "docs_api": "EventTermCfg",
            "events": [
                {
                    "name": "randomize_cube_pose_a4",
                    "phase": "reset",
                    "mode": "pose",
                    "params": {
                        "workspace": "a4_sheet",
                        "frame": "robot_base",
                        "xy_bounds_m": {"x": [-0.105, 0.105], "y": [-0.1485, 0.1485]},
                        "yaw_bounds_rad": [-3.14159265, 3.14159265],
                        "attempts_per_source_frame": request.attempts_per_source_frame,
                    },
                },
                {
                    "name": "randomize_physics_materials",
                    "phase": "reset",
                    "mode": "physics_material",
                    "params": {
                        "strength": request.render_strength,
                        "cube_material": "3d_printed_pla",
                        "table_material": "paper",
                        "gripper_inner_pad_material": "anti_slip_tape",
                    },
                },
                {
                    "name": "randomize_camera_pose",
                    "phase": "reset",
                    "mode": "camera_pose",
                    "params": {
                        "strength": request.camera_pose_strength,
                        "cameras": list(request.cameras),
                    },
                },
                {
                    "name": "randomize_rgbd_sensor_noise",
                    "phase": "post_render",
                    "mode": "sensor_noise",
                    "params": {
                        "rgb_strength": request.rgb_strength,
                        "depth_strength": request.depth_strength,
                        "depth_source": "d405_raw_depth_profile",
                    },
                },
            ],
        }

    @staticmethod
    def _remove_smoke_summary(hook_root: Path) -> None:
        try:
            (hook_root / "smoke_summary.json").unlink()
        except FileNotFoundError:
            return
        except OSError:
            return

    def _hook_blocked_validation_report(
        self,
        *,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        stage: str,
        blocker: str,
        message: str,
    ) -> dict[str, Any]:
        return {
            "schema": VALIDATION_SCHEMA,
            "ok": False,
            "status": "blocked",
            "stage": stage,
            "dataset": str(dataset_path),
            "output_root": str(output_root),
            "generated_at": _now(),
            "pipeline_mode": request.pipeline_mode.value,
            "fallback_policy": request.fallback_policy.value,
            "source_intent": request.source_intent.value,
            "checks": [
                {
                    "id": f"{stage}_smoke_ready",
                    "group": stage,
                    "status": "blocked",
                    "severity": "blocker",
                    "message": message,
                    "blocker_code": blocker,
                    "evidence": {"output_root": str(output_root)},
                    "docs": [],
                    "artifacts": {},
                }
            ],
            "blockers": [{"code": blocker, "check": f"{stage}_smoke_ready", "message": message}],
            "warnings": [],
            "artifacts": {},
        }

    def _mimic_smoke_summary(
        self,
        request: IsaacLabSyntheticRequest,
        output_root: Path,
        mimic_summary: dict[str, Any],
    ) -> dict[str, Any]:
        env_wrapper = mimic_summary.get("env_wrapper") if isinstance(mimic_summary.get("env_wrapper"), dict) else {}
        env_manifest = str(env_wrapper.get("manifest_path") or "")
        return {
            "schema": "atr.lerobot.isaac_lab_mimic.smoke_summary.v1",
            "status": "ready_to_launch",
            "dry_run": True,
            "generated_at": _now(),
            "output_root": str(output_root),
            "hdf5_path": str(mimic_summary.get("hdf5_path") or ""),
            "env_wrapper_manifest": env_manifest,
            "mimic_trials": request.mimic_trials,
            "mimic_num_envs": request.mimic_num_envs,
            "required_subtasks": list(mimic_summary.get("required_subtasks") or MIMIC_REQUIRED_SUBTASKS),
            "success_criteria": list(mimic_summary.get("success_criteria") or MIMIC_SUCCESS_CRITERIA),
            "expected_output_manifest": str(output_root / "mimic" / "manifest.jsonl"),
            "runtime_smoke": self._write_runtime_smoke_artifacts(request, output_root, env_manifest),
            "command_preview": {
                "runtime": "Isaac Lab worker",
                "operation": "mimic_generate_dataset",
                "hdf5": str(mimic_summary.get("hdf5_path") or ""),
                "env_wrapper": env_manifest,
                "trials": request.mimic_trials,
                "num_envs": request.mimic_num_envs,
            },
        }

    def _rl_teacher_smoke_summary(
        self,
        request: IsaacLabSyntheticRequest,
        output_root: Path,
        rl_teacher_summary: dict[str, Any],
    ) -> dict[str, Any]:
        env_wrapper = rl_teacher_summary.get("env_wrapper") if isinstance(rl_teacher_summary.get("env_wrapper"), dict) else {}
        env_manifest = str(env_wrapper.get("manifest_path") or "")
        return {
            "schema": "atr.lerobot.isaac_lab_rl_teacher.smoke_summary.v1",
            "status": "ready_to_launch",
            "dry_run": True,
            "generated_at": _now(),
            "output_root": str(output_root),
            "hdf5_path": str(rl_teacher_summary.get("hdf5_path") or ""),
            "env_wrapper_manifest": env_manifest,
            "rl_teacher_steps": request.rl_teacher_steps,
            "simulation_only": True,
            "runtime_policy_export_allowed": False,
            "success_criteria": list(rl_teacher_summary.get("success_criteria") or RL_TEACHER_SUCCESS_CRITERIA),
            "expected_output_manifest": str(output_root / "rl_teacher" / "manifest.jsonl"),
            "runtime_smoke": self._write_runtime_smoke_artifacts(request, output_root, env_manifest),
            "command_preview": {
                "runtime": "Isaac Lab worker",
                "operation": "rl_teacher_smoke",
                "hdf5": str(rl_teacher_summary.get("hdf5_path") or ""),
                "env_wrapper": env_manifest,
                "steps": request.rl_teacher_steps,
                "simulation_only": True,
            },
        }

    def _write_runtime_smoke_artifacts(self, request: IsaacLabSyntheticRequest, output_root: Path, env_manifest: str) -> dict[str, Any]:
        smoke_root = output_root / "runtime_smoke"
        contact_smoke = self._contact_smoke_summary(request, output_root, env_manifest)
        dof_smoke = self._dof_smoke_summary(request, output_root, env_manifest)
        _atomic_write_json(smoke_root / "contact_smoke.json", contact_smoke)
        _atomic_write_json(smoke_root / "dof_smoke.json", dof_smoke)
        return {
            "contact_smoke": {
                "status": contact_smoke["status"],
                "path": str(smoke_root / "contact_smoke.json"),
                "command_preview": dict(contact_smoke.get("command_preview") or {}),
            },
            "dof_smoke": {
                "status": dof_smoke["status"],
                "path": str(smoke_root / "dof_smoke.json"),
                "command_preview": dict(dof_smoke.get("command_preview") or {}),
            },
        }

    def _contact_smoke_summary(self, request: IsaacLabSyntheticRequest, output_root: Path, env_manifest: str) -> dict[str, Any]:
        physics = _read_json(output_root / "physics_preflight.json")
        threshold = 0.2
        checks = physics.get("checks") if isinstance(physics.get("checks"), list) else []
        for check in checks:
            evidence = check.get("evidence") if isinstance(check, dict) else {}
            contact = evidence.get("contact_reporting") if isinstance(evidence, dict) else {}
            if isinstance(contact, dict):
                threshold = _safe_float(contact.get("contact_threshold_n"), threshold, minimum=0.0)
                break
        return {
            "schema": "atr.lerobot.isaac_lab_runtime.contact_smoke.v1",
            "status": "ready_to_launch",
            "dry_run": True,
            "generated_at": _now(),
            "stage_path": str(self._stage_path(request)),
            "env_wrapper_manifest": env_manifest,
            "contact_pairs_required": ["left_finger:red_cube", "right_finger:red_cube"],
            "contact_threshold_n": threshold,
            "expected_output_path": str(output_root / "runtime_smoke" / "contact_result.json"),
            "command_preview": {
                "runtime": "Isaac Sim worker",
                "operation": "contact_smoke",
                "stage": str(self._stage_path(request)),
                "env_wrapper": env_manifest,
                "contact_threshold_n": threshold,
                "required_pairs": ["left_finger:red_cube", "right_finger:red_cube"],
            },
        }

    def _dof_smoke_summary(self, request: IsaacLabSyntheticRequest, output_root: Path, env_manifest: str) -> dict[str, Any]:
        return {
            "schema": "atr.lerobot.isaac_lab_runtime.dof_smoke.v1",
            "status": "ready_to_launch",
            "dry_run": True,
            "generated_at": _now(),
            "stage_path": str(self._stage_path(request)),
            "env_wrapper_manifest": env_manifest,
            "expected_output_path": str(output_root / "runtime_smoke" / "dof_result.json"),
            "checks": [
                "articulation_root_loads",
                "joint_names_match_lerobot_actions",
                "drive_targets_match_current_pose",
                "mimic_gear_direction_valid",
            ],
            "command_preview": {
                "runtime": "Isaac Sim worker",
                "operation": "dof_smoke",
                "stage": str(self._stage_path(request)),
                "env_wrapper": env_manifest,
                "checks": [
                    "articulation_root_loads",
                    "joint_names_match_lerobot_actions",
                    "drive_targets_match_current_pose",
                    "mimic_gear_direction_valid",
                ],
            },
        }

    def _write_mimic_generation_manifests(
        self,
        request: IsaacLabSyntheticRequest,
        output_root: Path,
        mimic_summary: dict[str, Any],
    ) -> dict[str, Any]:
        rows = self._dry_run_mimic_trajectory_rows(request, output_root, mimic_summary)
        successes = [row for row in rows if row.get("metrics", {}).get("success") is True]
        failures = [row for row in rows if row.get("metrics", {}).get("success") is not True]
        mimic_root = output_root / "mimic"
        _atomic_write_jsonl(mimic_root / "candidates.jsonl", rows)
        _atomic_write_jsonl(mimic_root / "successes.jsonl", successes)
        _atomic_write_jsonl(mimic_root / "failures.jsonl", failures)
        generated_dataset_path = mimic_root / "generated_dataset.hdf5"
        generated_dataset_small_path = mimic_root / "generated_dataset_small.hdf5"
        generated_hdf5_summary = self._write_generated_trajectory_hdf5(
            generated_dataset_path,
            successes,
            source_type=IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value,
            output_root=output_root,
        )
        small_hdf5_summary = self._write_generated_trajectory_hdf5(
            generated_dataset_small_path,
            successes[: min(len(successes), max(1, request.mimic_num_envs))],
            source_type=IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value,
            output_root=output_root,
        )
        return {
            "candidate_count": len(rows),
            "success_count": len(successes),
            "failure_count": len(failures),
            "candidate_manifest_path": str(mimic_root / "candidates.jsonl"),
            "success_manifest_path": str(mimic_root / "successes.jsonl"),
            "failure_manifest_path": str(mimic_root / "failures.jsonl"),
            "generated_dataset_path": str(generated_dataset_path),
            "generated_dataset_small_path": str(generated_dataset_small_path),
            "generated_hdf5": generated_hdf5_summary,
            "generated_hdf5_small": small_hdf5_summary,
        }

    def _write_rl_teacher_generation_manifests(
        self,
        request: IsaacLabSyntheticRequest,
        output_root: Path,
        rl_teacher_summary: dict[str, Any],
    ) -> dict[str, Any]:
        rows = self._dry_run_rl_teacher_trajectory_rows(request, output_root, rl_teacher_summary)
        successes = [row for row in rows if row.get("metrics", {}).get("success") is True]
        failures = [row for row in rows if row.get("metrics", {}).get("success") is not True]
        rl_root = output_root / "rl_teacher"
        _atomic_write_jsonl(rl_root / "candidates.jsonl", rows)
        _atomic_write_jsonl(rl_root / "successes.jsonl", successes)
        _atomic_write_jsonl(rl_root / "failures.jsonl", failures)
        generated_dataset_path = rl_root / "generated_dataset.hdf5"
        generated_hdf5_summary = self._write_generated_trajectory_hdf5(
            generated_dataset_path,
            successes,
            source_type=IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value,
            output_root=output_root,
        )
        return {
            "candidate_count": len(rows),
            "success_count": len(successes),
            "failure_count": len(failures),
            "candidate_manifest_path": str(rl_root / "candidates.jsonl"),
            "success_manifest_path": str(rl_root / "successes.jsonl"),
            "failure_manifest_path": str(rl_root / "failures.jsonl"),
            "generated_dataset_path": str(generated_dataset_path),
            "generated_hdf5": generated_hdf5_summary,
        }

    def _write_generated_trajectory_hdf5(
        self,
        output_path: Path,
        rows: list[dict[str, Any]],
        *,
        source_type: str,
        output_root: Path,
    ) -> dict[str, Any]:
        import h5py
        import numpy as np

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_name(f"{output_path.name}.tmp.{os.getpid()}")
        if tmp_path.exists():
            tmp_path.unlink()
        string_dtype = h5py.string_dtype(encoding="utf-8")
        with h5py.File(tmp_path, "w") as handle:
            handle.attrs["schema"] = "atr.lerobot.generated_trajectory_hdf5.v1"
            handle.attrs["source_type"] = source_type
            handle.attrs["output_root"] = str(output_root)
            handle.attrs["generated_at"] = _now()
            handle.attrs["success_count"] = len(rows)
            handle.attrs["trajectory_ids"] = json.dumps([str(row.get("trajectory_id") or "") for row in rows])
            data_group = handle.create_group("data")
            for index, row in enumerate(rows):
                trajectory_id = str(row.get("trajectory_id") or row.get("source_id") or f"trajectory_{index:06d}")
                trajectory = data_group.create_group(trajectory_id)
                actions = self._generated_hdf5_actions(row)
                states = self._generated_hdf5_states(row, actions.shape[0])
                frame_start = self._generated_frame_start(row)
                frame_indices = np.arange(frame_start, frame_start + actions.shape[0], dtype=np.int64)
                trajectory.attrs["source_type"] = source_type
                trajectory.attrs["trajectory_id"] = trajectory_id
                trajectory.attrs["success"] = True
                trajectory.attrs["generator"] = str(row.get("generator") or "")
                trajectory.attrs["source_episode_index"] = _safe_int(row.get("source_episode_index"), 0, minimum=0)
                trajectory.attrs["source_frame_index"] = _safe_int(row.get("source_frame_index"), 0, minimum=0)
                trajectory.attrs["frame_start"] = frame_start
                trajectory.attrs["frame_end"] = self._generated_frame_end(row)
                trajectory.attrs["num_samples"] = int(actions.shape[0])
                training = row.get("training") if isinstance(row.get("training"), dict) else {}
                trajectory.attrs["fidelity_weight"] = _safe_float(training.get("fidelity_weight"), 0.0, minimum=0.0, maximum=1.0)
                trajectory.create_dataset("actions", data=actions)
                trajectory.create_dataset("states", data=states)
                trajectory.create_dataset("frame_indices", data=frame_indices)
                object_pose = row.get("object_pose_randomization") if isinstance(row.get("object_pose_randomization"), dict) else {}
                object_pose_group = trajectory.create_group("object_pose_randomization")
                for key, value in sorted(object_pose.items()):
                    if isinstance(value, (str, int, float, bool)):
                        object_pose_group.attrs[key] = value
                    else:
                        object_pose_group.attrs[key] = json.dumps(value)
                metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
                metrics_group = trajectory.create_group("metrics")
                for key, value in sorted(metrics.items()):
                    if isinstance(value, (int, float, bool)):
                        metrics_group.attrs[key] = value
                    else:
                        metrics_group.attrs[key] = str(value)
                subtasks = row.get("subtasks") if isinstance(row.get("subtasks"), dict) else {}
                subtasks_group = trajectory.create_group("subtasks")
                for name, subtask in sorted(subtasks.items()):
                    if not isinstance(subtask, dict):
                        continue
                    subtask_group = subtasks_group.create_group(str(name))
                    subtask_group.attrs["start_frame"] = _safe_int(subtask.get("start_frame"), frame_start, minimum=0)
                    subtask_group.attrs["end_frame"] = _safe_int(subtask.get("end_frame"), frame_start, minimum=0)
                artifact_json = json.dumps(row.get("artifacts") if isinstance(row.get("artifacts"), dict) else {})
                trajectory.create_dataset("artifact_metadata", data=artifact_json, dtype=string_dtype)
        tmp_path.replace(output_path)
        return {
            "schema": "atr.lerobot.generated_trajectory_hdf5.summary.v1",
            "status": "passed",
            "path": str(output_path),
            "source_type": source_type,
            "success_count": len(rows),
            "trajectory_ids": [str(row.get("trajectory_id") or "") for row in rows],
        }

    @staticmethod
    def _generated_hdf5_actions(row: dict[str, Any]) -> Any:
        import numpy as np

        num_frames = max(1, _safe_int(row.get("num_frames"), 1, minimum=1))
        object_pose = row.get("object_pose_randomization") if isinstance(row.get("object_pose_randomization"), dict) else {}
        x_m = _safe_float(object_pose.get("x_m"), 0.0)
        y_m = _safe_float(object_pose.get("y_m"), 0.0)
        yaw_rad = _safe_float(object_pose.get("yaw_rad"), 0.0)
        actions = np.zeros((num_frames, 7), dtype=np.float64)
        actions[:, 0] = np.linspace(0.0, x_m, num_frames)
        actions[:, 1] = np.linspace(0.0, y_m, num_frames)
        actions[:, 2] = np.linspace(0.0, 0.04, num_frames)
        actions[:, 5] = np.linspace(0.0, yaw_rad, num_frames)
        if num_frames > 1:
            actions[:, 6] = np.linspace(0.0, 1.0, num_frames)
        else:
            actions[:, 6] = 1.0
        return actions

    @staticmethod
    def _generated_hdf5_states(row: dict[str, Any], num_frames: int) -> Any:
        import numpy as np

        object_pose = row.get("object_pose_randomization") if isinstance(row.get("object_pose_randomization"), dict) else {}
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        source_episode_index = _safe_int(row.get("source_episode_index"), 0, minimum=0)
        source_frame_index = _safe_int(row.get("source_frame_index"), 0, minimum=0)
        x_m = _safe_float(object_pose.get("x_m"), 0.0)
        y_m = _safe_float(object_pose.get("y_m"), 0.0)
        yaw_rad = _safe_float(object_pose.get("yaw_rad"), 0.0)
        lift_height_m = _safe_float(metrics.get("lift_height_m"), 0.0, minimum=0.0)
        stable_hold_s = _safe_float(metrics.get("stable_hold_s"), 0.0, minimum=0.0)
        states = np.zeros((num_frames, 8), dtype=np.float64)
        states[:, 0] = source_episode_index
        states[:, 1] = source_frame_index
        states[:, 2] = x_m
        states[:, 3] = y_m
        states[:, 4] = yaw_rad
        states[:, 5] = lift_height_m
        states[:, 6] = stable_hold_s
        states[:, 7] = 1.0
        return states

    def _dry_run_mimic_trajectory_rows(
        self,
        request: IsaacLabSyntheticRequest,
        output_root: Path,
        mimic_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        canonical_rows = _read_jsonl(output_root / "canonical_episode_index" / "manifest.jsonl")
        trial_count = max(1, request.mimic_trials)
        rows: list[dict[str, Any]] = []
        for index in range(trial_count):
            source_row = canonical_rows[index % len(canonical_rows)] if canonical_rows else {}
            success = not (trial_count > 1 and index % 4 == 3)
            failure_label = "" if success else "grasp_missed"
            trajectory_id = f"mimic_{index:06d}"
            row = self._generated_trajectory_row(
                source_type=IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value,
                trajectory_id=trajectory_id,
                source_row=source_row,
                index=index,
                success=success,
                failure_label=failure_label,
                hdf5_path="mimic/generated_dataset.hdf5",
                preview_path=f"mimic/previews/{trajectory_id}.html",
                fidelity_weight=0.25,
                generator="isaac_lab_mimic_dry_run",
                hdf5_source_path=str(mimic_summary.get("hdf5_path") or ""),
            )
            rows.append(row)
        return rows

    def _dry_run_rl_teacher_trajectory_rows(
        self,
        request: IsaacLabSyntheticRequest,
        output_root: Path,
        rl_teacher_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        canonical_rows = _read_jsonl(output_root / "canonical_episode_index" / "manifest.jsonl")
        source_row = canonical_rows[0] if canonical_rows else {}
        return [
            self._generated_trajectory_row(
                source_type=IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value,
                trajectory_id="rl_teacher_000000",
                source_row=source_row,
                index=0,
                success=True,
                failure_label="",
                hdf5_path="rl_teacher/generated_dataset.hdf5",
                preview_path="rl_teacher/previews/rl_teacher_000000.html",
                fidelity_weight=0.3,
                generator="isaac_lab_rl_teacher_dry_run",
                hdf5_source_path=str(rl_teacher_summary.get("hdf5_path") or ""),
            )
        ]

    @staticmethod
    def _generated_trajectory_row(
        *,
        source_type: str,
        trajectory_id: str,
        source_row: dict[str, Any],
        index: int,
        success: bool,
        failure_label: str,
        hdf5_path: str,
        preview_path: str,
        fidelity_weight: float,
        generator: str,
        hdf5_source_path: str,
    ) -> dict[str, Any]:
        source_episode_index = _safe_int(source_row.get("episode_index"), 0, minimum=0)
        source_frame_index = _safe_int(source_row.get("frame_index"), index, minimum=0)
        frame_start = max(0, source_frame_index)
        frame_end = frame_start + 4
        x_m = round(((index % 5) - 2) * 0.01, 4)
        y_m = round(((index % 7) - 3) * 0.01, 4)
        yaw_rad = round(((index % 9) - 4) * 0.05, 4)
        return {
            "schema": "atr.lerobot.generated_trajectory.v1",
            "source_type": source_type,
            "trajectory_id": trajectory_id,
            "generator": generator,
            "dry_run": True,
            "source_episode_index": source_episode_index,
            "source_frame_index": source_frame_index,
            "frame_start": frame_start,
            "frame_end": frame_end,
            "num_frames": frame_end - frame_start + 1,
            "object_pose_randomization": {
                "workspace": "a4_sheet",
                "x_m": x_m,
                "y_m": y_m,
                "yaw_rad": yaw_rad,
                "bounds_m": {"x": [-0.105, 0.105], "y": [-0.1485, 0.1485]},
            },
            "subtasks": {
                "approach": {"start_frame": frame_start, "end_frame": frame_start + 1},
                "grasp": {"start_frame": frame_start + 1, "end_frame": frame_start + 2},
                "lift": {"start_frame": frame_start + 2, "end_frame": frame_start + 3},
                "place": {"start_frame": frame_start + 3, "end_frame": frame_end},
                "release": {"start_frame": frame_end, "end_frame": frame_end},
            },
            "metrics": {
                "success": success,
                "failure_label": failure_label,
                "max_penetration_m": 0.001 if success else 0.018,
                "lift_height_m": 0.04 if success else 0.0,
                "stable_hold_s": 0.5 if success else 0.0,
            },
            "artifacts": {
                "hdf5_path": hdf5_path,
                "preview_path": preview_path,
                "source_hdf5_path": hdf5_source_path,
            },
            "training": {
                "eligible": success,
                "fidelity_weight": fidelity_weight,
                "exclusion_reason": "" if success else failure_label,
            },
        }

    def _write_hook_artifacts(self, hook_root: Path, summary: dict[str, Any]) -> None:
        _atomic_write_json(hook_root / "summary.json", summary)
        _atomic_write_json(hook_root / "preflight.json", self._hook_preflight(summary))
        _atomic_write_json(hook_root / "config.json", self._hook_config(summary))

    @staticmethod
    def _hook_preflight(summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": str(summary.get("schema") or "").replace(".summary.", ".preflight."),
            "status": summary.get("status", "skipped"),
            "enabled": bool(summary.get("enabled")),
            "blocker": summary.get("blocker", ""),
            "message": summary.get("message", ""),
            "hdf5_path": summary.get("hdf5_path", ""),
            "checks": list(summary.get("checks") or []),
        }

    @staticmethod
    def _hook_config(summary: dict[str, Any]) -> dict[str, Any]:
        config_keys = {
            "dataset_path",
            "output_root",
            "stage_path",
            "hdf5_path",
            "required_subtasks",
            "success_criteria",
            "mimic_trials",
            "mimic_num_envs",
            "rl_teacher_steps",
            "source_type",
            "source_weight",
            "fidelity_weight",
        }
        return {
            "schema": str(summary.get("schema") or "").replace(".summary.", ".config."),
            "status": summary.get("status", "skipped"),
            "enabled": bool(summary.get("enabled")),
            "parameters": {
                **{key: summary[key] for key in sorted(config_keys) if key in summary},
                "env_wrapper_manifest": str(
                    (
                        summary.get("env_wrapper")
                        if isinstance(summary.get("env_wrapper"), dict)
                        else {}
                    ).get("manifest_path")
                    or ""
                ),
            },
        }

    @staticmethod
    def _generated_manifest_counts(hook_root: Path, source_type: str) -> dict[str, Any]:
        candidates = [
            row
            for row in _read_jsonl(hook_root / "candidates.jsonl")
            if str(row.get("source_type") or source_type) == source_type
        ]
        successes = [
            row
            for row in _read_jsonl(hook_root / "successes.jsonl")
            if str(row.get("source_type") or source_type) == source_type
        ]
        failures = [
            row
            for row in _read_jsonl(hook_root / "failures.jsonl")
            if str(row.get("source_type") or source_type) == source_type
        ]
        return {
            "candidate_count": len(candidates),
            "success_count": len(successes),
            "failure_count": len(failures),
            "candidate_manifest_path": str(hook_root / "candidates.jsonl"),
            "success_manifest_path": str(hook_root / "successes.jsonl"),
            "failure_manifest_path": str(hook_root / "failures.jsonl"),
        }

    def _synthetic_trajectory_metrics(
        self,
        output_root: Path,
        *,
        mimic: dict[str, Any] | None = None,
        rl_teacher: dict[str, Any] | None = None,
        training_exposure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        training_rows = _read_jsonl(output_root / "training_import" / "manifest.jsonl")
        training_by_label: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"training_row_count": 0, "effective_training_samples": 0.0}
        )
        for row in training_rows:
            if str(row.get("source_type") or "") != ISAAC_LAB_SYNTHETIC_AGGREGATE_SOURCE:
                continue
            source_label = str(row.get("source_label") or row.get("generator_source_type") or "").strip()
            if source_label not in {
                IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value,
                IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value,
            }:
                continue
            training_by_label[source_label]["training_row_count"] += 1
            training_by_label[source_label]["effective_training_samples"] += _safe_float(
                row.get("effective_weight"),
                0.0,
                minimum=0.0,
            )

        def metric(hook_name: str, source_type: str, summary: dict[str, Any] | None) -> dict[str, Any]:
            summary = summary or {}
            manifest_counts = self._generated_manifest_counts(output_root / hook_name, source_type)
            training = training_by_label[source_type]
            return {
                "status": str(summary.get("status") or "skipped"),
                "source_type": source_type,
                "candidate_count": _safe_int(summary.get("candidate_count"), manifest_counts["candidate_count"], minimum=0),
                "success_count": _safe_int(summary.get("success_count"), manifest_counts["success_count"], minimum=0),
                "failure_count": _safe_int(summary.get("failure_count"), manifest_counts["failure_count"], minimum=0),
                "training_row_count": _safe_int(training.get("training_row_count"), 0, minimum=0),
                "effective_training_samples": round(
                    _safe_float(training.get("effective_training_samples"), 0.0, minimum=0.0),
                    6,
                ),
                "candidate_manifest_path": str(summary.get("candidate_manifest_path") or manifest_counts["candidate_manifest_path"]),
                "success_manifest_path": str(summary.get("success_manifest_path") or manifest_counts["success_manifest_path"]),
                "failure_manifest_path": str(summary.get("failure_manifest_path") or manifest_counts["failure_manifest_path"]),
            }

        mimic_metric = metric("mimic", IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value, mimic)
        rl_metric = metric("rl_teacher", IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value, rl_teacher)
        training_exposure = training_exposure or {}
        synthetic_training_count = _safe_int(
            dict(training_exposure.get("source_counts") or {}).get(ISAAC_LAB_SYNTHETIC_AGGREGATE_SOURCE),
            mimic_metric["training_row_count"] + rl_metric["training_row_count"],
            minimum=0,
        )
        return {
            "schema": "atr.lerobot.synthetic_trajectory_metrics.v1",
            "mimic": mimic_metric,
            "rl_teacher": rl_metric,
            "total": {
                "candidate_count": mimic_metric["candidate_count"] + rl_metric["candidate_count"],
                "success_count": mimic_metric["success_count"] + rl_metric["success_count"],
                "failure_count": mimic_metric["failure_count"] + rl_metric["failure_count"],
                "training_row_count": synthetic_training_count,
                "effective_training_samples": round(
                    mimic_metric["effective_training_samples"] + rl_metric["effective_training_samples"],
                    6,
                ),
            },
        }

    def _mimic_hook_summary(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        hdf5_summary: dict[str, Any],
        env_wrapper: dict[str, Any],
    ) -> dict[str, Any]:
        manifest_counts = self._generated_manifest_counts(output_root / "mimic", IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value)
        base = {
            "schema": MIMIC_SUMMARY_SCHEMA,
            "enabled": bool(request.enable_mimic),
            "generated_at": _now(),
            "dataset_path": str(dataset_path),
            "output_root": str(output_root),
            "stage_path": str(self._stage_path(request)),
            "required_subtasks": list(MIMIC_REQUIRED_SUBTASKS),
            "success_criteria": list(MIMIC_SUCCESS_CRITERIA),
            "mimic_trials": request.mimic_trials,
            "mimic_num_envs": request.mimic_num_envs,
            "source_type": IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value,
            "source_weight": request.isaac_lab_synthetic_weight,
            "fidelity_weight": 1.0,
            **manifest_counts,
            "training_import_path": str(output_root / "training_import" / "manifest.jsonl"),
            "env_wrapper": env_wrapper,
        }
        if not request.enable_mimic:
            return {
                **base,
                "status": "skipped",
                "blocker": "",
                "message": "Isaac Lab Mimic branch is disabled for this request.",
                "hdf5_path": "",
                "checks": [{"id": "mimic_enabled", "status": "skipped"}],
            }
        hdf5_path = str(hdf5_summary.get("output_path") or output_root / "hdf5" / "exported_successful_real_episodes.hdf5")
        if not hdf5_summary.get("hdf5_available"):
            return {
                **base,
                "status": "blocked",
                "blocker": "MIMIC_HDF5_EXPORT_MISSING",
                "message": "Mimic requires a successful Isaac Lab/robomimic HDF5 export before trajectory generation.",
                "hdf5_path": hdf5_path,
                "checks": [
                    {"id": "mimic_enabled", "status": "passed"},
                    {"id": "hdf5_available", "status": "blocked", "blocker": "MIMIC_HDF5_EXPORT_MISSING"},
                    {"id": "required_subtasks_declared", "status": "passed"},
                    {"id": "success_criteria_declared", "status": "passed"},
                    {"id": "env_wrapper_ready", "status": env_wrapper.get("status", "blocked")},
                ],
            }
        if env_wrapper.get("status") != "ready":
            return {
                **base,
                "status": "blocked",
                "blocker": "MIMIC_ENV_NOT_READY",
                "message": "Mimic requires the OMX Isaac Lab environment wrapper contract before trajectory generation.",
                "hdf5_path": hdf5_path,
                "checks": [
                    {"id": "mimic_enabled", "status": "passed"},
                    {"id": "hdf5_available", "status": "passed"},
                    {"id": "env_wrapper_ready", "status": "blocked", "blocker": "MIMIC_ENV_NOT_READY"},
                    {"id": "required_subtasks_declared", "status": "passed"},
                    {"id": "success_criteria_declared", "status": "passed"},
                ],
            }
        return {
            **base,
            "status": "ready",
            "blocker": "",
            "message": "Mimic small-batch generation is ready to launch from exported HDF5 demonstrations.",
            "hdf5_path": hdf5_path,
            "checks": [
                {"id": "mimic_enabled", "status": "passed"},
                {"id": "hdf5_available", "status": "passed"},
                {"id": "env_wrapper_ready", "status": "passed"},
                {"id": "required_subtasks_declared", "status": "passed"},
                {"id": "success_criteria_declared", "status": "passed"},
            ],
        }

    def _rl_teacher_hook_summary(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        hdf5_summary: dict[str, Any],
        env_wrapper: dict[str, Any],
    ) -> dict[str, Any]:
        manifest_counts = self._generated_manifest_counts(output_root / "rl_teacher", IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value)
        base = {
            "schema": RL_TEACHER_SUMMARY_SCHEMA,
            "enabled": bool(request.enable_rl_teacher),
            "generated_at": _now(),
            "dataset_path": str(dataset_path),
            "output_root": str(output_root),
            "stage_path": str(self._stage_path(request)),
            "success_criteria": list(RL_TEACHER_SUCCESS_CRITERIA),
            "rl_teacher_steps": request.rl_teacher_steps,
            "source_type": IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value,
            "source_weight": request.isaac_lab_synthetic_weight,
            "fidelity_weight": 1.0,
            **manifest_counts,
            "simulation_only": True,
            "runtime_policy_export_allowed": False,
            "training_import_path": str(output_root / "training_import" / "manifest.jsonl"),
            "env_wrapper": env_wrapper,
        }
        if not request.enable_rl_teacher:
            return {
                **base,
                "status": "skipped",
                "blocker": "",
                "message": "RL teacher branch is disabled for this request.",
                "hdf5_path": "",
                "checks": [{"id": "rl_teacher_enabled", "status": "skipped"}],
            }
        hdf5_path = str(hdf5_summary.get("output_path") or output_root / "hdf5" / "exported_successful_real_episodes.hdf5")
        if not hdf5_summary.get("hdf5_available"):
            return {
                **base,
                "status": "blocked",
                "blocker": "RL_TEACHER_HDF5_EXPORT_MISSING",
                "message": "RL teacher/evaluator smoke requires exported demonstrations for initialization and comparison.",
                "hdf5_path": hdf5_path,
                "checks": [
                    {"id": "rl_teacher_enabled", "status": "passed"},
                    {"id": "hdf5_available", "status": "blocked", "blocker": "RL_TEACHER_HDF5_EXPORT_MISSING"},
                    {"id": "env_wrapper_ready", "status": env_wrapper.get("status", "blocked")},
                    {"id": "simulation_only_guard", "status": "passed"},
                ],
            }
        if env_wrapper.get("status") != "ready":
            return {
                **base,
                "status": "blocked",
                "blocker": "RL_TEACHER_ENV_NOT_READY",
                "message": "RL teacher/evaluator smoke requires the OMX Isaac Lab environment wrapper contract.",
                "hdf5_path": hdf5_path,
                "checks": [
                    {"id": "rl_teacher_enabled", "status": "passed"},
                    {"id": "hdf5_available", "status": "passed"},
                    {"id": "env_wrapper_ready", "status": "blocked", "blocker": "RL_TEACHER_ENV_NOT_READY"},
                    {"id": "simulation_only_guard", "status": "passed"},
                ],
            }
        if request.rl_teacher_steps <= 0:
            return {
                **base,
                "status": "blocked",
                "blocker": "RL_TEACHER_STEPS_MISSING",
                "message": "RL teacher branch is enabled, but rl_teacher_steps is zero.",
                "hdf5_path": hdf5_path,
                "checks": [
                    {"id": "rl_teacher_enabled", "status": "passed"},
                    {"id": "hdf5_available", "status": "passed"},
                    {"id": "env_wrapper_ready", "status": "passed"},
                    {"id": "rl_teacher_steps", "status": "blocked", "blocker": "RL_TEACHER_STEPS_MISSING"},
                    {"id": "simulation_only_guard", "status": "passed"},
                ],
            }
        return {
            **base,
            "status": "ready",
            "blocker": "",
            "message": "RL teacher/evaluator smoke is ready to launch as a simulation-only branch.",
            "hdf5_path": hdf5_path,
            "checks": [
                {"id": "rl_teacher_enabled", "status": "passed"},
                {"id": "hdf5_available", "status": "passed"},
                {"id": "env_wrapper_ready", "status": "passed"},
                {"id": "rl_teacher_steps", "status": "passed"},
                {"id": "simulation_only_guard", "status": "passed"},
            ],
        }

    def _dataset_path(self, request: IsaacLabSyntheticRequest) -> Path:
        return Path(request.dataset_path).expanduser().resolve()

    def _output_root(self, request: IsaacLabSyntheticRequest, dataset_path: Path) -> Path:
        if request.output_root:
            return Path(request.output_root).expanduser().resolve()
        return dataset_path / "sidecar" / "isaac_lab_synthetic" / "latest"

    def _path_allowed(self, path: Path) -> bool:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return False
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _run_preflight_checks(self, request: IsaacLabSyntheticRequest, dataset_path: Path, output_root: Path) -> list[ValidationCheck]:
        requested_groups = self._validation_check_groups(request)
        checks = [
            self._check_dataset(dataset_path),
            self._check_allowed_path("validate_dataset_allowed_root", "request", dataset_path),
            self._check_allowed_path("validate_output_allowed_root", "request", output_root),
        ]
        optional_checks = [
            self._check_runtime(request),
            self._check_stage(request),
            self._check_stage_units(request),
            self._check_digital_twin_prims(request),
            self._check_render_camera_plan(request),
            self._check_depth(request, dataset_path),
            self._check_physics(request),
            self._check_articulation(request),
            self._check_replicator_runtime(request),
        ]
        checks.extend(check for check in optional_checks if check.group in requested_groups)
        return checks

    @staticmethod
    def _validation_check_groups(request: IsaacLabSyntheticRequest) -> set[str]:
        raw_groups = request.validation_checks or ["all"]
        groups = {
            str(item or "").strip().lower()
            for item in raw_groups
            if str(item or "").strip()
        }
        if not groups or "all" in groups:
            return {
                "runtime",
                "digital_twin",
                "depth",
                "physics",
                "articulation",
                "replicator",
                "hdf5",
                "mimic",
                "training",
                "legacy",
            }
        aliases = {
            "isaac_lab": "runtime",
            "isaac_sim": "runtime",
            "sim": "runtime",
            "twin": "digital_twin",
            "canonical": "canonical_index",
            "canonical_index": "canonical_index",
            "rl": "rl_teacher",
        }
        return {aliases.get(group, group) for group in groups}

    def _check_dataset(self, dataset_path: Path) -> ValidationCheck:
        if not dataset_path.is_dir():
            return ValidationCheck(
                id="validate_request_schema",
                group="request",
                status="blocked",
                severity="blocker",
                message="Dataset path does not exist.",
                evidence={"dataset_path": str(dataset_path)},
                blocker_code="REQ_INVALID_DATASET",
            )
        return ValidationCheck(
            id="validate_request_schema",
            group="request",
            status="passed",
            severity="info",
            message="Dataset path exists.",
            evidence={"dataset_path": str(dataset_path)},
        )

    def _check_allowed_path(self, check_id: str, group: str, path: Path) -> ValidationCheck:
        if not self._path_allowed(path):
            return ValidationCheck(
                id=check_id,
                group=group,
                status="blocked",
                severity="blocker",
                message="Path is outside allowed roots.",
                evidence={"path": str(path), "allowed_roots": [str(root) for root in self.allowed_roots]},
                blocker_code="PATH_OUTSIDE_ALLOWED_ROOTS",
            )
        return ValidationCheck(
            id=check_id,
            group=group,
            status="passed",
            severity="info",
            message="Path is inside allowed roots.",
            evidence={"path": str(path)},
        )

    def _check_runtime(self, request: IsaacLabSyntheticRequest) -> ValidationCheck:
        lab_path = self._isaac_lab_path(request)
        if not lab_path.is_dir():
            return ValidationCheck(
                id="validate_isaac_lab_import",
                group="runtime",
                status="blocked",
                severity="blocker",
                message="Isaac Lab path is missing.",
                evidence={"isaac_lab_path": str(lab_path)},
                blocker_code="COMPAT_LAB_MISSING",
                docs=["https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/index.html"],
            )
        return ValidationCheck(
            id="validate_isaac_lab_import",
            group="runtime",
            status="passed",
            severity="info",
            message="Isaac Lab path exists.",
            evidence={"isaac_lab_path": str(lab_path), "git": self._git_identity(lab_path)},
            docs=["https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/index.html"],
        )

    def _check_stage(self, request: IsaacLabSyntheticRequest) -> ValidationCheck:
        stage_path = self._stage_path(request)
        if not stage_path.is_file():
            status = "blocked" if request.require_digital_twin_pass else "warning"
            return ValidationCheck(
                id="validate_stage_loads",
                group="digital_twin",
                status=status,
                severity="blocker" if status == "blocked" else "warning",
                message="Configured Isaac stage is missing.",
                evidence={"stage_path": str(stage_path)},
                blocker_code="DIGITAL_TWIN_STAGE_MISSING" if status == "blocked" else None,
                docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/digital_twin/index.html"],
            )
        return ValidationCheck(
            id="validate_stage_loads",
            group="digital_twin",
            status="passed",
            severity="info",
            message="Isaac stage file exists.",
            evidence={"stage_path": str(stage_path)},
            docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/digital_twin/index.html"],
        )

    def _check_stage_units(self, request: IsaacLabSyntheticRequest) -> ValidationCheck:
        contract = self._stage_contract(request)
        if not contract["stage_exists"]:
            return ValidationCheck(
                id="validate_stage_units",
                group="digital_twin",
                status="skipped",
                severity="info",
                message="Stage units cannot be inspected because the stage file is missing.",
                evidence={"stage_path": contract["stage_path"]},
            )
        if contract["stage_units_meters_per_unit"] is None:
            return ValidationCheck(
                id="validate_stage_units",
                group="digital_twin",
                status="warning",
                severity="warning",
                message="Stage metersPerUnit is not declared; synthetic runs will record this as an unresolved digital-twin assumption.",
                evidence={"stage_path": contract["stage_path"], "stage_units_meters_per_unit": None},
                docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/physics/simulation_fundamentals.html"],
            )
        return ValidationCheck(
            id="validate_stage_units",
            group="digital_twin",
            status="passed",
            severity="info",
            message="Stage declares metersPerUnit.",
            evidence={
                "stage_path": contract["stage_path"],
                "stage_units_meters_per_unit": contract["stage_units_meters_per_unit"],
                "up_axis": contract["up_axis"],
            },
            docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/physics/simulation_fundamentals.html"],
        )

    def _check_digital_twin_prims(self, request: IsaacLabSyntheticRequest) -> ValidationCheck:
        contract = self._stage_contract(request)
        if not contract["stage_exists"]:
            return ValidationCheck(
                id="validate_digital_twin_prims",
                group="digital_twin",
                status="skipped",
                severity="info",
                message="Digital-twin prims cannot be inspected because the stage file is missing.",
                evidence={"stage_path": contract["stage_path"]},
            )
        missing = [
            name
            for name, prim in (
                ("robot_root_prim", contract["robot_root_prim"]),
                ("workspace_root_prim", contract["workspace_root_prim"]),
                ("cube_prim", contract["cube_prim"]),
            )
            if not prim.get("found")
        ]
        if missing:
            return ValidationCheck(
                id="validate_digital_twin_prims",
                group="digital_twin",
                status="warning",
                severity="warning",
                message="Some expected digital-twin prims were not detected in the static stage text.",
                evidence={"stage_path": contract["stage_path"], "missing": missing},
                docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/digital_twin/index.html"],
            )
        return ValidationCheck(
            id="validate_digital_twin_prims",
            group="digital_twin",
            status="passed",
            severity="info",
            message="Required robot, workspace, and cube prims were detected.",
            evidence={
                "stage_path": contract["stage_path"],
                "robot_root_prim": contract["robot_root_prim"],
                "workspace_root_prim": contract["workspace_root_prim"],
                "cube_prim": contract["cube_prim"],
            },
            docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/digital_twin/index.html"],
        )

    def _check_render_camera_plan(self, request: IsaacLabSyntheticRequest) -> ValidationCheck:
        contract = self._stage_contract(request)
        if not contract["stage_exists"]:
            return ValidationCheck(
                id="validate_render_camera_plan",
                group="digital_twin",
                status="skipped",
                severity="info",
                message="Render camera plan cannot be inspected because the stage file is missing.",
                evidence={"stage_path": contract["stage_path"]},
            )
        missing = [
            str(row.get("camera") or "")
            for row in contract["camera_prims"]
            if not row.get("found") and not row.get("planned_pose")
        ]
        camera_sources = {
            str(row.get("camera") or ""): str(row.get("source") or "stage")
            for row in contract["camera_prims"]
        }
        if missing:
            return ValidationCheck(
                id="validate_render_camera_plan",
                group="digital_twin",
                status="warning",
                severity="warning",
                message="Some requested render cameras have neither a stage prim nor a Replicator fallback pose.",
                evidence={"stage_path": contract["stage_path"], "missing": missing, "camera_sources": camera_sources},
                docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/replicator_tutorials/index.html"],
            )
        return ValidationCheck(
            id="validate_render_camera_plan",
            group="digital_twin",
            status="passed",
            severity="info",
            message="Requested render cameras have explicit stage prims or Replicator fallback poses.",
            evidence={
                "stage_path": contract["stage_path"],
                "camera_sources": camera_sources,
                "camera_prims": contract["camera_prims"],
            },
            docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/replicator_tutorials/index.html"],
        )

    def _check_depth(self, request: IsaacLabSyntheticRequest, dataset_path: Path) -> ValidationCheck:
        manifest = self._depth_manifest_path(dataset_path)
        if not manifest.is_file():
            status = "blocked" if request.require_depth_pass else "warning"
            return ValidationCheck(
                id="validate_depth_scale",
                group="depth",
                status=status,
                severity="blocker" if status == "blocked" else "warning",
                message="Raw depth transform manifest is missing.",
                evidence={"expected_manifest": str(manifest)},
                blocker_code="DEPTH_SCALE_UNKNOWN" if status == "blocked" else None,
                docs=["https://docs.isaacsim.omniverse.nvidia.com/5.1.0/assets/usd_assets_camera_depth_sensors.html"],
            )
        data = _read_json(manifest)
        scale = _safe_float(data.get("depth_scale_m_per_unit"), 0.0, minimum=0.0)
        if scale <= 0:
            return ValidationCheck(
                id="validate_depth_scale",
                group="depth",
                status="blocked" if request.require_depth_pass else "warning",
                severity="blocker" if request.require_depth_pass else "warning",
                message="Depth scale is missing or invalid.",
                evidence={"manifest": str(manifest), "depth_scale_m_per_unit": data.get("depth_scale_m_per_unit")},
                blocker_code="DEPTH_SCALE_UNKNOWN" if request.require_depth_pass else None,
                docs=["https://docs.isaacsim.omniverse.nvidia.com/5.1.0/assets/usd_assets_camera_depth_sensors.html"],
            )
        return ValidationCheck(
            id="validate_depth_scale",
            group="depth",
            status="passed",
            severity="info",
            message="Depth transform manifest has a positive scale.",
            evidence={"manifest": str(manifest), "depth_scale_m_per_unit": scale},
        )

    def _check_physics(self, request: IsaacLabSyntheticRequest) -> ValidationCheck:
        if not request.require_physics_pass:
            return ValidationCheck(
                id="validate_physics_preflight",
                group="physics",
                status="skipped",
                severity="info",
                message="Physics preflight is disabled for this request.",
                evidence={"require_physics_pass": False},
            )
        evidence = self._physics_preflight_evidence(request)
        blockers = list(evidence.get("blocking_failures") or [])
        if blockers:
            return ValidationCheck(
                id="validate_physics_preflight",
                group="physics",
                status="blocked",
                severity="blocker",
                message="Physics preflight blocked unsafe cube/gripper contact settings.",
                evidence=evidence,
                blocker_code=str(blockers[0]),
                docs=[
                    "https://docs.isaacsim.omniverse.nvidia.com/6.0.1/physics/simulation_fundamentals.html",
                    "https://docs.isaacsim.omniverse.nvidia.com/6.0.1/physics/physics_materials.html",
                ],
            )
        return ValidationCheck(
            id="validate_physics_preflight",
            group="physics",
            status="passed",
            severity="info",
            message="Static physics preflight passed for cube, gripper, material, contact, and filter settings.",
            evidence=evidence,
            docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.1/physics/simulation_fundamentals.html"],
        )

    @staticmethod
    def _physics_marker_values(stage_text: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for raw_line in stage_text.splitlines():
            match = re.search(r"#\s*atr:physics\s+(.*)$", raw_line)
            if not match:
                continue
            for token in match.group(1).split():
                if "=" not in token:
                    continue
                key, value = token.split("=", 1)
                key = key.strip().lower()
                value = value.strip().strip("\"'")
                if key:
                    values[key] = value
        return values

    @staticmethod
    def _physics_marker_text(markers: dict[str, str], *keys: str, default: str = "") -> str:
        for key in keys:
            value = markers.get(key.lower())
            if value is not None:
                return str(value).strip()
        return default

    @staticmethod
    def _physics_marker_float(markers: dict[str, str], key: str, default: float) -> float:
        return _safe_float(markers.get(key.lower()), default)

    def _physics_preflight_evidence(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        stage_path = self._stage_path(request)
        try:
            stage_text = stage_path.read_text(encoding="utf-8") if stage_path.is_file() else ""
        except OSError:
            stage_text = ""
        markers = self._physics_marker_values(stage_text)
        failures: list[str] = []

        cube_mode = self._physics_marker_text(markers, "cube_rigid_body", "cube_rigid_body_mode").lower()
        cube_dynamic = cube_mode in {"dynamic", "dynamic_rigid_body", "rigid_dynamic", "true", "1"}
        cube_mass_kg = self._physics_marker_float(markers, "cube_mass_kg", 0.0)
        cube_has_mass = cube_mass_kg > 0.0
        cube_collider_type = self._physics_marker_text(markers, "cube_collider_type", "cube_collider").lower()
        cube_collider_valid = cube_collider_type in {
            "box",
            "cube",
            "convex",
            "convex_hull",
            "convex_decomposition",
            "mesh_convex_decomposition",
        }
        if not stage_path.is_file() or not cube_dynamic or not cube_collider_valid or not cube_has_mass:
            failures.append("CUBE_RIGID_BODY_MISSING")

        cube_size_m = self._physics_marker_float(markers, "cube_size_m", 0.05)
        contact_offset_m = self._physics_marker_float(markers, "contact_offset_m", -1.0)
        rest_offset_m = self._physics_marker_float(markers, "rest_offset_m", 0.0)
        max_contact_offset_m = min(0.01, max(0.001, cube_size_m * 0.2))
        max_rest_offset_abs_m = max(0.001, cube_size_m * 0.03)
        contact_offset_valid = 0.0 < contact_offset_m <= max_contact_offset_m
        rest_offset_valid = abs(rest_offset_m) <= max_rest_offset_abs_m

        gripper_collider_type = self._physics_marker_text(markers, "gripper_collider_type", "gripper_collider").lower()
        gripper_collider_valid = gripper_collider_type in {
            "box",
            "capsule",
            "convex",
            "convex_hull",
            "convex_decomposition",
            "mesh_convex_decomposition",
        }
        gripper_skin_fraction = self._physics_marker_float(markers, "gripper_collider_skin_fraction", 1.0)
        gripper_inner_pad_only = _safe_bool(markers.get("gripper_inner_pad_only"), False)
        gripper_skin_valid = 0.0 <= gripper_skin_fraction <= 0.15
        if not gripper_collider_valid or not gripper_skin_valid or not gripper_inner_pad_only:
            failures.append("COLLIDER_PRECHECK_FAILED")
        elif not contact_offset_valid or not rest_offset_valid:
            failures.append("COLLIDER_PRECHECK_FAILED")

        cube_static_friction = self._physics_marker_float(markers, "cube_static_friction", -1.0)
        cube_dynamic_friction = self._physics_marker_float(markers, "cube_dynamic_friction", -1.0)
        a4_static_friction = self._physics_marker_float(markers, "a4_static_friction", -1.0)
        gripper_inner_static_friction = self._physics_marker_float(markers, "gripper_inner_static_friction", -1.0)
        gripper_inner_dynamic_friction = self._physics_marker_float(markers, "gripper_inner_dynamic_friction", -1.0)
        materials_valid = (
            cube_static_friction > 0.0
            and cube_dynamic_friction > 0.0
            and a4_static_friction > 0.0
            and gripper_inner_static_friction > 0.0
            and gripper_inner_dynamic_friction > 0.0
        )
        if not materials_valid:
            failures.append("PHYSICS_MATERIAL_MISSING")

        filtered_pairs_raw = self._physics_marker_text(markers, "filtered_collision_pairs").lower()
        finger_object_contact_filtered = _safe_bool(markers.get("finger_object_contact_filtered"), False) or "finger_object" in filtered_pairs_raw
        if finger_object_contact_filtered:
            failures.append("FILTERED_PAIR_UNSAFE")

        contact_report_enabled = _safe_bool(markers.get("contact_report_enabled"), False)
        contact_report_fingers = {
            item.strip().lower()
            for item in self._physics_marker_text(markers, "contact_report_fingers").split(",")
            if item.strip()
        }
        contact_threshold_n = self._physics_marker_float(markers, "contact_threshold_n", -1.0)
        both_fingers_to_cube = {"left", "right"}.issubset(contact_report_fingers)
        if not contact_report_enabled or not both_fingers_to_cube or contact_threshold_n <= 0.0:
            failures.append("CONTACT_REPORT_MISSING")

        sdf_custom_geometry_used = _safe_bool(markers.get("sdf_custom_geometry_used"), False)
        if sdf_custom_geometry_used:
            failures.append("SDF_UNSUPPORTED_FOR_BACKEND")

        return {
            "schema": "atr.lerobot.physics_preflight.evidence.v1",
            "stage_path": str(stage_path),
            "stage_exists": stage_path.is_file(),
            "marker_count": len(markers),
            "cube_rigid_body": {
                "mode": cube_mode,
                "dynamic": cube_dynamic,
                "mass_kg": cube_mass_kg,
                "has_mass": cube_has_mass,
            },
            "cube_collider": {
                "type": cube_collider_type,
                "valid": cube_collider_valid,
            },
            "gripper_collider": {
                "type": gripper_collider_type,
                "valid": gripper_collider_valid,
                "skin_fraction": gripper_skin_fraction,
                "inner_pad_only": gripper_inner_pad_only,
            },
            "collision_skin": {
                "cube_size_m": cube_size_m,
                "contact_offset_m": contact_offset_m,
                "rest_offset_m": rest_offset_m,
                "max_contact_offset_m": max_contact_offset_m,
                "max_rest_offset_abs_m": max_rest_offset_abs_m,
                "contact_offset_valid": contact_offset_valid,
                "rest_offset_valid": rest_offset_valid,
            },
            "materials": {
                "cube": {
                    "static_friction": cube_static_friction,
                    "dynamic_friction": cube_dynamic_friction,
                },
                "a4_workspace": {
                    "static_friction": a4_static_friction,
                },
                "gripper_inner_pad": {
                    "static_friction": gripper_inner_static_friction,
                    "dynamic_friction": gripper_inner_dynamic_friction,
                },
                "valid": materials_valid,
            },
            "filtered_pairs": {
                "raw": filtered_pairs_raw,
                "finger_object_contact_filtered": finger_object_contact_filtered,
                "safe": not finger_object_contact_filtered,
            },
            "contact_reporting": {
                "enabled": contact_report_enabled,
                "contact_threshold_n": contact_threshold_n,
                "fingers": sorted(contact_report_fingers),
                "both_fingers_to_cube": both_fingers_to_cube,
            },
            "physx_limitations": {
                "sdf_custom_geometry_used": sdf_custom_geometry_used,
                "sdf_supported_for_configured_backend": False,
            },
            "blocking_failures": list(dict.fromkeys(failures)),
        }

    def _check_articulation(self, request: IsaacLabSyntheticRequest) -> ValidationCheck:
        if not request.require_articulation_pass:
            return ValidationCheck(
                id="validate_articulation_preflight",
                group="articulation",
                status="skipped",
                severity="info",
                message="Articulation preflight is disabled for this request.",
                evidence={"require_articulation_pass": False},
            )
        evidence = self._articulation_preflight_evidence(request)
        blockers = list(evidence.get("blocking_failures") or [])
        if blockers:
            return ValidationCheck(
                id="validate_articulation_preflight",
                group="articulation",
                status="blocked",
                severity="blocker",
                message="Articulation preflight blocked unsafe joint drive or source settings.",
                evidence=evidence,
                blocker_code=str(blockers[0]),
                docs=[
                    "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/robot_simulation/articulation_controller.html",
                    "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/openusd_tuning_tutorials/tutorial_05_joint_drive_tuning.html",
                ],
            )
        return ValidationCheck(
            id="validate_articulation_preflight",
            group="articulation",
            status="passed",
            severity="info",
            message="Static articulation preflight passed for joint mapping, drive targets, gains, mimic, and source policy.",
            evidence=evidence,
            docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/robot_simulation/articulation_controller.html"],
        )

    @staticmethod
    def _articulation_marker_values(stage_text: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for raw_line in stage_text.splitlines():
            match = re.search(r"#\s*atr:articulation\s+(.*)$", raw_line)
            if not match:
                continue
            for token in match.group(1).split():
                if "=" not in token:
                    continue
                key, value = token.split("=", 1)
                key = key.strip().lower()
                value = value.strip().strip("\"'")
                if key:
                    values[key] = value
        return values

    @staticmethod
    def _articulation_marker_text(markers: dict[str, str], *keys: str, default: str = "") -> str:
        for key in keys:
            value = markers.get(key.lower())
            if value is not None:
                return str(value).strip()
        return default

    @staticmethod
    def _articulation_marker_float(markers: dict[str, str], key: str, default: float) -> float:
        return _safe_float(markers.get(key.lower()), default)

    @staticmethod
    def _articulation_marker_int(markers: dict[str, str], key: str, default: int) -> int:
        return _safe_int(markers.get(key.lower()), default)

    @staticmethod
    def _split_marker_csv(value: str) -> list[str]:
        return [item.strip() for item in str(value or "").split(",") if item.strip()]

    def _articulation_preflight_evidence(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        stage_path = self._stage_path(request)
        try:
            stage_text = stage_path.read_text(encoding="utf-8") if stage_path.is_file() else ""
        except OSError:
            stage_text = ""
        markers = self._articulation_marker_values(stage_text)
        failures: list[str] = []

        articulation_root = self._articulation_marker_text(markers, "articulation_root")
        joint_names = self._split_marker_csv(self._articulation_marker_text(markers, "joint_names"))
        action_keys = self._split_marker_csv(self._articulation_marker_text(markers, "lerobot_action_keys", "action_keys"))
        joint_mapping_mode = self._articulation_marker_text(markers, "joint_mapping").lower()
        duplicate_joints = sorted({name for name in joint_names if joint_names.count(name) > 1})
        duplicate_actions = sorted({name for name in action_keys if action_keys.count(name) > 1})
        missing_action_keys = sorted(set(action_keys) - set(joint_names))
        extra_joint_names = sorted(set(joint_names) - set(action_keys))
        one_to_one = (
            bool(stage_path.is_file())
            and bool(articulation_root)
            and bool(joint_names)
            and bool(action_keys)
            and len(joint_names) == len(action_keys)
            and not duplicate_joints
            and not duplicate_actions
            and not missing_action_keys
            and joint_mapping_mode in {"one_to_one", "exact", "exact_once"}
        )
        if not one_to_one:
            failures.append("JOINT_MAP_MISSING")

        zero_policy = self._articulation_marker_text(markers, "joint_zero_pose_policy").lower()
        zero_reference_only = zero_policy in {"reference_only", "reference", "calibration_reference", "zero_reference"}
        if not zero_reference_only:
            failures.append("JOINT_ZERO_USED_AS_COMMAND")

        drive_targets_initialized = _safe_bool(markers.get("drive_targets_initialized_from_current_pose"), False)
        if not drive_targets_initialized:
            failures.append("DRIVE_TARGET_JUMP_RISK")

        command_modes = {
            item.lower()
            for item in self._split_marker_csv(self._articulation_marker_text(markers, "command_modes"))
        }
        drive_modes = {
            item.lower()
            for item in self._split_marker_csv(self._articulation_marker_text(markers, "drive_mode_per_joint"))
        }
        primary_modes = {mode for mode in command_modes if mode in {"position", "velocity", "effort", "teleport", "direct"}}
        command_mode_conflict = len(primary_modes - {"teleport", "direct"}) > 1 or bool(primary_modes & {"teleport", "direct"})
        drive_mode_conflict = len({mode for mode in drive_modes if mode in {"position", "velocity", "effort"}}) > 1
        command_modes_exclusive = bool(primary_modes) and not command_mode_conflict and not drive_mode_conflict
        if not command_modes_exclusive:
            failures.append("COMMAND_MODE_CONFLICT")

        stiffness_max = self._articulation_marker_float(markers, "stiffness_max", -1.0)
        damping_min = self._articulation_marker_float(markers, "damping_min", -1.0)
        max_force_max = self._articulation_marker_float(markers, "max_force_max", -1.0)
        max_velocity_max = self._articulation_marker_float(markers, "max_velocity_max", -1.0)
        solver_position_iterations = self._articulation_marker_int(markers, "solver_position_iterations", 0)
        solver_velocity_iterations = self._articulation_marker_int(markers, "solver_velocity_iterations", 0)
        drive_gains_within_bounds = (
            0.0 <= stiffness_max <= 5000.0
            and 0.0 < damping_min <= 1000.0
            and 0.0 < max_force_max <= 100.0
            and 0.0 < max_velocity_max <= 20.0
            and solver_position_iterations >= 4
            and solver_velocity_iterations >= 1
        )
        if not drive_gains_within_bounds:
            failures.append("DRIVE_GAIN_UNSTABLE")

        mimic_joints = self._split_marker_csv(self._articulation_marker_text(markers, "mimic_joints"))
        mimic_gear_ratio = self._articulation_marker_float(markers, "mimic_gear_ratio", 0.0)
        mimic_direction = self._articulation_marker_text(markers, "mimic_direction").lower()
        mimic_valid = (
            len(mimic_joints) >= 2
            and mimic_gear_ratio > 0.0
            and mimic_direction in {"opposed", "opposed_close", "mirrored_opposed", "mirror_opposed"}
        )
        if not mimic_valid:
            failures.append("MIMIC_MAPPING_INVALID")

        source = self._articulation_marker_text(markers, "lerobot_joint_source", "joint_source").lower()
        explicit_source_policy = self._articulation_marker_text(markers, "explicit_source_policy").lower()
        leader_source = self._articulation_marker_text(markers, "leader_joint_source").lower()
        follower_source = self._articulation_marker_text(markers, "follower_joint_source").lower()
        known_sources = {"leader", "follower", "fused"}
        source_safe = source in known_sources and bool(explicit_source_policy)
        if source == "mixed" or not source_safe:
            failures.append("JOINT_SOURCE_UNKNOWN")

        return {
            "schema": "atr.lerobot.articulation_preflight.evidence.v1",
            "stage_path": str(stage_path),
            "stage_exists": stage_path.is_file(),
            "marker_count": len(markers),
            "articulation_root": {
                "path": articulation_root,
                "present": bool(articulation_root),
            },
            "joint_mapping": {
                "one_to_one": one_to_one,
                "joint_count": len(joint_names),
                "action_key_count": len(action_keys),
                "joint_names": joint_names,
                "lerobot_action_keys": action_keys,
                "mapping_mode": joint_mapping_mode,
                "missing_action_keys": missing_action_keys,
                "extra_joint_names": extra_joint_names,
                "duplicate_joints": duplicate_joints,
                "duplicate_actions": duplicate_actions,
            },
            "joint_zero_policy": {
                "policy": zero_policy,
                "reference_only": zero_reference_only,
            },
            "initial_drive_targets": {
                "initialized_from_current_pose": drive_targets_initialized,
            },
            "command_modes": {
                "requested": sorted(command_modes),
                "drive_modes": sorted(drive_modes),
                "exclusive": command_modes_exclusive,
                "command_mode_conflict": command_mode_conflict,
                "drive_mode_conflict": drive_mode_conflict,
            },
            "drive_gains": {
                "stiffness_max": stiffness_max,
                "damping_min": damping_min,
                "max_force_max": max_force_max,
                "max_velocity_max": max_velocity_max,
                "within_bounds": drive_gains_within_bounds,
            },
            "solver": {
                "position_iterations": solver_position_iterations,
                "velocity_iterations": solver_velocity_iterations,
            },
            "mimic_mapping": {
                "joints": mimic_joints,
                "gear_ratio": mimic_gear_ratio,
                "direction": mimic_direction,
                "valid": mimic_valid,
            },
            "joint_source": {
                "source": source,
                "explicit_policy": explicit_source_policy,
                "leader_joint_source": leader_source,
                "follower_joint_source": follower_source,
                "safe": source_safe and source != "mixed",
            },
            "blocking_failures": list(dict.fromkeys(failures)),
        }

    def _isaac_sim_python_path(self, request: IsaacLabSyntheticRequest) -> Path:
        raw_path = str(request.isaac_sim_python or os.environ.get("ISAAC_SIM_PYTHON", "")).strip()
        if raw_path:
            return Path(raw_path).expanduser()
        default_path = DEFAULT_ISAAC_SIM_PYTHON.expanduser()
        if default_path.is_file():
            return default_path
        return Path()

    def _isaac_sim_python_value(self, request: IsaacLabSyntheticRequest) -> str:
        python_path = self._isaac_sim_python_path(request)
        if not python_path or str(python_path) == ".":
            return ""
        try:
            return str(python_path.resolve())
        except OSError:
            return str(python_path)

    def _isaac_sim_version_info(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        explicit = str(request.isaac_sim_version or "").strip()
        if explicit:
            return {
                "version": explicit,
                "source": "request.isaac_sim_version",
                "checked": True,
            }
        python_path = self._isaac_sim_python_path(request)
        candidates: list[Path] = []
        if python_path and str(python_path) != ".":
            expanded = python_path.expanduser()
            candidates.extend([expanded.parent / "VERSION", expanded.parent.parent / "VERSION"])
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            if not candidate.is_file():
                continue
            try:
                version = candidate.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if version:
                return {
                    "version": version,
                    "source": str(resolved),
                    "checked": True,
                }
        return {
            "version": "",
            "source": "",
            "checked": False,
        }

    def _check_replicator_runtime(self, request: IsaacLabSyntheticRequest) -> ValidationCheck:
        if not request.enable_replicator:
            return ValidationCheck(
                id="validate_replicator_runtime",
                group="replicator",
                status="skipped",
                severity="info",
                message="Replicator branch is disabled for this request.",
                evidence={"enable_replicator": False},
            )
        python_path = self._isaac_sim_python_path(request)
        if not python_path.is_file():
            return ValidationCheck(
                id="validate_replicator_runtime",
                group="replicator",
                status="blocked",
                severity="blocker",
                message="Replicator is enabled, but Isaac Sim Python is not configured.",
                evidence={"isaac_sim_python": str(python_path) if str(python_path) != "." else ""},
                blocker_code="REPLICATOR_RUNTIME_MISSING",
                docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/replicator_tutorials/index.html"],
            )
        return ValidationCheck(
            id="validate_replicator_runtime",
            group="replicator",
            status="passed",
            severity="info",
            message="Isaac Sim Python path is configured; Replicator import probe is deferred to the Isaac Sim worker.",
            evidence={
                "isaac_sim_python": str(python_path.resolve()),
                "import_checked": False,
                "required_modules": list(REPLICATOR_REQUIRED_MODULES),
            },
            docs=["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/replicator_tutorials/index.html"],
        )

    def _validation_report(
        self,
        *,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        stage: str,
        checks: list[ValidationCheck],
    ) -> dict[str, Any]:
        check_rows = [check.as_dict() for check in checks]
        blockers = [
            {
                "code": str(row.get("blocker_code") or "UNKNOWN_BLOCKER"),
                "check": str(row.get("id") or ""),
                "message": str(row.get("message") or ""),
            }
            for row in check_rows
            if row.get("status") == "blocked"
        ]
        warnings = [row for row in check_rows if row.get("status") == "warning"]
        return {
            "schema": VALIDATION_SCHEMA,
            "ok": not blockers,
            "status": "blocked" if blockers else "passed",
            "stage": stage,
            "dataset": str(dataset_path),
            "output_root": str(output_root),
            "generated_at": _now(),
            "pipeline_mode": request.pipeline_mode.value,
            "fallback_policy": request.fallback_policy.value,
            "source_intent": request.source_intent.value,
            "checks": check_rows,
            "blockers": blockers,
            "warnings": warnings,
            "artifacts": {
                "compatibility": str(output_root / "compatibility.json"),
                "digital_twin_preflight": str(output_root / "digital_twin_preflight.json"),
            },
        }

    def _compatibility_summary(self, request: IsaacLabSyntheticRequest, *, output_root: Path | None = None) -> dict[str, Any]:
        lab_path = self._isaac_lab_path(request)
        git = self._git_identity(lab_path) if lab_path.is_dir() else {}
        git_tag = str(git.get("tag", ""))
        docs_version = request.isaac_sim_docs_version or "6.0.0"
        lab_is_beta = "beta" in git_tag.lower()
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if not lab_path.is_dir():
            blockers.append(
                {
                    "code": "COMPAT_LAB_MISSING",
                    "message": "Isaac Lab path is missing.",
                    "path": str(lab_path),
                }
            )
        if lab_is_beta and not str(docs_version).startswith("6."):
            blockers.append(
                {
                    "code": "COMPAT_LAB_SIM_VERSION_MISMATCH",
                    "message": "Isaac Lab beta stack requires an Isaac Sim 6.x docs/runtime marker.",
                    "isaac_lab_git_tag": git_tag,
                    "isaac_sim_docs_version": docs_version,
                }
            )
        python_value = self._isaac_sim_python_value(request)
        python_path = Path(python_value) if python_value else Path()
        sim_version_info = self._isaac_sim_version_info(request)
        sim_version = str(sim_version_info.get("version") or "")
        runtime_detector = self._isaac_sim_runtime_detector(
            request,
            python_path=python_path,
            sim_version_info=sim_version_info,
            docs_version=docs_version,
        )
        mimic_scripts = self._script_presence(lab_path, MIMIC_SCRIPT_RELATIVE_PATHS)
        mimic_scripts_present = all(item["exists"] for item in mimic_scripts.values()) if lab_path.is_dir() else False
        robomimic_train = self._script_presence(lab_path, {"train": ROBOMIMIC_TRAIN_RELATIVE_PATH})
        rl_wrappers = self._script_presence(lab_path, RL_WRAPPER_RELATIVE_PATHS)
        smoke_checks = self._isaac_lab_smoke_checks(
            lab_path=lab_path,
            python_path=python_path,
            mimic_scripts=mimic_scripts,
            robomimic_train=robomimic_train,
            rl_wrappers=rl_wrappers,
        )
        upgrade_plan = self._isaac_lab_upgrade_plan(
            request,
            lab_path=lab_path,
            git_tag=git_tag,
            sim_version=sim_version,
            docs_version=docs_version,
            output_root=output_root,
        )
        if output_root is not None and self._path_allowed(output_root):
            _atomic_write_json(Path(upgrade_plan["manifest_path"]), upgrade_plan)
        if lab_path.is_dir() and request.enable_mimic and not mimic_scripts_present:
            warnings.append(
                {
                    "code": "MIMIC_SCRIPTS_MISSING",
                    "message": "Isaac Lab Mimic scripts are not all present; Mimic generation will remain blocked until installed.",
                    "missing": [name for name, item in mimic_scripts.items() if not item["exists"]],
                }
            )
        status = "blocked" if blockers else "warning" if warnings else "ok"
        replicator_status = "unknown_requires_isaac_python" if python_path.is_file() else "blocked"
        return {
            "schema": "atr.lerobot.isaac_lab.compatibility.v1",
            "status": status,
            "isaac_lab_path": str(lab_path),
            "isaac_lab_exists": lab_path.is_dir(),
            "isaac_lab_git_commit": git.get("commit", ""),
            "isaac_lab_git_tag": git_tag,
            "isaac_sim_python": python_value,
            "isaac_sim_version": sim_version,
            "isaac_sim_docs_version": docs_version,
            "compatibility_stack": "beta_isaac_sim_6" if lab_is_beta else "manual_override_recorded" if lab_path.is_dir() else "",
            "compatibility_status": "blocked" if blockers else "passed",
            "runtime_detector": runtime_detector,
            "smoke_checks": smoke_checks,
            "upgrade_plan": upgrade_plan,
            "lab": {
                "path": str(lab_path.resolve()) if lab_path.exists() else str(lab_path),
                "exists": lab_path.is_dir(),
                "git_commit": git.get("commit", ""),
                "git_tag": git_tag,
                "is_beta": lab_is_beta,
            },
            "sim": {
                "python_path": python_value,
                "python_exists": python_path.is_file(),
                "version": sim_version,
                "version_source": str(sim_version_info.get("source") or ""),
                "version_checked": bool(sim_version_info.get("checked")),
                "docs_version": docs_version,
                "status": "unknown" if not sim_version else "ok",
                "runtime_checked": False,
            },
            "replicator": {**runtime_detector["replicator"], "status": replicator_status},
            "physics_backend": runtime_detector["physics_backend"],
            "sensor_extensions": runtime_detector["sensor_extensions"],
            "mimic": {
                "scripts_present": mimic_scripts_present,
                "scripts": mimic_scripts,
            },
            "robomimic": {
                "train_script_present": bool(robomimic_train["train"]["exists"]),
                "train_script": robomimic_train["train"],
                "import_checked": False,
            },
            "rl": {
                "wrappers": rl_wrappers,
                "available": any(item["exists"] for item in rl_wrappers.values()),
                "runtime_policy_export_allowed": False,
                "simulation_only": True,
            },
            "blockers": blockers,
            "warnings": warnings,
        }

    def _isaac_lab_upgrade_plan(
        self,
        request: IsaacLabSyntheticRequest,
        *,
        lab_path: Path,
        git_tag: str,
        sim_version: str,
        docs_version: str,
        output_root: Path | None,
    ) -> dict[str, Any]:
        manifest_path = output_root / "upgrade" / "isaac_lab_upgrade_plan.json" if output_root is not None else Path()
        selected_stack = self._select_isaac_lab_stack(git_tag=git_tag, sim_version=sim_version, docs_version=docs_version)
        candidate_stacks = [
            {
                "stack_id": "stable_lab_2_3_sim_5_1",
                "isaac_lab_target": "v2.3.X",
                "isaac_sim_target": "5.1",
                "docs_version": "5.1.0",
                "source": "official_isaac_lab_compatibility_and_isaac_sim_docs",
                "docs": [
                    "https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/index.html",
                    "https://docs.isaacsim.omniverse.nvidia.com/5.1.0/",
                ],
            },
            {
                "stack_id": "beta_lab_3_0_sim_6_0",
                "isaac_lab_target": "v3.0.0-beta2",
                "isaac_sim_target": "6.0",
                "docs_version": "6.0.0",
                "source": "official_isaac_lab_compatibility_and_isaac_sim_docs",
                "docs": [
                    "https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/index.html",
                    "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/",
                ],
            },
        ]
        return {
            "schema": "atr.lerobot.isaac_lab.upgrade_plan.v1",
            "status": "ready" if lab_path.is_dir() else "blocked",
            "selected_stack": selected_stack,
            "default_action": "record_only_no_mutation",
            "mutation_allowed_by_default": False,
            "manifest_path": str(manifest_path) if str(manifest_path) != "." else "",
            "isaac_lab_path": str(lab_path),
            "local_git_tag": git_tag,
            "local_isaac_sim_version": sim_version,
            "selected_docs_version": docs_version,
            "candidate_stacks": candidate_stacks,
            "command_preview": self._isaac_lab_upgrade_command_preview(lab_path, selected_stack),
            "requires_operator_confirmation": True,
            "notes": [
                "The default task records the chosen compatibility stack only.",
                "Pin or update commands are previews and must not run during live teleoperation or recording.",
            ],
        }

    @staticmethod
    def _select_isaac_lab_stack(*, git_tag: str, sim_version: str, docs_version: str) -> str:
        marker = " ".join([git_tag, sim_version, docs_version]).lower()
        if "6." in marker or "beta" in marker:
            return "beta_lab_3_0_sim_6_0"
        if "5.1" in marker or "2.3" in marker:
            return "stable_lab_2_3_sim_5_1"
        return "manual_override_recorded"

    @staticmethod
    def _isaac_lab_upgrade_command_preview(lab_path: Path, selected_stack: str) -> list[str]:
        if selected_stack == "beta_lab_3_0_sim_6_0":
            target = "v3.0.0-beta2"
        elif selected_stack == "stable_lab_2_3_sim_5_1":
            target = "v2.3.X"
        else:
            target = "<operator-selected-tag-or-commit>"
        return ["git", "-C", str(lab_path), "checkout", target]

    def _isaac_lab_smoke_checks(
        self,
        *,
        lab_path: Path,
        python_path: Path,
        mimic_scripts: dict[str, dict[str, Any]],
        robomimic_train: dict[str, dict[str, Any]],
        rl_wrappers: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        python_exists = python_path.is_file() if str(python_path) and str(python_path) != "." else False
        lab_exists = lab_path.is_dir()
        import_status = "deferred_to_isaac_runtime" if python_exists and lab_exists else "blocked"
        task_registry_status = "ready_to_probe" if python_exists and lab_exists else "blocked"
        record_demos = mimic_scripts.get("record_demos", {})
        generate_dataset = mimic_scripts.get("generate_dataset", {})
        robomimic = robomimic_train.get("train", {})
        rl_name, rl_wrapper = next(((name, row) for name, row in rl_wrappers.items() if row.get("exists")), ("", {}))
        if not rl_wrapper and rl_wrappers:
            rl_name, rl_wrapper = next(iter(rl_wrappers.items()))
        checks = [
            {
                "id": "isaac_lab_import",
                "status": import_status,
                "python_path": str(python_path.resolve()) if python_exists else "",
                "lab_path": str(lab_path.resolve()) if lab_exists else str(lab_path),
                "import_checked": False,
            },
            {
                "id": "task_registry_probe",
                "status": task_registry_status,
                "task_names": ["RobotisOMXPickPlaceLabEnv"],
                "probe_checked": False,
            },
            {
                "id": "record_demos_script",
                "status": "present" if record_demos.get("exists") else "missing",
                "path": str(record_demos.get("path") or ""),
            },
            {
                "id": "generate_dataset_script",
                "status": "present" if generate_dataset.get("exists") else "missing",
                "path": str(generate_dataset.get("path") or ""),
            },
            {
                "id": "robomimic_train_script",
                "status": "present" if robomimic.get("exists") else "missing",
                "path": str(robomimic.get("path") or ""),
            },
            {
                "id": "rl_train_wrapper",
                "status": "present" if rl_wrapper.get("exists") else "missing",
                "wrapper": rl_name,
                "path": str(rl_wrapper.get("path") or ""),
            },
        ]
        missing = [check for check in checks if check["status"] in {"blocked", "missing"}]
        return {
            "schema": "atr.lerobot.isaac_lab.smoke_checks.v1",
            "status": "blocked" if missing else "ready_to_probe",
            "import_checked": False,
            "task_registry_checked": False,
            "checks": checks,
            "blockers": [
                {
                    "code": f"SMOKE_{str(check['id']).upper()}_{str(check['status']).upper()}",
                    "check": check["id"],
                    "message": f"Isaac Lab smoke check {check['id']} is {check['status']}.",
                }
                for check in missing
            ],
        }

    def _isaac_sim_runtime_detector(
        self,
        request: IsaacLabSyntheticRequest,
        *,
        python_path: Path,
        sim_version_info: dict[str, Any],
        docs_version: str,
    ) -> dict[str, Any]:
        python_exists = python_path.is_file() if str(python_path) and str(python_path) != "." else False
        try:
            resolved_python = str(python_path.resolve()) if python_exists else str(python_path)
        except OSError:
            resolved_python = str(python_path)
        runtime_status = "deferred_to_isaac_runtime" if python_exists else "blocked"
        missing_reason = "" if python_exists else "isaac_sim_python_missing"
        return {
            "schema": "atr.lerobot.isaac_sim.runtime_detector.v1",
            "status": runtime_status,
            "isaac_sim_python": resolved_python if python_exists else "",
            "isaac_sim_python_exists": python_exists,
            "isaac_sim_version": str(sim_version_info.get("version") or ""),
            "isaac_sim_version_source": str(sim_version_info.get("source") or ""),
            "isaac_sim_version_checked": bool(sim_version_info.get("checked")),
            "selected_docs_version": docs_version,
            "runtime_import_checked": False,
            "probe_execution": "deferred_to_worker",
            "replicator": {
                "available": False,
                "status": runtime_status,
                "reason": missing_reason or "requires_isaac_runtime_import",
                "required_modules": list(REPLICATOR_REQUIRED_MODULES),
                "import_checked": False,
            },
            "physics_backend": {
                "name": "PhysX",
                "status": runtime_status,
                "reason": missing_reason or "requires_isaac_runtime_import",
                "import_checked": False,
                "gpu_dynamics": "unknown",
                "debug_visualization_available": "unknown",
                "docs_version": docs_version,
            },
            "sensor_extensions": {
                "omni.isaac.sensor": {
                    "available": False,
                    "status": runtime_status,
                    "reason": missing_reason or "requires_isaac_runtime_import",
                    "import_checked": False,
                },
                "isaacsim.sensors.camera": {
                    "available": False,
                    "status": runtime_status,
                    "reason": missing_reason or "requires_isaac_runtime_import",
                    "import_checked": False,
                },
            },
            "docs": [
                f"https://docs.isaacsim.omniverse.nvidia.com/{docs_version}/replicator_tutorials/index.html",
                f"https://docs.isaacsim.omniverse.nvidia.com/{docs_version}/physics/simulation_fundamentals.html",
                f"https://docs.isaacsim.omniverse.nvidia.com/{docs_version}/sensors/index.html",
            ],
            "request": {
                "enable_replicator": bool(request.enable_replicator),
                "require_physics_pass": bool(request.require_physics_pass),
                "require_depth_pass": bool(request.require_depth_pass),
            },
        }

    @staticmethod
    def _script_presence(root: Path, relative_paths: dict[str, str]) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "relative_path": relative_path,
                "path": str(root / relative_path),
                "exists": bool(root.is_dir() and (root / relative_path).is_file()),
            }
            for name, relative_path in relative_paths.items()
        }

    def _digital_twin_summary(
        self,
        request: IsaacLabSyntheticRequest,
        *,
        output_root: Path | None = None,
        write_snapshot: bool = False,
    ) -> dict[str, Any]:
        contract = self._stage_contract(request, output_root=output_root)
        stage_path = Path(contract["stage_path"])
        snapshot_path = ""
        snapshot_written = False
        if write_snapshot and output_root is not None and stage_path.is_file() and self._path_allowed(output_root):
            suffix = stage_path.suffix or ".usd"
            snapshot = output_root / "digital_twin" / f"stage_snapshot{suffix}"
            try:
                _atomic_copy_file(stage_path, snapshot)
            except OSError:
                snapshot_path = ""
            else:
                snapshot_path = str(snapshot)
                snapshot_written = True
        rtsp = contract.get("rtsp_streams") if isinstance(contract.get("rtsp_streams"), dict) else {}
        rtsp_manifest_path = Path(str(rtsp.get("manifest_path") or ""))
        if output_root is not None and rtsp_manifest_path and str(rtsp_manifest_path) != "." and self._path_allowed(output_root):
            _atomic_write_json(rtsp_manifest_path, rtsp)
        return {
            "schema": "atr.lerobot.isaac_lab.digital_twin_preflight.v1",
            **contract,
            "stage_snapshot_path": snapshot_path,
            "stage_snapshot_written": snapshot_written,
        }

    def _stage_contract(self, request: IsaacLabSyntheticRequest, *, output_root: Path | None = None) -> dict[str, Any]:
        stage_path = self._stage_path(request)
        text = self._read_stage_text(stage_path)
        stage_units = self._stage_units_meters_per_unit(text)
        up_axis = self._stage_up_axis(text)
        prim_paths = self._stage_prim_paths(text)
        robot_root = self._find_stage_prim(
            prim_paths,
            ["Robot", "robot", "RobotisOMX", "RobotisOMXAI", "omx", "omx_ai", "robotis_omx"],
            fallback_name="Robot",
        )
        workspace_root = self._find_stage_prim(
            prim_paths,
            ["A4Workspace", "Workspace", "workspace", "Table", "table", "Paper", "paper"],
            fallback_name="A4Workspace",
        )
        cube_prim = self._find_stage_prim(
            prim_paths,
            ["RedCube", "red_cube", "Cube", "cube", "Specimen", "specimen"],
            fallback_name="RedCube",
        )
        camera_prims = [self._camera_prim_contract(prim_paths, camera) for camera in request.cameras]
        return {
            "stage_path": str(stage_path),
            "stage_exists": stage_path.is_file(),
            "stage_units_meters_per_unit": stage_units,
            "up_axis": up_axis,
            "robot_root_prim": robot_root,
            "workspace_root_prim": workspace_root,
            "cube_prim": cube_prim,
            "requested_cameras": list(request.cameras),
            "camera_prims": camera_prims,
            "camera_prim_names": [row["path"] for row in camera_prims if row.get("found")],
            "detected_prim_count": len(prim_paths),
            "joint_zero_pose": self._digital_twin_joint_zero_contract(),
            "lerobot_joint_mapping": self._digital_twin_joint_mapping_contract(),
            "active_robot_cam": self._digital_twin_active_robot_cam_contract(),
            "d405_mount": self._digital_twin_d405_mount_contract(),
            "physics_materials": self._digital_twin_material_contract(),
            "rtsp_streams": self._digital_twin_rtsp_contract(request, output_root=output_root),
        }

    @staticmethod
    def _digital_twin_joint_zero_contract() -> dict[str, Any]:
        return {
            "reference": "stop_button_default_pose",
            "usd_joint_zero_is_default_pose": True,
            "usage": "calibration_reference_only",
            "teleop_pose_still_applied": True,
        }

    @staticmethod
    def _digital_twin_joint_mapping_contract() -> dict[str, Any]:
        return {
            "source": "utils.isaac_omx_mirror_mapping.ISAAC_OMX_JOINT_MAP",
            "joint_count": len(ISAAC_OMX_JOINT_MAP),
            "action_dimension": len(ISAAC_OMX_JOINT_MAP) + 1,
            "gripper_action_included": True,
            "joint_names": [str(row.get("isaac_joint_name") or "") for row in ISAAC_OMX_JOINT_MAP],
            "motor_ids": [_safe_int(row.get("motor_id"), 0, minimum=0) for row in ISAAC_OMX_JOINT_MAP],
            "leader_source_preferred": True,
        }

    @staticmethod
    def _digital_twin_active_robot_cam_contract() -> dict[str, Any]:
        return {
            "primary_camera_key": "wrist",
            "primary_model": "realsense_d405",
            "fallback_camera_key": "top",
            "fallback_model": "realsense_d455f",
            "pose_frame": "robot_base",
        }

    @staticmethod
    def _digital_twin_d405_mount_contract() -> dict[str, Any]:
        return {
            "camera": "d405",
            "mass_kg": 0.072,
            "mass_source": "intel_realsense_d405_nominal",
            "applied_to": "wrist_camera_mount",
            "sag_model": "gravity_load_contract",
        }

    @staticmethod
    def _digital_twin_material_contract() -> dict[str, Any]:
        return {
            "table": {"material": "paper", "role": "workspace_surface"},
            "cube": {"material": "3dp_pla", "role": "rigid_specimen"},
            "gripper_inner": {"material": "anti_slip_tape", "role": "high_friction_contact"},
        }

    @staticmethod
    def _digital_twin_rtsp_contract(request: IsaacLabSyntheticRequest, *, output_root: Path | None = None) -> dict[str, Any]:
        cameras = list(request.cameras)
        ports = [8554 + index for index, _camera in enumerate(cameras)]
        manifest_path = str(output_root / "digital_twin" / "rtsp_streams.json") if output_root is not None else ""
        registrations = [
            {
                "camera": str(camera),
                "port": ports[index],
                "url": f"rtsp://127.0.0.1:{ports[index]}/{camera}",
                "render_product": f"/Render/Products/{camera}",
                "startup_diagnostics": {
                    "first_frame_required": False,
                    "first_frame_status": "not_requested",
                    "startup_status": "not_requested",
                },
                "sei_metadata_capture": {
                    "enabled": True,
                    "frame_metadata_keys": ["camera", "frame_index", "timestamp_ns", "pose_robot_base"],
                },
            }
            for index, camera in enumerate(cameras)
        ]
        return {
            "required": False,
            "enabled": False,
            "unique_port_allocation": len(ports) == len(set(ports)),
            "manifest_path": manifest_path,
            "ports": ports,
            "registrations": registrations,
            "first_frame_required": False,
            "sei_metadata": "planned",
            "lifecycle_status": "not_requested",
        }

    @staticmethod
    def _read_stage_text(stage_path: Path) -> str:
        try:
            return stage_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    @staticmethod
    def _stage_units_meters_per_unit(stage_text: str) -> float | None:
        match = re.search(r"\bmetersPerUnit\s*=\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", stage_text)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _stage_up_axis(stage_text: str) -> str:
        match = re.search(r"\bupAxis\s*=\s*\"([^\"]+)\"", stage_text)
        return match.group(1) if match else ""

    @staticmethod
    def _stage_prim_paths(stage_text: str) -> dict[str, str]:
        prim_paths: dict[str, str] = {}
        stack: list[str] = []
        pending_prim: str | None = None
        prim_pattern = re.compile(r"\b(?:def|over|class)\s+\w+\s+\"([^\"]+)\"")
        for raw_line in stage_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if pending_prim and line.startswith("{"):
                stack.append(pending_prim)
                pending_prim = None
                continue
            match = prim_pattern.search(line)
            if match:
                name = match.group(1)
                prim_paths.setdefault(name, "/" + "/".join([*stack, name]))
                after_match = line[match.end() :]
                if "{" in after_match:
                    stack.append(name)
                else:
                    pending_prim = name
            close_count = line.count("}")
            for _ in range(close_count):
                if stack:
                    stack.pop()
        return prim_paths

    @staticmethod
    def _find_stage_prim(
        prim_paths: dict[str, str],
        candidates: list[str],
        *,
        fallback_name: str,
        allow_contains: bool = True,
    ) -> dict[str, Any]:
        for candidate in candidates:
            path = prim_paths.get(candidate)
            if path:
                return {"path": path, "found": True}
        lowered = [(name.lower(), path) for name, path in prim_paths.items()]
        for candidate in candidates:
            candidate_lower = candidate.lower()
            for name_lower, path in lowered:
                if candidate_lower == name_lower or (allow_contains and candidate_lower in name_lower):
                    return {"path": path, "found": True}
        return {"path": f"/World/{fallback_name}", "found": False}

    @classmethod
    def _camera_prim_contract(cls, prim_paths: dict[str, str], camera: str) -> dict[str, Any]:
        key = str(camera or "").strip()
        if not key:
            return {
                "camera": "",
                "path": "",
                "found": False,
                "source": "invalid_request",
                "planned_pose": {},
            }
        candidate_paths = cls._stage_camera_candidate_paths(key)
        for candidate_path in candidate_paths:
            if candidate_path in set(prim_paths.values()):
                return {"camera": key, "path": candidate_path, "found": True}
        found = cls._find_stage_prim(
            prim_paths,
            [
                f"Camera_{key}",
                f"{key}_camera",
                f"{key}Camera",
                key,
                key.capitalize(),
            ],
            fallback_name=f"Camera_{key}",
            allow_contains=False,
        )
        if found.get("found"):
            return {"camera": key, **found}
        planned_path = key if key.startswith("/") else f"/World/ATRRenderCameras/{key}"
        return {
            "camera": key,
            "path": planned_path,
            "found": False,
            "source": "replicator_worker_fallback",
            "stage_candidates": candidate_paths,
            "planned_pose": cls._planned_camera_pose(key),
        }

    @staticmethod
    def _stage_camera_candidate_paths(camera: str) -> list[str]:
        key = str(camera or "").strip()
        if not key:
            return []
        if key.startswith("/"):
            return [key]
        return [
            f"/World/Cameras/{key}",
            f"/World/Cameras/{key}_camera",
            f"/World/Cameras/Camera_{key}",
            f"/World/{key}_camera",
            f"/World/Camera_{key}",
            f"/World/ATRRenderCameras/{key}",
        ]

    @staticmethod
    def _planned_camera_pose(camera: str) -> dict[str, Any]:
        key = str(camera or "").lower()
        specs: dict[str, dict[str, Any]] = {
            "top": {"position": [0.315, 0.205, 0.72], "look_at": [0.315, 0.265, 0.0], "focal_length": 18.0},
            "front": {"position": [0.36, 0.96, 0.52], "look_at": [0.36, 0.28, 0.025], "focal_length": 14.0},
            "right": {"position": [0.86, 0.58, 0.52], "look_at": [0.38, 0.24, 0.02], "focal_length": 10.0},
            "wrist": {"position": [0.19, 0.08, 0.28], "look_at": [0.36, 0.28, 0.02], "focal_length": 18.0},
            "sim_overhead": {"position": [0.315, 0.265, 0.82], "look_at": [0.315, 0.265, 0.0], "focal_length": 18.0},
            "sim_top_oblique": {"position": [0.05, -0.12, 0.58], "look_at": [0.315, 0.265, 0.02], "focal_length": 18.0},
            "sim_wrist_offset": {"position": [0.14, 0.02, 0.32], "look_at": [0.36, 0.28, 0.02], "focal_length": 18.0},
        }
        spec = specs.get(key, {"position": [0.42, -0.08, 0.42], "look_at": [0.315, 0.265, 0.0], "focal_length": 18.0})
        return {
            **spec,
            "resolution": list(REPLICATOR_RENDER_RESOLUTION),
            "depth_units": "meters",
        }

    def _depth_summary(self, dataset_path: Path) -> dict[str, Any]:
        manifest = self._depth_manifest_path(dataset_path)
        data = _read_json(manifest)
        return {
            "schema": "atr.lerobot.depth_preflight.v1",
            "manifest_path": str(manifest),
            "manifest_exists": manifest.is_file(),
            "depth_encoding": str(data.get("depth_encoding") or ""),
            "depth_scale_m_per_unit": data.get("depth_scale_m_per_unit"),
            "camera_keys": list(data.get("camera_keys") or []),
        }

    def _static_group_summary(self, checks: list[ValidationCheck], group: str) -> dict[str, Any]:
        group_checks = [check.as_dict() for check in checks if check.group == group]
        return {
            "schema": f"atr.lerobot.{group}_preflight.v1",
            "status": "blocked" if any(row.get("status") == "blocked" for row in group_checks) else "passed",
            "checks": group_checks,
        }

    def _summary(self, request: IsaacLabSyntheticRequest, dataset_path: Path, output_root: Path, status: str) -> dict[str, Any]:
        return {
            "schema": SUMMARY_SCHEMA,
            "run_id": "latest",
            "status": status,
            "dataset_path": str(dataset_path),
            "output_root": str(output_root),
            "pipeline_mode": request.pipeline_mode.value,
            "fallback_policy": request.fallback_policy.value,
            "source_intent": request.source_intent.value,
            "fallback_used": False,
            "started_at": _now(),
            "finished_at": _now(),
            "counts": {
                "real_frames": 0,
                "canonical_frames": 0,
                "replicator_rows": 0,
                "mimic_candidates": 0,
                "mimic_successes": 0,
                "training_rows": 0,
            },
            "artifacts": {
                "validation_report": "validation_report.json",
                "canonical_index": "canonical_episode_index/manifest.jsonl",
                "training_import": "training_import/manifest.jsonl",
            },
            "blockers": [],
            "warnings": [],
        }

    def _build_canonical_index(self, request: IsaacLabSyntheticRequest, dataset_path: Path) -> list[dict[str, Any]]:
        episodes = _read_jsonl(dataset_path / "meta" / "episodes.jsonl")
        if not episodes:
            info = _read_json(dataset_path / "meta" / "info.json")
            total_frames = _safe_int(info.get("total_frames"), 0, minimum=0)
            episodes = [{"episode_index": 0, "length": max(total_frames, 1)}]
        rows: list[dict[str, Any]] = []
        depth = self._depth_summary(dataset_path)
        grasp_diagnostics_by_frame = self._mirror_grasp_diagnostics_by_frame(dataset_path)
        max_rows = request.max_source_frames
        success_by_episode = self._episode_success_by_index(dataset_path)
        for episode in episodes:
            episode_index = _safe_int(episode.get("episode_index"), 0, minimum=0)
            length = _safe_int(episode.get("length"), 1, minimum=1)
            episode_success = success_by_episode.get(episode_index, True)
            for frame_index in range(length):
                if len(rows) >= max_rows:
                    return rows
                grasp_diagnostics = grasp_diagnostics_by_frame.get((episode_index, frame_index))
                grasp_event_label = (
                    str(grasp_diagnostics.get("event_label") or "") if isinstance(grasp_diagnostics, dict) else ""
                )
                row = {
                    "schema": CANONICAL_FRAME_SCHEMA,
                    "dataset_id": dataset_path.name,
                    "episode_index": episode_index,
                    "episode_success": episode_success,
                    "frame_index": frame_index,
                    "timestamp_s": round(frame_index / 15.0, 6),
                    "lerobot": {
                        "observation_path": f"data/chunk-000/episode_{episode_index:06d}.parquet",
                        "action_index": frame_index,
                        "action_valid": True,
                    },
                    "real_rgb": {"available": False, "path": "", "frame_index": frame_index},
                    "raw_depth": {
                        "available": bool(depth.get("manifest_exists")),
                        "path": str(depth.get("manifest_path") or ""),
                        "dtype": "uint16" if depth.get("manifest_exists") else "",
                        "depth_units": "meter_per_unit",
                        "scale_m_per_unit": depth.get("depth_scale_m_per_unit"),
                    },
                    "isaac_rgbd": {
                        "available": bool(list((dataset_path / "sidecar" / "isaac_rgbd").glob("**/manifest.jsonl"))),
                        "camera_names": list(request.cameras),
                        "manifest_row": frame_index,
                    },
                    "active_robot_cam": {"available": False},
                    "grasp_diagnostics": grasp_diagnostics or {"available": False},
                    "grasp_event_label": grasp_event_label,
                }
                rows.append(self._canonical_row_with_source_markers(row))
        return rows

    def _mirror_grasp_diagnostics_by_frame(self, dataset_path: Path) -> dict[tuple[int, int], dict[str, Any]]:
        indexed: dict[tuple[int, int], dict[str, Any]] = {}
        mirror_root = dataset_path / "sidecar" / "isaac_mirror"
        for manifest_path in sorted(mirror_root.glob("*.jsonl")):
            for row in _read_jsonl(manifest_path):
                diagnostics = self._extract_mirror_grasp_diagnostics(row)
                if not diagnostics:
                    continue
                episode_index = _safe_int(row.get("episode_index"), 0, minimum=0)
                frame_index = self._mirror_frame_index(row)
                if frame_index is None:
                    continue
                event_label = self._grasp_event_label(diagnostics)
                indexed[(episode_index, frame_index)] = {
                    **diagnostics,
                    "available": bool(diagnostics.get("available", True)),
                    "state": event_label,
                    "event_label": event_label,
                    "source_manifest": str(manifest_path),
                    "sample_index": row.get("sample_index"),
                }
        return indexed

    @staticmethod
    def _extract_mirror_grasp_diagnostics(row: dict[str, Any]) -> dict[str, Any]:
        isaac_post = row.get("isaac_post") if isinstance(row.get("isaac_post"), dict) else {}
        isaac_response = isaac_post.get("response") if isinstance(isaac_post.get("response"), dict) else {}
        action_processing = row.get("action_processing") if isinstance(row.get("action_processing"), dict) else {}
        candidates = [
            row.get("grasp_diagnostics"),
            isaac_response.get("grasp_diagnostics"),
            action_processing.get("grasp_diagnostics"),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict):
                return dict(candidate)
        return {}

    @staticmethod
    def _mirror_frame_index(row: dict[str, Any]) -> int | None:
        if "frame_index" in row:
            return _safe_int(row.get("frame_index"), 0, minimum=0)
        if "canonical_frame_index" in row:
            return _safe_int(row.get("canonical_frame_index"), 0, minimum=0)
        if "sample_index" in row:
            sample_index = _safe_int(row.get("sample_index"), 1, minimum=1)
            return sample_index - 1
        return None

    @staticmethod
    def _grasp_event_label(diagnostics: dict[str, Any]) -> str:
        status = str(diagnostics.get("status") or diagnostics.get("state") or "").strip()
        if status == "grasp_candidate" and bool(diagnostics.get("object_lifted")):
            return "lifted"
        if status in {"released", "gripper_released"}:
            return "released"
        if status in {"not_near_object", "closed_not_near_object"}:
            return "not_near_object"
        if status == "near_closed_without_contact":
            return "near_closed_without_contact"
        if status == "grasp_candidate":
            return "grasp_candidate"
        if bool(diagnostics.get("near_object")) is False:
            return "not_near_object"
        return status

    @staticmethod
    def _canonical_row_with_source_markers(row: dict[str, Any]) -> dict[str, Any]:
        optional_sources = ["real_rgb", "raw_depth", "isaac_rgbd", "active_robot_cam", "grasp_diagnostics"]
        availability = {
            source: bool((row.get(source) if isinstance(row.get(source), dict) else {}).get("available"))
            for source in optional_sources
        }
        lerobot = row.get("lerobot") if isinstance(row.get("lerobot"), dict) else {}
        action_valid = bool(lerobot.get("action_valid"))
        availability["lerobot_action"] = action_valid
        required_missing = [] if action_valid else ["lerobot_action"]
        optional_missing = [source for source in optional_sources if not availability[source]]
        return {
            **row,
            "source_availability": availability,
            "missing_sources": required_missing + optional_missing,
            "source_completeness": {
                "required_missing": required_missing,
                "optional_missing": optional_missing,
            },
        }

    @staticmethod
    def _dataset_canonical_index_root(dataset_path: Path) -> Path:
        return dataset_path / "sidecar" / "canonical_episode_index" / "latest"

    def _canonical_index_summary_with_paths(
        self,
        *,
        dataset_path: Path,
        output_root: Path,
        canonical_summary: dict[str, Any],
    ) -> dict[str, Any]:
        lab_manifest = output_root / "canonical_episode_index" / "manifest.jsonl"
        lab_summary = output_root / "canonical_episode_index" / "summary.json"
        dataset_root = self._dataset_canonical_index_root(dataset_path)
        dataset_manifest = dataset_root / "manifest.jsonl"
        dataset_summary = dataset_root / "summary.json"
        return {
            **canonical_summary,
            "manifest_path": str(lab_manifest),
            "summary_path": str(lab_summary),
            "dataset_manifest_path": str(dataset_manifest),
            "dataset_summary_path": str(dataset_summary),
        }

    def _write_canonical_index_artifacts(
        self,
        *,
        dataset_path: Path,
        output_root: Path,
        canonical_rows: list[dict[str, Any]],
        canonical_summary: dict[str, Any],
    ) -> None:
        lab_manifest = output_root / "canonical_episode_index" / "manifest.jsonl"
        lab_summary = output_root / "canonical_episode_index" / "summary.json"
        dataset_root = self._dataset_canonical_index_root(dataset_path)
        dataset_manifest = dataset_root / "manifest.jsonl"
        dataset_summary = dataset_root / "summary.json"
        _atomic_write_jsonl(lab_manifest, canonical_rows)
        _atomic_write_json(
            lab_summary,
            {
                **canonical_summary,
                "dataset_manifest_path": str(dataset_manifest),
                "dataset_summary_path": str(dataset_summary),
            },
        )
        _atomic_write_jsonl(dataset_manifest, canonical_rows)
        _atomic_write_json(
            dataset_summary,
            {
                **canonical_summary,
                "manifest_path": str(dataset_manifest),
                "summary_path": str(dataset_summary),
                "isaac_lab_manifest_path": str(lab_manifest),
                "isaac_lab_summary_path": str(lab_summary),
            },
        )

    def _source_labels(
        self,
        request: IsaacLabSyntheticRequest,
        canonical_rows: list[dict[str, Any]],
        *,
        replicator_rows: list[dict[str, Any]] | None = None,
        generated_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        replicator_rows = list(replicator_rows or [])
        generated_rows = list(generated_rows or [])
        generated_counts = self._count_by(generated_rows, "source_type")
        generated_trainable_counts = self._count_by(
            [
                row
                for row in generated_rows
                if str(((row.get("artifacts") if isinstance(row.get("artifacts"), dict) else {}) or {}).get("hdf5_path") or "").strip()
            ],
            "source_type",
        )
        counts = {
            IsaacSyntheticSourceType.REAL_LEROBOT.value: len(canonical_rows),
            IsaacSyntheticSourceType.ISAAC_RGBD_RENDER.value: sum(1 for row in canonical_rows if (row.get("isaac_rgbd") or {}).get("available")),
            IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value: len(replicator_rows),
            IsaacSyntheticSourceType.ISAAC_TELEOP_REPLAY_RENDER.value: 0,
            IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value: _safe_int(generated_counts.get(IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value), 0, minimum=0),
            IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value: _safe_int(generated_counts.get(IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value), 0, minimum=0),
            IsaacSyntheticSourceType.LEGACY_SIDECAR.value: 0,
        }
        train_ready_intent = request.source_intent == IsaacSyntheticSourceIntent.TRAIN_READY_SUCCESS_ONLY
        details = {
            source: {
                "available": count > 0,
                "count": count,
                "trainable_count": count,
                "train_default": source == IsaacSyntheticSourceType.REAL_LEROBOT.value and count > 0 and train_ready_intent,
                "render_only": source in {
                    IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value,
                    IsaacSyntheticSourceType.ISAAC_TELEOP_REPLAY_RENDER.value,
                },
            }
            for source, count in counts.items()
        }
        details[IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value]["trainable_count"] = 0
        details[IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value]["train_default"] = False
        details[IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value]["trainable_count"] = _safe_int(
            generated_trainable_counts.get(IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value),
            0,
            minimum=0,
        )
        details[IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value]["train_default"] = (
            details[IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value]["trainable_count"] > 0
            and train_ready_intent
        )
        details[IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value]["trainable_count"] = _safe_int(
            generated_trainable_counts.get(IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value),
            0,
            minimum=0,
        )
        details[IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value]["train_default"] = (
            details[IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value]["trainable_count"] > 0
            and train_ready_intent
            and request.enable_rl_teacher
        )
        return {
            "schema": "atr.lerobot.source_labels.v1",
            "counts": counts,
            "details": details,
        }

    @staticmethod
    def _source_labels_with_training_config(
        source_labels: dict[str, Any],
        *,
        source_config: dict[str, Any],
        training_summary: dict[str, Any],
    ) -> dict[str, Any]:
        counts = dict(source_labels.get("counts") or {})
        details = {
            str(source): dict(detail if isinstance(detail, dict) else {})
            for source, detail in dict(source_labels.get("details") or {}).items()
        }
        weights = dict(source_config.get("weights") or {})
        fidelity_weights = dict(source_config.get("fidelity_weights") or {})
        train_defaults = dict(source_config.get("train_defaults") or {})
        exposed_counts = dict(training_summary.get("source_counts") or {})
        candidate_counts = dict(training_summary.get("candidate_source_counts") or {})
        for source, default in train_defaults.items():
            source_key = str(source)
            default_row = dict(default if isinstance(default, dict) else {})
            counts.setdefault(source_key, _safe_int(default_row.get("available_count"), 0, minimum=0))
            detail = details.setdefault(
                source_key,
                {
                    "available": bool(default_row.get("available")),
                    "count": counts.get(source_key, 0),
                    "trainable_count": _safe_int(default_row.get("trainable_count"), 0, minimum=0),
                    "train_default": bool(default_row.get("train_default")),
                    "render_only": source_key
                    in {
                        IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value,
                        IsaacSyntheticSourceType.ISAAC_TELEOP_REPLAY_RENDER.value,
                    },
                },
            )
            source_weight = _safe_float(default_row.get("source_weight"), _safe_float(weights.get(source_key), 0.0, minimum=0.0), minimum=0.0)
            fidelity_weight = _safe_float(
                default_row.get("fidelity_weight"),
                _safe_float(fidelity_weights.get(source_key), 1.0, minimum=0.0),
                minimum=0.0,
            )
            detail["source_weight"] = source_weight
            detail["fidelity_weight"] = fidelity_weight
            detail["effective_weight"] = round(source_weight * fidelity_weight, 6)
            detail["candidate_training_row_count"] = _safe_int(candidate_counts.get(source_key), 0, minimum=0)
            detail["training_row_count"] = _safe_int(exposed_counts.get(source_key), 0, minimum=0)
            detail["train_exposed"] = bool(training_summary.get("train_exposed")) and detail["training_row_count"] > 0
        return {
            **source_labels,
            "counts": counts,
            "details": details,
            "weights": weights,
            "fidelity_weights": fidelity_weights,
            "training_import": {
                "manifest_path": str(training_summary.get("manifest_path") or ""),
                "source_config_path": str(training_summary.get("source_config_path") or ""),
                "validation_path": str(training_summary.get("validation_path") or ""),
                "row_count": _safe_int(training_summary.get("row_count"), 0, minimum=0),
                "candidate_row_count": _safe_int(training_summary.get("candidate_row_count"), 0, minimum=0),
                "exposed_row_count": _safe_int(training_summary.get("exposed_row_count"), 0, minimum=0),
                "blocked_row_count": _safe_int(training_summary.get("blocked_row_count"), 0, minimum=0),
                "source_counts": exposed_counts,
                "candidate_source_counts": candidate_counts,
                "train_exposed": bool(training_summary.get("train_exposed")),
                "validation_status": str(training_summary.get("validation_status") or ""),
                "validation_ok": bool(training_summary.get("validation_ok")),
                "blockers": list(training_summary.get("blockers") or []),
            },
        }

    def _replicator_manifest_rows(self, output_root: Path, *, valid_only: bool = False) -> list[dict[str, Any]]:
        rows = []
        manifest_rows = _read_jsonl(output_root / "replicator" / "manifest.jsonl")
        invalid_indices: set[int] = set()
        if valid_only:
            validation = self._replicator_render_file_validation(output_root, manifest_rows)
            invalid_indices = {
                _safe_int(row.get("row_index"), -1)
                for row in list(validation.get("invalid_rows") or [])
                if isinstance(row, dict)
            }
        for index, row in enumerate(manifest_rows):
            if str(row.get("source_type") or IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value) != IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value:
                continue
            if valid_only and index in invalid_indices:
                continue
            rows.append(row)
        return rows

    @staticmethod
    def _preview_file_ref(raw_path: Any, *, root: Path | None = None) -> dict[str, Any]:
        if not raw_path:
            return {"available": False, "path": "", "serve_url": ""}
        path = Path(str(raw_path)).expanduser()
        if root is not None and not path.is_absolute():
            path = root / path
        available = path.is_file()
        return {
            "available": available,
            "path": str(path),
            "serve_url": f"/api/lerobot/visualization/file?path={quote(str(path))}" if available else "",
        }

    @classmethod
    def _preview_media(
        cls,
        *,
        real_rgb: Any = "",
        raw_depth_preview: Any = "",
        isaac_rgbd: Any = "",
        replicator_rgb: Any = "",
        replicator_depth_preview: Any = "",
        root: Path | None = None,
    ) -> dict[str, Any]:
        return {
            "real_rgb": cls._preview_file_ref(real_rgb, root=root),
            "raw_depth_preview": cls._preview_file_ref(raw_depth_preview, root=root),
            "isaac_rgbd": cls._preview_file_ref(isaac_rgbd, root=root),
            "replicator_rgb": cls._preview_file_ref(replicator_rgb, root=root),
            "replicator_depth_preview": cls._preview_file_ref(replicator_depth_preview, root=root),
        }

    @classmethod
    def _real_preview_card(cls, row: dict[str, Any]) -> dict[str, Any]:
        episode_index = _safe_int(row.get("episode_index"), 0, minimum=0)
        frame_index = _safe_int(row.get("frame_index"), 0, minimum=0)
        raw_depth = row.get("raw_depth") if isinstance(row.get("raw_depth"), dict) else {}
        isaac_rgbd = row.get("isaac_rgbd") if isinstance(row.get("isaac_rgbd"), dict) else {}
        episode_success = row.get("episode_success") is not False
        return {
            "row_id": f"{IsaacSyntheticSourceType.REAL_LEROBOT.value}:e{episode_index:06d}:f{frame_index:06d}",
            "source_type": IsaacSyntheticSourceType.REAL_LEROBOT.value,
            "episode_index": row.get("episode_index"),
            "frame_index": row.get("frame_index"),
            "camera": "",
            "episode_success": episode_success,
            "train_eligible": episode_success,
            "train_exclusion_reason": "" if episode_success else "episode_marked_failed",
            "raw_depth_available": bool(raw_depth.get("available")),
            "isaac_rgbd_available": bool(isaac_rgbd.get("available")),
            "qa": {
                "episode_success": episode_success,
                "raw_depth_available": bool(raw_depth.get("available")),
                "isaac_rgbd_available": bool(isaac_rgbd.get("available")),
            },
            "media": cls._preview_media(
                real_rgb=row.get("rgb_path") or row.get("image_path") or "",
                raw_depth_preview=raw_depth.get("preview_path") or raw_depth.get("path") or "",
                isaac_rgbd=isaac_rgbd.get("rgb_path") or isaac_rgbd.get("path") or "",
            ),
            "trajectory": {"available": False, "source": ""},
        }

    @classmethod
    def _replicator_preview_card(cls, row: dict[str, Any], *, output_root: Path) -> dict[str, Any]:
        episode_index = _safe_int(row.get("episode_index"), 0, minimum=0)
        frame_index = _safe_int(row.get("frame_index"), 0, minimum=0)
        camera = str(row.get("camera") or row.get("camera_name") or "")
        variant_index = _safe_int(row.get("variant_index"), 0, minimum=0)
        rgb_path = str(row.get("rgb_path") or "")
        depth_path = str(row.get("depth_path") or "")
        return {
            "row_id": f"{IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value}:e{episode_index:06d}:f{frame_index:06d}:c{camera}:v{variant_index:03d}",
            "source_type": IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value,
            "episode_index": row.get("episode_index"),
            "frame_index": row.get("frame_index"),
            "camera": camera,
            "variant_index": row.get("variant_index"),
            "rgb_path": rgb_path,
            "depth_path": depth_path,
            "segmentation_path": str(row.get("segmentation_path") or ""),
            "metadata_path": str(row.get("metadata_path") or ""),
            "train_eligible": bool(row.get("train_eligible")),
            "train_exclusion_reason": str(row.get("train_exclusion_reason") or ""),
            "qa": dict(row.get("qa") or {}),
            "media": cls._preview_media(
                replicator_rgb=rgb_path,
                replicator_depth_preview=depth_path,
                root=output_root,
            ),
            "trajectory": {"available": False, "source": ""},
        }

    def _generated_preview_rows(self, output_root: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        manifests = [
            (IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value, output_root / "mimic" / "successes.jsonl", "successes"),
            (IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value, output_root / "mimic" / "failures.jsonl", "failures"),
            (IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value, output_root / "rl_teacher" / "successes.jsonl", "successes"),
            (IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value, output_root / "rl_teacher" / "failures.jsonl", "failures"),
        ]
        for expected_source_type, manifest_path, manifest_kind in manifests:
            for row in _read_jsonl(manifest_path):
                source_type = str(row.get("source_type") or expected_source_type)
                if source_type != expected_source_type:
                    continue
                trajectory_id = str(row.get("trajectory_id") or row.get("source_id") or "").strip()
                if not trajectory_id:
                    trajectory_id = f"{source_type}_{len(rows):06d}"
                metrics = dict(row.get("metrics") if isinstance(row.get("metrics"), dict) else {})
                if manifest_kind == "failures":
                    metrics.setdefault("success", False)
                rows.append(
                    {
                        **row,
                        "source_type": source_type,
                        "trajectory_id": trajectory_id,
                        "metrics": metrics,
                        "manifest_path": str(manifest_path),
                        "manifest_kind": manifest_kind,
                    }
                )
        return rows

    def _generated_success_rows(self, output_root: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        manifests = [
            (IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value, output_root / "mimic" / "successes.jsonl"),
            (IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value, output_root / "rl_teacher" / "successes.jsonl"),
        ]
        for expected_source_type, manifest_path in manifests:
            for row in _read_jsonl(manifest_path):
                source_type = str(row.get("source_type") or expected_source_type)
                if source_type != expected_source_type:
                    continue
                metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
                training = row.get("training") if isinstance(row.get("training"), dict) else {}
                if not _safe_bool(metrics.get("success"), False):
                    continue
                if not _safe_bool(training.get("eligible"), False):
                    continue
                trajectory_id = str(row.get("trajectory_id") or row.get("source_id") or "").strip()
                if not trajectory_id:
                    trajectory_id = f"{source_type}_{len(rows):06d}"
                rows.append(
                    {
                        **row,
                        "source_type": source_type,
                        "trajectory_id": trajectory_id,
                        "manifest_path": str(manifest_path),
                    }
                )
        return rows

    @classmethod
    def _generated_preview_card(cls, row: dict[str, Any], *, output_root: Path) -> dict[str, Any]:
        artifacts = row.get("artifacts") if isinstance(row.get("artifacts"), dict) else {}
        training = row.get("training") if isinstance(row.get("training"), dict) else {}
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        artifact_path = str(artifacts.get("hdf5_path") or "")
        preview_path = str(artifacts.get("preview_path") or "")
        source_type = str(row.get("source_type") or "")
        source_id = str(row.get("trajectory_id") or row.get("source_id") or "")
        train_eligible = (
            _safe_bool(training.get("eligible"), False)
            and _safe_bool(metrics.get("success"), False)
            and bool(artifact_path.strip())
        )
        exclusion_reason = str(training.get("exclusion_reason") or "")
        if not train_eligible and not exclusion_reason and not artifact_path.strip():
            exclusion_reason = "artifact_path_missing"
        return {
            "row_id": f"{source_type}:{source_id}",
            "source_type": source_type,
            "source_id": source_id,
            "episode_index": row.get("source_episode_index"),
            "frame_index": row.get("source_frame_index"),
            "camera": "",
            "artifact_path": artifact_path,
            "preview_path": preview_path,
            "train_eligible": train_eligible,
            "train_exclusion_reason": exclusion_reason,
            "metrics": dict(metrics),
            "qa": dict(metrics),
            "media": cls._preview_media(),
            "trajectory": {
                "available": bool(artifact_path.strip()),
                "source": source_type,
                "trajectory_id": source_id,
                "artifact_path": artifact_path,
                "preview_path": preview_path,
                "preview": cls._preview_file_ref(preview_path, root=output_root),
                "manifest_path": str(row.get("manifest_path") or ""),
                "manifest_kind": str(row.get("manifest_kind") or ""),
            },
        }

    def _training_import_rows(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        canonical_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not canonical_rows:
            return []
        episode_indices = sorted({int(row["episode_index"]) for row in canonical_rows})
        rows: list[dict[str, Any]] = []
        for episode_index in episode_indices:
            episode_rows = [row for row in canonical_rows if int(row["episode_index"]) == episode_index]
            if any(row.get("episode_success") is False for row in episode_rows):
                continue
            frame_start = min(int(row["frame_index"]) for row in episode_rows)
            frame_end = max(int(row["frame_index"]) for row in episode_rows)
            rows.append(
                {
                    "schema": TRAINING_IMPORT_SCHEMA,
                    "source_type": IsaacSyntheticSourceType.REAL_LEROBOT.value,
                    "source_label": IsaacSyntheticSourceType.REAL_LEROBOT.value,
                    "source_id": f"real_episode_{episode_index:06d}",
                    "dataset_path": str(dataset_path),
                    "artifact_path": f"data/chunk-000/episode_{episode_index:06d}.parquet",
                    "episode_index": episode_index,
                    "frame_start": frame_start,
                    "frame_end": frame_end,
                    "success": True,
                    "source_weight": request.real_weight,
                    "fidelity_weight": 1.0,
                    "effective_weight": round(request.real_weight * 1.0, 6),
                    "validation_report": "../validation_report.json",
                    "generation_manifest": "../canonical_episode_index/manifest.jsonl",
                }
            )
        return rows

    def _generated_training_import_rows(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        generated_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in generated_rows:
            source_type = str(row.get("source_type") or "")
            if source_type == IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value and not request.enable_rl_teacher:
                continue
            if source_type not in {
                IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value,
                IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value,
            }:
                continue
            artifacts = row.get("artifacts") if isinstance(row.get("artifacts"), dict) else {}
            training = row.get("training") if isinstance(row.get("training"), dict) else {}
            source_id = str(row.get("trajectory_id") or row.get("source_id") or "").strip()
            artifact_path = str(artifacts.get("hdf5_path") or "").strip()
            fidelity_default = 0.25 if source_type == IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value else 0.3
            fidelity_weight = _safe_float(training.get("fidelity_weight"), fidelity_default, minimum=0.0, maximum=1.0)
            source_weight = request.isaac_lab_synthetic_weight
            rows.append(
                {
                    "schema": TRAINING_IMPORT_SCHEMA,
                    "source_type": ISAAC_LAB_SYNTHETIC_AGGREGATE_SOURCE,
                    "source_label": source_type,
                    "generator_source_type": source_type,
                    "source_id": source_id,
                    "dataset_path": str(dataset_path),
                    "artifact_path": artifact_path,
                    "episode_index": _safe_int(row.get("source_episode_index"), 0, minimum=0),
                    "frame_start": self._generated_frame_start(row),
                    "frame_end": self._generated_frame_end(row),
                    "success": True,
                    "source_weight": source_weight,
                    "fidelity_weight": fidelity_weight,
                    "effective_weight": round(source_weight * fidelity_weight, 6),
                    "validation_report": "../validation_report.json",
                    "generation_manifest": self._relative_generation_manifest(output_root, Path(str(row.get("manifest_path") or ""))),
                }
            )
        return rows

    @staticmethod
    def _generated_frame_start(row: dict[str, Any]) -> int:
        frame_start = row.get("frame_start")
        if frame_start is not None:
            return _safe_int(frame_start, 0, minimum=0)
        return 0

    @staticmethod
    def _generated_frame_end(row: dict[str, Any]) -> int:
        if row.get("frame_end") is not None:
            return _safe_int(row.get("frame_end"), 0, minimum=0)
        subtasks = row.get("subtasks") if isinstance(row.get("subtasks"), dict) else {}
        ends = [
            _safe_int(value.get("end_frame"), 0, minimum=0)
            for value in subtasks.values()
            if isinstance(value, dict) and value.get("end_frame") is not None
        ]
        if ends:
            return max(ends)
        if row.get("num_frames") is not None:
            return max(0, _safe_int(row.get("num_frames"), 1, minimum=1) - 1)
        return _safe_int(row.get("source_frame_index"), 0, minimum=0)

    @staticmethod
    def _relative_generation_manifest(output_root: Path, manifest_path: Path) -> str:
        try:
            return str(manifest_path.resolve().relative_to((output_root / "training_import").resolve()))
        except (OSError, ValueError):
            try:
                return str(Path("..") / manifest_path.resolve().relative_to(output_root.resolve()))
            except (OSError, ValueError):
                return str(manifest_path)

    @staticmethod
    def _failed_episode_indices(canonical_rows: list[dict[str, Any]]) -> list[int]:
        return sorted({int(row["episode_index"]) for row in canonical_rows if row.get("episode_success") is False})

    def _episode_success_by_index(self, dataset_path: Path) -> dict[int, bool]:
        result: dict[int, bool] = {}
        for episode in _read_jsonl(dataset_path / "meta" / "episodes.jsonl"):
            episode_index = _safe_int(episode.get("episode_index"), 0, minimum=0)
            result[episode_index] = self._episode_success(episode)
        return result

    @staticmethod
    def _episode_success(episode: dict[str, Any]) -> bool:
        for key in ("success", "is_success", "episode_success", "train_success"):
            if key in episode:
                return _safe_bool(episode.get(key), True)
        metrics = episode.get("metrics")
        if isinstance(metrics, dict) and "success" in metrics:
            return _safe_bool(metrics.get("success"), True)
        status = str(episode.get("status") or episode.get("episode_status") or "").strip()
        if status:
            return _safe_bool(status, True)
        return True

    def _training_source_config(
        self,
        *,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        source_labels: dict[str, Any],
        training_rows: list[dict[str, Any]],
        replicator_summary: dict[str, Any],
    ) -> dict[str, Any]:
        counts = dict(source_labels.get("counts") or {})
        training_counts = self._count_by(training_rows, "source_type")
        aggregate_lab_source = "isaac_lab_synthetic"
        sources = [
            IsaacSyntheticSourceType.REAL_LEROBOT.value,
            IsaacSyntheticSourceType.ISAAC_RGBD_RENDER.value,
            IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value,
            IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value,
            IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value,
            aggregate_lab_source,
            IsaacSyntheticSourceType.LEGACY_SIDECAR.value,
        ]
        weights = {
            IsaacSyntheticSourceType.REAL_LEROBOT.value: request.real_weight,
            IsaacSyntheticSourceType.ISAAC_RGBD_RENDER.value: request.isaac_rgbd_weight,
            IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value: request.replicator_render_weight,
            IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value: request.isaac_lab_synthetic_weight,
            IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value: request.isaac_lab_synthetic_weight,
            aggregate_lab_source: request.isaac_lab_synthetic_weight,
            IsaacSyntheticSourceType.LEGACY_SIDECAR.value: request.legacy_sidecar_weight,
        }
        fidelity_weights = {
            IsaacSyntheticSourceType.REAL_LEROBOT.value: 1.0,
            IsaacSyntheticSourceType.ISAAC_RGBD_RENDER.value: 0.5,
            IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value: 0.4,
            IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value: 0.3,
            IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value: 0.0,
            aggregate_lab_source: 0.25,
            IsaacSyntheticSourceType.LEGACY_SIDECAR.value: 0.2,
        }
        train_defaults: dict[str, dict[str, Any]] = {}
        for source in sources:
            available_count = _safe_int(counts.get(source), 0, minimum=0)
            trainable_count = _safe_int(training_counts.get(source), 0, minimum=0)
            train_defaults[source] = {
                "available": available_count > 0 or trainable_count > 0,
                "available_count": available_count,
                "trainable_count": trainable_count,
                "train_default": trainable_count > 0,
                "source_weight": weights[source],
                "fidelity_weight": fidelity_weights[source],
            }
        return {
            "schema": "atr.lerobot.training_import.source_config.v1",
            "dataset_path": str(dataset_path),
            "output_root": str(output_root),
            "source_intent": request.source_intent.value,
            "manifest_path": str(output_root / "training_import" / "manifest.jsonl"),
            "source_config_path": str(output_root / "training_import" / "lerobot_source_config.json"),
            "weights": weights,
            "fidelity_weights": fidelity_weights,
            "train_defaults": train_defaults,
            "replicator": {
                "status": replicator_summary.get("status", "skipped"),
                "expected_render_rows": replicator_summary.get("expected_render_rows", 0),
                "rendered_count": replicator_summary.get("rendered_count", 0),
                "manifest_path": replicator_summary.get("manifest_path", ""),
            },
        }

    @staticmethod
    def _validation_report_with_training_blockers(
        validation_report: dict[str, Any],
        training_validation: dict[str, Any],
    ) -> dict[str, Any]:
        blockers = list(validation_report.get("blockers") or [])
        for blocker in list(training_validation.get("blockers") or []):
            blockers.append(
                {
                    "code": str(blocker.get("code") or "TRAINING_IMPORT_BLOCKED"),
                    "check": "validate_training_import",
                    "message": str(blocker.get("message") or "Training import validation blocked train exposure."),
                }
            )
        checks = list(validation_report.get("checks") or [])
        checks.append(
            {
                "id": "validate_training_import",
                "group": "training",
                "status": "blocked",
                "severity": "blocker",
                "message": "Training import validation blocked train exposure.",
                "evidence": {
                    "validation_path": training_validation.get("validation_path", ""),
                    "row_count": training_validation.get("row_count", 0),
                },
                "blocker_code": blockers[-1]["code"] if blockers else "TRAINING_IMPORT_BLOCKED",
                "docs": [],
                "artifacts": {},
            }
        )
        return {
            **validation_report,
            "ok": False,
            "status": "blocked",
            "stage": "training",
            "checks": checks,
            "blockers": blockers,
        }

    @staticmethod
    def _validation_report_with_hdf5_check(
        validation_report: dict[str, Any],
        export_summary: dict[str, Any],
    ) -> dict[str, Any]:
        report = dict(validation_report or {})
        checks = list(report.get("checks") or [])
        checks = [check for check in checks if str(check.get("id") or "") != "validate_hdf5_export"]
        ok = bool(export_summary.get("ok"))
        blocker_code = str(export_summary.get("blocker") or "HDF5_EXPORT_BLOCKED")
        checks.append(
            {
                "id": "validate_hdf5_export",
                "group": "hdf5",
                "status": "passed" if ok else "blocked",
                "severity": "info" if ok else "blocker",
                "message": str(
                    export_summary.get("message")
                    or ("HDF5 export completed." if ok else "HDF5 export blocked.")
                ),
                "evidence": {
                    "output_path": export_summary.get("output_path", ""),
                    "hdf5_available": bool(export_summary.get("hdf5_available")),
                    "exported_episode_count": export_summary.get("exported_episode_count", 0),
                    "exported_frame_count": export_summary.get("exported_frame_count", 0),
                    "canonical_frame_count": export_summary.get("canonical_frame_count", 0),
                },
                "blocker_code": None if ok else blocker_code,
                "docs": ["https://isaac-sim.github.io/IsaacLab/main/source/overview/imitation-learning/index.html"],
                "artifacts": {},
            }
        )
        if ok:
            return {
                **report,
                "checks": checks,
            }
        blockers = list(report.get("blockers") or [])
        if not any(str(blocker.get("code") or "") == blocker_code for blocker in blockers):
            blockers.append(
                {
                    "code": blocker_code,
                    "check": "validate_hdf5_export",
                    "message": str(export_summary.get("message") or "HDF5 export blocked."),
                }
            )
        return {
            **report,
            "schema": report.get("schema", VALIDATION_SCHEMA),
            "ok": False,
            "status": "blocked",
            "stage": "hdf5",
            "checks": checks,
            "blockers": blockers,
        }

    @staticmethod
    def _validation_report_with_build_checks(
        validation_report: dict[str, Any],
        *,
        canonical_summary: dict[str, Any],
        training_validation: dict[str, Any],
    ) -> dict[str, Any]:
        checks = list(validation_report.get("checks") or [])
        existing = {str(check.get("id") or "") for check in checks}
        if "validate_canonical_episode_index" not in existing:
            frame_count = _safe_int(canonical_summary.get("frame_count"), 0, minimum=0)
            checks.append(
                {
                    "id": "validate_canonical_episode_index",
                    "group": "canonical_index",
                    "status": "passed" if frame_count > 0 else "warning",
                    "severity": "info" if frame_count > 0 else "warning",
                    "message": "Canonical episode index was written from LeRobot episodes.",
                    "evidence": {
                        "manifest_path": canonical_summary.get("manifest_path", ""),
                        "episode_count": canonical_summary.get("episode_count", 0),
                        "frame_count": frame_count,
                    },
                    "docs": [],
                    "artifacts": {},
                }
            )
        if training_validation.get("status") != "blocked" and "validate_training_import" not in existing:
            status = str(training_validation.get("status") or "skipped")
            checks.append(
                {
                    "id": "validate_training_import",
                    "group": "training",
                    "status": "passed" if status == "passed" else "skipped",
                    "severity": "info",
                    "message": "Training import validation completed without blockers."
                    if status == "passed"
                    else "Training import validation did not expose rows for training.",
                    "evidence": {
                        "validation_path": training_validation.get("validation_path", ""),
                        "row_count": training_validation.get("row_count", 0),
                        "candidate_row_count": training_validation.get("candidate_row_count", 0),
                        "train_exposed": bool(training_validation.get("train_exposed")),
                    },
                    "docs": [],
                    "artifacts": {},
                }
            )
        return {
            **validation_report,
            "checks": checks,
        }

    @staticmethod
    def _validation_report_with_replicator_blocker(
        validation_report: dict[str, Any],
        replicator_summary: dict[str, Any],
    ) -> dict[str, Any]:
        blocker_code = str(replicator_summary.get("blocker") or "REPLICATOR_UNAVAILABLE")
        blockers = list(validation_report.get("blockers") or [])
        if not any(str(blocker.get("code") or "") == blocker_code for blocker in blockers):
            blockers.append(
                {
                    "code": blocker_code,
                    "check": "validate_replicator_outputs",
                    "message": str(replicator_summary.get("message") or "Replicator output validation blocked the synthetic branch."),
                }
            )
        checks = list(validation_report.get("checks") or [])
        checks.append(
            {
                "id": "validate_replicator_outputs",
                "group": "replicator",
                "status": "blocked",
                "severity": "blocker",
                "message": str(replicator_summary.get("message") or "Replicator output validation blocked the synthetic branch."),
                "evidence": {
                    "summary_path": str(Path(str(replicator_summary.get("output_root") or "")) / "replicator" / "summary.json"),
                    "render_file_validation": dict(replicator_summary.get("render_file_validation") or {}),
                },
                "blocker_code": blocker_code,
                "docs": ["https://docs.isaacsim.omniverse.nvidia.com/6.0.0/replicator_tutorials/index.html"],
                "artifacts": {},
            }
        )
        return {
            **validation_report,
            "ok": False,
            "status": "blocked",
            "stage": "replicator",
            "checks": checks,
            "blockers": blockers,
        }

    def _training_import_validation(
        self,
        *,
        request: IsaacLabSyntheticRequest,
        output_root: Path,
        training_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        manifest_path = output_root / "training_import" / "manifest.jsonl"
        validation_path = output_root / "training_import" / "training_import_validation.json"
        allowed_sources = {
            IsaacSyntheticSourceType.REAL_LEROBOT.value,
            IsaacSyntheticSourceType.ISAAC_RGBD_RENDER.value,
            IsaacSyntheticSourceType.REPLICATOR_RENDER_ONLY.value,
            IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value,
            IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value,
            ISAAC_LAB_SYNTHETIC_AGGREGATE_SOURCE,
            IsaacSyntheticSourceType.LEGACY_SIDECAR.value,
        }
        if request.source_intent != IsaacSyntheticSourceIntent.TRAIN_READY_SUCCESS_ONLY:
            return {
                "schema": "atr.lerobot.training_import.validation.v1",
                "ok": True,
                "status": "skipped",
                "source_intent": request.source_intent.value,
                "train_exposed": False,
                "manifest_path": str(manifest_path),
                "manifest_exists": False,
                "validation_path": str(validation_path),
                "row_count": 0,
                "failed_row_count": 0,
                "invalid_source_count": 0,
                "blockers": [],
                "warnings": [
                    {
                        "code": "TRAINING_IMPORT_PREVIEW_ONLY",
                        "message": "Source intent does not expose rows to LeRobot training.",
                    }
                ],
                "checks": [
                    {"id": "source_intent_allows_training", "status": "skipped"},
                    {"id": "failed_rows_excluded", "status": "skipped"},
                    {"id": "source_types_allowed", "status": "skipped"},
                ],
            }
        blockers: list[dict[str, Any]] = []
        failed_rows = [
            {"row_index": index, "source_type": row.get("source_type"), "success": row.get("success")}
            for index, row in enumerate(training_rows)
            if row.get("success") is not True
        ]
        invalid_sources = [
            {"row_index": index, "source_type": row.get("source_type")}
            for index, row in enumerate(training_rows)
            if str(row.get("source_type") or "") not in allowed_sources
        ]
        missing_artifacts = [
            {"row_index": index, "source_type": row.get("source_type")}
            for index, row in enumerate(training_rows)
            if not str(row.get("artifact_path") or "").strip()
        ]
        missing_traceability = [
            {
                "row_index": index,
                "source_type": row.get("source_type"),
                "missing": [
                    key
                    for key in ("source_label", "fidelity_weight", "generation_manifest")
                    if (key not in row) or (key != "fidelity_weight" and not str(row.get(key) or "").strip())
                ],
            }
            for index, row in enumerate(training_rows)
            if any(
                (key not in row) or (key != "fidelity_weight" and not str(row.get(key) or "").strip())
                for key in ("source_label", "fidelity_weight", "generation_manifest")
            )
        ]
        synthetic_source_mismatches = [
            {
                "row_index": index,
                "source_type": row.get("source_type"),
                "source_label": row.get("source_label"),
            }
            for index, row in enumerate(training_rows)
            if (
                str(row.get("source_label") or "")
                in {IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value, IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value}
                or str(row.get("source_type") or "") in {IsaacSyntheticSourceType.ISAAC_LAB_MIMIC.value, IsaacSyntheticSourceType.ISAAC_LAB_RL_TEACHER.value}
            )
            and str(row.get("source_type") or "") != ISAAC_LAB_SYNTHETIC_AGGREGATE_SOURCE
        ]
        if failed_rows:
            blockers.append(
                {
                    "code": "TRAINING_IMPORT_FAILED_ROWS_PRESENT",
                    "message": "Failed rows cannot be exposed to training.",
                    "rows": failed_rows[:20],
                }
            )
        if invalid_sources:
            blockers.append(
                {
                    "code": "TRAINING_IMPORT_SOURCE_TYPE_INVALID",
                    "message": "Training import contains unknown source_type values.",
                    "rows": invalid_sources[:20],
                }
            )
        if missing_artifacts:
            blockers.append(
                {
                    "code": "TRAINING_IMPORT_ARTIFACT_PATH_MISSING",
                    "message": "Training import rows must reference an artifact path.",
                    "rows": missing_artifacts[:20],
                }
            )
        if missing_traceability:
            blockers.append(
                {
                    "code": "TRAINING_IMPORT_TRACEABILITY_FIELDS_MISSING",
                    "message": "Training import rows must include source_label, fidelity_weight, and generation_manifest.",
                    "rows": missing_traceability[:20],
                }
            )
        if synthetic_source_mismatches:
            blockers.append(
                {
                    "code": "TRAINING_IMPORT_SYNTHETIC_SOURCE_TYPE_INVALID",
                    "message": "Isaac Lab generated rows must use source_type=isaac_lab_synthetic and keep generator detail in source_label.",
                    "rows": synthetic_source_mismatches[:20],
                }
            )
        status = "blocked" if blockers else "passed"
        return {
            "schema": "atr.lerobot.training_import.validation.v1",
            "ok": not blockers,
            "status": status,
            "source_intent": request.source_intent.value,
            "train_exposed": bool(training_rows) and not blockers,
            "manifest_path": str(manifest_path),
            "manifest_exists": bool(training_rows),
            "validation_path": str(validation_path),
            "row_count": len(training_rows),
            "failed_row_count": len(failed_rows),
            "invalid_source_count": len(invalid_sources),
            "missing_artifact_count": len(missing_artifacts),
            "missing_traceability_count": len(missing_traceability),
            "synthetic_source_mismatch_count": len(synthetic_source_mismatches),
            "blockers": blockers,
            "warnings": [],
            "checks": [
                {"id": "source_intent_allows_training", "status": "passed"},
                {"id": "failed_rows_excluded", "status": "passed" if not failed_rows else "blocked"},
                {"id": "source_types_allowed", "status": "passed" if not invalid_sources else "blocked"},
                {"id": "artifact_paths_present", "status": "passed" if not missing_artifacts else "blocked"},
                {"id": "traceability_fields_present", "status": "passed" if not missing_traceability else "blocked"},
                {"id": "isaac_lab_synthetic_source_type", "status": "passed" if not synthetic_source_mismatches else "blocked"},
            ],
        }

    @staticmethod
    def _remove_path(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return

    def _response(
        self,
        *,
        tool: str,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        output_root: Path,
        status: IsaacSyntheticRunStatus,
        validation_report: dict[str, Any] | None = None,
        compatibility: dict[str, Any] | None = None,
        digital_twin: dict[str, Any] | None = None,
        canonical_episode_index: dict[str, Any] | None = None,
        replicator: dict[str, Any] | None = None,
        hdf5: dict[str, Any] | None = None,
        mimic: dict[str, Any] | None = None,
        rl_teacher: dict[str, Any] | None = None,
        source_labels: dict[str, Any] | None = None,
        training_exposure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        blockers = list((validation_report or {}).get("blockers") or [])
        ok = status not in {IsaacSyntheticRunStatus.BLOCKED, IsaacSyntheticRunStatus.FAILED, IsaacSyntheticRunStatus.CANCELLED}
        return {
            "ok": ok,
            "tool": tool,
            "schema": RESPONSE_SCHEMA,
            "status": status.value,
            "dataset_path": str(dataset_path),
            "output_root": str(output_root),
            "run_id": "latest",
            "job_id": None,
            "pipeline_mode": request.pipeline_mode.value,
            "fallback_policy": request.fallback_policy.value,
            "source_intent": request.source_intent.value,
            "fallback_used": False,
            "validation_report": validation_report or {},
            "compatibility": compatibility or {},
            "digital_twin": digital_twin or {},
            "canonical_episode_index": canonical_episode_index or {},
            "replicator": replicator or {"status": "skipped"},
            "hdf5": hdf5 or {},
            "mimic": mimic or {"status": "skipped"},
            "rl_teacher": rl_teacher or {"status": "skipped"},
            "source_labels": source_labels or {},
            "training_exposure": training_exposure or {},
            "synthetic_trajectory_metrics": self._synthetic_trajectory_metrics(
                output_root,
                mimic=mimic,
                rl_teacher=rl_teacher,
                training_exposure=training_exposure,
            ),
            "progress": {"percent": 100.0 if ok else 0.0, "status": status.value},
            "step_trace": self._step_trace(validation_report or {}, status=status),
            "error": (
                {
                    "code": blockers[0].get("code", "UNKNOWN_BLOCKER"),
                    "message": blockers[0].get("message", "Synthetic pipeline is blocked."),
                    "stage": (validation_report or {}).get("stage", ""),
                    "evidence": blockers[0],
                }
                if blockers
                else None
            ),
        }

    def _step_trace(self, validation_report: dict[str, Any], *, status: IsaacSyntheticRunStatus) -> list[dict[str, Any]]:
        checks = list(validation_report.get("checks") or [])
        if not checks:
            return [
                {
                    "stage": "request",
                    "status": status.value.lower(),
                    "progress_start": 0.0,
                    "progress_end": 100.0 if status != IsaacSyntheticRunStatus.BLOCKED else 0.0,
                    "message": status.value,
                }
            ]
        return [
            {
                "stage": str(check.get("group") or ""),
                "status": str(check.get("status") or ""),
                "progress_start": float(index),
                "progress_end": float(index + 1),
                "message": str(check.get("message") or ""),
                "blocker_code": check.get("blocker_code"),
            }
            for index, check in enumerate(checks)
        ]

    def _isaac_lab_path(self, request: IsaacLabSyntheticRequest) -> Path:
        if request.isaac_lab_path:
            return Path(request.isaac_lab_path).expanduser().resolve()
        local = self.repo_root / "IsaacLab"
        if local.exists():
            return local.resolve()
        return Path("/home/jin/IsaacLab").expanduser().resolve()

    def _stage_path(self, request: IsaacLabSyntheticRequest) -> Path:
        if request.stage_path:
            return Path(request.stage_path).expanduser().resolve()
        return (self.repo_root / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda").resolve()

    def _depth_manifest_path(self, dataset_path: Path) -> Path:
        for rel in (
            "sidecar/depth_raw/transform_manifest.json",
            "sidecar/raw_depth/transform_manifest.json",
            "sidecar/depth_raw/manifest.json",
            "sidecar/raw_depth/manifest.json",
        ):
            candidate = dataset_path / rel
            if candidate.is_file():
                return candidate
        return dataset_path / "sidecar" / "depth_raw" / "transform_manifest.json"

    @staticmethod
    def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            value = str(row.get(key) or "")
            counts[value] = counts.get(value, 0) + 1
        return counts

    @staticmethod
    def _git_identity(path: Path) -> dict[str, str]:
        if not path.is_dir():
            return {}
        result: dict[str, str] = {}
        try:
            commit = subprocess.check_output(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            ).strip()
            result["commit"] = commit
        except Exception:
            result["commit"] = ""
        try:
            tag = subprocess.check_output(
                ["git", "-C", str(path), "describe", "--tags", "--always"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            ).strip()
            result["tag"] = tag
        except Exception:
            result["tag"] = ""
        return result
