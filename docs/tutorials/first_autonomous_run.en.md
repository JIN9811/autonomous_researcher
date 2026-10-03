<!-- atr-doc
doc_type: guide
subtype: tutorial
status: active
authority: procedural
audience: [user, operator, researcher]
scope: [gui_tutorial, operator_workflow]
summary: Screenshot-led first virtual run, evidence inspection and recovery checkpoints.
source_of_truth:
  - web/templates/index.html
  - web/static/app.js
  - web/templates/planning.html
  - web/static/planning.js
  - utils/test_mode_execution_profiles.py
last_verified: 2026-09-29
verified_against: fcfba9f
related_docs:
  - docs/gui/visual_structure.md
  - docs/runtime/test_mode.md
supersedes: []
-->

# First Autonomous Run — Step by Step

[Korean](first_autonomous_run.ko.md) · [All tutorials](first_autonomous_run.md)

## Goal and prerequisites

Complete one **virtual** experiment through Live, then find its design, analysis
and optimization evidence. No printer or robot is required; a virtual result is
not a physical experiment result.

You need a configured AX4LAB installation, a reachable LLM backend and a browser.
If installation is incomplete, follow [Requirements](../../REQUIREMENTS.md) first.
Use a desktop viewport of 1920 × 1080 to match the figures. Screenshot numbers and
saved settings belong to the captured installation; do not copy them blindly.

## Step 1 — Open the application

From a terminal on the installed workstation:

```bash
atr up
```

Open `http://localhost:7860`. If the server is already running, use that instance;
do not restart an active experiment to follow this guide.

![Main dashboard: models above Run Control](../gui/assets/screenshots/2026-09-29/main-dashboard.png)

**Expected:** the Main dashboard shows model/backend controls and **Run Control**.
A loaded model indicates availability, not an active experiment.
If the page is unreachable, check the launcher output and local server before
trying any device action.

## Step 2 — Choose the virtual execution profile

1. In **Run Control**, click **Test Mode Settings**.
2. Select **Virtual Bridge**.
3. Inspect the per-agent physical boundaries. Keep the virtual/preflight configuration
   for the first exercise; do not change an agent to **Real device**.
4. Set **Total Cycles** to `1` for this exercise and click **Save profile**.
5. Click **Reload** and confirm the saved value/profile. This change affects future
   runs, not the cycle count of an already active or resumed run.

![Test Mode Settings: virtual profile and device boundaries](../gui/assets/screenshots/2026-09-29/test-mode-settings.png)

**Expected:** a saved revision and the intended virtual boundaries.
The screenshot's cycle count is illustrative, not the value required by this exercise.

Do not choose another profile just because it contains the word “test”:

| Profile | Printer path | Other device implications |
|---|---|---|
| Virtual Bridge | Virtual/preflight path | No physical calls under the virtual profile |
| Installed Printer | Slices, then sends an ejection-only artifact; print body/cooling skipped | Vision, manipulation and UTM can be real |
| Physical Print | Full sliced print, cooling and configured ejection | Vision, manipulation and UTM can be real |

The saved per-agent overrides also matter. See [Test Mode](../runtime/test_mode.md).

## Step 3 — Open the Live conversation

1. Return to Main.
2. Select the configured **Inference** backend. Verify its model or API route is ready.
3. Set **Mode** to **live**, then click **Start**.
4. Allow pop-ups for the local application if no new window appears.

![Live GUI: agent list, report and conversation](../gui/assets/screenshots/2026-09-29/live-overview.png)

**Expected:** Live GUI opens separately and initializes its conversation.
This is the chat-driven entry used in this tutorial. Main's **test → Start** instead
calls the direct run-start route; it is not the same button sequence.

The figure shows historical data. Opening Live does not confirm admission of a new run.

## Step 4 — Request and review the test plan

In Live chat, enter this supported Korean command alias for test mode with a
virtual bridge:

```text
테스트 모드, 가상 브릿지
```

This means “test mode, virtual bridge.” The scenario-input driver asks and answers
planning questions through the normal Orchestrator conversation. Read the resulting
**Experiment Contract** and **Experimental Setup**, not only the greeting.

Check the objective and units, specimen dimensions/material, design-variable names
and bounds, execution profile, and number of cycles. For the gyroid workflow,
the design variables are **cell size** and **wall thickness**, not an old density
search space. State corrections in chat if the proposed plan differs from your intent.

![Orchestrator: experiment contract and decisions](../gui/assets/screenshots/2026-09-29/live-orchestrator.png)

**Expected:** a reviewed contract and a run-specific admission/handoff.
Planning consent is distinct from execution consent. The test scenario can supply
normal review replies, but missing connection facts and physical confirmations
remain the operator's responsibility.

- Do not confirm a physical action that did not occur.
- If this virtual exercise requests physical confirmation, check the selected profile.

## Step 5 — Check design and specimen preparation

Click **DSN** on the left, then **Report**.

![Design report: generated specimens, design space and comparison](../gui/assets/screenshots/2026-09-29/live-design.png)

1. Match the selected candidate to this run/cycle.
2. Inspect **Generated Specimens**, **Design Space**, **Candidate Comparison** and
   **Constraint Check**.
3. Open a generated STL from **Artifacts** and check that it belongs to this candidate.
4. Select **SPC** to inspect slicing/preparation evidence.

**Expected:** an identifiable candidate, current constraint evidence and the
corresponding artifact. A thumbnail alone is not a pass verdict. Missing mass/time
before slicing is not a measurement; use the actual recorded slicer/analysis source
when it becomes available.

## Step 6 — Follow the agents without taking over their devices

![SPC report: preparation and printer evidence](../gui/assets/screenshots/2026-09-29/live-specimen.png)

Use the left agent list to inspect VIS, MAN and EQP reports as the workflow
progresses. Their virtual/preflight outcomes must remain distinguishable from
physical completion. Do not open a workspace and manually run a second print or
rollout to make a pending card turn green.

**Expected:** stage-specific evidence for the current run, then a handoff to ANL.
If a stage stops, open its **Timeline** and **Artifacts** before retrying.
Use the checklist in Step 9.

## Step 7 — Read analysis and BO

Select **ANL → Report**. Inspect the SS/FD views and their units, selected specimen,
mass source and metric result. Then select **BO → Report**.

![Analysis report and measured-response evidence](../gui/assets/screenshots/2026-09-29/live-analysis.png)

![BO report with posterior and candidate evidence](../gui/assets/screenshots/2026-09-29/live-bo.png)

**Expected:** analysis tied to the current candidate. A GP posterior is meaningful
only when sufficient observations exist; an initial LHS-only state is not a plotting
failure. In a one-cycle exercise a new BO recommendation is not guaranteed.
When available, inspect the 2D/3D mean, uncertainty and acquisition views and the
candidate coordinates. Never treat the synthetic/virtual result as measured SEA.

These figures show a historical multi-cycle run, not an expected single-cycle result.

## Step 8 — Find the files and review the session

1. Select the relevant agent, then **Artifacts**.
2. Use **All files** or the image filter as appropriate; an empty filtered view does not
   establish that the run lost its files.
3. Open the STL, curve image/data and BO files that actually exist.
4. Record the run ID, cycle and candidate ID alongside the file paths.

![Artifacts view: retained files and figure previews](../gui/assets/screenshots/2026-09-29/live-artifacts.png)

Run records live under `runs/<run-id>/`; artifacts can be stored separately under
`artifacts/`. Follow recorded references rather than assuming every file is inside
one run folder. For read-only history, return to Main, select **replay**, choose an
**Experiment session**, and click **Start**.

![Main: Replay mode and experiment-session selector](assets/screenshots/2026-09-29/main-replay.png)

**Expected:** a separate Replay window with recorded points, not device controls.
Only saved points can be selected; legacy sessions may not cover every cycle.
See [Replay](../gui/run_replay.md).

## Step 9 — Finish, or diagnose the first failure

A successful exercise has a terminal run result and inspectable artifacts for the
stages it actually executed. “No error on screen” alone is not completion.

| Symptom | First check | Do not do this |
|---|---|---|
| Live window did not open | Browser pop-up permission; Main mode must be live | Repeatedly start another run |
| LLM response stalls | Selected route/model, backend error and quota/availability | Change the experiment objective to bypass an API error |
| Real-device confirmation appears | Saved execution profile and per-agent boundaries | Confirm an action that did not occur |
| Card is pending or empty | Current run/cycle, Timeline, artifact source/filter | Reuse an old successful result as current evidence |
| Paused/error run | Read the unresolved reason; correct it, then use existing Resume | Start a new run to “resume” the old one |
| Recovery requests physical action | Operator supervision and actual device state | Assume virtual testing authorizes hardware |

For an idle system you intend to shut down, run `atr down`.
Do not use `atr restart` as a substitute for run recovery.

## Next exercise

Restore the cycle count you intend to use for future runs. Continue with the
[operator walkthroughs](user_manual.en.md) and
[printer setup](device_workspace_3dp_usage.en.md) before selecting physical devices.

## Verification scope

The instructions were checked against the current templates, browser handlers and
runtime references at `fcfba9f`. Screenshots were captured read-only on 29 September
2026; no new experiment was run for documentation. This is a navigation/procedure
check, not certification of the pictured hardware state.
