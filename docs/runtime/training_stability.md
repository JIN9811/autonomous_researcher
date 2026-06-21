# Training Stability and Crash Diagnosis

This page records the runtime policy for long LeRobot/Pi0.5 training runs on the
ATR workstation.

## 2026-06-19 Pi0.5 Training Crash Summary

Observed training run:

- Output directory: `outputs/train/260619_train`
- Training log: `runs/lerobot_sessions/session-exp-20260619T093043Z-48c8.log`
- Last durable checkpoint: `outputs/train/260619_train/checkpoints/000500`
- Checkpoint size: approximately `20G`
- Checkpoint step file: `training_state/training_step.json` reports `step=500`

Log interpretation:

- The run did not fail at step 500.
- Step 500 checkpoint was written at `2026-06-19 20:27:30 KST`.
- Training continued through step 505, step 510, and step 515.
- Last training line was `2026-06-19 20:31:36 KST step:515`.
- The previous boot ended abruptly at `2026-06-19 20:32:02 KST` with no clean
  shutdown entry.
- No Python traceback, CUDA OOM, kernel OOM killer, systemd-oomd event, NVIDIA
  Xid, or thermal shutdown message was found in the inspected logs.

Most likely class of failure from available evidence:

- Host-level hard reset, power loss, kernel/GPU hard hang, or hardware watchdog
  condition, not a normal LeRobot training exception.
- The step 500 checkpoint write is a plausible stress point because the saved
  artifact includes both model and optimizer state and is about `20G`.

Concrete abnormality found during the same window:

- The local `ollama.service` was configured to execute `/usr/bin/ollama serve`.
- The installed binary was `/usr/local/bin/ollama`.
- systemd repeatedly failed the unit with `status=203/EXEC` and restarted it
  every few seconds; restart counter reached approximately `49k` before the
  crash window.
- ATR does not require this broken systemd unit for LeRobot training. Stop and
  disable the service before long training unless deliberately testing local
  Ollama systemd serving.

## Pre-Training Checklist

Before long Pi0.5 training:

```bash
systemctl is-active ollama.service || true
systemctl is-enabled ollama.service || true
free -h
df -h / /home/jin
nvidia-smi
```

If `ollama.service` is in a restart loop, stop it:

```bash
sudo systemctl stop ollama.service || true
sudo systemctl disable ollama.service || true
sudo systemctl reset-failed ollama.service || true
```

Do not start unrelated local LLM services during robot policy training unless the
experiment explicitly needs them.

## Passive Training Monitor

Use the passive monitor while training. It does not control the robot, model
server, printer, camera, or training process. It only writes host diagnostics to
`runs/training_watch/`.

When LeRobot training is started from the ATR GUI bridge in `live` mode, the
bridge starts this monitor automatically and returns the monitor PID/output
directory in the training session response. Stop/canceling the GUI training
session also stops the attached monitor. Manual monitor commands are only needed
for CLI-only training or post-crash diagnosis outside the GUI.

One-shot smoke check:

```bash
python scripts/training_stability_monitor.py --once
```

Recommended long-run monitor:

```bash
python scripts/training_stability_monitor.py \
  --interval-seconds 30 \
  --train-log runs/lerobot_sessions/session-exp-20260619T093043Z-48c8.log \
  --checkpoint-dir outputs/train/260619_train/checkpoints/000500
```

The monitor records:

- UTC timestamp and host uptime
- RAM and disk state
- NVIDIA GPU memory, temperature, power draw, and utilization when available
- top RSS processes
- recent kernel warnings/errors
- recent system errors
- `ollama.service` status and recent unit logs
- optional checkpoint step file
- optional training log tail

The JSONL file is fsynced after every sample so the last records survive better
when the host crashes.

## Resume Policy

If a crash occurs after a checkpoint is written, resume from the latest complete
checkpoint directory rather than from the output root.

For the 2026-06-19 run, the durable resume candidate is:

```text
outputs/train/260619_train/checkpoints/000500
```

A later training log line alone is not sufficient to resume from that later step
unless the corresponding checkpoint directory exists and contains both:

- `pretrained_model/model.safetensors`
- `training_state/optimizer_state.safetensors`

## Next Diagnostic Escalation

If the host still powers off or hard-resets after disabling restart storms:

- log wall power/UPS status if available;
- lower checkpoint frequency or checkpoint only during supervised periods;
- record GPU temperature and power at 5-10 second intervals;
- check BIOS/kernel power management and watchdog settings;
- inspect `journalctl --list-boots`, `last -x`, and `runs/training_watch/*.jsonl`
  immediately after reboot.
