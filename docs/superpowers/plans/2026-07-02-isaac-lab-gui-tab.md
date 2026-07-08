# Isaac Lab GUI Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Isaac Lab controls out of section 7 into a dedicated in-page `Isaac Lab` tab while leaving training and Isaac Sim runtime code untouched.

**Architecture:** Add a lightweight tab shell to `web/templates/lerobot.html`. Keep existing Isaac Lab element IDs and API bindings so `web/static/lerobot.js` can reuse the current payload and action functions. Section 7 becomes a launcher and status summary only.

**Tech Stack:** Static HTML template, vanilla JavaScript, existing CSS, pytest static GUI tests.

---

### Task 1: Static GUI Contract Tests

**Files:**
- Modify: `tests/unit/test_lerobot_gui_static.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```python
def test_lerobot_isaac_lab_gui_tab_shell_is_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert 'id="lerobot-main-tab"' in template
    assert 'id="isaac-lab-tab"' in template
    assert 'id="btn-open-isaac-lab-gui"' in template
    assert 'data-lerobot-tab-target="isaac-lab-tab"' in template
    assert "function activateLeRobotGuiTab" in script
    assert 'bind("btn-open-isaac-lab-gui"' in script
```

Add a second test that checks section 7 no longer owns the full Lab control surface:

```python
def test_lerobot_section_7_is_launcher_not_full_lab_surface() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    launcher_start = template.index('id="isaac-augmentation-card"')
    lab_tab_start = template.index('id="isaac-lab-tab"')
    section_7 = template[launcher_start:lab_tab_start]

    assert "Open Isaac Lab GUI" in section_7
    assert "isaac-synthetic-pipeline-mode" not in section_7
    assert "isaac-synthetic-run-mimic" not in section_7
    assert "isaac-synthetic-status-training-exposure" not in section_7
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest tests/unit/test_lerobot_gui_static.py::test_lerobot_isaac_lab_gui_tab_shell_is_wired tests/unit/test_lerobot_gui_static.py::test_lerobot_section_7_is_launcher_not_full_lab_surface -q
```

Expected: both tests fail because the tab shell and launcher split do not exist yet.

### Task 2: HTML Tab Split

**Files:**
- Modify: `web/templates/lerobot.html`

- [ ] **Step 1: Add tab bar and tab panels**

Add an in-page tab bar after the quick nav:

```html
<div class="panel lerobot-tab-bar" role="tablist" aria-label="LeRobot workspace tabs">
  <button id="lerobot-main-tab-button" class="btn active" type="button" data-lerobot-tab-target="lerobot-main-tab">LeRobot</button>
  <button id="isaac-lab-tab-button" class="btn" type="button" data-lerobot-tab-target="isaac-lab-tab">Isaac Lab</button>
</div>
<div id="lerobot-main-tab" class="lerobot-tab-panel active" role="tabpanel">
```

Close the main tab before the session output, then add:

```html
</div>
<div id="isaac-lab-tab" class="lerobot-tab-panel" role="tabpanel" tabindex="-1">
  ...
</div>
```

- [ ] **Step 2: Replace section 7 Lab controls with launcher**

Section 7 keeps the existing augmentation controls but moves the `isaac-synthetic-panel` block into `isaac-lab-tab`. The section keeps:

```html
<div id="isaac-lab-launcher-summary" class="lerobot-report-card">
  <strong>Isaac Lab GUI</strong>
  <span>Dedicated Lab setup, HDF5 export, Mimic, RL teacher, and reports.</span>
</div>
<button id="btn-open-isaac-lab-gui" class="btn primary" type="button">Open Isaac Lab GUI</button>
```

### Task 3: JavaScript Tab Switching

**Files:**
- Modify: `web/static/lerobot.js`

- [ ] **Step 1: Add DOM references**

Add:

```javascript
const lerobotTabButtons = Array.from(document.querySelectorAll("[data-lerobot-tab-target]"));
const lerobotTabPanels = Array.from(document.querySelectorAll(".lerobot-tab-panel"));
```

- [ ] **Step 2: Add tab activation function**

Add:

```javascript
function activateLeRobotGuiTab(targetId) {
  const target = $(targetId);
  if (!target) return;
  lerobotTabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === targetId));
  lerobotTabButtons.forEach((button) => button.classList.toggle("active", button.dataset.lerobotTabTarget === targetId));
  target.focus({ preventScroll: false });
}
```

- [ ] **Step 3: Bind tab buttons and launcher**

Add:

```javascript
lerobotTabButtons.forEach((button) => {
  button.addEventListener("click", () => activateLeRobotGuiTab(button.dataset.lerobotTabTarget));
});
bind("btn-open-isaac-lab-gui", () => activateLeRobotGuiTab("isaac-lab-tab"));
```

### Task 4: CSS For Tabs

**Files:**
- Modify: `web/static/styles.css`

- [ ] **Step 1: Add tab styles**

Add:

```css
.lerobot-tab-bar {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.lerobot-tab-panel {
  display: none;
}

.lerobot-tab-panel.active {
  display: block;
}
```

### Task 5: Verification

**Files:**
- Test: `tests/unit/test_lerobot_gui_static.py`

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/unit/test_lerobot_gui_static.py -q
```

Expected: all static GUI tests pass.

- [ ] **Step 2: Run frontend smoke**

Start the local app if needed and verify:

```bash
python -m pytest tests/unit/test_lerobot_gui_static.py -q
```

Expected: no failures. If a local server is available, use Playwright to verify default `LeRobot` tab and launcher-to-`Isaac Lab` tab switch.
