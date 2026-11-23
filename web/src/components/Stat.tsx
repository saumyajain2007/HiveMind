import type { ReactNode } from "react";

import { CountUp } from "@/components/CountUp";
import { Delta } from "@/components/Delta";
import { Sparkline } from "@/components/Sparkline";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCompact } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface StatProps {
  /** Sentence case, no trailing colon. */
  label: string;
  value: number | null | undefined;
  format?: (n: number) => string;
  delta?: number | null;
  deltaFormat?: (x: number) => string;
  /** The period the delta compares against, e.g. "vs open". */
  period?: string;
  upIsGood?: boolean;
  trend?: number[];
  trendLabel?: string;
  badge?: ReactNode;
  hint?: ReactNode;
  loading?: boolean;
  className?: string;
}

/**
 * Stat tile: label, a large count-up value, an optional signed delta against a named period,
 * and an optional trend sparkline (history in the de-emphasis ink, latest stretch in the accent).
 */
export function Stat({
  label,
  value,
  format = formatCompact,
  delta,
  deltaFormat,
  period,
  upIsGood = true,
  trend,
  trendLabel,
  badge,
  hint,
  loading = false,
  className,
}: StatProps) {
  return (
    <div
      className={cn(
        "panel-highlight flex min-w-0 flex-col gap-2 rounded-xl border bg-card p-4",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-xs font-medium text-muted-foreground">{label}</p>
        {badge}
      </div>
      {loading ? (
        <>
          <Skeleton className="h-7 w-24" />
          <Skeleton className="h-4 w-16" />
        </>
      ) : (
        <>
          <div className="flex items-baseline gap-2">
            <CountUp
              value={value}
              format={format}
              className="tabular font-mono text-2xl font-semibold tracking-tight"
            />
          </div>
          {(delta !== undefined || hint) && (
            <div className="flex min-h-4 items-center gap-2">
              {delta !== undefined && (
                <Delta value={delta} period={period} upIsGood={upIsGood} format={deltaFormat} />
              )}
              {hint && <span className="truncate text-xs text-muted-foreground">{hint}</span>}
            </div>
          )}
        </>
      )}
      {trend && trend.length > 1 && !loading && (
        <Sparkline
          values={trend}
          label={trendLabel ?? `${label} trend`}
          highlight={Math.max(1, Math.floor(trend.length / 4))}
          height={32}
        />
      )}
    </div>
  );
}
