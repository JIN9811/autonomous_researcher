#!/usr/bin/env python3
"""
ATR packaged Piper TTS wrapper for LeRobot recording cues.

This wrapper is intentionally small and process-based because LeRobot recording runs
inside its own conda environment. The bridge passes this script path through env vars,
so recording can use ATR's packaged Piper runtime without modifying the LeRobot env.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VOICE_DIR = REPO_ROOT / "models" / "tts" / "piper" / "en_US-lessac-medium"
DEFAULT_MODEL = DEFAULT_VOICE_DIR / "en_US-lessac-medium.onnx"
DEFAULT_CONFIG = DEFAULT_VOICE_DIR / "en_US-lessac-medium.onnx.json"
DEFAULT_PIPER_BIN = REPO_ROOT / ".venv" / "bin" / "piper"


def _clamp_rate(value: int) -> int:
    return max(-100, min(100, int(value)))


def _length_scale_from_rate(rate: int) -> float:
    # LeRobot GUI follows Speech Dispatcher semantics: -100 slow, +100 fast.
    # Piper uses length-scale semantics: >1 slow, <1 fast.
    return round(max(0.65, min(1.35, 1.0 - (_clamp_rate(rate) * 0.0035))), 3)


def _fallback_spd_say(text: str, rate: int) -> int:
    spd_say = shutil.which("spd-say")
    if not spd_say:
        print("Piper failed and spd-say fallback is unavailable.", file=sys.stderr)
        return 1
    return subprocess.run([spd_say, "--rate", str(_clamp_rate(rate)), text], check=False).returncode


def _player_cmd(wav_path: Path, player: str) -> list[str] | None:
    if player:
        resolved = shutil.which(player) or player
        return [resolved, str(wav_path)]
    if aplay := shutil.which("aplay"):
        return [aplay, "-q", str(wav_path)]
    if paplay := shutil.which("paplay"):
        return [paplay, str(wav_path)]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Speak a short LeRobot cue with ATR packaged Piper TTS.")
    parser.add_argument("text", nargs="?", default="", help="Text to speak. If omitted, stdin is used.")
    parser.add_argument("--model", default=str(DEFAULT_MODEL), help="Piper ONNX voice model path.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Piper model JSON config path.")
    parser.add_argument("--piper-bin", default=str(DEFAULT_PIPER_BIN), help="Piper executable path.")
    parser.add_argument("--player", default="", help="Audio player executable. Defaults to aplay, then paplay.")
    parser.add_argument("--rate", type=int, default=-35, help="Speech rate in LeRobot GUI scale: -100..100.")
    parser.add_argument("--volume", type=float, default=1.0, help="Piper volume multiplier.")
    parser.add_argument("--sentence-silence", type=float, default=0.05, help="Silence after each sentence.")
    args = parser.parse_args()

    text = args.text or sys.stdin.read().strip()
    if not text:
        return 0

    piper_bin = Path(args.piper_bin).expanduser()
    model = Path(args.model).expanduser()
    config = Path(args.config).expanduser()
    if not piper_bin.exists() or not model.exists() or not config.exists():
        print(f"Piper runtime missing: bin={piper_bin} model={model} config={config}", file=sys.stderr)
        return _fallback_spd_say(text, args.rate)

    with tempfile.NamedTemporaryFile(prefix="atr_lerobot_tts_", suffix=".wav", delete=False) as handle:
        wav_path = Path(handle.name)

    try:
        piper_cmd = [
            str(piper_bin),
            "--model",
            str(model),
            "--config",
            str(config),
            "--output-file",
            str(wav_path),
            "--length-scale",
            str(_length_scale_from_rate(args.rate)),
            "--sentence-silence",
            str(max(0.0, args.sentence_silence)),
            "--volume",
            str(max(0.1, args.volume)),
        ]
        synth = subprocess.run(piper_cmd, input=f"{text}\n", text=True, capture_output=True, check=False)
        if synth.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
            if synth.stderr:
                print(synth.stderr.strip(), file=sys.stderr)
            return _fallback_spd_say(text, args.rate)

        player_cmd = _player_cmd(wav_path, args.player)
        if not player_cmd:
            print("No audio player found for Piper output.", file=sys.stderr)
            return _fallback_spd_say(text, args.rate)
        played = subprocess.run(player_cmd, check=False)
        return played.returncode
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
