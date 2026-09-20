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
  await page.getByRole("row", { name: new RegExp(COUNTRY) })
    .getByRole("button", { name: "delete for good" })
    .click();
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
  await page.getByRole("row", { name: new RegExp(country) })
    .getByRole("button", { name: "delete for good" })
    .click();
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
  await page.getByRole("button", { name: "Add item", exact: true }).click();

  await expect(page).toHaveURL(/\/items\/[0-9a-f-]{36}$/);
  const url = new URL(page.url()).pathname;
  await expect(page.locator("dl.facts .badge.trait")).toHaveText(/^radar$/i);

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

// Last on purpose: a restore replaces the whole collection, so a failure here
// can't disturb the tests above. Restoring a backup taken a moment earlier
// leaves everything as it was.
test("restore the backup just taken", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/settings");
  await page.getByRole("button", { name: "Back up now" }).click();
  const written = page.getByText(/^Backup written: cabinet-backup-/);
  await expect(written).toBeVisible({ timeout: 60_000 });
  const name = (await written.innerText()).match(/cabinet-backup-[\w-]+\.zip/)![0];

  await page
    .getByRole("row")
    .filter({ has: page.getByRole("link", { name, exact: true }) })
    .getByRole("button", { name: "Restore…" })
    .click();
  await expect(page.getByRole("columnheader", { name: "This archive" })).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByRole("columnheader", { name: "Here now" })).toBeVisible();

  const run = page.getByRole("button", { name: "Restore this archive" });
  await expect(run).toBeDisabled();
  await page.getByLabel("Type RESTORE to confirm").fill("RESTORE");
  await run.click();

  await expect(page.getByText(/^Restore complete:/)).toBeVisible({ timeout: 120_000 });
  // The page reloaded its data: the safety backup is in the list.
  await expect(page.getByText("before restore").first()).toBeVisible({ timeout: 30_000 });
});
