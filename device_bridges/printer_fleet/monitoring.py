"""Process-local, read-only printer telemetry and latest-frame fan-out.

No upload, print, or ejection commands belong in this module. Consumers receive
copies; stale/disconnected telemetry is never returned as healthy evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import ssl
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone


def _merge(target, delta):
    for key, value in delta.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


class MqttMonitor:
    MAX_AGE = 15.0
    IDLE_TIMEOUT = 120.0

    def __init__(self, mqtt, config, *, host, serial, username, access_code):
        self.condition = threading.Condition()
        self.report = {}
        self.received = 0.0
        self.received_at = ""
        self.connected = False
        self.closed = False
        self.last_access = time.monotonic()
        self.stop = threading.Event()
        self.topic = config.report_topic_template.format(serial=serial)
        self.request_topic = config.request_topic_template.format(serial=serial)
        client_id = f"atr-monitor-{uuid.uuid4().hex[:10]}"
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        except AttributeError:
            self.client = mqtt.Client(client_id=client_id)
        self.client.username_pw_set(username, access_code)
        self.client.tls_set(cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.client.connect_async(host, config.port, keepalive=30)
        self.client.loop_start()
        threading.Thread(target=self._watch, daemon=True, name="printer-mqtt-monitor").start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        code = int(getattr(reason_code, "value", reason_code))
        with self.condition:
            self.connected = code == 0
            # Never combine a pre-disconnect job with a new connection's deltas.
            self.report = {}
            self.received = 0.0
            self.condition.notify_all()
        if code == 0:
            client.subscribe(self.topic, qos=0)

    def _request(self):
        self.client.publish(self.request_topic, json.dumps({
            "pushing": {"sequence_id": "1", "command": "pushall"}, "user_id": "atr",
        }), qos=0)

    def _on_subscribe(self, *args):
        self._request()

    def _on_disconnect(self, *args):
        with self.condition:
            self.connected = False
            self.condition.notify_all()

    def _on_message(self, client, userdata, msg):
        if msg.topic != self.topic or getattr(msg, "retain", False):
            return
        try:
            delta = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeError):
            return
        if not isinstance(delta, dict) or not isinstance(delta.get("print"), dict):
            return
        with self.condition:
            _merge(self.report, delta)
            self.received = time.monotonic()
            self.received_at = datetime.now(timezone.utc).isoformat()
            self.condition.notify_all()

    def read(self, timeout_sec, force_refresh=False):
        deadline = time.monotonic() + max(0.0, timeout_sec)
        with self.condition:
            self.last_access = time.monotonic()
            previous = self.received if force_refresh else -1.0
            if force_refresh and self.connected:
                self._request()
            while True:
                age = time.monotonic() - self.received if self.received else float("inf")
                if not self.closed and self.connected and age <= self.MAX_AGE and self.received > previous:
                    return {"ok": True, "report": copy.deepcopy(self.report), "topic": self.topic,
                            "received_at": self.received_at, "cache_status": "live_subscription",
                            "cache_age_sec": round(age, 3)}
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self.closed:
                    return {"ok": False, "failure_code": "BAMBU_MQTT_REPORT_STALE" if self.received else "BAMBU_MQTT_REPORT_TIMEOUT",
                            "received_at": self.received_at, "cache_status": "unavailable"}
                self.condition.wait(remaining)

    def _watch(self):
        while not self.stop.wait(10):
            if time.monotonic() - self.last_access > self.IDLE_TIMEOUT:
                self.close()
                return
            if self.connected:
                self._request()

    def close(self):
        with self.condition:
            if self.closed:
                return
            self.closed = True
            self.connected = False
            self.stop.set()
            self.condition.notify_all()
        self.client.disconnect()
        self.client.loop_stop()


_mqtt_lock = threading.Lock()
_mqtt_monitors = {}


def read_mqtt_monitor(mqtt, config, *, timeout_sec, force_refresh=False, **connection):
    if mqtt is None:
        return {"ok": False, "failure_code": "PAHO_MQTT_NOT_INSTALLED"}
    if not all(connection.get(key) for key in ("host", "serial", "access_code")):
        return {"ok": False, "failure_code": "BAMBU_MQTT_CONNECTION_INFO_INCOMPLETE"}
    key = (connection["host"], connection["serial"], connection["username"],
           hashlib.sha256(connection["access_code"].encode()).hexdigest(),
           config.port, config.report_topic_template, config.request_topic_template)
    with _mqtt_lock:
        for old_key, item in list(_mqtt_monitors.items()):
            if item.closed or (old_key[:2] == key[:2] and old_key != key):
                item.close()
                del _mqtt_monitors[old_key]
        monitor = _mqtt_monitors.get(key)
        if monitor is None:
            if len(_mqtt_monitors) >= 4:
                oldest = min(_mqtt_monitors, key=lambda k: _mqtt_monitors[k].last_access)
                _mqtt_monitors.pop(oldest).close()
            try:
                monitor = MqttMonitor(mqtt, config, **connection)
            except (OSError, ValueError):
                return {"ok": False, "failure_code": "BAMBU_MQTT_CONNECT_FAILED"}
            _mqtt_monitors[key] = monitor
    return monitor.read(timeout_sec, force_refresh)


class LatestVideo:
    """One decoder per source, one bounded latest JPEG; no per-viewer backlog."""
    IDLE_TIMEOUT = 15.0
    FRAME_TIMEOUT = 15.0
    RECONNECT_TIMEOUT = 5.0
    RETRY_DELAY = 1.0

    def __init__(self, command, timeout_sec):
        self.command = command
        self.timeout = timeout_sec
        self.condition = threading.Condition()
        self.frame = b""
        self.sequence = 0
        self.readers = 0
        self.received = 0.0
        self.last_access = time.monotonic()
        self.closed = False
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="printer-video-monitor")
        self.thread.start()

    def _publish(self, frame):
        with self.condition:
            self.frame = frame
            self.sequence += 1
            self.received = time.monotonic()
            self.condition.notify_all()

    def read(self, after=0):
        with self.condition:
            deadline = time.monotonic() + (self.timeout if not self.sequence else self.FRAME_TIMEOUT)
            self.last_access = time.monotonic()
            self.readers += 1
            try:
                while not self.closed:
                    if self.sequence > after and time.monotonic() - self.received <= 2:
                        return self.sequence, self.frame
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("BAMBU_VIDEO_FRAME_TIMEOUT")
                    self.condition.wait(remaining)
                raise RuntimeError("BAMBU_VIDEO_FRAME_CAPTURE_FAILED")
            finally:
                self.readers -= 1
                self.last_access = time.monotonic()

    def _run(self):
        try:
            while not self.stop.is_set():
                reason, detail = self._decode_once()
                if reason in {"idle", "stopped"}:
                    break
                _video_diagnostic(reason, detail)
                # A source which has never produced a frame retains its original
                # startup failure behavior. Established viewers survive reconnects.
                if not self.sequence or self.stop.wait(self.RETRY_DELAY):
                    break
        finally:
            with self.condition:
                self.closed = True
                self.frame = b""
                self.condition.notify_all()

    def _decode_once(self):
        process = None
        reason = "stopped"
        errors = bytearray()
        try:
            process = subprocess.Popen(self.command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, bufsize=0)
            fd = process.stdout.fileno()
            os.set_blocking(fd, False)
            stderr = getattr(process, "stderr", None)
            if stderr:
                os.set_blocking(stderr.fileno(), False)
            buffer = bytearray()
            last_frame = time.monotonic()
            while not self.stop.is_set():
                now = time.monotonic()
                if stderr:
                    try:
                        errors.extend(os.read(stderr.fileno(), 4096))
                        del errors[:-2048]
                    except BlockingIOError:
                        pass
                if not self.readers and now - self.last_access > self.IDLE_TIMEOUT:
                    reason = "idle"
                    break
                frame_timeout = self.timeout if not self.sequence else self.RECONNECT_TIMEOUT
                if now - last_frame > frame_timeout:
                    reason = "frame_stalled"
                    break
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    self.stop.wait(.02)
                    continue
                if not chunk:
                    reason = "decoder_eof"
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", max(start + 2, 0))
                    if start < 0 or end < 0:
                        break
                    self._publish(bytes(buffer[start:end + 2]))
                    last_frame = time.monotonic()
                    del buffer[:end + 2]
                if len(buffer) > 4 * 1024 * 1024:
                    reason = "frame_buffer_limit"
                    break
        except OSError:
            reason = "decoder_io_error"
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                if process.stdout:
                    process.stdout.close()
                if getattr(process, "stderr", None):
                    process.stderr.close()
        return reason, errors.decode("utf-8", errors="replace")

    def close(self):
        self.stop.set()
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.thread.join(timeout=3)


_video_lock = threading.Lock()
_videos = {}


def _video_diagnostic(reason, detail):
    # Redact whole source URLs, not just passwords. Keep logging bounded and
    # separate from control/experiment evidence, even in the isolated worker.
    logger = logging.getLogger("atr.printer_video")
    try:
        if not logger.handlers:
            path = Path(os.environ.get("ATR_VIDEO_LOG_PATH") or
                        Path(__file__).resolve().parents[2] / "runs/monitoring/printer_video.log")
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=2)
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        safe = re.sub(r"(?:rtsps?|https?)://\S+", "[source redacted]", detail)
        logger.warning("%s %s", reason, safe[-2048:].replace("\n", " "))
    except OSError:
        pass  # Logging must never stop the display reader.


def shared_video(command, timeout_sec):
    key = hashlib.sha256("\0".join(command).encode()).hexdigest()
    with _video_lock:
        for old_key, item in list(_videos.items()):
            if item.closed:
                item.close()
                del _videos[old_key]
        if key not in _videos:
            if len(_videos) >= 4:
                oldest = min(_videos, key=lambda k: _videos[k].last_access)
                _videos.pop(oldest).close()
            _videos[key] = LatestVideo(command, timeout_sec)
        return _videos[key]


def close_monitors():
    with _mqtt_lock:
        for monitor in _mqtt_monitors.values():
            monitor.close()
        _mqtt_monitors.clear()
    with _video_lock:
        for video in _videos.values():
            video.close()
        _videos.clear()
