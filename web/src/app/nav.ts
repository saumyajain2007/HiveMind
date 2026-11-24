import {
  Activity,
  ChartSpline,
  FlaskConical,
  GitBranch,
  Landmark,
  WalletCards,
  Library,
  Network,
  Palette,
  SlidersHorizontal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  description: string;
  issue?: string;
  shortcut?: string;
}

export const NAV: NavItem[] = [
  {
    path: "/",
    label: "Runs",
    icon: Library,
    description: "Every run, its status and headline numbers",
    shortcut: "G R",
  },
  {
    path: "/builder",
    label: "Builder",
    icon: SlidersHorizontal,
    description: "Parameters and the event timeline",
    shortcut: "G B",
  },
  {
    path: "/cockpit",
    label: "Cockpit",
    icon: Activity,
    description: "Watch a run as it happens",
    shortcut: "G C",
  },
  {
    path: "/monte-carlo",
    label: "Monte Carlo",
    icon: ChartSpline,
    description: "Fan chart and price distribution",
    shortcut: "G M",
  },
  {
    path: "/network",
    label: "Network",
    icon: Network,
    description: "Rumours spreading through the platforms",
    shortcut: "G N",
  },
  {
    path: "/narratives",
    label: "Narratives",
    icon: GitBranch,
    description: "Lineage tree and awareness",
    shortcut: "G T",
  },
  {
    path: "/analysis",
    label: "Analysis",
    icon: FlaskConical,
    description: "Calibration and backtests",
    shortcut: "G A",
  },
  {
    path: "/real-data",
    label: "Real data",
    icon: Landmark,
    description: "Real stock, real filings: trained, then tested out of sample",
    shortcut: "G D",
  },
  {
    path: "/strategy",
    label: "Strategy",
    icon: WalletCards,
    description: "Expected prices, forecast statistics and trading results",
    shortcut: "G S",
  },
];

export const DESIGN_NAV: NavItem = {
  path: "/design",
  label: "Design system",
  icon: Palette,
  description: "Tokens and components in both themes",
};
