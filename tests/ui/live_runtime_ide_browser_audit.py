#!/usr/bin/env python3
"""Browser-level audit for the Live GUI Runtime IDE shell.

It verifies the upgraded `/live` surface beyond static template checks:
- all operational panels are visible in Firefox
- Agentic Binder renders all expected agents
- report/backend/artifact/timeline view tabs switch visible panels
- binder click and double-click change selected agent/view context
- bottom timeline and device strip are populated from injected runtime state

It expects:
- FastAPI server running, default http://127.0.0.1:7862
- geckodriver running, default http://127.0.0.1:4448
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from runtime_ide_browser_audit import WebDriverAudit, http_json  # noqa: E402


REPO_ROOT = THIS_DIR.parents[1]
LIVE_REFERENCE_IMAGE = REPO_ROOT / "docs/ATR_Live_GUI_Graph_Package/assets/reference/main_live_gui_reference.png"
LIVE_AUDIT_DRAFT_MODULE_ID = "ui_audit_draft_descriptor"


def cleanup_live_audit_draft_module() -> None:
    shutil.rmtree(REPO_ROOT / "graphs/modules" / LIVE_AUDIT_DRAFT_MODULE_ID, ignore_errors=True)
    shutil.rmtree(REPO_ROOT / "memory/module_versions" / LIVE_AUDIT_DRAFT_MODULE_ID, ignore_errors=True)


def image_visual_metrics(path: Path) -> dict[str, Any]:
    """Return coarse visual metrics used to keep Live GUI aligned with reference assets."""
    image = Image.open(path).convert("RGB")
    stat = ImageStat.Stat(image)
    width, height = image.size
    pixel_iter = image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()
    pixels = list(pixel_iter)
    bright_pixels = sum(1 for red, green, blue in pixels if red > 220 and green > 220 and blue > 220)
    mean_rgb = tuple(round(channel, 2) for channel in stat.mean)
    return {
        "path": str(path),
        "width": width,
        "height": height,
        "mean_rgb": mean_rgb,
        "bright_ratio": round(bright_pixels / max(len(pixels), 1), 5),
    }


def rgb_distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return round(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)) ** 0.5, 3)


def sample_payload(run_id: str = "run-ui-audit", approval_id: str = "approval-ui") -> dict[str, Any]:
    trace = {
        "step": 1,
        "acquisition": "expected_improvement",
        "candidate_count": 3,
        "evaluated_points": [{"x": 1, "candidate_id": "prev", "score": 0.4}],
        "selected": {
            "x": 2,
            "candidate_id": "cand-2",
            "score": 0.7,
            "acquisition_value": 0.9,
            "parameters": {"relative_density": 0.35},
        },
        "candidates": [
            {"x": 1, "surrogate_mean": 0.4, "uncertainty": 0.04, "acquisition_value": 0.2},
            {"x": 2, "surrogate_mean": 0.7, "uncertainty": 0.08, "acquisition_value": 0.9},
            {"x": 3, "surrogate_mean": 0.5, "uncertainty": 0.05, "acquisition_value": 0.4},
        ],
    }
    return {
        "session": {
            "messages": [
                {"role": "orchestrator", "content": "실험 목표와 필수 입력값을 확인했습니다.", "timestamp": "2026-05-26T09:00:00Z", "model": "gemma4:31b", "token_usage": {"prompt_tokens": 1800, "completion_tokens": 450, "total_tokens": 2250}},
                {
                    "role": "design_ai",
                    "content": "Design Agent selected printable gyroid TPMS specimen.",
                    "timestamp": "2026-05-26T09:00:04Z",
                    "model": "design_agent",
                    "experiment_spec": {"specimen_id": "spec-ui", "geometry_type": "gyroid_tpms", "specimen_size_mm": [30, 30, 30]},
                    "artifacts": {
                        "preview_url": "",
                        "experiment_spec_url": "/api/planning/artifacts/run-ui/spec-ui/experiment_spec.json",
                    },
                },
                {
                    "role": "analysis_ai",
                    "content": "Analysis Agent produced FEM contour and objective score.",
                    "timestamp": "2026-05-26T09:00:12Z",
                    "fem_artifacts": {
                        "contour_url": "",
                        "report_url": "/api/planning/artifacts/run-ui/spec-ui/cae_report.json",
                    },
                },
                {
                    "role": "bo_ai",
                    "content": "BO Agent updated the acquisition trace.",
                    "timestamp": "2026-05-26T09:00:16Z",
                    "bo_result": {
                        "strategy": "bo",
                        "acquisition": "expected_improvement",
                        "budget": 5,
                        "recommendation": {"candidate_id": "cand-2", "objective_score": 0.7},
                        "benchmark": {"strategies": {"bo": {"surrogate_trace": [trace]}}},
                    },
                },
            ],
            "state": {
                "run_id": run_id,
                "experiment_id": "exp-ui-audit",
                "mode": "live",
                "stage": "design",
                "active_goal": "Browser audit live workflow",
                "current_experiment_spec": {"specimen_id": "spec-ui", "geometry_type": "gyroid_tpms", "specimen_size_mm": [30, 30, 30]},
                "run_metadata": {},
            },
            "runtime": {"backend": {"name": "vllm", "label": "NemoClaw/vLLM"}},
            "is_running": True,
            "planning_session_id": "session-ui-audit",
        },
        "snapshot": {
            "system_resources": {
                "gpu": {"status": "ready", "aggregate": {"memory_used_gb": 12, "memory_total_gb": 48, "utilization_percent": 21}},
                "ram": {"status": "ready", "used_gb": 18, "total_gb": 128, "used_percent": 14},
            }
        },
        "events": [
            {
                "event_id": "evt-orchestrator-1",
                "trace_id": "trace-orchestrator-1",
                "event_type": "agent_started",
                "level": "INFO",
                "node_id": "orchestrator",
                "message": "Orchestrator planned the next handoff",
                "ts": "2026-05-26T09:00:02Z",
                "payload": {
                    "node_id": "orchestrator",
                    "model": "gemma4:31b",
                    "handler": "agents.orchestrator.run",
                    "raw_prompt": "Plan the next ATR closed-loop step from the current objective.",
                    "raw_response": "Proceed to Design Agent with a gyroid TPMS candidate.",
                    "tool_calls": [{"name": "handoff.design", "arguments": {"geometry_type": "gyroid_tpms"}}],
                    "input": {"objective": "Browser audit live workflow"},
                    "output": {"next_stage": "design"},
                    "logs": ["validated required fields", "handoff created"],
                },
            },
            {"event_type": "agent_started", "level": "INFO", "node_id": "design", "message": "Design started", "ts": "2026-05-26T09:00:04Z", "payload": {"node_id": "design"}},
            {"event_type": "tool_call_completed", "level": "INFO", "node_id": "specimen", "message": "Prusa slicer tool created gcode artifact", "ts": "2026-05-26T09:00:08Z", "payload": {"node_id": "specimen", "tool_calls": [{"name": "printer.prepare"}]}},
            {"event_type": "handoff_created", "level": "INFO", "node_id": "specimen", "message": "Handoff to Analysis Agent", "ts": "2026-05-26T09:00:10Z", "payload": {"node_id": "specimen"}},
            {"event_type": "agent_completed", "level": "INFO", "node_id": "analysis", "message": "Analysis completed", "ts": "2026-05-26T09:00:12Z", "payload": {"node_id": "analysis"}},
            {"event_id": "evt-agent-question-1", "trace_id": "trace-question-1", "event_type": "agent_question", "level": "WARNING", "node_id": "specimen", "message": "Specimen Agent needs bridge mode before print preparation", "ts": "2026-05-26T09:00:14Z", "payload": {"stage": "specimen", "title": "Specimen bridge mode required", "question": "가상 브릿지, 설치 프린터, 실제 출력 중 어떤 방식으로 진행할까요?", "missing_fields": ["bridge_mode"]}},
            {"event_id": "evt-printer-error-1", "trace_id": "trace-printer-error-1", "event_type": "device.error", "level": "ERROR", "node_id": "", "message": "PrusaLink upload failed during live print preparation", "ts": "2026-05-26T09:00:16Z", "payload": {"device": "printer", "tool": "printer.prepare", "failure_code": "PRINTER_UPLOAD_FAILED", "status": "failed", "message": "PrusaLink upload failed"}},
            {"event_id": "evt-approval-1", "trace_id": "trace-approval-1", "event_type": "approval.requested", "level": "WARNING", "node_id": "guardian", "message": "Operator approval required", "ts": "2026-05-26T09:00:18Z", "payload": {"stage": "guardian", "requires_human_approval": True}},
        ],
        "graph": {
            "ok": True,
            "graph": {
                "id": "atr_closed_loop",
                "version": "ui-audit",
                "entry_node": "orchestrator",
                "nodes": [
                    {"id": "orchestrator", "label": "Orchestrator", "stage": "orchestrator", "handler": "agents.orchestrator.run", "position": {"x": 220, "y": 180}},
                    {"id": "design", "label": "Design Agent", "stage": "design", "handler": "agents.design.run", "position": {"x": 760, "y": 180}},
                    {"id": "specimen", "label": "Specimen Agent", "stage": "specimen", "handler": "agents.specimen.run", "position": {"x": 1300, "y": 180}},
                    {"id": "guardian", "label": "Guardian", "stage": "guardian", "handler": "agents.guardian.run", "position": {"x": 1300, "y": 620}, "kind": "terminal"}
                ],
                "edges": [
                    {"source": "orchestrator", "target": "design", "label": "handoff", "metadata": {"runtime_edge": "logical_transition"}},
                    {"source": "design", "target": "specimen", "label": "handoff", "metadata": {"runtime_edge": "logical_transition"}},
                    {"source": "specimen", "target": "guardian", "label": "safety", "metadata": {"runtime_edge": "logical_transition"}}
                ],
            },
        },
        "artifacts": [
            {
                "name": "experiment_spec.json",
                "path": "spec-ui/experiment_spec.json",
                "size_bytes": 512,
                "preview_kind": "text",
                "url": f"/api/runs/{run_id}/artifact-file/spec-ui/experiment_spec.json",
                "download_url": f"/api/runs/{run_id}/artifact-file/spec-ui/experiment_spec.json?download=1",
            }
        ],
        "approvals": {"pending": [{"approval_id": approval_id, "title": "Guardian approval", "reason": "live hardware step", "stage": "guardian"}], "approvals": [], "resolved": []},
    }


def scenario_live_runtime_ide(audit: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    cleanup_live_audit_draft_module()
    draft_created = http_json(
        base_url,
        "/api/modules/templates/agent",
        method="POST",
        payload={
            "module_id": LIVE_AUDIT_DRAFT_MODULE_ID,
            "label": "UI Audit Draft Descriptor",
            "category": "custom",
            "author": "browser-audit",
        },
        timeout_s=10.0,
    )
    if not draft_created.get("ok"):
        raise AssertionError(f"Failed to create Live GUI draft module fixture: {draft_created}")
    draft_ui = http_json(
        base_url,
        f"/api/modules/{LIVE_AUDIT_DRAFT_MODULE_ID}/ui",
        method="PUT",
        payload={
            "ui": {
                "short": "UAD",
                "report_title": "UI Audit Draft Descriptor",
                "chat": {"mode": "open_on_demand"},
                "cards": [
                    {
                        "id": "audit_draft_card",
                        "title": "Audit Draft Card",
                        "selectors": {"status": "metadata.status"},
                    }
                ],
                "report_sections": [
                    {
                        "id": "audit_draft_section",
                        "title": "Audit Draft Section",
                        "selectors": {"status": "metadata.status"},
                    }
                ],
            },
            "reason": "live-runtime-browser-audit",
            "author": "browser-audit",
        },
        timeout_s=10.0,
    )
    if not draft_ui.get("ok"):
        raise AssertionError(f"Failed to save Live GUI draft UI fixture: {draft_ui}")

    state_payload = http_json(base_url, "/api/state", timeout_s=10.0)
    current_state = state_payload.get("state") if isinstance(state_payload.get("state"), dict) else {}
    run_id = str(current_state.get("run_id") or "run-ui-audit")
    approval = http_json(
        base_url,
        f"/api/runs/{run_id}/approvals",
        method="POST",
        payload={
            "title": "Live GUI browser audit approval",
            "reason": "Verify approve button calls the runtime approval endpoint",
            "stage": "guardian",
            "safety_class": "browser_audit",
            "requester": "live_runtime_ide_browser_audit",
        },
        timeout_s=10.0,
    )
    approval_id = str(approval.get("approval_id") or "approval-ui")

    audit.open(f"{base_url.rstrip('/')}/", wait_s=0.5)
    audit.js("""
      try {
        localStorage.removeItem('autonomousLiveGuiUiState');
        localStorage.removeItem('autonomousLivePlanningSessionId');
        sessionStorage.removeItem('autonomousLiveGuiUiState');
        sessionStorage.removeItem('autonomousLivePlanningSessionId');
      } catch (err) {}
      return true;
    """)
    audit.open(f"{base_url.rstrip('/')}/live", wait_s=4.0)
    result = audit.js(
        r"""
        try {
          const payload = arguments[0];
          if (typeof window.__liveGuiDebugSetState !== 'function') {
            return {ok: false, error: '__liveGuiDebugSetState is not available'};
          }
          window.__liveGuiDebugSetState(payload);

          function visible(id) {
            const el = document.getElementById(id);
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
          }
          function activePanel() {
            const el = document.querySelector('.live-center-view.active');
            return el ? el.id : '';
          }
          function click(selector) {
            const el = document.querySelector(selector);
            if (!el) return false;
            el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
            return true;
          }
          function ctrlclick(selector) {
            const el = document.querySelector(selector);
            if (!el) return false;
            el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window, ctrlKey: true}));
            return true;
          }
          function dblclick(selector) {
            const el = document.querySelector(selector);
            if (!el) return false;
            el.dispatchEvent(new MouseEvent('dblclick', {bubbles: true, cancelable: true, view: window}));
            return true;
          }
          function rightclick(selector) {
            const el = document.querySelector(selector);
            if (!el) return false;
            el.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true, view: window, clientX: 120, clientY: 160, button: 2}));
            return true;
          }
          function rect(selector) {
            const el = document.querySelector(selector);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height), right: Math.round(r.right), bottom: Math.round(r.bottom)};
          }
          function rgbNumbers(cssColor) {
            const nums = String(cssColor || '').match(/[0-9.]+/g) || [];
            return nums.slice(0, 3).map((value) => Number(value));
          }
          function luminance(rgb) {
            const [r, g, b] = (rgb || [0, 0, 0]).map((value) => {
              const c = Number(value) / 255;
              return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
            });
            return 0.2126 * r + 0.7152 * g + 0.0722 * b;
          }
          function contrastRatio(fg, bg) {
            const l1 = luminance(fg);
            const l2 = luminance(bg);
            const high = Math.max(l1, l2);
            const low = Math.min(l1, l2);
            return Math.round(((high + 0.05) / (low + 0.05)) * 100) / 100;
          }

          const adoptedSessionId = window.localStorage.getItem('autonomousLivePlanningSessionId') || window.sessionStorage.getItem('autonomousLivePlanningSessionId') || '';
          const bodyStyle = getComputedStyle(document.body);
          const panelStyle = getComputedStyle(document.querySelector('.live-center-panel'));
          const titleStyle = getComputedStyle(document.querySelector('.live-runtime-title h1'));
          const headerElement = document.querySelector('.live-runtime-header');
          const headerBefore = headerElement ? getComputedStyle(headerElement, '::before') : null;
          const headerAfter = headerElement ? getComputedStyle(headerElement, '::after') : null;
          const titleEyebrow = document.querySelector('.live-runtime-title .eyebrow');
          const titleRect = rect('.live-runtime-title');
          const titleH1Rect = rect('.live-runtime-title h1');
          const metricRects = Array.from(document.querySelectorAll('.live-runtime-metrics > *')).map((el) => {
            const itemRect = el.getBoundingClientRect();
            return {id: el.id || el.className || el.tagName, top: Math.round(itemRect.top), bottom: Math.round(itemRect.bottom), left: Math.round(itemRect.left), right: Math.round(itemRect.right), width: Math.round(itemRect.width)};
          });
          const metricRowTops = [];
          metricRects.map((item) => item.top).sort((a, b) => a - b).forEach((top) => {
            if (!metricRowTops.some((existing) => Math.abs(existing - top) <= 2)) metricRowTops.push(top);
          });
          const visual = {
            bodyClass: document.body.className,
            binderRect: rect('.live-agent-binder'),
            centerRect: rect('.live-center-panel'),
            chatRect: rect('.live-chat-panel'),
            bottomRect: rect('.live-runtime-bottom'),
            headerRect: rect('.live-runtime-header'),
            titleRect,
            titleH1Rect,
            titleEyebrowVisible: Boolean(titleEyebrow && getComputedStyle(titleEyebrow).display !== 'none' && titleEyebrow.getBoundingClientRect().height > 0),
            headerBeforeDisplay: headerBefore ? headerBefore.display : '',
            headerAfterDisplay: headerAfter ? headerAfter.display : '',
            headerMetricRows: metricRowTops.length,
            metricRects,
            safeStopRect: rect('#btn-live-safe-stop'),
            panelBg: panelStyle.backgroundColor,
            panelBorder: panelStyle.borderColor,
            titleColor: titleStyle.color,
            bodyTextColor: bodyStyle.color,
            bodyBgColor: bodyStyle.backgroundColor,
            titleContrastOnPanel: contrastRatio(rgbNumbers(titleStyle.color), rgbNumbers(panelStyle.backgroundColor)),
          };
          const tooltipProbe = document.querySelector('#live-quick-actions .live-quick-action[data-quick-action="dry_run"]');
          if (tooltipProbe) {
            tooltipProbe.dispatchEvent(new MouseEvent('mouseover', {bubbles: true, clientX: 100, clientY: 100}));
          }
          const hoverTooltip = document.getElementById('live-hover-tooltip');
          const hoverTooltipRect = hoverTooltip ? hoverTooltip.getBoundingClientRect() : {width: 0, height: 0};
          const compactTooltip = {
            exists: Boolean(hoverTooltip),
            visible: Boolean(hoverTooltip && !hoverTooltip.hidden && hoverTooltip.textContent.includes('Dry Run')),
            text: hoverTooltip ? hoverTooltip.textContent : '',
            width: hoverTooltipRect.width,
            height: hoverTooltipRect.height,
          };
          if (tooltipProbe) {
            tooltipProbe.dispatchEvent(new MouseEvent('mouseout', {bubbles: true, relatedTarget: document.body}));
          }
          const persistentChatLog = document.getElementById('planning-chat-log');
          const persistentChatTextBefore = persistentChatLog?.innerText || '';
          const persistentChatMessageCountBefore = document.querySelectorAll('#planning-chat-log .planning-chat-item').length;
          if (persistentChatLog) persistentChatLog.dataset.auditPersistentChatLog = '1';
          const before = {
            shell: visible('live-agent-binder-list') && visible('live-report-panel') && visible('planning-chat-log') && visible('live-timeline-strip') && visible('live-device-strip'),
            adoptedSessionId,
            binderCount: document.querySelectorAll('.binder-tab').length,
            binderIcons: Array.from(document.querySelectorAll('.binder-icon img')).filter((img) => img.complete && img.naturalWidth > 0).length,
            binderUnreadByAgent: Array.from(document.querySelectorAll('.binder-tab')).reduce((acc, el) => {
              const agentId = el.getAttribute('data-agent-id') || '';
              const badge = el.querySelector('.binder-unread');
              acc[agentId] = badge ? (badge.textContent || '').trim() : '';
              return acc;
            }, {}),
            binderStatusByAgent: Array.from(document.querySelectorAll('.binder-tab')).reduce((acc, el) => {
              const agentId = el.getAttribute('data-agent-id') || '';
              acc[agentId] = el.className || '';
              return acc;
            }, {}),
            headerMetricOverflowCount: (() => {
              const headerRect = rect('.live-runtime-header');
              if (!headerRect) return 999;
              return Array.from(document.querySelectorAll('.live-runtime-metrics > *')).filter((el) => {
                const itemRect = el.getBoundingClientRect();
                return itemRect.top < headerRect.top - 1 || itemRect.bottom > headerRect.bottom + 1 || itemRect.left < headerRect.left - 1 || itemRect.right > headerRect.right + 1;
              }).length;
            })(),
            headerMetricClipped: Array.from(document.querySelectorAll('.live-runtime-metrics > *')).filter((el) => el.scrollWidth > el.clientWidth + 1).map((el) => ({id: el.id || el.className || el.tagName, text: (el.textContent || '').trim(), scrollW: el.scrollWidth, clientW: el.clientWidth})),
            visibleQuickActions: Array.from(document.querySelectorAll('#live-quick-actions .live-quick-action')).filter((el) => getComputedStyle(el).display !== 'none').map((el) => el.getAttribute('data-quick-action') || ''),
            hiddenQuickActions: Array.from(document.querySelectorAll('#live-quick-actions .live-quick-action')).filter((el) => getComputedStyle(el).display === 'none').map((el) => el.getAttribute('data-quick-action') || ''),
            quickRailRect: rect('#live-quick-actions'),
            chatLogRect: rect('#planning-chat-log'),
            quickRailSide: (() => {
              const rail = rect('#live-quick-actions');
              const log = rect('#planning-chat-log');
              if (!rail || !log) return '';
              if (rail.left >= log.right - 1) return 'right';
              if (rail.right <= log.left + 1) return 'left';
              return 'overlap';
            })(),
            quickRailGapPx: (() => {
              const rail = rect('#live-quick-actions');
              const log = rect('#planning-chat-log');
              if (!rail || !log) return 999;
              if (rail.left >= log.right - 1) return Math.round(rail.left - log.right);
              if (rail.right <= log.left + 1) return Math.round(log.left - rail.right);
              return 0;
            })(),
            bottomDockRect: rect('.live-runtime-bottom'),
            bottomDockButtonRect: rect('#btn-live-bottom-collapse'),
            timelineStripRect: rect('#live-timeline-strip'),
            deviceStripRect: rect('#live-device-strip'),
            bottomDockContainment: (() => {
              const bottom = rect('.live-runtime-bottom');
              const timeline = rect('#live-timeline-strip');
              const device = rect('#live-device-strip');
              const button = rect('#btn-live-bottom-collapse');
              if (!bottom || !timeline || !device || !button) return {timeline: false, device: false, button: false};
              return {
                timeline: timeline.top >= bottom.top - 1 && timeline.bottom <= bottom.bottom + 1,
                device: device.top >= bottom.top - 1 && device.bottom <= bottom.bottom + 1,
                button: button.top >= bottom.top - 1 && button.bottom <= bottom.bottom + 1 && button.width <= 100,
              };
            })(),
            chatLogRole: persistentChatLog?.getAttribute('role') || '',
            chatLogAriaLive: persistentChatLog?.getAttribute('aria-live') || '',
            chatLogAriaRelevant: persistentChatLog?.getAttribute('aria-relevant') || '',
            chatMessageCount: persistentChatMessageCountBefore,
            chatTextBefore: persistentChatTextBefore,
            composerRect: rect('.planning-composer'),
            targetOptions: document.querySelectorAll('#live-chat-target option').length,
            targetValues: Array.from(document.querySelectorAll('#live-chat-target option')).map((el) => el.value || ''),
            targetGroupLabels: Array.from(document.querySelectorAll('#live-chat-target optgroup')).map((el) => el.label || ''),
            chatContextText: document.getElementById('live-chat-context-strip')?.textContent || '',
            chatContextTitle: document.getElementById('live-chat-context-strip')?.getAttribute('title') || '',
            chatContextRect: rect('#live-chat-context-strip'),
            focusContextText: document.getElementById('live-focus-strip')?.textContent || '',
            focusContextTitle: document.getElementById('live-focus-strip')?.getAttribute('title') || '',
            focusContextRect: rect('#live-focus-strip'),
            focusChipCount: document.querySelectorAll('#live-focus-strip .live-focus-chip').length,
            focusContextOverflow: (() => {
              const el = document.getElementById('live-focus-strip');
              return el ? el.scrollWidth > el.clientWidth + 1 : true;
            })(),
            approvalVisible: visible('live-approval-panel'),
            faultChipText: document.getElementById('live-fault-chip')?.textContent || '',
            faultChipClass: document.getElementById('live-fault-chip')?.className || '',
            faultChipTitle: document.getElementById('live-fault-chip')?.getAttribute('title') || '',
            faultCards: document.querySelectorAll('#live-approval-panel .live-fault-card').length,
            faultActionTitles: Array.from(document.querySelectorAll('#live-approval-panel .live-fault-action')).filter((el) => Boolean(el.getAttribute('title'))).length,
            faultActionWideCount: Array.from(document.querySelectorAll('#live-approval-panel .live-fault-action')).filter((el) => el.getBoundingClientRect().width > 44).length,
            faultActionHiddenLabels: Array.from(document.querySelectorAll('#live-approval-panel .live-fault-action .live-card-action-label')).filter((el) => getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width <= 2).length,
            deviceErrorCards: document.querySelectorAll('#live-device-strip .live-device-card.status-error').length,
            questionCards: document.querySelectorAll('#live-approval-panel .live-question-card').length,
            questionActionTitles: Array.from(document.querySelectorAll('#live-approval-panel .live-question-action')).filter((el) => Boolean(el.getAttribute('title'))).length,
            questionActionWideCount: Array.from(document.querySelectorAll('#live-approval-panel .live-question-action')).filter((el) => el.getBoundingClientRect().width > 44).length,
            questionActionHiddenLabels: Array.from(document.querySelectorAll('#live-approval-panel .live-question-action .live-card-action-label')).filter((el) => getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width <= 2).length,
            deviceCards: document.querySelectorAll('.live-device-card').length,
            deviceTitleCount: Array.from(document.querySelectorAll('.live-device-card')).filter((el) => Boolean(el.getAttribute('title'))).length,
            deviceDlHidden: getComputedStyle(document.querySelector('.live-device-card dl')).display === 'none',
            deviceEventCards: document.querySelectorAll('#live-device-strip .live-device-card[data-device-event-key]').length,
            deviceEventRoleCards: document.querySelectorAll('#live-device-strip .live-device-card[data-device-event-key][role="button"]').length,
            deviceEventHintCount: Array.from(document.querySelectorAll('#live-device-strip .live-device-card[data-device-event-key]')).filter((el) => (el.getAttribute('title') || '').includes('focus backend trace')).length,
            timelineItems: document.querySelectorAll('.live-timeline-item').length,
            timelineTitleCount: Array.from(document.querySelectorAll('.live-timeline-item')).filter((el) => Boolean(el.getAttribute('title'))).length,
            timelineText: document.getElementById('live-timeline-strip')?.textContent || '',
            quickActions: document.querySelectorAll('#live-quick-actions .live-quick-action').length,
            quickActionKeys: Array.from(document.querySelectorAll('#live-quick-actions .live-quick-action')).map((el) => el.dataset.quickAction || ''),
            quickActionTitles: Array.from(document.querySelectorAll('#live-quick-actions .live-quick-action')).filter((el) => Boolean(el.getAttribute('title'))).length,
            quickActionWideCount: Array.from(document.querySelectorAll('#live-quick-actions .live-quick-action')).filter((el) => el.getBoundingClientRect().width > 46).length,
            quickActionHiddenLabels: Array.from(document.querySelectorAll('#live-quick-actions .live-quick-label')).filter((el) => getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width <= 2).length,
            approvalDecisionKeys: Array.from(document.querySelectorAll('#live-approval-panel .live-approval-action')).map((el) => el.dataset.decision || ''),
            reportActions: document.querySelectorAll('#live-report-toolbar .live-report-action').length,
            reportActionTitles: Array.from(document.querySelectorAll('#live-report-toolbar .live-report-action')).filter((el) => Boolean(el.getAttribute('title'))).length,
            reportActionWideCount: Array.from(document.querySelectorAll('#live-report-toolbar .live-report-action')).filter((el) => el.getBoundingClientRect().width > 44).length,
            reportActionHiddenLabels: Array.from(document.querySelectorAll('#live-report-toolbar .live-report-action-label')).filter((el) => getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width <= 2).length,
            viewTabTitles: Array.from(document.querySelectorAll('.live-view-tab')).filter((el) => Boolean(el.getAttribute('title'))).length,
            viewTabWideCount: Array.from(document.querySelectorAll('.live-view-tab')).filter((el) => el.getBoundingClientRect().width > 44).length,
            viewTabHiddenLabels: Array.from(document.querySelectorAll('.live-tab-label')).filter((el) => getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width <= 2).length,
            evolutionQuickAction: Boolean(document.querySelector('#live-quick-actions .live-quick-action[data-quick-action="open_evolution"]')),
            evolutionReportAction: Boolean(document.querySelector('#live-report-toolbar .live-report-action[data-report-action="evolve"]')),
            reportSections: Array.from(document.querySelectorAll('#live-report-panel .live-report-section h4')).map((el) => el.textContent || ''),
            reportSpecificTitle: document.querySelector('#live-report-panel .live-agent-specific-report h4')?.textContent || '',
            reportSpecificText: document.querySelector('#live-report-panel .live-agent-specific-report')?.innerText || '',
            reportSpecificChecklistItems: document.querySelectorAll('#live-report-panel .live-agent-specific-checklist li').length,
            reportSpecificChecklistText: document.querySelector('#live-report-panel .live-agent-specific-checklist')?.innerText || '',
            reportSectionBodyCount: document.querySelectorAll('#live-report-panel .live-report-section .live-report-section-body').length,
            reportSectionTextByTitle: Array.from(document.querySelectorAll('#live-report-panel .live-report-section')).reduce((acc, section) => {
              const title = (section.querySelector('h4')?.textContent || '').trim();
              if (title) acc[title] = section.innerText || '';
              return acc;
            }, {}),
            timelineFilters: document.querySelectorAll('.live-timeline-filter').length,
            timelineFilterTitles: Array.from(document.querySelectorAll('.live-timeline-filter')).filter((el) => Boolean(el.getAttribute('title'))).length,
            timelineFilterWideCount: Array.from(document.querySelectorAll('.live-timeline-filter')).filter((el) => el.getBoundingClientRect().width > 42).length,
            timelineFilterHiddenLabels: Array.from(document.querySelectorAll('.live-timeline-filter-label')).filter((el) => getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width <= 2).length,
            keyboardShortcutAttrs: Array.from(document.querySelectorAll('[aria-keyshortcuts]')).map((el) => el.getAttribute('aria-keyshortcuts') || ''),
            shortcutOverlayExists: Boolean(document.getElementById('live-shortcut-overlay')),
            streamChipText: document.getElementById('live-stream-chip')?.textContent || '',
            streamChipTitle: document.getElementById('live-stream-chip')?.getAttribute('title') || '',
            streamChipClass: document.getElementById('live-stream-chip')?.className || '',
            syncChipText: document.getElementById('live-sync-chip')?.textContent || '',
            syncChipTitle: document.getElementById('live-sync-chip')?.getAttribute('title') || '',
            syncChipClass: document.getElementById('live-sync-chip')?.className || '',
            statusBadgeText: document.getElementById('planning-chat-status')?.textContent || '',
            statusBadgeClass: document.getElementById('planning-chat-status')?.className || '',
            statusBadgeTitle: document.getElementById('planning-chat-status')?.getAttribute('title') || '',
            statusBadgeAttention: document.getElementById('planning-chat-status')?.dataset.attentionStatus || '',
            stageChipText: document.getElementById('planning-stage-label')?.textContent || '',
            stageChipTitle: document.getElementById('planning-stage-label')?.getAttribute('title') || '',
            runChipText: document.getElementById('planning-run-detail')?.textContent || '',
            runChipTitle: document.getElementById('planning-run-detail')?.getAttribute('title') || '',
            activeAgentChipText: document.getElementById('live-active-agent-chip')?.textContent || '',
            activeAgentChipTitle: document.getElementById('live-active-agent-chip')?.getAttribute('title') || '',
            resourceChipText: document.getElementById('live-resource-chip')?.textContent || '',
            resourceChipTitle: document.getElementById('live-resource-chip')?.getAttribute('title') || '',
            tokenChipText: document.getElementById('live-token-chip')?.textContent || '',
            tokenChipTitle: document.getElementById('live-token-chip')?.getAttribute('title') || '',
            debugSnapshot: typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot() : {},
            deviceFields: document.querySelectorAll('#live-device-strip .live-device-field').length,
            activePanel: activePanel(),
            reportText: document.getElementById('live-report-panel')?.textContent || '',
          };
          const agentSpecificReports = {};
          ['orchestrator', 'design', 'specimen', 'bo', 'guardian'].forEach((agentId) => {
            click(`.binder-tab[data-agent-id="${agentId}"]`);
            agentSpecificReports[agentId] = document.querySelector('#live-report-panel')?.innerText || '';
          });
          const descriptorProbe = {};
          ['design', 'equipment', 'guardian', 'ui_audit_draft_descriptor'].forEach((agentId) => {
            click(`.binder-tab[data-agent-id="${agentId}"]`);
            descriptorProbe[agentId] = {
              cards: document.querySelectorAll('#live-report-panel .ar-descriptor-card').length,
              reportSections: document.querySelectorAll('#live-report-panel .ar-descriptor-report-section').length,
              text: document.querySelector('#live-report-panel')?.innerText || '',
            };
          });
          click('.binder-tab[data-agent-id="analysis"]');
          const binderChatTargetProbe = {
            targetValue: document.getElementById('live-chat-target')?.value || '',
            context: typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot().chat_context || {} : {},
            activePanel: activePanel(),
          };
          click('.binder-tab[data-agent-id="orchestrator"]');
          const chatHeightBeforeDockCollapse = rect('.live-chat-panel')?.height || 0;
          const bottomHeightBeforeDockCollapse = rect('.live-runtime-bottom')?.height || 0;
          click('#btn-live-bottom-collapse');
          const dockCollapseProbe = {
            collapsed: document.querySelector('.planning-runtime-shell')?.classList.contains('live-bottom-collapsed') || false,
            chatHeight: rect('.live-chat-panel')?.height || 0,
            bottomHeight: rect('.live-runtime-bottom')?.height || 0,
            buttonExpanded: document.getElementById('btn-live-bottom-collapse')?.getAttribute('aria-expanded') || '',
          };
          click('#btn-live-bottom-collapse');
          const dockExpandProbe = {
            collapsed: document.querySelector('.planning-runtime-shell')?.classList.contains('live-bottom-collapsed') || false,
            chatHeight: rect('.live-chat-panel')?.height || 0,
            bottomHeight: rect('.live-runtime-bottom')?.height || 0,
            buttonExpanded: document.getElementById('btn-live-bottom-collapse')?.getAttribute('aria-expanded') || '',
          };
          const busyPayload = JSON.parse(JSON.stringify(payload));
          busyPayload.session = {...busyPayload.session, is_planning_busy: true};
          window.__liveGuiDebugSetState(busyPayload);
          const busyProbe = {
            sendDisabled: Boolean(document.getElementById('btn-planning-send')?.disabled),
            planDisabled: Boolean(document.getElementById('btn-planning-generate')?.disabled),
            chatStatus: document.getElementById('planning-chat-status')?.textContent || '',
            statusBackendBusy: document.getElementById('planning-chat-status')?.dataset.backendBusy || '',
            sendTitle: document.getElementById('btn-planning-send')?.getAttribute('title') || '',
            debugSnapshot: typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot() : {},
          };
          window.__liveGuiDebugSetState(payload);
          click('#live-report-panel .live-report-section[data-report-section-title="Next Action / Audit"]');
          const selectedReportSectionCard = document.querySelector('#live-report-panel .live-report-section.selected');
          const selectedReportSectionTitle = selectedReportSectionCard?.dataset.reportSectionTitle || '';
          const selectedReportSectionAria = selectedReportSectionCard?.getAttribute('aria-selected') || '';
          const selectedReportSectionContext = window.__liveGuiDebugSnapshot().chat_context || {};
          click('#live-report-toolbar .live-report-action[data-report-action="ask"]');
          const sectionRewriteDraft = document.getElementById('planning-message-input')?.value || '';
          const evolutionQuickUrl = '';
          click('#live-report-toolbar .live-report-action[data-report-action="pin"]');
          const pinnedCompareText = document.querySelector('#live-report-panel .live-pinned-compare')?.textContent || '';
          const pinnedFindingsText = document.querySelector('#live-report-panel .live-pinned-findings')?.textContent || '';
          click('#live-report-panel .live-pinned-finding-action[data-pinned-index="0"]');
          const pinnedFocusProbe = {
            activePanel: activePanel(),
            focusTitle: document.getElementById('live-focus-strip')?.getAttribute('title') || '',
            focusText: document.getElementById('live-focus-strip')?.textContent || '',
            selectedSection: document.querySelector('#live-report-panel .live-report-section.selected')?.dataset.reportSectionTitle || '',
            context: typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot().chat_context || {} : {},
          };
          click('#live-report-toolbar .live-report-action[data-report-action="reviewed"]');
          const reviewedReportText = document.querySelector('#live-report-panel')?.textContent || '';
          document.dispatchEvent(new KeyboardEvent('keydown', {key: '?', bubbles: true}));
          const shortcutOverlay = document.getElementById('live-shortcut-overlay');
          const shortcutOverlayVisible = Boolean(shortcutOverlay && !shortcutOverlay.hidden && shortcutOverlay.textContent.includes('Alt+Shift+R/B/G/A/T'));
          document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
          const shortcutOverlayClosed = Boolean(shortcutOverlay && shortcutOverlay.hidden);
          document.dispatchEvent(new KeyboardEvent('keydown', {key: 'g', altKey: true, shiftKey: true, bubbles: true}));
          const shortcutGraphPanel = activePanel();
          click('.binder-attention-tab[data-attention-action="open"]');
          const attentionPanelText = document.querySelector('#live-report-panel')?.textContent || '';
          const attentionProbe = {
            approvalPanelVisible: visible('live-approval-panel'),
            activeTitle: document.getElementById('live-center-title')?.textContent || '',
            reportText: attentionPanelText,
            approvalCards: document.querySelectorAll('#live-report-panel .live-attention-approval-card').length,
            questionCards: document.querySelectorAll('#live-report-panel .live-question-card').length,
            faultCards: document.querySelectorAll('#live-report-panel .live-fault-card').length,
            questionActionTitles: Array.from(document.querySelectorAll('#live-report-panel .live-question-action')).filter((el) => Boolean(el.getAttribute('title'))).length,
            questionActionWideCount: Array.from(document.querySelectorAll('#live-report-panel .live-question-action')).filter((el) => el.getBoundingClientRect().width > 44).length,
            questionActionHiddenLabels: Array.from(document.querySelectorAll('#live-report-panel .live-question-action .live-card-action-label')).filter((el) => getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width <= 2).length,
            faultActionTitles: Array.from(document.querySelectorAll('#live-report-panel .live-fault-action')).filter((el) => Boolean(el.getAttribute('title'))).length,
            faultActionWideCount: Array.from(document.querySelectorAll('#live-report-panel .live-fault-action')).filter((el) => el.getBoundingClientRect().width > 44).length,
            faultActionHiddenLabels: Array.from(document.querySelectorAll('#live-report-panel .live-fault-action .live-card-action-label')).filter((el) => getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width <= 2).length,
          };
          click('#live-report-panel .live-fault-action[data-fault-action="backend"]');
          const faultSelectedTrace = document.querySelector('.live-selected-event-card')?.textContent || '';
          click('.binder-attention-tab[data-attention-action="open"]');
          click('#live-report-panel .live-question-action[data-question-action="answer"]');
          const questionAnswerDraft = document.getElementById('planning-message-input')?.value || '';
          const questionSelectedTrace = document.querySelector('.live-selected-event-card')?.textContent || '';
          const chatContextAfterTrace = {
            text: document.getElementById('live-chat-context-strip')?.textContent || '',
            title: document.getElementById('live-chat-context-strip')?.getAttribute('title') || '',
          };
          const focusContextAfterTrace = {
            text: document.getElementById('live-focus-strip')?.textContent || '',
            title: document.getElementById('live-focus-strip')?.getAttribute('title') || '',
            chipCount: document.querySelectorAll('#live-focus-strip .live-focus-chip').length,
          };
          const deviceFocus = (() => {
            const card = document.querySelector('#live-device-strip .live-device-card.status-error[data-device-event-key]') || document.querySelector('#live-device-strip .live-device-card[data-device-event-key]');
            if (!card) return {ok: false, error: 'device event card missing'};
            card.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
            const selected = document.querySelector('.live-selected-event-card')?.textContent || '';
            return {
              ok: Boolean(selected && document.querySelector('#live-backend-panel.live-center-view.active')),
              cardTitle: card.getAttribute('title') || '',
              eventKey: card.getAttribute('data-device-event-key') || '',
              agentId: card.getAttribute('data-agent-id') || '',
              selectedTraceText: selected,
              focusTitle: document.getElementById('live-focus-strip')?.getAttribute('title') || '',
              activePanel: activePanel(),
            };
          })();
          click('.binder-tab[data-agent-id="orchestrator"]');
          click('[data-live-view="backend"]');
          const backendPanel = activePanel();
          const backendTraceSections = document.querySelectorAll('#live-backend-panel .backend-trace-section').length;
          const backendTraceText = document.getElementById('live-backend-panel')?.textContent || '';
          const backendCompileContext = Boolean(document.querySelector('#live-backend-panel .raw-compile-context'));
          click('[data-live-view="graph"]');
          const graphPanel = activePanel();
          const graphNodes = document.querySelectorAll('#live-graph-panel .live-graph-mini-node').length;
          const activeGraphNodes = document.querySelectorAll('#live-graph-panel .live-graph-mini-node.node-active').length;
          const activeGraphEdges = document.querySelectorAll('#live-graph-panel .live-graph-edge.edge-active').length;
          const graphGateActions = Array.from(document.querySelectorAll('#live-graph-panel .live-graph-action')).map((el) => el.dataset.graphAction || '');
          const graphGateActionTitles = Array.from(document.querySelectorAll('#live-graph-panel .live-graph-action')).filter((el) => Boolean(el.getAttribute('title'))).length;
          const graphGateActionWideCount = Array.from(document.querySelectorAll('#live-graph-panel .live-graph-action')).filter((el) => el.getBoundingClientRect().width > 44).length;
          click('#live-graph-panel .live-graph-mini-node[data-graph-node-id="specimen"]');
          const selectedNodePanel = document.querySelector('#live-graph-panel .live-selected-node-view')?.textContent || '';
          const selectedGraphNodes = document.querySelectorAll('#live-graph-panel .live-graph-mini-node.node-selected').length;
          const selectedNodeActionWideCount = Array.from(document.querySelectorAll('#live-graph-panel .live-selected-node-action')).filter((el) => el.getBoundingClientRect().width > 44).length;
          const selectedNodeActionTitles = Array.from(document.querySelectorAll('#live-graph-panel .live-selected-node-action')).filter((el) => Boolean(el.getAttribute('title'))).length;
          const selectedNodeActionHiddenLabels = Array.from(document.querySelectorAll('#live-graph-panel .live-selected-node-action .live-card-action-label')).filter((el) => getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width <= 2).length;
          const runtimeIdeLinkHref = document.querySelector('#live-graph-panel a[data-live-ide-link]')?.getAttribute('href') || '';
          const runtimeIdeLinkTitle = document.querySelector('#live-graph-panel a[data-live-ide-link]')?.getAttribute('title') || '';
          click('#live-graph-panel .live-graph-mini-canvas');
          const blankGraphSelection = {
            selectedGraphNodes: document.querySelectorAll('#live-graph-panel .live-graph-mini-node.node-selected').length,
            selectedNodeText: document.querySelector('#live-graph-panel .live-selected-node-view')?.textContent || '',
            selectedNodeData: document.querySelector('#live-graph-panel .live-selected-node-view')?.getAttribute('data-selected-graph-node') || '',
            context: typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot().chat_context || {} : {},
            saved: JSON.parse(window.localStorage.getItem('autonomousLiveGuiUiState') || '{}'),
          };
          click('[data-live-view="artifacts"]');
          const artifactPanel = activePanel();
          click('[data-live-view="timeline"]');
          const timelinePanel = activePanel();
          click('.live-timeline-filter[data-timeline-filter="warning"]');
          const warningTimelineItems = document.querySelectorAll('#live-timeline-strip .live-timeline-item').length;
          click('#live-timeline-strip .live-timeline-item');
          const selectedTimelineTargetProbe = {
            targetValue: document.getElementById('live-chat-target')?.value || '',
            context: typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot().chat_context || {} : {},
          };
          const selectedEventText = document.querySelector('.live-selected-event-card')?.textContent || '';
          const selectedEventActions = document.querySelectorAll('.live-selected-event-card .live-selected-event-action').length;
          const selectedEventActionWideCount = Array.from(document.querySelectorAll('.live-selected-event-card .live-selected-event-action')).filter((el) => el.getBoundingClientRect().width > 44).length;
          const selectedEventActionTitles = Array.from(document.querySelectorAll('.live-selected-event-card .live-selected-event-action')).filter((el) => Boolean(el.getAttribute('title'))).length;
          const selectedEventActionHiddenLabels = Array.from(document.querySelectorAll('.live-selected-event-card .live-selected-event-action .live-card-action-label')).filter((el) => getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width <= 2).length;
          const selectedTimelineItems = document.querySelectorAll('#live-timeline-strip .live-timeline-item.selected').length;
          click('.live-selected-event-card .live-selected-event-action[data-event-action="open_report"]');
          const timelineActionClicked = true;
          click('[data-live-view="timeline"]');
          click('.live-timeline-filter[data-timeline-filter="warning"]');
          click('#live-timeline-strip .live-timeline-item');
          click('#live-timeline-strip');
          const blankTimelineSelection = {
            selectedTimelineItems: document.querySelectorAll('#live-timeline-strip .live-timeline-item.selected').length,
            selectedEventText: document.querySelector('.live-selected-event-card')?.textContent || '',
            context: typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot().chat_context || {} : {},
            saved: JSON.parse(window.localStorage.getItem('autonomousLiveGuiUiState') || '{}'),
          };
          rightclick('.binder-tab[data-agent-id="design"]');
          const contextMenuVisible = visible('live-binder-context-menu');
          const contextActions = document.querySelectorAll('#live-binder-context-menu .live-context-action').length;
          click('#live-binder-context-menu .live-context-action[data-context-action="mark_read"]');
          const contextActionClicked = true;
          const binderCtrlPinClicked = ctrlclick('.binder-tab[data-agent-id="bo"]');
          const binderCtrlPinProbe = {
            clicked: binderCtrlPinClicked,
            pinnedText: document.querySelector('#live-report-panel .live-pinned-findings')?.textContent || '',
            targetValue: document.getElementById('live-chat-target')?.value || '',
            context: typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot().chat_context || {} : {},
            title: document.querySelector('.binder-tab[data-agent-id="bo"]')?.getAttribute('title') || '',
          };
          click('.binder-tab[data-agent-id="analysis"]');
          const afterClickTitle = document.getElementById('live-center-title')?.textContent || '';
          dblclick('.binder-tab[data-agent-id="guardian"]');
          const afterDoublePanel = activePanel();
          const afterDoubleTitle = document.getElementById('live-center-title')?.textContent || '';
          const savedUiState = JSON.parse(window.localStorage.getItem('autonomousLiveGuiUiState') || '{}');
          const persistentChatTextAfter = document.getElementById('planning-chat-log')?.innerText || '';
          const persistentChatProbe = {
            marker: document.getElementById('planning-chat-log')?.dataset.auditPersistentChatLog || '',
            role: document.getElementById('planning-chat-log')?.getAttribute('role') || '',
            ariaLive: document.getElementById('planning-chat-log')?.getAttribute('aria-live') || '',
            messageCount: document.querySelectorAll('#planning-chat-log .planning-chat-item').length,
            beforeTextLength: persistentChatTextBefore.length,
            afterTextLength: persistentChatTextAfter.length,
            includesInitialMessages: persistentChatTextAfter.includes('실험 목표와 필수 입력값을 확인했습니다.') && persistentChatTextAfter.includes('Design Agent selected printable gyroid TPMS specimen.'),
          };

          return {
            ok: true,
            before,
            pinnedCompareText,
            pinnedFindingsText,
            pinnedFocusProbe,
            reviewedReportText,
            evolutionQuickUrl,
            selectedReportSectionTitle,
            selectedReportSectionAria,
            selectedReportSectionContext,
            sectionRewriteDraft,
            shortcutOverlayVisible,
            shortcutOverlayClosed,
            shortcutGraphPanel,
            attentionProbe,
            faultSelectedTrace,
            questionAnswerDraft,
            questionSelectedTrace,
            backendPanel,
            chatContextAfterTrace,
            focusContextAfterTrace,
            deviceFocus,
            backendTraceSections,
            backendTraceText,
            backendCompileContext,
            graphPanel,
            graphNodes,
            activeGraphNodes,
            activeGraphEdges,
            graphGateActions,
            graphGateActionTitles,
            graphGateActionWideCount,
            selectedNodePanel,
            selectedGraphNodes,
            selectedNodeActionWideCount,
            selectedNodeActionTitles,
            selectedNodeActionHiddenLabels,
            blankGraphSelection,
            runtimeIdeLinkHref,
            runtimeIdeLinkTitle,
            artifactPanel,
            timelinePanel,
            warningTimelineItems,
            selectedEventText,
            selectedEventActions,
            selectedEventActionWideCount,
            selectedEventActionTitles,
            selectedEventActionHiddenLabels,
            selectedTimelineItems,
            selectedTimelineTargetProbe,
            blankTimelineSelection,
            timelineActionClicked,
            contextMenuVisible,
            contextActions,
            contextActionClicked,
            binderCtrlPinProbe,
            afterClickTitle,
            afterDoublePanel,
            afterDoubleTitle,
            savedUiState,
            compactTooltip,
            bodyWidth: document.body.scrollWidth,
            viewportWidth: window.innerWidth,
            visual,
            agentSpecificReports,
            descriptorProbe,
            binderChatTargetProbe,
            dockCollapseProbe,
            dockExpandProbe,
            chatHeightBeforeDockCollapse,
            bottomHeightBeforeDockCollapse,
            busyProbe,
            persistentChatProbe,
          };
        } catch (err) {
          return {ok: false, error: String(err && err.message ? err.message : err), stack: String(err && err.stack ? err.stack : "")};
        }
        """,
        [sample_payload(run_id=run_id, approval_id=approval_id)],
    )
    if not result.get("ok"):
        raise AssertionError(result)
    before = result.get("before", {})
    visual = result.get("visual") or before.get("visual") or {}
    if not before.get("shell"):
        raise AssertionError(f"Live shell panels are not visible: {result}")
    if before.get("adoptedSessionId") != "session-ui-audit":
        raise AssertionError(f"Live GUI did not adopt server planning_session_id for shared-window state: {result}")
    if before.get("chatLogRole") != "log" or before.get("chatLogAriaLive") != "polite" or "additions" not in str(before.get("chatLogAriaRelevant")):
        raise AssertionError(f"Runtime Chat conversation stream is not exposed as a persistent live log: {before}")
    if int(before.get("chatMessageCount") or 0) < 4 or "Design Agent selected" not in str(before.get("chatTextBefore") or ""):
        raise AssertionError(f"Runtime Chat initial conversation did not render enough persisted messages: {before}")
    if before.get("binderCount") != 12:
        raise AssertionError(f"Expected 12 binder tabs including the draft descriptor fixture, got {before.get('binderCount')}: {result}")
    if before.get("binderIcons") != 12:
        raise AssertionError(f"Agentic Binder SVG icons did not load for all tabs: {result}")
    if LIVE_AUDIT_DRAFT_MODULE_ID not in (before.get("targetValues") or []):
        raise AssertionError(f"Draft descriptor module did not reach Runtime Chat target options: {before.get('targetValues')}")
    unread_by_agent = before.get("binderUnreadByAgent") or {}
    if not unread_by_agent.get("specimen") or not unread_by_agent.get("guardian"):
        raise AssertionError(f"Binder unread badges do not reflect runtime event/approval updates: {unread_by_agent}")
    if before.get("headerMetricOverflowCount") != 0:
        raise AssertionError(f"Live header metric chips overflow the top LIVE section: {before}")
    if before.get("headerMetricClipped"):
        raise AssertionError(f"Live header metric chip text is clipped inside the top LIVE section: {before.get('headerMetricClipped')}")
    bottom_containment = before.get("bottomDockContainment") or {}
    if not all(bottom_containment.get(key) for key in ["timeline", "device", "button"]):
        raise AssertionError(
            f"Live Event/IO bottom dock content escapes or the collapse button is oversized: containment={bottom_containment} "
            f"bottom={before.get('bottomDockRect')} timeline={before.get('timelineStripRect')} "
            f"device={before.get('deviceStripRect')} button={before.get('bottomDockButtonRect')}"
        )
    status_by_agent = before.get("binderStatusByAgent") or {}
    if "status-error" not in str(status_by_agent.get("specimen", "")):
        raise AssertionError(f"Device fault events did not mark the owning agent binder as error: {status_by_agent}")
    if "error" not in str(before.get("faultChipClass", "")) or "PRINTER_UPLOAD_FAILED" not in str(before.get("faultChipTitle", "")):
        raise AssertionError(f"Runtime fault header chip did not expose device errors: {before}")
    visible_quick = set(before.get("visibleQuickActions") or [])
    required_visible_quick = {"approve_next_step", "revise", "reject_next_step", "pause_run", "resume_run", "safe_stop", "dry_run"}
    if visible_quick != required_visible_quick:
        raise AssertionError(f"Runtime Chat visible quick-action rail should expose only essential actions: {before.get('visibleQuickActions')}")
    if abs(((visual.get("binderRect") or {}).get("width") or 0) - 196) > 2:
        raise AssertionError(f"Live agent binder must preserve the reference 196px layout width: {visual.get('binderRect')}")
    if ((before.get("composerRect") or {}).get("height") or 0) < 88 or ((before.get("composerRect") or {}).get("height") or 999) > 96:
        raise AssertionError(f"Runtime Chat composer must preserve the reference 92px layout height: {before.get('composerRect')}")
    if ((visual.get("safeStopRect") or {}).get("width") or 0) < 130:
        raise AssertionError(f"E-STOP must preserve the reference header slot width: {visual.get('safeStopRect')}")
    if ((before.get("chatLogRect") or {}).get("height") or 0) < 380 or ((before.get("quickRailRect") or {}).get("width") or 999) > 34:
        raise AssertionError(f"Runtime Chat log/rail layout is not reference-compatible: chat={before.get('chatLogRect')} rail={before.get('quickRailRect')}")
    if before.get("quickRailSide") != "right" or int(before.get("quickRailGapPx") or 999) > 8:
        raise AssertionError(f"Runtime Chat quick-action rail is not attached to the transcript side: side={before.get('quickRailSide')} gap={before.get('quickRailGapPx')} rail={before.get('quickRailRect')} chat={before.get('chatLogRect')}")
    if before.get("targetOptions") < 10:
        raise AssertionError(f"Chat target selector is under-populated: {result}")
    if before.get("approvalVisible") or before.get("statusBadgeAttention") == "1":
        raise AssertionError(f"Operator attention leaked outside the ATT report page: {before}")
    attention_probe = result.get("attentionProbe") or {}
    if attention_probe.get("approvalPanelVisible"):
        raise AssertionError(f"Legacy approval panel should remain hidden after opening ATT: {attention_probe}")
    if "Operator Attention" not in str(attention_probe.get("activeTitle")):
        raise AssertionError(f"ATT binder did not open the Operator Attention report page: {attention_probe}")
    if attention_probe.get("questionCards", 0) < 1:
        raise AssertionError(f"Agent question card is not visible on the ATT report page: {attention_probe}")
    if attention_probe.get("questionActionTitles", 0) < 3 or attention_probe.get("questionActionWideCount", 1) != 0 or attention_probe.get("questionActionHiddenLabels", 0) < 3:
        raise AssertionError(f"Agent question actions are not compact icon+tooltip controls on ATT page: {attention_probe}")
    if attention_probe.get("faultCards", 0) < 1 or before.get("deviceErrorCards", 0) < 1:
        raise AssertionError(f"Device/runtime faults are not surfaced on the ATT page and IO strip: attention={attention_probe} before={before}")
    if attention_probe.get("faultActionTitles", 0) < 2 or attention_probe.get("faultActionWideCount", 1) != 0 or attention_probe.get("faultActionHiddenLabels", 0) < 2:
        raise AssertionError(f"Runtime fault actions are not compact icon+tooltip controls on ATT page: {attention_probe}")
    if before.get("deviceCards", 0) < 6:
        raise AssertionError(f"Device/runtime strip did not populate: {result}")
    if before.get("deviceTitleCount", 0) < before.get("deviceCards", 0) or not before.get("deviceDlHidden"):
        raise AssertionError(f"Device cards are not compact hover-detail cards: {before}")
    if before.get("deviceEventCards", 0) < 1 or before.get("deviceEventRoleCards", 0) < before.get("deviceEventCards", 0) or before.get("deviceEventHintCount", 0) < before.get("deviceEventCards", 0):
        raise AssertionError(f"Device cards with runtime events are not exposed as trace-focus controls: {before}")
    if before.get("timelineItems", 0) < 3:
        raise AssertionError(f"Timeline did not populate: {result}")
    if before.get("timelineTitleCount", 0) < before.get("timelineItems", 0):
        raise AssertionError(f"Timeline items are missing hover titles: {before}")
    required_quick_actions = {
        "approve_next_step",
        "revise",
        "reject_next_step",
        "pause_run",
        "resume_run",
        "safe_stop",
        "dry_run",
    }
    if set(before.get("quickActionKeys") or []) != required_quick_actions:
        raise AssertionError(f"Runtime chat quick actions should contain only essential runtime controls: {result}")
    if before.get("hiddenQuickActions"):
        raise AssertionError(f"Runtime chat should not keep hidden debug quick actions in the rail: {before.get('hiddenQuickActions')}")
    if "cancelled" not in set(before.get("approvalDecisionKeys") or []):
        raise AssertionError(f"Approval card does not expose package-required Revise action: {result}")
    if before.get("quickActions", 0) != len(required_quick_actions):
        raise AssertionError(f"Runtime chat quick actions are not limited to essential controls: {result}")
    if before.get("quickActionTitles", 0) < before.get("quickActions", 0) or before.get("quickActionWideCount", 1) != 0:
        raise AssertionError(f"Runtime chat quick actions are not compact icon+tooltip controls: {before}")
    if before.get("quickActionHiddenLabels", 0) < before.get("quickActions", 0):
        raise AssertionError(f"Runtime chat quick action labels are not visually compacted: {before}")
    compact_tooltip = result.get("compactTooltip") or {}
    if not compact_tooltip.get("exists") or not compact_tooltip.get("visible") or compact_tooltip.get("width", 0) < 40:
        raise AssertionError(f"Compact icon tooltip did not render on hover/focus: {compact_tooltip}")
    if before.get("reportActions", 0) < 3:
        raise AssertionError(f"Report actions are incomplete: {result}")
    if before.get("reportActionTitles", 0) < before.get("reportActions", 0) or before.get("reportActionWideCount", 1) != 0:
        raise AssertionError(f"Report actions are not compact icon+tooltip controls: {before}")
    if before.get("reportActionHiddenLabels", 0) < before.get("reportActions", 0):
        raise AssertionError(f"Report action labels are not visually compacted: {before}")
    if before.get("viewTabTitles", 0) < 5 or before.get("viewTabWideCount", 1) != 0 or before.get("viewTabHiddenLabels", 0) < 5:
        raise AssertionError(f"Center view tabs are not compact icon+tooltip controls: {before}")
    required_sections = {"Mission Contract", "Decision Register (Today)", "Orchestration Plan / Handoff Route", "Next Action / Audit"}
    if not required_sections.issubset(set(before.get("reportSections") or [])):
        raise AssertionError(f"Academic report sections are incomplete: {result}")
    if result.get("selectedReportSectionTitle") != "Next Action / Audit" or result.get("selectedReportSectionAria") != "true":
        raise AssertionError(f"Report section selection did not mark the selected section: {result}")
    section_context = result.get("selectedReportSectionContext") or {}
    if section_context.get("selected_report_section") != "Next Action / Audit" or "Next Action / Audit" not in str(result.get("sectionRewriteDraft")) :
        raise AssertionError(f"Selected report section was not carried into Runtime Chat context/rewrite draft: {result}")
    ask_result = wait_for_live_action(audit, "operator.report.ask_drafted", timeout_s=8.0)
    if not ask_result.get("ok"):
        raise AssertionError(f"Report Ask action did not record the required operator event: {ask_result}")
    ask_payload = ((ask_result.get("hit") or {}).get("payload") or {})
    if ask_payload.get("selected_report_section") != "Next Action / Audit" or ask_payload.get("ask_scope") != "selected_report_section":
        raise AssertionError(f"Report Ask action did not preserve selected section context: {ask_result}")
    agent_specific_reports = result.get("agentSpecificReports") or {}
    expected_agent_phrases = {
        "design": "DOE Map / Design Space",
        "specimen": "Printer Runtime",
        "bo": "BO Candidate Ranking",
        "guardian": "Stop / Continue Decision",
    }
    for agent_id, phrase in expected_agent_phrases.items():
        report_text = str(agent_specific_reports.get(agent_id, "")).lower()
        if phrase.lower() not in report_text:
            raise AssertionError(f"{agent_id} report is not role-specific: {agent_specific_reports}")
    descriptor_probe = result.get("descriptorProbe") or {}
    for agent_id in (LIVE_AUDIT_DRAFT_MODULE_ID,):
        probe = descriptor_probe.get(agent_id) or {}
        if int(probe.get("cards") or 0) < 1:
            raise AssertionError(f"{agent_id} descriptor cards did not render from backend manifest: {descriptor_probe}")
        if int(probe.get("reportSections") or 0) < 1:
            raise AssertionError(f"{agent_id} descriptor report sections did not render from backend manifest: {descriptor_probe}")
    for agent_id in ("design", "equipment", "guardian"):
        probe = descriptor_probe.get(agent_id) or {}
        if int(probe.get("cards") or 0) != 0 or int(probe.get("reportSections") or 0) != 0:
            raise AssertionError(f"{agent_id} built-in reference report should not be displaced by descriptor preview cards: {descriptor_probe}")
    binder_target = result.get("binderChatTargetProbe") or {}
    binder_context = binder_target.get("context") or {}
    if binder_target.get("targetValue") != "analysis" or binder_context.get("chat_target") != "analysis" or binder_context.get("selected_agent") != "analysis":
        raise AssertionError(f"Binder agent selection did not retarget Runtime Chat to the selected agent: {binder_target}")
    pinned_compare_text = str(result.get("pinnedCompareText"))
    if "Selected vs Pinned" not in pinned_compare_text or "Focus Pinned" not in pinned_compare_text:
        raise AssertionError(f"Pinned comparison panel did not render the selected-vs-pinned context: {result}")
    pinned_text = str(result.get("pinnedFindingsText"))
    if "Pinned Findings" not in pinned_text or "Next Action / Audit" not in pinned_text:
        raise AssertionError(f"Pinned findings panel did not render the selected section after pin action: {result}")
    report_pin_result = wait_for_live_action_exact(audit, "operator.report.pinned", timeout_s=8.0)
    if not report_pin_result.get("ok"):
        raise AssertionError(f"Report Pin Finding action did not append runtime evidence: {report_pin_result}")
    pin_payload = ((report_pin_result.get("hit") or {}).get("payload") or {})
    pinned_finding = pin_payload.get("pinned_finding") or {}
    if pin_payload.get("selected_report_section") != "Next Action / Audit" or pinned_finding.get("selected_report_section") != "Next Action / Audit":
        raise AssertionError(f"Report Pin Finding did not preserve selected section evidence: {report_pin_result}")
    pinned_focus_result = wait_for_live_action_exact(audit, "operator.report.pinned_focused", timeout_s=8.0)
    if not pinned_focus_result.get("ok"):
        raise AssertionError(f"Pinned finding focus action did not append runtime evidence: {pinned_focus_result}")
    pinned_focus_payload = ((pinned_focus_result.get("hit") or {}).get("payload") or {})
    if pinned_focus_payload.get("source_action") != "report.pinned_focus" or pinned_focus_payload.get("selected_report_section") != "Next Action / Audit":
        raise AssertionError(f"Pinned finding focus payload is incomplete: {pinned_focus_result}")
    pinned_focus_probe = result.get("pinnedFocusProbe") or {}
    if pinned_focus_probe.get("activePanel") != "live-report-panel" or "report_section=Next Action / Audit" not in str(pinned_focus_probe.get("focusTitle")) or "Next Action / Audit" not in str(pinned_focus_probe.get("selectedSection")):
        raise AssertionError(f"Pinned finding focus did not restore report context: {pinned_focus_probe}")
    report_reviewed_result = wait_for_live_action(audit, "operator.report.reviewed", timeout_s=8.0)
    if not report_reviewed_result.get("ok"):
        raise AssertionError(f"Report Mark Reviewed action did not append runtime evidence: {report_reviewed_result}")
    binder_pin_result = wait_for_live_action(audit, "operator.binder.report_pinned", timeout_s=8.0)
    if not binder_pin_result.get("ok"):
        raise AssertionError(f"Binder Ctrl/Cmd-click pin did not append runtime evidence: {binder_pin_result}")
    binder_pin_payload = ((binder_pin_result.get("hit") or {}).get("payload") or {})
    if binder_pin_payload.get("source_action") != "binder.ctrl_click" or binder_pin_payload.get("selected_agent") != "bo":
        raise AssertionError(f"Binder Ctrl/Cmd-click pin evidence payload is incomplete: {binder_pin_result}")
    restored_report_state = audit.js(
        r"""
        if (typeof window.__liveGuiDebugRestoreOperatorReportState !== 'function') {
          return {ok: false, error: '__liveGuiDebugRestoreOperatorReportState missing'};
        }
        const snapshot = window.__liveGuiDebugRestoreOperatorReportState('orchestrator', 'report');
        return {
          ok: true,
          pinned: snapshot.pinned_findings || [],
          reviewed: snapshot.reviewed_agents || {},
          reportText: document.querySelector('#live-report-panel')?.textContent || '',
        };
        """
    )
    if not restored_report_state.get("pinned") or "orchestrator" not in str(restored_report_state.get("reviewed")):
        raise AssertionError(f"Operator report state was not restored from runtime events: {restored_report_state}")
    restored_text = str(restored_report_state.get("reportText") or "")
    if "Pinned Findings" not in restored_text or "reviewed" not in restored_text.lower():
        raise AssertionError(f"Restored pin/review state is not visible in report UI: {restored_report_state}")
    audit.js("window.__liveGuiDebugRestoreOperatorReportState('guardian', 'backend');")
    timeline_action_result = wait_for_live_action(audit, "operator.timeline.open_report", timeout_s=8.0)
    if not timeline_action_result.get("ok"):
        raise AssertionError(f"Timeline event action did not append runtime evidence: {timeline_action_result}")
    context_action_result = wait_for_live_action(audit, "operator.context.mark_read", timeout_s=8.0)
    if not context_action_result.get("ok"):
        raise AssertionError(f"Binder context action did not append runtime evidence: {context_action_result}")
    question_attention_result = wait_for_live_action(audit, "operator.attention.question_answer", timeout_s=8.0)
    if not question_attention_result.get("ok") or ((question_attention_result.get("hit") or {}).get("payload") or {}).get("attention_event_key") != "evt-agent-question-1":
        raise AssertionError(f"Question attention action did not append runtime evidence: {question_attention_result}")
    fault_attention_result = wait_for_live_action(audit, "operator.attention.fault_backend", timeout_s=8.0)
    if not fault_attention_result.get("ok") or ((fault_attention_result.get("hit") or {}).get("payload") or {}).get("attention_event_key") != "evt-printer-error-1":
        raise AssertionError(f"Fault attention action did not append runtime evidence: {fault_attention_result}")
    device_focus_result = wait_for_live_action(audit, "operator.device.trace_focused", timeout_s=8.0)
    if not device_focus_result.get("ok") or (((device_focus_result.get("hit") or {}).get("payload") or {}).get("source_action") != "device_card.focus_trace"):
        raise AssertionError(f"Device card focus did not append runtime evidence: {device_focus_result}")
    if "PRINTER_UPLOAD_FAILED" not in str(result.get("faultSelectedTrace")):
        raise AssertionError(f"Fault backend action did not focus the selected fault trace: {result}")
    device_focus = result.get("deviceFocus") or {}
    if not device_focus.get("ok") or "PRINTER_UPLOAD_FAILED" not in str(device_focus.get("selectedTraceText")) or "backend" not in str(device_focus.get("activePanel")):
        raise AssertionError(f"Device card click did not focus the matching backend trace: {device_focus}")
    if "bridge_mode" not in str(result.get("questionAnswerDraft")) or "trace-question-1" not in str(result.get("questionSelectedTrace")):
        raise AssertionError(f"Agent question answer flow did not preserve selected trace context: {result}")
    trace_context = result.get("chatContextAfterTrace") or {}
    if "trace-question-1" not in str(trace_context.get("title")) or "A:SPC" not in str(trace_context.get("text")) or "C:SPC" not in str(trace_context.get("text")) or "R:LIV:ON" not in str(trace_context.get("text")) or "Ref:" not in str(trace_context.get("text")) or "running=true" not in str(trace_context.get("title")) or "goal=Browser audit live workflow" not in str(trace_context.get("title")):
        raise AssertionError(f"Live chat context strip did not track selected trace/agent/target/run/reference: {trace_context}")
    if "R:LIV:ON" not in str(before.get("chatContextText")) or "mode=live" not in str(before.get("chatContextTitle")) or "running=true" not in str(before.get("chatContextTitle")):
        raise AssertionError(f"Live chat context strip did not expose live mode/running state: {before.get('chatContextText')} / {before.get('chatContextTitle')}")
    if before.get("focusChipCount", 0) < 7 or before.get("focusContextOverflow"):
        raise AssertionError(f"Live focus strip is missing chips or overflowing: {before}")
    if "agent=" not in str(before.get("focusContextTitle")) or "report_section=" not in str(before.get("focusContextTitle")):
        raise AssertionError(f"Live focus strip does not expose selected operator context: {before.get('focusContextTitle')}")
    focus_context = result.get("focusContextAfterTrace") or {}
    if "trace-question-1" not in str(focus_context.get("title")) or "target=specimen" not in str(focus_context.get("title")) or int(focus_context.get("chipCount") or 0) < 7:
        raise AssertionError(f"Live focus strip did not follow selected trace/target context: {focus_context}")
    if before.get("timelineFilters", 0) < 7:
        raise AssertionError(f"Timeline filters are incomplete: {result}")
    if before.get("timelineFilterTitles", 0) < before.get("timelineFilters", 0) or before.get("timelineFilterWideCount", 1) != 0 or before.get("timelineFilterHiddenLabels", 0) < before.get("timelineFilters", 0):
        raise AssertionError(f"Timeline filters are not compact icon+tooltip controls: {before}")
    shortcut_attrs = set(before.get("keyboardShortcutAttrs") or [])
    for required_shortcut in ["Alt+Shift+X", "Alt+Shift+G", "Alt+Shift+D", "Control+Enter"]:
        if required_shortcut not in shortcut_attrs:
            raise AssertionError(f"Live GUI keyboard shortcut metadata is incomplete: {before}")
    if not before.get("shortcutOverlayExists") or not result.get("shortcutOverlayVisible") or not result.get("shortcutOverlayClosed"):
        raise AssertionError(f"Live GUI shortcut overlay did not open/close through keyboard: {result}")
    busy_probe = result.get("busyProbe") or {}
    if not busy_probe.get("sendDisabled") or not busy_probe.get("planDisabled") or busy_probe.get("chatStatus") != "BUSY" or busy_probe.get("statusBackendBusy") != "1":
        raise AssertionError(f"Live GUI does not reflect backend planning busy state across windows: {busy_probe}")
    if "still reasoning" not in str(busy_probe.get("sendTitle", "")) or not (busy_probe.get("debugSnapshot") or {}).get("backend_planning_busy"):
        raise AssertionError(f"Live GUI backend busy tooltip/debug snapshot is incomplete: {busy_probe}")
    if result.get("shortcutGraphPanel") != "live-graph-panel":
        raise AssertionError(f"Alt+Shift+G did not switch to graph panel: {result}")
    if "SSE" not in str(before.get("streamChipText")) or "Runtime event stream" not in str(before.get("streamChipTitle")):
        raise AssertionError(f"Live GUI stream freshness chip is missing or uninformative: {before}")
    if "Sync" not in str(before.get("syncChipText")) or "Last state sync" not in str(before.get("syncChipTitle")):
        raise AssertionError(f"Live GUI state sync freshness chip is missing or stale: {before}")
    if "runtime-chip" not in str(before.get("streamChipClass")) or "runtime-chip" not in str(before.get("syncChipClass")):
        raise AssertionError(f"Live GUI connection chips do not use runtime-chip styling: {before}")
    if not str(before.get("stageChipText", "")).startswith("S:") or "Stage:" not in str(before.get("stageChipTitle", "")):
        raise AssertionError(f"Live GUI stage chip is not compact but tooltip-backed: {before}")
    if "run=" in str(before.get("runChipText", "")) or "run=" not in str(before.get("runChipTitle", "")):
        raise AssertionError(f"Live GUI run chip did not compact full run detail into a tooltip: {before}")
    if not str(before.get("activeAgentChipText", "")).startswith("A:") or "Active agent:" not in str(before.get("activeAgentChipTitle", "")):
        raise AssertionError(f"Live GUI active agent chip is not compact but tooltip-backed: {before}")
    if "GPU/RAM" not in str(before.get("resourceChipText", "")) or "GPU" not in str(before.get("resourceChipTitle", "")):
        raise AssertionError(f"Live GUI resource chip is not compact but tooltip-backed: {before}")
    if not str(before.get("tokenChipText", "")).startswith("Tok ") or "LLM token usage" not in str(before.get("tokenChipTitle", "")):
        raise AssertionError(f"Live GUI token chip is not compact but tooltip-backed: {before}")
    debug_snapshot = before.get("debugSnapshot") or {}
    if "sync_state" not in debug_snapshot or "last_sync_at" not in debug_snapshot or "stream_state" not in debug_snapshot:
        raise AssertionError(f"Live GUI debug snapshot does not expose sync/stream freshness state: {debug_snapshot}")
    if int((debug_snapshot.get("token_usage") or {}).get("total") or 0) < 2250:
        raise AssertionError(f"Live GUI debug snapshot does not expose token usage: {debug_snapshot}")
    if before.get("deviceFields", 0) < 24:
        raise AssertionError(f"Device cards do not expose bridge/command/heartbeat/safety fields: {result}")
    if result.get("backendPanel") != "live-backend-panel":
        raise AssertionError(f"Backend tab did not switch: {result}")
    if result.get("backendTraceSections", 0) < 6:
        raise AssertionError(f"Backend trace sections did not render raw prompt/tool/node I/O: {result}")
    backend_trace_text = str(result.get("backendTraceText") or "")
    required_backend_trace_labels = ["Graph / Compile Context", "Raw Prompt / Messages", "Raw LLM Response", "Tool Calls / Results", "Node Input JSON", "Node Output JSON", "Logs / Step Trace"]
    if not result.get("backendCompileContext") or not all(label in backend_trace_text for label in required_backend_trace_labels):
        raise AssertionError(f"Backend trace is missing required runtime debug sections: {result}")
    if result.get("graphPanel") != "live-graph-panel" or result.get("graphNodes", 0) < 3 or result.get("activeGraphNodes", 0) < 1:
        raise AssertionError(f"Graph mini view did not render active runtime graph: {result}")
    if result.get("activeGraphEdges", 0) < 1:
        raise AssertionError(f"Graph mini view did not apply IDE-style active edge flow state: {result}")
    graph_gate_actions = set(result.get("graphGateActions") or [])
    if graph_gate_actions != {"validate", "compile", "save_version", "run_test"} or result.get("graphGateActionTitles", 0) < 4 or result.get("graphGateActionWideCount", 99) != 0:
        raise AssertionError(f"Graph gate actions are not compact or complete: {result}")
    if result.get("selectedGraphNodes", 0) < 1 or "Specimen Agent" not in str(result.get("selectedNodePanel")):
        raise AssertionError(f"Selected Node View did not track clicked graph node: {result}")
    blank_graph = result.get("blankGraphSelection") or {}
    if blank_graph.get("selectedGraphNodes") != 0 or blank_graph.get("selectedNodeData") or "No node selected" not in str(blank_graph.get("selectedNodeText")) or not (blank_graph.get("saved") or {}).get("graphSelectionCleared"):
        raise AssertionError(f"Blank graph canvas click did not clear selected node state: {blank_graph}")
    if result.get("selectedNodeActionTitles", 0) < 3 or result.get("selectedNodeActionWideCount", 1) != 0 or result.get("selectedNodeActionHiddenLabels", 0) < 3:
        raise AssertionError(f"Selected node actions are not compact icon+tooltip controls: {result}")
    runtime_ide_href = str(result.get("runtimeIdeLinkHref") or "")
    runtime_ide_title = str(result.get("runtimeIdeLinkTitle") or "")
    if "/ide?" not in runtime_ide_href or "graph=atr_closed_loop" not in runtime_ide_href or "node=specimen" not in runtime_ide_href or "source=live_graph" not in runtime_ide_href:
        raise AssertionError(f"Live Graph Runtime IDE handoff link does not preserve graph/node context: href={runtime_ide_href!r} title={runtime_ide_title!r}")
    graph_validate_click = dispatch_live_graph_action(audit, "validate")
    graph_validate_status = wait_for_live_graph_gate_status(audit, "Graph Validate", timeout_s=8.0)
    if not graph_validate_status.get("ok"):
        raise AssertionError(f"Live Graph Validate did not complete through the graph gate card: {graph_validate_status}")
    graph_compile_click = dispatch_live_graph_action(audit, "compile")
    graph_compile_result = wait_for_live_action(audit, "graph.compiled", timeout_s=8.0)
    if not graph_compile_result.get("ok"):
        raise AssertionError(f"Live Graph Compile did not append graph.compiled runtime evidence: {graph_compile_result}")
    graph_save_click = dispatch_live_graph_action(audit, "save_version")
    graph_change_result = wait_for_live_action(audit, "graph_change_requested", timeout_s=8.0)
    graph_save_result = wait_for_live_action(audit, "graph_version_saved", timeout_s=8.0)
    if not graph_change_result.get("ok") or not graph_save_result.get("ok"):
        raise AssertionError(f"Live Graph Save Version did not record graph change/version evidence: change={graph_change_result} save={graph_save_result}")
    if result.get("artifactPanel") != "live-artifact-panel":
        raise AssertionError(f"Artifacts tab did not switch: {result}")
    if result.get("timelinePanel") != "live-timeline-detail-panel":
        raise AssertionError(f"Timeline tab did not switch: {result}")
    if result.get("warningTimelineItems", 0) < 1:
        raise AssertionError(f"Timeline warning filter did not keep warning events visible: {result}")
    selected_event_text = str(result.get("selectedEventText"))
    has_trace_context = "trace-approval-1" in selected_event_text or "trace-question-1" in selected_event_text
    if not has_trace_context or result.get("selectedEventActions", 0) < 5 or result.get("selectedTimelineItems", 0) < 1:
        raise AssertionError(f"Selected timeline event trace inspection did not render: {result}")
    timeline_target = result.get("selectedTimelineTargetProbe") or {}
    timeline_context = timeline_target.get("context") or {}
    if not timeline_context.get("selected_agent") or timeline_target.get("targetValue") != timeline_context.get("selected_agent") or timeline_context.get("chat_target") != timeline_context.get("selected_agent"):
        raise AssertionError(f"Timeline event selection did not retarget Runtime Chat to the event agent: {timeline_target}")
    blank_timeline = result.get("blankTimelineSelection") or {}
    blank_context = blank_timeline.get("context") or {}
    if blank_timeline.get("selectedTimelineItems") != 0 or "Click an event to inspect" not in str(blank_timeline.get("selectedEventText")) or blank_context.get("selected_event_key") or blank_context.get("trace_id") or (blank_timeline.get("saved") or {}).get("selectedEventKey"):
        raise AssertionError(f"Blank timeline click did not clear selected event/trace state: {blank_timeline}")
    if result.get("selectedEventActionTitles", 0) < result.get("selectedEventActions", 0) or result.get("selectedEventActionWideCount", 1) != 0:
        raise AssertionError(f"Selected event actions are not compact icon+tooltip controls: {result}")
    if result.get("selectedEventActionHiddenLabels", 0) < result.get("selectedEventActions", 0):
        raise AssertionError(f"Selected event action labels are not visually compacted: {result}")
    if not result.get("contextMenuVisible") or result.get("contextActions", 0) < 9:
        raise AssertionError(f"Binder context menu did not expose required actions: {result}")
    binder_ctrl_pin = result.get("binderCtrlPinProbe") or {}
    binder_ctrl_context = binder_ctrl_pin.get("context") or {}
    if not binder_ctrl_pin.get("clicked") or "BO Agent" not in str(binder_ctrl_pin.get("pinnedText")) or binder_ctrl_pin.get("targetValue") != "bo" or binder_ctrl_context.get("chat_target") != "bo" or "Ctrl/Cmd-click pin" not in str(binder_ctrl_pin.get("title")):
        raise AssertionError(f"Binder Ctrl/Cmd-click did not locally pin and retarget the selected agent report: {binder_ctrl_pin}")
    if "Analysis Agent" not in str(result.get("afterClickTitle")):
        raise AssertionError(f"Binder click did not select Analysis Agent: {result}")
    if result.get("afterDoublePanel") != "live-backend-panel" or "Guardian Agent" not in str(result.get("afterDoubleTitle")):
        raise AssertionError(f"Binder double-click did not open Guardian backend: {result}")
    persistent_chat = result.get("persistentChatProbe") or {}
    if persistent_chat.get("marker") != "1" or persistent_chat.get("role") != "log" or persistent_chat.get("ariaLive") != "polite":
        raise AssertionError(f"Runtime Chat log was unmounted or lost live-log semantics during navigation: {persistent_chat}")
    if int(persistent_chat.get("messageCount") or 0) < int(before.get("chatMessageCount") or 0) or not persistent_chat.get("includesInitialMessages"):
        raise AssertionError(f"Runtime Chat conversation did not persist while switching reports/backend/graph/timeline: {persistent_chat}")
    saved_ui_state = result.get("savedUiState") or {}
    if saved_ui_state.get("selectedAgent") != "guardian" or saved_ui_state.get("currentView") != "backend":
        raise AssertionError(f"Live GUI did not persist selected agent/view context: {saved_ui_state}")
    audit.open(f"{base_url.rstrip('/')}/live", wait_s=4.0)
    reload_probe = audit.js(
        r"""
        const snapshot = typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot() : {};
        const saved = JSON.parse(window.localStorage.getItem('autonomousLiveGuiUiState') || '{}');
        const activePanel = Array.from(document.querySelectorAll('.live-center-view')).find((el) => el.classList.contains('active'))?.id || '';
        const title = document.getElementById('live-center-title')?.textContent || '';
        const chatLog = document.getElementById('planning-chat-log');
        return {
          selectedAgent: snapshot.selected_agent || '',
          currentView: snapshot.current_view || '',
          activePanel,
          title,
          savedAgent: saved.selectedAgent || '',
          savedView: saved.currentView || '',
          planningSessionId: snapshot.planning_session_id || '',
          storedPlanningSessionId: window.localStorage.getItem('autonomousLivePlanningSessionId') || '',
          chatLogRole: chatLog?.getAttribute('role') || '',
          chatLogAriaLive: chatLog?.getAttribute('aria-live') || '',
          targetOptions: document.querySelectorAll('#live-chat-target option').length,
        };
        """
    )
    expected_reload_panel = {
        "report": "live-report-panel",
        "backend": "live-backend-panel",
        "graph": "live-graph-panel",
        "artifacts": "live-artifact-panel",
        "timeline": "live-timeline-detail-panel",
    }.get(str(reload_probe.get("savedView") or ""), "")
    if (
        reload_probe.get("selectedAgent") != reload_probe.get("savedAgent")
        or reload_probe.get("currentView") != reload_probe.get("savedView")
        or reload_probe.get("activePanel") != expected_reload_panel
        or "Guardian" not in str(reload_probe.get("title") or "")
        or reload_probe.get("chatLogRole") != "log"
        or reload_probe.get("chatLogAriaLive") != "polite"
        or int(reload_probe.get("targetOptions") or 0) < 10
    ):
        raise AssertionError(f"Live GUI did not restore selected agent/view/chat shell after reload: {reload_probe}")
    restore_after_reload = audit.js(
        r"""
        const payload = arguments[0];
        if (typeof window.__liveGuiDebugSetState !== 'function') return {ok: false, error: '__liveGuiDebugSetState missing after reload'};
        window.__liveGuiDebugSetState(payload);
        return typeof window.__liveGuiDebugSnapshot === 'function' ? {ok: true, snapshot: window.__liveGuiDebugSnapshot()} : {ok: false, error: 'debug snapshot missing after reload'};
        """,
        [sample_payload(run_id=run_id, approval_id=approval_id)],
    )
    if not restore_after_reload.get("ok"):
        raise AssertionError(f"Live GUI test fixture could not be restored after reload: {restore_after_reload}")
    result["reloadProbe"] = reload_probe
    dock_collapse = result.get("dockCollapseProbe") or {}
    dock_expand = result.get("dockExpandProbe") or {}
    if not dock_collapse.get("collapsed") or dock_collapse.get("buttonExpanded") != "false":
        raise AssertionError(f"Bottom Event/IO dock did not collapse: {result}")
    if int(dock_collapse.get("chatHeight", 0)) <= int(result.get("chatHeightBeforeDockCollapse") or 0):
        raise AssertionError(f"Collapsing bottom dock did not increase Runtime Chat vertical space: {result}")
    if int(dock_collapse.get("bottomHeight", 9999)) >= int(result.get("bottomHeightBeforeDockCollapse") or 0):
        raise AssertionError(f"Collapsing bottom dock did not reduce bottom area height: {result}")
    if dock_expand.get("collapsed") or dock_expand.get("buttonExpanded") != "true":
        raise AssertionError(f"Bottom Event/IO dock did not expand back to normal view: {result}")
    if result.get("bodyWidth", 0) > result.get("viewportWidth", 0) + 24:
        raise AssertionError(f"Unexpected large horizontal overflow: {result}")
    visual = result.get("visual") or before.get("visual") or {}
    binder_rect = visual.get("binderRect") or {}
    center_rect = visual.get("centerRect") or {}
    chat_rect = visual.get("chatRect") or {}
    bottom_rect = visual.get("bottomRect") or {}
    safe_stop_rect = visual.get("safeStopRect") or {}
    if "planning-live-body" not in str(visual.get("bodyClass")):
        raise AssertionError(f"Live GUI dark runtime body class is missing: {result}")
    if abs(int(binder_rect.get("width", 0)) - 196) > 2:
        raise AssertionError(f"Agentic Binder width no longer matches reference layout: {visual}")
    if not (int(binder_rect.get("left", 9999)) < int(center_rect.get("left", 0)) < int(chat_rect.get("left", 0))):
        raise AssertionError(f"Live GUI columns are not ordered binder -> center -> chat: {visual}")
    if int(center_rect.get("width", 0)) < 500 or int(chat_rect.get("width", 0)) < 460:
        raise AssertionError(f"Center/chat panels are too narrow for operational use: {visual}")
    ratio = int(center_rect.get("width", 1)) / max(int(chat_rect.get("width", 1)), 1)
    if not (0.75 <= ratio <= 1.35):
        raise AssertionError(f"Center/chat panel ratio drifted from reference three-zone layout: ratio={ratio}, visual={visual}")
    if int(bottom_rect.get("top", 0)) <= int(center_rect.get("top", 0)):
        raise AssertionError(f"Runtime timeline is not below main panels: {visual}")
    header_rect = visual.get("headerRect") or {}
    title_rect = visual.get("titleRect") or {}
    title_h1_rect = visual.get("titleH1Rect") or {}
    if not visual.get("titleEyebrowVisible") or int(title_h1_rect.get("width", 0)) < 54:
        raise AssertionError(f"Live header product identity/title tile is clipped or missing: {visual}")
    if visual.get("headerBeforeDisplay") != "none" or visual.get("headerAfterDisplay") != "none":
        raise AssertionError(f"Live header decorative overlays should not cover the title or metrics: {visual}")
    if int(visual.get("headerMetricRows") or 99) > 2:
        raise AssertionError(f"Live header metrics should fit into at most two stable rows: {visual}")
    too_narrow_metrics = [item for item in (visual.get("metricRects") or []) if item.get("id") != "planning-state-dot" and int(item.get("width") or 0) < 42]
    if too_narrow_metrics:
        raise AssertionError(f"Live header metric chip is clipped too aggressively: {visual}")
    if int(title_rect.get("top", 0)) < int(header_rect.get("top", 0)) or int(title_rect.get("bottom", 9999)) > int(header_rect.get("bottom", 0)):
        raise AssertionError(f"Live title tile escapes the header bounds: {visual}")
    if int(safe_stop_rect.get("width", 0)) < 72 or int(safe_stop_rect.get("height", 0)) < 52:
        raise AssertionError(f"Safe Stop is not visibly accessible in the header: {visual}")
    if float(visual.get("titleContrastOnPanel") or 0) < 3.0:
        raise AssertionError(f"Live GUI title contrast is too low for reference-style dark UI: {visual}")

    # Pending human approval must block execution-starting actions before the operator resolves it.
    audit.js(
        r"""
        const payload = arguments[0];
        if (typeof window.__liveGuiDebugSetState !== 'function') return {ok: false, error: '__liveGuiDebugSetState missing'};
        window.__liveGuiDebugSetState(payload);
        return {ok: true, pending: (window.__liveGuiDebugSnapshot().approvals || {}).pending || []};
        """,
        [sample_payload(run_id=run_id, approval_id=approval_id)],
    )
    blocked_graph_click = dispatch_live_graph_action(audit, "run_test")
    blocked_execution_result = wait_for_live_action_for_run(audit, "approval.blocked_execution", run_id, source_action="live_graph.run_test", blocked_action="live_graph.run_test", timeout_s=8.0)
    if not blocked_execution_result.get("ok"):
        raise AssertionError(f"Pending approval did not block Live Graph Run Test execution: click={blocked_graph_click} result={blocked_execution_result}")
    blocked_payload = ((blocked_execution_result.get("hit") or {}).get("payload") or {})
    if blocked_payload.get("blocked_action") != "live_graph.run_test" or blocked_payload.get("source_action") != "live_graph.run_test" or not blocked_payload.get("pending_approval_id"):
        raise AssertionError(f"Approval execution block event payload is incomplete: {blocked_execution_result}")

    # Exercise actions that must hit real backend APIs, not just render visible buttons.
    action_start = audit.js(
        r"""
        const approve = document.querySelector('#live-quick-actions .live-quick-action[data-quick-action="approve_next_step"]');
        const dry = document.querySelector('#live-quick-actions .live-quick-action[data-quick-action="dry_run"]');
        const pause = document.querySelector('#live-quick-actions .live-quick-action[data-quick-action="pause_run"]');
        const resume = document.querySelector('#live-quick-actions .live-quick-action[data-quick-action="resume_run"]');
        const safeStop = document.querySelector('#btn-live-safe-stop');
        if (!approve || !dry || !pause || !resume || !safeStop) return {ok: false, error: 'approve_next_step, dry_run, pause_run, resume_run, or safe stop button missing'};
        approve.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        window.__liveActionAuditDryButton = dry;
        window.__liveActionAuditPauseButton = pause;
        window.__liveActionAuditResumeButton = resume;
        window.__liveActionAuditSafeStopButton = safeStop;
        return {ok: true};
        """
    )
    if not action_start.get("ok"):
        raise AssertionError(f"Live GUI API action buttons are missing: {action_start}")
    approval_result = wait_for_live_action(audit, "approval.resolved", timeout_s=8.0)
    if not approval_result.get("ok"):
        raise AssertionError(f"Live GUI approval quick action did not append runtime evidence: {approval_result}")

    revise_approval = http_json(
        base_url,
        f"/api/runs/{run_id}/approvals",
        method="POST",
        payload={
            "title": "Live GUI browser audit revision approval",
            "reason": "Verify Revise quick action resolves a pending approval through backend evidence",
            "stage": "guardian",
            "safety_class": "browser_audit",
            "requester": "live_runtime_ide_browser_audit",
        },
        timeout_s=10.0,
    )
    revise_approval_id = str(revise_approval.get("approval_id") or "approval-revise-ui")
    deadline = time.time() + 3.0
    while time.time() < deadline:
        ready = audit.js(
            r"""
            const revise = document.querySelector('#live-quick-actions .live-quick-action[data-quick-action="revise"]');
            return Boolean(revise && !revise.disabled);
            """
        )
        if ready:
            break
        time.sleep(0.1)
    revise_start = audit.js(
        r"""
        const payload = arguments[0];
        if (typeof window.__liveGuiDebugSetState !== 'function') return {ok: false, error: '__liveGuiDebugSetState missing'};
        window.__liveGuiDebugSetState(payload);
        const revise = document.querySelector('#live-quick-actions .live-quick-action[data-quick-action="revise"]');
        const reviseCard = document.querySelector('#live-approval-panel .live-approval-action[data-decision="cancelled"]');
        if (!revise || !reviseCard) return {ok: false, error: 'revise quick action or approval card action missing'};
        if (revise.disabled) return {ok: false, error: 'revise quick action is disabled'};
        revise.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        return {ok: true};
        """,
        [sample_payload(run_id=run_id, approval_id=revise_approval_id)],
    )
    if not revise_start.get("ok"):
        raise AssertionError(f"Live GUI Revise action is not available: {revise_start}")
    revise_result = wait_for_live_approval_decision(audit, revise_approval_id, "cancelled", timeout_s=8.0)
    if not revise_result.get("ok"):
        raise AssertionError(f"Live GUI Revise quick action did not resolve approval through backend evidence: {revise_result}")
    audit.js(
        r"""
        const payload = arguments[0];
        if (typeof window.__liveGuiDebugSetState !== 'function') return {ok: false, error: '__liveGuiDebugSetState missing'};
        payload.approvals = {approvals: [], pending: [], resolved: [{approval_id: arguments[1], decision: 'cancelled'}]};
        window.__liveGuiDebugSetState(payload);
        return {ok: true, pending: (window.__liveGuiDebugSnapshot().approvals || {}).pending || []};
        """,
        [sample_payload(run_id=run_id, approval_id=revise_approval_id), revise_approval_id],
    )

    dispatch_live_quick_action(audit, "dry_run")
    command_result = wait_for_live_action(audit, "runtime_command_requested", timeout_s=8.0)
    if not command_result.get("ok"):
        raise AssertionError(f"Live GUI dry-run did not record the required runtime_command_requested intent event: {command_result}")
    dry_result = wait_for_live_action(audit, "graph.dry_run", timeout_s=8.0)
    if not dry_result.get("ok"):
        raise AssertionError(f"Live GUI dry-run quick action did not append runtime evidence: {dry_result}")
    dispatch_live_selected_node_action(audit, "run_node_test")
    rerun_result = wait_for_live_action_exact(audit, "node_rerun_requested", timeout_s=8.0)
    blocked_node_test_result = wait_for_live_action_exact(audit, "approval.blocked_execution", timeout_s=8.0)
    if not rerun_result.get("ok") and not blocked_node_test_result.get("ok"):
        raise AssertionError(f"Live GUI node-test did not record the required node_rerun_requested intent event or an approval block: rerun={rerun_result} blocked={blocked_node_test_result}")
    if blocked_node_test_result.get("ok"):
        node_result = blocked_node_test_result
    else:
        node_result = wait_for_live_action(audit, "module.node_test", timeout_s=8.0)
        if not node_result.get("ok"):
            raise AssertionError(f"Live GUI node-test quick action did not append runtime evidence: {node_result}")
    dispatch_live_quick_action(audit, "pause_run")
    pause_result = wait_for_live_action(audit, "run_pause", timeout_s=8.0)
    if not pause_result.get("ok"):
        raise AssertionError(f"Live GUI pause quick action did not append runtime evidence: {pause_result}")
    audit.js(
        r"""
        const payload = arguments[0];
        if (typeof window.__liveGuiDebugSetState !== 'function') return {ok: false, error: '__liveGuiDebugSetState missing'};
        payload.approvals = {approvals: [], pending: [], resolved: []};
        window.__liveGuiDebugSetState(payload);
        return {ok: true, pending: (window.__liveGuiDebugSnapshot().approvals || {}).pending || []};
        """,
        [sample_payload(run_id=run_id, approval_id="approval-cleared-before-resume")],
    )
    dispatch_live_quick_action(audit, "resume_run")
    resume_result = wait_for_live_action(audit, "run_resume", timeout_s=8.0)
    if not resume_result.get("ok"):
        raise AssertionError(f"Live GUI resume quick action did not append runtime evidence: {resume_result}")
    audit.js(
        r"""
        const payload = arguments[0];
        if (typeof window.__liveGuiDebugSetState !== 'function') return {ok: false, error: '__liveGuiDebugSetState missing'};
        payload.approvals = {approvals: [], pending: [], resolved: []};
        window.__liveGuiDebugSetState(payload);
        return {ok: true, pending: (window.__liveGuiDebugSnapshot().approvals || {}).pending || []};
        """,
        [sample_payload(run_id=run_id, approval_id="approval-cleared-before-graph-run")],
    )
    graph_run_click = dispatch_live_graph_action(audit, "run_test")
    graph_run_request = wait_for_live_action(audit, "graph_run_requested", timeout_s=8.0)
    graph_run_status = wait_for_live_graph_gate_status(audit, "Graph Run Test", timeout_s=10.0)
    graph_run_payload = (graph_run_request.get("hit") or {}).get("payload") or {}
    if not graph_run_request.get("ok") or graph_run_payload.get("mode") != "test" or graph_run_payload.get("source_action") != "live_graph.run_test":
        raise AssertionError(f"Live Graph Run Test did not record test-mode runtime intent evidence: click={graph_run_click} request={graph_run_request}")
    graph_run_status_text = str(graph_run_status.get("text") or "")
    if not graph_run_status.get("ok") or "mode" not in graph_run_status_text or "test" not in graph_run_status_text or "run_id" not in graph_run_status_text:
        raise AssertionError(f"Live Graph Run Test did not show backend run status in the graph gate card: {graph_run_status}")

    safe_stop_arm = audit.js(
        r"""
        const button = document.querySelector('#btn-live-safe-stop') || window.__liveActionAuditSafeStopButton;
        if (!button) return {ok: false, error: 'safe stop button missing'};
        button.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        const buttonRect = button.getBoundingClientRect();
        const headerRect = document.querySelector('.live-runtime-header')?.getBoundingClientRect();
        return {
          ok: button.classList.contains('is-armed') && button.textContent.includes('CONFIRM'),
          className: button.className,
          text: button.textContent,
          title: button.getAttribute('title') || '',
          rect: {left: Math.round(buttonRect.left), right: Math.round(buttonRect.right), width: Math.round(buttonRect.width), height: Math.round(buttonRect.height)},
          headerRect: headerRect ? {left: Math.round(headerRect.left), right: Math.round(headerRect.right), width: Math.round(headerRect.width), height: Math.round(headerRect.height)} : null,
        };
        """
    )
    if not safe_stop_arm.get("ok"):
        raise AssertionError(f"Live GUI safe-stop first click did not arm confirmation state: {safe_stop_arm}")
    armed_rect = safe_stop_arm.get("rect") or {}
    armed_header_rect = safe_stop_arm.get("headerRect") or {}
    if int(armed_rect.get("width", 0)) < 130 or int(armed_rect.get("width", 0)) > 170 or int(armed_rect.get("height", 0)) < 52:
        raise AssertionError(f"Live GUI armed safe-stop button no longer fits the reference header slot: {safe_stop_arm}")
    if int(armed_rect.get("right", 9999)) > int(armed_header_rect.get("right", 0)) + 2:
        raise AssertionError(f"Live GUI armed safe-stop button escapes the header bounds: {safe_stop_arm}")
    audit.js("window.__liveActionAuditSafeStopButton.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));")
    safe_stop_result = wait_for_live_action(audit, "run_safe_stop", timeout_s=8.0)
    if not safe_stop_result.get("ok"):
        raise AssertionError(f"Live GUI safe-stop button did not append runtime evidence: {safe_stop_result}")

    screenshot_path = out_dir / "live_runtime_ide_browser_audit.png"
    audit.screenshot(screenshot_path)
    live_metrics = image_visual_metrics(screenshot_path)
    reference_metrics = image_visual_metrics(LIVE_REFERENCE_IMAGE)
    distance = rgb_distance(tuple(live_metrics["mean_rgb"]), tuple(reference_metrics["mean_rgb"]))
    visual_reference = {"live": live_metrics, "reference": reference_metrics, "rgb_distance": distance}
    if max(live_metrics["mean_rgb"]) > 72:
        raise AssertionError(f"Live GUI screenshot is too bright compared with dark reference: {visual_reference}")
    if live_metrics["bright_ratio"] > 0.08:
        raise AssertionError(f"Live GUI has too much white/light surface area for the reference theme: {visual_reference}")
    if distance > 42:
        raise AssertionError(f"Live GUI screenshot color profile drifted from the reference image: {visual_reference}")
    result["api_actions"] = {"approval_block": blocked_execution_result, "report_pin": report_pin_result, "binder_pin": binder_pin_result, "report_ask": ask_result, "approval": approval_result, "revise": revise_result, "graph_validate": graph_validate_status, "graph_compile": graph_compile_result, "graph_save": graph_save_result, "graph_change": graph_change_result, "graph_run_request": graph_run_request, "graph_run_status": graph_run_status, "runtime_command": command_result, "dry_run": dry_result, "node_rerun": rerun_result, "node_test": node_result, "pause": pause_result, "resume": resume_result, "safe_stop": safe_stop_result}
    result["visual_reference"] = visual_reference
    return result




def dispatch_live_quick_action(audit: WebDriverAudit, action: str, *, timeout_s: float = 4.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = audit.js(
            r"""
            const action = arguments[0];
            const button = document.querySelector(`#live-quick-actions .live-quick-action[data-quick-action="${action}"]`);
            return {ok: Boolean(button && !button.disabled), exists: Boolean(button), disabled: Boolean(button && button.disabled), action};
            """,
            [action],
        )
        if last.get("ok"):
            result = audit.js(
                r"""
                const action = arguments[0];
                const button = document.querySelector(`#live-quick-actions .live-quick-action[data-quick-action="${action}"]`);
                if (!button || button.disabled) return {ok: false, exists: Boolean(button), disabled: Boolean(button && button.disabled), action};
                button.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                return {ok: true, action};
                """,
                [action],
            )
            if result.get("ok"):
                return result
            last = result
        time.sleep(0.15)
    raise AssertionError(f"Live GUI quick action {action!r} was not clickable: {last}")


def dispatch_live_selected_node_action(audit: WebDriverAudit, action: str, *, node_id: str = "specimen", timeout_s: float = 4.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = audit.js(
            r"""
            const action = arguments[0];
            const nodeId = arguments[1];
            const graphTab = document.querySelector('[data-live-view="graph"]');
            if (graphTab) graphTab.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
            const node = document.querySelector(`#live-graph-panel .live-graph-mini-node[data-graph-node-id="${nodeId}"]`);
            if (node) node.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
            const button = document.querySelector(`#live-graph-panel .live-selected-node-action[data-context-action="${action}"]`);
            return {ok: Boolean(button && !button.disabled), exists: Boolean(button), disabled: Boolean(button && button.disabled), action, nodeId};
            """,
            [action, node_id],
        )
        if last.get("ok"):
            result = audit.js(
                r"""
                const action = arguments[0];
                const button = document.querySelector(`#live-graph-panel .live-selected-node-action[data-context-action="${action}"]`);
                if (!button || button.disabled) return {ok: false, exists: Boolean(button), disabled: Boolean(button && button.disabled), action};
                button.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                return {ok: true, action};
                """,
                [action],
            )
            if result.get("ok"):
                return result
            last = result
        time.sleep(0.15)
    raise AssertionError(f"Live GUI selected-node action {action!r} was not clickable: {last}")


def dispatch_live_graph_action(audit: WebDriverAudit, action: str, *, timeout_s: float = 4.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = audit.js(
            r"""
            const action = arguments[0];
            const graphTab = document.querySelector('[data-live-view="graph"]');
            if (graphTab) graphTab.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
            const button = document.querySelector(`#live-graph-panel .live-graph-action[data-graph-action="${action}"]`);
            return {ok: Boolean(button && !button.disabled), exists: Boolean(button), disabled: Boolean(button && button.disabled), action};
            """,
            [action],
        )
        if last.get("ok"):
            result = audit.js(
                r"""
                const action = arguments[0];
                const button = document.querySelector(`#live-graph-panel .live-graph-action[data-graph-action="${action}"]`);
                if (!button || button.disabled) return {ok: false, exists: Boolean(button), disabled: Boolean(button && button.disabled), action};
                button.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                return {ok: true, action};
                """,
                [action],
            )
            if result.get("ok"):
                return result
            last = result
        time.sleep(0.15)
    raise AssertionError(f"Live GUI graph action {action!r} was not clickable: {last}")


def wait_for_live_graph_gate_status(audit: WebDriverAudit, label: str, *, timeout_s: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = audit.js(
            r"""
            const label = arguments[0];
            const card = document.querySelector('#live-graph-panel .live-graph-action-status');
            const text = card ? card.textContent : '';
            const className = card ? card.className : '';
            const successful = text.includes('ok') || text.includes('started') || className.includes('ok');
            return {ok: Boolean(card && text.includes(label) && successful), label, text, className};
            """,
            [label],
        )
        if last.get("ok"):
            return last
        time.sleep(0.25)
    return last or {"ok": False, "label": label}


def wait_for_live_action(audit: WebDriverAudit, event_type: str, *, timeout_s: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = audit.js(
            r"""
            const wanted = arguments[0];
            const snapshot = typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot() : {};
            const runEvents = Array.isArray(snapshot.run_events) ? snapshot.run_events : [];
            const recentEvents = Array.isArray(snapshot.recent_events) ? snapshot.recent_events : [];
            const events = runEvents.concat(recentEvents);
            const hit = events.slice().reverse().find((event) => String(event.event_type || event.type || '').includes(wanted));
            return {
              ok: Boolean(hit),
              wanted,
              hit: hit || null,
              status: snapshot.chat_status || document.getElementById('planning-chat-status')?.textContent || '',
              timelineText: document.getElementById('live-timeline-strip')?.textContent || '',
            };
            """,
            [event_type],
        )
        if last.get("ok"):
            return last
        time.sleep(0.25)
    return last or {"ok": False, "wanted": event_type}

def wait_for_live_action_exact(audit: WebDriverAudit, event_type: str, *, timeout_s: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = audit.js(
            r"""
            const wanted = arguments[0];
            const snapshot = typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot() : {};
            const runEvents = Array.isArray(snapshot.run_events) ? snapshot.run_events : [];
            const recentEvents = Array.isArray(snapshot.recent_events) ? snapshot.recent_events : [];
            const events = runEvents.concat(recentEvents);
            const hit = events.slice().reverse().find((event) => String(event.event_type || event.type || '') === wanted);
            return {
              ok: Boolean(hit),
              wanted,
              hit: hit || null,
              status: snapshot.chat_status || document.getElementById('planning-chat-status')?.textContent || '',
              timelineText: document.getElementById('live-timeline-strip')?.textContent || '',
            };
            """,
            [event_type],
        )
        if last.get("ok"):
            return last
        time.sleep(0.25)
    return last or {"ok": False, "wanted": event_type}


def wait_for_live_action_for_run(audit: WebDriverAudit, event_type: str, run_id: str, *, source_action: str = "", blocked_action: str = "", timeout_s: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = audit.js(
            r"""
            const wanted = arguments[0];
            const runId = arguments[1];
            const sourceAction = arguments[2];
            const blockedAction = arguments[3];
            const snapshot = typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot() : {};
            const runEvents = Array.isArray(snapshot.run_events) ? snapshot.run_events : [];
            const recentEvents = Array.isArray(snapshot.recent_events) ? snapshot.recent_events : [];
            const events = runEvents.concat(recentEvents);
            const hit = events.slice().reverse().find((event) => {
              const payload = event && typeof event.payload === 'object' && event.payload ? event.payload : {};
              if (!String(event.event_type || event.type || '').includes(wanted)) return false;
              if (runId && String(event.run_id || payload.run_id || '') !== String(runId)) return false;
              if (sourceAction && String(payload.source_action || '') !== String(sourceAction)) return false;
              if (blockedAction && String(payload.blocked_action || '') !== String(blockedAction)) return false;
              return true;
            });
            return {
              ok: Boolean(hit),
              wanted,
              run_id: runId,
              source_action: sourceAction,
              blocked_action: blockedAction,
              hit: hit || null,
              status: snapshot.chat_status || document.getElementById('planning-chat-status')?.textContent || '',
              timelineText: document.getElementById('live-timeline-strip')?.textContent || '',
            };
            """,
            [event_type, run_id, source_action, blocked_action],
        )
        if last.get("ok"):
            return last
        time.sleep(0.25)
    return last or {"ok": False, "wanted": event_type, "run_id": run_id}


def wait_for_live_approval_decision(audit: WebDriverAudit, approval_id: str, decision: str, *, timeout_s: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = audit.js(
            r"""
            const approvalId = arguments[0];
            const decision = arguments[1];
            const snapshot = typeof window.__liveGuiDebugSnapshot === 'function' ? window.__liveGuiDebugSnapshot() : {};
            const events = Array.isArray(snapshot.run_events) ? snapshot.run_events : [];
            function payloadOf(event) { return event && typeof event.payload === 'object' && event.payload ? event.payload : {}; }
            function nestedPayloadOf(payload) { return payload && payload.event && typeof payload.event.payload === 'object' ? payload.event.payload : {}; }
            const hit = events.slice().reverse().find((event) => {
              const type = String(event.event_type || event.type || '');
              const payload = payloadOf(event);
              const nested = nestedPayloadOf(payload);
              const eventPayload = payloadOf(payload.event || {});
              const actualApprovalId = String(payload.approval_id || nested.approval_id || eventPayload.approval_id || '');
              const actualDecision = String(payload.decision || nested.decision || eventPayload.decision || '');
              return type.includes('approval.resolved') && actualApprovalId === approvalId && actualDecision === decision;
            });
            return {
              ok: Boolean(hit),
              approval_id: approvalId,
              decision,
              hit: hit || null,
              status: snapshot.chat_status || document.getElementById('planning-chat-status')?.textContent || '',
              timelineText: document.getElementById('live-timeline-strip')?.textContent || '',
            };
            """,
            [approval_id, decision],
        )
        if last.get("ok"):
            return last
        time.sleep(0.25)
    return last or {"ok": False, "approval_id": approval_id, "decision": decision}


def scenario_evolution_lab(audit: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    audit.open(f"{base_url.rstrip('/')}/evolution-lab?target_type=prompt&target_id=design&source=browser_audit", wait_s=2.0)
    result = audit.js(
        r"""
        try {
          function visible(id) {
            const el = document.getElementById(id);
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
          }
          return {
            ok: true,
            title: document.querySelector('h1')?.textContent || '',
            targetValue: document.getElementById('evolution-target-input')?.value || '',
            statusLabel: document.getElementById('evolution-status-label')?.textContent || '',
            pipelineVisible: visible('evolution-pipeline-output'),
            leaderboardVisible: visible('evolution-leaderboard-output'),
            historyVisible: visible('evolution-history-output'),
            lineageVisible: visible('evolution-lineage-output'),
            outputVisible: visible('evolution-output'),
            pipelineSteps: document.querySelectorAll('#evolution-pipeline-output .evolution-pipeline-step').length,
            leaderboardText: document.getElementById('evolution-leaderboard-output')?.textContent || '',
            gateText: document.getElementById('evolution-candidate-summary')?.textContent || '',
            bodyWidth: document.body.scrollWidth,
            viewportWidth: window.innerWidth,
          };
        } catch (err) {
          return {ok: false, error: String(err && err.message ? err.message : err), stack: String(err && err.stack ? err.stack : '')};
        }
        """
    )
    if not result.get("ok"):
        raise AssertionError(result)
    if "Self-Evolution Lab" not in str(result.get("title")):
        raise AssertionError(f"Evolution Lab title is missing: {result}")
    for key in ["pipelineVisible", "leaderboardVisible", "historyVisible", "lineageVisible", "outputVisible"]:
        if not result.get(key):
            raise AssertionError(f"Evolution Lab panel {key} is not visible: {result}")
    if result.get("pipelineSteps") != 6:
        raise AssertionError(f"Evolution pipeline should render 6 steps: {result}")
    if "No candidates" not in str(result.get("leaderboardText")) and "score=" not in str(result.get("leaderboardText")):
        raise AssertionError(f"Candidate leaderboard did not render candidate/empty state: {result}")
    if result.get("bodyWidth", 0) > result.get("viewportWidth", 0) + 24:
        raise AssertionError(f"Evolution Lab has unexpected horizontal overflow: {result}")
    audit.screenshot(out_dir / "evolution_lab_browser_audit.png")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7862")
    parser.add_argument("--webdriver-url", default="http://127.0.0.1:4448")
    parser.add_argument("--out-dir", default="artifacts/ui")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1200)
    args = parser.parse_args()

    audit = WebDriverAudit(args.webdriver_url, width=args.width, height=args.height)
    try:
        audit.start()
        out_dir = Path(args.out_dir)
        result = scenario_live_runtime_ide(audit, args.base_url, out_dir)
        evolution_result = scenario_evolution_lab(audit, args.base_url, out_dir)
        print("live_runtime_ide_browser_audit: PASS")
        print({"live": result, "evolution_lab": evolution_result})
        return 0
    finally:
        time.sleep(0.1)
        audit.stop()
        cleanup_live_audit_draft_module()


if __name__ == "__main__":
    raise SystemExit(main())
