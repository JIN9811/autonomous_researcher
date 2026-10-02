"""Isolated UI fixture. Imports no runtime/controller and uses a temporary run root.

Run: .venv/bin/python scripts/preview_run_review.py --port 8775
"""
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from app.run_review_routes import review_router
from utils.run_review import RunReviewRecorder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8775)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="atr-review-preview-") as directory:
        root = Path(directory)
        run = root / "preview-fixture"
        run.mkdir()
        recorder = RunReviewRecorder(root, "excluded-live-run")
        for cycle in range(2):
            for agent, checkpoint in (("design", "handoff"), ("vision", "verification_1"), ("analysis", "handoff"), ("bo", "candidate_ready")):
                recorder.record({"run_id": run.name, "event_type": "agent.attention_requested", "agent": agent,
                    "ts": f"2026-09-17T12:{cycle * 10 + len(recorder.index):02d}:00Z",
                    "payload": {"checkpoint": checkpoint, "status": "recorded",
                                "latest": {"role": agent, "content": "Isolated UI fixture. No experiment or device was started."},
                                "design_parameters": {"cell_size_mm": 7.5, "wall_thickness_mm": .9}},
                    "state": {"run_id": run.name, "loop_count": cycle, "mode": "test", "stage": agent}})
        app = FastAPI(title="Isolated Replay Preview")
        app.mount("/static", StaticFiles(directory=ROOT / "web/static"))
        for directory in (ROOT / "agents").glob("*/frontend"):
            app.mount(f"/module-assets/{directory.parent.name}", StaticFiles(directory=directory))
        app.include_router(review_router(root, Jinja2Templates(directory=ROOT / "web/templates")))
        @app.get("/main-preview", response_class=HTMLResponse)
        def main_picker_preview():
            # Exact production Run Control markup, without any runtime scripts.
            html = (ROOT / "web/templates/index.html").read_text()
            controls = html.split('<section class="panel controls">', 1)[1].split('</section>', 1)[0]
            return ('<!doctype html><html><head><title>Replay session picker · isolated preview</title>'
                    '<link rel="stylesheet" href="/static/styles.css"></head><body><main class="page">'
                    '<p>Isolated Run Control preview · no experimental backend</p>'
                    '<section class="panel controls">' + controls + '</section></main>'
                    '<script src="/static/run_review_picker.js"></script>'
                    '<script>document.getElementById("btn-start").addEventListener("click",'
                    '()=>window.AX4LABRunReviewPicker.open());</script></body></html>')
        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
