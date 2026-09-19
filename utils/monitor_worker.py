"""Isolated video OR robot reader. No controller, tool registry or actuation API."""
from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
import json
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import quote

from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.responses import Response, StreamingResponse
import uvicorn


def create_monitor_app(kind, config, token, latest):
    vision_sources = {}
    source_lock = threading.Lock()
    # Imports stay in their own process/domain; no server/application import.
    @asynccontextmanager
    async def lifespan(app):
        yield
        if kind == "video":
            with source_lock:
                sources = list(vision_sources.values())
                vision_sources.clear()
            for source in sources:
                await asyncio.to_thread(source.stop)
            from device_bridges.printer_fleet.monitoring import close_monitors
            await asyncio.to_thread(close_monitors)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    prefix = f"/{token}"
    viewers = 0

    if kind == "video":
        from device_bridges.printer_fleet.monitoring import shared_video
        printer_config = config

        def control(payload):
            nonlocal printer_config
            operation = payload["operation"]
            if operation == "printer":
                printer_config = payload["config"]
                return {"ok": True}
            if operation == "vision_stop":
                with source_lock:
                    source = vision_sources.pop(payload["source_id"], None)
                if source is not None:
                    source.stop()
                return {"ok": True}
            with source_lock:
                if operation == "vision_register":
                    # Import the existing byte-preserving subscriber, not a runtime manager.
                    from device_bridges.camera_vision.utm_runtime_bridge import SharedMjpegTopicStream
                    settings = payload["config"]
                    source_id = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:24]
                    if source_id not in vision_sources:
                        if len(vision_sources) >= 4:
                            raise ValueError("Vision display source limit reached")
                        vision_sources[source_id] = SharedMjpegTopicStream(**settings)
                    return {"ok": True, "source_id": source_id}
                raise ValueError("Unknown video configuration")
        app.state.video_control = control

        def vision_source(source_id):
            with source_lock:
                source = vision_sources.get(source_id)
            if source is None:
                raise HTTPException(status_code=404, detail="Display source unavailable")
            return source

        @app.get(prefix + "/vision/{source_id}/status")
        async def vision_status(source_id: str):
            return vision_source(source_id).stats()

        @app.get(prefix + "/vision/{source_id}/stream.mjpeg")
        async def vision_stream(source_id: str):
            nonlocal viewers
            source = vision_source(source_id)
            if viewers >= 8:
                return Response(status_code=429)
            viewers += 1

            async def frames():
                nonlocal viewers
                cancelled = threading.Event()
                iterator = source.frames(cancelled=cancelled)
                sentinel = object()
                task = None
                try:
                    while True:
                        task = asyncio.create_task(asyncio.to_thread(next, iterator, sentinel))
                        chunk = await asyncio.shield(task)
                        task = None
                        if chunk is sentinel:
                            break
                        yield chunk
                finally:
                    cancelled.set()
                    # Closing a generator while next() is running is unsafe. Disconnect
                    # must release its viewer even when ROS stops producing images.
                    if task is not None and not task.done():
                        def release(_):
                            try:
                                _.result()
                                iterator.close()
                            except (Exception, asyncio.CancelledError):
                                pass
                        task.add_done_callback(release)
                    else:
                        iterator.close()
                    viewers -= 1
            return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                     headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

        def video():
            settings = printer_config
            if not settings:
                raise HTTPException(status_code=503, detail="Printer display source not configured")
            return shared_video(settings["command"], settings["timeout"])

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
            # A delayed publisher is not an explicit session reset. Continue
            # reading its known log, with freshness reported separately. Parent
            # death still shuts this process down through EOF on the control pipe.
            return latest[0]

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
                    publisher_fresh=lambda: time.monotonic() - latest[1] < 5,
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
                if first["kind"] == "video" and "monitor_control" in payload:
                    try:
                        reply = app.state.video_control(payload["monitor_control"])
                    except Exception as exc:
                        reply = {"ok": False, "error": str(exc)}
                    print(json.dumps(reply), flush=True)
                    continue
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
