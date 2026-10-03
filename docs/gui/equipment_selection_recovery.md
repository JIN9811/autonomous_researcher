# Restart recovery at an unexecuted Equipment selection

This operator-requested recovery preserves the current run and completed fabrication/robot transfer. It is not an automatic retry policy or a way to repeat device commands.

## Eligibility

- The run is paused at the Guardian recovery wait for `EQUIPMENT_WORKFLOW_SELECTION_REJECTED`.
- The failed selection has no executed lifecycle events. Only an operator-review selection or the explicitly recognized pre-model adapter TypeError is eligible.
- Run, cycle, specimen and experiment identities match the durable Equipment record.
- Manipulation is successful and stopped, with matching Verification 1 evidence.
- No active safety source or stop flag is present; no Analysis/BO execution has started for the cycle.

## Save, restore and resume

1. `python -m app.equipment_selection_checkpoint --run-id RUN_ID` writes `runs/RUN_ID/recovery/equipment_selection.json`, retaining the complete state, planning transcript identity, completed specimen payload and checksums of owner results.
2. Restart the server only after the checkpoint validates. Existing checkpoints are never overwritten.
3. `POST /api/runs/RUN_ID/recovery/restore-equipment-selection` restores the paused run on a fresh inactive server. It performs no device action.
4. The normal `POST /api/runs/RUN_ID/resume` revalidates the checkpoint, runtime identities and PLC start gate, then enters the existing graph tail at Equipment. Printing and completed robot transfer are not repeated.

A durable, exclusive claim prevents dispatching this checkpoint twice, including across another restart. Any changed transcript, owner result, selection record or specimen identity blocks restoration. Investigate the newer execution rather than deleting a claim to replay work.

The resumed tail retains normal Equipment, verification and safety gates. It stops at this cycle's boundary without starting another fabrication cycle. That restriction belongs to this explicit recovery, not normal experiment defaults. Historical image evidence is retained as history, never given a fabricated fresh timestamp.
