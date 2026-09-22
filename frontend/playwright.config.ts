import { defineConfig } from "@playwright/test";

import { STORAGE_STATE_PATH } from "./e2e/global-setup";

// Smoke tests against a running stack (docker compose up), not the dev server.
// BASE_URL points at the proxy: http://localhost by default, http://proxy from
// a container on the compose network. Cabinet needs a login (v0.30.0), so
// globalSetup claims or signs in once and every project starts from that
// saved session; CABINET_USER/CABINET_PASSWORD and, on a fresh stack,
// SETUP_CODE steer it. There is no sign-in page yet, so a spec that hits a
// "fresh" route confirms the password itself, through the request context.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
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
