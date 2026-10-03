# Vision review and same-run retry

Use this guide for a failed ActiveCam image review after printing has completed.
Recovery must obtain a new image for the same run and specimen; it must not reuse
the failed image as fresh proof or repeat printing/ejection.

## Operator: inspect the failure before requesting a retry

1. Open Live GUI → VIS and inspect the ActiveCam raw/annotated image, verdict
   and blocking reason. Compare the run, cycle and specimen with SPC's verified
   printer-completion evidence.
2. Check Timeline for any downstream Manipulation, Equipment, Analysis or BO
   execution in that cycle. If any exists, or if physical effects are uncertain,
   this narrow retry is not eligible. Keep the run paused and request review.
3. Retain the failed attempt's images and execution ID. Ask support to establish
   the eligible recovery boundary described below; do not invoke hot reload as a
   normal operator repair step.
4. Once recovery is prepared, use **Resume**. The PLC interlock is checked and
   the existing graph tail starts at Vision with a fresh capture. Confirm that
   the new image and verdict belong to this attempt before reading later stages.

Success continues the configured cycle series, with no new one-cycle cap. A
remaining owner failure appears as `needs_attention`; it is not cycle completion.
See [Resume routing](run_resume.md) for other failure types.

## How to interpret image-review evidence

Vision decision references are restricted to the reviewed `vision-role` Wiki page.
The retrieval query describes the current inspection contract, not the overall
experiment/BO goal. References remain background information, not frame evidence
or permission to introduce new acceptance criteria.

For same-capture raw/annotated image review, code checks original raster bounds,
finite ordered coordinates and center/bounding-box consistency. It supplies
normalized positions to the model. The model checks visible target/box agreement
without estimating exact pixels from its image representation. Numeric validity
does not establish detection correctness or override visual rejection. Existing
ROI, identity, freshness, clearance and physical-safety gates remain in force.

## Operator-requested retry

This section describes the support-only preparation contract. It does not grant
permission to change a running experiment or bypass a safety latch.

The support hot-reload endpoint can prepare a narrow retry when an inactive run
has verified same-cycle printer completion and an archived failed ActiveCam
image review. It rejects safety latches, scope changes and any same-cycle
downstream manipulation/equipment/analysis/BO execution. Hot reload runs tests
and verifies source hashes before publishing stateless support functions and
the compatible Resume dispatcher. It does not actuate devices.

The existing Resume control then checks the PLC interlock and starts the shared
tail at Vision with a fresh capture. It does not upload, print or eject again,
and does not treat the archived picture as current evidence. On successful
recovery, the existing configured cycle series continues; this image-review
retry does not impose a new one-cycle cap. Explicit printer-wait or Equipment
restart checkpoints have their own separate recovery limits.
An unresolved owner failure is reported as `needs_attention`, not successful
cycle completion. Original failed attempts remain in the runtime archive.
