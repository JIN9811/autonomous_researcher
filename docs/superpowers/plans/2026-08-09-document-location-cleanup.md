# Document Location Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relocate the approved documentation batch, archive one replaced image package, repair references, and codify strict future archive rules.

**Architecture:** Keep current material inside its owning domain and use `research`, `history`, and `evidence` subdirectories only where the subtype is clear. Preserve the old relative context under `docs/oldversion/`, expose one archive index, and verify literal paths plus Markdown links after every move.

**Tech Stack:** Markdown, YAML document manifest, JSON asset manifest, Python documentation validator, pytest, git.

## Global Constraints

- Apply only the relocation map in the approved Design.
- Do not archive a package payload, current Guide, current Reference, implementation plan/specification, or evidence record.
- Do not change application, agent, bridge, API, graph, or test behavior.
- Preserve the user's pre-existing `.env.example` modification and never stage it.
- Update inbound literal paths and relative Markdown links in the same change as each move.
- Do not claim that archived PNG schematics describe the current implementation.

---

### Task 1: Create the Archive Contract and Navigation

**Files:**
- Create: `docs/oldversion/README.md`
- Modify: `docs/standards/documentation_standard.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: lifecycle and migration-debt rules in the current Documentation Standard.
- Produces: one canonical archive admission rule and one discoverable historical entry point.

- [x] **Step 1: Add the archive index**

Record the archived image package with its original path, final path, archive
date `2026-08-09`, reason, and replacement
`docs/agents/assets/figures/` plus `docs/agents/README.md`.

- [x] **Step 2: Add archive governance to the Standard**

Add the five admission checks from the approved Design, original-path
preservation rule, archive index requirement, normal-reading-path exclusion,
and restoration procedure.

- [x] **Step 3: Link the archive from the documentation index**

Add `oldversion/README.md` as an explicitly historical entry point and state
that legacy or unmanifested does not mean unused.

- [x] **Step 4: Run documentation validation**

Run:

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/pytest -q tests/unit/test_documentation_validation.py
```

Expected: both commands pass.

### Task 2: Relocate Active Research, History, and Evidence

**Files:**
- Move: the seven active files listed in the approved Design relocation map.
- Modify: `docs/README.md`
- Modify: `docs/agents/equipment_agent.md`
- Modify: `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`
- Modify: `docs/device_bridges/prusa_mk4s_bridge.md`
- Modify: `개선안/02_specimen_making_agent_autonomous_fabrication_loop_research.md`
- Modify: `개선안/13_bambulab_x2d_spc_device_bridge_research.md`

**Interfaces:**
- Consumes: current domain ownership and existing UTM completion-audit links.
- Produces: stable domain-local research, history, and evidence locations.

- [x] **Step 1: Move the research and GUI history files**

Use `mkdir -p` for the three approved destination directories and `git mv` for
the four research/history documents. Do not edit their substantive contents.

- [x] **Step 2: Move the runtime and hardware evidence files**

Use `git mv` for the three audit/validation documents. Keep evidence text and
dates unchanged.

- [x] **Step 3: Repair known inbound references**

Replace the old UTM completion-audit path in `docs/README.md`,
`docs/agents/equipment_agent.md`, and
`docs/hardware/windows_pyautogui_equipment_agent_guideline.md` with the new
`docs/hardware/evidence/` path, using the correct relative form in Markdown.
Replace the old Prusa live-validation path in the Prusa bridge Reference and
both research records with the new `docs/hardware/evidence/` path.

- [x] **Step 4: Check all seven old paths**

Run fixed-string searches for each old path and basename. Remaining full old
paths are allowed only in the approved Design and implementation Plan.

### Task 3: Archive the Replaced Image Package

**Files:**
- Move: `docs/github_docs_image/autonomous_researcher_gpt_image_schematics/`
- Create destination: `docs/oldversion/github_docs_image/autonomous_researcher_gpt_image_schematics/`

**Interfaces:**
- Consumes: the package README, JSON manifest, and eleven PNG files.
- Produces: an intact historical package excluded from active documentation paths.

- [x] **Step 1: Move the package as one unit**

Preserve the package's internal layout so every `manifest.json` filename still
resolves relative to the manifest.

- [x] **Step 2: Verify archive package integrity**

Parse `manifest.json`, resolve each `files[].filename` from the manifest's
directory, and fail if any path is absent. Confirm there are exactly eleven PNG
entries and eleven PNG files.

- [x] **Step 3: Confirm no active inbound references remain**

Search outside `docs/oldversion/`, the approved Design, and this Plan for
`github_docs_image` and the package name. Expected: no matches.

### Task 4: Validate and Commit the Relocation Batch

**Files:**
- Verify: all files changed by Tasks 1-3.

**Interfaces:**
- Consumes: the final relocation tree and repaired references.
- Produces: a reviewable documentation-only commit ready to push.

- [x] **Step 1: Run repository documentation validation**

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/pytest -q tests/unit/test_documentation_validation.py
```

Expected: both commands pass.

- [x] **Step 2: Check every tracked Markdown local link**

Run a repository-relative Markdown link checker that ignores external URLs,
anchors, and image data URLs. Expected: zero missing local targets.

- [x] **Step 3: Review whitespace and scope**

```bash
git diff --check
git status --short
git diff --stat
```

Expected: no whitespace errors; `.env.example` is the only unrelated change and
is not staged.

- [x] **Step 4: Commit only documentation cleanup files**

```bash
git add docs
git commit -m "docs: organize legacy documentation locations"
```

- [x] **Step 5: Verify and push**

Confirm the commit contains no `.env.example` change, then push the current
branch to its configured upstream.
