"""Client handle for display-only ROS readers in the shared video worker."""
from __future__ import annotations

import json
from urllib.request import urlopen

from utils.monitor_process import monitor_process


class RemoteVisionStream:
    def __init__(self, **config):
        self.worker = monitor_process("video", {})
        self.source_id = self.worker.control({"operation": "vision_register", "config": config})["source_id"]

    def alive(self):
        return self.worker.process.poll() is None

    def url(self):
        return self.worker.url(f"vision/{self.source_id}/stream.mjpeg")

    def stats(self):
        with urlopen(self.worker.url(f"vision/{self.source_id}/status"), timeout=2) as response:
            return json.load(response)

    def stop(self):
        # Preview failure must never prevent ROS shutdown/reload or a decision.
        try:
            if self.alive():
                self.worker.control({"operation": "vision_stop", "source_id": self.source_id})
        except (OSError, ValueError, RuntimeError, TimeoutError):
            pass
