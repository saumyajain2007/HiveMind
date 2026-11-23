import {
  Activity,
  ChartSpline,
  FlaskConical,
  GitBranch,
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
    issue: "#20",
    shortcut: "G B",
  },
  {
    path: "/cockpit",
    label: "Cockpit",
    icon: Activity,
    description: "Watch a run as it happens",
    issue: "#21",
    shortcut: "G C",
  },
  {
    path: "/monte-carlo",
    label: "Monte Carlo",
    icon: ChartSpline,
    description: "Fan chart and price distribution",
    issue: "#22",
    shortcut: "G M",
  },
  {
    path: "/network",
    label: "Network",
    icon: Network,
    description: "Rumours spreading through the platforms",
    issue: "#23",
    shortcut: "G N",
  },
  {
    path: "/narratives",
    label: "Narratives",
    icon: GitBranch,
    description: "Lineage tree and awareness",
    issue: "#24",
    shortcut: "G T",
  },
  {
    path: "/analysis",
    label: "Analysis",
    icon: FlaskConical,
    description: "Calibration and backtests",
    issue: "#25",
    shortcut: "G A",
  },
];

export const DESIGN_NAV: NavItem = {
  path: "/design",
  label: "Design system",
  icon: Palette,
  description: "Tokens and components in both themes",
};
