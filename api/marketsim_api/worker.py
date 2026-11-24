"""Code that runs inside a job process (issue #17).

The worker never imports FastAPI. It reports through a `multiprocessing` queue with
(run_id, kind, payload) tuples:

* ("started", {...hello fields})
* ("msg", message)       a stream message (tick / event / narrative / progress)
* ("finished", {"status": ..., "summary": ...})  or ("failed", {"error": ...})

Ticks are sent every tick; the API side coalesces them for slow clients. Cancellation is a
shared flag polled before every tick (single runs) or between runs (Monte Carlo).
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from marketsim import montecarlo
from marketsim.config import TICKS_PER_DAY
from marketsim.sim import Scenario, Simulation, TickFrame, World
from marketsim.sim import save as save_run

from .config_schema import parameters_to_engine
from .schemas import RunMode, RunSpec

NODE_SAMPLE = 3_000  # nodes whose awareness is streamed for the network view (#23)
PROGRESS_EVERY = 1  # Monte Carlo: partial quantiles after every finished run


def scenario_of(spec: RunSpec) -> Scenario:
    events = [e.to_engine() for e in spec.scenario.events]
    labels = {e.id: e.label for e in spec.scenario.events if e.label}
    return Scenario(events, labels)


def node_sample(n_nodes: int, seed: int, k: int = NODE_SAMPLE) -> np.ndarray:
    rng = np.random.default_rng([seed, 23])
    return np.sort(rng.choice(n_nodes, size=min(k, n_nodes), replace=False))


def tick_message(frame: Mapping[str, Any]) -> dict[str, Any]:
    msg = {k: v for k, v in frame.items() if k not in ("born", "node_seen")}
    msg["type"] = "tick"
    if frame.get("node_seen"):
        msg["node_seen"] = frame["node_seen"]
    return msg


def execute(run_id: str, spec_json: str, run_dir: str, queue: Any, cancel: Any, pace: float = 0.0) -> None:
    """Run one job to the end and report through `queue`. Never raises."""
    try:
        spec = RunSpec.model_validate_json(spec_json)
        out = Path(run_dir)
        cfg = parameters_to_engine(spec.parameters, spec.scenario.n_agents, spec.scenario.seed)
        scenario = scenario_of(spec)
        n_ticks = spec.scenario.n_ticks
        world = World.build(cfg)
        sample = node_sample(world.pop.n, cfg.seed)
        hello = {
            "type": "hello",
            "run_id": run_id,
            "mode": spec.mode.value,
            "runs": spec.runs,
            "n_agents": spec.scenario.n_agents,
            "n_nodes": world.pop.n,
            "days": spec.scenario.days,
            "seed": spec.seed,
            "ticks_per_day": TICKS_PER_DAY,
            "initial_price": cfg.market.initial_price,
            "node_sample": sample.tolist() if spec.mode == RunMode.single else [],
        }
        queue.put((run_id, "started", hello))
        if spec.mode == RunMode.single:
            summary, status = _single(
                run_id, spec, cfg, scenario, world, sample, n_ticks, out, queue, cancel, pace
            )
        else:
            summary, status = _montecarlo(run_id, spec, cfg, scenario, world, n_ticks, out, queue, cancel)
        queue.put((run_id, "finished", {"status": status, "summary": summary}))
    except Exception as e:  # report, never crash the pool
        queue.put((run_id, "failed", {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}))


def _single(
    run_id: str,
    spec: RunSpec,
    cfg: Any,
    scenario: Scenario,
    world: World,
    sample: np.ndarray,
    n_ticks: int,
    out: Path,
    queue: Any,
    cancel: Any,
    pace: float,
) -> tuple[dict[str, Any], str]:
    start = time.perf_counter()

    def on_tick(frame: TickFrame) -> None:
        for m in frame["born"]:
            queue.put((run_id, "msg", m))
        queue.put((run_id, "msg", tick_message(frame)))
        if pace > 0:  # watchable live runs: at most `pace` ticks per second
            due = start + (frame["tick"] + 1) / pace
            wait = due - time.perf_counter()
            if wait > 0:
                time.sleep(wait)

    sim = Simulation(
        cfg, scenario, spec.seed, world=world, on_tick=on_tick, should_stop=cancel.is_set, node_sample=sample
    )
    res = sim.run(n_ticks)
    save_run(res, out / "result")
    return res["summary"], "cancelled" if res["meta"]["cancelled"] else "done"


def _montecarlo(
    run_id: str,
    spec: RunSpec,
    cfg: Any,
    scenario: Scenario,
    world: World,
    n_ticks: int,
    out: Path,
    queue: Any,
    cancel: Any,
) -> tuple[dict[str, Any], str]:
    seeds = [spec.seed + i for i in range(1, spec.runs + 1)]

    def progress(done: int, total: int, q: dict[str, np.ndarray]) -> None:
        queue.put(
            (
                run_id,
                "msg",
                {
                    "type": "progress",
                    "done": done,
                    "total": total,
                    "quantiles": {k: np.round(v, 4).tolist() for k, v in q.items()},
                },
            )
        )

    mc = montecarlo.run(
        cfg,
        scenario,
        seeds=seeds,
        n_ticks=n_ticks,
        workers=spec.workers,  # job processes are not daemonic, so they may start their own pool
        progress=progress,
        progress_every=PROGRESS_EVERY,
        should_stop=cancel.is_set,
        world=world if spec.workers <= 1 else None,
    )
    montecarlo.save(mc, out / "mc")
    summary = mc.summary()
    return summary, "cancelled" if mc.meta["stopped_early"] else "done"
