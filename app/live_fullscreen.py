"""Local desktop presentation only; never invokes runtime/device controls."""
import asyncio
import ipaddress
import re
import shutil
import subprocess

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


class LiveWindow(BaseModel):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")


def enter_live_fullscreen(token: str) -> bool:
    if not re.fullmatch(r"[a-f0-9]{32}", token) or not shutil.which("wmctrl"):
        return False
    title = f"AX4LAB LIVE [{token}]"
    try:
        windows = subprocess.run(["wmctrl", "-lx"], capture_output=True,
                                 text=True, timeout=2, check=True).stdout
        matches = []
        for line in windows.splitlines():
            fields = line.split(None, 4)
            if len(fields) != 5:
                continue
            window_id, _, window_class, _, window_title = fields
            if ("firefox" in window_class.lower()
                    and window_title in (title, title + " — Mozilla Firefox")
                    and re.fullmatch(r"0x[0-9a-fA-F]+", window_id)):
                matches.append(window_id)
        if len(matches) != 1:
            return False
        # Add, never toggle: an already fullscreen window must stay fullscreen.
        # No focus/keyboard injection, so another app cannot receive an F11.
        subprocess.run(["wmctrl", "-ir", matches[0], "-b", "add,fullscreen"],
                       capture_output=True, timeout=2, check=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


@router.post("/api/ui/live-fullscreen")
async def live_fullscreen(payload: LiveWindow, request: Request):
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local = False
    origin = request.headers.get("origin", "")
    if not local or origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Local same-origin desktop requests only")
    # Firefox may take a moment to publish the new page title to the WM.
    for _ in range(8):
        if await asyncio.to_thread(enter_live_fullscreen, payload.token):
            return {"ok": True}
        await asyncio.sleep(0.2)
    return {"ok": False}
