import { expect, test } from "@playwright/test";

test("build a scenario from scratch, block invalid input, run it live", async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem("marketsim-builder"));
  await page.goto("/builder");
  await page
    .getByRole("combobox", { name: "Load a preset or saved scenario" })
    .selectOption("quiet");
  await expect(page.getByRole("heading", { name: "Quiet market" })).toBeVisible();

  // add an event and edit it
  await page.getByRole("button", { name: "Event", exact: true }).click();
  await page.getByLabel("Headline (shown in the UI only)").fill("Takeover rumour");
  await page.getByLabel("Seeding (who hears it first)").selectOption("influencer");
  await expect(page.getByRole("button", { name: /Takeover rumour, rumour, Day 1/ })).toBeVisible();

  // invalid input is blocked with an inline message
  await page.getByRole("spinbutton", { name: "Days", exact: true }).fill("0");
  await expect(page.getByRole("alert").first()).toContainText("Days must be");
  await expect(page.getByRole("button", { name: "Run live" })).toBeDisabled();
  await page.getByRole("spinbutton", { name: "Days", exact: true }).fill("3");
  await expect(page.getByRole("button", { name: "Run live" })).toBeEnabled();

  // a parameter change shows up in the diff
  await page.getByLabel("twitter_mean_out value").fill("55");
  await page.getByRole("button", { name: "Diff" }).click();
  await expect(page.getByRole("cell", { name: "graph.twitter_mean_out" })).toBeVisible();

  await page.getByRole("button", { name: "Run live" }).click();
  await expect(page).toHaveURL(/\/cockpit$/);
});

test("import headlines through the manual LLM flow", async ({ page }) => {
  await page.goto("/builder");
  await page.getByRole("button", { name: "Import headlines" }).click();
  const sheet = page.getByRole("dialog", { name: "Import headlines" });
  await sheet.getByLabel(/Headlines, one per line/).fill("2 10:30 | Acme misses estimates");
  await sheet.getByRole("button", { name: /Parse 1 headline/ }).click();
  await sheet
    .getByLabel("Reply for headline 1")
    .fill(
      '{"kind":"earnings","true_impact":-0.04,"sentiment":-0.6,"credibility":0.9,"salience":0.7,"complexity":0.4,"seeding":"official"}',
    );
  await sheet.getByRole("button", { name: "Read the replies" }).click();
  await expect(sheet.getByText("Day 2 · 10:30 · earnings · official")).toBeVisible();
  await sheet.getByRole("button", { name: /Add 1 to the timeline/ }).click();
  await expect(
    page.getByRole("button", { name: /Acme misses estimates, earnings, Day 2 · 10:30/ }),
  ).toBeVisible();
});
