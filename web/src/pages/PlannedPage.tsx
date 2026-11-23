import { Compass, Play } from "lucide-react";

import type { NavItem } from "@/app/nav";
import { useDemoReplay } from "@/app/useDemoReplay";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const PREVIEW: Record<string, string> = {
  "/builder":
    "Grouped parameter sliders with PLACEHOLDER badges, and a day/hour timeline you drop events onto.",
  "/monte-carlo":
    "A fan chart of 5–95% price bands that fills in as runs finish, with the random-walk benchmark beside it.",
  "/network":
    "A WebGL graph of a sampled subgraph where nodes light up the tick they hear a rumour.",
  "/narratives":
    "The lineage tree of every rumour, mutation and invention, with S-shaped awareness curves.",
  "/analysis":
    "Calibration trials, the parameter-recovery report and CRPS backtests against a random walk.",
};

/** A page whose content is built in a later issue: explains what is coming and shows its layout. */
export function PlannedPage({ item }: { item: NavItem }) {
  const demo = useDemoReplay();
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-6 p-6">
      <EmptyState
        icon={item.icon}
        title={item.label}
        description={PREVIEW[item.path] ?? item.description}
        issue={item.issue}
        actions={
          <Button variant="outline" onClick={() => void demo.start()} disabled={demo.pending}>
            <Play />
            Watch the demo run meanwhile
          </Button>
        }
      />
      <div
        aria-hidden
        className="grid grid-cols-12 gap-4 [mask-image:linear-gradient(to_bottom,black,transparent)] opacity-60"
      >
        <div className="col-span-12 flex flex-col gap-3 rounded-xl border bg-card p-4 lg:col-span-8">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-56 w-full" />
        </div>
        <div className="col-span-12 flex flex-col gap-3 rounded-xl border bg-card p-4 lg:col-span-4">
          <Skeleton className="h-4 w-32" />
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <div className="grid min-h-full place-items-center p-6">
      <EmptyState
        icon={Compass}
        title="Page not found"
        description="That address does not match any page."
      />
    </div>
  );
}
