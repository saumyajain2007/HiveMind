import { CircleAlert, Command, LoaderCircle, Moon, Play, Radio, Sun, WifiOff } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";
import { NavLink, Outlet, useLocation, useMatch } from "react-router";

import { Tag } from "@/components/badges";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { WithTooltip } from "@/components/ui/tooltip";
import { useHealth } from "@/lib/api/queries";
import { useLive } from "@/lib/live/store";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

import { CommandPalette } from "./CommandPalette";
import { DESIGN_NAV, NAV } from "./nav";
import { TickerStrip } from "./TickerStrip";
import { useDemoReplay } from "./useDemoReplay";

export const MOCK_API = import.meta.env.VITE_API_MOCK === "true";

export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const location = useLocation();
  const current = [...NAV, DESIGN_NAV].find((n) =>
    n.path === "/" ? location.pathname === "/" : location.pathname.startsWith(n.path),
  );

  return (
    <div className="flex h-full min-h-svh bg-background">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <NavRail onOpenPalette={() => setPaletteOpen(true)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-4 border-b bg-background/80 px-5 backdrop-blur-md">
          <div className="flex min-w-0 items-baseline gap-2.5">
            <h1 className="truncate text-[15px] font-semibold tracking-tight">
              {current?.label ?? "Not found"}
            </h1>
            {current?.issue && <Tag className="hidden sm:inline-flex">{current.issue}</Tag>}
          </div>
          <div className="mx-auto hidden min-w-0 lg:block">
            <TickerStrip />
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-2 lg:ml-0">
            {MOCK_API && (
              <WithTooltip
                label="The app is talking to the built-in mock API (VITE_API_MOCK=true)"
                side="bottom"
              >
                <span
                  tabIndex={0}
                  className="rounded-md border border-dashed border-official/50 px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-wider text-official-text outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                >
                  MOCK DATA
                </span>
              </WithTooltip>
            )}
            <LiveIndicator />
            <DemoButton />
          </div>
        </header>
        <main
          id="main"
          tabIndex={-1}
          className="bg-terminal min-h-0 flex-1 overflow-y-auto outline-none"
        >
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}

function NavRail({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { theme, toggleTheme } = useTheme();
  const health = useHealth();
  const apiOk = health.isSuccess;
  return (
    <nav
      aria-label="Primary"
      className="sticky top-0 flex h-svh w-16 shrink-0 flex-col items-center border-r bg-card/50 py-3"
    >
      <NavLink
        to="/"
        className="mb-4 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      >
        <Logo className="size-9" />
      </NavLink>
      <ul className="flex flex-col items-center gap-1">
        {NAV.map((item) => (
          <li key={item.path}>
            <RailLink item={item} />
          </li>
        ))}
      </ul>
      <div className="mt-auto flex flex-col items-center gap-1">
        <RailLink item={DESIGN_NAV} />
        <WithTooltip
          label={
            <span>
              Command palette <kbd className="ml-1 font-mono text-muted-foreground">Ctrl K</kbd>
            </span>
          }
        >
          <Button
            variant="ghost"
            size="icon"
            aria-label="Open command palette"
            onClick={onOpenPalette}
          >
            <Command />
          </Button>
        </WithTooltip>
        <WithTooltip label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
          <Button variant="ghost" size="icon" aria-label="Toggle theme" onClick={toggleTheme}>
            {theme === "dark" ? <Sun /> : <Moon />}
          </Button>
        </WithTooltip>
        <WithTooltip
          label={
            health.isPending
              ? "Checking the API…"
              : apiOk
                ? `API online · engine v${health.data?.engine_version}`
                : "API offline"
          }
        >
          <span
            role="status"
            tabIndex={0}
            aria-label={apiOk ? "API online" : health.isPending ? "Checking API" : "API offline"}
            className="mt-1 grid size-9 place-items-center rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          >
            <span
              className={cn(
                "size-2 rounded-full",
                apiOk
                  ? "bg-status-good shadow-[0_0_0_3px_color-mix(in_oklab,var(--status-good)_25%,transparent)]"
                  : health.isPending
                    ? "bg-muted-foreground"
                    : "bg-status-critical",
              )}
            />
          </span>
        </WithTooltip>
      </div>
    </nav>
  );
}

function RailLink({ item }: { item: (typeof NAV)[number] }) {
  // Active state from useMatch (not NavLink's render props): the tooltip trigger clones the
  // link, and plain props survive that reliably.
  const isActive = useMatch({ path: item.path, end: item.path === "/" }) != null;
  return (
    <WithTooltip
      label={
        <span className="flex flex-col">
          <span className="font-medium">{item.label}</span>
          <span className="text-muted-foreground">{item.description}</span>
        </span>
      }
    >
      <NavLink
        to={item.path}
        end={item.path === "/"}
        aria-label={item.label}
        aria-current={isActive ? "page" : undefined}
        className={cn(
          "relative grid size-10 place-items-center rounded-lg text-muted-foreground transition-colors outline-none",
          "hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60",
          isActive && "text-primary hover:text-primary",
        )}
      >
        {isActive && (
          <motion.span
            layoutId="rail-active"
            className="absolute inset-0 rounded-lg bg-primary/12 ring-1 ring-primary/30"
            transition={{ type: "spring", stiffness: 500, damping: 38 }}
          />
        )}
        {isActive && (
          <motion.span
            layoutId="rail-bar"
            className="absolute top-2 -left-[15px] h-6 w-[3px] rounded-r-full bg-primary"
            transition={{ type: "spring", stiffness: 500, damping: 38 }}
          />
        )}
        <item.icon className="relative size-[18px]" aria-hidden />
      </NavLink>
    </WithTooltip>
  );
}

function LiveIndicator() {
  const status = useLive((s) => s.status);
  const runId = useLive((s) => s.runId);
  if (status === "idle") return null;
  const map = {
    connecting: {
      icon: LoaderCircle,
      label: "Connecting",
      cls: "text-muted-foreground",
      spin: true,
    },
    live: {
      icon: Radio,
      label: "Live",
      cls: "text-primary border-primary/40 bg-primary/10",
      spin: false,
    },
    reconnecting: {
      icon: WifiOff,
      label: "Reconnecting",
      cls: "text-official-text border-official/40",
      spin: false,
    },
    done: { icon: Radio, label: "Finished", cls: "text-muted-foreground", spin: false },
    error: {
      icon: CircleAlert,
      label: "Stream error",
      cls: "text-bear-text border-status-critical/50",
      spin: false,
    },
  } as const;
  const s = map[status];
  return (
    <WithTooltip label={`Run ${runId}`} side="bottom">
      <span
        role="status"
        tabIndex={0}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
          s.cls,
        )}
      >
        {status === "live" ? (
          <span className="relative flex size-2">
            <span className="absolute inline-flex h-full w-full rounded-full bg-primary opacity-60 motion-safe:animate-ping" />
            <span className="relative inline-flex size-2 rounded-full bg-primary" />
          </span>
        ) : (
          <s.icon className={cn("size-3.5", s.spin && "motion-safe:animate-spin")} aria-hidden />
        )}
        {s.label}
      </span>
    </WithTooltip>
  );
}

function DemoButton() {
  const demo = useDemoReplay();
  return (
    <Button size="sm" onClick={() => void demo.start()} disabled={demo.pending}>
      {demo.pending ? <LoaderCircle className="motion-safe:animate-spin" /> : <Play />}
      Run demo
    </Button>
  );
}
