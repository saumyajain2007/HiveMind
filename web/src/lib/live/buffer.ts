/**
 * Fixed-capacity ring buffer of numbers. Appending never allocates, so the live store can
 * take thousands of frames without touching React state per frame.
 */
export class SeriesBuffer {
  private data: Float64Array;
  private start = 0;
  private count = 0;

  constructor(readonly capacity: number) {
    if (capacity < 1) throw new Error("capacity must be >= 1");
    this.data = new Float64Array(capacity);
  }

  get length(): number {
    return this.count;
  }

  push(value: number): void {
    const end = (this.start + this.count) % this.capacity;
    this.data[end] = value;
    if (this.count < this.capacity) this.count += 1;
    else this.start = (this.start + 1) % this.capacity; // overwrite the oldest
  }

  /** i-th oldest value still held (0 = oldest). */
  at(i: number): number {
    if (i < 0 || i >= this.count) return Number.NaN;
    return this.data[(this.start + i) % this.capacity] as number;
  }

  last(): number {
    return this.count ? this.at(this.count - 1) : Number.NaN;
  }

  first(): number {
    return this.at(0);
  }

  /** Copy of the held values, oldest first; the last `n` only if given. */
  toArray(n?: number): number[] {
    const k = n === undefined ? this.count : Math.min(n, this.count);
    const out = new Array<number>(k);
    for (let i = 0; i < k; i++) out[i] = this.at(this.count - k + i);
    return out;
  }

  clear(): void {
    this.start = 0;
    this.count = 0;
  }
}
