from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import re
import tempfile
import tkinter as tk
from tkinter import ttk
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parent / "advanced_visual_work_queue_runtime"
RUNTIME_ROOT = Path(os.environ.get("ATR_ADVANCED_QUEUE_ROOT", DEFAULT_ROOT)).expanduser().resolve()
MODE_PATH = RUNTIME_ROOT / "mode.txt"
STATUS_PATH = RUNTIME_ROOT / "status.json"
OUTPUT_ROOT = RUNTIME_ROOT / "output"
SUPPORTED_MODES = {"initial", "shifted", "reordered", "shifted_reordered", "missing_target"}
SPECIMENS = (
    ("specimen-alpha", "A-17", "validated"),
    ("specimen-beta", "B-42", "validated"),
    ("specimen-gamma", "C-08", "validated"),
    ("specimen-delta", "D-31", "validated"),
)


def normalize_mode(raw: str) -> str:
    value = str(raw or "").strip().lower()
    for suffix in ("_reset", "-reset"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    return value if value in SUPPORTED_MODES else "initial"


def specimens_for_mode(mode: str) -> list[tuple[str, str, str]]:
    rows = list(SPECIMENS)
    if mode in {"reordered", "shifted_reordered"}:
        rows.reverse()
    if mode == "missing_target":
        rows = [row for row in rows if row[0] != "specimen-beta"]
    return rows


def validated_batch_summary() -> str:
    return f"validated-batch-2026-08 · {len(SPECIMENS)} records · schema valid"


def stable_button_style(background: str, foreground: str = "white") -> dict[str, str]:
    """Keep image-recorded controls visually stable while the pointer hovers."""
    return {
        "bg": background,
        "fg": foreground,
        "activebackground": background,
        "activeforeground": foreground,
    }


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def analysis_result(specimen_id: str, method: str, evidence: bool, load_limit: str) -> dict[str, object]:
    specimen = specimen_id.strip()
    selected_method = method.strip()
    try:
        numeric_limit = float(str(load_limit).strip())
    except ValueError as exc:
        raise ValueError("load limit must be numeric") from exc
    if numeric_limit <= 0:
        raise ValueError("load limit must be positive")
    if not specimen:
        raise ValueError("specimen id is required")
    if not selected_method:
        raise ValueError("method is required")
    return {
        "specimen_id": specimen,
        "method": selected_method,
        "evidence_enabled": bool(evidence),
        "load_limit": numeric_limit,
    }


def write_exports(output_root: Path, base_name: str, result: dict[str, object]) -> dict[str, str]:
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", base_name.strip()).strip("_")
    if not safe_name:
        raise ValueError("output name is required")
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / f"{safe_name}.json"
    csv_path = output_root / f"{safe_name}.csv"
    atomic_write_text(json_path, json.dumps(result, ensure_ascii=True, indent=2) + "\n")
    with tempfile.NamedTemporaryFile("w", newline="", delete=False, dir=output_root, encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result))
        writer.writeheader()
        writer.writerow({**result, "evidence_enabled": str(bool(result["evidence_enabled"])).lower()})
        temporary = Path(handle.name)
    temporary.replace(csv_path)
    return {"json": str(json_path), "csv": str(csv_path)}


class AdvancedVisualWorkQueue:
    COLORS = {
        "background": "#0b1424",
        "panel": "#111f34",
        "panel_alt": "#172942",
        "line": "#2c4969",
        "text": "#edf5ff",
        "muted": "#9db1ca",
        "blue": "#2767df",
        "green": "#1fab73",
        "amber": "#e4a72b",
        "red": "#d9485f",
        "violet": "#7357d9",
    }

    def __init__(self) -> None:
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = tk.Tk()
        self.root.title("ATR Advanced Visual Work Queue")
        self.root.configure(bg=self.COLORS["background"])
        self.root.attributes("-topmost", True)
        self.mode_token = ""
        self.mode = "initial"
        self.dialogs: dict[str, tk.Toplevel] = {}
        self.source_widgets: list[tk.Widget] = []
        self.selected_batch = ""
        self.selected_specimen = ""
        self.drag_specimen = ""
        self.queue: list[str] = []
        self.method = "Compression"
        self.evidence_enabled = False
        self.evidence_click_ignored = False
        self.load_limit = "12.5"
        self.analysis_attempts = 0
        self.recovery_count = 0
        self.result: dict[str, object] = {}
        self.exports: dict[str, str] = {}
        self.state = "waiting"
        self.progress_value = 0

        self._build_main_surface()
        self._poll_mode()

    def _build_main_surface(self) -> None:
        c = self.COLORS
        tk.Label(
            self.root,
            text="ATR ADVANCED VISUAL WORK QUEUE",
            bg=c["background"],
            fg=c["text"],
            font=("DejaVu Sans", 24, "bold"),
        ).place(x=36, y=24)
        tk.Label(
            self.root,
            text="Identity-grounded selection · visual drag · bounded recovery · verified export",
            bg=c["background"],
            fg=c["muted"],
            font=("DejaVu Sans", 12),
        ).place(x=39, y=68)

        self.input_button = tk.Button(
            self.root,
            text="OPEN INPUT BROWSER",
            command=self.open_input_browser,
            **stable_button_style(c["blue"]),
            relief="flat",
            font=("DejaVu Sans", 13, "bold"),
        )
        self.input_button.place(x=40, y=112, width=245, height=54)
        self.batch_label = tk.Label(
            self.root,
            text="No validated batch selected",
            bg=c["panel"],
            fg=c["amber"],
            anchor="w",
            padx=14,
            font=("DejaVu Sans", 12, "bold"),
        )
        self.batch_label.place(x=300, y=112, width=720, height=54)

        self.source_panel = tk.Frame(self.root, bg=c["panel"], highlightbackground=c["line"], highlightthickness=1)
        self.source_panel.place(x=40, y=198, width=440, height=320)
        tk.Label(
            self.source_panel,
            text="VALIDATED SPECIMEN TABLE",
            bg=c["panel"],
            fg=c["text"],
            font=("DejaVu Sans", 14, "bold"),
        ).place(x=18, y=16)
        tk.Label(
            self.source_panel,
            text="Select by identity, then drag the row card",
            bg=c["panel"],
            fg=c["muted"],
            font=("DejaVu Sans", 10),
        ).place(x=18, y=45)
        self.rows_frame = tk.Frame(self.source_panel, bg=c["panel"])
        self.rows_frame.place(x=18, y=78, width=402, height=224)

        self.queue_panel = tk.Frame(self.root, bg=c["panel"], highlightbackground=c["line"], highlightthickness=1)
        self.queue_panel.place(x=500, y=198, width=520, height=320)
        tk.Label(
            self.queue_panel,
            text="ANALYSIS QUEUE",
            bg=c["panel"],
            fg=c["text"],
            font=("DejaVu Sans", 14, "bold"),
        ).place(x=18, y=16)
        tk.Label(
            self.queue_panel,
            text="Drop one validated specimen into this lane",
            bg=c["panel"],
            fg=c["muted"],
            font=("DejaVu Sans", 10),
        ).place(x=18, y=45)
        self.queue_lane = tk.Label(
            self.queue_panel,
            text="DROP SPECIMEN HERE",
            bg="#0d192b",
            fg="#76a7ee",
            highlightbackground="#3473c8",
            highlightthickness=2,
            font=("DejaVu Sans", 17, "bold"),
        )
        self.queue_lane.place(x=18, y=82, width=484, height=120)
        self.config_button = tk.Button(
            self.queue_panel,
            text="CONFIGURE QUEUED ITEM",
            command=self.open_config_dialog,
            state="disabled",
            **stable_button_style(c["violet"]),
            disabledforeground="#6c7890",
            relief="flat",
            font=("DejaVu Sans", 12, "bold"),
        )
        self.config_button.place(x=18, y=224, width=230, height=54)
        self.start_button = tk.Button(
            self.queue_panel,
            text="START ANALYSIS",
            command=self.start_analysis,
            state="disabled",
            **stable_button_style(c["green"]),
            disabledforeground="#6c7890",
            relief="flat",
            font=("DejaVu Sans", 12, "bold"),
        )
        self.start_button.place(x=270, y=224, width=232, height=54)

        self.validation_button = tk.Button(
            self.root,
            text="EVIDENCE REQUIRED · REOPEN CONFIG",
            command=self.open_config_dialog,
            **stable_button_style(c["red"]),
            relief="flat",
            font=("DejaVu Sans", 12, "bold"),
        )
        self.progress = ttk.Progressbar(self.root, orient="horizontal", mode="determinate", maximum=100)
        self.result_label = tk.Label(
            self.root,
            text="WAITING FOR VALIDATED INPUT",
            bg=c["panel_alt"],
            fg=c["muted"],
            anchor="w",
            padx=16,
            font=("DejaVu Sans", 13, "bold"),
        )
        self.result_label.place(x=40, y=574, width=730, height=76)
        self.export_button = tk.Button(
            self.root,
            text="EXPORT RESULT",
            command=self.open_export_dialog,
            state="disabled",
            **stable_button_style(c["blue"]),
            disabledforeground="#6c7890",
            relief="flat",
            font=("DejaVu Sans", 13, "bold"),
        )
        self.export_button.place(x=790, y=574, width=230, height=76)
        self.root.bind_all("<ButtonRelease-1>", self._finish_drag, add="+")

    def _geometry(self, surface: str) -> str:
        shifted = self.mode in {"shifted", "shifted_reordered"}
        layouts = {
            "root": ("1060x700+720+220", "1060x700+70+70"),
            "input": ("620x420+1050+330", "620x420+270+210"),
            "config": ("640x530+960+270", "640x530+350+230"),
            "export": ("640x500+1030+300", "640x500+390+250"),
        }
        shifted_value, initial_value = layouts[surface]
        return shifted_value if shifted else initial_value

    def _ordered_specimens(self) -> list[tuple[str, str, str]]:
        return specimens_for_mode(self.mode)

    def _render_source_rows(self) -> None:
        for widget in self.source_widgets:
            widget.destroy()
        self.source_widgets.clear()
        for index, (specimen_id, batch_code, status) in enumerate(self._ordered_specimens()):
            row = tk.Label(
                self.rows_frame,
                text=f"{specimen_id}     {batch_code}     {status.upper()}",
                bg="#1b3150" if specimen_id != self.selected_specimen else "#285da5",
                fg=self.COLORS["text"],
                anchor="w",
                padx=16,
                font=("DejaVu Sans", 11, "bold"),
                cursor="hand2",
            )
            row.place(x=0, y=index * 52, width=402, height=44)
            row.bind("<ButtonPress-1>", lambda event, value=specimen_id: self._begin_drag(value))
            self.source_widgets.append(row)

    def _begin_drag(self, specimen_id: str) -> None:
        if not self.selected_batch:
            self.result_label.configure(text="SELECT A VALIDATED INPUT BATCH FIRST", fg=self.COLORS["amber"])
            return
        self.selected_specimen = specimen_id
        self.drag_specimen = specimen_id
        self._render_source_rows()
        self.write_status("specimen_selected")

    def _finish_drag(self, _event: tk.Event[Any]) -> None:
        if not self.drag_specimen:
            return
        pointer_x, pointer_y = self.root.winfo_pointerx(), self.root.winfo_pointery()
        lane_x, lane_y = self.queue_lane.winfo_rootx(), self.queue_lane.winfo_rooty()
        inside = lane_x <= pointer_x <= lane_x + self.queue_lane.winfo_width() and lane_y <= pointer_y <= lane_y + self.queue_lane.winfo_height()
        specimen = self.drag_specimen
        self.drag_specimen = ""
        if not inside:
            return
        self.queue = [specimen]
        self.queue_lane.configure(text=f"QUEUED · {specimen}", bg="#123a35", fg="#5ee6ad")
        self.config_button.configure(state="normal")
        self.result_label.configure(text=f"{specimen} QUEUED · CONFIGURATION REQUIRED", fg=self.COLORS["text"])
        self.write_status("queued")

    def open_input_browser(self) -> None:
        existing = self.dialogs.get("input")
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        dialog = self._dialog("input", "ATR Input Browser")
        tk.Label(dialog, text="INPUT BROWSER", bg=self.COLORS["background"], fg=self.COLORS["text"], font=("DejaVu Sans", 21, "bold")).place(x=34, y=24)
        tk.Label(dialog, text="Validated local specimen batches", bg=self.COLORS["background"], fg=self.COLORS["muted"], font=("DejaVu Sans", 11)).place(x=36, y=66)
        tk.Button(
            dialog,
            text="VALIDATED BATCH 2026-08\n4 SPECIMEN RECORDS",
            command=self.select_batch,
            **stable_button_style(self.COLORS["blue"]),
            relief="flat",
            font=("DejaVu Sans", 15, "bold"),
        ).place(x=52, y=120, width=516, height=110)
        tk.Label(dialog, text="Schema: atr.specimen_batch.v1 · checksum verified", bg=self.COLORS["panel"], fg="#76d5b0", font=("DejaVu Sans", 11, "bold")).place(x=52, y=264, width=516, height=48)

    def select_batch(self) -> None:
        self.selected_batch = "validated-batch-2026-08"
        self.batch_label.configure(text=validated_batch_summary(), fg="#5ee6ad")
        self._close_dialog("input")
        self.write_status("input_selected")

    def open_config_dialog(self) -> None:
        if not self.queue:
            return
        existing = self.dialogs.get("config")
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        dialog = self._dialog("config", "Queued Specimen Configuration")
        tk.Label(dialog, text="ANALYSIS CONFIGURATION", bg=self.COLORS["background"], fg=self.COLORS["text"], font=("DejaVu Sans", 20, "bold")).place(x=34, y=22)
        tk.Label(dialog, text=self.queue[0], bg=self.COLORS["panel"], fg="#76d5b0", anchor="w", padx=14, font=("DejaVu Sans", 12, "bold")).place(x=36, y=70, width=568, height=46)
        tk.Label(dialog, text="Method", bg=self.COLORS["background"], fg=self.COLORS["muted"], font=("DejaVu Sans", 11, "bold")).place(x=38, y=142)
        method_value = tk.StringVar(value=self.method)
        method_box = ttk.Combobox(dialog, textvariable=method_value, values=("Compression", "Tension", "Shear"), state="readonly", font=("DejaVu Sans", 12))
        method_box.place(x=38, y=170, width=566, height=42)
        tk.Label(dialog, text="Load limit", bg=self.COLORS["background"], fg=self.COLORS["muted"], font=("DejaVu Sans", 11, "bold")).place(x=38, y=236)
        load_entry = tk.Entry(dialog, bg="#e6effc", fg="#10213a", insertbackground="#10213a", relief="flat", font=("DejaVu Sans", 13, "bold"))
        load_entry.insert(0, self.load_limit)
        load_entry.place(x=38, y=264, width=566, height=44)
        evidence_background = self.COLORS["green"] if self.evidence_enabled else self.COLORS["panel_alt"]
        evidence_button = tk.Button(
            dialog,
            text="EVIDENCE CAPTURE · ON" if self.evidence_enabled else "EVIDENCE CAPTURE · OFF",
            **stable_button_style(evidence_background),
            relief="flat",
            font=("DejaVu Sans", 12, "bold"),
        )
        evidence_button.configure(command=lambda: self._toggle_evidence(evidence_button))
        evidence_button.place(x=38, y=332, width=566, height=52)
        tk.Button(
            dialog,
            text="SAVE CONFIGURATION",
            command=lambda: self.save_configuration(method_value.get(), load_entry.get()),
            **stable_button_style(self.COLORS["violet"]),
            relief="flat",
            font=("DejaVu Sans", 13, "bold"),
        ).place(x=38, y=414, width=566, height=64)

    def _toggle_evidence(self, button: tk.Button) -> None:
        if not self.evidence_click_ignored:
            self.evidence_click_ignored = True
            button.configure(
                text="EVIDENCE CAPTURE · OFF",
                bg=self.COLORS["panel_alt"],
                activebackground=self.COLORS["panel_alt"],
            )
            self.write_status("evidence_input_missed", injected_missed_evidence=True)
            return
        self.evidence_enabled = not self.evidence_enabled
        evidence_background = self.COLORS["green"] if self.evidence_enabled else self.COLORS["panel_alt"]
        button.configure(
            text="EVIDENCE CAPTURE · ON" if self.evidence_enabled else "EVIDENCE CAPTURE · OFF",
            bg=evidence_background,
            activebackground=evidence_background,
        )
        self.write_status("configuration_editing")

    def save_configuration(self, method: str, load_limit: str) -> None:
        try:
            analysis_result(self.queue[0], method, self.evidence_enabled, load_limit)
        except ValueError as exc:
            self.result_label.configure(text=f"CONFIGURATION ERROR · {exc}", fg=self.COLORS["red"])
            self.write_status("configuration_invalid", error=str(exc))
            return
        self.method = method
        self.load_limit = load_limit
        self.start_button.configure(state="normal")
        self.result_label.configure(text=f"CONFIGURED · {method} · LIMIT {float(load_limit):g}", fg=self.COLORS["text"])
        self._close_dialog("config")
        self.write_status("configured")

    def start_analysis(self) -> None:
        if not self.queue or self.state == "running":
            return
        self.analysis_attempts += 1
        if not self.evidence_enabled:
            self.state = "validation_failed"
            self.validation_button.place(x=40, y=528, width=980, height=38)
            self.result_label.configure(text="ANALYSIS BLOCKED · EVIDENCE CAPTURE WAS NOT OBSERVED", fg=self.COLORS["red"])
            self.write_status("validation_failed", failure_code="WORKFLOW_VALIDATION_FAILED")
            return
        if self.analysis_attempts > 2:
            self.state = "validation_failed"
            self.write_status("validation_failed", failure_code="WORKFLOW_VALIDATION_FAILED")
            return
        self.recovery_count = 1 if self.analysis_attempts == 2 else 0
        self.validation_button.place_forget()
        self.state = "running"
        self.progress_value = 0
        self.progress.place(x=40, y=536, width=980, height=20)
        self.start_button.configure(state="disabled")
        self.result_label.configure(text="ANALYSIS RUNNING · 0%", fg=self.COLORS["amber"])
        self.write_status("running")
        self._advance_progress()

    def _advance_progress(self) -> None:
        if self.state != "running":
            return
        self.progress_value = min(100, self.progress_value + 20)
        self.progress["value"] = self.progress_value
        self.result_label.configure(text=f"ANALYSIS RUNNING · {self.progress_value}%")
        self.write_status("running")
        if self.progress_value < 100:
            self.root.after(130, self._advance_progress)
            return
        self.result = analysis_result(self.queue[0], self.method, self.evidence_enabled, self.load_limit)
        self.state = "completed"
        self.progress.place_forget()
        self.result_label.configure(
            text=f"COMPLETED · {self.result['specimen_id']} · {self.result['method']} · LIMIT {self.result['load_limit']}",
            fg="#5ee6ad",
        )
        self.export_button.configure(state="normal")
        self.write_status("completed")

    def open_export_dialog(self) -> None:
        if not self.result:
            return
        existing = self.dialogs.get("export")
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        dialog = self._dialog("export", "Verified Result Export")
        tk.Label(dialog, text="EXPORT VERIFIED RESULT", bg=self.COLORS["background"], fg=self.COLORS["text"], font=("DejaVu Sans", 20, "bold")).place(x=34, y=22)
        json_value = tk.BooleanVar(value=False)
        csv_value = tk.BooleanVar(value=False)
        tk.Checkbutton(
            dialog,
            text="JSON",
            variable=json_value,
            indicatoron=False,
            selectcolor=self.COLORS["green"],
            **stable_button_style(self.COLORS["panel_alt"]),
            relief="flat",
            font=("DejaVu Sans", 13, "bold"),
        ).place(x=38, y=88, width=270, height=58)
        tk.Checkbutton(
            dialog,
            text="CSV",
            variable=csv_value,
            indicatoron=False,
            selectcolor=self.COLORS["green"],
            **stable_button_style(self.COLORS["panel_alt"]),
            relief="flat",
            font=("DejaVu Sans", 13, "bold"),
        ).place(x=334, y=88, width=270, height=58)
        tk.Label(dialog, text="Output name", bg=self.COLORS["background"], fg=self.COLORS["muted"], font=("DejaVu Sans", 11, "bold")).place(x=38, y=174)
        name_entry = tk.Entry(dialog, bg="#e6effc", fg="#10213a", insertbackground="#10213a", relief="flat", font=("DejaVu Sans", 13, "bold"))
        name_entry.insert(0, "advanced_queue_result")
        name_entry.place(x=38, y=204, width=566, height=48)
        tk.Button(
            dialog,
            text="SAVE JSON + CSV",
            command=lambda: self.save_export(name_entry.get(), json_value.get(), csv_value.get()),
            **stable_button_style(self.COLORS["blue"]),
            relief="flat",
            font=("DejaVu Sans", 14, "bold"),
        ).place(x=38, y=300, width=566, height=70)
        self.export_error = tk.Label(dialog, text="Select both verified formats", bg=self.COLORS["background"], fg=self.COLORS["muted"], font=("DejaVu Sans", 10))
        self.export_error.place(x=38, y=390, width=566, height=36)

    def save_export(self, name: str, include_json: bool, include_csv: bool) -> None:
        if not include_json or not include_csv:
            self.export_error.configure(text="BOTH JSON AND CSV ARE REQUIRED", fg=self.COLORS["red"])
            self.write_status("export_invalid", failure_code="ARTIFACT_VALIDATION_FAILED")
            return
        try:
            self.exports = write_exports(OUTPUT_ROOT, name, self.result)
        except ValueError as exc:
            self.export_error.configure(text=str(exc).upper(), fg=self.COLORS["red"])
            self.write_status("export_invalid", failure_code="ARTIFACT_VALIDATION_FAILED")
            return
        self.state = "exported"
        self._close_dialog("export")
        self.result_label.configure(text="EXPORTED · advanced_queue_result.json + advanced_queue_result.csv", fg="#5ee6ad")
        self.write_status("exported")

    def _dialog(self, key: str, title: str) -> tk.Toplevel:
        dialog = tk.Toplevel(self.root)
        self.dialogs[key] = dialog
        dialog.title(title)
        dialog.geometry(self._geometry(key))
        dialog.configure(bg=self.COLORS["background"])
        dialog.attributes("-topmost", True)
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._close_dialog(key))
        return dialog

    def _close_dialog(self, key: str) -> None:
        dialog = self.dialogs.pop(key, None)
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()

    def reset(self) -> None:
        for key in tuple(self.dialogs):
            self._close_dialog(key)
        self.selected_batch = ""
        self.selected_specimen = ""
        self.drag_specimen = ""
        self.queue = []
        self.method = "Compression"
        self.evidence_enabled = False
        self.evidence_click_ignored = False
        self.load_limit = "12.5"
        self.analysis_attempts = 0
        self.recovery_count = 0
        self.result = {}
        self.exports = {}
        self.progress_value = 0
        self.state = "waiting"
        self.batch_label.configure(text="No validated batch selected", fg=self.COLORS["amber"])
        self.queue_lane.configure(text="DROP SPECIMEN HERE", bg="#0d192b", fg="#76a7ee")
        self.config_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.validation_button.place_forget()
        self.progress.place_forget()
        self.result_label.configure(text="WAITING FOR VALIDATED INPUT", fg=self.COLORS["muted"])
        self.root.geometry(self._geometry("root"))
        self._render_source_rows()
        self.write_status("waiting")

    def write_status(self, state: str | None = None, **extra: object) -> None:
        if state is not None:
            self.state = state
        payload: dict[str, object] = {
            "state": self.state,
            "mode": self.mode,
            "selected_batch": self.selected_batch,
            "selected_specimen": self.selected_specimen,
            "queue": list(self.queue),
            "configuration": {
                "method": self.method,
                "evidence_enabled": self.evidence_enabled,
                "load_limit": self.load_limit,
            },
            "analysis_attempts": self.analysis_attempts,
            "recovery_count": self.recovery_count,
            "progress": self.progress_value,
            "result": self.result,
            "exports": self.exports,
            "injected_missed_evidence": self.evidence_click_ignored,
            **extra,
        }
        atomic_write_text(STATUS_PATH, json.dumps(payload, ensure_ascii=True, indent=2) + "\n")

    def _poll_mode(self) -> None:
        token = MODE_PATH.read_text(encoding="utf-8").strip() if MODE_PATH.exists() else "initial"
        if token != self.mode_token:
            self.mode_token = token
            self.mode = normalize_mode(token)
            self.reset()
        self.root.after(100, self._poll_mode)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    AdvancedVisualWorkQueue().run()
