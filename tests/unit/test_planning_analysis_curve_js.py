"""Executable regression tests for the Analysis stress-strain figure helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLANNING_JS = PROJECT_ROOT / "web" / "static" / "planning.js"


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    assert start >= 0, f"{name} helper is missing from planning.js"
    signature_depth = 0
    body_search_start = -1
    for index in range(start + len(f"function {name}"), len(source)):
        char = source[index]
        if char == "(":
            signature_depth += 1
        elif char == ")":
            signature_depth -= 1
            if signature_depth == 0:
                body_search_start = index + 1
                break
    assert body_search_start >= 0
    brace = source.find("{", body_search_start)
    assert brace >= 0
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"{name} helper body is incomplete")


def _node_eval(script: str) -> str:
    node = shutil.which("node")
    assert node, "node is required for planning.js Analysis figure tests"
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_analysis_stress_strain_points_prefer_server_contract_and_normalize_legacy_reports() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    helper = _extract_function(source, "analysisStressStrainPoints")
    script = f"""
const dashboardFiniteNumber = (value) => {{
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}};
{helper}
const server = analysisStressStrainPoints({{
  stress_strain_curve: {{ preview: [
    {{ strain: 0, strain_pct: 0, stress_MPa: 0, force_N: 0 }},
    {{ strain: 0.5, strain_pct: 50, stress_MPa: 1, force_N: 200 }},
  ] }},
  specimen_geometry: {{ cross_section_area_mm2: 999, gauge_length_mm: 999 }},
}});
const legacy = analysisStressStrainPoints({{
  utm_curve: {{ preview: [
    {{ displacement_mm: 0, force_N: 0 }},
    {{ displacement_mm: 15, force_N: 200 }},
  ] }},
  specimen_geometry: {{ cross_section_area_mm2: 200, gauge_length_mm: 30 }},
}});
const invalid = analysisStressStrainPoints({{
  utm_curve: {{ preview: [{{ displacement_mm: 15, force_N: 200 }}] }},
  specimen_geometry: {{ cross_section_area_mm2: 0, gauge_length_mm: 30 }},
}});
console.log(JSON.stringify({{ server, legacy, invalid }}));
"""

    result = json.loads(_node_eval(script))

    assert result["server"] == [
        {"strain_pct": 0, "stress_MPa": 0},
        {"strain_pct": 50, "stress_MPa": 1},
    ]
    assert result["legacy"] == result["server"]
    assert result["invalid"] == []


def test_analysis_curve_renders_scientific_axes_ticks_and_50pct_reference() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    helpers = "\n".join(
        _extract_function(source, name)
        for name in ("analysisStressStrainPoints", "analysisScientificTicks", "renderAnalysisCurve")
    )
    script = f"""
const dashboardFiniteNumber = (value) => {{
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}};
const renderVizEmpty = (message) => `<p>${{message}}</p>`;
const numberText = (value, digits = 2) => String(Number(Number(value).toFixed(digits)));
const polyline = (points) => points.map((point) => point.join(",")).join(" ");
const escapeHtml = (value) => String(value);
{helpers}
const html = renderAnalysisCurve({{
  stress_strain_curve: {{ preview: [
    {{ strain_pct: 0, stress_MPa: 0 }},
    {{ strain_pct: 25, stress_MPa: 0.8 }},
    {{ strain_pct: 50, stress_MPa: 1.0 }},
  ] }},
}});
console.log(html);
"""

    html = _node_eval(script)

    assert "Engineering compressive strain" in html
    assert "Engineering stress" in html
    assert "50% strain" in html
    assert "class=\"grid\"" in html
    assert "class=\"tick-label" in html
    assert "class=\"limit-reference\"" in html
    assert "class=\"curve\"" in html
    assert "class=\"peak\"" not in html
    assert "<circle" not in html
