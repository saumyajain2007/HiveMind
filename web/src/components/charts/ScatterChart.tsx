import { useState } from "react";

import { cn } from "@/lib/utils";

import { extent, linear, niceTicks } from "./scale";
import { useSize } from "./useSize";

export interface ScatterPoint {
  x: number;
  y: number;
  label: string;
  highlight?: boolean;
}

/**
 * Points (≥ 8px markers with a 2px surface ring) on one x and one y axis. The highlighted point
 * (e.g. the best trial) is drawn larger in the accent; every point has a hover readout.
 */
export function ScatterChart({
  points,
  height = 200,
  xLabel,
  yLabel,
  xFormat = (v) => v.toFixed(2),
  yFormat = (v) => v.toFixed(3),
  label,
  className,
  color = "var(--fundamental)",
  truth,
}: {
  points: ScatterPoint[];
  height?: number;
  xLabel: string;
  yLabel: string;
  xFormat?: (v: number) => string;
  yFormat?: (v: number) => string;
  label: string;
  className?: string;
  color?: string;
  /** Optional reference x value drawn as a dashed line (e.g. the true parameter). */
  truth?: number;
}) {
  const [ref, w] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const width = Math.max(w, 160);
  const M = { top: 10, right: 46, bottom: 30, left: 8 };
  const xd = extent([points.map((p) => p.x), truth != null ? [truth] : []]);
  const yd = extent([points.map((p) => p.y)]);
  const sx = linear(xd, [M.left + 6, width - M.right]);
  const sy = linear(yd, [height - M.bottom, M.top]);
  const best = points.find((p) => p.highlight);
  return (
    <div className={cn("min-w-0", className)}>
      <div
        ref={ref}
        className="relative w-full"
        style={{ height }}
        role="img"
        aria-label={`${label}: ${points.length} points${best ? `; best ${best.label}` : ""}`}
      >
        {w > 0 && (
          <svg width={width} height={height}>
            {niceTicks(yd[0], yd[1], 3).map((t) => (
              <g key={t}>
                <line x1={M.left} x2={width - M.right} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" />
                <text
                  x={width - M.right + 6}
                  y={sy(t)}
                  dy="0.32em"
                  className="fill-muted-foreground font-mono text-[10px]"
                >
                  {yFormat(t)}
                </text>
              </g>
            ))}
            {niceTicks(xd[0], xd[1], Math.max(2, Math.round(width / 90))).map((t) => (
              <text
                key={t}
                x={sx(t)}
                y={height - 14}
                textAnchor="middle"
                className="fill-muted-foreground font-mono text-[10px]"
              >
                {xFormat(t)}
              </text>
            ))}
            <text x={M.left} y={height - 2} className="fill-muted-foreground text-[10px]">
              {xLabel} →
            </text>
            <text
              x={width - M.right + 6}
              y={M.top - 2}
              className="fill-muted-foreground text-[10px]"
            >
              {yLabel}
            </text>
            {truth != null && (
              <line
                x1={sx(truth)}
                x2={sx(truth)}
                y1={M.top}
                y2={height - M.bottom}
                stroke="var(--foreground)"
                strokeOpacity={0.5}
                strokeDasharray="4 3"
              />
            )}
            {points.map((p, i) => (
              <circle
                key={i}
                cx={sx(p.x)}
                cy={sy(p.y)}
                r={p.highlight ? 6.5 : 4.5}
                fill={p.highlight ? "var(--primary)" : color}
                fillOpacity={p.highlight ? 1 : 0.75}
                stroke="var(--card)"
                strokeWidth={2}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
              >
                <title>{p.label}</title>
              </circle>
            ))}
          </svg>
        )}
        {hover != null && points[hover] && (
          <div className="pointer-events-none absolute top-1 left-2 rounded-md border bg-popover/95 px-2 py-1 text-xs shadow">
            {points[hover]!.label}
          </div>
        )}
      </div>
    </div>
  );
}
