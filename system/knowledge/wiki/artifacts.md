---
{"topic_id":"artifacts","owner":"documentation","source_refs":["system/runtime/loop_artifact_archiving.md","system/knowledge/publication.md"],"source_revision":{"system/runtime/loop_artifact_archiving.md":"96868e8b3e73bc37373a9b3bf279c4b7a30a09c4081aabc589a2dccf2bd4e25f","system/knowledge/publication.md":"45d6b053ad1f4632f089b80bec6e0729783d2ed1d4328170a992c23fba52ffe4"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: artifacts","status":"reviewed"}
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
