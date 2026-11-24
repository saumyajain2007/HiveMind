import { GitCompareArrows } from "lucide-react";
import { useMemo } from "react";

import { XYChart } from "@/components/charts/XYChart";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useQuantiles, useRun, useSeries } from "@/lib/api/queries";
import type { QuantilesResponse, SeriesResponse } from "@/lib/api/results";
import { simClock, TICKS_PER_DAY } from "@/lib/format";

/** Every leaf of a nested JSON value as "a.b.c" -> value. */
function flatten(
  v: unknown,
  prefix = "",
  out: Record<string, unknown> = {},
): Record<string, unknown> {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    for (const [k, x] of Object.entries(v as Record<string, unknown>))
      flatten(x, prefix ? `${prefix}.${k}` : k, out);
  } else out[prefix] = v;
  return out;
}

const show = (v: unknown) =>
  typeof v === "number" ? String(Number(v.toPrecision(5))) : JSON.stringify(v);

/** Two runs side by side: price paths on one axis (change from the start) and what differs in their specs. */
export function RunCompare({ a, b }: { a: string; b: string }) {
  const ra = useRun(a);
  const rb = useRun(b);
  const done = (s?: string) => s === "done" || s === "cancelled";
  const sa = useSeries(
    done(ra.data?.status) && ra.data?.mode !== "calibration" && ra.data?.mode !== "backtest"
      ? a
      : null,
    2,
  );
  const sb = useSeries(
    done(rb.data?.status) && rb.data?.mode !== "calibration" && rb.data?.mode !== "backtest"
      ? b
      : null,
    2,
  );
  const qa = useQuantiles(ra.data?.mode === "montecarlo" && done(ra.data.status) ? a : null);
  const qb = useQuantiles(rb.data?.mode === "montecarlo" && done(rb.data.status) ? b : null);

  const chart = useMemo(() => {
    const curve = (s: SeriesResponse | undefined, q: QuantilesResponse | undefined) => {
      if (q) {
        const m = q.quantiles["0.5"];
        return { x: m.map((_, i) => i), y: m.map((v) => (100 * v) / m[0]! - 100) };
      }
      if (s)
        return { x: s.tick, y: s.series.price.map((v) => (100 * v) / s.series.price[0]! - 100) };
      return null;
    };
    const ca = curve(sa.data, qa.data);
    const cb = curve(sb.data, qb.data);
    if (!ca || !cb) return null;
    const n = Math.max(ca.x[ca.x.length - 1]!, cb.x[cb.x.length - 1]!);
    const x = Array.from({ length: Math.floor(n / 2) + 1 }, (_, i) => i * 2);
    const at = (c: { x: number[]; y: number[] }) => {
      const m = new Map(c.x.map((t, i) => [t, c.y[i]!]));
      let carry: number | null = null;
      return x.map((t) => {
        if (m.has(t)) carry = m.get(t)!;
        return t > c.x[c.x.length - 1]! ? null : carry;
      });
    };
    return { x, ya: at(ca), yb: at(cb), n };
  }, [sa.data, sb.data, qa.data, qb.data]);

  const diff = useMemo(() => {
    if (!ra.data || !rb.data) return [];
    const fa = flatten({
      scenario: ra.data.spec.scenario,
      parameters: ra.data.spec.parameters,
      seed: ra.data.spec.seed,
      mode: ra.data.mode,
      runs: ra.data.runs,
    });
    const fb = flatten({
      scenario: rb.data.spec.scenario,
      parameters: rb.data.spec.parameters,
      seed: rb.data.spec.seed,
      mode: rb.data.mode,
      runs: rb.data.runs,
    });
    return [...new Set([...Object.keys(fa), ...Object.keys(fb)])]
      .filter(
        (k) => !k.startsWith("scenario.events") && JSON.stringify(fa[k]) !== JSON.stringify(fb[k]),
      )
      .map((k) => ({ k, a: fa[k], b: fb[k] }))
      .concat(
        JSON.stringify(ra.data.spec.scenario.events) !==
          JSON.stringify(rb.data.spec.scenario.events)
          ? [
              {
                k: "scenario.events",
                a: `${ra.data.spec.scenario.events?.length ?? 0} events`,
                b: `${rb.data.spec.scenario.events?.length ?? 0} events (different)`,
              },
            ]
          : [],
      );
  }, [ra.data, rb.data]);

  const nameA = ra.data?.name ?? a;
  const nameB = rb.data?.name ?? b;
  return (
    <Panel
      title="Compare runs"
      icon={GitCompareArrows}
      subtitle={`${nameA} (${a}) vs ${nameB} (${b})`}
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        {chart ? (
          <XYChart
            x={chart.x}
            series={[
              {
                key: "a",
                label: `A · ${nameA}${ra.data?.mode === "montecarlo" ? " (median)" : ""}`,
                values: chart.ya,
                color: "var(--fundamental)",
              },
              {
                key: "b",
                label: `B · ${nameB}${rb.data?.mode === "montecarlo" ? " (median)" : ""}`,
                values: chart.yb,
                color: "var(--official)",
                dash: "6 3",
              },
            ]}
            height={280}
            zeroLine={0}
            xFormat={(t) => simClock(t).label}
            xTicks={Array.from(
              { length: Math.ceil(chart.n / TICKS_PER_DAY) },
              (_, d) => d * TICKS_PER_DAY,
            )}
            yFormat={(v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`}
            label="Price change from the start, both runs"
          />
        ) : (
          <Skeleton className="h-[280px]" />
        )}
        <div className="min-w-0">
          <h3 className="mb-2 text-xs font-medium text-muted-foreground">
            {diff.length
              ? `${diff.length} setting${diff.length === 1 ? "" : "s"} differ`
              : "Specs are identical"}
          </h3>
          <div className="max-h-[260px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-1 font-medium">Setting</th>
                  <th className="py-1 font-medium">A</th>
                  <th className="py-1 font-medium">B</th>
                </tr>
              </thead>
              <tbody>
                {diff.map((d) => (
                  <tr key={d.k} className="border-t">
                    <td className="py-1.5 pr-2 font-mono">{d.k}</td>
                    <td className="max-w-28 truncate py-1.5 pr-2 font-mono" title={show(d.a)}>
                      {show(d.a)}
                    </td>
                    <td className="max-w-28 truncate py-1.5 font-mono" title={show(d.b)}>
                      {show(d.b)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Panel>
  );
}
