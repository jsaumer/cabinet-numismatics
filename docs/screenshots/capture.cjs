// Captures the README screenshots, each page in dark and in light.
// Run inside the Playwright image; see README.md in this folder.
//   node capture.cjs settings          the Settings page only (capture it first)
//   node capture.cjs rest <item-id>    collection, dashboard, and the item page
const { chromium } = require("/app/node_modules/@playwright/test");

const [mode, itemId] = process.argv.slice(2);
const pages =
  mode === "settings"
    ? [["settings", "/settings"]]
    : [
        ["collection", "/collection"],
        ["dashboard", "/"],
        ["item-detail", `/items/${itemId}`],
      ];

(async () => {
  const browser = await chromium.launch();
  for (const theme of ["dark", "light"]) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    // Cabinet keeps the chosen theme in localStorage; dark is its default.
    await context.addInitScript((t) => localStorage.setItem("theme", t), theme);
    const page = await context.newPage();
    for (const [name, path] of pages) {
      await page.goto(`http://proxy${path}`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `/out/${name}-${theme}.png` });
      console.log(`${name}-${theme}.png`);
    }
    await context.close();
  }
  await browser.close();
})();
