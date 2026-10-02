#!/usr/bin/env python3
"""Inspect or disable USB autosuspend for RealSense-class cameras.

This script is intentionally small and explicit: it never remaps cameras and it
does not open a camera stream. It only reads/writes Linux sysfs power-control
knobs for currently enumerated USB devices.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


REALSENSE_VENDOR_ID = "8086"
BRIO_VENDOR_PRODUCT = ("046d", "085e")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _write(path: Path, value: str) -> tuple[bool, str]:
    try:
        path.write_text(value, encoding="utf-8")
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _iter_usb_devices(include_brio: bool) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for device_dir in sorted(Path("/sys/bus/usb/devices").glob("*")):
        vendor = _read(device_dir / "idVendor").lower()
        product_id = _read(device_dir / "idProduct").lower()
        if not vendor:
            continue
        is_realsense = vendor == REALSENSE_VENDOR_ID
        is_brio = include_brio and (vendor, product_id) == BRIO_VENDOR_PRODUCT
        if not (is_realsense or is_brio):
            continue
        rows.append(
            {
                "sysfs": str(device_dir),
                "bus_port": device_dir.name,
                "vendor_product": f"{vendor}:{product_id}",
                "product": _read(device_dir / "product"),
                "serial": _read(device_dir / "serial"),
                "speed": _read(device_dir / "speed"),
                "power_control": _read(device_dir / "power" / "control"),
                "autosuspend": _read(device_dir / "power" / "autosuspend"),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or disable USB autosuspend for RealSense cameras.")
    parser.add_argument("--apply", action="store_true", help="Write power/control=on for matched devices.")
    parser.add_argument("--include-brio", action="store_true", help="Also include Logitech BRIO 4K webcam.")
    args = parser.parse_args()

    usbcore_autosuspend = _read(Path("/sys/module/usbcore/parameters/autosuspend")) or "unknown"
    print(f"usbcore.autosuspend={usbcore_autosuspend}")
    print(f"effective_uid={os.geteuid()}")

    rows = _iter_usb_devices(args.include_brio)
    if not rows:
        print("No matching USB RealSense devices are currently enumerated.")
        return 2

    for row in rows:
        print(
            "device "
            f"bus_port={row['bus_port']} "
            f"id={row['vendor_product']} "
            f"serial={row['serial'] or '-'} "
            f"product={row['product'] or '-'} "
            f"speed={row['speed'] or '-'} "
            f"power_control={row['power_control'] or '-'} "
            f"autosuspend={row['autosuspend'] or '-'}"
        )
        if args.apply:
            ok, error = _write(Path(row["sysfs"]) / "power" / "control", "on")
            if ok:
                print(f"applied bus_port={row['bus_port']} power_control=on")
            else:
                print(f"apply_failed bus_port={row['bus_port']} error={error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
