(function exposeWindowsEquipmentSelection(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.atrWindowsEquipmentSelection = api;
  }
}(typeof globalThis !== "undefined" ? globalThis : this, function buildWindowsEquipmentSelection() {
  "use strict";

  function candidateSelectionView(candidate) {
    const selected = Boolean(candidate && candidate.selected);
    return {
      selected,
      cardClass: selected ? "equipment-candidate-card selected" : "equipment-candidate-card",
      ariaCurrent: selected ? "true" : null,
      buttonText: selected ? "Selected" : "Select",
      buttonDisabled: selected,
      buttonClass: selected ? "btn mini primary" : "btn mini",
      ariaPressed: selected ? "true" : "false",
    };
  }

  function confirmCandidateSelection(response, requestedAlias) {
    const payload = response && typeof response === "object" ? response : {};
    const expected = String(requestedAlias || "").trim();
    if (payload.ok !== true) {
      throw new Error(String(payload.message || payload.failure_code || "Windows bridge candidate selection failed."));
    }
    if (payload.selected !== true || String(payload.selected_candidate || "") !== expected) {
      throw new Error(`Windows bridge did not confirm requested candidate: ${expected}`);
    }
    return payload;
  }

  function profileConnectionStatus(connection) {
    const payload = connection && typeof connection === "object" ? connection : {};
    const explicit = String(payload.status || "").trim();
    if (explicit && explicit !== "unknown") return explicit;
    return payload.selected === true ? "selected" : "missing";
  }

  function selectedCandidatesFirst(candidates) {
    const list = Array.isArray(candidates) ? candidates : [];
    return [
      ...list.filter((candidate) => Boolean(candidate && candidate.selected)),
      ...list.filter((candidate) => !Boolean(candidate && candidate.selected)),
    ];
  }

  function agenticRunTerminalBadgeView(_result) {
    return {
      state: "idle",
      detail: "",
    };
  }

  function skillIdFromRecordingName(name, recordingId) {
    const source = String(name || recordingId || "recording_skill")
      .normalize("NFKD")
      .toLowerCase();
    const slug = source
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 96);
    return slug || "recording_skill";
  }

  return {
    agenticRunTerminalBadgeView,
    candidateSelectionView,
    confirmCandidateSelection,
    profileConnectionStatus,
    selectedCandidatesFirst,
    skillIdFromRecordingName,
  };
}));
