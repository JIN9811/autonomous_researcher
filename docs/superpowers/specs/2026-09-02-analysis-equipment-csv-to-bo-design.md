# Equipment CSV to BO Analysis Design

## Goal

Turn the Lab Equipment Agent's native TRAPEZIUMX compression CSV into a rich Analysis report while sending only the force-displacement energy integrated from 0 mm to 50% of the experiment-planned initial specimen height to the BO Agent.

## Authoritative input

- The input is the Linux-local `utm_csv` artifact produced by the Lab Equipment Agent.
- The native format is the observed CP949 TRAPEZIUMX export with title, header, unit, and numeric data rows.
- The raw artifact remains byte-for-byte unchanged and its path and SHA-256 remain in provenance.
- `specimen_id` is not required to parse a CSV. The current experiment plan and specimen result supply the initial height, cross-section, and mass.
- The measured displacement extent always comes from the CSV. No expected terminal displacement is hardcoded.

## Analysis behavior

- Reuse the Lab Equipment UTM parser instead of maintaining a second TRAPEZIUM parser.
- Preserve acquisition order while parsing. Analysis may sort the monotonic compression curve for displacement-domain calculations.
- Retain the existing metrics: peak force, peak displacement, stiffness, strength, modulus, peak strain, full-curve energy, energy density, and specific energy when mass is available.
- Add an integration boundary equal to `0.5 * gauge_length_mm`, where `gauge_length_mm` is resolved from the current experiment plan/specimen geometry. For the current 30 mm sample this evaluates to 15 mm, but neither value is fixed in code.
- Insert a linearly interpolated force at the boundary when the CSV does not contain an exact 15 mm row.
- Integrate by the trapezoidal rule. Since `N * mm = mJ`, the BO metric is `energy_absorption_50pct_mJ`.
- Compare the CSV-derived maximum displacement against the calculated boundary. Block BO readiness when the measured curve does not reach it; never assume a 21 mm endpoint and never extrapolate.
- If a real equipment artifact exists but cannot be parsed, do not replace it with a synthetic curve.

## BO contract

The full metric set remains in `analysis.utm_metrics` and the Analysis artifacts. The BO-facing observation and handoff expose one measured objective:

```json
{
  "metric_name": "energy_absorption_50pct_mJ",
  "unit": "mJ",
  "score": 1234.5,
  "observed_metrics": {
    "energy_absorption_50pct_mJ": 1234.5
  }
}
```

The existing `bo_observation.v1` and `analysis_bo_handoff_v2` envelope versions remain unchanged. Parameters, uncertainty, quality, trust, and provenance remain available, but unrelated measured metrics are not sent as BO training targets.

If a run has an explicitly activated compiled objective, that immutable binding remains authoritative and BO receives its single compiled `objective_score` instead. The 50%-height energy contract is the default physical-loop objective; it does not overwrite an operator-approved custom objective.

## Compatibility

- Keep canonical UTF-8 and legacy Analysis header/unit parsing.
- Keep the Lab Equipment probe payload compact; canonical numeric rows are returned only by the new parse API.
- The BO Agent continues to accept older SEA observations while preferring the metric explicitly named by a new Analysis handoff.
- Existing activated compiled-objective runs continue to train BO on the bound objective score and hash.
