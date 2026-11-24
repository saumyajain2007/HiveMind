import { cn } from "@/lib/utils";

export interface LegendItem {
  key: string;
  label: string;
  color: string;
  dash?: string;
  kind?: "line" | "band" | "dot" | "bar";
  muted?: boolean;
}

/** Legend row: a swatch drawn like the mark (line with dash, band, dot) plus text in ink. */
export function Legend({
  items,
  className,
  onToggle,
}: {
  items: LegendItem[];
  className?: string;
  onToggle?: (key: string) => void;
}) {
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 text-xs", className)}>
      {items.map((it) => {
        const swatch = (
          <svg width="18" height="10" aria-hidden className="shrink-0">
            {it.kind === "band" ? (
              <rect x="0" y="1" width="18" height="8" rx="2" fill={it.color} opacity={0.35} />
            ) : it.kind === "dot" || it.kind === "bar" ? (
              <rect
                x="5"
                y="1"
                width="8"
                height="8"
                rx={it.kind === "dot" ? 4 : 2}
                fill={it.color}
              />
            ) : (
              <line
                x1="1"
                x2="17"
                y1="5"
                y2="5"
                stroke={it.color}
                strokeWidth="2"
                strokeDasharray={it.dash || undefined}
                strokeLinecap="round"
              />
            )}
          </svg>
        );
        const body = (
          <>
            {swatch}
            <span className={cn("text-muted-foreground", it.muted && "line-through opacity-60")}>
              {it.label}
            </span>
          </>
        );
        return (
          <li key={it.key}>
            {onToggle ? (
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                aria-pressed={!it.muted}
                onClick={() => onToggle(it.key)}
              >
                {body}
              </button>
            ) : (
              <span className="inline-flex items-center gap-1.5">{body}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
