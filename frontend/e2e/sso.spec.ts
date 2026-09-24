import { Browser, expect, Page, test } from "@playwright/test";

// Single sign-on in the browser (SPEC_0330 section 11, stage 5), against the
// mock provider (scripts/ci/mock_idp.py, from docker-compose.ci.yml) and the
// providers, linked identities, and trusted-header mode that
// scripts/ci/stack-smoke.sh's sso phase leaves configured. Skipped when
// MOCK_IDP_URL is unset (a stack without the mock).
//
// This file sorts after smoke.spec.ts, whose last two tests change the
// admin's password and username (and put them back), which revokes the
// suite's shared storageState session. So nothing here starts from it: the
// admin's pages sign in through the form (as auth.spec.ts does), and every
// sign-in round trip runs in a brand-new browser context with no storage at
// all, the way a visitor arrives. Nothing here changes the password or the
// username.

const BASE_URL = process.env.BASE_URL ?? "http://localhost";
const MOCK_IDP_URL = process.env.MOCK_IDP_URL;
const CABINET_USER = process.env.CABINET_USER ?? "owner";
const CABINET_PASSWORD = process.env.CABINET_PASSWORD ?? "correct horse battery";
const PROVIDER = "CI provider";

test.describe.configure({ mode: "serial" });
test.use({ storageState: { cookies: [], origins: [] } });
test.skip(!MOCK_IDP_URL, "MOCK_IDP_URL is unset: no mock provider to sign in through");

const dashboard = (page: Page) => page.getByRole("heading", { level: 1, name: "Dashboard" });

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(CABINET_USER);
  await page.getByLabel("Password").fill(CABINET_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(dashboard(page)).toBeVisible();
}

// See smoke.spec.ts: a fresh route's window may have lapsed, in which case
// the confirm-password dialog appears after the action and needs answering.
async function withPasswordConfirm(page: Page, act: () => Promise<void>) {
  await act();
  const dialog = page.getByRole("dialog", { name: "Confirm your password" });
  const appeared = await dialog
    .waitFor({ state: "visible", timeout: 3000 })
    .then(() => true)
    .catch(() => false);
  if (!appeared) return;
  await dialog.getByLabel("Password").fill(CABINET_PASSWORD);
  await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(dialog).toBeHidden();
}

async function visitor(browser: Browser, headers?: Record<string, string>) {
  const context = await browser.newContext({ baseURL: BASE_URL, extraHTTPHeaders: headers });
  return { context, page: await context.newPage() };
}

// The mock's authorize page: one button, then back to Cabinet.
async function approveAtMock(page: Page) {
  await expect(page).toHaveURL(/\/authorize\?/);
  await page.getByRole("button", { name: "Approve" }).click();
}

async function providerSignIn(page: Page) {
  await page.goto("/login");
  await page.getByRole("link", { name: `Sign in with ${PROVIDER}` }).click();
  await approveAtMock(page);
  await expect(dashboard(page)).toBeVisible();
}

test("Settings, Sign-in lists the provider, its callback URL, and the linked identity", async ({ page }) => {
  await signIn(page);
  await page.goto("/settings/signin");
  await expect(page.getByRole("heading", { level: 2, name: "Sign-in", exact: true })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: PROVIDER }).first()).toBeVisible();
  const callback = page.locator("code", { hasText: "/api/auth/oidc/callback" }).first();
  await expect(callback).toBeVisible();
  await expect(callback.locator("xpath=..").getByRole("button", { name: "Copy" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "ci-user-1" }).filter({ hasText: PROVIDER })).toBeVisible();
});

test("the sign-in page offers the providers and the proxy above the password", async ({ browser }) => {
  const { context, page } = await visitor(browser);
  await page.goto("/login");
  const provider = page.getByRole("link", { name: `Sign in with ${PROVIDER}` });
  await expect(provider).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in with GitHub" })).toBeVisible();
  const proxy = page.getByRole("button", { name: "Continue with the proxy's sign-in" });
  await expect(proxy).toBeVisible();
  const username = page.getByLabel("Username");
  await expect(username).toBeVisible();
  const [a, b, c] = await Promise.all([provider.boundingBox(), proxy.boundingBox(), username.boundingBox()]);
  expect(a!.y).toBeLessThan(b!.y);
  expect(b!.y).toBeLessThan(c!.y);
  await context.close();
});

test("signing in through the provider, then out", async ({ browser }) => {
  const { context, page } = await visitor(browser);
  await providerSignIn(page);
  await expect(page.getByText(/failed sign-in.*since your last visit/)).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await context.close();
});

test("confirming at the provider opens the window and replays nothing", async ({ browser }) => {
  const { context, page } = await visitor(browser);
  await providerSignIn(page);
  await page.goto("/settings/general");
  const retention = page.locator(".setting-row").filter({ hasText: "Empty the trash automatically" }).locator("select");
  await expect(retention).toBeEnabled();
  const before = await retention.inputValue();
  const other = before === "7" ? "90" : "7";

  // A single sign-on session never typed a password: the change asks first.
  await retention.selectOption(other);
  const dialog = page.getByRole("dialog", { name: "Confirm your password" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Confirm at your sign-in provider" }).click();
  await approveAtMock(page);

  await expect(page.getByText("Confirmed. Repeat the action you started.")).toBeVisible();
  await expect(page).toHaveURL(/\/settings\/general/);
  // Nothing was replayed on the way back (CR-20).
  await expect(retention).toHaveValue(before);

  // The window is open: the change goes through with no dialog, and back.
  await retention.selectOption(other);
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await expect(dialog).toHaveCount(0);
  await expect(retention).toHaveValue(other);
  await retention.selectOption(before);
  await expect(retention).toHaveValue(before);
  await expect(retention).toBeEnabled();
  await context.close();
});

test("the proxy's sign-in starts a trusted-header session", async ({ browser, request }) => {
  const minted = await request.get(`${MOCK_IDP_URL}/mint`);
  expect(minted.ok()).toBeTruthy();
  const { context, page } = await visitor(browser, { "X-authentik-jwt": (await minted.text()).trim() });
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue with the proxy's sign-in" }).click();
  await expect(dashboard(page)).toBeVisible();
  const origin = new URL(page.url()).origin;
  const me = await page.request.get("/api/auth/me", { headers: { Origin: origin } });
  expect(me.ok()).toBeTruthy();
  expect((await me.json()).auth_method).toBe("trusted_header");
  await context.close();
});

test("the trusted-header identity can be unlinked from Settings", async ({ page }) => {
  await signIn(page);
  await page.goto("/settings/signin");
  page.on("dialog", (d) => d.accept());
  const row = page.getByRole("row").filter({ hasText: "Trusted header" });
  await expect(row).toHaveCount(1);
  await withPasswordConfirm(page, () => row.getByRole("button", { name: "Unlink" }).click());
  await expect(row).toHaveCount(0);
  // The provider's identity stays.
  await expect(page.getByRole("row").filter({ hasText: "ci-user-1" }).filter({ hasText: PROVIDER })).toBeVisible();
});
