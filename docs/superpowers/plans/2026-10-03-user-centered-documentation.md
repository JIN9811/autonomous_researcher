<!-- atr-doc
doc_type: plan
subtype: implementation
status: active
authority: execution
audience: [maintainer]
scope: [user_documentation]
summary: Rewrite public reading paths and operating prose without changing runtime behavior.
execution_status: completed
governing_design: docs/superpowers/specs/2026-10-03-user-centered-documentation-design.md
related_docs: [docs/README.md]
supersedes: []
-->

# User-centered documentation implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the
> disjoint editorial tasks. The user requested continuous execution through
> commit and push; no intermediate approval pause is required.

**Goal:** Make the existing documentation usable from first setup to experiment
results and recovery in coherent English and natural Korean.

**Architecture:** Preserve public paths and runtime contracts. Separate learning,
operating, research and technical lookup routes. Parallel editors own disjoint
document families; the coordinator integrates navigation, verifies source hashes
and performs final publication checks.

**Tech Stack:** Markdown, existing PNG/SVG assets, YAML/JSON editorial metadata,
the standalone documentation validator and filesystem-only checks.

**Spec:** [Approved editorial design](../specs/2026-10-03-user-centered-documentation-design.md).

## Global Constraints

- Work on main as explicitly requested; do not merge the layout branch.
- No application, server, device, model or runtime configuration changes or starts.
- Edit only assigned files; preserve existing factual limits, UI labels, commands,
  units, data identity, approval conditions and numerical definitions.
- Use apply_patch for authored edits. Do not delete historical evidence or assets.
- Wiki bodies and runtime prompt/guideline inputs remain byte-identical.
- Source-hash reconciliation is coordinator-owned, per reviewed source only;
  preserve freshness and do not reapprove unrelated stale pages.
- No editor commits while parallel editors are working. The coordinator owns
  staging, final review, commit and push.
- Read the assigned original before rewriting. Do not replace detailed useful
  guidance with generic prose or a link directory.

## Review Focus

1. TEST with physical printer work versus a hardware-free test: guide pairs must
   identify the selected execution path and its effects before action.
2. Recovery after a process accepted work: preserve unknown-effect checks and do
   not suggest blindly repeating printing or robot/UTM movement.
3. Saved evidence versus current readiness: Replay and dated screenshots must
   not be presented as fresh clearance or new validation.
4. Scientific interpretation: retain mass-normalized SEA, displacement/strain
   conventions, campaign scope and operator interventions.
5. Editorially changed Wiki sources: compare original article bodies, source
   sets and prior/final freshness; hash updates are not behavior changes.

## Task 1: Onboarding and tutorial prose

**Files:** install/README.md; all nine existing Markdown files in
docs/tutorials/ (including the language selector).

**Consumes:** Existing controls, screenshots and current operational evidence.
**Produces:** A complete first-run journey and task-focused 3DP/Vision guides in
English/Korean; user manuals with direct recovery/results/extension links.

- [x] Read originals and relevant audit findings; preserve exact mode semantics.
- [x] Rewrite in connected prose and concrete steps, with expected outcomes and
  useful screenshot explanations. Remove repetition and implementation diaries.
- [x] Keep paired language facts aligned and existing inbound anchors reachable.
- [x] Check links, images, metadata and diff; report factual uncertainties.
- [x] Independent review of scope, usability and fact preservation.

## Task 2: GUI, recovery and hardware operation

**Files:** docs/gui/*.md except reference/live_gui_reference_alignment.md;
docs/hardware/windows_pyautogui_bridge_windows_setup.md;
docs/hardware/windows_pyautogui_equipment_agent_guideline.md;
docs/hardware/utm_ros_vision_runtime_bridge.md;
docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md;
docs/hardware/isaac_sim_robotis_omx_mirror_mode.md;
docs/device_bridges/x2d_pre_eject_cleanup.md.

**Consumes:** Canonical unchanged agent/bridge contracts and saved captures.
**Produces:** Task/symptom-oriented operating prose with normal-result and recovery
checks, plus concise technical background where actually needed.

- [x] Read and rewrite guides, keeping physical effects and readiness conditions.
- [x] Make Live/Replay/Workspace differences clear; retain screenshots and captions.
- [x] Replace developer-history openings with purpose, use and outcome; move
  implementation details after the user procedure without erasing unique facts.
- [x] Check local links and inbound headings; identify any runtime-consumed file
  before modifying it. Do not modify active runtime prompt inputs.
- [x] Independent review of recovery/effect boundaries and reader comprehension.

## Task 3: Knowledge, research and extension reading

**Files:** docs/knowledge/{manual_rag_knowledge.ko.md,
markdown_memory_operations.ko.md,publication.md,runtime_reference_safety.md,
wiki_memory.md}; create manual_rag_knowledge.en.md and
markdown_memory_operations.en.md as corresponding English guides;
docs/paper/README.md, 01_problem_and_contributions.md through
09_claim_evidence_traceability.md, appendix_a_interfaces.md,
appendix_b_hardware_and_deployment.md; docs/modularity.md;
docs/runtime/runtime_ide.md; packages/README.md.

**Consumes:** Existing scientific/evidence records and exact runtime contracts.
**Produces:** Natural Knowledge operating guides, logically connected research
explanation and understandable module/IDE extension instructions.

- [x] Rewrite confusing language and narrative while preserving all substantive
  research claims, equations, units, scope and qualifications.
- [x] Keep historical evidence and all docs/knowledge/wiki article bodies unchanged.
- [x] Link user tasks first, schemas/implementation later; preserve mandated IDE
  headings/figures or flag a precise validator conflict for the coordinator.
- [x] Check language pairs, links and metadata; report source-hash dependencies.
- [x] Independent review of scientific and module-contract fidelity.

## Task 4: Entry points, editorial policy and integration

**Files:** README.md; README.ko.md; docs/README.md; new docs/README.ko.md;
docs/agents/README.md; docs/device_bridges/README.md;
docs/device_bridges/windows_pyautogui_bridge.md (English translation of mixed prose);
docs/runtime/{api_keys.md,test_mode.md,logging.md,loop_artifact_archiving.md};
docs/standards/documentation_standard.md; docs/templates/document_types.md;
docs/document_manifest.yaml; documentation-only checks if required.

**Consumes:** Tasks 1–3 guides and unchanged specialist references.
**Produces:** Short useful entry points, a task-oriented bilingual docs index,
clear detailed-reference navigation, and consistent authoring guidance.

- [x] Record baseline source/body hashes and standalone validator result.
- [x] Write navigation and common operating explanations; preserve required root
  reference links but move inventories behind concise reference sections.
- [x] Make reader-first guidance explicit for guides/indexes without silently
  weakening specialist reference contracts or metadata validation.
- [x] Register new guides and design/plan; reconcile reviewed Wiki source hashes
  only after checking each edited source's meaning and unchanged Wiki body.
- [x] Record file-level disposition for the complete audited corpus: rewritten,
  retained specialist reference, protected runtime/evidence, or history/vendor.
- [x] Check all explicit local links/anchors, language-pair controls and images.

## Task 5: Verify, review and publish

**Files:** Whole editorial diff; documentation-only audit record under
docs/maintenance/; the plan's completion checkboxes.

- [x] Run `.venv/bin/python scripts/validate_documentation.py` and the isolated
  documentation-validator unit tests; no app imports or equipment calls.
- [x] Run static local-link/anchor, protected-file and Wiki freshness/body checks.
- [x] Review the complete change independently, fix important findings and
  recheck affected documents. Do not re-run unrelated hardware tests.
- [x] Verify `git diff --check`, allowed-file scope and no unrelated edits.
- [x] Commit the completed documentation and push main without force.
- [x] Confirm the remote SHA; report what changed and the exact validation scope.
