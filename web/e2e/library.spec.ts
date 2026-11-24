import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

async function axe(page: import("@playwright/test").Page) {
  await page.waitForTimeout(1000); // entry animations and toasts settle, so axe sees final colours
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  const summary = results.violations.map((v) => `${v.id}: ${v.nodes.length} × ${v.help}`);
  expect(summary, summary.join("\n")).toEqual([]);
}

test("analysis: start a calibration and a backtest", async ({ page }) => {
  await page.goto("/analysis");
  await page.getByRole("checkbox", { name: "Fit mu0" }).uncheck();
  await page.getByRole("spinbutton", { name: "impact_Y low" }).fill("2");
  await expect(page.getByRole("alert")).toContainText("impact_Y");
  await expect(page.getByRole("button", { name: "Start calibration" })).toBeDisabled();
  await page.getByRole("spinbutton", { name: "impact_Y low" }).fill("0.4");
  await page.getByRole("button", { name: "Start calibration" }).click();
  await expect(page.getByText("Calibration started")).toBeVisible();
  await expect(page.getByRole("img", { name: /RMSE against impact_Y/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /Observed and best-fit log price/ })).toBeVisible();
  await axe(page);

  await page.getByRole("tab", { name: "Backtest" }).click();
  await page.getByRole("button", { name: "Start backtest" }).click();
  await expect(page.getByText("CRPS skill vs random walk")).toBeVisible();
  await expect(
    page.getByRole("img", { name: /CRPS of the model and the random walk/ }),
  ).toBeVisible();
  await axe(page);
});

test("run library: compare two runs, duplicate one into the Builder", async ({ page }) => {
  await page.goto("/");
  const boxes = page.getByRole("checkbox", { name: /^Compare / });
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  const compare = page.getByRole("region", { name: "Compare runs" });
  await expect(
    compare.getByRole("img", { name: /Price change from the start, both runs/ }),
  ).toBeVisible();
  await expect(compare.getByText(/settings? differ/)).toBeVisible();
  await axe(page);

  await page
    .getByRole("button", { name: /^Duplicate Demo: rumour/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/builder$/);
  await expect(page.getByRole("heading", { name: /\(copy\)$/ })).toBeVisible();
});
