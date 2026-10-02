# Packaged Piper TTS

ATR uses Piper as the default LeRobot recording cue voice engine.

Packaged voice:

- `en_US-lessac-medium`: local English neural voice for recording status cues.
- Model path: `models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx`
- Config path: `models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx.json`

Install or repair the local runtime from the repository root:

```bash
bash install/install_piper_tts.sh
```

The LeRobot bridge passes these paths to the recording subprocess through
`LEROBOT_TTS_PIPER_*` environment variables. The LeRobot conda environment does
not need to install Piper separately.
