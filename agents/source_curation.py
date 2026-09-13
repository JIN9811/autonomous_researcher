"""Compatibility alias for the canonical core Knowledge source-curation module."""

import sys

from agents.core.knowledge import source_curation as _implementation

sys.modules[__name__] = _implementation
