import AxeBuilder from "@axe-core/playwright";
import { expect, Page, test } from "@playwright/test";

// Accessibility basics, kept from regressing.
//
// An automated scan (axe, WCAG 2.0 to 2.2 at levels A and AA) of the main
// pages in light and dark, the other three color themes on two busy pages,
// and the things a scan can't judge: that a dialog holds focus and gives it
// back, that a field's outline can be seen, that every page has a title of
// its own, and that the keyboard can skip to the content.
//
// The scan checks structure and contrast. It can't tell whether a label
// makes sense, which is why the checks after it are written out by hand.

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const MODES = ["dark", "light"] as const;
const PALETTES = ["silver", "album", "ledger"];

/** Every finding as one readable line, so a failure names the rule and the
 * element. */
async function findings(page: Page, rules?: string[]): Promise<string[]> {
  const builder = new AxeBuilder({ page });
  const results = await (rules ? builder.withRules(rules) : builder.withTags(TAGS)).analyze();
  return results.violations.map(
    (v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`,
  );
}

async function inMode(page: Page, mode: (typeof MODES)[number]) {
  await page.addInitScript((m) => localStorage.setItem("theme", m), mode);
}

/** A page is ready to scan once its heading is up and requests have settled. */
async function open(page: Page, path: string) {
  await page.goto(path);
  await expect(page.locator("main h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
}

// A piece of our own, so the item page, the form, and the dashboard have
// something to show whatever the stack already holds.
let pieceId = "";

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  await page.goto("/");
  pieceId = await page.evaluate(async () => {
    const response = await fetch("/api/items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: "coin",
        country: "Accessibility",
        denomination: "1 scan",
        year: 1999,
        composition: "90% silver",
        storage_location: "Box A",
        tags: ["a11y"],
        acquisition_price: 12.5,
      }),
    });
    const id = (await response.json()).id as string;
    // A photo too, so the item page's photo controls are part of the scan.
    const canvas = document.createElement("canvas");
    canvas.width = 120;
    canvas.height = 90;
    canvas.getContext("2d")!.fillRect(0, 0, 120, 90);
    const blob = await new Promise<Blob>((done) => canvas.toBlob((b) => done(b!), "image/png"));
    const form = new FormData();
    form.append("file", blob, "scan.png");
    await fetch(`/api/items/${id}/photos`, { method: "POST", body: form });
    return id;
  });
  await page.close();
});

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await page.goto("/");
  await page.evaluate((id) => fetch(`/api/items/${id}`, { method: "DELETE" }), pieceId);
  await page.close();
});

const PAGES: [string, string, string][] = [
  // name, path, the page's title before " · Cabinet"
  ["dashboard", "/", "Dashboard"],
  ["collection", "/collection", "Collection"],
  ["item form", "/items/new", "Add a piece, every field"],
  ["quick add", "/items/add", "Add a piece"],
  ["add a run", "/items/run", "Add a run"],
  ["import", "/import", "Import"],
  ["stack", "/stack", "Stack"],
  ["checklists", "/checklists", "Checklists"],
  ["pricing", "/pricing", "Pricing"],
  ["trash", "/trash", "Trash"],
  ["settings, general", "/settings/general", "Settings, General"],
  ["settings, pricing", "/settings/pricing", "Settings, Pricing"],
  ["settings, backups", "/settings/backups", "Settings, Backups"],
  ["settings, alerts", "/settings/alerts", "Settings, Alerts & metrics"],
  ["settings, sharing", "/settings/sharing", "Settings, Sharing"],
  ["settings, account", "/settings/account", "Settings, Account"],
  ["settings, sign-in", "/settings/signin", "Settings, Sign-in"],
  ["settings, about", "/settings/about", "Settings, About"],
];

for (const mode of MODES) {
  test(`the main pages pass the scan, ${mode}`, async ({ page }) => {
    test.setTimeout(120_000);
    await inMode(page, mode);
    const failed: string[] = [];
    for (const [name, path] of PAGES) {
      await open(page, path);
      for (const finding of await findings(page)) failed.push(`${name}: ${finding}`);
    }
    for (const [name, path] of [
      ["item page", `/items/${pieceId}`],
      ["item edit", `/items/${pieceId}/edit`],
      ["inspector", `/collection/${pieceId}`],
    ]) {
      await open(page, path);
      for (const finding of await findings(page)) failed.push(`${name}: ${finding}`);
    }
    expect(failed).toEqual([]);
  });
}

test("the sign-in page passes the scan, and says what it is", async ({ browser }) => {
  for (const mode of MODES) {
    const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const page = await context.newPage();
    await inMode(page, mode);
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await expect(page).toHaveTitle("Sign in · Cabinet");
    expect(await findings(page), mode).toEqual([]);
    await context.close();
  }
});

test("the other color themes keep their contrast, light and dark", async ({ page }) => {
  test.setTimeout(120_000);
  const failed: string[] = [];
  for (const palette of PALETTES) {
    for (const mode of MODES) {
      for (const path of ["/", "/items/new"]) {
        await open(page, path);
        // The look only: the saved theme is the server's and stays as it is.
        await page.evaluate(
          ([p, m]) => {
            document.documentElement.dataset.palette = p;
            document.documentElement.dataset.theme = m;
          },
          [palette, mode],
        );
        for (const finding of await findings(page, ["color-contrast", "link-in-text-block"])) {
          failed.push(`${palette} ${mode} ${path}: ${finding}`);
        }
      }
    }
  }
  expect(failed).toEqual([]);
});

/** WCAG's contrast ratio between two CSS colors, worked out in the page. */
const FIELD_CHECK = () => {
  const parse = (color: string) => {
    const parts = color.match(/[\d.]+/g)?.map(Number) ?? [0, 0, 0, 1];
    return { r: parts[0], g: parts[1], b: parts[2], a: parts[3] ?? 1 };
  };
  const luminance = ({ r, g, b }: { r: number; g: number; b: number }) => {
    const channel = (v: number) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const ratio = (a: string, b: string) => {
    const [x, y] = [luminance(parse(a)), luminance(parse(b))];
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  };
  const behind = (el: Element): string => {
    for (let node = el.parentElement; node; node = node.parentElement) {
      const color = getComputedStyle(node).backgroundColor;
      if (parse(color).a > 0.5) return color;
    }
    return getComputedStyle(document.body).backgroundColor;
  };
  const fields = [...document.querySelectorAll<HTMLElement>("main input, main select, main textarea, .auth-card input")]
    .filter((el) => el.offsetParent !== null)
    .filter((el) => !["checkbox", "radio", "file", "range"].includes((el as HTMLInputElement).type));
  const faint: string[] = [];
  const small: string[] = [];
  for (const el of fields) {
    const style = getComputedStyle(el);
    const name = el.getAttribute("aria-label") ?? el.closest("label")?.textContent?.trim().slice(0, 30) ?? el.tagName;
    if (ratio(style.borderTopColor, behind(el)) < 3) faint.push(name);
    if (parseFloat(style.fontSize) < 13.5) small.push(name);
  }
  return { count: fields.length, faint, small };
};

test("every field's outline can be seen and its text read, in every theme", async ({ page }) => {
  test.setTimeout(120_000);
  const failed: string[] = [];
  for (const palette of ["bronze", ...PALETTES]) {
    for (const mode of MODES) {
      for (const path of ["/items/new", "/items/add", "/settings/general", "/collection"]) {
        await open(page, path);
        await page.evaluate(
          ([p, m]) => {
            document.documentElement.dataset.palette = p;
            document.documentElement.dataset.theme = m;
          },
          [palette, mode],
        );
        const result = await page.evaluate(FIELD_CHECK);
        expect(result.count).toBeGreaterThan(0);
        if (result.faint.length) failed.push(`${palette} ${mode} ${path}: faint outline on ${result.faint.join(", ")}`);
        if (result.small.length) failed.push(`${palette} ${mode} ${path}: small text in ${result.small.join(", ")}`);
      }
    }
  }
  expect(failed).toEqual([]);
});

test("every page has a title of its own", async ({ page }) => {
  for (const [, path, title] of PAGES) {
    await open(page, path);
    await expect(page).toHaveTitle(`${title} · Cabinet`);
  }
  await open(page, `/items/${pieceId}`);
  await expect(page).toHaveTitle("Accessibility 1 scan, 1999 · Cabinet");
  await page.goto("/no/such/page");
  await expect(page).toHaveTitle("Page not found · Cabinet");
});

test("the keyboard can skip to the content, and a new page takes focus to its heading", async ({ page }) => {
  await open(page, "/stack");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: "Stack" })).toBeFocused();
  // The address is untouched: the router owns it.
  await expect(page).toHaveURL(/\/stack$/);

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Pricing" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Pricing" })).toBeFocused();
  // A page that puts focus somewhere itself keeps it.
  await page.getByRole("link", { name: "Add piece" }).click();
  await expect(page.getByLabel("Look up a piece")).toBeFocused();
});

test("a dialog takes focus, holds it, and gives it back", async ({ page }) => {
  await open(page, "/");
  await page.getByRole("button", { name: "Edit dashboard" }).click();
  const add = page.getByRole("button", { name: "Add widget" });
  await add.click();
  const dialog = page.getByRole("dialog", { name: "Add a widget" });
  await expect(dialog).toBeVisible();
  const inside = () => page.evaluate(() => !!document.activeElement?.closest("dialog[open]"));
  expect(await inside()).toBe(true);
  // Tab goes round the dialog and the browser's own toolbar, where the page
  // has no focused element at all. It never reaches anything behind.
  const behind = () =>
    page.evaluate(() => {
      const active = document.activeElement;
      return !!active && active !== document.body && !active.closest("dialog[open]");
    });
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    expect(await behind(), `after ${i + 1} tabs`).toBe(false);
  }
  expect(await findings(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(add).toBeFocused();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
});

test("the photo viewer is a dialog too: Escape closes it and focus returns", async ({ page }) => {
  await open(page, `/items/${pieceId}`);
  const thumb = page.getByRole("button", { name: /^View the .* larger$/ }).first();
  await thumb.click();
  const viewer = page.getByRole("dialog", { name: "Photo viewer" });
  await expect(viewer).toBeVisible();
  expect(await page.evaluate(() => !!document.activeElement?.closest("dialog[open]"))).toBe(true);
  expect(await findings(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(viewer).toBeHidden();
  await expect(thumb).toBeFocused();
});

test("the single-key shortcuts can be switched off", async ({ page }) => {
  await open(page, "/collection");
  await page.keyboard.press("n");
  await expect(page).toHaveURL(/\/items\/add$/);

  await open(page, "/settings/general");
  await page.getByLabel("Single-key shortcuts").uncheck();
  await open(page, "/collection");
  await page.keyboard.press("n");
  await page.keyboard.press("/");
  await expect(page).toHaveURL(/\/collection$/);
  await expect(page.getByLabel("Search the collection")).not.toBeFocused();

  await open(page, "/settings/general");
  await page.getByLabel("Single-key shortcuts").check();
});

test("an edit-in-place button reads its value, and an error is announced", async ({ page }) => {
  await open(page, `/collection/${pieceId}`);
  const inspector = page.getByRole("region", { name: "Selected piece" });
  await expect(inspector.getByRole("button", { name: "Change storage: Box A" })).toBeVisible();

  // A refused sign-in confirmation is an alert, not just red text.
  await open(page, "/items/add");
  await page.getByRole("button", { name: "Save and add another" }).click();
  await expect(page.getByRole("alert")).toContainText("country and a denomination");
});
