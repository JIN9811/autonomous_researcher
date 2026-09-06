// Run with Playwright available on NODE_PATH; this audit never contacts hardware.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium } = require("playwright");

test("both UTM verification layouts keep the entire frame visible without a stretched title", async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const css = fs.readFileSync("web/static/styles.css", "utf8");
    const frame = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="red"/></svg>');
    const title = '<div class="ar-vis-utm-selected-title"><strong>Verification — UTM</strong><span>2026-09-06T15:16:09Z</span></div>';
    const contents = `<div class="ar-vis-active-cam-frame"><img src="${frame}"></div><div class="ar-report-metrics"><div class="ar-report-metric">Confirmed</div></div><details class="ar-vis-card-details"><summary>Inspection details</summary></details>`;
    for (const width of [360, 560, 1000]) {
      await page.setViewportSize({ width: width + 40, height: 800 });
      for (const verification of [1, 2]) {
        // V1 has its title outside the evidence card; V2 has it inside.
        const body = verification === 1
          ? `${title}<div class="ar-vis-active-cam-card ar-vis-utm-confirmation-card">${contents}</div>`
          : `<div class="ar-vis-active-cam-card ar-vis-utm-confirmation-card">${title}${contents}</div>`;
        await page.setContent(`<style>${css}</style><body class="planning-live-body"><section class="ar-report-card ar-vis-utm-verification-card" style="width:${width}px;min-height:600px"><div class="ar-report-card-head">UTM Verification</div><div class="ar-report-card-body">${body}</div></section></body>`);
        await page.locator("img").evaluate(image => image.decode());
        const boxes = await page.evaluate(() => Object.fromEntries([
          ["title", ".ar-vis-utm-selected-title"], ["frame", ".ar-vis-active-cam-frame"], ["image", "img"],
        ].map(([key, selector]) => [key, document.querySelector(selector).getBoundingClientRect().toJSON()])));
        assert.ok(boxes.title.height < 65, `V${verification}/${width}: title consumed ${boxes.title.height}px`);
        assert.ok(boxes.frame.top - boxes.title.bottom < 30, `V${verification}/${width}: blank gap above frame`);
        assert.ok(boxes.image.top >= boxes.frame.top && boxes.image.bottom <= boxes.frame.bottom + 1,
          `V${verification}/${width}: image extends beyond frame (${JSON.stringify(boxes)})`);
        assert.ok(boxes.image.left >= boxes.frame.left && boxes.image.right <= boxes.frame.right + 1);
      }
    }
  } finally {
    await browser.close();
  }
});
