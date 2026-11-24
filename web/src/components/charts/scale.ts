/** Minimal linear scales and "nice" ticks for the SVG charts. */

export interface Linear {
  (v: number): number;
  domain: [number, number];
  range: [number, number];
  invert: (px: number) => number;
}

export function linear(domain: [number, number], range: [number, number]): Linear {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  const f = ((v: number) => r0 + (v - d0) * k) as Linear;
  f.domain = domain;
  f.range = range;
  f.invert = (px: number) => (k === 0 ? d0 : d0 + (px - r0) / k);
  return f;
}

/** Round step (1, 2, 2.5 or 5 × 10^k) giving about `count` ticks across [lo, hi]. */
export function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (lo === hi) return [lo];
  const raw = (hi - lo) / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const start = Math.ceil(lo / step - 1e-9) * step;
  const out: number[] = [];
  for (let v = start; v <= hi + step * 1e-9; v += step) out.push(Math.round(v / step) * step);
  return out;
}

/** [min, max] over finite values, padded by `pad` of the span (or ±1% when flat). */
export function extent(arrays: (number | null | undefined)[][], pad = 0.06): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const a of arrays)
    for (const v of a) {
      if (v == null || !Number.isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  if (!Number.isFinite(lo)) return [0, 1];
  const span = hi - lo || Math.abs(hi) * 0.02 || 1;
  return [lo - span * pad, hi + span * pad];
}

/** Index of the value in sorted `xs` nearest to `x`. */
export function nearestIndex(xs: number[], x: number): number {
  let lo = 0;
  let hi = xs.length - 1;
  if (hi < 0) return -1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid]! < x) lo = mid;
    else hi = mid;
  }
  return Math.abs(xs[lo]! - x) <= Math.abs(xs[hi]! - x) ? lo : hi;
}

/** Categorical hues (validated order, see DECISIONS #19), used for families and series identity. */
export const CATEGORICAL = [
  "var(--twitter)",
  "var(--reddit)",
  "var(--friendship)",
  "var(--instagram)",
  "var(--tiktok)",
  "var(--youtube)",
] as const;
export const OTHER = "var(--muted-foreground)";
export const DASHES = ["", "6 3", "2 3", "8 3 2 3", "1 2", "10 4"] as const;
