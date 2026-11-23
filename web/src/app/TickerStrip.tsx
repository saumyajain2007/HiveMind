import { useEffect, useRef, useState } from "react";

import { CountUp } from "@/components/CountUp";
import { Delta } from "@/components/Delta";
import { formatPct, formatPrice, simClock } from "@/lib/format";
import { useLive } from "@/lib/live/store";
import { cn } from "@/lib/utils";

/**
 * Top-bar ticker: price (counts up and flashes on each move), change since the start of the
 * run, implied vol, ATM call and the simulation clock. Only this strip re-renders on frames.
 */
export function TickerStrip({ className }: { className?: string }) {
  const last = useLive((s) => s.last);
  const initial = useLive((s) => s.meta?.initial_price ?? null);
  const prev = useRef<number | null>(null);
  const [flash, setFlash] = useState<{ dir: "up" | "down"; key: number } | null>(null);

  useEffect(() => {
    if (!last) {
      prev.current = null;
      return;
    }
    if (prev.current != null && last.price !== prev.current) {
      setFlash({ dir: last.price > prev.current ? "up" : "down", key: last.tick });
    }
    prev.current = last.price;
  }, [last]);

  const change = last && initial ? last.price / initial - 1 : null;
  const clock = last ? simClock(last.tick) : null;

  return (
    <dl className={cn("flex items-center gap-5", className)} aria-label="Market ticker">
      <div className="flex items-baseline gap-2">
        <dt className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground">ACME</dt>
        <dd
          key={flash?.key}
          className={cn(
            "tabular -mx-1 rounded px-1 font-mono text-base font-semibold",
            flash?.dir === "up" && "animate-flash-up",
            flash?.dir === "down" && "animate-flash-down",
          )}
        >
          <CountUp value={last?.price} format={(v) => formatPrice(v)} duration={0.25} />
        </dd>
        <dd>
          <Delta value={change} />
        </dd>
      </div>
      <TickerItem label="IV" value={last ? formatPct(last.iv) : "—"} />
      <TickerItem label="ATM CALL" value={last ? formatPrice(last.atm_call) : "—"} />
      <div className="flex items-center gap-2">
        <dt className="sr-only">Simulation clock</dt>
        <dd className="tabular font-mono text-xs text-muted-foreground">
          {clock ? clock.label : "Day — · --:--"}
        </dd>
        <dd>
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wider",
              clock?.open ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
            )}
          >
            {clock ? (clock.open ? "OPEN" : "CLOSED") : "IDLE"}
          </span>
        </dd>
      </div>
    </dl>
  );
}

function TickerItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground">{label}</dt>
      <dd className="tabular font-mono text-sm">{value}</dd>
    </div>
  );
}
