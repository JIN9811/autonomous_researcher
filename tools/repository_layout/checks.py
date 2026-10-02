"""Pinned software checks executed exclusively in disposable namespaces."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from .manifest import build_manifest, validate_manifest, git_entries, _git
from .sandbox import export_tracked, run_bounded, sandbox_command

CHECKS: dict[str, list[list[str]]] = {
    "1": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_layout_manifest.py",
            "tests/unit/test_layout_validation_sandbox.py"
        ]
    ],
    "2": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_runtime_paths.py",
            "tests/unit/test_runtime_path_consumers.py",
            "tests/unit/test_source_runtime.py",
            "tests/unit/test_knowledge_archive_intake.py",
            "tests/unit/test_run_review.py",
            "tests/unit/test_experiment_runtime.py"
        ]
    ],
    "3": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_knowledge_publication.py"
        ]
    ],
    "4": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_package_contracts.py",
            "tests/unit/test_langgraph_runtime.py",
            "tests/unit/test_module_control_views.py",
            "tests/unit/test_runtime_reference_roots.py",
            "tests/unit/test_orchestrator_capabilities.py",
            "tests/unit/test_ide_module_lifecycle_js.py",
            "tests/integration/test_agent_execution_graph_api.py",
            "tests/integration/test_packages_api.py",
            "tests/integration/test_design_module_lifecycle.py"
        ],
        [
            "node",
            "--test",
            "tests/js/agent_module_host.test.cjs",
            "tests/js/module_execution_editor.test.cjs",
            "tests/js/module_control_view.test.cjs",
            "tests/js/module_control_structure.test.cjs"
        ]
    ],
    "5": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_knowledge_layout_compatibility.py",
            "tests/unit/test_runtime_wiki_safety.py",
            "tests/unit/test_knowledge_workspace_services.py",
            "tests/unit/test_manual_knowledge_ingest.py",
            "tests/unit/test_manual_knowledge_retrieval.py",
            "tests/unit/test_rag.py",
            "tests/unit/test_graphify_bridge.py",
            "tests/unit/test_source_runtime.py",
            "tests/unit/test_knowledge_archive_intake.py",
            "tests/integration/test_knowledge_graphify_api.py"
        ]
    ],
    "6": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_persisted_references.py",
            "tests/unit/test_run_recovery_checkpoint.py",
            "tests/unit/test_equipment_tail_recovery.py",
            "tests/unit/test_bo_budget_recovery.py",
            "tests/unit/test_run_review_artifacts.py",
            "tests/unit/test_agent_artifact_archive.py",
            "tests/unit/test_run_review.py",
            "tests/unit/test_artifact_preservation.py"
        ],
        [
            "node",
            "--test",
            "tests/js/run_review_artifacts.test.cjs"
        ]
    ],
    "7": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_runtime_worker_origins.py",
            "tests/unit/test_runtime_launchers.py",
            "tests/unit/test_compute_pool.py",
            "tests/unit/test_monitor_process.py",
            "tests/unit/test_safe_hot_reload.py",
            "tests/unit/test_local_pyautogui_bridge.py",
            "tests/unit/test_cli_restart.py",
            "tests/unit/test_module_designer_cli_contract.py"
        ]
    ],
    "8": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_document_relocation.py",
            "tests/unit/test_documentation_validation.py",
            "tests/unit/test_paper_publication_validation.py",
            "tests/unit/test_knowledge_publication.py",
            "tests/unit/test_knowledge_layout_compatibility.py"
        ]
    ],
    "9": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_distribution_layout.py",
            "tests/unit/test_install_packaging.py",
            "tests/unit/test_cli_restart.py",
            "tests/unit/test_module_designer_cli_contract.py",
            "tests/unit/test_package_contracts.py",
            "tests/unit/test_knowledge_publication.py",
            "tests/unit/test_windows_bridge_release.py",
            "tests/unit/test_windows_bridge_supervisor.py",
            "tests/unit/test_windows_bridge_self_updater.py",
            "tests/unit/test_windows_pyautogui_bridge_server_helper.py",
            "tests/unit/test_windows_pyautogui_demo_assets.py",
            "tests/unit/test_advanced_visual_work_queue_e2e.py",
            "tests/unit/test_advanced_visual_work_queue_demo.py"
        ]
    ],
    "10": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_external_asset_layout.py",
            "tests/unit/test_specimen_pose_tracker.py",
            "tests/unit/test_isaac_lab_robotis_omx_registration.py",
            "tests/unit/test_isaac_grip_pad_inset.py",
            "tests/unit/test_camera_vision_package.py",
            "tests/unit/test_utm_runtime_stack_script.py",
            "tests/unit/test_utm_runtime_camera_env.py",
            "tests/unit/test_linear_interpolation_options.py",
            "tests/unit/test_lerobot_bridge.py",
            "tests/unit/test_plc_bridge.py",
            "tests/unit/test_plc_bridge_service.py",
            "tests/unit/test_lerobot_gui_static.py",
            "tests/integration/test_rtc_queue_alignment.py",
            "libs/joint_linear_interpolation/tests/test_transmitter.py"
        ],
        [
            "node",
            "--test",
            "tests/js/omx_environment_layout.test.cjs"
        ]
    ],
    "11": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests"
        ],
        [
            "node",
            "--test",
            "tests/js"
        ]
    ],
    "12": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_private_state_migration.py",
            "tests/unit/test_runtime_paths.py",
            "tests/unit/test_knowledge_layout_compatibility.py",
            "tests/unit/test_persisted_references.py",
            "tests/integration/test_repository_layout_equivalence.py"
        ]
    ]
}
BASELINE = "ba273ddb0fc2bf8795630d51d93d3932748e0a51"

# Task 7's final, bounded cross-slice gate. Keep failures visible by partition,
# with fresh child-origin evidence and the original behavior suites alongside
# each root/default matrix. No device/model/provider lifecycle is exercised.
_TASK7_PARTITIONS = [
    # Root propagation across the composed bootstrap and app factories.
    ["tests/unit/test_runtime_paths.py", "tests/unit/test_runtime_path_consumers.py",
     "tests/unit/test_runtime_bridge_roots.py", "tests/unit/test_runtime_printer_roots.py",
     "tests/unit/test_runtime_lerobot_roots.py", "tests/unit/test_runtime_app_bridge_roots.py",
     "tests/unit/test_runtime_knowledge_roots.py", "tests/unit/test_runtime_app_knowledge_roots.py",
     "tests/unit/test_runtime_ancillary_roots.py", "tests/unit/test_knowledge_graph_cli.py"],
    # Actual fresh children: origins, metadata, environment, artifacts, cancellation.
    ["tests/unit/test_runtime_worker_origins.py", "tests/unit/test_runtime_launchers.py",
     "tests/unit/test_compute_pool.py", "tests/unit/test_monitor_process.py",
     "tests/unit/test_safe_hot_reload.py", "tests/unit/test_local_pyautogui_bridge.py",
     "tests/unit/test_cli_restart.py", "tests/unit/test_module_designer_cli_contract.py"],
    # UTM/pose/equipment synthetic behavior and private output families.
    ["tests/unit/test_utm_tools.py", "tests/unit/test_utm_runtime_bridge.py",
     "tests/unit/test_utm_camera_config.py", "tests/unit/test_utm_camera_calibration_command.py",
     "tests/unit/test_utm_runtime_camera_env.py", "tests/unit/test_utm_state_observer.py",
     "tests/unit/test_specimen_pose_tracker.py", "tests/unit/test_equipment_pyautogui_bridge.py",
     "tests/unit/test_multifidelity_contracts.py", "tests/unit/test_vision_monitor_stream.py",
     "tests/unit/test_windows_equipment_module_contract.py", "tests/unit/test_camera_vision_package.py"],
    # Both printer branches, profile helpers and artifact/provenance compatibility.
    ["tests/unit/test_prusa_bridge.py", "tests/unit/test_printer_tools.py",
     "tests/unit/test_bambu_bridge.py", "tests/unit/test_bambu_auto_orientation.py",
     "tests/unit/test_bambu_slicer_profiles.py", "tests/unit/test_printer_fleet_package.py",
     "tests/unit/test_bambu_material_priority.py", "tests/unit/test_printer_profile.py",
     "tests/unit/test_bambu_autoejection.py", "tests/unit/test_bambu_autoejection_completion_audit.py"],
    # LeRobot source and process contracts. One unchanged baseline interpreter-name
    # assertion is recorded in task-7d-report.md, not rerun to produce a known failure.
    ["tests/unit/test_lerobot_home_paths.py", "tests/unit/test_lerobot_bridge.py",
     "tests/unit/test_lerobot_tools.py", "tests/unit/test_lerobot_joint_telemetry.py",
     "tests/unit/test_lerobot_isaac_lab_e2e_contract.py", "tests/unit/test_lerobot_isaac_lab_synthetic.py",
     "tests/unit/test_lerobot_isaac_mirror_runtime_wrapper.py", "tests/unit/test_lerobot_active_robot_cam_once.py",
     "tests/unit/test_lerobot_replay.py", "tests/unit/test_lerobot_rollout_profile.py",
     "tests/unit/test_manipulation_lerobot_agent.py", "tests/unit/test_lerobot_synthetic_e2e_smoke.py",
     "tests/unit/test_lerobot_isaac_lab_validate_cli.py", "tests/unit/test_isaac_omx_mirror_mapping.py",
     "--deselect=tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_live_e2e_check_command_uses_real_10s_three_episode_preset"],
    # Knowledge ownership, ontology, evidence identities and retired API behavior.
    ["tests/unit/test_knowledge_service.py", "tests/unit/test_knowledge_graph_backend.py",
     "tests/unit/test_knowledge_ontology.py", "tests/unit/test_knowledge_agent.py",
     "tests/unit/test_knowledge_reconciliation_service.py", "tests/unit/test_knowledge_layout_compatibility.py",
     "tests/unit/test_graphify_bridge.py", "tests/unit/test_source_runtime.py",
     "tests/integration/test_knowledge_api.py", "tests/integration/test_knowledge_ontology_api.py",
     "tests/integration/test_knowledge_graphify_api.py", "tests/integration/test_markdown_knowledge_api.py"],
    # Ancillary agent semantics and the changed controller BO-store composition.
    ["tests/unit/test_analysis_agent.py", "tests/unit/test_analysis_measurement_only.py",
     "tests/unit/test_analysis_decisions.py", "tests/unit/test_design_agent.py",
     "tests/unit/test_design_decision.py", "tests/unit/test_design_evidence_display.py",
     "tests/unit/test_test_bo_workspace.py", "tests/unit/test_test_mode_cycles.py"],
]
CHECKS["7"] = [
    ["python", "-u", "-m", "pytest", "-vv", "--tb=short", "-p", "pytest_asyncio.plugin", *selection]
    for selection in _TASK7_PARTITIONS
]
# Reuse the already-approved dependency-only CPU profile, never a simulator.
CHECKS["7"][4][:1] = ["/usr/bin/env", "ISAAC_LAB_PATH=/deps/validation-tools/isaaclab-cpu-source", "/deps/bin/python3", "-S"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["check"])
    parser.add_argument("task", choices=sorted(CHECKS))
    parser.add_argument("--dependencies", type=Path)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--baseline-suite", action="store_true", help="Run bounded ordinary pytest after containment")
    args = parser.parse_args(argv)
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    private = root / ".superpowers/sdd/2026-10-01-repository-layout-migration"
    dependencies = args.dependencies or private / "deps"
    original = build_manifest(root, BASELINE)
    revision = _git(root, "rev-parse", "--verify", f"{args.revision}^{{tree}}").decode().strip()
    records = {path: (mode, kind, blob) for path, mode, kind, blob in git_entries(root, revision)}
    candidates = [path for path in ("docs/maintenance/repository_layout_manifest.json",
                                   "system/maintenance/repository_layout_manifest.json") if path in records]
    if len(candidates) != 1:
        print(json.dumps({"manifest_errors": ["Requested revision must contain exactly one public inventory"]}))
        return 1
    mode, kind, blob = records[candidates[0]]
    if kind != "blob" or mode not in {"100644", "100755"}:
        print(json.dumps({"manifest_errors": ["Revision inventory must be a regular Git blob"]}))
        return 1
    try:
        manifest = json.loads(_git(root, "cat-file", "blob", blob))
    except (ValueError, UnicodeDecodeError) as exc:
        print(json.dumps({"manifest_errors": [f"Invalid revision inventory JSON: {exc}"]}))
        return 1
    if not isinstance(manifest, dict):
        print(json.dumps({"manifest_errors": ["Revision inventory must be an object"]}))
        return 1
    errors = validate_manifest(manifest)
    if manifest.get("baseline_commit") != BASELINE or set(manifest.get("entries", {})) != set(original["entries"]):
        errors.append("Public inventory no longer accounts for the frozen baseline")
    for path, entry in manifest.get("entries", {}).items():
        if path in original["entries"] and any(entry.get(key) != original["entries"][path][key]
                                              for key in ("mode", "git_blob", "sha256", "size")):
            errors.append(f"Unexplained baseline object drift: {path}")
    if errors:
        print(json.dumps({"manifest_errors": errors}))
        return 1
    private.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="check-", dir=private) as temporary:
        snapshot = Path(temporary) / "snapshot"
        export_tracked(root, snapshot, revision=revision)
        cwd = "/snapshot/runtime" if (snapshot / "runtime/pyproject.toml").is_file() else "/snapshot"
        probe = ["python", "-c", "import json; from tools.repository_layout.sandbox import boundary_probe; b=boundary_probe(); print(json.dumps(b)); assert not b['host_paths_visible'] and not b['device_nodes'] and not b['host_pid_visible'] and not b['non_loopback_connected']"]
        commands = [["python", "-m", "pytest", "-p", "pytest_asyncio.plugin"]] if args.baseline_suite else CHECKS[args.task]
        for command in [probe, *commands]:
            completed = run_bounded(sandbox_command(snapshot, dependencies, command, cwd=cwd), timeout=args.timeout)
            print(completed.stdout, end="", flush=True)
            results.append({"command": command, "returncode": completed.returncode, "output": completed.stdout})
            if command is probe and completed.returncode:
                break
    report = {"task": args.task, "baseline": BASELINE, "revision": revision,
              "requested_revision": args.revision, "checks": results,
              "software_only": True, "complete": len(results) == len(commands) + 1}
    label = "baseline-suite" if args.baseline_suite else f"check-{args.task}"
    (private / f"{label}-results.json").write_text(json.dumps(report, indent=2))
    return 0 if report["complete"] and all(item["returncode"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
