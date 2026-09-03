# Safe Preflight Closed-Loop Design

## Goal

Run the complete Design → Specimen → Vision → Manipulation/VLA → Lab Equipment → Analysis/CAE → Knowledge → BO → redesign cycle without actuating the printer, camera runtime, robot, or UTM. Preserve the same typed handoffs needed for a later physical run, and make a user-selected real printer path produce and validate specimen-specific G-code plus position-aware Bambu auto-ejection before any print is allowed.

This design composes the existing Lab Equipment agentic task, stress–strain energy-density, and CalculiX quasi-static compression contracts. It does not introduce a second orchestrator or a second BO objective.

## Safety boundary

The execution policy is explicit and per stage:

```json
{
  "execution_policy": {
    "printer": "preflight_only",
    "manipulation": "preflight_only",
    "lab_equipment": "preflight_only",
    "cae": "execute",
    "analysis": "execute",
    "bo": "execute"
  }
}
```

`preflight_only` is a successful preparation state, not a fake physical completion. It may inspect local artifacts, compile plans, validate profiles, and invoke deterministic non-device tools. It must not call an external actuation endpoint.

Forbidden during the non-actuating acceptance run:

- printer upload, start, pause, resume, cancel, or MQTT `gcode_line` publication;
- camera capture, active robot-camera startup, or UTM camera-runtime startup;
- `lerobot.rollout.start`, `robot.pick_place`, robot teleoperation, or motor writes;
- Windows/PyAutoGUI `/execute`, UTM start, jig motion, or equipment method mutation.

Health reads are not needed for the acceptance run and should be stubbed so the test has no network dependency.

## Closed-loop execution policy

The planning controller carries the policy in the experiment specification across every redesign cycle. BO parameter updates may modify only declared design variables; they must not remove or weaken the execution policy.

The policy has two intended deployments:

1. **Safe validation:** printer, Manipulation/VLA, and Lab Equipment are `preflight_only`; CAE, Analysis, BO, and redesign execute locally.
2. **Later physical run:** the operator explicitly selects a real printer and confirms physical output. Printer execution may then become `execute`, while robot and UTM retain their own independent confirmation gates. Selecting a printer must never implicitly enable robot or UTM actuation.

Unknown policy values fail closed. Legacy specifications without the field retain their current behavior.

## Printer and auto-ejection contract

In `preflight_only`, Specimen Agent must run the complete digital preparation path:

1. generate the candidate STL and preserve candidate identity;
2. slice or package the candidate into a plate-specific `.gcode.3mf` artifact;
3. validate the archive and `Metadata/plate_<id>.gcode` mapping;
4. extract the actual extrusion bounds from that exact plate G-code;
5. generate the native Bambu auto-ejection tail from the extracted object center, height, bed bounds, configured push lane, direction, Z offset, and motion limits;
6. patch a new immutable artifact and recompute the G-code MD5 entry;
7. validate that the patched artifact contains the original print body followed by one bounded ejection routine and that the routine is compatible with the object bounds;
8. emit a `printer_preflight.v1` record with source and patched hashes, plate ID, object bounds, ejection path/clearance evidence, and `ready_for_physical_start`.

The source file is never overwritten. The ejection tail must begin after the final extrusion, approach the rear push lane above both the configured safe Z and the object top clearance, and only then descend to the bounded sweep heights. Post-write validation reopens the artifact, checks its plate mapping, embedded MD5, tail order and motion invariants, and SHA-256. The same SHA is checked again immediately before export/upload and immediately before print-start publication. A missing extrusion bound, out-of-bed object, unsafe Z/push path, wrong plate mapping, missing ejection configuration, changed hash, or invalid archive blocks readiness. The test must prove no upload or print-start call occurs.

The policy boundary applies to every supported real-printer provider. Bambu produces a validated `.gcode.3mf`; Prusa performs a real local PrusaSlicer pass, extracts extrusion bounds, appends and validates its position-aware bed-sweep tail, and stops before any PrusaLink status, storage, upload, or start operation.

When the user later selects a real printer, Specimen Agent may upload/start only the same hash-verified patched artifact. The physical run remains subject to the existing explicit confirmation and printer readiness gates.

## Vision transfer preflight contract

When both the printer and Manipulation policies are `preflight_only`, Vision Agent must not capture a frame or start an active robot/UTM camera runtime. It derives only the identities and intended transfer boundary from the verified printer preflight, then emits:

```json
{
  "schema": "vision_preflight.v1",
  "status": "execution_ready_pending_approval",
  "capture_performed": false,
  "actuation_performed": false,
  "requested_next_stage": "Manipulation"
}
```

This record is not a fabricated detection, pose estimate, or pickup confirmation. It must carry the current run/specimen identity and a hash that still matches the local artifact. Manipulation may consume it only while its own policy remains `preflight_only`; an executing physical transfer still requires a fresh camera observation through the existing Vision contract.

## Manipulation/VLA preflight contract

Manipulation Agent builds the real intended VLA payload and evaluates the existing preflight checks:

- current specimen and source/target identities;
- fresh Vision handoff or an explicitly typed synthetic validation observation;
- robot profile and policy reference;
- camera/VLA readiness;
- action clamp, relative-target bound, shoulder-lift backstop, and terminal pose;
- operator confirmation requirement for a future live run.

With `manipulation=preflight_only`, it stops before `lerobot.rollout.start` or `robot.pick_place` and emits:

```json
{
  "schema": "manipulation_preflight.v1",
  "status": "execution_ready_pending_approval",
  "would_execute_tool": "lerobot.rollout.start",
  "actuation_performed": false
}
```

This typed handoff satisfies the safe-validation controller path but must never be relabelled as physical specimen placement.

## Lab Equipment agentic preflight contract

Lab Equipment Agent resolves the saved profile-bound `run_utm_compression_cycle` flow and validates every block, skill version, locator/vision binding, route, timeout, export context, and run/specimen identity.

With `lab_equipment=preflight_only`, the policy is checked at agent entry before LLM, camera, explicit-skill, profile, or legacy execution branches. A saved, enabled, valid full flow is mandatory; otherwise the agent returns typed `preflight_not_ready` and cannot fall through to a device path. For a valid flow it walks the workflow structure and produces a planned-step trace through:

- prepare next specimen;
- start test;
- monitor contact/run;
- await auto return;
- save raw data;
- validate raw data;
- advance without save;
- restore robot clearance.

It stops before the first external PyAutoGUI execution. The report records `would_execute`, resolved program IDs, expected pre/postconditions, and the blocking boundary. It accepts the predecessor only when the Manipulation schema, run ID, and specimen ID exactly match the current cycle. Its terminal status is `execution_ready_pending_approval`, with `actuation_performed=false` and `ready_for_analysis=false`; it does not fabricate a measured UTM CSV.

Analysis is nevertheless allowed to continue in this explicit safe-validation policy using a CAE observation. The physical UTM path continues to require `equipment_handoff.status=ready_for_analysis` and a verified CSV.

## Reference UTM data and CAE calibration

Historical equipment artifacts are reference evidence, not current-cycle measurements. A reference file is eligible only when the existing UTM parser proves:

- a recognized TrapeziumX/canonical format and explicit unit mapping;
- finite force and displacement values;
- nonzero, changing force and changing displacement;
- monotonic or canonically orderable displacement;
- enough coverage to compute the intended calibration feature;
- stable file size and a SHA-256 fingerprint.

Files are deduplicated by content hash. Flat/zero-force simulator CSVs, short smoke-test CSVs, partial exports, and copies of the same source are excluded. The selection report records accepted and rejected paths with reasons. Unmatched specimen identity is a calibration limitation and must be labelled; it cannot be claimed as validation.

The CAE bridge receives an optional typed `reference_calibration` summary rather than an arbitrary objective constant. It may use robust dimensionless scale factors derived from eligible force–displacement or stress–strain curves to keep the deterministic quasi-static equivalent within the observed order of magnitude. It must retain the candidate-dependent effects of relative density, cell size, wall thickness, material, area, and height. The result records reference hashes, calibration method, sample count, limits, and solver mode.

The CAE curve ends at the experiment-planned 50% compressive strain and retains the existing frictionless top/bottom face constraints without modeled platens. It emits the same engineering stress–strain and energy-density semantics used by Analysis.

## Analysis observation contract

There is one optimization metric:

```text
energy_density_50pct_MJ_per_m3
```

Analysis selects its source explicitly:

- verified current-cycle UTM CSV → `fidelity=utm_high`, `observation_kind=measured`;
- safe-validation CAE endpoint → `fidelity=cae_mid`, `observation_kind=predicted`.

The CAE path is allowed only when the execution policy explicitly declares Lab Equipment `preflight_only`, the CAE result is successful, reaches 50% strain, contains a finite energy-density value, and carries calibration provenance. It is not a fallback after a malformed or failed physical UTM run.

Analysis must never turn printability, a composite score, or a partial curve into this observation. Blocked observations contain no numeric score.

## BO fail-closed contract

BO trains only on records whose metric name exactly matches the active objective and whose observation is explicitly ready. For this workflow that means `energy_density_50pct_MJ_per_m3` from `utm_high` or `cae_mid`.

Remove all training-score fallback behavior that substitutes:

- generic `objective_score` when the declared metric is missing;
- Specimen/Design `printability_score` or performance proxies;
- specific energy absorption or total force–displacement energy under a different metric name;
- failed or blocked Analysis records.

Non-objective records may remain as feasibility, duplicate, or failure context, but they carry no GP training score. If no compatible observation exists when one is required, BO returns a stable blocked result instead of silently optimizing another scale. Initial design generation before any observation remains a separate design-space bootstrap, not an objective fallback.

Every BO recommendation carries the objective metric, unit, observation fidelity, training observation IDs, and provenance references. The next Design cycle must preserve the execution policy and apply the declared shape parameters at their configured precision.

## Controller acceptance gates

For every safe-validation cycle the controller requires:

1. printer preflight ready and no physical printer call;
2. Vision `execution_ready_pending_approval`, no capture/runtime call, and no fabricated detection;
3. Manipulation/VLA `execution_ready_pending_approval` and no robot call;
4. Lab Equipment agentic flow `execution_ready_pending_approval` and no Windows/UTM execution;
5. CAE result successful, endpoint at 50%, and calibration provenance present;
6. Analysis BO observation ready with the exact energy-density metric and `cae_mid` fidelity;
7. BO recommendation ready with the same metric;
8. next Design receives the recommended `cell_size_mm` and `relative_density` while preserving the execution policy.

Any failure stops the cycle and surfaces its stable failure code. A controller test that merely reaches `complete` is insufficient.

Once an execution-policy mapping exists, omitted physical stages default to `preflight_only`; therefore enabling only the printer cannot implicitly enable the robot or UTM. A legacy specification with no execution-policy field retains its existing behavior.

## Verification

Implementation uses test-driven development and hardware-call tripwires.

- Unit tests prove each preflight boundary returns before its capture or actuation tool and that all four typed preflight records survive graph-state persistence.
- Printer tests build a real local `.gcode.3mf`, extract noncentral object bounds, patch position-aware ejection, validate archive/MD5/tail ordering, and prove no network/start call.
- Reference-data tests deduplicate hashes and reject flat, partial, or unit-ambiguous CSVs.
- CAE tests prove calibration provenance, exact 50% endpoint, frictionless boundary metadata, finite energy density, and candidate-dependent output.
- Analysis tests prove typed CAE observations are accepted only in explicit preflight mode and physical UTM failures never fall back to CAE.
- BO tests prove proxy-only histories block and mixed histories train only on exact-metric ready observations.
- A 20-cycle integration test installs tripwire implementations for every physical tool and verifies all eight controller acceptance gates across 19 BO-driven redesigns.

No acceptance test contacts a printer, robot, Windows bridge, UTM, or external network service.

## Verification record

Final hardware-free verification produced the following evidence:

| Scope | Result |
|---|---:|
| 20-cycle closed loop with physical/camera tripwires and 19 BO redesigns | 1 passed (706.40 s) |
| Bambu patcher and bridge | 110 passed |
| Prusa bridge and printer-tool boundary | 40 passed |
| Lab Equipment Agent | 72 passed |
| Analysis, exact-metric BO, UTM calibration, and CAE | 73 passed |
| Policy, lineage, Vision/VLA, Specimen, validation, and graph focus set | 13 passed |

The real Bambu Studio source artifact from run `run-20260902T171920Z-d3aaeb` was also re-patched through the hardened local validator. It resolved extrusion bounds X=123.279–153.210 mm, Y=113.063–142.939 mm, Zmax=30.2 mm; placed the tail after the final extrusion; and passed plate-path, embedded MD5, tail-order, and SHA-256 re-open validation with publishing and start disabled.

## Compatibility and non-goals

- Existing physical execution remains available only through its explicit per-device confirmation gates.
- Existing report envelopes remain additive; new preflight fields do not redefine physical completion.
- Historical CSVs calibrate the safe-validation CAE surrogate but do not count as new experiments.
- This work does not claim physical validation, matched-specimen model validation, or safe unattended auto-ejection on hardware.
- No equipment method values, robot targets, or printer credentials are hardcoded.
