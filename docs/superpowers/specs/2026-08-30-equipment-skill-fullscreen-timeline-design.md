# Equipment Skill Full-Screen Timeline Design

Date: 2026-08-30
Status: Implemented and under full-path verification

## 1. Purpose

Record the complete Windows equipment demonstration as a low-rate visual timeline, let the selected multimodal LLM understand the entire operation flow, and preserve enough evidence to rebuild, validate, deploy, and execute an Equipment Skill without relying on a short rolling buffer.

This design extends the existing Windows PyAutoGUI recording and Linux-side Skill authoring path. It does not introduce a second recording or execution path.

## 2. Required Behavior

- Capture the complete desktop at 2 FPS from recording start through recording stop.
- Persist every periodic frame to disk instead of evicting frames after 20-30 seconds.
- Capture event evidence independently at mouse, keyboard, window-transition, checkpoint, exception, and recording-boundary events.
- For an action event, retain the most recent clean pre-action frame, the event-time frame, and a post-action frame.
- Hide the recording overlay before the final frame is captured.
- Preserve the native full-screen source frame. Generate reduced derivatives only for preview or LLM transport.
- Do not impose an arbitrary frame-count, duration, or total-byte evidence limit on a completed recording.
- Protect the host only with explicit disk-space and write-failure handling. Never silently truncate a recording.
- Make the selected shared multimodal backend interpret the complete timeline, including both periodic and event evidence.
- Compile the approved interpretation into the existing deterministic Equipment Skill format and deploy it through the existing authenticated worker path.

## 3. Architecture

### 3.1 Windows recorder

The Windows worker owns capture only. It does not perform semantic interpretation.

During recording it runs one 2 FPS capture producer. Each frame is written immediately to the recording directory; the producer keeps only the current encode buffer and a small recent-frame cache needed for pre-action evidence. No full-session image list is retained in RAM.

Event capture is an additional evidence layer, not a replacement for the 2 FPS sequence. Event records point to the closest periodic frame and may also own high-quality event frames when an exact boundary image is required.

### 3.2 Linux importer

The existing authenticated recording package endpoint remains the only transfer route. The importer verifies the package manifest, path containment, file size, SHA-256, and chronological index before exposing the recording to Skill authoring.

### 3.3 Multimodal timeline analyzer

Model context and request-size limits cannot be removed. Instead, all evidence is processed without silent loss through hierarchical temporal analysis:

1. Split the complete timeline into deterministic eight-second chronological chunks.
2. Build one 4x4 temporal storyboard from the 16 periodic frames in each chunk.
3. Overlay timestamp, frame ID, event type, and compact input-action metadata on each tile without covering the observed control area.
4. Mark chronological direction and distinguish pre-action, event-time, post-action, boundary, and exception frames with a consistent visual key.
5. Include the storyboard, event frames, input events, active-window metadata, and prior/next boundary context in each chunk request.
6. Ask the selected multimodal backend to describe state transitions, operator intent, visible completion evidence, failures, and candidate locators for that chunk.
7. Persist each chunk result with its exact storyboard-tile and source-frame references.
8. Build a session overview storyboard from representative chunk boundaries for GUI inspection and audit. Final synthesis consumes the ordered chunk analyses and only action-locator images that were not already represented by those analyses; it does not resend state-frame or overview images.
9. Produce one workflow summary, ordered step transitions, locator proposals, completion criteria, and exception evidence.

The same shared backend selection applies to OpenAI, vLLM, Ollama, NemoClaw, and mock/test backends. Unsupported visual capability is an explicit failure; no undeclared backend fallback is allowed.

### 3.4 Skill compiler and deployment

The existing flow remains authoritative:

```text
Windows recording
  -> authenticated package transfer
  -> package and timeline validation
  -> multimodal chunk annotation
  -> final workflow synthesis
  -> deterministic Skill compilation
  -> validation and approval
  -> deployment to the selected Windows worker
  -> deterministic execution
```

Normal Skill execution does not call the LLM. The LLM is used during authoring and, separately, during declared exception recovery.

## 4. Recording Storage Contract

Each recording uses the following structure:

```text
recordings/<recording_id>/
  recording.json
  timeline.jsonl
  manifest.json
  frames/
    periodic/
      frame-00000001.jpg
      frame-00000002.jpg
      ...
    events/
      event-000001-pre.png
      event-000001-at.png
      event-000001-post.png
      ...
    boundaries/
      recording-start.png
      recording-stop.png
    exceptions/
      ...
  derivatives/
    previews/
    llm/
      storyboards/
        chunk-0001.jpg
        ...
        session-overview.jpg
  authoring/
    chunks/
      chunk-0001.json
      ...
    workflow-synthesis.json
```

`timeline.jsonl` is append-only. Each row contains:

- monotonic and wall-clock timestamps;
- frame ID and relative path;
- evidence role: `periodic`, `pre_action`, `event`, `post_action`, `boundary`, or `exception`;
- active window title and process when available;
- pointer position and input-event reference when applicable;
- display dimensions and image dimensions;
- mask-policy version;
- SHA-256 and encoded byte size;
- related action, step, chunk, and checkpoint identifiers when known.

`manifest.json` contains the complete file inventory and hashes. `recording.json` contains capture configuration, start/stop state, display topology, language/input state, and package schema version.

## 5. Capture and Encoding Defaults

- Periodic capture: fixed 2 FPS.
- Periodic format: JPEG at a quality chosen to keep text and controls legible; native desktop dimensions are retained.
- Event and boundary format: PNG.
- LLM derivative: bounded resolution and format selected by the backend adapter; the source frame is never replaced.
- Temporal storyboard: 4x4 tiles, 16 periodic frames, and eight seconds per default chunk at 2 FPS.
- Storyboard overlays: timestamp, frame ID, event marker, action label, and chronological direction; overlays must not obscure the event ROI.
- Session overview: representative boundary tile from every chunk, paginated into multiple overview images when one image would make labels unreadable.
- Preview derivative: browser-oriented JPEG/WebP generated from the source.
- Recent-frame RAM cache: only enough frames to resolve pre-action evidence; it is not the recording archive.

## 6. Capacity and Failure Handling

There is no normal evidence-count or recording-duration cutoff. Capacity protection is explicit:

- Before recording, estimate the available duration from recent encoded frame sizes and free disk space.
- During recording, periodically check free space and writer health.
- At the warning threshold, keep recording and surface an operator warning.
- At the critical threshold or on write failure, stop capture cleanly, finalize the partial package, mark it incomplete, and preserve all frames already written.
- Never delete old recordings automatically as part of capture.
- Never report a complete recording when the timeline or manifest finalization failed.

## 7. LLM Flow Understanding

The authoring prompt and response schema must require temporal reasoning rather than independent image captions. For every chunk and final synthesis, the model must identify:

- initial visible state;
- operator action and likely intent;
- resulting state transition;
- visible success or failure evidence;
- whether the action depends on coordinates, text, image location, window state, or timing;
- stable ROI candidates from pre-action frames that do not include the pointer;
- uncertainty and required operator review.

Chunk analyses include ordered timestamps and adjacent event references so transitions remain traceable at boundaries. Final synthesis receives every persisted chunk result and must reference source frame IDs for compiled steps and completion conditions.

Storyboards are transport derivatives, not authoritative evidence. Every tile maps to an immutable source frame through `timeline.jsonl`, including tile index, crop/scale transform, source SHA-256, and event references. The LLM receives the storyboard together with structured timeline metadata so visual order and machine-readable time remain consistent.

## 8. GUI Behavior

The existing Windows recording overlay remains the single recording control:

- five-second countdown;
- recording indicator and elapsed time;
- one Stop control;
- no pairing requirement for local recording;
- final clean frame after the overlay disappears.

Linux Lab Equipment Workspace shows one authoring job with ordered progress:

```text
Importing -> Validating -> Analyzing timeline -> Synthesizing ->
Compiling -> Validating Skill -> Ready to deploy -> Deploying -> Deployed
```

Preview loads timeline pages on demand. It must not load the entire recording into browser memory.

## 9. Test Strategy

### Unit tests

- 2 FPS scheduling and chronological frame IDs;
- immediate disk persistence and bounded RAM cache;
- event pre/at/post linkage;
- clean recording-stop boundary capture;
- timeline and manifest hash generation;
- disk-warning and clean partial-finalization behavior;
- deterministic chronological chunking with boundary event references and no omitted frame IDs;
- deterministic 4x4 storyboard composition, labels, visual key, and tile-to-source mapping;
- session overview pagination without unreadable downscaling;
- multimodal backend request construction and response validation;
- workflow synthesis source-reference validation.

### Integration tests

- Windows package export and Linux import with a multi-chunk recording;
- recording list, preview pagination, annotation, compilation, deployment, and execution APIs;
- selected backend propagation through the complete authoring job;
- canonical Windows server and install mirror parity;
- portable release contains the current server, supervisor, updater, and dependencies.

### Full-path acceptance

Run through the GUI path, not a private helper path:

1. Start the Windows worker from the packaged launcher.
2. Record a representative desktop skill long enough to produce multiple analysis chunks.
3. Stop from the recording overlay.
4. Confirm 2 FPS periodic frames plus event evidence and the final clean frame.
5. Confirm each eight-second interval produces a readable 4x4 storyboard whose tiles resolve to the original frames.
6. Select the recording in Lab Equipment Workspace.
7. Import, annotate with the selected multimodal backend, compile, and validate the Skill.
8. Deploy the Skill to the selected worker.
9. Execute it from the GUI.
10. Compare execution checkpoints against the recorded source evidence.
11. Verify process cleanup, bounded memory, artifact persistence, and audit logs.

Physical equipment actuation is performed only when the selected demonstration is explicitly approved for live execution. A desktop-only test Skill is used first to validate the complete software path.

## 10. Acceptance Criteria

- A recording longer than 30 seconds retains its complete 2 FPS visual history.
- Event evidence is linked chronologically to the periodic timeline.
- Stopping recording leaves no capture thread or unbounded image collection in memory.
- The imported package contains every indexed source frame with a verified hash.
- The LLM analyzes every timeline chunk and final synthesis includes source evidence references.
- The LLM receives ordered storyboards plus structured timestamps and can trace every interpreted transition back to original frames.
- No arbitrary `max_images` or total-evidence-byte limit silently drops completed recording evidence.
- Preview and model transport derivatives do not replace or modify source evidence.
- The GUI can complete recording, Skill conversion, deployment, and execution through the public application routes.
- The deployed Skill executes deterministically without requiring the LLM in the normal path.
