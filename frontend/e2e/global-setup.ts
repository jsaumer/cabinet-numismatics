import { request as playwrightRequest } from "@playwright/test";

// Runs once before the suite: claims a fresh stack with SETUP_CODE, or signs
// in to an already-claimed one, then saves the session as storageState so
// every spec starts signed in (playwright.config.ts wires this in). There is
// no sign-in page yet (that is stage 9), so this talks to the API directly.
//
// The request context sends no Sec-Fetch-Site header, so an explicit Origin
// is required for the cookie CSRF check (docs/specs/SPEC_0300.md section 4)
// once a session exists; setup and login themselves are anonymous and don't
// need it, but sending it does no harm.

const BASE_URL = process.env.BASE_URL ?? "http://localhost";
const CABINET_USER = process.env.CABINET_USER ?? "owner";
const CABINET_PASSWORD = process.env.CABINET_PASSWORD ?? "correct horse battery";
const SETUP_CODE = process.env.SETUP_CODE;

export const STORAGE_STATE_PATH = "e2e/.auth/storage-state.json";

export default async function globalSetup() {
  const context = await playwrightRequest.newContext({
    baseURL: BASE_URL,
    extraHTTPHeaders: { Origin: BASE_URL },
  });
  try {
    const state = await context.get("/api/auth/state");
    if (!state.ok()) {
      throw new Error(`GET /api/auth/state failed: ${state.status()} ${await state.text()}`);
    }
    const { setup_required: setupRequired } = await state.json();

    if (setupRequired) {
      if (!SETUP_CODE) {
        throw new Error(
          "The stack is unclaimed and SETUP_CODE is not set; export it before running the Playwright suite.",
        );
      }
      const setup = await context.post("/api/auth/setup", {
        data: { code: SETUP_CODE, username: CABINET_USER, password: CABINET_PASSWORD },
      });
      if (!setup.ok()) {
        throw new Error(`POST /api/auth/setup failed: ${setup.status()} ${await setup.text()}`);
      }
    } else {
      const login = await context.post("/api/auth/login", {
        data: { username: CABINET_USER, password: CABINET_PASSWORD },
      });
      if (!login.ok()) {
        throw new Error(`POST /api/auth/login failed: ${login.status()} ${await login.text()}`);
      }
    }

    await context.storageState({ path: STORAGE_STATE_PATH });
  } finally {
    await context.dispose();
  }
}
