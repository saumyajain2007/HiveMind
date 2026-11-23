import { Activity, Inbox, Play } from "lucide-react";
import type { ReactNode } from "react";

import {
  PlaceholderBadge,
  PlatformIcon,
  SentimentChip,
  StatusPill,
  Tag,
} from "@/components/badges";
import { PLATFORMS } from "@/lib/vocab";
import type { PlatformName } from "@/lib/vocab";
import { Delta } from "@/components/Delta";
import { EmptyState } from "@/components/EmptyState";
import { Logo } from "@/components/Logo";
import { Panel } from "@/components/Panel";
import { Sparkline } from "@/components/Sparkline";
import { Stat } from "@/components/Stat";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPrice, formatSignedPct } from "@/lib/format";
import { cn } from "@/lib/utils";

const SPARK = [
  100, 100.4, 99.8, 100.9, 101.6, 101.1, 102.3, 103.0, 102.2, 101.4, 99.7, 98.9, 99.6, 97.8, 96.4,
  96.9,
];
const REF = SPARK.map((_, i) => (i < 12 ? 100 : 95.1));

const TOKENS: Array<{ group: string; items: Array<[string, string]> }> = [
  {
    group: "Surfaces & ink",
    items: [
      ["background", "--background"],
      ["card", "--card"],
      ["surface-2", "--surface-2"],
      ["border", "--border-strong"],
      ["foreground", "--foreground"],
      ["muted text", "--muted-foreground"],
      ["accent", "--primary"],
    ],
  },
  {
    group: "Market marks",
    items: [
      ["up", "--bull"],
      ["down", "--bear"],
      ["narrative", "--narrative"],
      ["official", "--official"],
      ["fundamental", "--fundamental"],
    ],
  },
  {
    group: "Platforms (fixed order)",
    items: (Object.keys(PLATFORMS) as PlatformName[]).map((p) => [PLATFORMS[p].label, `--${p}`]),
  },
  {
    group: "Status (icon + label always)",
    items: [
      ["good", "--status-good"],
      ["warning", "--status-warning"],
      ["serious", "--status-serious"],
      ["critical", "--status-critical"],
    ],
  },
];

function Swatch({ name, token }: { name: string; token: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <span
        className="size-7 shrink-0 rounded-md border"
        style={{ background: `var(${token})` }}
        aria-hidden
      />
      <div className="min-w-0">
        <p className="truncate text-xs font-medium">{name}</p>
        <p className="truncate font-mono text-[10px] text-muted-foreground">{token}</p>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Every token and shared component, rendered inside one theme island. */
function Gallery({ theme }: { theme: "dark" | "light" }) {
  return (
    <div
      className={cn(
        theme,
        "bg-terminal flex min-w-0 flex-col gap-7 rounded-2xl border bg-background p-5 text-foreground",
      )}
      aria-label={`${theme} theme`}
      role="region"
    >
      <div className="flex items-center gap-3">
        <Logo className="size-10" />
        <div>
          <p className="text-base font-semibold tracking-tight">
            HiveMind · {theme === "dark" ? "Dark (default)" : "Light"}
          </p>
          <p className="text-xs text-muted-foreground">
            Inter for text, JetBrains Mono with tabular figures for numbers
          </p>
        </div>
      </div>

      <Section title="Tokens">
        {TOKENS.map((g) => (
          <div key={g.group}>
            <p className="mb-2 text-xs text-muted-foreground">{g.group}</p>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
              {g.items.map(([name, token]) => (
                <Swatch key={token} name={name} token={token} />
              ))}
            </div>
          </div>
        ))}
      </Section>

      <Section title="Type">
        <div className="space-y-1">
          <p className="text-2xl font-semibold tracking-tight">Rumours move markets</p>
          <p className="text-sm text-muted-foreground">
            Body copy in Inter. Secondary text uses the muted ink.
          </p>
          <p className="tabular font-mono text-xl font-semibold">101.37 · 12.9K · −4.82%</p>
        </div>
      </Section>

      <Section title="Buttons">
        <div className="flex flex-wrap gap-2">
          <Button>
            <Play />
            Primary
          </Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button disabled>Disabled</Button>
        </div>
      </Section>

      <Section title="Stat tiles">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Stat
            label="Price"
            value={96.9}
            format={(v) => formatPrice(v)}
            delta={-0.031}
            period="vs open"
            trend={SPARK}
          />
          <Stat
            label="Agents aware of the rumour"
            value={4123}
            delta={0.18}
            deltaFormat={formatSignedPct}
            period="vs an hour ago"
            badge={<PlaceholderBadge />}
          />
          <Stat label="Loading" value={null} loading />
        </div>
      </Section>

      <Section title="Sparkline (hover or focus, then ← →)">
        <div className="rounded-xl border bg-card p-4">
          <Sparkline
            values={SPARK}
            reference={REF}
            referenceLabel="Fundamental"
            label="Example price path"
            height={90}
            interactive
            format={(v) => formatPrice(v)}
          />
        </div>
      </Section>

      <Section title="Deltas, sentiment, platforms, status">
        <div className="flex flex-wrap items-center gap-3">
          <Delta value={0.0124} period="vs open" />
          <Delta value={-0.048} period="vs open" />
          <Delta value={0} />
          <Delta value={0.02} upIsGood={false} period="volatility" />
        </div>
        <div className="flex flex-wrap gap-2">
          {[-0.9, -0.35, 0, 0.4, 0.85].map((s) => (
            <SentimentChip key={s} value={s} />
          ))}
        </div>
        <div className="flex flex-wrap gap-3">
          {(Object.keys(PLATFORMS) as PlatformName[]).map((p) => (
            <PlatformIcon key={p} platform={p} />
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {["queued", "running", "done", "failed", "cancelled"].map((s) => (
            <StatusPill key={s} status={s} />
          ))}
          <PlaceholderBadge />
          <Tag>#21</Tag>
          <Tag>MC ×20</Tag>
        </div>
      </Section>

      <Section title="Panel, skeleton, empty state">
        <Panel
          title={`Panel title (${theme})`}
          subtitle="Optional subtitle"
          icon={Activity}
          actions={<Tag>actions</Tag>}
        >
          <div className="space-y-2">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-16 w-full" />
          </div>
        </Panel>
        <div className="rounded-xl border bg-card">
          <EmptyState
            icon={Inbox}
            title="Nothing here yet"
            description="Empty states explain what will appear and offer one next step."
            issue="#20"
            actions={<Button size="sm">Do the thing</Button>}
          />
        </div>
      </Section>
    </div>
  );
}

export function DesignPage() {
  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-5 p-6">
      <div>
        <p className="font-mono text-[11px] tracking-[0.16em] text-primary">DESIGN SYSTEM</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">Tokens and components</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Chart colours were validated for lightness, chroma, colour-blind separation and contrast
          against each theme&apos;s panel surface. Up/down, narrative and official colours never
          share a chart with platform colours.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Gallery theme="dark" />
        <Gallery theme="light" />
      </div>
    </div>
  );
}
