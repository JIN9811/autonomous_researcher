"""Compatibility alias for the canonical core Orchestrator decision module."""

import sys

from agents.core.orchestrator import decision as _implementation

sys.modules[__name__] = _implementation
