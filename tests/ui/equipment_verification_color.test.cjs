const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');

test('equipment vision verification uses cyan normally and retains red on failure', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<style>${fs.readFileSync('web/static/styles.css', 'utf8')}</style><body class="planning-live-body"><div class="ar-equipment-agentic-card">${['waiting', 'success', 'failed'].map(state => `<div id="${state}" class="ar-equipment-agentic-vision-slot is-${state}"><strong>Vision verification</strong></div>`).join('')}</div></body>`);
    const colors = await page.evaluate(() => Object.fromEntries(['waiting', 'success', 'failed'].map(id => [id, getComputedStyle(document.querySelector(`#${id} strong`)).color])));
    for (const state of ['waiting', 'success']) {
      const [red, green, blue] = colors[state].match(/[\d.]+/g).map(Number);
      assert.ok(blue > green && green > red + 50, `${state} should be cyan: ${colors[state]}`);
    }
    assert.equal(colors.failed, 'rgba(254, 202, 202, 0.98)');
  } finally { await browser.close(); }
});
