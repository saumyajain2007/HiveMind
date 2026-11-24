import { useState } from "react";

import { cn } from "@/lib/utils";

import { Legend } from "./Legend";
import { extent, linear, niceTicks } from "./scale";
import { useSize } from "./useSize";

export interface BarGroup {
  key: string;
  label: string;
  color: string;
  values: number[];
}

/**
 * Grouped vertical bars: categories on x, one bar per group in each category. Bars start at 0
 * with 4px rounded ends and a 2px surface gap; hovering (or focusing) a bar shows its value.
 */
export function BarChart({
  categories,
  groups,
  height = 220,
  yFormat = (v) => v.toFixed(2),
  label,
  className,
  band,
}: {
  categories: string[];
  groups: BarGroup[];
  height?: number;
  yFormat?: (v: number) => string;
  label: string;
  className?: string;
  /** Shaded ±band around 0 (e.g. a 95% confidence band). */
  band?: number;
}) {
  const [ref, w] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<[number, number] | null>(null);
  const width = Math.max(w, 120);
  const m = { top: 8, right: 48, bottom: 28, left: 8 };
  const plotW = width - m.left - m.right;
  const plotH = height - m.top - m.bottom;
  const all = groups.flatMap((g) => g.values);
  const [lo0, hi0] = extent([[...all, 0, ...(band ? [band, -band] : [])]], 0.08);
  const lo = Math.min(0, lo0);
  const hi = Math.max(0, hi0);
  const sy = linear([lo, hi], [m.top + plotH, m.top]);
  const slot = plotW / Math.max(1, categories.length);
  const bw = Math.max(2, (slot * 0.78) / Math.max(1, groups.length) - 2);
  const ticks = niceTicks(lo, hi, 4);
  const summary = groups
    .map(
      (g) => `${g.label}: ${g.values.map((v, i) => `${categories[i]} ${yFormat(v)}`).join(", ")}`,
    )
    .join("; ");
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      <div
        ref={ref}
        className="relative w-full"
        style={{ height }}
        role="img"
        aria-label={`${label}. ${summary}`}
      >
        {w > 0 && (
          <svg width={width} height={height} className="block">
            {band != null && (
              <rect
                x={m.left}
                width={plotW}
                y={sy(band)}
                height={Math.max(0, sy(-band) - sy(band))}
                fill="var(--muted)"
                opacity={0.6}
              />
            )}
            {ticks.map((t) => (
              <g key={t}>
                <line x1={m.left} x2={m.left + plotW} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" />
                <text
                  x={m.left + plotW + 6}
                  y={sy(t)}
                  dy="0.32em"
                  className="fill-muted-foreground font-mono text-[10px]"
                >
                  {yFormat(t)}
                </text>
              </g>
            ))}
            <line x1={m.left} x2={m.left + plotW} y1={sy(0)} y2={sy(0)} stroke="var(--axis)" />
            {categories.map((c, ci) => (
              <g key={c}>
                {groups.map((g, gi) => {
                  const v = g.values[ci] ?? 0;
                  const x0 =
                    m.left + ci * slot + (slot - groups.length * (bw + 2)) / 2 + gi * (bw + 2);
                  const y = Math.min(sy(v), sy(0));
                  const h = Math.max(1, Math.abs(sy(v) - sy(0)));
                  const active = hover?.[0] === ci && hover?.[1] === gi;
                  return (
                    <rect
                      key={g.key}
                      x={x0}
                      y={y}
                      width={bw}
                      height={h}
                      rx={Math.min(4, bw / 2)}
                      fill={g.color}
                      opacity={hover && !active ? 0.55 : 1}
                      onPointerEnter={() => setHover([ci, gi])}
                      onPointerLeave={() => setHover(null)}
                    >
                      <title>{`${g.label} · ${c}: ${yFormat(v)}`}</title>
                    </rect>
                  );
                })}
                <text
                  x={m.left + ci * slot + slot / 2}
                  y={height - 8}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[10px]"
                >
                  {c}
                </text>
              </g>
            ))}
          </svg>
        )}
        {hover && (
          <div className="pointer-events-none absolute top-1 left-2 rounded-md border bg-popover/95 px-2 py-1 text-xs shadow">
            <span className="text-muted-foreground">
              {groups[hover[1]]!.label} · {categories[hover[0]]}:
            </span>{" "}
            <span className="tabular font-mono">
              {yFormat(groups[hover[1]]!.values[hover[0]] ?? 0)}
            </span>
          </div>
        )}
      </div>
      {groups.length > 1 && (
        <Legend
          items={groups.map((g) => ({ key: g.key, label: g.label, color: g.color, kind: "bar" }))}
        />
      )}
    </div>
  );
}
