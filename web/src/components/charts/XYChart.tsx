import { useCallback, useId, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Legend } from "./Legend";
import type { LegendItem } from "./Legend";
import { extent, linear, nearestIndex, niceTicks } from "./scale";
import type { Linear } from "./scale";
import { useSize } from "./useSize";

export interface Series {
  key: string;
  label: string;
  values: (number | null)[];
  color: string;
  dash?: string;
  width?: number;
  /** Faint fill from the line down to the bottom of the plot. */
  area?: boolean;
  /** Drawn thin and faint, left out of the legend and the tooltip (e.g. sample paths). */
  ghost?: boolean;
}

export interface Band {
  key: string;
  label: string;
  lo: number[];
  hi: number[];
  color: string;
  opacity?: number;
}

export interface Marker {
  x: number;
  label: string;
  color: string;
  /** Short text drawn at the top of the marker line. */
  tag?: string;
}

export interface XYChartProps {
  x: number[];
  series: Series[];
  bands?: Band[];
  markers?: Marker[];
  /** Shaded x ranges (e.g. market closed). */
  shades?: { x0: number; x1: number }[];
  height?: number;
  yDomain?: [number, number];
  zeroLine?: number;
  xFormat?: (x: number) => string;
  yFormat?: (y: number) => string;
  xTicks?: number[];
  label: string;
  legend?: boolean;
  className?: string;
  /** Extra SVG drawn inside the plot area (receives the scales). */
  overlay?: (sx: Linear, sy: Linear) => ReactNode;
  onHover?: (index: number | null) => void;
}

const M = { top: 10, right: 56, bottom: 22, left: 8 };

function path(xs: number[], ys: (number | null)[], sx: Linear, sy: Linear): string {
  let d = "";
  let pen = false;
  for (let i = 0; i < xs.length; i++) {
    const y = ys[i];
    if (y == null || !Number.isFinite(y)) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${sx(xs[i]!).toFixed(1)},${sy(y).toFixed(1)}`;
    pen = true;
  }
  return d;
}

function bandPath(xs: number[], lo: number[], hi: number[], sx: Linear, sy: Linear): string {
  if (!xs.length) return "";
  let d = `M${sx(xs[0]!).toFixed(1)},${sy(hi[0]!).toFixed(1)}`;
  for (let i = 1; i < xs.length; i++) d += `L${sx(xs[i]!).toFixed(1)},${sy(hi[i]!).toFixed(1)}`;
  for (let i = xs.length - 1; i >= 0; i--)
    d += `L${sx(xs[i]!).toFixed(1)},${sy(lo[i]!).toFixed(1)}`;
  return d + "Z";
}

/**
 * Line / area / band chart with one y axis (right), recessive grid, optional event markers and
 * shaded ranges, a legend, and a crosshair tooltip that follows the pointer or ← → keys.
 */
export function XYChart({
  x,
  series,
  bands = [],
  markers = [],
  shades = [],
  height = 260,
  yDomain,
  zeroLine,
  xFormat = (v) => String(v),
  yFormat = (v) => v.toFixed(2),
  xTicks,
  label,
  legend = true,
  className,
  overlay,
  onHover,
}: XYChartProps) {
  const [ref, w] = useSize<HTMLDivElement>();
  const clipId = useId();
  const [hover, setHover] = useState<number | null>(null);
  const width = Math.max(w, 120);
  const plotW = width - M.left - M.right;
  const plotH = height - M.top - M.bottom;

  const { sx, sy, yt, xt } = useMemo(() => {
    const ys = [...series.map((s) => s.values), ...bands.flatMap((b) => [b.lo, b.hi])];
    const dom = yDomain ?? extent(ys);
    const sx = linear([x[0] ?? 0, x[x.length - 1] ?? 1], [M.left, M.left + plotW]);
    const sy = linear(dom, [M.top + plotH, M.top]);
    const yt = niceTicks(dom[0], dom[1], Math.max(2, Math.round(plotH / 50)));
    const xt = xTicks ?? niceTicks(sx.domain[0], sx.domain[1], Math.max(2, Math.round(plotW / 90)));
    return { sx, sy, yt, xt };
  }, [x, series, bands, yDomain, plotW, plotH, xTicks]);

  const setIdx = useCallback(
    (i: number | null) => {
      setHover(i);
      onHover?.(i);
    },
    [onHover],
  );

  const visible = series.filter((s) => !s.ghost);
  const last = (s: Series) => {
    for (let i = s.values.length - 1; i >= 0; i--) {
      const v = s.values[i];
      if (v != null && Number.isFinite(v)) return v;
    }
    return null;
  };
  const summary = visible
    .map((s) => {
      const v = last(s);
      return `${s.label}: last ${v == null ? "n/a" : yFormat(v)}`;
    })
    .join("; ");

  const legendItems: LegendItem[] = [
    ...bands.map((b) => ({ key: b.key, label: b.label, color: b.color, kind: "band" as const })),
    ...visible.map((s) => ({ key: s.key, label: s.label, color: s.color, dash: s.dash })),
  ];
  const hx = hover != null ? x[hover] : undefined;

  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      <div
        ref={ref}
        className="relative w-full outline-none focus-visible:rounded-md focus-visible:ring-2 focus-visible:ring-ring/60"
        style={{ height }}
        role="img"
        aria-label={`${label}. ${summary}`}
        tabIndex={0}
        onKeyDown={(e) => {
          if (!x.length) return;
          if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
            e.preventDefault();
            const step = e.shiftKey ? 10 : 1;
            const cur = hover ?? (e.key === "ArrowLeft" ? x.length : -1);
            setIdx(
              Math.max(0, Math.min(x.length - 1, cur + (e.key === "ArrowLeft" ? -step : step))),
            );
          } else if (e.key === "Escape") setIdx(null);
        }}
        onBlur={() => setIdx(null)}
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const px = e.clientX - r.left;
          if (px < M.left || px > M.left + plotW) return setIdx(null);
          setIdx(nearestIndex(x, sx.invert(px)));
        }}
        onPointerLeave={() => setIdx(null)}
      >
        {w > 0 && (
          <svg width={width} height={height} className="block overflow-visible">
            <defs>
              <clipPath id={clipId}>
                <rect x={M.left} y={M.top} width={plotW} height={plotH} />
              </clipPath>
            </defs>
            {shades.map((s, i) => (
              <rect
                key={i}
                x={sx(s.x0)}
                y={M.top}
                width={Math.max(0, sx(s.x1) - sx(s.x0))}
                height={plotH}
                fill="var(--muted)"
                opacity={0.45}
              />
            ))}
            {yt.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={M.left + plotW} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" />
                <text
                  x={M.left + plotW + 6}
                  y={sy(t)}
                  dy="0.32em"
                  className="fill-muted-foreground font-mono text-[10px]"
                >
                  {yFormat(t)}
                </text>
              </g>
            ))}
            {xt.map((t) => (
              <text
                key={t}
                x={sx(t)}
                y={height - 6}
                textAnchor="middle"
                className="fill-muted-foreground font-mono text-[10px]"
              >
                {xFormat(t)}
              </text>
            ))}
            {zeroLine != null && (
              <line
                x1={M.left}
                x2={M.left + plotW}
                y1={sy(zeroLine)}
                y2={sy(zeroLine)}
                stroke="var(--axis)"
                strokeWidth={1}
              />
            )}
            <g clipPath={`url(#${clipId})`}>
              {bands.map((b) => (
                <path
                  key={b.key}
                  d={bandPath(x, b.lo, b.hi, sx, sy)}
                  fill={b.color}
                  opacity={b.opacity ?? 0.2}
                />
              ))}
              {series
                .filter((s) => s.area && !s.ghost)
                .map((s) => {
                  const d = path(x, s.values, sx, sy);
                  if (!d) return null;
                  const first = s.values.findIndex((v) => v != null);
                  const lastI = s.values.length - 1;
                  return (
                    <path
                      key={`${s.key}-area`}
                      d={`${d}L${sx(x[lastI]!)},${M.top + plotH}L${sx(x[first]!)},${M.top + plotH}Z`}
                      fill={s.color}
                      opacity={0.1}
                    />
                  );
                })}
              {series.map((s) => (
                <path
                  key={s.key}
                  d={path(x, s.values, sx, sy)}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={s.ghost ? 1 : (s.width ?? 2)}
                  strokeOpacity={s.ghost ? 0.18 : 1}
                  strokeDasharray={s.dash || undefined}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ))}
              {overlay?.(sx, sy)}
            </g>
            {markers.map((m, i) => (
              <g key={i}>
                <line
                  x1={sx(m.x)}
                  x2={sx(m.x)}
                  y1={M.top}
                  y2={M.top + plotH}
                  stroke={m.color}
                  strokeWidth={1.5}
                  strokeDasharray="3 3"
                />
                <rect
                  x={sx(m.x) - 4}
                  y={M.top - 4}
                  width={8}
                  height={8}
                  transform={`rotate(45 ${sx(m.x)} ${M.top})`}
                  fill={m.color}
                  stroke="var(--card)"
                  strokeWidth={2}
                >
                  <title>{m.label}</title>
                </rect>
              </g>
            ))}
            {hover != null && hx != null && (
              <g pointerEvents="none">
                <line
                  x1={sx(hx)}
                  x2={sx(hx)}
                  y1={M.top}
                  y2={M.top + plotH}
                  stroke="var(--foreground)"
                  strokeOpacity={0.35}
                />
                {visible.map((s) => {
                  const v = s.values[hover];
                  return v == null || !Number.isFinite(v) ? null : (
                    <circle
                      key={s.key}
                      cx={sx(hx)}
                      cy={sy(v)}
                      r={4}
                      fill={s.color}
                      stroke="var(--card)"
                      strokeWidth={2}
                    />
                  );
                })}
              </g>
            )}
          </svg>
        )}
        {hover != null && hx != null && (
          <div
            className="pointer-events-none absolute top-1 z-10 min-w-36 rounded-md border bg-popover/95 px-2.5 py-1.5 text-xs shadow-lg backdrop-blur"
            style={sx(hx) > width / 2 ? { right: width - sx(hx) + 12 } : { left: sx(hx) + 12 }}
          >
            <p className="mb-1 font-mono text-[10px] text-muted-foreground">{xFormat(hx)}</p>
            {bands.map((b) => (
              <p key={b.key} className="flex justify-between gap-3">
                <span className="text-muted-foreground">{b.label}</span>
                <span className="tabular font-mono">
                  {yFormat(b.lo[hover]!)}–{yFormat(b.hi[hover]!)}
                </span>
              </p>
            ))}
            {visible.map((s) => {
              const v = s.values[hover];
              return (
                <p key={s.key} className="flex items-center justify-between gap-3">
                  <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                    <span className="size-2 rounded-full" style={{ background: s.color }} />
                    {s.label}
                  </span>
                  <span className="tabular font-mono">
                    {v == null || !Number.isFinite(v) ? "–" : yFormat(v)}
                  </span>
                </p>
              );
            })}
            {markers
              .filter((m) => Math.abs(sx(m.x) - sx(hx)) < 6)
              .map((m, i) => (
                <p key={i} className="mt-1 border-t pt-1 font-medium">
                  {m.label}
                </p>
              ))}
          </div>
        )}
      </div>
      {legend && legendItems.length > 1 && <Legend items={legendItems} />}
    </div>
  );
}
