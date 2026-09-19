"""Isolated video OR robot reader. No controller, tool registry or actuation API."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import quote

from fastapi import FastAPI, WebSocket
from fastapi.responses import Response, StreamingResponse
import uvicorn


def create_monitor_app(kind, config, token, latest):
    # Imports stay in their own process/domain; no server/application import.
    @asynccontextmanager
    async def lifespan(app):
        yield
        if kind == "video":
            from device_bridges.printer_fleet.monitoring import close_monitors
            await asyncio.to_thread(close_monitors)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    prefix = f"/{token}"
    viewers = 0

    if kind == "video":
        from device_bridges.printer_fleet.monitoring import shared_video

        def video():
            return shared_video(config["command"], config["timeout"])

        @app.get(prefix + "/frame.jpg")
        async def frame():
            _, frame_bytes = await asyncio.to_thread(video().read)
            return Response(frame_bytes, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

        @app.get(prefix + "/stream.mjpeg")
        async def stream():
            nonlocal viewers
            if viewers >= 8:
                return Response(status_code=429)
            viewers += 1
            async def frames():
                nonlocal viewers
                sequence = 0
                try:
                    while True:
                        sequence, data = await asyncio.to_thread(video().read, sequence)
                        yield b"--ffmpeg\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n"
                except (TimeoutError, RuntimeError):
                    return
                finally:
                    viewers -= 1
            return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=ffmpeg",
                                     headers={"Cache-Control": "no-store"})
    elif kind == "robot":
        from utils.lerobot_joint_telemetry import finalize_policy_tracking_artifacts
        from utils.manipulation_runtime_view import build_manipulation_runtime_view
        from utils.robot_monitor_stream import stream_robot_samples
        artifact_lock = threading.Lock()

        def current():
            # Stop showing live data if the owning server stops publishing.
            return latest[0] if time.monotonic() - latest[1] < 5 else {}

        def artifacts(path, session):
            with artifact_lock:
                result = finalize_policy_tracking_artifacts(path, session)
            for key in ("plot_png_path", "summary_json_path", "raw_jsonl_path", "raw_csv_path", "grasp_outcomes_path"):
                value = str(result.get(key) or "")
                if value and Path(value).is_file():
                    result[key.removesuffix("_path") + "_url"] = f"/api/lerobot/visualization/file?path={quote(value, safe='')}"
            return result

        @app.websocket(prefix + "/joints")
        async def joints(ws: WebSocket):
            nonlocal viewers
            if viewers >= 8 or ws.headers.get("origin") not in config["origins"]:
                await ws.close(code=1008)
                return
            viewers += 1
            try:
                await stream_robot_samples(ws,
                    context=lambda: current().get("context"),
                    reset=lambda: latest[0].get("reset_at_ms", 0),
                    public_session=lambda session: session,
                    runtime_view=lambda session, packet, artifacts=None: build_manipulation_runtime_view(
                        session=session, packet=packet, artifacts=artifacts or {}, state=current().get("state", {})),
                    artifacts=artifacts)
            finally:
                viewers -= 1
    return app


def main():
    first = json.loads(sys.stdin.readline())
    latest = [{}, 0.0]
    app = create_monitor_app(first["kind"], first["config"], first["token"], latest)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(32)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, ws_max_queue=4,
                                          timeout_graceful_shutdown=2))

    def receive():
        for line in sys.stdin:
            try:
                payload = json.loads(line)
                latest[:] = [payload, time.monotonic()]
            except (ValueError, TypeError):
                continue
        # The pipe closes on parent death, including SIGKILL. Release decoder.
        server.should_exit = True
    threading.Thread(target=receive, daemon=True).start()
    print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
    server.run(sockets=[listener])


if __name__ == "__main__":
    main()
