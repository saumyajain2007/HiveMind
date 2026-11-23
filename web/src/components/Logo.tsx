import { useId } from "react";

import { cn } from "@/lib/utils";

/** HiveMind mark: three hexagon cells with a rising price line through them. */
export function Logo({ className, title = "HiveMind" }: { className?: string; title?: string }) {
  const id = useId();
  const hex = (cx: number, cy: number, r: number) =>
    Array.from({ length: 6 }, (_, i) => {
      const a = (Math.PI / 3) * i - Math.PI / 2;
      return `${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`;
    }).join(" ");
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} role="img" aria-label={title}>
      <defs>
        <linearGradient id={`${id}-g`} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--primary)" />
          <stop offset="100%" stopColor="var(--narrative)" />
        </linearGradient>
      </defs>
      <polygon
        points={hex(10, 19, 7)}
        fill="none"
        stroke={`url(#${id}-g)`}
        strokeWidth="1.6"
        opacity="0.55"
      />
      <polygon
        points={hex(22, 19, 7)}
        fill="none"
        stroke={`url(#${id}-g)`}
        strokeWidth="1.6"
        opacity="0.55"
      />
      <polygon
        points={hex(16, 9, 7)}
        fill="none"
        stroke={`url(#${id}-g)`}
        strokeWidth="1.6"
        opacity="0.55"
      />
      <polyline
        points="4,24 11,17 16,20 22,10 28,13"
        fill="none"
        stroke={`url(#${id}-g)`}
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="22" cy="10" r="2.2" fill="var(--narrative)" />
    </svg>
  );
}
