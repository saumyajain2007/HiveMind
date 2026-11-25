import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const PAGES = [
  "/",
  "/builder",
  "/cockpit",
  "/monte-carlo",
  "/network",
  "/narratives",
  "/analysis",
  "/event-lab",
  "/real-data",
  "/import",
  "/algo",
  "/signals",
  "/strategy",
  "/design",
];

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.addInitScript((t) => localStorage.setItem("marketsim-theme", t), theme);
}

async function settle(page: Page) {
  // not "networkidle": pages poll run status, and WebGL / worker pages never go fully quiet
  await page.waitForLoadState("load");
  await page.locator("main h2, main [role=img], main h1").first().waitFor({ timeout: 15_000 });
  // let entry animations and mock requests finish so axe measures the final page
  await page.waitForTimeout(1200);
}

for (const theme of ["dark", "light"] as const) {
  test.describe(`${theme} theme`, () => {
    for (const path of PAGES) {
      test(`axe: no violations on ${path}`, async ({ page }) => {
        await setTheme(page, theme);
        await page.goto(path);
        await settle(page);
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze();
        const summary = results.violations.map((v) => `${v.id}: ${v.nodes.length} × ${v.help}`);
        expect(summary, summary.join("\n")).toEqual([]);
      });
    }
  });
}

test("demo replay streams live data into the ticker and cockpit", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Simulation runs" })).toBeVisible();
  await expect(page.getByRole("row").nth(1)).toBeVisible(); // seeded mock runs
  await page.getByRole("button", { name: "Run demo", exact: true }).click();
  await expect(page).toHaveURL(/\/cockpit$/);
  await expect(page.getByRole("status").filter({ hasText: "Live" })).toBeVisible({
    timeout: 10_000,
  });
  const ticker = page.getByLabel("Market ticker");
  await expect(ticker).toContainText(/Day \d · \d\d:\d\d/, { timeout: 10_000 });
  await expect(page.getByRole("img", { name: /Price over the run: \d+ points/ })).toBeVisible();
});

test("command palette opens with Ctrl+K and navigates", async ({ page }) => {
  await page.goto("/");
  await settle(page);
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await page.keyboard.type("design");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/design$/);
});

test("theme toggle switches and persists", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("button", { name: "Toggle theme" }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/light/);
});

test("reduced motion: no running CSS animations on the cockpit", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await page.goto("/");
  await page.getByRole("button", { name: "Run demo", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Live" })).toBeVisible({
    timeout: 10_000,
  });
  await page.waitForTimeout(500);
  const long = await page.evaluate(() =>
    document
      .getAnimations()
      .filter((a) => {
        const t = a.effect?.getComputedTiming();
        return (
          t && a.playState === "running" && (t.iterations === Infinity || Number(t.duration) > 1)
        );
      })
      .map((a) => {
        const target = (a.effect as KeyframeEffect | null)?.target as Element | null;
        const name = "animationName" in a ? String(a.animationName) : a.constructor.name;
        return `${name} on <${target?.tagName.toLowerCase()} class="${target?.getAttribute("class")?.slice(0, 80)}">`;
      }),
  );
  expect(long).toEqual([]);
  await ctx.close();
});
