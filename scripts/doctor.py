#!/usr/bin/env python3
"""Fresh-install diagnostics for autonomous_researcher.

The doctor is intentionally non-actuating: it does not start models, contact
printers, open robot ports, or write device memory. It checks whether the clone
has enough local files and host tools to proceed, then reports optional hardware
setup gaps separately from core install failures.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - only happens before requirements install.
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE_IMPORTS = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "langgraph",
    "yaml",
    "httpx",
    "jinja2",
    "numpy",
    "skimage",
    "trimesh",
    "gpytorch",
    "botorch",
    "paho.mqtt.client",
]


class Doctor:
    def __init__(self, *, core_only: bool = False, hardware: bool = False) -> None:
        self.core_only = core_only
        self.hardware = hardware
        self.results: list[dict[str, str]] = []

    def add(self, level: str, name: str, detail: str, hint: str = "") -> None:
        self.results.append({"level": level, "name": name, "detail": detail, "hint": hint})

    def ok(self, name: str, detail: str, hint: str = "") -> None:
        self.add("ok", name, detail, hint)

    def warn(self, name: str, detail: str, hint: str = "") -> None:
        self.add("warn", name, detail, hint)

    def fail(self, name: str, detail: str, hint: str = "") -> None:
        self.add("fail", name, detail, hint)

    def load_yaml(self, relative: str) -> dict[str, Any]:
        path = ROOT / relative
        if yaml is None:
            self.warn("yaml loader", "PyYAML is not importable yet.", "Run pip install -r requirements.txt.")
            return {}
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            self.fail(relative, f"failed to read YAML: {exc}", "Check file syntax.")
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def resolve_repo_path(self, value: str) -> Path:
        path = Path(str(value)).expanduser()
        if path.is_absolute():
            return path
        return ROOT / path

    def check_core_files(self) -> None:
        required = [
            "app/main.py",
            "app/serve.py",
            "configs/system.yaml",
            "configs/models.yaml",
            "configs/devices.yaml",
            "requirements.txt",
            "install/install_cli.sh",
            ".env.example",
        ]
        missing = [item for item in required if not (ROOT / item).exists()]
        if missing:
            self.fail("core files", "missing: " + ", ".join(missing), "Re-clone the repository or restore files.")
        else:
            self.ok("core files", "required repository files are present")

    def check_python(self) -> None:
        version = sys.version_info
        if version >= (3, 11):
            self.ok("python", f"{version.major}.{version.minor}.{version.micro}")
        else:
            self.fail("python", f"{version.major}.{version.minor}.{version.micro}", "Use Python 3.11 or newer.")

        linux_venv = ROOT / ".venv" / "bin" / "python"
        windows_venv = ROOT / ".venv" / "Scripts" / "python.exe"
        if linux_venv.exists() or windows_venv.exists():
            self.ok("virtualenv", ".venv exists")
        else:
            self.warn("virtualenv", ".venv was not found", "Run bash install/bootstrap_linux.sh or create .venv manually.")

    def check_env(self) -> None:
        env_path = ROOT / ".env"
        example = ROOT / ".env.example"
        if env_path.exists():
            self.ok("environment", ".env exists")
        elif example.exists():
            self.warn("environment", ".env missing", "Copy .env.example to .env before normal operation.")
        else:
            self.fail("environment", ".env.example missing", "Restore the tracked template.")

        if example.exists():
            raw = example.read_bytes()[:3]
            if raw == b"\xef\xbb\xbf":
                self.warn(".env.example", "file starts with UTF-8 BOM", "Remove BOM if shell tooling has trouble parsing it.")
            else:
                self.ok(".env.example", "template has no UTF-8 BOM")

    def check_imports(self) -> None:
        failed: list[str] = []
        for module in CORE_IMPORTS:
            try:
                importlib.import_module(module)
            except Exception as exc:
                failed.append(f"{module}: {exc}")
        if failed:
            self.fail("python imports", "; ".join(failed), "Run pip install -r requirements.txt in the active environment.")
        else:
            self.ok("python imports", "core runtime imports succeeded")

    def check_app_import(self) -> None:
        try:
            from app.main import app  # noqa: PLC0415

            routes = [route for route in app.routes if hasattr(route, "path")]
        except Exception as exc:
            self.fail("FastAPI app", f"import failed: {type(exc).__name__}: {exc}", "Fix import-time errors before starting the server.")
            return
        self.ok("FastAPI app", f"import succeeded, routes={len(routes)}")

    def check_cli(self) -> None:
        target = Path.home() / ".local" / "bin" / "atr"
        if not target.exists():
            self.warn("atr launcher", "~/.local/bin/atr is not installed", "Run bash install/install_cli.sh.")
            return
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.warn("atr launcher", f"cannot read {target}: {exc}", "Reinstall with bash install/install_cli.sh.")
            return
        if str(ROOT) in text:
            self.ok("atr launcher", f"bound to this checkout: {ROOT}")
        else:
            self.warn("atr launcher", "installed but bound to another checkout", "Run ATR_FORCE_INSTALL=1 bash install/install_cli.sh if this repo should own atr.")

    def check_bambu(self) -> None:
        devices = self.load_yaml("configs/devices.yaml")
        bambu = devices.get("devices", {}).get("printer", {}).get("bambu", {}) if isinstance(devices, dict) else {}
        slicer = bambu.get("slicer", {}) if isinstance(bambu, dict) else {}
        env_name = str(slicer.get("executable_env") or "BAMBU_STUDIO_EXECUTABLE")
        configured = str(slicer.get("executable_path") or "install/bambustudio/bambu-studio-wrapper")
        wrapper = self.resolve_repo_path(configured)
        if wrapper.exists() and os.access(wrapper, os.X_OK):
            self.ok("Bambu wrapper", str(wrapper))
        else:
            self.warn("Bambu wrapper", f"missing or not executable: {wrapper}", "Restore install/bambustudio/bambu-studio-wrapper or set BAMBU_STUDIO_EXECUTABLE.")

        candidates = []
        env_value = os.getenv(env_name, "").strip()
        if env_value:
            candidates.append(("env", Path(env_value).expanduser()))
        for name in ("bambu-studio", "BambuStudio", "bambu-studio.AppImage", "BambuStudio.AppImage"):
            found = shutil.which(name)
            if found:
                candidates.append(("PATH", Path(found)))
        if wrapper.exists():
            candidates.append(("wrapper", wrapper))

        resolved = ""
        for source, path in candidates:
            if path.exists() and os.access(path, os.X_OK):
                resolved = f"{source}: {path}"
                break
        if resolved:
            self.ok("Bambu Studio resolver", resolved)
        else:
            self.warn("Bambu Studio resolver", "no executable found", "Install Bambu Studio or export BAMBU_STUDIO_EXECUTABLE.")

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            self.ok("Bambu video dependency", f"ffmpeg={ffmpeg}")
        else:
            self.warn("Bambu video dependency", "ffmpeg not found", "Install ffmpeg for browser MJPEG proxy.")

    def check_prusa(self) -> None:
        wrapper = ROOT / "install" / "prusaslicer" / "prusa-slicer-docker"
        dockerfile = ROOT / "install" / "prusaslicer" / "Dockerfile"
        if wrapper.exists() and os.access(wrapper, os.X_OK) and dockerfile.exists():
            self.ok("PrusaSlicer wrapper", "Docker wrapper files are present")
        else:
            self.warn("PrusaSlicer wrapper", "Docker wrapper files are incomplete", "Restore install/prusaslicer files.")
        if shutil.which("docker"):
            self.ok("docker", "docker command found")
        else:
            self.warn("docker", "docker command not found", "Install Docker before using PrusaSlicer/CAE container paths.")

    def check_lerobot(self) -> None:
        cfg = self.load_yaml("configs/lerobot.yaml")
        root_cfg = cfg.get("lerobot", {}) if isinstance(cfg, dict) else {}
        conda = str(root_cfg.get("conda_executable") or "conda")
        conda_path = shutil.which(conda)
        if conda_path:
            self.ok("conda", conda_path)
        else:
            self.warn("conda", f"not found: {conda}", "Install Miniconda or set configs/lerobot.yaml conda_executable.")

        lerobot_root = Path(os.getenv("LEROBOT_ROOT", str(Path.home() / "lerobot"))).expanduser()
        if (lerobot_root / ".git").exists():
            self.ok("LeRobot checkout", str(lerobot_root))
        else:
            self.warn("LeRobot checkout", f"not found: {lerobot_root}", "Clone LeRobot separately before live robot workflows.")

        patch = ROOT / "patches" / "lerobot" / "spark_realsense_d405_rsusb.patch"
        applier = ROOT / "install" / "apply_lerobot_d405_patch.sh"
        if patch.exists() and applier.exists():
            self.ok("LeRobot D405 patch", "patch and apply script are present")
        else:
            self.warn("LeRobot D405 patch", "patch package is missing", "Restore patches/lerobot and install/apply_lerobot_d405_patch.sh.")

        pi05_root = self.resolve_repo_path(str(root_cfg.get("pi05_repo_root") or "~/lerobot_pi05"))
        if pi05_root.exists():
            self.ok("Pi0.5 worktree", str(pi05_root))
        else:
            self.warn("Pi0.5 worktree", f"not found: {pi05_root}", "Only needed for Pi0.5 training/rollout.")

    def check_realsense(self) -> None:
        try:
            rs = importlib.import_module("pyrealsense2")
        except Exception as exc:
            self.warn("RealSense SDK", f"pyrealsense2 import failed: {exc}", "Install pyrealsense2 and the RSUSB build when using D405/D455F.")
            return
        module_file = str(getattr(rs, "__file__", ""))
        if "librealsense-rsusb" in module_file:
            self.ok("RealSense SDK", f"RSUSB binding active: {module_file}")
        else:
            self.warn("RealSense SDK", f"importable but not clearly RSUSB: {module_file}", "D405 live use on Spark should load the local FORCE_RSUSB_BACKEND build first.")

        if self.hardware:
            try:
                ctx = rs.context()
                devices = list(ctx.query_devices())
                self.ok("RealSense hardware", f"visible devices={len(devices)}")
            except Exception as exc:
                self.warn("RealSense hardware", f"enumeration failed: {exc}", "Check USB bus/hub and RSUSB installation.")

    def check_models(self) -> None:
        deploy = ROOT / "deploy" / "nemoclaw-vllm.yaml"
        models = self.load_yaml("configs/models.yaml")
        if deploy.exists():
            self.ok("NemoClaw/vLLM deploy", str(deploy))
        else:
            self.warn("NemoClaw/vLLM deploy", "deploy/nemoclaw-vllm.yaml missing", "Restore deploy config if local vLLM is required.")
        backend = models.get("backend", {}) if isinstance(models, dict) else {}
        self.ok("model backend config", f"default={backend.get('default')} fallback={backend.get('fallback')}")

    def check_secrets_policy(self) -> None:
        git = shutil.which("git")
        if not git:
            self.warn("git", "git command not found", "Install git for version control and ignore checks.")
            return
        secret_paths = [".env", "memory/api_keys.json", "memory/bambu_connection.json", "memory/prusa_connection.json"]
        missing_ignore: list[str] = []
        for path in secret_paths:
            result = subprocess.run(
                [git, "check-ignore", path],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode != 0:
                missing_ignore.append(path)
        if missing_ignore:
            self.fail("secret ignore policy", "not ignored: " + ", ".join(missing_ignore), "Update .gitignore before entering secrets.")
        else:
            self.ok("secret ignore policy", "local secret paths are ignored")

    def run(self) -> list[dict[str, str]]:
        self.check_core_files()
        self.check_python()
        self.check_env()
        self.check_imports()
        self.check_app_import()
        self.check_cli()
        self.check_secrets_policy()
        if not self.core_only:
            self.check_bambu()
            self.check_prusa()
            self.check_lerobot()
            self.check_realsense()
            self.check_models()
        return self.results

    def exit_code(self) -> int:
        return 1 if any(item["level"] == "fail" for item in self.results) else 0


def render_text(results: list[dict[str, str]]) -> None:
    labels = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
    for item in results:
        level = labels.get(item["level"], item["level"].upper())
        print(f"[{level}] {item['name']}: {item['detail']}")
        if item.get("hint"):
            print(f"       hint: {item['hint']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check autonomous_researcher fresh-install readiness.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--core-only", action="store_true", help="Skip optional hardware/external-tool checks.")
    parser.add_argument("--hardware", action="store_true", help="Allow passive hardware enumeration checks.")
    args = parser.parse_args()

    doctor = Doctor(core_only=bool(args.core_only), hardware=bool(args.hardware))
    results = doctor.run()
    if args.json:
        print(json.dumps({"ok": doctor.exit_code() == 0, "results": results}, ensure_ascii=False, indent=2))
    else:
        render_text(results)
    return doctor.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
