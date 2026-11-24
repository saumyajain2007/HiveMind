import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("network: spread count matches the API's node awareness; layers and stats", async ({
  page,
}) => {
  await page.goto("/network");
  await expect(page.getByRole("img", { name: /Network of \d+ sampled agents/ })).toBeVisible({
    timeout: 15_000,
  });
  const runId =
    new URL(page.url()).searchParams.get("run") ??
    (await page.getByRole("combobox", { name: "Run" }).inputValue());

  // recount from the raw endpoints: sampled nodes that saw any item of family 0 by the end
  const expected = await page.evaluate(async (id) => {
    const get = (p: string) => fetch(`/api/v1/runs/${id}/${p}`).then((r) => r.json());
    const [graph, seen, lineage] = await Promise.all([
      get("graph?layer=all&sample=2000"),
      get("node-seen"),
      get("lineage"),
    ]);
    const rootOf = new Map(lineage.items.map((i: { id: number; root: number }) => [i.id, i.root]));
    const inGraph = new Set(graph.nodes.map((n: { index: number }) => n.index));
    const lit = new Set<number>();
    for (const [, idx, item] of seen.rows as [number, number, number][])
      if (rootOf.get(item) === 0 && inGraph.has(idx)) lit.add(idx);
    return lit.size;
  }, runId);

  const clock = page.getByRole("slider", { name: "Spread clock" });
  await clock.focus();
  await page.keyboard.press("End");
  await expect(page.getByText(`${expected} by the end of the run`)).toBeVisible();
  await expect(page.getByText(new RegExp(`^${expected}\\s*/`))).toBeVisible();
  await page.keyboard.press("Home");
  await expect(page.getByText(/^0\s*\/\s*\d+ sampled/)).toBeVisible();

  await page.getByRole("button", { name: "Twitter" }).click();
  await expect(page.getByRole("button", { name: "Twitter" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "Layer stats" }).click();
  await expect(page.getByRole("dialog", { name: "Layer statistics" })).toContainText("reciprocity");
  await page.keyboard.press("Escape");

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  const summary = results.violations.map((v) => `${v.id}: ${v.nodes.length} × ${v.help}`);
  expect(summary, summary.join("\n")).toEqual([]);
});
