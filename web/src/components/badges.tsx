import { Ban, CircleCheck, CircleX, Clock, FlaskConical, LoaderCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { WithTooltip } from "@/components/ui/tooltip";
import { PLATFORMS, sentimentLabel } from "@/lib/vocab";
import type { PlatformName } from "@/lib/vocab";
import { formatSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

// ----------------------------------------------------------------------------- placeholder

/** Marks a parameter that is a guess, not fitted to data (PLACEHOLDER in config.py). */
export function PlaceholderBadge({ className }: { className?: string }) {
  return (
    <WithTooltip label="Placeholder: a reasonable guess, not yet fitted to data" side="top">
      <span
        tabIndex={0}
        className={cn(
          "inline-flex items-center gap-1 rounded-full border border-official/40 bg-official/10 px-2 py-0.5 text-[10px] font-semibold tracking-wider text-official-text uppercase outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
          className,
        )}
      >
        <FlaskConical className="size-3" aria-hidden />
        Placeholder
      </span>
    </WithTooltip>
  );
}

// ----------------------------------------------------------------------------- sentiment

/**
 * Sentiment in [-1, 1]: a small diverging bar (coral ← grey → teal) plus a word and the
 * value, so the reading never depends on colour.
 */
export function SentimentChip({
  value,
  compact = false,
  className,
}: {
  value: number;
  compact?: boolean;
  className?: string;
}) {
  const v = Math.max(-1, Math.min(1, value));
  const tone = v <= -0.2 ? "text-bear-text" : v >= 0.2 ? "text-bull-text" : "text-muted-foreground";
  const width = `${Math.abs(v) * 50}%`;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border bg-surface-2 px-2 py-0.5 text-xs",
        className,
      )}
      aria-label={`Sentiment ${sentimentLabel(v)} (${formatSigned(v)})`}
    >
      <span aria-hidden className="relative h-1.5 w-10 overflow-hidden rounded-full bg-muted">
        <span className="absolute top-0 left-1/2 h-full w-px bg-axis" />
        <span
          className={cn(
            "absolute top-0 h-full rounded-full",
            v >= 0 ? "left-1/2 bg-bull" : "right-1/2 bg-bear",
          )}
          style={{ width }}
        />
      </span>
      {!compact && <span className={cn("font-medium", tone)}>{sentimentLabel(v)}</span>}
      <span className="tabular font-mono text-muted-foreground">{formatSigned(v)}</span>
    </span>
  );
}

// ----------------------------------------------------------------------------- platforms

/** Platform glyph in its fixed colour, with the name (identity never relies on colour alone). */
export function PlatformIcon({
  platform,
  showLabel = true,
  className,
}: {
  platform: PlatformName;
  showLabel?: boolean;
  className?: string;
}) {
  const p = PLATFORMS[platform];
  const Icon = p.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", className)}>
      <span
        className="grid size-5 place-items-center rounded-md"
        style={{
          backgroundColor: `color-mix(in oklab, ${p.color} 18%, transparent)`,
          color: p.color,
        }}
        aria-hidden={showLabel}
        aria-label={showLabel ? undefined : p.label}
        role={showLabel ? undefined : "img"}
      >
        <Icon className="size-3" />
      </span>
      {showLabel && <span className="font-medium">{p.label}</span>}
    </span>
  );
}

// ----------------------------------------------------------------------------- run status

const STATUS: Record<
  string,
  { label: string; icon: LucideIcon; className: string; spin?: boolean }
> = {
  queued: {
    label: "Queued",
    icon: Clock,
    className: "text-muted-foreground border-border-strong bg-muted",
  },
  running: {
    label: "Running",
    icon: LoaderCircle,
    className: "text-primary border-primary/40 bg-primary/[0.06]",
    spin: true,
  },
  done: {
    label: "Done",
    icon: CircleCheck,
    className: "text-status-good-text border-status-good/40 bg-status-good/10",
  },
  failed: {
    label: "Failed",
    icon: CircleX,
    className: "text-bear-text border-status-critical/50 bg-status-critical/10",
  },
  cancelled: {
    label: "Cancelled",
    icon: Ban,
    className: "text-muted-foreground border-border-strong bg-muted",
  },
};

/** Run status: icon + label + colour (status colours are reserved for state). */
export function StatusPill({ status, className }: { status: string; className?: string }) {
  const s = STATUS[status] ?? STATUS.queued!;
  const Icon = s.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium",
        s.className,
        className,
      )}
    >
      <Icon className={cn("size-3.5", s.spin && "motion-safe:animate-spin")} aria-hidden />
      {s.label}
    </span>
  );
}

/** Small neutral tag, e.g. run mode or an issue reference. */
export function Tag({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground",
        className,
      )}
    >
      {children}
    </span>
  );
}
