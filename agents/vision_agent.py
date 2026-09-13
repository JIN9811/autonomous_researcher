"""Legacy import shares the canonical Vision owner's monkeypatch boundaries."""
import sys
from agents.vision import agent as _owner

sys.modules[__name__] = _owner
