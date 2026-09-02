# Analysis Stress-Strain and Energy-Density Design

## Goal

Convert the measured UTM force-displacement response into a specimen-size-normalized engineering stress-strain response, use its integral through 50% compressive strain as the default BO objective, and replace the Analysis dashboard's neon force-displacement preview with a publication-style scientific stress-strain figure.

The raw force-displacement record remains authoritative evidence. Normalization adds a comparable structural-performance view; it does not replace or rewrite the equipment artifact.

## Scientific basis

For the initial apparent loaded area `A0`, initial specimen height `H0`, compressive force `F`, and compressive displacement `delta`, Analysis uses

```text
engineering stress:  sigma = F / A0
engineering strain: epsilon = delta / H0
initial volume:       V0 = A0 * H0
```

With `F` in N and geometry in mm, `sigma` is in `N/mm2`, numerically equal to MPa. Compression is represented as positive stress and positive strain.

The default BO objective is the area under the engineering stress-strain curve through 50% strain:

```text
U50 = integral(sigma d epsilon), epsilon = 0 ... 0.5
```

Its dimension is energy per initial volume:

```text
MPa = N/mm2 = mJ/mm3 = MJ/m3
```

The total energy and normalized energy density obey

```text
W50 = integral(F d delta) = V0 * U50
```

Consequently, the stress-strain integral must be named energy density rather than energy. Total force-displacement energy remains available in mJ for physical traceability.

This convention follows compression studies that convert measured force-displacement data with initial specimen geometry and report energy absorption as the stress-strain integral:

- Scientific Reports, "Topology-alloy interactions governing deformation and failure in LPBF-fabricated A286 and Inconel 718 lattice structures": https://www.nature.com/articles/s41598-026-55663-x
- Materials, "Novel Negative Poisson's Ratio Lattice Structures with Enhanced Stiffness and Energy Absorption Capacity": https://www.mdpi.com/1996-1944/11/7/1095
- Nature Communications, "Mechanical metamaterials made of freestanding quasi-BCC nanolattices of gold and copper with ultra-high energy absorption capacity": https://www.nature.com/articles/s41467-023-36965-4

## Geometry authority

Analysis resolves normalization geometry from the current experiment plan and specimen result using the existing precedence:

1. explicit `cross_section_area_mm2`, otherwise `specimen_size_mm[0] * specimen_size_mm[1]`;
2. explicit `gauge_length_mm` or `height_mm`, otherwise `specimen_size_mm[2]`;
3. `V0 = A0 * H0` for the energy identity.

The measured curve endpoint always comes from the UTM artifact. The implementation must not hardcode 30 mm, 21 mm, 15 mm, or any other specimen dimension or terminal displacement.

Zero-offset removal continues to use the first valid force and displacement sample, matching the existing canonical-curve contract. No smoothing is introduced. Load drops and serrations caused by lattice buckling, fracture, or progressive collapse remain visible and contribute to the integral.

Invalid, zero, negative, or non-finite normalization geometry blocks normalized curve generation and BO readiness. Analysis must not silently substitute default geometry after an explicit invalid experiment value has been supplied.

## Analysis data contract

### Preserved force-displacement evidence

The following remain available and backward compatible:

- the original equipment CSV and its fingerprint;
- `analysis.utm_curve`, a compact force-displacement preview;
- `canonical_curve.csv`, containing force, displacement, engineering stress, and engineering strain;
- existing force, displacement, stiffness, total-energy, provenance, and quality fields.

### New runtime stress-strain curve

Analysis adds `analysis.stress_strain_curve`:

```json
{
  "schema": "engineering_stress_strain_curve.v1",
  "convention": "positive_compression",
  "stress_unit": "MPa",
  "strain_unit": "1",
  "normalization": {
    "area_basis": "initial_apparent_cross_section",
    "cross_section_area_mm2": 900.0,
    "height_basis": "initial_gauge_length",
    "gauge_length_mm": 30.0,
    "initial_volume_mm3": 27000.0
  },
  "point_count": 1001,
  "preview": [
    {
      "strain": 0.5,
      "strain_pct": 50.0,
      "stress_MPa": 1.25,
      "displacement_mm": 15.0,
      "force_N": 1125.0
    }
  ]
}
```

The preview is capped at 200 points. Ordered bucket extrema, plus the first and last points, are retained so a compact runtime payload preserves meaningful load drops and peaks better than sparse index sampling. The full-resolution canonical CSV remains the numerical authority.

### New metrics

`analysis.utm_metrics` adds:

```json
{
  "energy_density_50pct_MJ_per_m3": 0.625,
  "energy_density_limit_strain": 0.5,
  "energy_density_limit_reached": true,
  "energy_identity_relative_error": 0.0
}
```

`energy_density_50pct_MJ_per_m3` is integrated from the canonical engineering stress-strain response with a linearly interpolated point at `epsilon = 0.5` when needed. No extrapolation is allowed. If the measured response does not reach 50%, this metric is `null` and the existing BO readiness gate remains closed.

`energy_identity_relative_error` compares the normalized integral against `energy_absorption_50pct_mJ / V0`. It is a diagnostic for implementation and provenance, not a separate optimization target.

The objective metric registry adds the lower-case identifier `energy_density_50pct_mj_per_m3`, mapped to the Analysis field `energy_density_50pct_MJ_per_m3`, unit `MJ/m3`, dimension `energy_density`.

## BO contract

When no operator-approved compiled objective is active, Analysis sends one default measured target:

```json
{
  "metric_name": "energy_density_50pct_MJ_per_m3",
  "unit": "MJ/m3",
  "objective_score": 0.625,
  "observed_metrics": {
    "energy_density_50pct_MJ_per_m3": 0.625
  }
}
```

The optimization direction remains `maximize`. Envelope versions `bo_observation.v1` and `analysis_bo_handoff_v2` remain unchanged because this is a metric selection change within their existing explicit-name contract.

An activated compiled objective remains authoritative. This change must not replace its metric, score, unit, hash, feasibility, or provenance.

The former `energy_absorption_50pct_mJ` remains in Analysis artifacts and metrics, but is no longer the default BO target. It can still be selected through an explicitly compiled objective.

## Dashboard figure

The Analysis dashboard card becomes `Engineering Stress-Strain Curve` and reads `analysis.stress_strain_curve.preview`. Older reports without the new field may be normalized client-side from `analysis.utm_curve` and `analysis.specimen_geometry`, but new reports must use the server-derived curve.

The figure uses a restrained publication-style presentation:

- white plotting surface;
- charcoal axes, ticks, tick labels, and axis titles;
- light neutral major grid lines;
- Matplotlib default blue `#1f77b4` for the measured UTM curve;
- approximately 2 px solid stroke with no glow, gradient, shadow, or neon accent;
- x-axis title `Engineering compressive strain, ε (%)`;
- y-axis title `Engineering stress, σ (MPa)`;
- a thin neutral dashed reference at 50% strain when the curve reaches it;
- no peak marker or decorative annotation that could obscure serrated collapse behavior.

Both axes include numeric tick labels. The plot domain starts at zero for an honest magnitude comparison and expands slightly above the observed maximum stress. The surrounding dark operator dashboard remains unchanged; only the scientific figure surface becomes paper-like.

## Error and compatibility behavior

- Missing or invalid geometry produces an explicit normalization failure and blocks the default BO objective.
- A curve ending below 50% strain remains displayable but cannot produce the default objective.
- The raw UTM curve and total energy remain available for old consumers and auditing.
- Old Analysis reports continue to render through the documented frontend fallback.
- No other agent, equipment protocol, Windows bridge, or CalculiX boundary condition changes as part of this work.
- Existing unrelated uncommitted GUI and Equipment changes must be preserved.

## Verification

Implementation follows test-driven development.

Backend tests must demonstrate with hand-derived values that:

1. `F = 200 N`, `A0 = 200 mm2` produces `sigma = 1 MPa`;
2. `delta = 15 mm`, `H0 = 30 mm` produces `epsilon = 0.5`;
3. a linear `0 ... 1 MPa` curve through 50% strain integrates to `0.25 MJ/m3`;
4. multiplying the normalized integral by `V0` reproduces force-displacement energy within numerical tolerance;
5. an interpolated 50% endpoint is used without extrapolation;
6. invalid geometry or an endpoint below 50% blocks the default BO observation;
7. an activated compiled objective is unchanged;
8. preview downsampling preserves order, endpoints, and bucket extrema.

Frontend tests execute the real curve-normalization and SVG-rendering helpers against controlled payloads and verify visible stress/strain units, numeric ticks, the 50% reference, and backward-compatible fallback behavior. CSS and final rendered SVG are inspected for a white surface, restrained scientific palette, legible labels, and absence of curve glow.
