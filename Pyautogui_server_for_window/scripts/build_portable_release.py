#!/usr/bin/env python3
"""Build a copy-and-click Windows x64 Equipment Bridge release folder."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.13.14"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-amd64.exe"
PYTHON_SHA256 = "c54d9b9bbb8a36e6489363ddd01139707fd781d72f1f9e90c7ec65d0061368e0"

PURE_WHEEL_REQUIREMENTS = (
    "PyAutoGUI==0.9.54",
    "pynput>=1.7.7,<2",
    "pywinauto>=0.6.9,<1",
    "pytesseract>=0.3.13,<1",
    "comtypes>=1.4,<2",
    "pymsgbox",
    "pytweening",
    "pyscreeze",
    "pygetwindow",
    "pyrect",
    "mouseinfo",
    "pyperclip",
    "six",
    "packaging",
)

WINDOWS_WHEEL_REQUIREMENTS = (
    "Pillow>=10.0,<13",
    "opencv-python>=4.9,<5",
    "numpy>=2.0,<2.3",
    "pywin32>=306",
)

REQUIRED_WHEEL_PROJECTS = {
    "comtypes",
    "mouseinfo",
    "numpy",
    "opencv-python",
    "packaging",
    "pillow",
    "pyautogui",
    "pygetwindow",
    "pymsgbox",
    "pynput",
    "pyperclip",
    "pyrect",
    "pyscreeze",
    "pytesseract",
    "pytweening",
    "pywin32",
    "pywinauto",
    "six",
}

COPY_DIRECTORIES = ("bridge", "demo", "docs", "examples", "scripts", "tests")
COPY_FILES = ("README.md", "requirements-portable.txt", "requirements-windows.txt")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_source_tree(output: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "artifacts", "dist", "build", ".venv")
    for directory in COPY_DIRECTORIES:
        shutil.copytree(PACKAGE_ROOT / directory, output / directory, ignore=ignore)
    for filename in COPY_FILES:
        shutil.copy2(PACKAGE_ROOT / filename, output / filename)
    portable = PACKAGE_ROOT / "portable"
    for source in portable.iterdir():
        if source.is_file():
            shutil.copy2(source, output / source.name)
    for directory in ("artifacts", "locators", "utm_exports", "programs", "recordings", "logs"):
        (output / "data" / directory).mkdir(parents=True, exist_ok=True)


def run(command: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def wheel_project_name(path: Path) -> str:
    distribution = path.name.split("-", 1)[0]
    return distribution.replace("_", "-").lower()


def validate_wheelhouse(wheelhouse: Path) -> None:
    wheels = sorted(wheelhouse.glob("*.whl"))
    projects = {wheel_project_name(path) for path in wheels}
    missing = sorted(REQUIRED_WHEEL_PROJECTS - projects)
    if missing:
        raise RuntimeError(f"Portable wheelhouse is incomplete: {', '.join(missing)}")

    incompatible = []
    for path in wheels:
        filename = path.name.lower()
        if "-win_amd64.whl" in filename and not ("-cp313-" in filename or "-abi3-" in filename):
            incompatible.append(path.name)
    if incompatible:
        raise RuntimeError(f"Windows wheel ABI mismatch: {', '.join(incompatible)}")


def prepare_offline_runtime(output: Path) -> None:
    python_dir = output / "vendor" / "python"
    wheelhouse = output / "vendor" / "wheelhouse"
    python_dir.mkdir(parents=True, exist_ok=True)
    wheelhouse.mkdir(parents=True, exist_ok=True)

    installer = python_dir / "python-installer-amd64.exe"
    print(f"Downloading official Python {PYTHON_VERSION} Windows x64 installer...", flush=True)
    urllib.request.urlretrieve(PYTHON_URL, installer)
    actual_hash = sha256(installer)
    if actual_hash != PYTHON_SHA256:
        raise RuntimeError(f"Python installer SHA256 mismatch: expected={PYTHON_SHA256} actual={actual_hash}")

    for requirement in PURE_WHEEL_REQUIREMENTS:
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheelhouse), requirement])
    for requirement in WINDOWS_WHEEL_REQUIREMENTS:
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--dest",
                str(wheelhouse),
                "--platform",
                "win_amd64",
                "--python-version",
                "313",
                "--implementation",
                "cp",
                "--abi",
                "cp313",
                "--only-binary=:all:",
                "--no-deps",
                requirement,
            ]
        )

    validate_wheelhouse(wheelhouse)


def write_manifest(output: Path, *, source_only: bool, version: str) -> Path:
    files = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        relative = path.relative_to(output).as_posix()
        if relative == "portable_manifest.json":
            continue
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "schema": "atr.windows_equipment_bridge.portable.v1",
        "version": version,
        "architecture": "windows-x64",
        "python_version": None if source_only else PYTHON_VERSION,
        "offline_ready": not source_only,
        "entrypoint": "START_EQUIPMENT_BRIDGE.cmd",
        "data_root": "data",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    manifest_path = output / "portable_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return manifest_path


def create_zip(output: Path) -> Path:
    zip_path = output.with_suffix(".zip")
    if zip_path.exists():
        raise FileExistsError(f"Refusing to replace existing ZIP: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in output.rglob("*") if item.is_file()):
            archive.write(path, Path(output.name) / path.relative_to(output))
    return zip_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New release folder to create.")
    parser.add_argument("--version", default="dev")
    parser.add_argument("--source-only", action="store_true", help="Skip runtime downloads for contract tests.")
    parser.add_argument("--no-zip", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)
    copy_source_tree(output)
    if not args.source_only:
        prepare_offline_runtime(output)
    manifest = write_manifest(output, source_only=args.source_only, version=str(args.version))
    print(f"Portable manifest: {manifest}")
    if not args.no_zip:
        print(f"Portable ZIP: {create_zip(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
