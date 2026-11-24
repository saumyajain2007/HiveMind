import { expect, test } from "@playwright/test";

/**
 * The whole product in one pass: build the demo scenario → run it live → see the event markers →
 * run Monte Carlo → see the fan → open the lineage.
 */
test("demo scenario end to end", async ({ page }) => {
  test.setTimeout(120_000);
  await page.addInitScript(() => localStorage.removeItem("marketsim-builder"));
  await page.goto("/builder");
  await page
    .getByRole("combobox", { name: "Load a preset or saved scenario" })
    .selectOption("demo");
  await expect(
    page.getByRole("heading", { name: "Demo: rumour → denial → earnings miss" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Forum post: Acme in takeover talks, rumour, Day 1/ }),
  ).toBeVisible();

  // run live: markers and the feed appear as events are injected
  await page.getByRole("button", { name: "Run live" }).click();
  await expect(page).toHaveURL(/\/cockpit$/);
  const feed = page.getByRole("list", { name: "News feed, newest first" });
  await expect(feed.getByText(/Forum post: Acme in takeover talks/)).toBeVisible({
    timeout: 30_000,
  });
  await expect(
    page.getByRole("img", { name: /Price over the run: \d+ points.*[1-9]\d* events marked/ }),
  ).toBeVisible();

  // Monte Carlo from the same scenario
  await page.getByRole("link", { name: "Builder" }).click();
  await page.getByRole("spinbutton", { name: "Monte Carlo runs" }).fill("5");
  await page.getByRole("button", { name: /Monte Carlo ×/ }).click();
  await expect(page).toHaveURL(/\/monte-carlo\?run=/);
  await expect(
    page.getByRole("img", { name: /Fan chart of \d+ simulated price paths/ }),
  ).toBeVisible({
    timeout: 30_000,
  });

  // the lineage of a finished single run
  await page.getByRole("link", { name: "Narratives" }).click();
  await expect(page.getByRole("group", { name: /Lineage of \d+ items/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Story" })).toContainText(/mutated/);
});
