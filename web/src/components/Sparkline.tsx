import { useCallback, useId, useLayoutEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";

export interface SparklineProps {
  values: number[];
  /** Optional dashed reference series on the same axis (e.g. fundamental value). */
  reference?: number[];
  referenceLabel?: string;
  label: string;
  /** Pixel height, or "fill" to take the container's height (give the wrapper a height). */
  height?: number | "fill";
  /** Recessive gridlines with low / mid / high value labels on the right. */
  showRange?: boolean;
  /** CSS colour of the line; defaults to the primary accent. */
  color?: string;
  /** Last `highlight` points drawn in the accent, the rest in the de-emphasis ink. */
  highlight?: number;
  area?: boolean;
  /** Crosshair + readout on hover / keyboard focus. */
  interactive?: boolean;
  format?: (v: number) => string;
  xLabel?: (index: number) => string;
  className?: string;
}

function useSize<T extends HTMLElement>(): [React.RefObject<T | null>, number, number] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setSize({ w: el.clientWidth, h: el.clientHeight });
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      if (entry) setSize({ w: entry.contentRect.width, h: entry.contentRect.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size.w, size.h];
}

/**
 * Small line chart: 2px line, a ringed end dot, an optional faint area and an optional
 * dashed reference line on the same axis. Measures its own width so strokes and markers stay
 * crisp at any size. The accessible name summarises first, last, min and max.
 */
export function Sparkline({
  values,
  reference,
  referenceLabel = "Reference",
  label,
  height: heightProp = 36,
  showRange = false,
  color = "var(--primary)",
  highlight,
  area = true,
  interactive = false,
  format = (v) => v.toFixed(2),
  xLabel = (i) => `#${i + 1}`,
  className,
}: SparklineProps) {
  const [ref, boxWidth, boxHeight] = useSize<HTMLDivElement>();
  const fill = heightProp === "fill";
  const height = fill ? Math.max(120, boxHeight) : heightProp;
  const labelGutter = showRange ? 56 : 0; // room for value labels on the right
  const width = Math.max(0, boxWidth - labelGutter);
  const gradId = useId();
  const [hover, setHover] = useState<number | null>(null);
  const pad = 5; // room for the end dot and its ring

  const geom = useMemo(() => {
    const all = reference ? [...values, ...reference] : values;
    const finite = all.filter(Number.isFinite);
    if (values.length < 2 || finite.length === 0 || width <= 0) return null;
    let lo = Math.min(...finite);
    let hi = Math.max(...finite);
    if (hi - lo < 1e-12) {
      lo -= 1;
      hi += 1;
    }
    const n = values.length;
    const x = (i: number) => pad + (i / (n - 1)) * (width - 2 * pad);
    const y = (v: number) => pad + (1 - (v - lo) / (hi - lo)) * (height - 2 * pad);
    const path = (vs: number[], from = 0) =>
      vs
        .map((v, i) => [i + from, v] as const)
        .filter(([, v]) => Number.isFinite(v))
        .map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
        .join("");
    const h = highlight ? Math.min(highlight, n - 1) : 0;
    const split = n - 1 - h;
    return {
      x,
      y,
      line: path(values),
      history: h ? path(values.slice(0, split + 1)) : null,
      current: h ? path(values.slice(split), split) : null,
      ref: reference ? path(reference) : null,
      area: `${path(values)}L${x(n - 1).toFixed(1)},${height - pad}L${x(0).toFixed(1)},${height - pad}Z`,
      ticks: [hi, (hi + lo) / 2, lo],
    };
  }, [values, reference, width, height, highlight]);

  const summary = useMemo(() => {
    const f = values.filter(Number.isFinite);
    if (!f.length) return `${label}: no data`;
    return `${label}: ${f.length} points, from ${format(f[0]!)} to ${format(f[f.length - 1]!)}, low ${format(Math.min(...f))}, high ${format(Math.max(...f))}`;
  }, [values, label, format]);

  const onMove = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      if (!geom || values.length < 2) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const t = (e.clientX - rect.left - pad) / Math.max(1, rect.width - 2 * pad);
      setHover(Math.max(0, Math.min(values.length - 1, Math.round(t * (values.length - 1)))));
    },
    [geom, values.length],
  );

  const onKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (!values.length) return;
      if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? values.length - 1) - 1));
      else if (e.key === "ArrowRight")
        setHover((h) => Math.min(values.length - 1, (h ?? values.length - 1) + 1));
      else if (e.key === "Escape") setHover(null);
      else return;
      e.preventDefault();
    },
    [values.length],
  );

  const lastIdx = values.length - 1;
  const last = values[lastIdx];
  const hv = hover != null ? values[hover] : undefined;

  return (
    <div
      ref={ref}
      className={cn("relative w-full", fill && "min-h-[120px]", className)}
      style={fill ? undefined : { height }}
    >
      {geom && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={summary}
          tabIndex={interactive ? 0 : undefined}
          onPointerMove={interactive ? onMove : undefined}
          onPointerLeave={interactive ? () => setHover(null) : undefined}
          onKeyDown={interactive ? onKey : undefined}
          onBlur={interactive ? () => setHover(null) : undefined}
          className={cn(
            "block overflow-visible",
            fill && "absolute top-0 left-0", // never let the SVG drive the container's height
            interactive &&
              "cursor-crosshair rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
          )}
        >
          <defs>
            <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.22} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          {showRange &&
            geom.ticks.map((v, i) => (
              <g key={i} aria-hidden>
                <line
                  x1={0}
                  x2={width}
                  y1={geom.y(v)}
                  y2={geom.y(v)}
                  stroke={i === 2 ? "var(--axis)" : "var(--grid)"}
                  strokeWidth={1}
                />
                <text
                  x={width + 8}
                  y={geom.y(v)}
                  dy="0.32em"
                  className="tabular fill-muted-foreground font-mono text-[10px]"
                >
                  {format(v)}
                </text>
              </g>
            ))}
          {area && <path d={geom.area} fill={`url(#${gradId})`} />}
          {geom.ref && (
            <path
              d={geom.ref}
              fill="none"
              stroke="var(--fundamental)"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              strokeLinecap="round"
            />
          )}
          {geom.history ? (
            <>
              <path
                d={geom.history}
                fill="none"
                stroke="var(--muted-foreground)"
                strokeOpacity={0.55}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              <path
                d={geom.current ?? ""}
                fill="none"
                stroke={color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            </>
          ) : (
            <path
              d={geom.line}
              fill="none"
              stroke={color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          )}
          {last != null && Number.isFinite(last) && hover == null && (
            <circle
              cx={geom.x(lastIdx)}
              cy={geom.y(last)}
              r={4}
              fill={color}
              stroke="var(--card)"
              strokeWidth={2}
            />
          )}
          {hover != null && hv != null && Number.isFinite(hv) && (
            <g aria-hidden>
              <line
                x1={geom.x(hover)}
                x2={geom.x(hover)}
                y1={0}
                y2={height}
                stroke="var(--axis)"
                strokeWidth={1}
              />
              <circle
                cx={geom.x(hover)}
                cy={geom.y(hv)}
                r={4}
                fill={color}
                stroke="var(--card)"
                strokeWidth={2}
              />
            </g>
          )}
        </svg>
      )}
      {interactive && hover != null && hv != null && geom && (
        <div
          role="status"
          className="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full rounded-md border border-border-strong bg-popover px-2 py-1 text-xs whitespace-nowrap text-popover-foreground shadow-lg"
          style={{ left: Math.min(Math.max(geom.x(hover), 60), width - 60) }}
        >
          <span className="text-muted-foreground">{xLabel(hover)}</span>{" "}
          <span className="tabular font-mono font-medium">{format(hv)}</span>
          {reference && reference[hover] != null && Number.isFinite(reference[hover]) && (
            <span className="ml-2 text-muted-foreground">
              {referenceLabel}{" "}
              <span className="tabular font-mono">{format(reference[hover]!)}</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
