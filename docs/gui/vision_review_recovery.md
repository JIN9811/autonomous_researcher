# Vision review and same-run retry

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

The support hot-reload endpoint can prepare a narrow retry when an inactive run
has verified same-cycle printer completion and an archived failed ActiveCam
image review. It rejects safety latches, scope changes and any same-cycle
downstream manipulation/equipment/analysis/BO execution. Hot reload runs tests
and verifies source hashes before publishing stateless support functions and
the compatible Resume dispatcher. It does not actuate devices.

The existing Resume control then checks the PLC interlock and starts the shared
tail at Vision with a fresh capture. It does not upload, print or eject again,
and does not treat the archived picture as current evidence. This bounded retry
returns at the current cycle boundary without launching the next fabrication.
An unresolved owner failure is reported as `needs_attention`, not successful
cycle completion. Original failed attempts remain in the runtime archive.
