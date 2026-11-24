/** Small statistics helpers for the Monte Carlo view. */

export function quantile(sorted: number[], q: number): number {
  if (!sorted.length) return Number.NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo]! + (sorted[hi]! - sorted[lo]!) * (pos - lo);
}

export function histogram(values: number[], lo: number, hi: number, bins: number) {
  const width = (hi - lo) / bins;
  const counts = new Array<number>(bins).fill(0);
  for (const v of values) {
    const i = Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / width)));
    counts[i]! += 1;
  }
  const n = Math.max(1, values.length);
  return counts.map((c, i) => ({
    x0: lo + i * width,
    x1: lo + (i + 1) * width,
    density: c / n / width,
  }));
}

/** Gaussian kernel density with Silverman's bandwidth. */
export function kde(values: number[], xs: number[]): number[] {
  const n = values.length;
  if (n < 2) return xs.map(() => 0);
  const mean = values.reduce((a, b) => a + b, 0) / n;
  const sd = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) || 1e-9;
  const h = 1.06 * sd * n ** -0.2;
  const k = 1 / (n * h * Math.sqrt(2 * Math.PI));
  return xs.map((x) => k * values.reduce((a, v) => a + Math.exp(-0.5 * ((x - v) / h) ** 2), 0));
}

/** Density of p0 · exp(N(−½s², s²)), the driftless random-walk benchmark (s = σ_daily · √days). */
export function lognormalPdf(x: number, p0: number, s: number): number {
  if (x <= 0 || s <= 0) return 0;
  const mu = Math.log(p0) - 0.5 * s * s;
  return Math.exp(-((Math.log(x) - mu) ** 2) / (2 * s * s)) / (x * s * Math.sqrt(2 * Math.PI));
}
