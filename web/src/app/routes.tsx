/* eslint-disable react-refresh/only-export-components -- route table module, not a hot-reloaded component file */
import { lazy, Suspense } from "react";
import type { ComponentType, LazyExoticComponent, ReactNode } from "react";
import type { RouteObject } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";
import { RunsPage } from "@/pages/RunsPage";

import { AppShell } from "./AppShell";

// The Runs page ships with the shell; every other page is split into its own chunk.
const CockpitPage = lazy(() =>
  import("@/pages/CockpitPage").then((m) => ({ default: m.CockpitPage })),
);
const BuilderPage = lazy(() =>
  import("@/pages/BuilderPage").then((m) => ({ default: m.BuilderPage })),
);
const MonteCarloPage = lazy(() =>
  import("@/pages/MonteCarloPage").then((m) => ({ default: m.MonteCarloPage })),
);
const NetworkPage = lazy(() =>
  import("@/pages/NetworkPage").then((m) => ({ default: m.NetworkPage })),
);
const NarrativesPage = lazy(() =>
  import("@/pages/NarrativesPage").then((m) => ({ default: m.NarrativesPage })),
);
const AnalysisPage = lazy(() =>
  import("@/pages/AnalysisPage").then((m) => ({ default: m.AnalysisPage })),
);
const RealDataPage = lazy(() =>
  import("@/pages/RealDataPage").then((m) => ({ default: m.RealDataPage })),
);
const StrategyPage = lazy(() =>
  import("@/pages/StrategyPage").then((m) => ({ default: m.StrategyPage })),
);
const EventLabPage = lazy(() =>
  import("@/pages/EventLabPage").then((m) => ({ default: m.EventLabPage })),
);
const ImportPage = lazy(() =>
  import("@/pages/ImportPage").then((m) => ({ default: m.ImportPage })),
);
const SignalLabPage = lazy(() =>
  import("@/pages/SignalLabPage").then((m) => ({ default: m.SignalLabPage })),
);
const AlgoPage = lazy(() => import("@/pages/AlgoPage").then((m) => ({ default: m.AlgoPage })));
const DesignPage = lazy(() =>
  import("@/pages/DesignPage").then((m) => ({ default: m.DesignPage })),
);
const NotFoundPage = lazy(() =>
  import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })),
);

function PageFallback() {
  return (
    <div
      className="mx-auto flex max-w-[1400px] flex-col gap-4 p-6"
      aria-busy="true"
      aria-label="Loading page"
    >
      <Skeleton className="h-8 w-64" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-72" />
    </div>
  );
}

function page<P extends object>(C: LazyExoticComponent<ComponentType<P>>, props: P): ReactNode {
  return (
    <Suspense fallback={<PageFallback />}>
      <C {...props} />
    </Suspense>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <RunsPage /> },
      { path: "cockpit", element: page(CockpitPage, {}) },
      { path: "builder", element: page(BuilderPage, {}) },
      { path: "monte-carlo", element: page(MonteCarloPage, {}) },
      { path: "network", element: page(NetworkPage, {}) },
      { path: "narratives", element: page(NarrativesPage, {}) },
      { path: "analysis", element: page(AnalysisPage, {}) },
      { path: "real-data", element: page(RealDataPage, {}) },
      { path: "strategy", element: page(StrategyPage, {}) },
      { path: "event-lab", element: page(EventLabPage, {}) },
      { path: "import", element: page(ImportPage, {}) },
      { path: "algo", element: page(AlgoPage, {}) },
      { path: "signals", element: page(SignalLabPage, {}) },
      { path: "design", element: page(DesignPage, {}) },
      { path: "*", element: page(NotFoundPage, {}) },
    ],
  },
];
