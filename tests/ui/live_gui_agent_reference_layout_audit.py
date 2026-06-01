#!/usr/bin/env python3
"""Agent-by-agent Live GUI reference layout audit.

This audit is intentionally stricter than card-count checks. It compares the
current browser screenshots against the generated_full_screens references by:
- full-image RGB MAE
- topbar / left rail / center report / right chat / bottom dock MAE
- center-panel edge projection peaks, which expose row/column layout mismatch
- DOM card geometry when browser capture is requested

The goal is to drive code -> screenshot -> reference image layout diff -> code,
not merely to satisfy section counts.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageStat

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from runtime_ide_browser_audit import WebDriverAudit  # noqa: E402

try:
    import numpy as np
    from scipy.ndimage import sobel
except Exception as exc:  # pragma: no cover - handled at runtime
    np = None
    sobel = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = ROOT / "livegui_package/autonomous_researcher_live_gui_uiux_package_v2/00_references/generated_full_screens"
OUT_DIR_DEFAULT = ROOT / "artifacts/live_gui_upgrade/layout_geometry_audit"

AGENTS = [
    ("orchestrator", "01_orchestrator_agent_report.png"),
    ("design", "02_design_agent_report.png"),
    ("specimen", "03_specimen_making_agent_report.png"),
    ("vision", "04_vision_agent_report.png"),
    ("manipulation", "05_manipulation_agent_report.png"),
    ("equipment", "06_lab_equipment_agent_report.png"),
    ("analysis", "07_analysis_agent_report.png"),
    ("bo", "08_bayesian_optimization_agent_report.png"),
]

# Structured evidence payloads are deliberately compact but complete enough to
# render primary visuals for each generated_full_screens agent report.
SAMPLE_SECTIONS: dict[str, dict[str, Any]] = {
    "orchestrator": {
        "mission_contract": {"objective": "FDM-printable TPMS compression specimen loop", "mode": "test", "trigger": "operator execution", "constraint_count": 6},
        "route_state": {"route_progress": 68, "handoff_count": 3, "stage_count": 8, "active_stage": "orchestrator"},
        "missing_inputs": {"missing_count": 0, "required_inputs": "objective, specimen size, material, printer mode", "status": "complete"},
        "decision_register": {"approval_ratio": 82, "decision_count": 5, "risk_ratio": 18, "followup_count": 1},
        "followup_questions": {"question_count": 2, "priority": "printer mode and test specimen size", "status": "ready"},
        "approval_summary": {"approval_ratio": 76, "gate_count": 4, "blocked_count": 0, "status": "operator-visible"},
        "risk_register": {"risk_count": 3, "highest_risk": "printer connection and layer adhesion", "risk_ratio": 24},
        "task_queue": {"queued_count": 5, "active_count": 1, "completed_count": 2, "next_agent": "Design Agent"},
        "next_action": {"next_action": "collect missing values or execute workflow", "handoff": "Design Agent", "confidence_ratio": 88},
    },
    "design": {
        "design_brief": {"objective": "FDM-printable gyroid TPMS compression specimen", "target": "specific energy absorption", "constraint_count": 7},
        "candidate_board": {"candidate_count": 6, "valid_count": 5, "relative_density_ratio": 0.32, "cell_size_mm": 5},
        "candidate_ranking": {"selected_score": 0.74, "uncertainty": 0.18, "info_gain": 0.42, "risk_ratio": 22},
        "parameter_sweep": {"density_min_ratio": 0.24, "density_max_ratio": 0.42, "wall_thickness_mm": 0.8, "sample_count": 24},
        "expected_performance": {"predicted_strength_mpa": 8.4, "energy_absorption_score": 0.69, "confidence_ratio": 78, "iteration_count": 3},
        "manufacturability": {"manufacturability_ratio": 86, "overhang_risk_ratio": 18, "slicer_ready": "yes", "fdm_gate": "pass"},
        "material_notes": {"material": "PLA", "nozzle_mm": 0.4, "layer_height_mm": 0.2},
        "handoff_to_specimen": {"next_agent": "Specimen Making Agent", "handoff_ready": "yes", "artifact": "stl_path"},
        "artifact_ledger": {"stl": "artifacts/design/specimen.stl", "preview": "artifacts/design/preview.png", "metadata": "design.json"},
    },
    "specimen": {
        "slicer_configuration": {"profile": "MK4S PLA 0.20 quality", "layer_height_mm": 0.2, "nozzle_mm": 0.4, "skirt": "off"},
        "printer_profile": {"printer": "Prusa MK4S", "material": "PLA", "bed_temp_c": 60, "nozzle_temp_c": 215},
        "build_queue": {"queued_count": 1, "ready_count": 1, "blocked_count": 0, "job": "tpms-test"},
        "estimated_print_time": {"duration_min": 38, "warmup_min": 4, "slicing_duration_s": 12, "transfer_duration_s": 18},
        "filament_usage": {"filament_g": 4.6, "material_cost_score": 0.21, "mass_ratio": 0.31, "spool_remaining_ratio": 82},
        "gcode_validation": {"gcode_size_mb": 2.4, "validation_count": 5, "failed_count": 0, "status": "pass"},
        "print_readiness": {"readiness_ratio": 91, "gate_count": 6, "blocked_count": 0, "adhesion_risk_ratio": 16},
        "build_timeline": {"step_count": 6, "completion_ratio": 72, "handoff": "Vision Agent", "next": "upload_or_virtual_bridge"},
        "layer_preview": {"layer_count": 100, "first_layer_mm": 0.2, "infill_ratio": 0.32, "shell_count": 0},
        "artifact_ledger": {"stl": "specimen.stl", "gcode": "specimen.gcode", "slicer_report": "slicer.json"},
        "printer_status": {"printer_ready_ratio": 88, "network_latency_ms": 12, "bed_temp_c": 60, "nozzle_temp_c": 215},
        "handoff_status": {"next_agent": "Vision Agent", "handoff_ready": "yes", "fabrication_schema": "phase1"},
    },
    "vision": {
        "camera_health": {"camera_count": 2, "frame_age_ms": 42, "dropped_frame_ratio": 1, "status": "ok"},
        "calibration_summary": {"calibration_score": 0.91, "reprojection_error_px": 0.38, "confidence_ratio": 86, "camera_count": 2},
        "confidence_distribution": {"pickup_ready_confidence": 0.84, "defect_probability": 0.08, "pose_confidence": 0.79, "quality_ratio": 88},
        "inspection_feed": {"frame_count": 12, "latency_ms": 55, "confidence_ratio": 84, "latest_frame": "frame_001"},
        "segmentation": {"mask_confidence": 0.81, "object_count": 1, "defect_area_ratio": 3, "quality_ratio": 90},
        "defect_summary": {"defect_count": 0, "highest_risk": "none", "surface_quality_ratio": 92},
        "pose_estimation": {"pose_confidence": 0.79, "x_mm": 112, "y_mm": 84, "theta_deg": 3.5},
        "confusion_matrix": {"true_positive_count": 18, "false_positive_count": 1, "false_negative_count": 0, "accuracy_ratio": 95},
        "quality_metrics": {"quality_score": 0.88, "coverage_ratio": 93, "inspection_count": 4},
        "evidence_review": {"review_status": "accepted", "artifact_count": 3, "signal_count": 5},
        "handoff_recommendations": {"next_agent": "Manipulation Agent", "handoff_ready": "yes", "confidence_ratio": 86},
    },
    "manipulation": {
        "success_metrics": {"success_ratio": 72, "episode_count": 5, "failed_count": 1, "completion_ratio": 80},
        "grasp_plan": {"grasp_confidence": 0.78, "waypoint_count": 6, "policy": "pi0.5", "target": "UTM fixture"},
        "waypoint_sequence": {"waypoint_count": 6, "duration_s": 24, "risk_ratio": 14, "stage": "pick_place"},
        "motion_execution": {"execution_progress": 68, "latency_ms": 28, "action_clamp_ratio": 70, "status": "active"},
        "robot_workspace": {"workspace_coverage_ratio": 82, "reachability_score": 0.74, "zone_count": 4, "safe_zone_count": 3},
        "reachability_map": {"reachable_ratio": 76, "collision_risk_ratio": 12, "sample_count": 64, "margin_mm": 18},
        "collision_safety": {"safety_ratio": 88, "blocked_count": 0, "guard_count": 4, "status": "pass"},
        "object_pose_handoff": {"pose_confidence": 0.81, "handoff_ready": "yes", "next_agent": "Lab Equipment Agent"},
        "motion_trajectory": {"trajectory_points": 36, "smoothness_score": 0.67, "duration_s": 24, "max_speed_ratio": 55},
        "reaction_timeline": {"event_count": 8, "recovery_count": 1, "completion_ratio": 80, "duration_s": 24},
        "camera_views": {"camera_count": 2, "frame_age_ms": 46, "confidence_ratio": 82, "view": "top+wrist"},
        "key_artifacts": {"policy_path": "outputs/policy", "rollout_log": "runs/rollout.log", "video": "rollout.mp4"},
    },
    "equipment": {
        "equipment_readiness": {"readiness_ratio": 89, "bridge_count": 2, "connected_count": 2, "blocked_count": 0},
        "live_test_status": {"status": "armed", "program_id": "utm_compression", "screen_assertion_count": 4, "progress_ratio": 64},
        "load_displacement_preview": {"peak_force_n": 420, "stiffness_n_per_mm": 38, "sample_count": 512, "quality_ratio": 86},
        "test_recipe": {"recipe": "compression cyclic load", "rate_mm_min": 2, "max_displacement_mm": 8, "cycle_count": 3},
        "sensor_channels": {"channel_count": 4, "active_count": 4, "latency_ms": 18, "dropout_ratio": 0},
        "environmental_conditions": {"temperature_c": 23, "humidity_ratio": 42, "bed_status": "clear", "camera_ok": "yes"},
        "safety_interlocks": {"interlock_count": 5, "passed_count": 5, "risk_ratio": 8, "status": "pass"},
        "event_log": {"event_count": 9, "warning_count": 1, "last_event": "bridge ready"},
        "control_approval": {"approval_ratio": 92, "human_gate": "required_before_live", "handoff_ready": "yes"},
    },
    "analysis": {
        "preprocessing_status": {"quality_ratio": 91, "sample_count": 512, "filtered_count": 498, "status": "pass"},
        "signal_overview": {"peak_force_N": 420, "strength_MPa": 8.6, "energy_absorption_score": 0.71, "quality_ratio": 91},
        "data_quality": {"missing_ratio": 0, "noise_ratio": 6, "valid_sample_ratio": 97, "outlier_count": 3},
        "extracted_features": {"feature_count": 18, "stiffness_n_per_mm": 38, "peak_force_N": 420, "energy_score": 0.71},
        "time_series": {"sample_count": 512, "duration_s": 42, "peak_force_N": 420, "completion_ratio": 100},
        "histogram": {"bin_count": 24, "peak_bin_count": 41, "distribution_score": 0.64, "outlier_ratio": 3},
        "frequency_analysis": {"dominant_hz": 3.2, "spectral_energy_ratio": 76, "noise_ratio": 6, "sample_count": 512},
        "model_output": {"objective_score": 0.71, "prediction_confidence_ratio": 83, "uncertainty": 0.12, "bo_ready": "yes"},
        "confusion_matrix": {"true_positive_count": 18, "false_positive_count": 1, "false_negative_count": 0, "accuracy_ratio": 95},
        "key_insights": {"insight_count": 4, "dominant_factor": "relative_density", "confidence_ratio": 83},
        "anomaly_detection": {"anomaly_count": 1, "risk_ratio": 12, "quality_ratio": 91},
        "artifacts": {"curve": "load_displacement.svg", "report": "analysis.json", "fem_contour": "contour.png"},
        "result_summary": {"bo_handoff": "ready", "objective_score": 0.71, "next_agent": "BO Agent"},
    },
    "bo": {
        "optimization_goal": {"objective_score": 0.71, "direction": "maximize", "target": "specific energy absorption", "constraint_count": 6},
        "iterations": {"iteration_count": 5, "measured_count": 4, "candidate_count": 8, "best_iteration": 4},
        "best_observed": {"best_score": 0.71, "relative_density_ratio": 0.32, "wall_thickness_mm": 0.8, "cell_size_mm": 5},
        "current_regret": {"regret_score": 0.08, "improvement_ratio": 18, "uncertainty": 0.12, "iteration_count": 5},
        "surrogate_model": {"model": "gaussian_process", "r2_score": 0.74, "uncertainty": 0.12, "prior_count": 4},
        "acquisition_function": {"acquisition_value": 0.86, "exploration_ratio": 42, "exploitation_ratio": 58, "selected_candidate": "bo-cand-5"},
        "convergence_history": {"iteration_count": 5, "best_score": 0.71, "previous_score": 0.62, "improvement_ratio": 14},
        "objective_space": {"candidate_count": 8, "valid_count": 6, "density_span_ratio": 42, "score_span": 0.31},
        "stop_continue_recommendation": {"recommendation": "continue", "confidence_ratio": 81, "remaining_budget": 4},
        "acquisition_breakdown": {"acquisition_ratio": 86, "expected_improvement": 0.86, "uncertainty": 0.12, "mean_score": 0.66},
        "parameter_importance": {"relative_density_importance": 0.42, "wall_thickness_importance": 0.31, "cell_size_importance": 0.19, "orientation_importance": 0.08},
        "parallel_coordinates": {"axis_count": 4, "candidate_count": 8, "best_rank": 1, "coverage_ratio": 78},
        "candidate_queue": {"queued_count": 4, "top_candidate": "bo-cand-5", "ready_count": 3, "blocked_count": 0},
        "uncertainty_map": {"uncertainty": 0.12, "max_uncertainty": 0.24, "sample_count": 64, "coverage_ratio": 78},
        "recent_evaluations": {"evaluation_count": 4, "latest_score": 0.71, "failed_count": 0, "quality_ratio": 91},
        "artifacts": {"surrogate_plot": "surrogate.svg", "acquisition_plot": "acquisition.svg", "bo_state": "bo.json"},
    },
}

ROLE_BY_AGENT = {
    "orchestrator": "orchestrator",
    "design": "design_ai",
    "specimen": "specimen_ai",
    "vision": "vision_ai",
    "manipulation": "manipulation_ai",
    "equipment": "equipment_ai",
    "analysis": "analysis_ai",
    "bo": "bo_ai",
}

METADATA_KEY = {
    "orchestrator": "orchestrator_report",
    "design": "design_report",
    "specimen": "specimen_report",
    "vision": "vision_report",
    "manipulation": "manipulation_report",
    "equipment": "equipment_report",
    "analysis": "analysis_report",
    "bo": "bo_report",
}

REGION_FRACTIONS = {
    "topbar": (0.00, 0.00, 1.00, 0.08),
    "left_rail": (0.00, 0.08, 0.13, 0.78),
    "center_report": (0.13, 0.08, 0.69, 0.78),
    "right_chat": (0.69, 0.08, 1.00, 0.78),
    "bottom_dock": (0.00, 0.78, 1.00, 1.00),
}


def selected_agent_pairs(raw_agents: str | None) -> list[tuple[str, str]]:
    if not raw_agents:
        return list(AGENTS)
    wanted = [item.strip() for item in raw_agents.split(",") if item.strip()]
    if not wanted:
        return list(AGENTS)
    by_agent = {agent: reference for agent, reference in AGENTS}
    unknown = [agent for agent in wanted if agent not in by_agent]
    if unknown:
        allowed = ", ".join(agent for agent, _reference in AGENTS)
        raise SystemExit(f"Unknown agent(s): {', '.join(unknown)}. Allowed: {allowed}")
    return [(agent, by_agent[agent]) for agent in wanted]


@dataclass
class ImagePair:
    agent: str
    reference_path: Path
    current_path: Path
    reference: Image.Image
    current: Image.Image


def rgb_hex(image: Image.Image) -> str:
    mean = ImageStat.Stat(image.convert("RGB")).mean
    return "#%02x%02x%02x" % tuple(round(value) for value in mean)


def mae(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    return round(sum(ImageStat.Stat(diff).mean) / 3, 3)


def region_box(size: tuple[int, int], frac: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    width, height = size
    x0, y0, x1, y1 = frac
    return (int(width * x0), int(height * y0), int(width * x1), int(height * y1))


def center_edge_signature(image: Image.Image) -> dict[str, Any]:
    if np is None or sobel is None:
        raise RuntimeError(f"numpy/scipy unavailable: {IMPORT_ERROR}")
    gray = np.asarray(image.convert("L"), dtype=float)
    box = region_box(image.size, REGION_FRACTIONS["center_report"])
    crop = gray[box[1] : box[3], box[0] : box[2]]
    gx = np.abs(sobel(crop, axis=1))
    gy = np.abs(sobel(crop, axis=0))
    vertical = gx.mean(axis=0)
    horizontal = gy.mean(axis=1)

    def peaks(arr: Any, *, min_dist: int, limit: int) -> list[int]:
        order = np.argsort(arr)[::-1]
        out: list[int] = []
        threshold = float(arr.mean() + arr.std() * 1.15)
        for raw_idx in order:
            idx = int(raw_idx)
            if float(arr[idx]) < threshold:
                break
            if all(abs(idx - existing) >= min_dist for existing in out):
                out.append(idx)
            if len(out) >= limit:
                break
        return sorted(out)

    return {
        "center_box": list(box),
        "vertical_peaks_x": peaks(vertical, min_dist=18, limit=18),
        "horizontal_peaks_y": peaks(horizontal, min_dist=16, limit=18),
        "mean_gray": round(float(crop.mean()), 3),
        "std_gray": round(float(crop.std()), 3),
    }


def region_metrics(pair: ImagePair) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for name, frac in REGION_FRACTIONS.items():
        box = region_box(pair.reference.size, frac)
        ref_crop = pair.reference.crop(box)
        cur_crop = pair.current.crop(box)
        metrics[name] = {
            "box": list(box),
            "mae": mae(ref_crop, cur_crop),
            "reference_mean": rgb_hex(ref_crop),
            "current_mean": rgb_hex(cur_crop),
        }
    return metrics


def session_for_agent(agent: str) -> dict[str, Any]:
    metadata_key = METADATA_KEY[agent]
    return {
        "planning_session_id": f"layout-audit-{agent}",
        "messages": [
            {
                "role": ROLE_BY_AGENT[agent],
                "content": f"{agent} reference layout audit sample evidence.",
                "timestamp": "2026-06-01T00:00:00Z",
            }
        ],
        "state": {
            "run_id": f"run-layout-audit-{agent}",
            "mode": "test",
            "stage": agent,
            "experiment_id": "exp-layout-audit",
            "run_metadata": {metadata_key: {"sections": SAMPLE_SECTIONS[agent]}},
        },
    }


def capture_agent(driver: WebDriverAudit, base_url: str, agent: str, out_dir: Path) -> dict[str, Any]:
    driver.open(f"{base_url.rstrip('/')}/live", wait_s=1.1)
    session = session_for_agent(agent)
    driver.js(
        """
        window.__liveGuiDebugSetState({session: arguments[0], events: [], artifacts: [], approvals: {approvals: [], pending: [], resolved: []}});
        window.__liveGuiDebugRestoreOperatorReportState(arguments[1], 'report');
        return true;
        """,
        [session, agent],
    )
    time.sleep(0.35)
    shot = out_dir / f"current_{agent}.png"
    driver.screenshot(shot)
    dom = driver.js(
        """
        const cards = Array.from(document.querySelectorAll('.live-agent-reference-workboard.live-generated-fullscreen-grid .live-agent-ref-card')).map((el) => {
          const r = el.getBoundingClientRect();
          const visual = el.querySelector('.live-agent-ref-visual:not(.visual-empty)');
          return {
            title: (el.querySelector('h4')?.textContent || '').trim(),
            x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
            visual: Boolean(visual), visualClass: visual ? visual.className : '',
          };
        });
        const center = document.querySelector('.live-center-panel')?.getBoundingClientRect();
        const workboard = document.querySelector('.live-agent-reference-workboard')?.getBoundingClientRect();
        return {
          bodyAgent: document.body.dataset.liveAgent || '',
          chatTarget: document.querySelector('#live-chat-target')?.value || '',
          viewport: [window.innerWidth, window.innerHeight],
          bodyOverflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
          center: center ? {x: Math.round(center.x), y: Math.round(center.y), w: Math.round(center.width), h: Math.round(center.height)} : null,
          workboard: workboard ? {x: Math.round(workboard.x), y: Math.round(workboard.y), w: Math.round(workboard.width), h: Math.round(workboard.height)} : null,
          cardCount: cards.length,
          visualCount: cards.filter((card) => card.visual).length,
          cards,
        };
        """
    )
    return {"screenshot": str(shot), "dom": dom}


def analyze_pair(agent: str, reference_file: str, current_path: Path) -> dict[str, Any]:
    ref_path = REFERENCE_DIR / reference_file
    reference = Image.open(ref_path).convert("RGB")
    current_original = Image.open(current_path).convert("RGB")
    current = current_original.resize(reference.size, Image.LANCZOS)
    pair = ImagePair(agent, ref_path, current_path, reference, current)
    diff = ImageChops.difference(reference, current)
    diff_path = current_path.parent / f"{agent}_reference_current_diff.png"
    diff.save(diff_path)
    contact_path = current_path.parent / f"{agent}_layout_contact_sheet.png"
    make_contact_sheet(reference, current_original, diff, contact_path)
    return {
        "agent": agent,
        "reference": str(ref_path.relative_to(ROOT)),
        "current": str(current_path.relative_to(ROOT)),
        "diff": str(diff_path.relative_to(ROOT)),
        "contact_sheet": str(contact_path.relative_to(ROOT)),
        "reference_size": list(reference.size),
        "current_size": list(current_original.size),
        "diff_mae": mae(reference, current),
        "reference_mean": rgb_hex(reference),
        "current_mean": rgb_hex(current),
        "regions": region_metrics(pair),
        "reference_center_signature": center_edge_signature(reference),
        "current_center_signature": center_edge_signature(current),
    }


def make_contact_sheet(reference: Image.Image, current: Image.Image, diff: Image.Image, out_path: Path) -> None:
    thumbs = []
    for label, image in [("REFERENCE", reference), ("CURRENT", current), ("DIFF", diff)]:
        thumb = image.convert("RGB")
        thumb.thumbnail((620, 350), Image.LANCZOS)
        canvas = Image.new("RGB", (640, 390), (12, 18, 28))
        canvas.paste(thumb, ((640 - thumb.width) // 2, 34))
        draw = ImageDraw.Draw(canvas)
        draw.text((16, 10), label, fill=(230, 238, 250))
        thumbs.append(canvas)
    sheet = Image.new("RGB", (640 * 3, 390), (8, 12, 18))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, (640 * index, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def write_markdown(results: list[dict[str, Any]], out_path: Path) -> None:
    lines = [
        "# Live GUI Agent Reference Layout Audit",
        "",
        "This report is layout-first. Card/visual counts are secondary and are not sufficient for passing the reference goal.",
        "",
        "| Agent | Diff MAE | Worst region | Center ref peaks X/Y | Center current peaks X/Y | Contact sheet |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for result in results:
        regions = result["regions"]
        worst_name, worst_data = max(regions.items(), key=lambda item: item[1]["mae"])
        ref_sig = result["reference_center_signature"]
        cur_sig = result["current_center_signature"]
        lines.append(
            f"| {result['agent']} | {result['diff_mae']:.3f} | {worst_name} {worst_data['mae']:.3f} | "
            f"{ref_sig['vertical_peaks_x'][:6]} / {ref_sig['horizontal_peaks_y'][:6]} | "
            f"{cur_sig['vertical_peaks_x'][:6]} / {cur_sig['horizontal_peaks_y'][:6]} | `{result['contact_sheet']}` |"
        )
    lines.append("")
    lines.append("## Follow-Up Discipline")
    lines.append("")
    lines.append("Future changes must preserve layout geometry, overflow safety, and visual dominance; card-count or section-count matches alone are not acceptance criteria.")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--webdriver-url", default="http://127.0.0.1:4448")
    parser.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    parser.add_argument("--capture", action="store_true", help="Capture fresh browser screenshots before analysis")
    parser.add_argument("--agents", default="", help="Comma-separated subset of agents to audit, e.g. vision,analysis,bo")
    args = parser.parse_args()
    agent_pairs = selected_agent_pairs(args.agents)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    capture_data: dict[str, Any] = {}
    if args.capture:
        driver = WebDriverAudit(args.webdriver_url, width=1920, height=1080)
        driver.start()
        try:
            for agent, _reference in agent_pairs:
                agent_dir = out_dir / f"agent_{agent}"
                agent_dir.mkdir(parents=True, exist_ok=True)
                capture_data[agent] = capture_agent(driver, args.base_url, agent, agent_dir)
        finally:
            driver.stop()

    results: list[dict[str, Any]] = []
    for agent, reference_file in agent_pairs:
        if args.capture:
            current_path = Path(capture_data[agent]["screenshot"]).resolve()
        else:
            current_path = (ROOT / f"artifacts/live_gui_upgrade/agent_pass_{agent}/current_{agent}.png").resolve()
        agent_result = analyze_pair(agent, reference_file, current_path)
        if args.capture:
            agent_result["dom"] = capture_data[agent]["dom"]
        results.append(agent_result)

    summary = {"layout_geometry_agent_passes": results}
    summary_path = out_dir / "agent_reference_layout_geometry_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(results, out_dir / "agent_reference_layout_geometry_summary.md")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
