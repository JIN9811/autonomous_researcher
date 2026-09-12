"""Scoped verification guard. No application bootstrap or network at import time."""
from contextlib import ExitStack
from pathlib import Path
import builtins
import ctypes.util
import importlib
import io
import os
import socket
import subprocess
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit


class VerificationGuard:
    """Deny external effects, permitting only named model endpoints/fixture I/O.

    This is defense in depth for known Python/native entrypoints, not an OS
    sandbox or proof about arbitrary native extension code.
    """
    def __init__(self):
        self.stack = ExitStack()
        self.denied = []
        self.simulated_boundary_requests = []
        self.physical_call_count = 0
        self.allowed_tools = set()
        self.endpoints = set()
        self.addresses = set()
        self.discovery_command = None

    def deny(self, *args, **kwargs):
        self.denied.append([f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
            for frame in traceback.extract_stack(limit=6)[:-1]])
        raise AssertionError("Physical tool invocation is forbidden in setup verification")

    def allow_endpoint(self, base_url):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("Invalid registered provider endpoint")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.endpoints.add((parsed.scheme, parsed.hostname, port, parsed.path.rstrip("/")))
        for address in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM):
            self.addresses.add((address[4][0], port))

    def __enter__(self):
        original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
        def connect(sock, address, *args, **kwargs):
            if not isinstance(address, tuple) or tuple(address[:2]) not in self.addresses:
                return self.deny()
            return original_connect(sock, address, *args, **kwargs)
        def connect_ex(sock, address, *args, **kwargs):
            if not isinstance(address, tuple) or tuple(address[:2]) not in self.addresses:
                return self.deny()
            return original_connect_ex(sock, address, *args, **kwargs)
        self.stack.enter_context(patch.object(socket.socket, "connect", connect))
        self.stack.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))
        self.stack.enter_context(patch.object(socket.socket, "sendto", self.deny))
        original_popen = subprocess.Popen
        def popen(command, *args, **kwargs):
            if (self.discovery_command is None or command != self.discovery_command
                    or kwargs.get("shell") or kwargs.get("executable")):
                return self.deny()
            return original_popen(command, *args, **kwargs)
        self.stack.enter_context(patch.object(subprocess, "Popen", popen))
        self.stack.enter_context(patch.object(os, "system", self.deny))
        # Trio's optional OS thread-name support discovers libc by running
        # ldconfig during import. Disable that cosmetic probe under verification.
        def find_library(name):
            if name in {"c", "pthread"}:
                return None
            return self.deny()
        self.stack.enter_context(patch.object(ctypes.util, "find_library", find_library))
        for module, name in ((os, "open"), (builtins, "open"), (io, "open")):
            original = getattr(module, name)
            def guarded_open(path, *args, _original=original, **kwargs):
                if isinstance(path, (str, bytes, os.PathLike)):
                    value = os.fsdecode(path)
                    if value.startswith("/dev/") and value != "/dev/null":
                        return self.deny()
                return _original(path, *args, **kwargs)
            self.stack.enter_context(patch.object(module, name, guarded_open))
        for name, attributes in (("cv2", ("VideoCapture",)),
                                 ("pyrealsense2", ("pipeline", "context")),
                                 ("serial", ("Serial", "serial_for_url"))):
            try:
                module = importlib.import_module(name)
            except ImportError:
                continue
            for attribute in attributes:
                if hasattr(module, attribute):
                    self.stack.enter_context(patch.object(module, attribute, self.deny))
        import httpx
        original_send = httpx.AsyncClient.send
        async def send(client, request, *args, **kwargs):
            url = request.url
            if not any((url.scheme, url.host, url.port or (443 if url.scheme == "https" else 80)) == item[:3]
                       and ((request.method == "POST" and url.path == item[3] + "/chat/completions")
                            or (request.method == "GET" and url.path == item[3] + "/models"))
                       for item in self.endpoints):
                return self.deny()
            return await original_send(client, request, *args, **kwargs)
        self.stack.enter_context(patch.object(httpx.AsyncClient, "send", send))
        # These modules define classes only; patch before constructing bootstrap.
        from agents.analysis_runtime import AnalysisRuntimeService
        self.stack.enter_context(patch.object(AnalysisRuntimeService, "resume", self.deny))
        from backends.vllm_client import VLLMBackend
        from backends.nemoclaw_vllm_runtime import NemoClawVLLMRuntime
        for cls in (VLLMBackend, NemoClawVLLMRuntime):
            for name in ("prepare_model", "ensure_model", "load_model", "unload_model",
                         "scale_down_idle_models", "scale_down_models_except"):
                if hasattr(cls, name):
                    self.stack.enter_context(patch.object(cls, name, self.deny))
        from mcp_tools.tool_registry import ToolRegistry
        original_call = ToolRegistry.call
        def tool_call(registry, name, payload=None):
            if name not in self.allowed_tools:
                return self.deny()
            return original_call(registry, name, payload)
        self.stack.enter_context(patch.object(ToolRegistry, "call", tool_call))
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)
