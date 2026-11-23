/** Number, time and simulation-clock formatting. All output is plain text for tabular figures. */

export const TICKS_PER_DAY = 96;
export const MINUTES_PER_TICK = 15;
export const MARKET_OPEN_TICK = 38;
export const MARKET_CLOSE_TICK = 64;

const compactFmt = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const intFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** 1,284 · 12.9K · 4.2M (auto-compact above 10,000). */
export function formatCompact(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return Math.abs(n) < 10_000 ? intFmt.format(n) : compactFmt.format(n);
}

export function formatPrice(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Signed percentage: +1.24% / −0.80%. `x` is a fraction (0.0124). Uses a true minus sign. */
export function formatSignedPct(x: number | null | undefined, digits = 2): string {
  if (x == null || !Number.isFinite(x)) return "—";
  const s = Math.abs(x * 100).toFixed(digits);
  if (Number(s) === 0) return `0.${"0".repeat(digits)}%`;
  return `${x > 0 ? "+" : "−"}${s}%`;
}

export function formatPct(x: number | null | undefined, digits = 1): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

/** Signed number with a true minus sign: +0.42 / −0.18. */
export function formatSigned(x: number | null | undefined, digits = 2): string {
  if (x == null || !Number.isFinite(x)) return "—";
  const s = Math.abs(x).toFixed(digits);
  if (Number(s) === 0) return (0).toFixed(digits);
  return `${x > 0 ? "+" : "−"}${s}`;
}

export interface SimClock {
  day: number; // 1-based
  hh: number;
  mm: number;
  open: boolean;
  label: string; // "Day 2 · 10:15"
}

export function simClock(tick: number): SimClock {
  const t = Math.max(0, Math.floor(tick));
  const day = Math.floor(t / TICKS_PER_DAY) + 1;
  const inDay = t % TICKS_PER_DAY;
  const minutes = inDay * MINUTES_PER_TICK;
  const hh = Math.floor(minutes / 60);
  const mm = minutes % 60;
  const open = inDay >= MARKET_OPEN_TICK && inDay < MARKET_CLOSE_TICK;
  return {
    day,
    hh,
    mm,
    open,
    label: `Day ${day} · ${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`,
  };
}

const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function formatRelative(date: string | Date, now: Date = new Date()): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const sec = Math.round((d.getTime() - now.getTime()) / 1000);
  const abs = Math.abs(sec);
  if (abs < 60) return rtf.format(sec, "second");
  if (abs < 3600) return rtf.format(Math.round(sec / 60), "minute");
  if (abs < 86_400) return rtf.format(Math.round(sec / 3600), "hour");
  return rtf.format(Math.round(sec / 86_400), "day");
}

export function shortHash(hash: string, n = 8): string {
  return hash.slice(0, n);
}
