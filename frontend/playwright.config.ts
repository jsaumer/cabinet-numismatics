import { defineConfig } from "@playwright/test";

import { STORAGE_STATE_PATH } from "./e2e/global-setup";

// Smoke tests against a running stack (docker compose up), not the dev server.
// BASE_URL points at the proxy: http://localhost by default, http://proxy from
// a container on the compose network. Cabinet needs a login (v0.30.0), so
// globalSetup claims or signs in once and every project starts from that
// saved session; CABINET_USER/CABINET_PASSWORD and, on a fresh stack,
// SETUP_CODE steer it. A spec that hits a "fresh" route (the recent-password
// window) answers the app's own confirm-password dialog.
//
// workers: 1. Every spec shares one backend and one database, and a couple
// of things aren't safe run at once: smoke.spec.ts's restore test replaces
// the whole database mid-suite, and its two account tests at the end change
// the admin's password and username for a moment before putting them back.
// A second worker signing in concurrently during that moment would see
// "Wrong username or password." for no reason a person watching would
// understand. One worker also makes file order deterministic (Playwright
// runs files in the order it finds them, alphabetically here), which is how
// auth.spec.ts (no account mutations) finishes before smoke.spec.ts's
// account tests, themselves last in that file, ever start.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost",
    viewport: { width: 1280, height: 800 },
    trace: "retain-on-failure",
    storageState: STORAGE_STATE_PATH,
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
