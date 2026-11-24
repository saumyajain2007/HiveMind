import { TICKS_PER_DAY } from "@/lib/format";

/** "2 10:30 | Acme misses estimates" → day 2, 10:30; a bare line lands at 09:00 on day 1. */
export function parseLine(line: string): { text: string; tick: number } {
  const m = /^\s*(?:d(?:ay)?\s*)?(\d+)\s+(\d{1,2}):(\d{2})\s*\|\s*(.+)$/i.exec(line);
  if (!m) return { text: line.trim(), tick: 36 };
  const day = Math.max(1, Number(m[1]));
  const tick = (day - 1) * TICKS_PER_DAY + Math.floor((Number(m[2]) * 60 + Number(m[3])) / 15);
  return { text: m[4]!.trim(), tick };
}
