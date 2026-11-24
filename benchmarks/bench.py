"""Engine benchmark: build time, seconds per tick and peak RSS (issue #15, HANDOFF §4 M6).

    uv run python benchmarks/bench.py                       # 10k and 100k
    uv run python benchmarks/bench.py --sizes 10000 100000 1000000 --reduced 1000000

Each size runs in its own process so peak RSS is per size. The workload is the demo scenario
for `--days` days (default 1: the rumour is born and spreads during the day). "Reduced" sizes
halve the platform degrees (Twitter / Instagram out-degree, friendship degree, Reddit
memberships, YouTube subscriptions) to fit in memory; the table says which sizes used it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import replace

import numpy as np
import psutil

from marketsim import scenarios
from marketsim.config import TICKS_PER_DAY, Config
from marketsim.market import is_market_open
from marketsim.sim import Simulation, World


def peak_rss_mb() -> float:
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None)  # Windows
    if peak is None:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # Linux reports KiB
    return peak / 2**20


def reduced(cfg: Config) -> Config:
    g = cfg.graph
    return replace(
        cfg,
        graph=replace(
            g,
            twitter_mean_out=g.twitter_mean_out / 2,
            instagram_mean_out=g.instagram_mean_out / 2,
            friendship_mean_degree=g.friendship_mean_degree / 2,
            reddit_mean_memberships=max(1.0, g.reddit_mean_memberships / 2),
            youtube_mean_subs=g.youtube_mean_subs / 2,
        ),
    )


def one(n: int, days: float, is_reduced: bool) -> dict:
    cfg = replace(Config(), n_agents=n)
    if is_reduced:
        cfg = reduced(cfg)
    t0 = time.perf_counter()
    world = World.build(cfg)
    build = time.perf_counter() - t0
    sim = Simulation(cfg, scenarios.demo(), 1, world=world)
    n_ticks = round(days * TICKS_PER_DAY)
    times = np.zeros(n_ticks)
    for t in range(n_ticks):
        t1 = time.perf_counter()
        sim.step()
        times[t] = time.perf_counter() - t1
    open_ = np.array([is_market_open(t) for t in range(n_ticks)])
    edges = sum(int(getattr(layer, "n_edges", 0)) for layer in world.graph.layers.values())
    return {
        "agents": n,
        "reduced": is_reduced,
        "edges": edges,
        "build_s": build,
        "tick_s_mean": float(times.mean()),
        "tick_s_open": float(times[open_].mean()) if open_.any() else None,
        "tick_s_max": float(times.max()),
        "peak_rss_mb": peak_rss_mb(),
        "items": len(sim.items.lineage),
    }


def table(rows: list[dict]) -> str:
    out = [
        "| agents | degrees | edges | build | s / tick (mean) | s / tick (open) | peak RSS |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        if "error" in r:
            degrees = "halved" if r["reduced"] else "default"
            out.append(f"| {r['agents']:,} | {degrees} | – | – | – | – | {r['error']} |")
            continue
        out.append(
            f"| {r['agents']:,} | {'halved' if r['reduced'] else 'default'} | {r['edges']:,} | "
            f"{r['build_s']:.1f} s | {r['tick_s_mean']:.4f} | {r['tick_s_open']:.4f} | "
            f"{r['peak_rss_mb']:,.0f} MB |"
        )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[10_000, 100_000])
    ap.add_argument("--reduced", type=int, nargs="*", default=[], help="sizes run with halved degrees")
    ap.add_argument("--days", type=float, default=1.0)
    ap.add_argument("--one", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--json", action="store_true", help="print JSON rows instead of a table")
    args = ap.parse_args()
    if args.one:
        print(json.dumps(one(args.one, args.days, args.one in args.reduced)))
        return
    rows = []
    for n in args.sizes:
        cmd = [sys.executable, __file__, "--one", str(n), "--days", str(args.days)]
        if n in args.reduced:
            cmd += ["--reduced", str(n)]
        print(f"benchmarking {n:,} agents...", file=sys.stderr)
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            tail = (p.stderr.strip().splitlines() or ["failed"])[-1]
            rows.append({"agents": n, "reduced": n in args.reduced, "error": tail[:80]})
        else:
            rows.append(json.loads(p.stdout.strip().splitlines()[-1]))
    print(json.dumps(rows, indent=1) if args.json else table(rows))


if __name__ == "__main__":
    main()
