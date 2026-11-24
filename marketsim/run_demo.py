"""`python -m marketsim.run_demo --agents 10000 --days 5 --runs 20` (issue #11, HANDOFF §4 M4).

Runs the scripted scenario (an anonymous acquisition rumour on day 1, the company's denial on
day 3, a real earnings miss of −5% on day 4) as a Monte Carlo ensemble and writes the plots and
`summary.json` to `outputs/`.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import replace
from pathlib import Path

from . import montecarlo, scenarios, viz
from .config import TICKS_PER_DAY, Config
from .sim import World, json_safe


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--agents", type=int, default=10_000)
    ap.add_argument("--days", type=float, default=5)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--workers", type=int, default=min(2, os.cpu_count() or 1))
    ap.add_argument("--seed", type=int, default=0, help="world seed (population and graph)")
    ap.add_argument("--out", type=Path, default=Path("outputs"))
    args = ap.parse_args(argv)

    cfg = replace(Config(), n_agents=args.agents, seed=args.seed)
    n_ticks = round(args.days * TICKS_PER_DAY)
    t0 = time.perf_counter()
    world = World.build(cfg)
    t_build = time.perf_counter() - t0

    def progress(done: int, total: int, _q: dict) -> None:
        print(f"\r  run {done}/{total}", end="", flush=True)

    print(
        f"marketsim demo: {args.agents} agents, {args.days:g} days, {args.runs} runs, {args.workers} workers"
    )
    mc = montecarlo.run(
        cfg,
        scenarios.demo(),
        R=args.runs,
        workers=args.workers,
        n_ticks=n_ticks,
        progress=progress,
        world=world if args.workers <= 1 else None,
    )
    print()
    t_mc = time.perf_counter() - t0 - t_build
    args.out.mkdir(parents=True, exist_ok=True)
    plots = viz.all_plots(mc, args.out, world.pop.category, world.pop.platform_use)
    summary = mc.summary()
    summary["timing"] = {"build_s": t_build, "montecarlo_s": t_mc, "per_run_s": t_mc / max(mc.n_runs, 1)}
    summary["plots"] = [p.name for p in plots]
    if mc.representative is not None:
        summary["representative"] = mc.representative["summary"]
    (args.out / "summary.json").write_text(json.dumps(json_safe(summary), indent=2), encoding="utf-8")
    sf = summary["stylized_facts"]
    fq = summary["final_price_quantiles"]
    print(f"  final price 5/50/95%: {fq['0.05']:.2f} / {fq['0.5']:.2f} / {fq['0.95']:.2f}")
    print(f"  excess kurtosis {sf['excess_kurtosis']:.2f}; |r| ACF lag 1 {sf['acf_abs_r'][0]:.2f}")
    print(f"  wrote {len(plots)} plots and summary.json to {args.out}/ in {time.perf_counter() - t0:.1f}s")
    return summary


if __name__ == "__main__":
    main()
