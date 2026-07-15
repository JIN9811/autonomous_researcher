# LeRobot Camera USB Link Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the negotiated USB link of each RealSense camera during Detect & Save and show it on the Top/Wrist Device Port Setup cards.

**Architecture:** RealSense enumeration collects SDK identity, USB descriptor, physical port, and ASIC serial without starting a stream. A pure normalization helper resolves the actual sysfs speed when possible, derives a stable display contract, and passes it through the existing `ports_detect`/`ports_save` persistence path. The existing `renderDeviceMemory()` path renders that contract as a compact status badge and remains backward-compatible with saved profiles that lack the new fields.

**Tech Stack:** Python 3.12, pyrealsense2, Linux sysfs, FastAPI bridge responses, vanilla JavaScript, CSS, pytest.

## Global Constraints

- Preserve the existing camera Detect & Save, capture, teleoperation, recording, and rollout behavior.
- Do not block workflows, reset hardware, or add a fallback based on USB link speed.
- Show USB 3.x as `ok`, USB 2.x as `warning`, and unavailable metadata as `unknown`.
- Persist `usb_type`, `usb_speed_mbps`, `usb_link_label`, and `usb_link_status` in the existing camera device entry.
- Existing camera entries without USB fields must continue loading and display `USB link unknown`.
- Do not revert or rewrite unrelated changes in the dirty worktree.

---

### Task 1: RealSense USB Link Contract

**Files:**
- Modify: `device_bridges/lerobot_bridge.py:13876`
- Test: `tests/unit/test_lerobot_bridge.py:1966`

**Interfaces:**
- Consumes: RealSense entry keys `serial`, `name`, `product_line`, `usb_type`, `physical_port`, and `asic_serial`.
- Produces: `LeRobotBridge._realsense_usb_link_metadata(entry, sysfs_root=Path(...)) -> dict[str, Any]`.

- [ ] **Step 1: Write failing normalization tests**

Add tests that create temporary sysfs device directories and assert these exact contracts:

```python
assert bridge._realsense_usb_link_metadata(entry, sysfs_root=sysfs_root) == {
    "usb_type": "3.2",
    "usb_speed_mbps": 5000,
    "usb_link_label": "USB 3.2 · 5000 Mbps",
    "usb_link_status": "ok",
}
```

Also assert USB `2.1`/`480` returns `warning`, and an empty entry returns `USB link unknown` with status `unknown`.

- [ ] **Step 2: Run RED tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_lerobot_bridge.py -k 'realsense_usb_link_metadata' -q
```

Expected: failure because `_realsense_usb_link_metadata` does not exist.

- [ ] **Step 3: Extend enumeration and add the pure normalizer**

Update both in-process and conda-environment enumeration to collect:

```python
for key in ("name", "serial_number", "product_line", "usb_type_descriptor", "physical_port", "asic_serial_number"):
    ...
```

Normalize SDK names to `usb_type` and `asic_serial`. Resolve sysfs speed by matching `asic_serial` first and the SDK physical-port topology second. If sysfs is unavailable, infer `5000` for USB 3.x and `480` for USB 2.x from the SDK descriptor. Return the four-field contract above.

- [ ] **Step 4: Run GREEN tests**

Run the same focused pytest command and expect all selected tests to pass.

### Task 2: Detect & Save Persistence

**Files:**
- Modify: `device_bridges/lerobot_bridge.py:1417`
- Modify: `device_bridges/lerobot_bridge.py:1560`
- Modify: `device_bridges/lerobot_bridge.py:14045`
- Test: `tests/unit/test_lerobot_bridge.py:2055`

**Interfaces:**
- Consumes: `LeRobotBridge._realsense_entry_for_identifier(identifier, entries)` and Task 1 metadata.
- Produces: USB fields in `saved_device` and `saved_devices.cameras.<camera_key>`.

- [ ] **Step 1: Write failing persistence tests**

Mock a live D455F entry with `usb_type=3.2`, `asic_serial`, and a temporary 5000 Mbps sysfs node. Assert both `ports_detect()` and `ports_save()` persist:

```python
assert saved["usb_link_status"] == "ok"
assert saved["usb_speed_mbps"] == 5000
assert saved["usb_link_label"] == "USB 3.2 · 5000 Mbps"
```

- [ ] **Step 2: Run RED persistence tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_lerobot_bridge.py -k 'realsense_live_detect_persists_usb_link or realsense_live_save_persists_usb_link' -q
```

Expected: assertions fail because saved camera entries lack USB fields.

- [ ] **Step 3: Thread metadata through existing save paths**

Add optional `camera_metadata: dict[str, Any] | None = None` to `_save_device_port()`. For live RealSense detect/save, match the normalized serial against current entries, normalize its USB contract, and merge only the four public USB fields into the camera entry. Test-mode and OpenCV behavior remains unchanged.

- [ ] **Step 4: Run GREEN persistence tests and nearby regressions**

Run:

```bash
.venv/bin/pytest tests/unit/test_lerobot_bridge.py -k 'realsense and (detect or save or usb_link)' -q
```

Expected: all selected tests pass.

### Task 3: Device Port Setup Badge

**Files:**
- Modify: `web/static/lerobot.js:2597`
- Modify: `web/static/lerobot.js:2653`
- Modify: `web/static/styles.css:23610`
- Test: `tests/unit/test_lerobot_gui_static.py`

**Interfaces:**
- Consumes: camera fields `usb_link_label` and `usb_link_status` from the existing `/api/lerobot/config` response.
- Produces: `.lerobot-camera-usb-link.{ok,warning,unknown}` badge markup.

- [ ] **Step 1: Write failing static UI test**

Assert `web/static/lerobot.js` contains the USB badge formatter and fields, and `web/static/styles.css` contains green, amber, and neutral variants.

- [ ] **Step 2: Run RED static test**

Run:

```bash
.venv/bin/pytest tests/unit/test_lerobot_gui_static.py -k 'camera_usb_link' -q
```

Expected: failure because the formatter and CSS classes do not exist.

- [ ] **Step 3: Render and style the badge**

Add `cameraUsbLinkBadge(camera, realsense)` that returns no badge for OpenCV and otherwise uses:

```javascript
const status = ["ok", "warning"].includes(camera.usb_link_status) ? camera.usb_link_status : "unknown";
const label = camera.usb_link_label || "USB link unknown";
```

Render it immediately below the saved camera identifier. Use green for USB 3.x, amber for USB 2.x with `rollout risk`, and a neutral gray for unknown.

- [ ] **Step 4: Run GREEN UI tests**

Run the focused static test and expect it to pass.

### Task 4: Integrated Verification

**Files:**
- Verify only: `device_bridges/lerobot_bridge.py`
- Verify only: `web/static/lerobot.js`
- Verify only: `web/static/styles.css`

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: verified persisted USB status and browser-visible camera badges.

- [ ] **Step 1: Run focused automated regression suite**

```bash
.venv/bin/pytest tests/unit/test_lerobot_bridge.py tests/unit/test_lerobot_gui_static.py tests/integration/test_lerobot_gui_api.py -k 'realsense or camera_usb_link or ports_detect or ports_save' -q
```

- [ ] **Step 2: Run syntax checks**

```bash
.venv/bin/python -m py_compile device_bridges/lerobot_bridge.py
node --check web/static/lerobot.js
```

- [ ] **Step 3: Verify live enumeration without opening camera streams**

Call `_scan_live_realsense_camera_entries()` and confirm D455F and D405 each report `USB 3.2 · 5000 Mbps` on the current machine. Do not start teleoperation, recording, or rollout.

- [ ] **Step 4: Inspect the scoped diff**

```bash
git diff -- device_bridges/lerobot_bridge.py web/static/lerobot.js web/static/styles.css tests/unit/test_lerobot_bridge.py tests/unit/test_lerobot_gui_static.py docs/superpowers/plans/2026-07-15-lerobot-camera-usb-link-status.md
```

Confirm there are no workflow gates, resets, fallback branches, or unrelated changes in this feature diff.
