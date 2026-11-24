import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Rows × columns of values in [0, 1], one hue light → dark (sequential), with the value printed
 * in each cell so the reading never depends on colour. Cells are buttons for keyboard focus.
 */
export function Heatmap({
  rows,
  cols,
  values,
  format = (v) => `${Math.round(v * 100)}%`,
  label,
  className,
  rowColors,
}: {
  rows: string[];
  cols: string[];
  values: number[][];
  format?: (v: number) => string;
  label: string;
  className?: string;
  /** Optional identity swatch per row. */
  rowColors?: string[];
}) {
  const [active, setActive] = useState<[number, number] | null>(null);
  return (
    <div className={cn("min-w-0 overflow-x-auto", className)}>
      <table className="w-full border-separate border-spacing-0.5 text-xs" aria-label={label}>
        <thead>
          <tr>
            <th className="w-1/4" />
            {cols.map((c) => (
              <th
                key={c}
                scope="col"
                className="px-1 pb-1 text-center font-medium text-muted-foreground"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={r}>
              <th scope="row" className="truncate pr-2 text-left font-medium">
                <span className="inline-flex max-w-56 items-center gap-1.5">
                  {rowColors?.[ri] && (
                    <span
                      className="size-2 shrink-0 rounded-full"
                      style={{ background: rowColors[ri] }}
                    />
                  )}
                  <span className="truncate">{r}</span>
                </span>
              </th>
              {cols.map((c, ci) => {
                const v = values[ri]?.[ci] ?? 0;
                const pct = Math.round(Math.max(0, Math.min(1, v)) * 85 + 6);
                const on = active?.[0] === ri && active?.[1] === ci;
                return (
                  <td key={c} className="p-0">
                    <button
                      type="button"
                      className={cn(
                        "tabular h-9 w-full min-w-12 rounded-[4px] font-mono text-[11px] outline-none focus-visible:ring-2 focus-visible:ring-ring/70",
                        on && "ring-2 ring-foreground/50",
                      )}
                      style={{
                        background: `color-mix(in oklab, var(--bull) ${pct}%, var(--surface-2))`,
                      }}
                      aria-label={`${r}, ${c}: ${format(v)}`}
                      onPointerEnter={() => setActive([ri, ci])}
                      onPointerLeave={() => setActive(null)}
                      onFocus={() => setActive([ri, ci])}
                      onBlur={() => setActive(null)}
                    >
                      <span className="rounded-[3px] bg-card/85 px-1 py-px text-foreground">
                        {format(v)}
                      </span>
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
