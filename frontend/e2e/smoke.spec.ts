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
  await expect(page.getByText("12.50 USD")).toBeVisible();
});

test("record a value by hand", async ({ page }) => {
  await page.goto(itemUrl);
  await page.getByLabel("Value", { exact: true }).fill("20");
  await page.getByRole("button", { name: "Record value" }).click();
  await expect(page.getByRole("cell", { name: "20.00 USD" })).toBeVisible();
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
