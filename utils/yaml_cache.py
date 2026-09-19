"""Bounded parse-only cache: read current bytes every time, return owned values.

No TTL or mtime assumption: atomic replacements, same-size edits and restored
timestamps are visible immediately. Runtime validation still runs in callers.
"""
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from threading import RLock

import yaml

_LOCK = RLock()


@lru_cache(maxsize=128)
def _parse(text: str):
    return yaml.safe_load(text)


def read_yaml(path: str | Path):
    text = Path(path).read_text(encoding="utf-8")
    # Large uploaded documents should not occupy the configuration cache.
    if len(text) > 262144:
        return yaml.safe_load(text)
    with _LOCK:
        return deepcopy(_parse(text))
