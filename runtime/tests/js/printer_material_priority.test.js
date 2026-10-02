"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../web/static/printer.js"), "utf8");

function workspace() {
  let saved = {enabled: false, slots: []};
  const requests = [];
  const context = vm.createContext({
    materialPriorityOrder: [], lastMaterialPanel: {}, materialPriorityEnabled: {checked: false},
    materialPriorityState: {}, btnMaterialPrioritySave: {}, materialSlotSummary: {}, materialSlotList: {},
    escapeHtml: (s) => String(s), formatMaybe: (value, suffix = "") => value == null ? "--" : `${value}${suffix}`,
    setBusy() {}, writeLog() {},
    apiJson: async (url, request) => {
      requests.push({url, request});
      if (request) saved = JSON.parse(request.body);
      return {ok: true, priority: saved};
    },
  });
  const start = source.indexOf("function orderedMaterialSlots(");
  vm.runInContext(source.slice(start, source.indexOf("function renderEvidenceCards(", start)), context);
  return {context, requests};
}

test("telemetry refresh cannot revert an operator's reordered slots", async () => {
  const {context, requests} = workspace();
  const panel = {slots: [{slot_id: "0:1", tray_type: "PLA"}, {slot_id: "0:2", tray_type: "PLA"}]};
  context.renderMaterialSlots(panel);
  context.moveMaterialPriority("0:2", -1);
  context.renderMaterialSlots(panel);
  assert.equal(context.materialPriorityOrder.join(","), "0:2,0:1");
  assert.equal(context.materialPriorityEnabled.checked, true);
  assert.equal(context.materialPriorityState.textContent, "Unsaved");
  assert.match(context.materialSlotList.innerHTML, /Priority 1/);
  assert.match(context.materialSlotList.innerHTML, /aria-label="Increase priority"/);
  assert.match(context.materialSlotList.innerHTML, /aria-label="Decrease priority"/);
  await context.saveMaterialPriority();
  assert.equal(context.materialPriorityState.textContent, "Saved");
  assert.equal(requests[0].url, "/api/printer/material-priority");
  assert.deepEqual(JSON.parse(requests[0].request.body), {enabled: true, slots: ["0:2", "0:1"]});
  context.materialPriorityOrder = [];
  await context.refreshMaterialPriority();
  assert.equal(context.materialPriorityOrder.join(","), "0:2,0:1");
});

test("disconnected preferred slots remain ordered and unsupported slots are not selectable", () => {
  const {context} = workspace();
  context.materialPriorityOrder = ["0:2", "0:1"];
  context.renderMaterialSlots({slots: [{slot_id: "0:1", tray_type: "PLA"}, {slot_id: "128:0", ams_id: "128", tray_id: "0"}]});
  assert.equal(context.materialPriorityOrder.join(","), "0:2,0:1");
  assert.match(context.materialSlotList.innerHTML, /Disconnected/);
  assert.doesNotMatch(context.materialSlotList.innerHTML, /data-priority-slot="128:0"/);
});

test("priority controls and placement reminder use English", () => {
  const template = fs.readFileSync(path.join(__dirname, "../../web/templates/printer.html"), "utf8");
  assert.match(template, /Enable priority/);
  assert.match(template, /Save priority/);
  assert.match(template, /Re-slice the original STL after changing the position\./);
  assert.doesNotMatch(source, /[\uac00-\ud7a3]/);
});

test("slot cards separate priority, material, details, and remaining amount", () => {
  const {context} = workspace();
  context.renderMaterialSlots({slots: [{slot_id: "0:1", tray_type: "PLA", label: "AMS 1 · Slot 2", tray_sub_brands: "Bambu", remain_percent: 80}]});
  const html = context.materialSlotList.innerHTML;
  assert.match(html, /<span class="bambu-material-priority">Priority 1<\/span>\s*<strong>PLA<\/strong>\s*<span>AMS 1 · Slot 2 · Bambu<\/span>\s*<small>Remaining: 80%<\/small>/);
  assert.match(html, /data-priority-slot="0:1"/);
});
