import AxeBuilder from "@axe-core/playwright";
import { expect, Page, test } from "@playwright/test";

// The first screens a new owner meets, and the form that used to lose work.
//
// The suite's stack isn't empty by the time this runs, and the demo
// collection only loads into an empty one, so the two tests about an empty
// collection answer a few requests themselves (the counts, the demo's
// routes): what they prove is the page. Loading and removing the demo for
// real, against Postgres, is scripts/ci/stack-smoke.sh's `demo` step, and
// backend/tests/test_demo.py covers its rules.

// Several tests answer a request by fetching the real one and changing it; a
// page still loading when its test ends would otherwise fail the next test.
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

const DEMO_LOADED = {
  items: 17,
  photos: { state: "done", total: 22, fetched: 22, failed: 0 },
};
const NO_DEMO = { items: 0, photos: { state: "idle", total: 0, fetched: 0, failed: 0 } };

/** The collection's counts as the server gave them, with every one zero. */
async function emptyCollection(page: Page) {
  await page.route("**/api/stats/collection*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    for (const key of Object.keys(body.counts)) body.counts[key] = 0;
    await route.fulfill({ response, json: body });
  });
  await page.route("**/api/items?*", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { items: [], total: 0, limit: 50, offset: 0 } });
  });
}

test("an address PUBLIC_ORIGINS doesn't name gets a page that says so, with the value to set", async ({ page }) => {
  // What the gate answers a signed-in browser whose address isn't on the
  // list: a port left out of PUBLIC_ORIGINS still loads the page (nginx
  // matches the name alone), and then every request is refused. The page
  // used to say Cabinet wasn't answering yet, and to wait forever.
  await page.route("**/api/auth/state", (route) =>
    route.fulfill({ status: 403, json: { detail: "Cross-site request refused." } }),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Cabinet refused this address" })).toBeVisible();
  await expect(page.locator(".auth-card")).toContainText("PUBLIC_ORIGINS");
  await expect(page.locator(".refused-origin")).toHaveText(new URL(page.url()).origin);
  await expect(page).toHaveTitle("Wrong address · Cabinet");
  await expect(page.getByText("isn't answering yet")).toHaveCount(0);
  // It is a page of its own, outside the ones a11y.spec.ts visits.
  const scan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(scan.violations.map((v) => v.id)).toEqual([]);
});

test("an empty collection offers three ways to start, and no red box", async ({ page }) => {
  await emptyCollection(page);
  await page.goto("/");
  const welcome = page.getByRole("region", { name: "Welcome to Cabinet" });
  await expect(welcome).toBeVisible();
  // One "add" destination: the quick add, as the header's button.
  await expect(welcome.getByRole("link", { name: "Add a piece" })).toHaveAttribute("href", "/items/add");
  await expect(welcome.getByRole("link", { name: "Import a collection" })).toHaveAttribute("href", "/import");
  await expect(welcome.getByRole("button", { name: "Load the demo collection" })).toBeVisible();

  // The checklist is its own, neutral card under it, and no longer says the
  // collection is empty: the welcome state did.
  const checklist = page.locator(".setup-card");
  await expect(checklist.getByRole("heading", { name: "Before you rely on it" })).toBeVisible();
  await expect(checklist).not.toContainText("The collection is empty");
  await expect(checklist).toContainText("Cabinet is for private networks");
  const border = await checklist.evaluate((el) => getComputedStyle(el).borderTopColor);
  const cardBorder = await welcome
    .locator(".welcome-action")
    .first()
    .evaluate((el) => getComputedStyle(el).borderTopColor);
  expect(border).toBe(cardBorder);

  // The collection page says the same thing, where it used to offer no link.
  await page.goto("/collection");
  await expect(page.getByRole("region", { name: "Welcome to Cabinet" })).toBeVisible();
});

test("the demo collection loads from one button", async ({ page }) => {
  await emptyCollection(page);
  let loaded = false;
  await page.route("**/api/demo", async (route) => {
    if (route.request().method() === "POST") {
      loaded = true;
      await route.fulfill({ status: 201, json: { ...DEMO_LOADED, photos: { ...DEMO_LOADED.photos, state: "idle" } } });
    } else {
      await route.fulfill({ json: loaded ? DEMO_LOADED : NO_DEMO });
    }
  });
  await page.goto("/");
  const counts = page.waitForRequest("**/api/stats/collection*");
  await page.getByRole("button", { name: "Load the demo collection" }).click();
  await expect.poll(() => loaded).toBe(true);
  // The page asks for the collection again once the demo is there.
  await counts;
});

test("the demo says what it is, can be kept, and is removed in one step", async ({ page }) => {
  let removed = false;
  await page.route("**/api/demo", async (route) => {
    if (route.request().method() === "DELETE") {
      removed = true;
      await route.fulfill({ json: { removed: 17 } });
    } else {
      await route.fulfill({ json: removed ? NO_DEMO : DEMO_LOADED });
    }
  });
  await page.goto("/collection");
  const notice = page.locator(".demo-notice");
  await expect(notice).toContainText("This is the demo collection.");

  // Kept: gone from the page in this browser, and still gone after a reload.
  await notice.getByRole("button", { name: "Keep it for now" }).click();
  await expect(notice).toBeHidden();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(notice).toBeHidden();

  // Settings still offers the removal, which asks before it deletes.
  await page.goto("/settings/general");
  const row = page.locator(".setting-row", { hasText: "Demo collection" });
  await expect(row).toContainText("17 demo pieces loaded");
  page.once("dialog", (dialog) => {
    expect(dialog.message()).toContain("Pieces you entered yourself stay");
    void dialog.accept();
  });
  await row.getByRole("button", { name: "Remove the demo collection" }).click();
  await expect.poll(() => removed).toBe(true);
  await expect(row).toBeHidden();
  await page.evaluate(() => localStorage.removeItem("cabinet.demo.dismissed"));
});

test("a new piece starts in the display currency", async ({ page }) => {
  await page.route("**/api/settings", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), display_currency: "EUR" } });
  });
  await page.goto("/items/new");
  await expect(page.getByLabel("Currency", { exact: true })).toHaveValue("EUR");
  await page.goto("/items/add");
  await expect(page.getByLabel("Currency", { exact: true })).toHaveValue("EUR");
  await page.goto("/items/run");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("a refused save says why beside the Save buttons, by the field's label", async ({ page }) => {
  await page.goto("/items/new");
  await page.getByLabel("Country *").fill("Refused");
  await page.getByLabel("Denomination *").fill("1 test");
  await page.getByLabel("Year *").fill("1999");
  // The browser accepts this; the server doesn't.
  await page.getByLabel("Currency", { exact: true }).fill("U1");
  const save = page.getByRole("button", { name: "Add item" });
  await save.click();

  const summary = page.locator(".form-errors");
  await expect(summary).toBeInViewport();
  await expect(summary).toHaveAttribute("role", "alert");
  await expect(summary).toBeFocused();
  await expect(summary).toContainText("three-letter code");
  await expect(summary).not.toContainText("Value error");
  const currency = page.getByLabel("Currency", { exact: true });
  await expect(currency).toHaveAttribute("aria-invalid", "true");
  // The field's name in the summary takes you to it.
  await summary.getByRole("button", { name: "Currency" }).click();
  await expect(currency).toBeFocused();

  // Fixing it and saving again clears the mark.
  await currency.fill("USD");
  await save.click();
  await expect(page).toHaveURL(/\/items\/[0-9a-f-]{36}$/);
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page).toHaveURL(/\/collection/);
});

test("leaving a half-filled form asks first, and a saved one doesn't", async ({ page }) => {
  await page.goto("/items/new");
  const country = page.getByLabel("Country *");
  // Untouched, the form lets you go without a word.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Dashboard" }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/items/new");
  await country.fill("Half filled");
  let asked = "";
  page.once("dialog", (dialog) => {
    asked = dialog.message();
    void dialog.dismiss();
  });
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Dashboard" }).click();
  await expect.poll(() => asked).toContain("hasn't been saved");
  await expect(page).toHaveURL(/\/items\/new$/);
  await expect(country).toHaveValue("Half filled");

  // Saying yes leaves.
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Dashboard" }).click();
  await expect(page).toHaveURL(/\/$/);
});

test("the quick add takes an undated piece, and asks for a year otherwise", async ({ page }) => {
  const country = `Undated ${Date.now()}`;
  await page.goto("/items/add");
  await page.getByLabel("Country", { exact: true }).fill(country);
  await page.getByLabel("Denomination", { exact: true }).fill("50 pfennig");
  await page.getByRole("button", { name: "Save and add another" }).click();
  await expect(page.getByRole("alert")).toContainText('tick "No date"');

  await page.getByLabel("No date").check();
  await page.getByRole("button", { name: "Save and add another" }).click();
  const added = page
    .getByRole("complementary", { name: "Added this visit" })
    .getByRole("link", { name: `ND 50 pfennig ${country}` });
  await expect(added).toBeVisible();

  await added.click();
  const inspector = page.getByRole("region", { name: "Selected piece" });
  await expect(inspector.getByRole("heading", { level: 1 })).toContainText(country);
  page.once("dialog", (dialog) => void dialog.accept());
  await inspector.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page).toHaveURL(/\/collection$/);
});

/** A Numista key that says it is set up, and a catalog that answers from
 * here: the lookups below are about what the page does with the answers. */
async function fakeNumista(page: Page) {
  await page.route("**/api/settings", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    body.sources = body.sources.map((s: { key: string }) =>
      s.key === "numista" ? { ...s, configured: true, enabled: true } : s,
    );
    await route.fulfill({ response, json: body });
  });
  const type = (id: number, country: string, denomination: string) => ({
    type_id: id,
    title: `${denomination} (${country})`,
    url: null,
    category: "coin",
    fields: { type: "coin", country, denomination, composition: id === 1 ? "Silver" : "Copper" },
    catalog_refs: [{ catalog: "numista", ref_code: `N#${id}` }],
    issues: [],
  });
  await page.route("**/api/numista/types/1", (route) => route.fulfill({ json: type(1, "Firstland", "1 first") }));
  await page.route("**/api/numista/types/2", (route) => route.fulfill({ json: type(2, "Secondland", "2 second") }));
}

test("a second lookup replaces the first one's answer instead of keeping it", async ({ page }) => {
  await fakeNumista(page);
  await page.goto("/items/add");
  const box = page.getByLabel("Look up a piece");
  await box.fill("N# 1");
  await box.press("Enter");
  await expect(page.getByLabel("Country", { exact: true })).toHaveValue("Firstland");
  // The wrong one: look again.
  await box.fill("N# 2");
  await box.press("Enter");
  await expect(page.getByLabel("Country", { exact: true })).toHaveValue("Secondland");
  await expect(page.getByLabel("Denomination", { exact: true })).toHaveValue("2 second");
  // The looked-up piece is unsaved work now: leaving asks.
  let asked = false;
  page.once("dialog", (dialog) => {
    asked = true;
    void dialog.accept();
  });
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Dashboard" }).click();
  await expect.poll(() => asked).toBe(true);
});

test("a bare year in the lookup box is a name to search, not a Numista number", async ({ page }) => {
  await fakeNumista(page);
  let searched = "";
  let fetchedType = false;
  await page.route("**/api/numista/search*", async (route) => {
    searched = new URL(route.request().url()).searchParams.get("q") ?? "";
    await route.fulfill({ json: { count: 0, results: [] } });
  });
  await page.route("**/api/numista/types/1932", async (route) => {
    fetchedType = true;
    await route.fulfill({ status: 404, json: { detail: "no" } });
  });
  await page.goto("/items/add");
  const box = page.getByLabel("Look up a piece");
  await box.fill("1932");
  await box.press("Enter");
  await expect.poll(() => searched).toBe("1932");
  expect(fetchedType).toBe(false);
});
