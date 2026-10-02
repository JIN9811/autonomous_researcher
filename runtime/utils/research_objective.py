"""Shared naming for the existing mass-normalized compression objective."""
import re

SEA_METRIC = "specific_energy_absorption_J_per_g"


def uses_sea(spec, goal=""):
    spec = spec if isinstance(spec, dict) else {}
    text = " ".join(str(spec.get(key) or "") for key in ("objective_type", "metric_name", "primary_metric"))
    text = (text + " " + str(goal)).lower()
    return bool(re.search(r"\bsea\b", text) or any(token in text for token in (
        "specific_energy_absorption", "specific energy", "energy_absorption_per_mass")))
