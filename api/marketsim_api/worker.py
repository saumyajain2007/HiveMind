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

import json
import time
import traceback
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from marketsim import montecarlo
from marketsim.backtest import CLOSE_TICK, DatedEvent, backtest, load_dated_events, load_price_csv
from marketsim.calibration import calibrate
from marketsim.config import TICKS_PER_DAY
from marketsim.isolation import isolate
from marketsim.sim import Scenario, Simulation, TickFrame, World, json_safe
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
        if spec.mode in (RunMode.calibration, RunMode.backtest):
            summary, status = _analysis(run_id, spec, cfg, world, out, queue, cancel)
        elif spec.mode == RunMode.isolation:
            summary, status = _isolation(run_id, spec, cfg, scenario, world, n_ticks, out, queue, cancel)
        elif spec.mode == RunMode.single:
            summary, status = _single(
                run_id, spec, cfg, scenario, world, sample, n_ticks, out, queue, cancel, pace
            )
        else:
            summary, status = _montecarlo(run_id, spec, cfg, scenario, world, n_ticks, out, queue, cancel)
        queue.put((run_id, "finished", {"status": status, "summary": summary}))
    except Exception as e:  # report, never crash the pool
        queue.put((run_id, "failed", {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}))


def _isolation(
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
    """Paired counterfactual runs: every event's isolated effect (`marketsim.isolation`)."""

    def progress(done: int, total: int) -> None:
        queue.put((run_id, "msg", {"type": "progress", "done": done, "total": total}))

    res = isolate(
        cfg,
        scenario,
        [spec.seed + i for i in range(spec.runs)],
        n_ticks,
        world=world,
        progress=progress,
        should_stop=cancel.is_set,
    )
    (out / "isolation.json").write_text(json.dumps(res), encoding="utf-8")
    if not res.get("seeds"):
        return {"seeds": 0}, "cancelled"
    top = max(res["events"], key=lambda e: abs(e["final"]["mean"]), default=None)
    summary = {
        "seeds": res["seeds"],
        "events": len(res["events"]),
        "total_effect": res["total"]["final"]["mean"],
        "interaction": res["interaction"],
        "largest": None if top is None else {"label": top["label"], "effect": top["final"]["mean"]},
    }
    return summary, "cancelled" if res["cancelled"] else "done"


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
    seen: list[tuple[int, int, int]] = []  # (tick, sample index, item) for the network view

    def on_tick(frame: TickFrame) -> None:
        seen.extend((frame["tick"], i, item) for i, item in frame.get("node_seen", []))
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
    np.save(out / "result" / "node_seen.npy", np.asarray(seen, np.int64).reshape(-1, 3))
    np.save(out / "result" / "node_sample.npy", sample)
    return res["summary"], "cancelled" if res["meta"]["cancelled"] else "done"


def _dataset(out: Path) -> tuple[list[str], np.ndarray, list[DatedEvent]]:
    dates, closes = load_price_csv(out / "prices.csv")
    events = load_dated_events(out / "events.json", dates)
    return dates, closes, events


def _analysis(
    run_id: str, spec: RunSpec, cfg: Any, world: World, out: Path, queue: Any, cancel: Any
) -> tuple[dict[str, Any], str]:
    """Calibration or backtest on the dataset copied into the run folder."""
    dates, closes, dated = _dataset(out)
    if spec.calibration is not None:
        c = spec.calibration
        days = len(closes)
        events = [replace(e.event, tick=e.time) for e in dated]

        def on_trial(i: int, n: int, trial: dict[str, Any]) -> None:
            queue.put((run_id, "msg", {"type": "trial", "done": i + 1, "total": n, **trial}))

        cal = calibrate(
            np.log(closes),
            Scenario(events),
            c.space,
            c.n_trials,
            c.runs_per_trial,
            config=cfg,
            seed=spec.seed,
            world=world,
            on_trial=on_trial,
            should_stop=cancel.is_set,
            observed_ticks=[d * TICKS_PER_DAY + CLOSE_TICK for d in range(days)],
            relative=True,
        )
        doc = {**cal.to_dict(), "dates": dates}
        (out / "calibration.json").write_text(json.dumps(json_safe(doc)), encoding="utf-8")
        summary = {
            "best": cal.best,
            "best_rmse": cal.best_rmse,
            "n_trials": len(cal.trials),
            "sensitivity": cal.sensitivity(),
        }
        return json_safe(summary), "cancelled" if len(cal.trials) < c.n_trials else "done"
    assert spec.backtest is not None
    b = spec.backtest
    origins = b.origins or list(range(min(20, len(closes) - b.horizon - 1), len(closes) - b.horizon))

    def on_origin(k: int, n: int, row: dict[str, Any]) -> None:
        queue.put((run_id, "msg", {"type": "origin", "done": k + 1, "total": n, **row}))

    res = backtest(
        closes,
        dated,
        origins,
        b.horizon,
        config=cfg,
        runs=b.runs,
        lookback_days=b.lookback_days,
        dates=dates,
        seed=spec.seed,
        world=world,
        on_origin=on_origin,
        should_stop=cancel.is_set,
    )
    doc = {**res.to_dict(), "dates": dates, "closes": closes.tolist()}
    (out / "backtest.json").write_text(json.dumps(json_safe(doc)), encoding="utf-8")
    summary = {
        "skill": res.skill if res.origins else None,
        "mean_crps_model": res.mean_crps_model if res.origins else None,
        "mean_crps_rw": res.mean_crps_rw if res.origins else None,
        "n_origins": len(res.origins),
    }
    return json_safe(summary), "cancelled" if len(res.origins) < len(origins) else "done"


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
