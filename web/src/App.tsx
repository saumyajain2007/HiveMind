import {
  Activity,
  ChartLine,
  CircleCheck,
  Circle,
  FlaskConical,
  GitBranch,
  Library,
  Network,
  SlidersHorizontal,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { useApiHealth, type ApiHealth } from "@/lib/useApiHealth";
import { cn } from "@/lib/utils";

const NAV = [
  { label: "Runs", icon: Library },
  { label: "Builder", icon: SlidersHorizontal },
  { label: "Cockpit", icon: Activity },
  { label: "Monte Carlo", icon: ChartLine },
  { label: "Network", icon: Network },
  { label: "Narratives", icon: GitBranch },
  { label: "Analysis", icon: FlaskConical },
] as const;

const PHASES = [
  { id: "P0", title: "Foundations", issues: "#1", done: true },
  { id: "P1", title: "Engine core", issues: "#2–#10", done: false },
  { id: "P2", title: "Prediction", issues: "#11–#15", done: false },
  { id: "P3", title: "API", issues: "#16–#18", done: false },
  { id: "P4", title: "Web app", issues: "#19–#25", done: false },
] as const;

const TICKER = [
  { label: "PRICE", value: "—" },
  { label: "Δ DAY", value: "—" },
  { label: "IV", value: "30.0%" },
  { label: "ATM CALL", value: "—" },
] as const;

function StatusPill({ health }: { health: ApiHealth }) {
  const tone =
    health.state === "online"
      ? "bg-bull/10 text-bull ring-bull/30"
      : health.state === "offline"
        ? "bg-bear/10 text-bear ring-bear/30"
        : "bg-muted text-muted-foreground ring-border";
  const text =
    health.state === "online"
      ? `API online · engine v${health.engineVersion}`
      : health.state === "offline"
        ? "API offline"
        : "Checking API…";
  return (
    <span
      role="status"
      className={cn(
        "inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ring-1",
        tone,
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full bg-current",
          health.state === "online" && "motion-safe:animate-pulse",
        )}
      />
      {text}
    </span>
  );
}

export default function App() {
  const health = useApiHealth();

  return (
    <div className="flex min-h-svh bg-background">
      <nav
        aria-label="Primary"
        className="flex w-16 flex-col items-center gap-2 border-r bg-card/60 py-4"
      >
        <div className="mb-4 grid size-9 place-items-center rounded-lg bg-primary/15 font-mono text-sm font-bold text-primary">
          H
        </div>
        {NAV.map(({ label, icon: Icon }) => (
          <Button
            key={label}
            variant="ghost"
            size="icon"
            disabled
            title={`${label} (coming soon)`}
            aria-label={label}
          >
            <Icon />
          </Button>
        ))}
      </nav>

      <div className="flex flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b px-6">
          <div className="flex items-baseline gap-3">
            <h1 className="text-base font-semibold tracking-tight">HiveMind</h1>
            <span className="font-mono text-xs text-muted-foreground">marketsim · v0.1.0</span>
          </div>
          <dl className="hidden items-center gap-6 md:flex">
            {TICKER.map(({ label, value }) => (
              <div key={label} className="flex items-baseline gap-2">
                <dt className="text-[10px] font-medium tracking-widest text-muted-foreground">
                  {label}
                </dt>
                <dd className="tabular font-mono text-sm">{value}</dd>
              </div>
            ))}
          </dl>
          <StatusPill health={health} />
        </header>

        <main className="grid flex-1 place-items-center p-8">
          <section className="w-full max-w-xl rounded-xl border bg-card p-8 shadow-[inset_0_1px_0_0_rgb(255_255_255/0.04)]">
            <p className="font-mono text-xs tracking-widest text-primary">SKELETON READY</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">
              Agent-based market simulator
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              Rumours spread through social platforms, move beliefs, and agents trade on them in a
              batch auction. The engine, API and dashboard are built in the issues below.
            </p>
            <ol className="mt-6 space-y-2">
              {PHASES.map((p) => (
                <li
                  key={p.id}
                  className="flex items-center gap-3 rounded-lg border bg-background/40 px-4 py-2.5"
                >
                  {p.done ? (
                    <CircleCheck className="size-4 text-bull" aria-label="done" />
                  ) : (
                    <Circle className="size-4 text-muted-foreground" aria-label="to do" />
                  )}
                  <span className="font-mono text-xs text-muted-foreground">{p.id}</span>
                  <span className="text-sm">{p.title}</span>
                  <span className="ml-auto font-mono text-xs text-muted-foreground">
                    {p.issues}
                  </span>
                </li>
              ))}
            </ol>
          </section>
        </main>
      </div>
    </div>
  );
}
