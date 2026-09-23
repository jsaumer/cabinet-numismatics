import { expect, Page, test } from "@playwright/test";

// Sign-in, sign-out, the confirm-password dialog, and the Account section
// (SPEC_0300 section 9's new Playwright tests). Every test here uses its own
// signed-out browser context (test.use below), never the suite's default
// storageState (global-setup.ts): that shared session belongs to
// smoke.spec.ts and every other spec, and a couple of these actions (ending
// a session, changing a token) would otherwise disturb it. Nothing in this
// file changes the admin's password or username, so it's safe to run
// alongside smoke.spec.ts in another worker; see smoke.spec.ts for the two
// tests that do change them (and put them back), kept there so they run
// after everything else in that file, restore included.

const CABINET_USER = process.env.CABINET_USER ?? "owner";
const CABINET_PASSWORD = process.env.CABINET_PASSWORD ?? "correct horse battery";

test.use({ storageState: { cookies: [], origins: [] } });

async function signIn(page: Page, username = CABINET_USER, password = CABINET_PASSWORD) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();
}

test("visiting a page while signed out goes to sign-in, with next", async ({ page }) => {
  await page.goto("/collection");
  await expect(page).toHaveURL(/\/login\?next=%2Fcollection/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("a wrong password, then the right one, shows the failed-attempts notice", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(CABINET_USER);
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Wrong username or password.")).toBeVisible();

  await page.getByLabel("Password").fill(CABINET_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();

  await expect(page.getByText(/failed sign-in.*since your last visit/)).toBeVisible();
  await page.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByText(/failed sign-in.*since your last visit/)).toHaveCount(0);
});

test("signing out clears the session; back navigation shows no collection data", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.goBack();
  // The page that used to be the dashboard now redirects straight back to
  // sign-in: nothing from the collection renders from a cached copy.
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toHaveCount(0);
});

test("a photo URL fetched from a signed-out context is refused", async ({ page }) => {
  const response = await page.request.get("/photos/does-not-exist.jpg");
  expect(response.status()).toBe(401);
});

test("the confirm dialog appears once for a fresh route, not again within the window", async ({ page }) => {
  await signIn(page);
  await page.goto("/collection");

  // First fresh action of a brand-new session: the dialog answers it.
  const [csv] = await Promise.all([
    page.waitForEvent("download"),
    (async () => {
      await page.getByRole("button", { name: "Export / import" }).click();
      await page.getByRole("menuitem", { name: "Export as CSV" }).click();
      const dialog = page.getByRole("dialog", { name: "Confirm your password" });
      await expect(dialog).toBeVisible();
      await dialog.getByLabel("Password").fill(CABINET_PASSWORD);
      await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
      await expect(dialog).toBeHidden();
    })(),
  ]);
  expect(csv.suggestedFilename()).toMatch(/\.csv$/);

  // Still within the 5-minute window: backup.zip downloads without asking again.
  await page.goto("/settings/backups");
  const [backup] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download backup" }).click(),
  ]);
  expect(backup.suggestedFilename()).toMatch(/\.zip\.age$/);
  await expect(page.getByRole("dialog", { name: "Confirm your password" })).toHaveCount(0);
});

test("an API token is shown once, then revoked", async ({ page }) => {
  await signIn(page);
  await page.goto("/settings/account");

  const name = `e2e-token-${Date.now()}`;
  const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Create token" }) });
  await form.getByLabel("Name").fill(name);
  await form.getByRole("button", { name: "Create token" }).click();

  // A "fresh" route: the dialog may appear for this brand-new session.
  const dialog = page.getByRole("dialog", { name: "Confirm your password" });
  if (await dialog.waitFor({ state: "visible", timeout: 3000 }).then(() => true).catch(() => false)) {
    await dialog.getByLabel("Password").fill(CABINET_PASSWORD);
    await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
  }

  await expect(page.getByText(`${name} (read): copy it now, it won't be shown again.`)).toBeVisible();
  const tokenValue = await page.locator("code").filter({ hasText: /^cabinet_/ }).innerText();
  expect(tokenValue).toMatch(/^cabinet_[a-z2-7]{10}_[A-Za-z0-9_-]{43}$/);

  const row = page.getByRole("row", { name });
  await row.getByRole("button", { name: "Revoke" }).click();
  await expect(row).toHaveCount(0);
});

test("ending another session", async ({ page, browser }) => {
  const marker = `E2E session ${Date.now()}`;
  const other = await browser.newContext({ userAgent: marker });
  const otherPage = await other.newPage();
  await signIn(otherPage);
  await other.close();

  await signIn(page);
  await page.goto("/settings/account");
  const row = page.getByRole("row", { name: new RegExp(marker) });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "End" }).click();

  // Ending another session is fresh too (SPEC_0300.md section 3): a
  // brand-new session hasn't confirmed yet, so the dialog answers it.
  const dialog = page.getByRole("dialog", { name: "Confirm your password" });
  if (await dialog.waitFor({ state: "visible", timeout: 3000 }).then(() => true).catch(() => false)) {
    await dialog.getByLabel("Password").fill(CABINET_PASSWORD);
    await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
  }
  await expect(row).toHaveCount(0);
});

test("deleting a photo asks for the password, then removes it", async ({ page }) => {
  // A fresh session has no recent-password window, and deleting a photo is
  // for good (stage 12): the gallery's own confirm, then the password dialog.
  await signIn(page);
  const origin = { Origin: new URL(page.url()).origin };
  const item = await page.request.post("/api/items", {
    headers: origin,
    data: { type: "coin", country: "Photo delete", denomination: "1 test", year: 2026 },
  });
  expect(item.status()).toBe(201);
  const id = (await item.json()).id as string;
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
    "base64",
  );
  const upload = await page.request.post(`/api/items/${id}/photos`, {
    headers: origin,
    multipart: { file: { name: "p.png", mimeType: "image/png", buffer: png } },
  });
  expect(upload.status()).toBe(201);

  await page.goto(`/items/${id}`);
  await expect(page.locator(".photo-card")).toHaveCount(1);
  page.once("dialog", (dialog) => dialog.accept()); // "Delete this photo?"
  await page.getByTitle("Delete photo").click();
  const confirm = page.getByRole("dialog", { name: "Confirm your password" });
  await expect(confirm).toBeVisible();
  await confirm.getByLabel("Password").fill(CABINET_PASSWORD);
  await confirm.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.locator(".photo-card")).toHaveCount(0);

  // Inside the window now, so deleting the item for good needs no dialog.
  const gone = await page.request.delete(`/api/items/${id}?permanent=true`, { headers: origin });
  expect(gone.status()).toBe(204);
});
