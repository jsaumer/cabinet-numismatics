import { expect, Page, test } from "@playwright/test";

// One item, named uniquely so the tests can run against a stack that already
// holds data, and cleaned up (deleted for good) by the last step.
const COUNTRY = `E2E ${Date.now()}`;
const DENOMINATION = "1 smoke test";
const YEAR = "2026";
const TITLE = `${COUNTRY} ${DENOMINATION}, ${YEAR}`;

test.describe.configure({ mode: "serial" });

let itemUrl: string;

const acceptDialogs = (page: Page) => page.on("dialog", (dialog) => dialog.accept());

const CABINET_USER = process.env.CABINET_USER ?? "owner";
const CABINET_PASSWORD = process.env.CABINET_PASSWORD ?? "correct horse battery";

// global-setup.ts signs the whole suite in, but a "fresh" route (a recent
// password confirmation, docs/specs/SPEC_0300.md section 5) still needs its
// own 5-minute window per session. Run the action that reaches such a route
// (restore inspect and run, deleting for good, here); if the window has
// lapsed, the app's own confirm-password dialog appears (client.ts's req()
// caught the 403 and is waiting), so answer it and let the original action
// retry itself. Within the window (most calls after the first in a test),
// no dialog appears and this is a no-op.
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

test("the dashboard renders", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();
});

test("add an item and see it on its page", async ({ page }) => {
  await page.goto("/items/new");
  await page.getByLabel("Country *").fill(COUNTRY);
  await page.getByLabel("Denomination *").fill(DENOMINATION);
  await page.getByLabel("Year *").fill(YEAR);
  await page.getByLabel("Price paid").fill("12.50");
  await page.getByRole("button", { name: "Add item", exact: true }).click();

  await expect(page).toHaveURL(/\/items\/[0-9a-f-]{36}$/);
  itemUrl = new URL(page.url()).pathname;
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(TITLE);
  await expect(page.getByText("$12.50")).toBeVisible();
});

test("record a value by hand", async ({ page }) => {
  await page.goto(itemUrl);
  await page.getByLabel("Value", { exact: true }).fill("20");
  await page.getByRole("button", { name: "Record value" }).click();
  await expect(page.getByRole("cell", { name: "$20.00" })).toBeVisible();

  // A typed-in value can be taken back.
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByLabel("Value", { exact: true }).fill("21");
  await page.getByRole("button", { name: "Record value" }).click();
  const mistake = page.getByRole("row", { name: /\$21\.00/ });
  await expect(mistake).toBeVisible();
  await mistake.getByRole("button", { name: "delete" }).click();
  await expect(mistake).toHaveCount(0);
  await expect(page.getByRole("cell", { name: "$20.00" })).toBeVisible();
});

// Needs an item, so it sits after the one above: an empty collection shows the
// "nothing to report yet" page instead of the grid.
test("the dashboard can be rearranged, and put back", async ({ page }) => {
  acceptDialogs(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Edit dashboard" }).click();
  await page.getByRole("button", { name: "Add widget" }).click();
  await page.locator(".import-source", { hasText: "Recent additions" }).click();

  const earlier = page.getByRole("button", { name: "Move Recent additions earlier" });
  await expect(earlier).toBeVisible();
  await earlier.click();
  await expect(page.locator(".dash-live")).toContainText("moved to position 11 of 12");

  // And by dragging, one chart over its neighbour in the same row. The cards
  // reorder under the pointer mid-drag, and the release still has to land.
  const handle = page.getByRole("button", { name: "Move Estimated value by tag", exact: true });
  await handle.evaluate((el) => el.scrollIntoView({ block: "center" }));
  const from = (await handle.boundingBox())!;
  const to = (await page
    .getByRole("button", { name: "Move Estimated value by country", exact: true })
    .boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 10 });
  await page.mouse.up();
  await expect(page.locator(".dash-live")).toContainText("Estimated value by tag moved to position 4 of 12");

  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Edit dashboard" })).toBeVisible();

  // Saved on the server, so it survives a reload.
  await page.reload();
  await expect(page.getByRole("heading", { level: 2, name: "Recent additions" })).toBeVisible();

  await page.getByRole("button", { name: "Edit dashboard" }).click();
  await page.getByRole("button", { name: "Reset to default" }).click();
  await expect(page.getByRole("button", { name: "Edit dashboard" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Recent additions" })).toHaveCount(0);
});

test("entering it again warns about the duplicate", async ({ page }) => {
  await page.goto("/items/new");
  await page.getByLabel("Country *").fill(COUNTRY);
  await page.getByLabel("Denomination *").fill(DENOMINATION);
  await page.getByLabel("Year *").fill(YEAR);
  const warning = page.locator(".dup-warning");
  await expect(warning).toContainText("Already in the collection?");
  await expect(warning.getByRole("link", { name: TITLE.replace(",", "") })).toBeVisible();
  await expect(warning).toContainText("same country, denomination, year, and mint mark");
});

test("a generated checklist fills itself from what's owned", async ({ page }) => {
  acceptDialogs(page);
  await page.goto("/checklists");
  const form = page.locator("form", { hasText: "First year" });
  await form.getByLabel("Country").fill(COUNTRY);
  await form.getByLabel("Denomination").fill(DENOMINATION);
  await form.getByLabel("First year").fill("2025");
  await form.getByLabel("Last year").fill("2027");
  await form.getByRole("button", { name: "Generate" }).click();

  const card = page.locator(".card", { hasText: `${COUNTRY} ${DENOMINATION} 2025–2027` });
  await expect(card).toContainText("1 / 3 · 33%");
  await expect(card.getByRole("link", { name: YEAR, exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Delete" }).click();
  await expect(card).toHaveCount(0);
});

test("the collection finds it by search", async ({ page }) => {
  await page.goto(`/collection?q=${encodeURIComponent(COUNTRY)}`);
  const row = page.locator("table.items tbody tr", { hasText: COUNTRY }).first();
  await expect(row).toContainText(DENOMINATION);
  await row.getByText(COUNTRY).click(); // rows open the item on click
  await expect(page).toHaveURL(itemUrl);
});

test("trash it, restore it, then delete it for good", async ({ page }) => {
  acceptDialogs(page);
  await page.goto(itemUrl);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page).toHaveURL(/\/collection$/);

  await page.goto("/trash");
  const row = page.getByRole("row", { name: new RegExp(COUNTRY) });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "restore" }).click();
  await expect(page.getByText("Restored 1 item to the collection.")).toBeVisible();

  await page.goto(itemUrl);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(TITLE);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.goto("/trash");
  // deleting for good is admin, fresh (already-trashed items too).
  await withPasswordConfirm(page, () =>
    page.getByRole("row", { name: new RegExp(COUNTRY) })
      .getByRole("button", { name: "delete for good" })
      .click(),
  );
  await expect(page.getByText("Deleted 1 item for good.")).toBeVisible();

  await page.goto(itemUrl);
  await expect(page.locator("p.error")).toBeVisible();
});

// These two make and remove their own items, under names the tests above don't match.
// A select inside its label, found by how the label's text starts.
const selectIn = (page: Page, label: RegExp) =>
  page.locator("label.field", { hasText: label }).locator("select");

async function deleteForGood(page: Page, url: string, country: string) {
  await page.goto(url);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page).toHaveURL(/\/collection$/);
  await page.goto("/trash");
  // DELETE /api/items/{id}?permanent=true is admin, fresh.
  await withPasswordConfirm(page, () =>
    page.getByRole("row", { name: new RegExp(country) })
      .getByRole("button", { name: "delete for good" })
      .click(),
  );
  await expect(page.getByText("Deleted 1 item for good.")).toBeVisible();
}

test("a note with a radar serial number gets its badge", async ({ page }) => {
  acceptDialogs(page);
  const country = `E2E note ${Date.now()}`;
  await page.goto("/items/new");
  await selectIn(page, /^Type/).selectOption("note");
  await page.getByLabel("Country *").fill(country);
  await page.getByLabel("Denomination *").fill("1 dollar");
  await page.getByLabel("Year *").fill("1957");
  await page.getByLabel("Serial number", { exact: true }).fill("12344321");
  await page.getByLabel("Width (mm)").fill("156");
  await page.getByLabel("Height (mm)").fill("66.5");
  await page.getByLabel("Printer", { exact: true }).fill("BEP");
  await page.getByRole("button", { name: "Add item", exact: true }).click();

  await expect(page).toHaveURL(/\/items\/[0-9a-f-]{36}$/);
  const url = new URL(page.url()).pathname;
  await expect(page.locator("dl.facts .badge.trait")).toHaveText(/^radar$/i);
  // The note details, in the item page's Physical group.
  await expect(page.getByText("156 × 66.5 mm")).toBeVisible();
  await expect(page.getByText("BEP", { exact: true })).toBeVisible();

  await deleteForGood(page, url, country);
});

test("a wishlist coin shows its target price", async ({ page }) => {
  acceptDialogs(page);
  const country = `E2E wish ${Date.now()}`;
  await page.goto("/items/new");
  await page.getByLabel("Country *").fill(country);
  await page.getByLabel("Denomination *").fill("1 cent");
  await page.getByLabel("Year *").fill("1909");
  await selectIn(page, /^Status/).selectOption("wishlist");
  await page.getByLabel("Target price").fill("1000");
  await selectIn(page, /^Priority/).selectOption("1");
  await page.getByRole("button", { name: "Add item", exact: true }).click();

  await expect(page).toHaveURL(/\/items\/[0-9a-f-]{36}$/);
  const url = new URL(page.url()).pathname;
  const target = page
    .locator("dl.facts > div")
    .filter({ has: page.locator("dt", { hasText: /^Target$/ }) });
  await expect(target).toContainText("$1,000.00");

  await deleteForGood(page, url, country);
});

test("the security headers are set and nothing trips the policy", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (/content security policy/i.test(message.text())) violations.push(message.text());
  });
  const response = await page.goto("/");
  const headers = response!.headers();
  expect(headers["content-security-policy"]).toContain("script-src 'self'");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["x-frame-options"]).toBe("SAMEORIGIN");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  for (const path of ["/collection", "/items/new", "/items/run", "/checklists", "/pricing", "/settings"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("link", { name: "Collection" }).first()).toBeVisible();
  }
  expect(violations).toEqual([]);
});

test("every Settings section renders, with the version", async ({ page }) => {
  await page.goto("/settings");
  for (const name of [
    "General",
    "Price sources",
    "Cached market data",
    "Backups",
    "Alerts & metrics",
    "About",
  ]) {
    await expect(page.getByRole("heading", { level: 2, name, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("link", { name: /^\d+\.\d+\.\d+$/ })).toBeVisible();
});

test("an undated piece takes ND with no year", async ({ page }) => {
  acceptDialogs(page);
  const country = `E2E nd ${Date.now()}`;
  await page.goto("/items/new");
  await page.getByLabel("Country *").fill(country);
  await page.getByLabel("Denomination *").fill("1 notgeld");
  await page.getByLabel("ND (no date on the piece)").check();
  await page.getByRole("button", { name: "Add item", exact: true }).click();

  await expect(page).toHaveURL(/\/items\/[0-9a-f-]{36}$/);
  const url = new URL(page.url()).pathname;
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`${country} 1 notgeld, ND`);

  await deleteForGood(page, url, country);
});

test("a silver piece counts toward the stack", async ({ page }) => {
  acceptDialogs(page);
  const country = `E2E stack ${Date.now()}`;
  await page.goto("/items/new");
  await page.getByLabel("Country *").fill(country);
  await page.getByLabel("Denomination *").fill("1 dollar");
  await page.getByLabel("Year *").fill("1986");
  await page.getByLabel("Composition", { exact: true }).fill("Silver");
  await page.getByLabel("Weight (g)").fill("31.1035");
  await page.getByLabel("Fineness", { exact: true }).fill("0.999");
  await page.getByLabel("Quantity", { exact: true }).fill("2");
  await page.getByLabel("Price paid").fill("70");
  await page.getByRole("button", { name: "Add item", exact: true }).click();

  await expect(page).toHaveURL(/\/items\/[0-9a-f-]{36}$/);
  const url = new URL(page.url()).pathname;

  // Assert on ounces and cost, computed from what was entered: no network call.
  await page.goto("/stack");
  await expect(page.getByRole("heading", { level: 2, name: "Silver" })).toBeVisible();
  const row = page.getByRole("row", { name: new RegExp(country) });
  await expect(row).toContainText("2"); // fine oz, ~2 troy oz of .999 fine silver
  await expect(row).toContainText("$70.00"); // cost basis of the lot

  await deleteForGood(page, url, country);
});

// Last on purpose: a restore replaces the whole collection, so a failure here
// can't disturb the tests above. Restoring a backup taken a moment earlier
// leaves everything as it was.
test("restore the backup just taken", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/settings");
  await page.getByRole("button", { name: "Back up now" }).click();
  const written = page.getByText(/^Backup written: cabinet-backup-/);
  await expect(written).toBeVisible({ timeout: 60_000 });
  const name = (await written.innerText()).match(/cabinet-backup-[\w-]+\.zip\.age/)![0];

  // POST /api/restore/inspect is a fresh route: the confirm-password dialog
  // answers it the first time it's needed.
  await withPasswordConfirm(page, () =>
    page
      .getByRole("row")
      .filter({ has: page.getByRole("link", { name, exact: true }) })
      .getByRole("button", { name: "Restore…" })
      .click(),
  );
  await expect(page.getByRole("columnheader", { name: "This archive" })).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByRole("columnheader", { name: "Here now" })).toBeVisible();

  // POST /api/restore/{id}/run is fresh too; the window from above usually
  // still covers it, so no dialog is expected here, but withPasswordConfirm
  // answers one if it appears.
  const run = page.getByRole("button", { name: "Restore this archive" });
  await expect(run).toBeDisabled();
  await page.getByLabel("Type RESTORE to confirm").fill("RESTORE");
  await withPasswordConfirm(page, () => run.click());

  await expect(page.getByText(/^Restore complete:/)).toBeVisible({ timeout: 120_000 });
  // The page reloaded its data: the safety backup is in the list.
  await expect(page.getByText("before restore").first()).toBeVisible({ timeout: 30_000 });
});

// These two change the admin's password and username, which (per
// SPEC_0300.md section 5) signs out every OTHER session: that includes the
// one session baked into e2e/.auth/storage-state.json, which is what every
// other test's page fixture is freshly loaded from (Playwright reads that
// file for each new context; it isn't the live cookie of any running page).
// So the moment the first test here rotates its own session, that stored
// session dies for anyone else who starts from it, including the second
// test in this very describe. Both therefore sign themselves in through the
// form first, exactly as the task calls for ("a separate browser context
// that signs in itself"), rather than trusting the ambient storageState.
// They run last, after the restore above, and in their own serial,
// no-retry describe: a retry that assumed the password was still
// CABINET_PASSWORD after a first attempt left it as something else would
// only compound the problem. playwright.config.ts's workers: 1 keeps
// everything else from making a request while the password is briefly
// something else. A restore never touches cabinet_auth, so running after
// one is no different from running before it.
test.describe("account changes (isolated, self-reverting)", () => {
  test.describe.configure({ mode: "serial", retries: 0 });

  async function signIn(page: Page, username: string, password: string) {
    await page.goto("/login");
    // The first of these two tests gets a fresh page fixture that's often
    // still signed in from the shared storageState (nothing has rotated it
    // yet): /login then bounces straight back to "/", with nothing to fill
    // in. The second test's fresh page never is (the first just revoked
    // that stored session), so it sees the form.
    const usernameField = page.getByLabel("Username");
    const dashboard = page.getByRole("heading", { level: 1, name: "Dashboard" });
    await expect(usernameField.or(dashboard)).toBeVisible();
    if (await usernameField.isVisible().catch(() => false)) {
      await usernameField.fill(username);
      await page.getByLabel("Password").fill(password);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(dashboard).toBeVisible();
    }
  }

  test("changing the password revokes tokens, and can be changed back", async ({ page }) => {
    await signIn(page, CABINET_USER, CABINET_PASSWORD);
    await page.goto("/settings");
    const tokenName = `e2e-pw-token-${Date.now()}`;
    const tokenForm = page.locator("form").filter({ has: page.getByRole("button", { name: "Create token" }) });
    await tokenForm.getByLabel("Name").fill(tokenName);
    await tokenForm.getByRole("button", { name: "Create token" }).click();
    // Creating a token is fresh too; the window from the restore test just
    // above usually still covers it, but answer the dialog if it appears.
    const dialog = page.getByRole("dialog", { name: "Confirm your password" });
    if (await dialog.waitFor({ state: "visible", timeout: 3000 }).then(() => true).catch(() => false)) {
      await dialog.getByLabel("Password").fill(CABINET_PASSWORD);
      await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
    }
    await expect(page.getByText(`${tokenName} (read): copy it now, it won't be shown again.`)).toBeVisible();

    const passwordForm = page.locator("form").filter({ has: page.getByRole("button", { name: "Change password" }) });
    async function changePassword(current: string, next: string) {
      await passwordForm.getByLabel("Current password").fill(current);
      await passwordForm.getByLabel("New password", { exact: true }).fill(next);
      await passwordForm.getByLabel("Confirm new password").fill(next);
      await passwordForm.getByRole("button", { name: "Change password" }).click();
    }

    const temp = `${CABINET_PASSWORD} temp`;
    await changePassword(CABINET_PASSWORD, temp);
    await expect(page.getByText(/^Password changed\./)).toBeVisible();
    await expect(page.getByText(new RegExp(`Revoked: .*${tokenName}`))).toBeVisible();

    await changePassword(temp, CABINET_PASSWORD);
    await expect(page.getByText(/^Password changed\./)).toBeVisible();
  });

  test("changing the username, and back", async ({ page }) => {
    // The password test just above rotated and restored the session it
    // used, but that killed the storageState session every fresh page
    // fixture (this one included) would otherwise start from: sign in again.
    await signIn(page, CABINET_USER, CABINET_PASSWORD);
    await page.goto("/settings");
    const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Change username" }) });
    async function changeUsername(username: string) {
      await form.getByLabel("Current password").fill(CABINET_PASSWORD);
      await form.getByLabel("New username").fill(username);
      await form.getByRole("button", { name: "Change username" }).click();
    }

    const temp = `${CABINET_USER}-e2e`;
    await changeUsername(temp);
    await expect(page.getByText("Username changed.")).toBeVisible();

    await changeUsername(CABINET_USER);
    await expect(page.getByText("Username changed.")).toBeVisible();
  });
});
