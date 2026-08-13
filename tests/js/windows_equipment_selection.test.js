"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  candidateSelectionView,
  confirmCandidateSelection,
  profileConnectionStatus,
} = require("../../web/static/windows_equipment_selection.js");

test("selected candidate view is explicit, disabled, and accessible", () => {
  const selected = candidateSelectionView({
    candidate_alias: "windows_192.168.50.40_Nextpc",
    selected: true,
  });
  const standby = candidateSelectionView({
    candidate_alias: "windows_192.168.50.58",
    selected: false,
  });

  assert.deepEqual(selected, {
    selected: true,
    cardClass: "equipment-candidate-card selected",
    ariaCurrent: "true",
    buttonText: "Selected",
    buttonDisabled: true,
    buttonClass: "btn mini primary",
    ariaPressed: "true",
  });
  assert.deepEqual(standby, {
    selected: false,
    cardClass: "equipment-candidate-card",
    ariaCurrent: null,
    buttonText: "Select",
    buttonDisabled: false,
    buttonClass: "btn mini",
    ariaPressed: "false",
  });
});

test("selection confirmation rejects application failure and alias mismatch", () => {
  const requested = "windows_192.168.50.40_Nextpc";
  assert.equal(
    confirmCandidateSelection(
      { ok: true, selected: true, selected_candidate: requested },
      requested,
    ).selected_candidate,
    requested,
  );
  assert.throws(
    () => confirmCandidateSelection(
      { ok: false, failure_code: "PYAUTOGUI_CANDIDATE_NOT_FOUND" },
      requested,
    ),
    /PYAUTOGUI_CANDIDATE_NOT_FOUND/,
  );
  assert.throws(
    () => confirmCandidateSelection(
      { ok: true, selected: true, selected_candidate: "windows_other" },
      requested,
    ),
    /did not confirm requested candidate/,
  );
});

test("profile connection display derives selected state when status is absent", () => {
  assert.equal(profileConnectionStatus({ selected: true }), "selected");
  assert.equal(profileConnectionStatus({ selected: true, status: "unknown" }), "selected");
  assert.equal(profileConnectionStatus({ selected: false }), "missing");
  assert.equal(profileConnectionStatus({ selected: true, status: "ready" }), "ready");
});
