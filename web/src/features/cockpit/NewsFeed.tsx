import { GitBranch, Lightbulb, Newspaper, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { SentimentChip } from "@/components/badges";
import { formatCompact, simClock } from "@/lib/format";
import type { ItemMeta } from "@/lib/live/store";
import { useMotionTransition } from "@/lib/motion";
import { cn } from "@/lib/utils";

const ORIGIN: Record<ItemMeta["origin"], { icon: LucideIcon; label: string; tone: string }> = {
  event: { icon: Newspaper, label: "Event", tone: "text-official-text" },
  mutation: { icon: GitBranch, label: "Mutation", tone: "text-narrative-text" },
  invention: { icon: Lightbulb, label: "Invented", tone: "text-narrative-text" },
  price_news: { icon: TrendingUp, label: "Price news", tone: "text-muted-foreground" },
};

/**
 * Items as they are born, newest first: origin, sentiment, credibility, and awareness that rises
 * as the item spreads. Mutations link to their parent.
 */
export function NewsFeed({
  items,
  awareness,
  nAgents,
}: {
  items: ItemMeta[];
  awareness: Record<string, number>;
  nAgents: number;
}) {
  const [flash, setFlash] = useState<number | null>(null);
  const transition = useMotionTransition({ duration: 0.3, ease: [0.22, 1, 0.36, 1] });
  const list = [...items].reverse().slice(0, 60);
  if (!list.length)
    return (
      <p className="text-sm text-muted-foreground">
        Nothing has happened yet. Events and narratives appear here as they are born.
      </p>
    );
  return (
    <ol className="flex flex-col gap-2" aria-label="News feed, newest first">
      <AnimatePresence initial={false}>
        {list.map((it) => {
          const o = ORIGIN[it.origin];
          const Icon = o.icon;
          const aware = awareness[String(it.item)];
          return (
            <motion.li
              key={`${it.item}-${it.tick}`}
              id={`feed-${it.item}`}
              layout
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={transition}
              className={cn(
                "rounded-lg border bg-surface-2/60 p-2.5",
                flash === it.item && "ring-2 ring-narrative",
              )}
            >
              <div className="flex items-start gap-2">
                <span className={cn("mt-0.5", o.tone)}>
                  <Icon className="size-4" aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm leading-snug font-medium">{it.label}</p>
                  <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                    #{it.item} · {o.label}
                    {it.seeding ? ` · ${it.seeding}` : ""} · {simClock(it.tick).label}
                  </p>
                </div>
                <SentimentChip value={it.sentiment} compact />
              </div>
              <div className="mt-2 flex items-center gap-3 text-[11px]">
                <span className="text-muted-foreground">Credibility</span>
                <span
                  className="relative h-1.5 w-20 overflow-hidden rounded-full bg-muted"
                  aria-hidden
                >
                  <span
                    className="absolute inset-y-0 left-0 rounded-full bg-foreground/60"
                    style={{ width: `${it.credibility * 100}%` }}
                  />
                </span>
                <span className="tabular font-mono">{it.credibility.toFixed(2)}</span>
                <span className="ml-auto text-muted-foreground">Aware</span>
                <span className="tabular font-mono font-semibold">
                  {aware == null
                    ? "–"
                    : `${formatCompact(aware)} (${((aware / Math.max(1, nAgents)) * 100).toFixed(1)}%)`}
                </span>
              </div>
              {it.parent >= 0 && it.origin !== "event" && (
                <button
                  type="button"
                  className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-narrative-text underline-offset-2 hover:underline"
                  onClick={() => {
                    setFlash(it.parent);
                    document
                      .getElementById(`feed-${it.parent}`)
                      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
                    window.setTimeout(() => setFlash(null), 1500);
                  }}
                >
                  <GitBranch className="size-3" aria-hidden />
                  mutated from #{it.parent}
                </button>
              )}
              {it.parent >= 0 && it.origin === "event" && (
                <p className="mt-1.5 text-[11px] text-muted-foreground">Follows up #{it.parent}</p>
              )}
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ol>
  );
}
