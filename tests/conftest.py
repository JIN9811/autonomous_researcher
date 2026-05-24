"""Pytest bootstrap to ensure project root is importable."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep automated tests deterministic and lightweight.
os.environ.setdefault("AUTONOMOUS_USE_REAL_LLM_IN_TEST", "0")
os.environ.setdefault("AUTONOMOUS_ALLOW_MOCK_FALLBACK", "1")
os.environ.setdefault("AUTONOMOUS_BACKEND", "ollama")
os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:9")
