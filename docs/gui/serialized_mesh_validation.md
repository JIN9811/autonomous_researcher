# Serialized specimen mesh validation

Use the generated specimen's **Validity** field to distinguish a rejected mesh
from one that has not been checked. A plausible preview is not evidence that the
STL on disk passed manufacturing gates.

## When a specimen is rejected

Open Live GUI → SPC and inspect the geometry, mesh-quality and wall-thickness
results for the same specimen. In its artifacts, locate the STL and
`geometry_report.serialized_mesh_cleanup`; compare the reported STL SHA-256 with
the file used for the handoff. Missing evidence remains unverified, not passing.

If generation failed before any device operation, the
[pre-device SPC recovery conditions](run_resume.md#spc-retry-before-device-execution)
describe when Resume can repeat SPC for the same specimen. Do not manually repair
the retained STL, relax a failed gate, or treat a preview as permission to print.
If a printer request may already have occurred, use job-bound recovery instead.

## What the on-disk check does

Generated gyroid meshes are checked after writing the STL, not only in
memory. STL float32 serialization can collapse very small triangles even when
the pre-export mesh has already been cleaned.

The generation path performs these steps:

1. Generate the requested geometry without changing cell size or wall thickness.
2. Export STL and reload the serialized mesh.
3. Remove degenerate and duplicate faces and unreferenced vertices only.
4. Verify the cleaned temporary STL, publish it atomically, and recheck the
   published file before returning generation success.
5. Independently inspect that file in the mesh-quality and wall-thickness gates.

Cleanup does not fill holes, smooth surfaces, repair normals, remove additional
components, or relax wall-thickness limits. Remaining topology defects, changed
envelope, inverted volume, and unexpected bounding-box dimensions are rejected.
The self-intersection check is explicitly marked `not_performed`; it is not
reported as zero intersections.

`geometry_report.serialized_mesh_cleanup` records removed face counts and the
final validation, including STL SHA-256, dimensions, topology, volume and face
counts. The generated-specimen Validity field uses specimen-scoped SPC gate
evidence when available, distinguishing failure from unverified geometry.

Regression coverage includes the cycle-8 wall/cell pair
`0.858487698594413 / 7.184657338151279 mm`, which exposed six degenerate faces
after serialization. Direct and compute-worker execution must produce identical
final STL hashes and manufacturing verdicts. Operational run files are not
rewritten by these tests.
