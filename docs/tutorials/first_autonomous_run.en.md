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

[한국어](first_autonomous_run.ko.md) · [All tutorials](first_autonomous_run.md)

## Goal and prerequisites

By the end of this walkthrough, you will have requested one **virtual** experiment,
followed its candidate through the agents, and opened the saved evidence. The
exercise teaches the operating sequence without requiring a printer or robot.
Its synthetic results must remain labeled virtual, not physical measurements.

You need a configured AX4LAB installation, a reachable LLM backend and a browser.
If installation is incomplete, follow [Install](../../install/README.md) first.
Use a desktop viewport of 1920 × 1080 to match the figures. Screenshot numbers and
saved settings belong to the captured installation; do not copy them blindly.

## Step 1 — Open the application

Start the installed application from a Linux/WSL terminal:

```bash
atr up
```

On native Windows, activate the checkout's `.venv` and use `python -m app.serve`
instead, as shown in the installation guide.

Open `http://localhost:7860`. If the server is already running, use that instance;
do not restart an active experiment to follow this guide.

![Main dashboard: models above Run Control](../gui/assets/screenshots/2026-09-29/main-dashboard.png)

Locate **Run Control** beneath the model/backend controls in the figure. You
should see the same control groups in your browser. A loaded model means it is
available; it does not mean an experiment is running. If Main is unreachable,
read the launcher output and check the local server before doing any device work.

## Step 2 — Choose the virtual execution profile

The first decision is what the experiment may do, not which Start button to press.
Save the virtual boundary before opening the conversation:

1. In **Run Control**, click **Test Mode Settings**.
2. Select **Virtual Bridge**.
3. Inspect the per-agent physical boundaries. Keep the virtual/preflight configuration
   for the first exercise; do not change an agent to **Real device**.
4. Set **Total Cycles** to `1` for this exercise and click **Save profile**.
5. Click **Reload** and confirm the saved value/profile. This change affects future
   runs, not the cycle count of an already active or resumed run.

![Test Mode Settings: virtual profile and device boundaries](../gui/assets/screenshots/2026-09-29/test-mode-settings.png)

After **Reload**, the saved revision, **Virtual Bridge** and `1` cycle should still
be visible. Inspect the per-agent values as well as the profile name. The figure's
cycle count is a captured installation value, not this exercise's required value.

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

The separate Live window should initialize a conversation. Use its agent list to
navigate reports and its chat area to review the plan. Main's **test → Start**
uses a direct run-start route instead; do not switch to that sequence partway
through this chat-driven exercise.

The figure contains historical data. Opening Live is not evidence that a new run
has been admitted.

## Step 4 — Request and review the test plan

In Live chat, enter this supported example:

```text
테스트 모드, 가상 브릿지
```

This means “test mode, virtual bridge.” It selects a prepared scenario whose
planning replies still pass through the Orchestrator conversation. Wait for the
**Experiment Contract** and **Experimental Setup**, then read them before treating
the plan as ready to execute.

Check the objective and units, specimen dimensions/material, design-variable names
and bounds, execution profile, and number of cycles. For the gyroid workflow,
the design variables are **cell size** and **wall thickness**, not an old density
search space. State corrections in chat if the proposed plan differs from your intent.

![Orchestrator: experiment contract and decisions](../gui/assets/screenshots/2026-09-29/live-orchestrator.png)

Look for the reviewed plan in the Orchestrator report and new run/cycle evidence
in the reports or **Timeline** as work begins. A greeting, a historical contract
or an opened window is not proof that this request started a new run. Record the
new run ID when it is available so that later artifacts can be matched to it.

Agreeing to a plan and agreeing to execute it are separate decisions. The scenario
can provide normal review replies, but it cannot supply missing connection facts
or witness a physical action. If this virtual exercise asks for physical confirmation,
stop at that request and recheck the saved profile; do not invent a confirmation.

## Step 5 — Check design and specimen preparation

Select **DSN → Report** to see what will be made. The figure locates the candidate
views; your own run may contain fewer candidates or different values.

![Design report: generated specimens, design space and comparison](../gui/assets/screenshots/2026-09-29/live-design.png)

1. Match the selected candidate to this run/cycle.
2. Inspect **Generated Specimens**, **Design Space**, **Candidate Comparison** and
   **Constraint Check**.
3. Open a generated STL from **Artifacts** and check that it belongs to this candidate.
4. Select **SPC** to inspect slicing/preparation evidence.

You should be able to connect one candidate ID to its constraint result and STL.
A thumbnail alone does not establish that constraints passed. Mass and print time
may remain unknown until slicing; do not read an empty field as zero or replace it
with a value from the screenshot. Use the recorded slicer/analysis source when it
becomes available.

## Step 6 — Follow the agents without taking over their devices

![SPC report: preparation and printer evidence](../gui/assets/screenshots/2026-09-29/live-specimen.png)

Follow **SPC** (specimen preparation), **VIS** (vision), **MAN** (manipulation) and
**EQP** (equipment) in the left agent list. Read each stage's report as it progresses.
In this exercise, virtual results and preflight checks—checks before device use—
are expected, not evidence of a real print, robot motion or compression test.

The SPC figure helps locate preparation evidence. If a card is pending, inspect
its **Timeline** and **Artifacts** for the current run. Do not launch a separate
print or robot rollout from a workspace to make the card turn green: a run owns
its device sequence.

**Expected:** stage-specific evidence for the current run, then a handoff to ANL.
If a stage stops, open its **Timeline** and **Artifacts** before retrying.
Use the checklist in Step 9.

## Step 7 — Read analysis and BO

Select **ANL → Report** and match the selected specimen to the candidate you saved.
Read the force–displacement (**FD**) and stress–strain (**SS**) curves, including
their axes and units. Check the source data, mass source and resulting metric.
Then open **BO → Report**, where Bayesian optimization uses accepted observations
to propose later candidates.

![Analysis report and measured-response evidence](../gui/assets/screenshots/2026-09-29/live-analysis.png)

![BO report with posterior and candidate evidence](../gui/assets/screenshots/2026-09-29/live-bo.png)

The basic success check is that the analysis belongs to this candidate and retains
its virtual source. A one-cycle exercise need not produce a new BO recommendation.
Specific energy absorption (**SEA**) derived from virtual data is not measured SEA.

If you want to inspect optimization more deeply, first check the observation count.
The Gaussian-process (**GP**) model needs sufficient observations; an initial
Latin-hypercube sampling (**LHS**) view without a posterior is not necessarily a
plotting failure. When available, compare mean, uncertainty and acquisition views
in 2D/3D with the candidate's cell-size and wall-thickness coordinates. An old 1D
display does not represent the full two-variable space. See
[analysis interpretation](../agents/analysis_agent.md) and
[BO evidence](../agents/bo_agent.md).

These figures show a historical multi-cycle run, not the result you must reproduce
after a single cycle.

## Step 8 — Find the files and review the session

1. Select the relevant agent, then **Artifacts**.
2. Use **All files** or the image filter as appropriate; an empty filter does not
   establish that the run lost its files.
3. Open the STL, curve image/data and BO files that actually exist.
4. Record the run ID, cycle and candidate ID alongside the file paths.

![Artifacts view: retained files and figure previews](../gui/assets/screenshots/2026-09-29/live-artifacts.png)

Run records live under `runs/<run-id>/`; artifacts can be stored separately under
`artifacts/`. Follow recorded references rather than assuming every file is inside
one run folder. For read-only history, return to Main, select **replay**, choose an
**Experiment session**, and click **Start**.

![Main: Replay mode and experiment-session selector](assets/screenshots/2026-09-29/main-replay.png)

The new window should show **REPLAY** and saved points, with no device execution.
This is artifact/session review, not robot motion replay. Only recorded points are
available; older sessions may not cover every cycle. See [Replay](../gui/run_replay.md)
for point navigation and [artifact preservation](../gui/artifact_preservation.md)
for retaining the referenced files.

## Step 9 — Finish, or diagnose the first failure

Before calling the exercise complete, check the final run state and open at least
the design and analysis files produced by the stages that ran. Match their run,
cycle and candidate identities. A clean-looking screen without a terminal result
does not establish completion. If the run is blocked, keep the partial artifacts
and exact reason; they are the starting point for recovery, not failed files to delete.

| Symptom | First check | Do not do this |
|---|---|---|
| Live window did not open | Browser pop-up permission; Main mode must be live | Repeatedly start another run |
| LLM response stalls | Selected route/model, backend error and quota/availability | Change the experiment objective to bypass an API error |
| Real-device confirmation appears | Saved execution profile and per-agent boundaries | Confirm an action that did not occur |
| Card is pending or empty | Current run/cycle, Timeline, artifact source/filter | Reuse an old successful result as current evidence |
| Paused/error run | Read the unresolved reason; correct it, then use existing Resume | Start a new run to “resume” the old one |
| Recovery requests physical action | Operator supervision and actual device state | Assume virtual testing authorizes hardware |

For an idle system you intend to shut down, run `atr down`.
For native Windows, stop the server in its terminal with `Ctrl+C` after work has
finished. Do not use `atr restart` as a substitute for
[resuming the existing run](../gui/run_resume.md).

## Next exercise

Restore the cycle count you intend to use for future runs. Continue with the
[operator walkthroughs](user_manual.en.md) and
[printer setup](device_workspace_3dp_usage.en.md) before selecting physical devices.

## Verification scope

The instructions were checked against the current templates, browser handlers and
runtime references at `fcfba9f`. Screenshots were captured read-only on 29 September
2026; no new experiment was run for documentation. This is a navigation/procedure
check, not certification of the pictured hardware state.
