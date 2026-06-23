"""Isaac Sim extension that hosts the ATR ROBOTIS OMX mirror receiver in-process."""

from __future__ import annotations

import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    import omni.ext  # type: ignore
except Exception:  # pragma: no cover - exercised outside Isaac by unit tests
    class _BaseExtension:
        pass
else:
    _BaseExtension = omni.ext.IExt  # type: ignore[name-defined]


def _repo_root_from_extension() -> Path:
    """Find the autonomous_researcher repo root from this extension path."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "sim" / "robotis_omx" / "tools" / "isaac_omx_mirror_server.py").exists():
            return parent
    # extension.py -> mirror -> omx -> atr -> atr.omx.mirror -> extensions -> robotis_omx -> sim -> repo
    return here.parents[7]


def _settings() -> Any | None:
    try:
        import carb.settings  # type: ignore

        return carb.settings.get_settings()
    except Exception:
        return None


def _setting_string(settings: Any | None, key: str, default: str) -> str:
    if settings is None:
        return default
    try:
        value = settings.get_as_string(key)
    except Exception:
        try:
            value = settings.get(key)
        except Exception:
            value = None
    text = str(value or "").strip()
    return text or default


def _setting_int(settings: Any | None, key: str, default: int) -> int:
    if settings is None:
        return default
    try:
        value = settings.get_as_int(key)
    except Exception:
        try:
            value = settings.get(key)
        except Exception:
            value = None
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _setting_bool(settings: Any | None, key: str, default: bool) -> bool:
    if settings is None:
        return default
    try:
        value = settings.get_as_bool(key)
    except Exception:
        try:
            value = settings.get(key)
        except Exception:
            value = None
    if value is None:
        return default
    return bool(value)


def _log_info(message: str) -> None:
    try:
        import carb  # type: ignore

        carb.log_info(message)
    except Exception:
        print(message)


def _log_error(message: str) -> None:
    try:
        import carb  # type: ignore

        carb.log_error(message)
    except Exception:
        print(message)


def _open_gui_stage(scene_path: Path) -> str:
    """Ask Isaac's GUI USD context to open the mirror scene."""
    try:
        import omni.usd  # type: ignore

        context = omni.usd.get_context()
        if context is None:
            return "skipped:no_usd_context"
        result = context.open_stage(str(scene_path))
        return f"requested:{result}"
    except Exception as exc:
        return f"failed:{exc.__class__.__name__}: {exc}"


def _play_timeline() -> str:
    """Start Isaac's timeline so authored physics and drives are stepped."""
    try:
        import omni.timeline  # type: ignore

        timeline = omni.timeline.get_timeline_interface()
        if timeline is None:
            return "skipped:no_timeline"
        timeline.play()
        try:
            playing = bool(timeline.is_playing())
        except Exception:
            playing = True
        return f"playing:{playing}"
    except Exception as exc:
        return f"failed:{exc.__class__.__name__}: {exc}"


def install_delayed_timeline_play_subscription(delay_ticks: int) -> Any:
    """Start Isaac's timeline from an update callback after Kit has settled."""
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        stream = app.get_update_event_stream()
        remaining = max(1, int(delay_ticks))
        done = False

        def _on_update(_event: Any) -> None:
            nonlocal remaining, done
            if done:
                return
            remaining -= 1
            if remaining > 0:
                return
            done = True
            timeline_status = _play_timeline()
            _log_info(f"ATR OMX mirror delayed timeline status={timeline_status}")

        return stream.create_subscription_to_pop(_on_update, name="atr-isaac-omx-mirror-delayed-play")
    except Exception as exc:
        _log_error(f"ATR OMX mirror delayed timeline subscription failed: {exc.__class__.__name__}: {exc}")
        return None


class AtrOmxMirrorExtension(_BaseExtension):
    """Omniverse extension entrypoint for in-process Isaac mirror serving."""

    def __init__(self) -> None:
        super().__init__()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._state: Any | None = None
        self._subscription: Any | None = None
        self._timeline_subscription: Any | None = None
        self._endpoint = ""

    def on_startup(self, ext_id: str) -> None:  # noqa: D401 - Isaac extension API name
        """Start the HTTP mirror receiver inside the Isaac Sim process."""
        settings = _settings()
        if not _setting_bool(settings, "/exts/atr.omx.mirror/enabled", True):
            _log_info(f"[{ext_id}] ATR OMX mirror receiver disabled by settings")
            return
        if self._server is not None:
            return

        repo_root = _repo_root_from_extension()
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        from sim.robotis_omx.tools.isaac_omx_mirror_server import (  # pylint: disable=import-outside-toplevel
            DEFAULT_HOST,
            DEFAULT_PORT,
            DEFAULT_SCENE,
            IsaacMirrorState,
            install_kit_update_subscription,
            make_handler,
        )

        host = _setting_string(settings, "/exts/atr.omx.mirror/host", DEFAULT_HOST)
        port = _setting_int(settings, "/exts/atr.omx.mirror/port", DEFAULT_PORT)
        scene_setting = _setting_string(settings, "/exts/atr.omx.mirror/scene", "")
        scene_path = Path(scene_setting).expanduser().resolve() if scene_setting else Path(DEFAULT_SCENE).resolve()
        use_current_stage = _setting_bool(settings, "/exts/atr.omx.mirror/useCurrentStage", True)
        open_scene_on_startup = _setting_bool(settings, "/exts/atr.omx.mirror/openSceneOnStartup", True)
        play_timeline_on_startup = _setting_bool(settings, "/exts/atr.omx.mirror/playTimelineOnStartup", True)
        play_timeline_delay_ticks = _setting_int(settings, "/exts/atr.omx.mirror/playTimelineDelayTicks", 300)
        if use_current_stage and open_scene_on_startup:
            open_status = _open_gui_stage(scene_path)
            _log_info(f"[{ext_id}] ATR OMX mirror requested GUI stage scene={scene_path} status={open_status}")

        self._state = IsaacMirrorState(scene_path, use_current_stage=use_current_stage)
        self._subscription = install_kit_update_subscription(self._state)
        if play_timeline_on_startup:
            self._timeline_subscription = install_delayed_timeline_play_subscription(play_timeline_delay_ticks)
        self._server = ThreadingHTTPServer((host, port), make_handler(self._state))
        self._thread = threading.Thread(target=self._server.serve_forever, name="atr-isaac-omx-mirror", daemon=True)
        self._thread.start()
        self._endpoint = f"http://{host}:{port}/joints"
        mode = self._state.status_payload().get("apply_mode", "unknown")
        _log_info(f"[{ext_id}] ATR OMX mirror receiver listening at {self._endpoint} apply_mode={mode}")

    def on_shutdown(self) -> None:
        """Stop the in-process mirror receiver."""
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        self._subscription = None
        self._timeline_subscription = None
        self._state = None
        endpoint = self._endpoint
        self._endpoint = ""
        if server is not None:
            try:
                server.shutdown()
            except Exception as exc:  # pragma: no cover - best effort cleanup
                _log_error(f"ATR OMX mirror receiver shutdown failed: {exc}")
            try:
                server.server_close()
            except Exception:
                pass
        if thread is not None:
            thread.join(timeout=2.0)
        if endpoint:
            _log_info(f"ATR OMX mirror receiver stopped at {endpoint}")
