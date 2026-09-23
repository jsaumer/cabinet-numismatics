// Captures the README screenshots, each page in dark and in light.
// Run inside the Playwright image; see README.md in this folder.
//   node capture.cjs signin            the sign-in page only, signed out
//   node capture.cjs settings          the Settings pages only (capture them first)
//   node capture.cjs rest <item-id>    collection, dashboard, and the item page
//
// Cabinet needs a sign-in (v0.30.0): "settings" and "rest" sign in through
// the sign-in form itself, once per theme (a fresh browser context each
// time, so there's no session to reuse), before navigating anywhere else.
// CABINET_USER / CABINET_PASSWORD name the admin to sign in as (defaults
// match the stack the README's regeneration steps set up).
const { chromium } = require("/app/node_modules/@playwright/test");

const CABINET_USER = process.env.CABINET_USER ?? "owner";
const CABINET_PASSWORD = process.env.CABINET_PASSWORD ?? "correct horse battery";

const [mode, itemId] = process.argv.slice(2);
const pages =
  mode === "signin"
    ? [["signin", "/login"]]
    : mode === "settings"
      ? [
          ["settings-backups", "/settings/backups"],
          ["settings-general", "/settings/general"],
        ]
      : [
          ["collection", "/collection"],
          ["dashboard", "/"],
          ["item-detail", `/items/${itemId}`],
        ];

// Cabinet runs behind https in real use, where the insecure-connection
// warning never shows; the capture container only reaches the proxy over
// plain http. Chromium's own "--unsafely-treat-insecure-origin-as-secure"
// flag is meant for exactly this, but does not take effect for a plain
// hostname in the Chromium build this image ships (confirmed with an
// isolated repro: the flag left window.isSecureContext false for a
// deliberately fake, non-loopback host, with or without a fresh profile).
// What Chromium always treats as secure with no flag, per the same spec
// that flag is for, is a "localhost" origin (loopback is exempt
// unconditionally). "--host-resolver-rules" resolves that hostname straight
// to the proxy container over the compose network, so the browser connects
// to the right place while its address bar (and window.isSecureContext)
// says "localhost".
const ORIGIN = "http://localhost";

async function signIn(page) {
  await page.goto(`${ORIGIN}/login`);
  await page.getByLabel("Username").fill(CABINET_USER);
  await page.getByLabel("Password").fill(CABINET_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(`${ORIGIN}/`);
}

(async () => {
  const browser = await chromium.launch({
    args: ["--host-resolver-rules=MAP localhost proxy"],
  });
  for (const theme of ["dark", "light"]) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    // Cabinet keeps the chosen theme in localStorage; dark is its default.
    await context.addInitScript((t) => localStorage.setItem("theme", t), theme);
    const page = await context.newPage();
    if (mode !== "signin") {
      await signIn(page);
    }
    for (const [name, path] of pages) {
      await page.goto(`${ORIGIN}${path}`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `/out/${name}-${theme}.png` });
      console.log(`${name}-${theme}.png`);
    }
    await context.close();
  }
  await browser.close();
})();
