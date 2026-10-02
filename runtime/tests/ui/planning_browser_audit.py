#!/usr/bin/env python3
"""Browser-level Live GUI planning renderer audit.

This script verifies the frontend rendering contract for planning chat payloads
that are difficult to prove from backend unit tests alone:
- analysis_ai messages with fem_artifacts render a CAE/FEM contour card
- bo_ai messages with bo_result.benchmark.*.surrogate_trace render BO SVG plots
- the chat viewport scrolls to the newest rendered message

It expects:
- FastAPI server running, default http://127.0.0.1:7860
- geckodriver running, default http://127.0.0.1:4448
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from runtime_ide_browser_audit import WebDriverAudit  # noqa: E402


def sample_planning_messages() -> list[dict[str, Any]]:
    """Return minimal plot-ready Live GUI messages matching backend payloads."""
    trace = {
        "step": 1,
        "acquisition": "expected_improvement",
        "candidate_count": 5,
        "evaluated_points": [
            {"x": 1, "candidate_id": "prev-1", "score": 0.42, "parameters": {"relative_density": 0.28, "cell_size_mm": 5.0}},
            {"x": 3, "candidate_id": "prev-2", "score": 0.57, "parameters": {"relative_density": 0.32, "cell_size_mm": 5.0}},
        ],
        "selected": {
            "x": 4,
            "candidate_id": "bo-cand-4",
            "score": 0.64,
            "acquisition_value": 0.91,
            "parameters": {
                "geometry_type": "gyroid",
                "relative_density": 0.34,
                "wall_thickness_mm": 1.25,
                "cell_size_mm": 5.0,
                "orientation_deg": 0,
            },
        },
        "candidates": [
            {"x": 1, "candidate_id": "cand-1", "surrogate_mean": 0.41, "uncertainty": 0.06, "acquisition_value": 0.22},
            {"x": 2, "candidate_id": "cand-2", "surrogate_mean": 0.48, "uncertainty": 0.08, "acquisition_value": 0.37},
            {"x": 3, "candidate_id": "cand-3", "surrogate_mean": 0.55, "uncertainty": 0.05, "acquisition_value": 0.52},
            {"x": 4, "candidate_id": "bo-cand-4", "surrogate_mean": 0.62, "uncertainty": 0.11, "acquisition_value": 0.91},
            {"x": 5, "candidate_id": "cand-5", "surrogate_mean": 0.58, "uncertainty": 0.07, "acquisition_value": 0.63},
        ],
    }
    return [
        {
            "role": "analysis_ai",
            "content": "CAE Agent completed deterministic closed-loop analysis.",
            "fem_artifacts": {
                "contour_url": "/api/planning/artifacts/run-ui-audit/specimen-ui/fem_contour.svg",
                "report_url": "/api/planning/artifacts/run-ui-audit/specimen-ui/cae_report.json",
            },
            "experiment_spec": {"specimen_id": "specimen-ui", "geometry_type": "gyroid"},
        },
        {
            "role": "bo_ai",
            "content": "BO Agent recommended the next printable gyroid candidate.",
            "bo_result": {
                "strategy": "mbo",
                "acquisition": "expected_improvement",
                "budget": 5,
                "recommendation": {
                    "candidate_id": "bo-cand-4",
                    "objective_score": 0.64,
                    "parameters": trace["selected"]["parameters"],
                },
                "benchmark": {"strategies": {"bo": {"surrogate_trace": [trace]}}},
                "knowledge_context": {"memory_summary": "cell_size_mm locked at 5 mm for FDM-printable test loop"},
            },
        },
    ]


def scenario_live_planning_render(audit: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    audit.open(f"{base_url.rstrip('/')}/live", wait_s=2.0)
    rendered = audit.js(
        """
        try {
          if (typeof renderPlanningMessages !== 'function') {
            return {ok: false, error: 'renderPlanningMessages is not available'};
          }
          renderPlanningMessages(arguments[0]);
          const log = document.querySelector('#planning-chat-log');
          const boCard = document.querySelector('.bo-live-card');
          const boToggle = document.querySelector('.bo-graph-toggle');
          const collapsedBefore = document.querySelectorAll('.bo-plot-collapsed').length;
          const boSvgBefore = document.querySelectorAll('.bo-trace-svg').length;
          const selectedRowsBefore = document.querySelectorAll('.bo-selected-row').length;
          if (boToggle) boToggle.click();
          const boSvgAfter = document.querySelectorAll('.bo-trace-svg').length;
          const selectedRowsAfter = document.querySelectorAll('.bo-selected-row').length;
          const femCard = document.querySelector('.fem-contour-card');
          const femImg = document.querySelector('.fem-contour-preview');
          const atBottom = log ? (log.scrollTop + log.clientHeight >= log.scrollHeight - 4) : false;
          return {
            ok: true,
            boSvgCount: boSvgAfter,
            boSvgBefore,
            boCard: Boolean(boCard),
            boToggle: Boolean(boToggle),
            collapsedBefore,
            femCard: Boolean(femCard),
            femSrc: femImg ? femImg.getAttribute('src') : '',
            selectedRows: selectedRowsAfter,
            selectedRowsBefore,
            atBottom,
            text: log ? (log.innerText || log.textContent || '') : '',
            textContent: log ? (log.textContent || '') : '',
            boText: boCard ? (boCard.textContent || '') : '',
            femText: femCard ? (femCard.textContent || '') : '',
          };
        } catch (err) {
          return {ok: false, error: String(err && err.message ? err.message : err)};
        }
        """,
        [sample_planning_messages()],
    )
    if not rendered.get("ok"):
        raise AssertionError(rendered.get("error") or "planning render failed")
    if rendered.get("boSvgBefore") != 0 or rendered.get("collapsedBefore") < 1 or not rendered.get("boToggle"):
        raise AssertionError(f"BO plot did not start collapsed: {rendered}")
    if rendered.get("boSvgCount") != 1 or not rendered.get("boCard"):
        raise AssertionError(f"BO plot did not render after toggle: {rendered}")
    if not rendered.get("femCard") or not str(rendered.get("femSrc", "")).startswith("/api/planning/artifacts/"):
        raise AssertionError(f"FEM contour card did not render: {rendered}")
    if rendered.get("selectedRowsBefore") != 0:
        raise AssertionError(f"BO selected rows rendered while collapsed: {rendered}")
    if rendered.get("selectedRows") < 1:
        raise AssertionError(f"BO selected candidate rows missing after toggle: {rendered}")
    bo_text = "\n".join(str(rendered.get(key, "")) for key in ("text", "textContent", "boText"))
    fem_text = "\n".join(str(rendered.get(key, "")) for key in ("text", "textContent", "femText"))
    if "bo surrogate / acquisition trace" not in bo_text.lower():
        raise AssertionError("BO trace title missing from chat text")
    if "fem / cae contour" not in fem_text.lower():
        raise AssertionError("FEM contour title missing from chat text")
    audit.screenshot(out_dir / "planning_browser_audit_live_artifacts.png")
    return rendered


def scenario_vision_pose_gate_render(audit: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    audit.open(f"{base_url.rstrip('/')}/live", wait_s=2.0)
    rendered = audit.js(
        """
        try {
          if (typeof renderVisionDashboardCards !== 'function') {
            return {ok: false, error: 'renderVisionDashboardCards is not available'};
          }
          const report = {
            state: {
              run_id: 'run-vision-pose-audit',
              run_metadata: {
                vision_agent_report: {
                  specimen_pose: {
                    schema: 'specimen_pose.v1',
                    specimen_id: 'specimen-audit',
                    workspace: 'a4_robot_workspace',
                    port_released: true,
                    vla_camera_precheck_ok: true,
                    confidence: 0.93,
                    position_robot_base_mm: {x: 11, y: 22, z: 33},
                  },
                  transfer_readiness: {
                    ready: true,
                    camera_returned_to_vla: true,
                    vla_camera_precheck_ok: true,
                  },
                },
                vision_report: {
                  specimen_pose: {
                    schema: 'specimen_pose.v1',
                    confidence: 0.93,
                    port_released: true,
                    vla_camera_precheck_ok: true,
                    position_robot_base_mm: {x: 11, y: 22, z: 33},
                  },
                  transfer_readiness: {
                    ready: true,
                    camera_returned_to_vla: true,
                    vla_camera_precheck_ok: true,
                  },
                },
              },
            },
          };
          const host = document.createElement('div');
          host.id = 'vision-pose-gate-audit-host';
          host.innerHTML = renderVisionDashboardCards(report, 'ready', 'Vision Agent', {});
          document.body.appendChild(host);
          const cards = Array.from(host.querySelectorAll('.ar-report-card'));
          const card = cards.find((item) => (item.textContent || '').includes('D455F Pose / VLA Return'));
          const text = card ? (card.textContent || '') : '';
          return {
            ok: Boolean(card),
            cardCount: cards.length,
            hasGrid: Boolean(card && card.querySelector('.vision-pose-gate-grid')),
            text,
            hasReturned: text.includes('returned'),
            hasReady: text.includes('ready'),
            hasConfidence: text.includes('0.93'),
            hasRobotBase: text.includes('x 11') && text.includes('y 22'),
          };
        } catch (err) {
          return {ok: false, error: String(err && err.message ? err.message : err)};
        }
        """,
        [],
    )
    if not rendered.get("ok"):
        raise AssertionError(rendered.get("error") or f"D455F Vision card did not render: {rendered}")
    for key in ("hasGrid", "hasReturned", "hasReady", "hasConfidence", "hasRobotBase"):
        if not rendered.get(key):
            raise AssertionError(f"D455F Vision card missing {key}: {rendered}")
    audit.screenshot(out_dir / "planning_browser_audit_vision_pose_gate.png")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--webdriver-url", default="http://127.0.0.1:4448")
    parser.add_argument("--out-dir", default="artifacts/ui")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1100)
    args = parser.parse_args()

    audit = WebDriverAudit(args.webdriver_url, width=args.width, height=args.height)
    try:
        audit.start()
        result = scenario_live_planning_render(audit, args.base_url, Path(args.out_dir))
        vision_result = scenario_vision_pose_gate_render(audit, args.base_url, Path(args.out_dir))
        print("planning_browser_audit: PASS")
        print({k: v for k, v in result.items() if k != "text"})
        print({k: v for k, v in vision_result.items() if k != "text"})
        return 0
    finally:
        time.sleep(0.1)
        audit.stop()


if __name__ == "__main__":
    raise SystemExit(main())
