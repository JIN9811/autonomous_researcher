"""
File purpose:
- Surrogate model placeholder for BO and active learning workflows.

Key classes/functions:
- SurrogateModel

Inputs/outputs:
- Input: training samples and labels
- Output: predicted score and uncertainty

Dependencies:
- none

Modification guide:
- Safe places to edit: prediction formula or model backend integration
- Risky places to edit: output schema used by BO engine
- Related files: learning/bo_engine.py, learning/uncertainty.py
"""

from __future__ import annotations


class SurrogateModel:
    """Minimal surrogate model interface stub."""

    def predict(self, x: list[float]) -> tuple[float, float]:
        """Return synthetic score and uncertainty."""
        score = sum(x) / max(len(x), 1)
        uncertainty = max(0.05, 0.5 / max(len(x), 1))
        return score, uncertainty
