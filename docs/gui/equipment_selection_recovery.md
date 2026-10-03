# Restart recovery at an unexecuted Equipment selection

This operator-requested recovery preserves the current run and completed fabrication/robot transfer. It is not an automatic retry policy or a way to repeat device commands.

## Operator: establish that selection failed before execution

Open Live GUI → EQP → Report, then Backend and Timeline for the same run/cycle.
Look for `EQUIPMENT_WORKFLOW_SELECTION_REJECTED` and the Guardian recovery wait.
Record the specimen ID and Equipment execution identity. Ask support to check the
durable record against the eligibility list below; an empty progress card alone
does not prove that no device command ran.

Leave the run paused while this is checked. Do not repeat fabrication, robot
transfer, a Windows Skill, or a manual UTM command. After support restores an
eligible checkpoint, use the normal **Resume** control and watch EQP for a new
selection and gated execution. This recovery pauses at this cycle's boundary;
it must not start another fabrication cycle. If the checkpoint is rejected,
preserve the blocker and investigate the changed evidence rather than deleting
the record or its exclusive claim.

## Eligibility

- The run is paused at the Guardian recovery wait for `EQUIPMENT_WORKFLOW_SELECTION_REJECTED`.
- The failed selection has no executed lifecycle events. Only an operator-review selection or the explicitly recognized pre-model adapter TypeError is eligible.
- Run, cycle, specimen and experiment identities match the durable Equipment record.
- Manipulation is successful and stopped, with matching Verification 1 evidence.
- No active safety source or stop flag is present; no Analysis/BO execution has started for the cycle.

## Save, restore and resume

The following is a support runbook, not a routine GUI retry. All eligibility
checks above must pass before checkpoint creation or a server restart.

1. `python -m app.equipment_selection_checkpoint --run-id RUN_ID` writes `runs/RUN_ID/recovery/equipment_selection.json`, retaining the complete state, planning transcript identity, completed specimen payload and checksums of owner results.
2. Restart the server only after the checkpoint validates. Existing checkpoints are never overwritten.
3. `POST /api/runs/RUN_ID/recovery/restore-equipment-selection` restores the paused run on a fresh inactive server. It performs no device action.
4. The normal `POST /api/runs/RUN_ID/resume` revalidates the checkpoint, runtime identities and PLC start gate, then enters the existing graph tail at Equipment. Printing and completed robot transfer are not repeated.

A durable, exclusive claim prevents dispatching this checkpoint twice, including across another restart. Any changed transcript, owner result, selection record or specimen identity blocks restoration. Investigate the newer execution rather than deleting a claim to replay work.

The resumed tail retains normal Equipment, verification and safety gates. It stops at this cycle's boundary without starting another fabrication cycle. That restriction belongs to this explicit recovery, not normal experiment defaults. Historical image evidence is retained as history, never given a fabricated fresh timestamp.
