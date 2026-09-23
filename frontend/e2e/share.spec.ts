import { expect, Page, test } from "@playwright/test";

// Settings -> Sharing end to end (SPEC_0320, stage 3 and 4): create a
// collection link, open it in a signed-out context with no storage state at
// all (a share visitor never runs the sign-in boot check, App.tsx routes
// /s/* before AuthProvider is even mounted), see a piece and no price on the
// page (values are off by default) and no cert number (show_certs is off by
// default too, stage 4 finding 10), turn show_certs on and see the number
// appear, revoke the link, and see the same page a stranger without the
// link would see.

const CABINET_PASSWORD = process.env.CABINET_PASSWORD ?? "correct horse battery";

const ITEM_COUNTRY = `Share test ${Date.now()}`;
const ITEM_DENOMINATION = "1 share test";
const ITEM_YEAR = "2026";
const CERT_SERVICE = "PCGS";
const CERT_NUMBER = `88${Date.now()}`;
const LINK_NAME = `E2E share ${Date.now()}`;

test.describe.configure({ mode: "serial" });

const acceptDialogs = (page: Page) => page.on("dialog", (dialog) => dialog.accept());

// Copied from smoke.spec.ts (see there for why): a "fresh" route's recent-
// password window may have lapsed, in which case the app's own confirm
// dialog appears after the action and needs answering before it retries.
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

async function deleteForGood(page: Page, url: string, country: string) {
  await page.goto(url);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page).toHaveURL(/\/collection$/);
  await page.goto("/trash");
  await withPasswordConfirm(page, () =>
    page.getByRole("row", { name: new RegExp(country) })
      .getByRole("button", { name: "delete for good" })
      .click(),
  );
}

test("a collection share link works for a signed-out visitor, then stops", async ({ page, browser }) => {
  // A piece for the link to show, with a cert number: show_certs (stage 4,
  // finding 10) needs one to prove it's held back, and cert_service to
  // prove show_grades still carries the service name on its own.
  await page.goto("/items/new");
  await page.getByLabel("Country *").fill(ITEM_COUNTRY);
  await page.getByLabel("Denomination *").fill(ITEM_DENOMINATION);
  await page.getByLabel("Year *").fill(ITEM_YEAR);
  await page.getByLabel("Cert service").fill(CERT_SERVICE);
  await page.getByLabel("Cert number").fill(CERT_NUMBER);
  await page.getByRole("button", { name: "Add item", exact: true }).click();
  await expect(page).toHaveURL(/\/items\/[0-9a-f-]{36}$/);
  const itemUrl = new URL(page.url()).pathname;

  await page.goto("/settings/sharing");
  // PUT /api/settings is fresh: the click opens the password dialog before
  // the switch can move, so click (not check) and confirm the state after.
  const sharing = page.getByLabel("Turn on sharing");
  await expect(sharing).toBeVisible();
  if (!(await sharing.isChecked())) {
    // A run that stopped short may have left it on; only click it on.
    await withPasswordConfirm(page, () => sharing.click());
  }
  await expect(sharing).toBeChecked();

  // A collection link, values left off (the default), through the create
  // form: POST /api/share-links is fresh.
  await page.getByLabel("Name").fill(LINK_NAME);
  await withPasswordConfirm(page, () => page.getByRole("button", { name: "Create link" }).click());
  const shareUrl = (await page.locator("code").textContent())?.trim();
  expect(shareUrl).toBeTruthy();

  // A brand-new browser context: no cookies, no storage state at all, the
  // way a stranger who was just sent the link would arrive.
  // The link is built from PUBLIC_ORIGINS[0], which is what a browser uses
  // to reach the stack; this test may reach it another way (BASE_URL through
  // the compose network), so open the link's path on the page's own origin.
  const sharePath = new URL(shareUrl as string).pathname;
  const origin = new URL(page.url()).origin;
  const guestContext = await browser.newContext();
  const guestPage = await guestContext.newPage();
  await guestPage.goto(origin + sharePath);

  await expect(guestPage.locator("header.site-header")).toContainText(LINK_NAME);
  await expect(guestPage.locator(".share-card").first()).toBeVisible();
  // No way back into the signed-in app from a share page.
  await expect(guestPage.locator("header.site-header nav a")).toHaveCount(0);
  // show_values defaults off: no price anywhere on the grid.
  await expect(guestPage.locator("body")).not.toContainText(/\$\d/);

  await guestPage.locator(".share-card").first().click();
  await expect(guestPage.locator(".share-piece")).toBeVisible();
  await expect(guestPage.locator("body")).not.toContainText(/\$\d/);
  // show_grades defaults on: the certification service shows.
  await expect(guestPage.locator("body")).toContainText(CERT_SERVICE);
  // show_certs defaults off: the cert number itself doesn't, even though
  // the service above it does.
  await expect(guestPage.locator("body")).not.toContainText(CERT_NUMBER);

  // Turn show_certs on from the row's Options panel: PATCH /api/share-links/
  // {id} is fresh (stage 4, finding 9).
  const row = page.getByRole("row", { name: new RegExp(LINK_NAME) });
  await row.getByRole("button", { name: "Options" }).click();
  // Scoped to the links table: the create form below repeats the same
  // toggle labels, so an unscoped getByLabel would match both.
  const linksTable = page.locator("table.estimates");
  const certsToggle = linksTable.getByLabel("Certification number");
  await expect(certsToggle).not.toBeChecked();
  await certsToggle.check();
  await withPasswordConfirm(page, () => linksTable.getByRole("button", { name: "Save" }).click());

  await guestPage.reload();
  await expect(guestPage.locator("body")).toContainText(CERT_NUMBER);

  // Revoke from the signed-in side: a native confirm, then DELETE (fresh).
  acceptDialogs(page);
  await withPasswordConfirm(page, () => row.getByRole("button", { name: "Revoke" }).click());
  await expect(row).toHaveCount(0);

  await guestPage.reload();
  await expect(guestPage.getByText("This link isn't active.")).toBeVisible();
  await guestContext.close();

  if (await page.getByLabel("Turn on sharing").isChecked()) {
    await withPasswordConfirm(page, () => page.getByLabel("Turn on sharing").click());
  }
  await expect(page.getByLabel("Turn on sharing")).not.toBeChecked();

  await deleteForGood(page, itemUrl, ITEM_COUNTRY);
});

test("creating a link while sharing is off shows the switch-it-on message", async ({ page }) => {
  await page.goto("/settings/sharing");
  await expect(page.getByLabel("Turn on sharing")).not.toBeChecked();

  await page.getByLabel("Name").fill(`E2E share off ${Date.now()}`);
  await page.getByRole("button", { name: "Create link" }).click();
  await expect(page.getByText("Switch sharing on in Settings first.")).toBeVisible();
});
