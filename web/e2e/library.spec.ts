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

test("real data: horizons, bands and the biggest differences", async ({ page }) => {
  await page.goto("/real-data");
  await expect(page.getByRole("heading", { name: /AAPL/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /90% forecast band/ })).toBeVisible();
  await expect(page.getByText("Biggest differences: agent model vs random walk")).toBeVisible();
  await page.getByRole("tab", { name: "5 days ahead" }).click();
  await expect(page.getByRole("tab", { name: "5 days ahead" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByRole("combobox", { name: "Window" }).selectOption("all");
  await axe(page);
});

test("strategy: latest forecast, statistics and strategies", async ({ page }) => {
  await page.goto("/strategy");
  await expect(page.getByText(/Forecast from the last close/)).toBeVisible();
  await expect(
    page.getByRole("img", { name: /expected price with 50% and 90% ranges/ }),
  ).toBeVisible();
  await expect(page.getByText("Buy and hold").first()).toBeVisible();
  await page.getByRole("tab", { name: "5 days ahead" }).click();
  await page.getByRole("combobox", { name: "Window" }).selectOption("all");
  await expect(page.getByRole("img", { name: /Equity of every strategy/ })).toBeVisible();
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

test("event lab: isolate the demo's events, real moves, the library", async ({ page }) => {
  await page.goto("/event-lab");
  await page.getByRole("button", { name: /^Isolate \d+ events?/ }).click();
  await expect(
    page.getByRole("img", { name: /Isolated price effect of every event/ }),
  ).toBeVisible();
  await expect(page.getByText("Interaction").first()).toBeVisible();
  await axe(page);
  await page.getByRole("tab", { name: "Real earnings moves" }).click();
  await expect(page.getByRole("combobox", { name: "Earnings window" })).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Each filing's isolated contribution/ }),
  ).toBeVisible();
  await axe(page);
  await page.getByRole("tab", { name: "Event library" }).click();
  await expect(page.getByText("Isolated real effect of each event type")).toBeVisible();
  await axe(page);
});

test("algo run: stats, charts and trades", async ({ page }) => {
  await page.goto("/algo");
  await expect(page.getByText("Sharpe ratio")).toBeVisible();
  await expect(page.getByRole("img", { name: /Equity of the strategy/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Recent trades table" })).toBeVisible();
  await axe(page);
});

test("import: pick a stock, import, classifier", async ({ page }) => {
  await page.goto("/import");
  await page.getByRole("button", { name: "Import AAPL" }).click();
  await expect(page.getByText("Event classification")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("region", { name: "Headline list" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Social posts" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Classified events" })).toBeVisible();
  await axe(page);
});

test("signal lab: three inputs, a 5-day hold and realistic costs", async ({ page }) => {
  await page.goto("/signals");
  await expect(page.getByRole("note")).toContainText("demonstration purposes only");
  await expect(page.getByRole("checkbox")).toHaveCount(3);
  await expect(page.getByRole("radio")).toHaveCount(2);
  await expect(page.getByText("Spread and market impact 4 bp per trade")).toBeVisible();
  await page.getByRole("button", { name: "Run backtest" }).click();
  await expect(page.getByRole("img", { name: "Monte Carlo equity fan" })).toBeVisible();
  await expect(page.getByText("Trading costs", { exact: true })).toBeVisible();
  await axe(page);
});
