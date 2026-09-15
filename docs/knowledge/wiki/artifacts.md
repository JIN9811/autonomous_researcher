---
{"topic_id":"artifacts","owner":"documentation","source_refs":["docs/runtime/loop_artifact_archiving.md","docs/knowledge/publication.md"],"source_revision":{"docs/runtime/loop_artifact_archiving.md":"9bd25ead4124f7905da7d47df243d9c8a6c8377f8298f37831874adf9901b6a3","docs/knowledge/publication.md":"e97dab54bf4de8be668589091b6fd06e2cfbd9307b56f3db527e90f780734371"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: artifacts","status":"reviewed"}
---

# Artifacts — Run Outputs and Records

Artifacts preserve inputs, outputs, events and files by run, loop, agent and attempt. They are not temporary dashboard illustrations. New loops and retries retain previous invocation records.

## Finding a result

1. Check the run and loop.
2. Open Artifacts from the relevant agent.
3. Select its report, plot or original file in the folder/file explorer.
4. Distinguish earlier attempts by identity and status.

Opening from an agent defaults to that agent and the current loop. All files may include other owners and older results. Files with unknown loop ownership are not arbitrarily assigned to the current loop.

| File type | Contents |
|---|---|
| Input/result JSON | Conditions received and results returned |
| Events/tool records | Call order, observations and failures |
| Measurement CSV | Original equipment export |
| Reports/curves/figures | Derived interpretation and visualization |
| Manifest | Invocation/file identity and archival metadata |

Folders reflect the archive hierarchy, typically loop, agent and attempt under runtime/loops. Short display labels do not change original paths.

## Preview limits

CSV previews show at most 100 data rows and 40 columns. Large text and binary files use original-file links. Preview row counts are not measurement counts, and preview limits do not truncate original experimental data.

Chat-linked files can appear under Linked references in the same explorer. Reading files does not rerun past calculations or necessarily create new artifacts. Failure and cancellation records are retained; archival completion is separate from experiment success.

Original experiment files and private context do not belong in the public Wiki.

[Artifact reference](../../runtime/loop_artifact_archiving.md), [publication boundary](../publication.md).
