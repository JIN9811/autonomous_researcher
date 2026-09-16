"""Display-only capture publication; grants no verification or handoff authority."""
from datetime import datetime, timezone


def publish_capture_preview(state, capture, slot):
    if not isinstance(capture, dict) or capture.get("capture_skipped") or capture.get("ok") is False:
        return False
    scope = {"run_id": state.run_id, "loop_id": state.loop_count,
             "specimen_id": state.current_experiment_spec.get("specimen_id", "")}
    if any(capture.get(k) not in (None, "", v) for k, v in scope.items()):
        return False
    path = next((capture.get(k) for k in ("annotated_frame_path", "annotated_capture_path", "frame_path",
                "capture_path", "raw_frame_path", "image_path", "path") if capture.get(k)), "")
    url = capture.get("artifact_url") or capture.get("frame_url") or capture.get("capture_url") or ""
    if not path and not url:
        return False
    records = state.run_metadata.get("utm_verifications") or {}
    if any(records.get(k) != v for k, v in scope.items()):
        records = dict(scope)
        state.run_metadata["utm_verifications"] = records
    records.setdefault("previews", {})[slot] = {
        "status": "pending", "confirmed": False, "review_pending": True,
        "captured_at": capture.get("captured_at") or capture.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "artifact": {"path": str(path), "url": str(url)},
        "evidence": {k: capture[k] for k in ("roi_xyxy", "width", "height", "frame_width", "frame_height") if k in capture},
    }
    return True
