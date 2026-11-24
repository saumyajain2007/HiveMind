import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("Monte Carlo from the Builder: progress streams in, fan, distribution, stylised facts", async ({
  page,
}) => {
  await page.goto("/builder");
  await page.getByRole("spinbutton", { name: "Monte Carlo runs" }).fill("6");
  await page.getByRole("button", { name: /Monte Carlo ×/ }).click();
  await expect(page).toHaveURL(/\/monte-carlo\?run=/);
  await expect(
    page.getByRole("img", { name: /Fan chart of \d+ simulated price paths/ }),
  ).toBeVisible({
    timeout: 15_000,
  });
  // the mock job finishes and the final summary appears
  await expect(page.getByText("Median final price")).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Fan chart of 20 simulated price paths/ }),
  ).toBeVisible({
    timeout: 15_000,
  });

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export fan-chart as CSV" }).click();
  expect((await download).suggestedFilename()).toBe("quantiles.csv");

  await page.getByRole("tab", { name: "Terminal price" }).click();
  await expect(page.getByRole("img", { name: /Distribution of the final price/ })).toBeVisible();
  await page.getByRole("tab", { name: "Stylised facts" }).click();
  await expect(page.getByText(/excess kurtosis/)).toBeVisible();
  await expect(page.getByRole("img", { name: /Autocorrelation of returns/ })).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  const summary = results.violations.map((v) => `${v.id}: ${v.nodes.length} × ${v.help}`);
  expect(summary, summary.join("\n")).toEqual([]);
});
