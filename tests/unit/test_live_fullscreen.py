from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import live_fullscreen as module

TOKEN = "a" * 32


def test_only_exact_live_firefox_window_enters_fullscreen(monkeypatch):
    calls = []
    rows = ("0x123 0 Navigator.firefox host Autonomous Researcher Dashboard — Mozilla Firefox\n"
            "0x124 0 Navigator.firefox host Replay GUI — Mozilla Firefox\n"
            f"0x125 0 Navigator.firefox host AX4LAB LIVE [{TOKEN}] — Mozilla Firefox\n")
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/wmctrl")
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=rows)
    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.enter_live_fullscreen(TOKEN)
    assert calls == [["wmctrl", "-lx"], ["wmctrl", "-ir", "0x125", "-b", "add,fullscreen"]]


def test_missing_ambiguous_or_other_application_never_receives_action(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda _: "wmctrl")
    row = f"0x125 0 Navigator.firefox host AX4LAB LIVE [{TOKEN}] — Mozilla Firefox\n"
    for rows in ("", row + row, row.replace("Navigator.firefox", "terminal")):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(stdout=rows)
        monkeypatch.setattr(module.subprocess, "run", run)
        assert not module.enter_live_fullscreen(TOKEN)
        assert calls == [["wmctrl", "-lx"]]


def test_desktop_route_requires_loopback_and_same_origin(monkeypatch):
    app = FastAPI()
    app.include_router(module.router)
    calls = []
    monkeypatch.setattr(module, "enter_live_fullscreen", lambda token: calls.append(token) or True)
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        assert client.post("/api/ui/live-fullscreen", json={"token": TOKEN}).status_code == 403
        assert client.post("/api/ui/live-fullscreen", json={"token": TOKEN}, headers={"Origin": "https://other.test"}).status_code == 403
        assert client.post("/api/ui/live-fullscreen", json={"token": "bad"}, headers={"Origin": "http://testserver"}).status_code == 422
        assert client.post("/api/ui/live-fullscreen", json={"token": TOKEN}, headers={"Origin": "http://testserver"}).json() == {"ok": True}
    with TestClient(app, client=("192.0.2.1", 1234)) as client:
        assert client.post("/api/ui/live-fullscreen", json={"token": TOKEN}, headers={"Origin": "http://testserver"}).status_code == 403
    assert calls == [TOKEN]
