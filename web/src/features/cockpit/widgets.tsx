import { motion } from "motion/react";

import { formatSigned } from "@/lib/format";
import { useMotionTransition } from "@/lib/motion";
import { sentimentLabel } from "@/lib/vocab";

/**
 * Semicircular diverging gauge for a value in [-1, 1]: coral (bearish) ← grey → teal (bullish).
 * The needle angle carries the value; the number and word repeat it in text.
 */
export function ConfidenceGauge({ value, label }: { value: number | null; label: string }) {
  const v = Math.max(-1, Math.min(1, value ?? 0));
  const transition = useMotionTransition({ type: "spring", stiffness: 120, damping: 18 });
  const R = 70;
  const cx = 90;
  const cy = 84;
  const arc = (a0: number, a1: number) => {
    const p = (a: number) => [cx + R * Math.cos(Math.PI - a), cy - R * Math.sin(Math.PI - a)];
    const [x0, y0] = p(a0);
    const [x1, y1] = p(a1);
    return `M${x0},${y0} A${R},${R} 0 0 1 ${x1},${y1}`;
  };
  const segs = 9;
  return (
    <figure
      className="flex flex-col items-center"
      aria-label={`${label}: ${sentimentLabel(v)} (${formatSigned(v)})`}
      role="img"
    >
      <svg width={180} height={100} viewBox="0 0 180 100" aria-hidden>
        {Array.from({ length: segs }, (_, i) => {
          const a0 = (i / segs) * Math.PI + 0.02;
          const a1 = ((i + 1) / segs) * Math.PI - 0.02;
          const mid = (i + 0.5) / segs; // 0 = bearish end
          const strength = Math.abs(mid - 0.5) * 2;
          const color = mid < 0.45 ? "var(--bear)" : mid > 0.55 ? "var(--bull)" : "var(--axis)";
          return (
            <path
              key={i}
              d={arc(a0, a1)}
              stroke={color}
              strokeOpacity={0.25 + 0.75 * strength}
              strokeWidth={12}
              fill="none"
              strokeLinecap="butt"
            />
          );
        })}
        <motion.g
          initial={false}
          animate={{ rotate: v * 90 }}
          transition={transition}
          style={{ originX: `${cx}px`, originY: `${cy}px` }}
        >
          <line
            x1={cx}
            y1={cy}
            x2={cx}
            y2={cy - R + 16}
            stroke="var(--foreground)"
            strokeWidth={2.5}
            strokeLinecap="round"
          />
        </motion.g>
        <circle cx={cx} cy={cy} r={5} fill="var(--foreground)" />
      </svg>
      <figcaption className="-mt-1 text-center">
        <span className="tabular block font-mono text-xl font-semibold">{formatSigned(v)}</span>
        <span className="text-xs text-muted-foreground">{sentimentLabel(v)}</span>
      </figcaption>
    </figure>
  );
}

/** Horizontal meter for retail order imbalance in [-1, 1] (sell pressure ← → buy pressure). */
export function ImbalanceMeter({ value }: { value: number | null }) {
  const v = Math.max(-1, Math.min(1, value ?? 0));
  const transition = useMotionTransition({ duration: 0.25 });
  return (
    <div
      className="flex flex-col gap-1.5"
      role="meter"
      aria-label="Retail order imbalance"
      aria-valuemin={-1}
      aria-valuemax={1}
      aria-valuenow={Number(v.toFixed(2))}
    >
      <div className="relative h-2.5 overflow-hidden rounded-full bg-muted">
        <span className="absolute top-0 left-1/2 h-full w-px bg-axis" />
        <motion.span
          className={
            v >= 0
              ? "absolute top-0 left-1/2 h-full rounded-r-full bg-bull"
              : "absolute top-0 right-1/2 h-full rounded-l-full bg-bear"
          }
          initial={false}
          animate={{ width: `${Math.abs(v) * 50}%` }}
          transition={transition}
        />
      </div>
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span>Selling</span>
        <span className="tabular font-mono text-foreground">{formatSigned(v)}</span>
        <span>Buying</span>
      </div>
    </div>
  );
}
