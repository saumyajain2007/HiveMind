import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("live cockpit: markers and feed fill in, pause and scrub, no axe violations", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Run demo", exact: true }).click();
  await expect(page).toHaveURL(/\/cockpit$/);
  const feed = page.getByRole("list", { name: "News feed, newest first" });
  await expect(feed.getByText("Forum post: Acme in takeover talks")).toBeVisible({
    timeout: 20_000,
  });
  await expect(
    page.getByRole("img", { name: /Price over the run: \d+ points.*events marked/ }),
  ).toBeVisible();

  // pause, then scrub back to the start: the clock follows the cursor
  await page.getByRole("button", { name: "Pause the display" }).click();
  const scrub = page.getByRole("slider", { name: "Scrub through the buffered frames" });
  await scrub.focus();
  await page.keyboard.press("Home");
  await expect(page.getByText("Day 1 · 00:00").first()).toBeVisible();
  await expect(feed).toHaveCount(0); // nothing had been born at tick 0
  await page.getByRole("button", { name: "Live", exact: true }).click();
  await expect(feed.getByText("Forum post: Acme in takeover talks")).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .exclude(".tv-lightweight-charts")
    .analyze();
  const summary = results.violations.map((v) => `${v.id}: ${v.nodes.length} × ${v.help}`);
  expect(summary, summary.join("\n")).toEqual([]);
});
