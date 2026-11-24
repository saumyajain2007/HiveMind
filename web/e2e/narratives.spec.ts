import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("narratives: rumour family with mutations and its denial; heat map matches /awareness", async ({
  page,
}) => {
  await page.goto("/narratives");
  const story = page.getByRole("region", { name: "Story" });
  await expect(story).toContainText(/Rumour #0 .* → mutated twice → reached \d+% of agents/);
  await expect(story).toContainText(/official statement #\d+ reached/);

  // the denial hangs under the rumour, and a mutation's chain starts at the rumour
  await page.getByRole("button", { name: /^#4 .*Mutation/ }).click();
  const card = page.getByRole("region", { name: /#4 distorted retelling of #3/ });
  await expect(card.getByText("#0 Event")).toBeVisible();
  await expect(card.getByText("#3 Mutation")).toBeVisible();

  // heat-map value recomputed from the raw endpoint
  const runId = await page.getByRole("combobox", { name: "Run" }).inputValue();
  const expected = await page.evaluate(async (id) => {
    const a = await fetch(`/api/v1/runs/${id}/awareness?every=2`).then((r) => r.json());
    const f = a.families.find((x: { root: number }) => x.root === 0);
    const peak = f.rows.reduce((b: number[], r: number[]) => (r[2]! > b[2]! ? r : b), f.rows[0]);
    const P = a.platforms.length;
    return Math.round((peak[3 + P + 0] / a.category_sizes[0]) * 100);
  }, runId);
  await expect(
    page.getByRole("button", { name: new RegExp(`^#0 .*, Non-investors: ${expected}%$`) }),
  ).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  const summary = results.violations.map((v) => `${v.id}: ${v.nodes.length} × ${v.help}`);
  expect(summary, summary.join("\n")).toEqual([]);
});
