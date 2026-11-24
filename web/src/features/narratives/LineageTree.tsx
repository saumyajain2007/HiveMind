import { useState } from "react";

import { useSize } from "@/components/charts/useSize";
import { linear, niceTicks } from "@/components/charts/scale";
import type { LineageItem } from "@/lib/api/results";

import { ORIGIN_LABEL } from "./origins";
import { simClock, TICKS_PER_DAY } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Marker shape per origin (identity never rests on colour alone). */
export function OriginGlyph({
  origin,
  cx,
  cy,
  r,
  ...rest
}: {
  origin: LineageItem["origin"];
  cx: number;
  cy: number;
  r: number;
} & React.SVGProps<SVGPathElement>) {
  let d: string;
  if (origin === "mutation")
    d = `M${cx},${cy - r * 1.2}L${cx + r * 1.1},${cy + r * 0.8}L${cx - r * 1.1},${cy + r * 0.8}Z`;
  else if (origin === "invention")
    d = `M${cx - r * 0.9},${cy - r * 0.9}h${r * 1.8}v${r * 1.8}h${-r * 1.8}Z`;
  else if (origin === "price_news")
    d = `M${cx},${cy - r * 1.1}L${cx + r * 1.1},${cy}L${cx},${cy + r * 1.1}L${cx - r * 1.1},${cy}Z`;
  else d = `M${cx - r},${cy}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0`;
  return <path d={d} {...rest} />;
}

/**
 * Narrative lineage: x = born, y = sentiment, curved links to parents, size = final awareness,
 * shape = origin, colour = family. Hovering an item highlights its whole family; clicking selects it.
 */
export function LineageTree({
  items,
  nTicks,
  nNodes,
  colorOf,
  selected,
  onSelect,
}: {
  items: LineageItem[];
  nTicks: number;
  nNodes: number;
  colorOf: (root: number) => string;
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  const [ref, w] = useSize<HTMLDivElement>();
  const [hoverRoot, setHoverRoot] = useState<number | null>(null);
  const H = 380;
  const M = { top: 16, right: 44, bottom: 26, left: 12 };
  const width = Math.max(w, 300);
  const sx = linear([0, nTicks], [M.left, width - M.right]);
  const sy = linear([-1.1, 1.1], [H - M.bottom, M.top]);
  const byId = new Map(items.map((i) => [i.id, i]));
  const r = (i: LineageItem) => 4 + 16 * Math.sqrt(i.final_aware / Math.max(1, nNodes));
  const focus = hoverRoot ?? (selected != null ? (byId.get(selected)?.root ?? null) : null);
  const dim = (i: LineageItem) => focus != null && i.root !== focus;
  return (
    <div ref={ref} className="w-full">
      {w > 0 && (
        <svg
          width={width}
          height={H}
          role="group"
          aria-label={`Lineage of ${items.length} items: born on x, sentiment on y`}
        >
          {niceTicks(-1, 1, 4).map((t) => (
            <g key={t}>
              <line
                x1={M.left}
                x2={width - M.right}
                y1={sy(t)}
                y2={sy(t)}
                stroke={t === 0 ? "var(--axis)" : "var(--grid)"}
              />
              <text
                x={width - M.right + 6}
                y={sy(t)}
                dy="0.32em"
                className="fill-muted-foreground font-mono text-[10px]"
              >
                {t > 0 ? `+${t}` : t}
              </text>
            </g>
          ))}
          {Array.from({ length: Math.ceil(nTicks / TICKS_PER_DAY) }, (_, d) => (
            <text
              key={d}
              x={sx(d * TICKS_PER_DAY) + 4}
              y={H - 8}
              className="fill-muted-foreground font-mono text-[10px]"
            >
              Day {d + 1}
            </text>
          ))}
          <text x={width - M.right + 6} y={M.top - 4} className="fill-muted-foreground text-[10px]">
            bullish
          </text>
          <text
            x={width - M.right + 6}
            y={H - M.bottom + 12}
            className="fill-muted-foreground text-[10px]"
          >
            bearish
          </text>
          {items
            .filter((i) => i.parent >= 0 && byId.has(i.parent))
            .map((i) => {
              const p = byId.get(i.parent)!;
              const x0 = sx(p.born);
              const y0 = sy(p.sentiment);
              const x1 = sx(i.born);
              const y1 = sy(i.sentiment);
              return (
                <path
                  key={`l${i.id}`}
                  d={`M${x0},${y0} C${(x0 + x1) / 2},${y0} ${(x0 + x1) / 2},${y1} ${x1},${y1}`}
                  fill="none"
                  stroke={colorOf(i.root)}
                  strokeWidth={2}
                  strokeOpacity={dim(i) ? 0.12 : 0.7}
                />
              );
            })}
          {[...items]
            .sort((a, b) => b.final_aware - a.final_aware)
            .map((i) => {
              const on = selected === i.id;
              return (
                <g
                  key={i.id}
                  role="button"
                  tabIndex={0}
                  aria-pressed={on}
                  aria-label={`#${i.id} ${i.label ?? i.kind}: ${ORIGIN_LABEL[i.origin]}, born ${simClock(i.born).label}, sentiment ${i.sentiment.toFixed(2)}, ${i.final_aware} aware`}
                  className="cursor-pointer outline-none [&:focus-visible>path]:stroke-[var(--ring)]"
                  onPointerEnter={() => setHoverRoot(i.root)}
                  onPointerLeave={() => setHoverRoot(null)}
                  onFocus={() => setHoverRoot(i.root)}
                  onBlur={() => setHoverRoot(null)}
                  onClick={() => onSelect(i.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(i.id);
                    }
                  }}
                >
                  <OriginGlyph
                    origin={i.origin}
                    cx={sx(i.born)}
                    cy={sy(i.sentiment)}
                    r={r(i)}
                    fill={colorOf(i.root)}
                    fillOpacity={dim(i) ? 0.15 : 0.9}
                    stroke={on ? "var(--foreground)" : "var(--card)"}
                    strokeWidth={on ? 2.5 : 2}
                  />
                  <title>{`#${i.id} ${i.label ?? i.kind} · ${ORIGIN_LABEL[i.origin]}`}</title>
                </g>
              );
            })}
        </svg>
      )}
      <ul className={cn("mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground")}>
        {(Object.keys(ORIGIN_LABEL) as LineageItem["origin"][]).map((o) => (
          <li key={o} className="inline-flex items-center gap-1.5">
            <svg width={14} height={14} aria-hidden>
              <OriginGlyph origin={o} cx={7} cy={7} r={5} fill="var(--muted-foreground)" />
            </svg>
            {ORIGIN_LABEL[o]}
          </li>
        ))}
        <li>Size: final awareness · colour: family</li>
      </ul>
    </div>
  );
}
