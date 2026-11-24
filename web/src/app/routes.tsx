/* eslint-disable react-refresh/only-export-components -- route table module, not a hot-reloaded component file */
import { lazy, Suspense } from "react";
import type { ComponentType, LazyExoticComponent, ReactNode } from "react";
import type { RouteObject } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";
import { RunsPage } from "@/pages/RunsPage";

import { AppShell } from "./AppShell";
import { NAV } from "./nav";

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
const DesignPage = lazy(() =>
  import("@/pages/DesignPage").then((m) => ({ default: m.DesignPage })),
);
const PlannedPage = lazy(() =>
  import("@/pages/PlannedPage").then((m) => ({ default: m.PlannedPage })),
);
const NotFoundPage = lazy(() =>
  import("@/pages/PlannedPage").then((m) => ({ default: m.NotFoundPage })),
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

const BUILT = ["/", "/cockpit", "/builder", "/monte-carlo", "/network"];
const planned = NAV.filter((n) => !BUILT.includes(n.path));

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
      ...planned.map((item) => ({
        path: item.path.slice(1),
        element: page(PlannedPage, { item }),
      })),
      { path: "design", element: page(DesignPage, {}) },
      { path: "*", element: page(NotFoundPage, {}) },
    ],
  },
];
