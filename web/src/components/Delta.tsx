import { Minus, TrendingDown, TrendingUp } from "lucide-react";

import { formatSignedPct } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Signed change with an arrow, so direction never relies on colour alone. Colour = direction ×
 * whether up is good. Text uses the text tokens, never the mark colours.
 */
export function Delta({
  value,
  period,
  upIsGood = true,
  format = formatSignedPct,
  className,
}: {
  value: number | null | undefined;
  period?: string;
  upIsGood?: boolean;
  format?: (x: number) => string;
  className?: string;
}) {
  if (value == null || !Number.isFinite(value)) {
    return <span className={cn("text-xs text-muted-foreground", className)}>—</span>;
  }
  const flat = Math.abs(value) < 1e-9;
  const up = value > 0;
  const good = flat ? null : up === upIsGood;
  const Icon = flat ? Minus : up ? TrendingUp : TrendingDown;
  return (
    <span
      className={cn(
        "tabular inline-flex items-center gap-1 text-xs font-medium",
        good === null ? "text-muted-foreground" : good ? "text-bull-text" : "text-bear-text",
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      <span className="sr-only">{flat ? "unchanged" : up ? "up" : "down"}</span>
      {format(value)}
      {period && <span className="font-normal text-muted-foreground">{period}</span>}
    </span>
  );
}
