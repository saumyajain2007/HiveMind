import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
} from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  MouseEventParams,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { SentimentChip } from "@/components/badges";
import {
  formatPrice,
  MARKET_CLOSE_TICK,
  MARKET_OPEN_TICK,
  simClock,
  TICKS_PER_DAY,
} from "@/lib/format";
import type { ItemMeta } from "@/lib/live/store";
import { cn } from "@/lib/utils";

/** Monday 2025-01-06 00:00 UTC: tick 0. Only the axis labels use it. */
const EPOCH = Date.UTC(2025, 0, 6) / 1000;
const tickTime = (t: number) => (EPOCH + t * 15 * 60) as UTCTimestamp;
const isOpen = (t: number) => {
  const d = t % TICKS_PER_DAY;
  return d >= MARKET_OPEN_TICK && d < MARKET_CLOSE_TICK;
};
/** The open tick an event shows up at (events outside market hours land on the next open). */
function markerTick(t: number): number {
  const d = t % TICKS_PER_DAY;
  if (d < MARKET_OPEN_TICK) return t - d + MARKET_OPEN_TICK;
  if (d >= MARKET_CLOSE_TICK) return t - d + TICKS_PER_DAY + MARKET_OPEN_TICK;
  return t;
}

/** Canvas colours must be plain CSS colours: hex token + alpha as rgba(). */
function alpha(hex: string, a: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1]!, 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

export interface PriceChartProps {
  ticks: number[];
  price: number[];
  volume: number[];
  events: ItemMeta[];
  mode: "candles" | "line";
  /** Increments when an event is injected: the chart pulses. */
  pulseKey: number;
  className?: string;
}

/**
 * The cockpit's main chart (TradingView lightweight-charts): 15-minute candles or a line,
 * volume underneath and event markers (amber =
 * official / news, violet = rumour or narrative, grey = price headline). Only market hours are
 * drawn; the gaps between sessions mark the closed market.
 */
export function PriceChart({
  ticks,
  price,
  volume,
  events,
  mode,
  pulseKey,
  className,
}: PriceChartProps) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const s = useRef<{
    candles: ISeriesApi<"Candlestick">;
    line: ISeriesApi<"Line">;
    volume: ISeriesApi<"Histogram">;
    markers: ISeriesMarkersPluginApi<Time>;
    lineMarkers: ISeriesMarkersPluginApi<Time>;
  } | null>(null);
  const [hover, setHover] = useState<{
    x: number;
    y: number;
    w: number;
    items: ItemMeta[];
    tick: number;
  } | null>(null);
  const [theme, setTheme] = useState(0);
  const eventsRef = useRef(events);
  useEffect(() => {
    eventsRef.current = events;
  }, [events]);

  // create once
  useEffect(() => {
    const el = box.current!;
    const c = createChart(el, {
      autoSize: true,
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        // sim clock on the axis: "Day N" at a session start, HH:MM otherwise
        tickMarkFormatter: (time: Time) => {
          const c = simClock(Math.round(((time as number) - EPOCH) / 900));
          return c.hh * 60 + c.mm === MARKET_OPEN_TICK * 15 ? `Day ${c.day}` : c.label.slice(-5);
        },
      },
      localization: {
        priceFormatter: (p: number) => formatPrice(p),
        timeFormatter: (time: Time) => simClock(Math.round(((time as number) - EPOCH) / 900)).label,
      },
    });
    const candles = c.addSeries(CandlestickSeries, { priceLineVisible: true });
    const line = c.addSeries(LineSeries, { lineWidth: 2, priceLineVisible: false, visible: false });
    const vol = c.addSeries(HistogramSeries, {
      priceScaleId: "vol",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } });
    s.current = {
      candles,
      line,
      volume: vol,
      markers: createSeriesMarkers(candles, []),
      lineMarkers: createSeriesMarkers(line, []),
    };
    chart.current = c;
    const onMove = (p: MouseEventParams<Time>) => {
      if (!p.time || !p.point) return setHover(null);
      const t = Math.round(((p.time as number) - EPOCH) / 900);
      const items = eventsRef.current.filter((e) => markerTick(e.tick) === t);
      setHover(
        items.length ? { x: p.point.x, y: p.point.y, w: el.clientWidth, items, tick: t } : null,
      );
    };
    c.subscribeCrosshairMove(onMove);
    const mo = new MutationObserver(() => setTheme((v) => v + 1));
    mo.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "data-theme"],
    });
    return () => {
      mo.disconnect();
      c.unsubscribeCrosshairMove(onMove);
      c.remove();
      chart.current = null;
      s.current = null;
    };
  }, []);

  // colours follow the theme tokens
  useEffect(() => {
    const c = chart.current;
    const ss = s.current;
    if (!c || !ss) return;
    const fg = css("--muted-foreground");
    c.applyOptions({
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: fg,
        fontFamily: "JetBrains Mono Variable, ui-monospace, monospace",
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } },
      rightPriceScale: { borderColor: css("--axis") },
      timeScale: { borderColor: css("--axis") },
      crosshair: {
        vertLine: { color: fg, labelBackgroundColor: css("--surface-2") },
        horzLine: { color: fg, labelBackgroundColor: css("--surface-2") },
      },
    });
    const up = css("--bull");
    const down = css("--bear");
    ss.candles.applyOptions({
      upColor: up,
      downColor: down,
      borderUpColor: up,
      borderDownColor: down,
      wickUpColor: up,
      wickDownColor: down,
    });
    ss.line.applyOptions({ color: css("--primary") });
  }, [theme]);

  // data
  useEffect(() => {
    const ss = s.current;
    if (!ss) return;
    const candles = [];
    const lineData = [];
    const vols = [];
    const up = css("--bull");
    const down = css("--bear");
    let prev = price[0] ?? 0;
    for (let i = 0; i < ticks.length; i++) {
      const t = ticks[i]!;
      const p = price[i]!;
      if (isOpen(t)) {
        const time = tickTime(t);
        candles.push({
          time,
          open: prev,
          close: p,
          high: Math.max(prev, p),
          low: Math.min(prev, p),
        });
        lineData.push({ time, value: p });
        vols.push({ time, value: volume[i]!, color: alpha(p >= prev ? up : down, 0.45) });
      }
      prev = p;
    }
    ss.candles.setData(candles);
    ss.line.setData(lineData);
    ss.volume.setData(vols);
    const last = ticks[ticks.length - 1] ?? -1;
    const markers: SeriesMarker<Time>[] = events
      .filter((e) => markerTick(e.tick) <= last)
      .map((e) => {
        const narrative =
          e.origin === "mutation" ||
          e.origin === "invention" ||
          e.kind === "rumour" ||
          e.kind === "leak";
        const price_news = e.origin === "price_news";
        return {
          time: tickTime(markerTick(e.tick)),
          position: e.sentiment >= 0 ? ("aboveBar" as const) : ("belowBar" as const),
          shape: price_news
            ? ("square" as const)
            : narrative
              ? ("circle" as const)
              : ("arrowDown" as const),
          color: price_news
            ? css("--muted-foreground")
            : narrative
              ? css("--narrative")
              : css("--official"),
          text: price_news ? "" : `#${e.item}`,
          size: price_news ? 0.6 : 1,
        };
      })
      .sort((a, b) => (a.time as number) - (b.time as number));
    chart.current?.timeScale().fitContent();
    ss.markers.setMarkers(mode === "candles" ? markers : []);
    ss.lineMarkers.setMarkers(mode === "line" ? markers : []);
  }, [ticks, price, volume, events, mode, theme]);

  useEffect(() => {
    s.current?.candles.applyOptions({ visible: mode === "candles" });
    s.current?.line.applyOptions({ visible: mode === "line" });
  }, [mode]);

  const last = ticks.length ? ticks[ticks.length - 1]! : 0;
  return (
    <div className={cn("relative h-full min-h-[300px]", className)}>
      <div
        key={pulseKey}
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-0 z-10 rounded-lg",
          pulseKey > 0 && "motion-safe:animate-[pulse-ring_1.2s_ease-out_1]",
        )}
      />
      <div
        ref={box}
        className="h-full w-full"
        role="img"
        aria-label={`Price over the run: ${ticks.length} points, last ${formatPrice(price[price.length - 1])} at ${simClock(last).label}; ${events.length} events marked`}
      />
      {hover && (
        <div
          className="pointer-events-none absolute z-20 w-64 rounded-lg border bg-popover/95 p-2.5 text-xs shadow-xl backdrop-blur"
          style={{
            left: Math.min(hover.x + 14, hover.w - 270),
            top: Math.max(4, hover.y - 20),
          }}
        >
          <p className="mb-1 font-mono text-[10px] text-muted-foreground">
            {simClock(hover.tick).label}
          </p>
          {hover.items.map((e) => (
            <div
              key={e.item}
              className="mt-1 flex flex-col gap-1 border-t pt-1 first:mt-0 first:border-0 first:pt-0"
            >
              <p className="font-medium">{e.label}</p>
              <p className="flex items-center gap-2 text-muted-foreground">
                #{e.item} ·{" "}
                {e.origin === "event" ? `${e.kind} · ${e.seeding}` : e.origin.replace("_", " ")}
                <SentimentChip value={e.sentiment} compact className="ml-auto" />
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
