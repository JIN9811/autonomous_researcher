---
doc_type: evidence
subtype: test_report
status: active
authority: evidentiary
audience: [developer, researcher, reviewer]
scope: [vision_agent, multimodal, prompt, api, local_model]
summary: Generic Vision prompt and evidence-context refinement improved observed choices on archived cases, with residual local image-pair errors.
evidence_date: 2026-09-08
method: Compare the original and revised Vision decision prompts through registered API and vLLM routes on fixed archived cases, then evaluate a frozen revision on unused captures without hardware tools.
related_docs:
  - docs/agents/vision_agent.md
  - docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
  - docs/superpowers/plans/2026-09-08-vision-multimodal-decision.md
supersedes: []
---

# Vision / Generic Prompt Verification

## Outcome

The revised prompt and evidence context improved observed decision consistency.
It did not eliminate errors or establish cross-experiment accuracy.

| Check | API `gpt-5.5` | Registered vLLM `gemma4:31b` |
|---|---:|---:|
| Original prompt, development expectations matched | 10/13 | 9/13 |
| Revised prompt/context, same expectations matched | 12/13 | 12/13 |
| Original prompt, valid decision arguments | 13/13 | 11/13 |
| Revised prompt/context, valid decision arguments | 13/13 | 13/13 |
| Frozen revision, held-out expectations matched | 6/6 | 5/6 |
| Frozen revision, held-out valid decision arguments | 6/6 | 6/6 |

These are declared expected-choice matches, not benchmark accuracy or closed-loop
completion rates. All 64 real calls completed without timeout. No camera,
robot, printer or test equipment was actuated; source image hashes were unchanged.

## Change and Control

The production change is limited to `agents/vision_decision.py`:

- Review **pair → location → validity → claim**, rather than treating the annotated
  image as automatically belonging to the raw frame.
- Compare camera/background/object state across both images, then compare the raw
  object, drawn box and numeric detector coordinates. A correct overlay does not
  repair inconsistent numeric facts.
- Read target properties from the supplied experiment context. No fixed color,
  material, dimensions, apparatus, compression condition or canonical shape is
  embedded in the generic prompt.
- Supply actual image dimensions, pixel origin and `xyxy` convention; forward
  existing registration, failure and unknown reasons alongside detector facts.
- Provide valid JSON examples for both tools, including mandatory `contract_id`
  for rejection. Return a short observable rationale, not internal reasoning.

The artifact probe no longer invents `red PLA` when the archive has no material.
Both the new baseline and revised trials used that corrected loader. Previously
reported 8/13 API and 9/13 local results used the older loader and are historical,
not the controlled baseline above. Input-context enrichment accompanied the prompt
change, so this comparison does not isolate wording as the only causal factor.

One candidate prompt was tested and frozen before held-out inference. No changes
were made in response to held-out results. Existing parser, tools, routing,
provider options, timeouts, thresholds, freshness and final safety gates were not
relaxed. The local route retained its configured E4B primary/31B fallback, with
actual responses from `gemma4:31b`; this is not an E4B-primary validation.

## Cases and Remaining Errors

The development set contains eight archived natural inputs and five in-memory
detector/pair perturbations. The held-out set contains six cases derived from
three additional archived captures: upright, compressed and empty scenes, plus
occupied-clearance, wrong-box and mismatched-pair cases. Those captures were not
used to adjust the prompt. They share the existing apparatus/domain, so this is
not a cross-domain or independently human-labelled generalization benchmark.

| Revised decision | API | Local |
|---|---|---|
| Natural presence and compressed references | Accepted | Accepted |
| Unknown detector evidence | Returned for review | Returned for review |
| False presence/absence detector claims | Returned for review | Returned for review |
| Incorrect numeric box, development and held-out | Returned for review | Returned for review |
| Different-camera pair | Returned for review | Returned for review |
| Same-background changed-object-state pair, development and held-out | Returned for review | **Incorrectly accepted** |
| Development Clear B, detector-labelled clear | Returned for possible residual | Accepted |
| Held-out natural empty scene | Accepted | Accepted |

API's Clear B explanation cited a red/orange horizontal residual-like mark in the
ROI. Its original-prompt repeat accepted this image, while an earlier run returned
it. There is no independent ground-truth label resolving the discrepancy; the
record shows decision variability and possible over-rejection, not a proven
detector or model error. Other expected-positive inputs remained accepted in these
single passes. No statistical reliability or false-rejection rate is established.

The local failure was specific: it supported presence in the raw frame but missed
that the paired annotation depicted a different object state. Prompt refinement
does not replace code-owned provenance/coordinate validation or make two-image
consistency reliable enough to serve as a sole gate.

## Timing and Workflow Boundary

| Phase | API mean / range | Local mean / range |
|---|---|---|
| Original prompt, 13 cases | 6.924 / 3.454–12.915 s | 7.640 / 5.635–9.637 s |
| Revised prompt/context, 13 cases | 8.160 / 4.436–13.477 s | 6.248 / 5.174–7.626 s |
| Frozen revision, 6 held-out cases | Range 5.510–9.279 s | Range 5.464–6.796 s |

Each case ran once per phase/backend. These observations do not establish a
speed improvement or a latency guarantee. LIVE's five-second evidence expiry
remains unchanged; all historical ActiveCam inputs stayed expired after model
acceptance. Placement/clearance helper acceptance alone does not complete the
workflow. Existing regression tests retain detector unknown/occupied blocking,
verified-stop ordering, session isolation and deadline enforcement.

The combined 14-file regression run reported **271 passed**, 10 existing warnings,
14.18 seconds. Added input-contract tests failed before implementation and passed
after it: real raster dimensions/validity reasons, executable accept/return JSON
examples, and no invented material. Read-only code review found no important
issues in these deltas. This is not hardware or full closed-loop validation.

## Local Evidence

Exact responses, model routes, durations and image digests are in the following
temporary reports. They are not permanent or GitHub-hosted; this document retains
the result summary and file hashes.

| Phase | Local `results.json` directory | SHA-256 |
|---|---|---|
| Original API | `/tmp/atr-vision-multimodal-8cjbjeb7` | `32383b03314836de08fded2ea548ccbcbeb6cf3a2905a69db11a35ffe18ce657` |
| Original local | `/tmp/atr-vision-multimodal-kg1pfssd` | `a31be0de28587090b9db52dea48c4bc05073b7bd637854603e80d00bf5abb094` |
| Revised API | `/tmp/atr-vision-multimodal-oz33okf9` | `07533d99dd9f64ded00e270bf94cfbb513a1cc9631dc3c22c5d9fc69564340f4` |
| Revised local | `/tmp/atr-vision-multimodal-em3veuv_` | `704c757dfeadc59252196498ece8a39760e8351bc5d98673b45b491028bd6b95` |
| Held-out API | `/tmp/atr-vision-multimodal-t1d62yto` | `4bb63ae5fe419cb2c901db3fce0a42a4a5471ecb1a429089259f5332c1d2c065` |
| Held-out local | `/tmp/atr-vision-multimodal-b0ivixc2` | `5f60e4952b1f9f277e3eb17e89df457a6b5084b7d84b285f09af034870ab8b8b` |

Development manifest: `/tmp/atr-vision-crosscheck-pDiiDg/input_manifest.json`.
Held-out manifest: `/tmp/atr-vision-prompt-eval-48a4aQ/holdout.json`.
The existing [verification script](../../../scripts/verify_vision_multimodal.py)
accepts `--execute --backend openai` or `--backend vllm` together with
`--artifact-manifest PATH`. It requires the referenced local archives and existing
registered services. No commit, tag, push, service restart or model configuration
change was performed for this refinement.
