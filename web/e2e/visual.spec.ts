import { expect, test } from "@playwright/test";

/**
 * Visual-regression snapshots of the key screens (mock data, dark theme).
 *
 * Screenshots differ between operating systems (fonts, anti-aliasing), so baselines are stored
 * per platform and this suite is opt-in: `VISUAL=1 pnpm e2e visual` compares against the
 * baselines, `VISUAL=1 pnpm e2e visual --update-snapshots` records them. CI does not run it.
 */
test.skip(!process.env.VISUAL, "set VISUAL=1 to run the visual-regression suite");

const SCREENS = [
  ["runs", "/"],
  ["builder", "/builder"],
  ["monte-carlo", "/monte-carlo"],
  ["narratives", "/narratives"],
  ["analysis", "/analysis"],
  ["real-data", "/real-data"],
] as const;

for (const [name, path] of SCREENS) {
  test(`screen: ${name}`, async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("marketsim-theme", "dark");
      localStorage.removeItem("marketsim-builder");
    });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(path);
    await page.waitForLoadState("load");
    await page.waitForTimeout(2000);
    await expect(page).toHaveScreenshot(`${name}.png`, {
      fullPage: true,
      maxDiffPixelRatio: 0.02,
      mask: [page.locator("time"), page.getByText(/ago$/)],
    });
  });
}
