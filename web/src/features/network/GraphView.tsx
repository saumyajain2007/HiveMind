import Graph from "graphology";
import FA2Layout from "graphology-layout-forceatlas2/worker";
import { inferSettings } from "graphology-layout-forceatlas2";
import { useEffect, useRef, useState } from "react";
import Sigma from "sigma";

import type { GraphNode, GraphResponse } from "@/lib/api/results";

/** Canvas / WebGL colours must be real colours: read the theme tokens. */
function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888888";
}
function withAlpha(hex: string, a: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1]!, 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
}

const PLATFORM_TOKEN: Record<string, string> = {
  twitter: "--twitter",
  reddit: "--reddit",
  friendship: "--friendship",
  instagram: "--instagram",
  tiktok: "--tiktok",
  youtube: "--youtube",
};

export interface SpreadState {
  /** node id -> tick the node first saw the selected family; absent = never. */
  firstSeen: Map<number, number>;
  tick: number;
  /** narrative (violet) or official (amber) spread colour token. */
  colorToken: "--narrative" | "--official";
}

function mulberry(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Sigma.js (WebGL) view of the run's sampled subgraph. Layout: ForceAtlas2 in a Web Worker on
 * every layer's edges (so switching layers keeps positions), stopped after a few seconds and
 * cached per run in localStorage. Size = log influence (media outlets are the largest); edges
 * take their platform's colour; nodes light up when they first see the selected item family.
 */
export function GraphView({
  data,
  runId,
  layer,
  spread,
  onHover,
  onLayoutDone,
}: {
  data: GraphResponse;
  runId: string;
  layer: string;
  spread: SpreadState | null;
  onHover: (node: (GraphNode & { x: number; y: number }) | null) => void;
  onLayoutDone?: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const sigma = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const state = useRef({ layer, spread });
  const [ready, setReady] = useState(false);
  const [theme, setTheme] = useState(0);
  const hoverRef = useRef(onHover);
  const doneRef = useRef(onLayoutDone);
  useEffect(() => {
    hoverRef.current = onHover;
    doneRef.current = onLayoutDone;
  }, [onHover, onLayoutDone]);

  // build the graph + sigma once per data set
  useEffect(() => {
    const g = new Graph({ multi: true, type: "undirected", allowSelfLoops: false });
    const cacheKey = `marketsim-layout-v2-${runId}-${data.nodes.length}`;
    let cached: Record<string, [number, number]> | null;
    try {
      cached = JSON.parse(localStorage.getItem(cacheKey) ?? "null") as Record<
        string,
        [number, number]
      > | null;
    } catch {
      cached = null;
    }
    const rand = mulberry(7);
    for (const n of data.nodes) {
      const pos = cached?.[n.id];
      const media = n.category === "media";
      g.addNode(String(n.id), {
        x: pos ? pos[0] : rand() * 100,
        y: pos ? pos[1] : rand() * 100,
        size: (media ? 4 : 1.6) + 1.4 * Math.log1p(n.influence),
        label: media ? `outlet ${n.id}` : null,
        node: n,
      });
    }
    data.edges.forEach(([a, b, l], i) => {
      if (g.hasNode(String(a)) && g.hasNode(String(b)))
        g.addEdgeWithKey(`e${i}`, String(a), String(b), { layer: l, size: 0.6 });
    });
    graphRef.current = g;
    const s = new Sigma(g, box.current!, {
      settings: {
        renderLabels: false,
        labelRenderedSizeThreshold: 9,
        hideEdgesOnMove: g.size > 20_000,
        zIndex: true,
        minCameraRatio: 0.05,
        maxCameraRatio: 4,
      } as never,
      nodeReducer: (_key, d, attrs) => {
        const { spread: sp } = state.current;
        const n = attrs.node as GraphNode;
        const base = { ...d };
        const seen = sp?.firstSeen.get(n.id);
        if (sp && seen != null && seen <= sp.tick) {
          const fresh = sp.tick - seen < 4;
          base.color = fresh ? token("--foreground") : token(sp.colorToken);
          base.size = d.size * (fresh ? 2.2 : 1.6);
          base.zIndex = fresh ? 2 : 1;
        } else {
          base.color = withAlpha(token("--muted-foreground"), sp ? 0.4 : 0.85);
          base.zIndex = 0;
        }
        return base;
      },
      edgeReducer: (key, d, attrs) => {
        const { layer: l, spread: sp } = state.current;
        if (l !== "all" && attrs.layer !== l) return { ...d, hidden: true };
        const color = token(PLATFORM_TOKEN[attrs.layer as string] ?? "--muted-foreground");
        let glow = false;
        if (sp) {
          const [a, b] = g.extremities(key);
          const sa = g.getNodeAttribute(a, "node") as GraphNode;
          const sb = g.getNodeAttribute(b, "node") as GraphNode;
          const ta = sp.firstSeen.get(sa.id);
          const tb = sp.firstSeen.get(sb.id);
          glow =
            (ta != null && ta <= sp.tick && sp.tick - ta < 4) ||
            (tb != null && tb <= sp.tick && sp.tick - tb < 4);
        }
        return {
          ...d,
          color: withAlpha(color, glow ? 0.9 : l === "all" ? 0.06 : 0.14),
          size: glow ? 1.6 : 0.6,
          zIndex: glow ? 1 : 0,
        };
      },
    });
    sigma.current = s;
    s.on("enterNode", ({ node }) => {
      const a = g.getNodeAttributes(node);
      const vp = s.graphToViewport({ x: a.x as number, y: a.y as number });
      hoverRef.current({ ...(a.node as GraphNode), x: vp.x, y: vp.y });
    });
    s.on("leaveNode", () => hoverRef.current(null));

    let layout: FA2Layout | null = null;
    let timer = 0;
    if (!cached) {
      layout = new FA2Layout(g, {
        settings: {
          ...inferSettings(g),
          linLogMode: true,
          scalingRatio: 6,
          gravity: 1.5,
          barnesHutOptimize: g.order > 500,
          slowDown: 3,
        },
      });
      layout.start();
      timer = window.setTimeout(() => {
        layout?.stop();
        const out: Record<string, [number, number]> = {};
        g.forEachNode(
          (k, a) =>
            (out[k] = [Number((a.x as number).toFixed(2)), Number((a.y as number).toFixed(2))]),
        );
        try {
          localStorage.setItem(cacheKey, JSON.stringify(out));
        } catch {
          // storage full: the layout is simply recomputed next time
        }
        setReady(true);
        doneRef.current?.();
      }, 3500);
    } else {
      timer = window.setTimeout(() => {
        setReady(true);
        doneRef.current?.();
      }, 0);
    }
    const mo = new MutationObserver(() => setTheme((t) => t + 1));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => {
      window.clearTimeout(timer);
      layout?.kill();
      mo.disconnect();
      s.kill();
      sigma.current = null;
    };
  }, [data, runId]);

  useEffect(() => {
    state.current = { layer, spread };
    sigma.current?.refresh();
  }, [layer, spread, theme]);

  return (
    <div className="relative h-full w-full">
      <div
        ref={box}
        className="h-full w-full"
        role="img"
        aria-label={`Network of ${data.nodes.length} sampled agents and ${data.edges.length} ties; drag to pan, scroll to zoom`}
      />
      {!ready && (
        <p className="pointer-events-none absolute top-3 left-3 rounded-md bg-card/80 px-2 py-1 text-xs text-muted-foreground">
          Laying out the network (ForceAtlas2)…
        </p>
      )}
    </div>
  );
}
