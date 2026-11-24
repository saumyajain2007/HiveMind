"""Isolate the effect of each event: paired counterfactual runs (with vs without that event).

    from marketsim.isolation import isolate
    res = isolate(cfg, scenario, seeds=range(20), n_ticks=5 * 96)

For every seed the scenario is run once with all its events, once with none, and once per
target event with *that event removed*. The simulation draws every subsystem (diffusion,
beliefs, trading, market noise, events) from its own random stream, so a run without an event is
identical to the full run until the moment the event would have fired; any later difference is
caused by the event, directly or through what agents did because of it. Averaging the paired
difference over seeds gives the event's isolated effect with a confidence band:

* **effect path:** mean, 5-95% band and standard error of log P(all) - log P(without e);
* **at one day / at the end:** the isolated move one trading day after the release and at the end
  of the run, a 95% CI, P(effect > 0), and the share of the total move it accounts for;
* **peak and timing:** the largest mean effect and when it happens, and how long the effect
  takes to reach half of its peak (speed of price discovery);
* **pass-through:** final effect / the event's true impact (how much of the news the market
  priced, and whether it over- or under-reacted);
* **volume:** extra traded volume caused by the event, as a share of the volume without it;
* **interaction:** the move with all events minus the move with none, compared with the sum of
  the isolated effects. A gap means events amplify or cancel each other (a rumour followed by a
  denial is not the sum of the two).

`decompose_real_move` applies the same machinery to a real stretch of history: the filings in
the window are replayed with their measured reactions and each one's isolated contribution to
the window's move is reported next to the real abnormal return.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from .config import TICKS_PER_DAY, Config
from .events import Event
from .sim import Scenario, Simulation, World, json_safe

ROOT = Path(__file__).resolve().parents[1]


def _variants(events: list[Event], targets: Sequence[int]) -> dict[str, list[Event]]:
    out: dict[str, list[Event]] = {"all": events, "none": []}
    for t in targets:
        out[f"without_{t}"] = [e for e in events if e.id != t]
    return out


def _stats(eff: np.ndarray, every: int, event_tick: int | None) -> dict[str, Any]:
    """eff: (seeds, ticks) paired log-price differences."""
    r, n = eff.shape
    mean = eff.mean(axis=0)
    se = eff.std(axis=0, ddof=1) / np.sqrt(r) if r > 1 else np.zeros(n)
    final = eff[:, -1]
    f_mean = float(final.mean())
    f_se = float(final.std(ddof=1) / np.sqrt(r)) if r > 1 else 0.0
    start = 0 if event_tick is None else min(event_tick, n - 1)
    after = np.abs(mean[start:])
    k = int(np.argmax(after)) + start if len(after) else 0
    peak = float(mean[k])
    half = None
    if abs(peak) > 0:
        hit = np.nonzero(np.abs(mean[start:]) >= 0.5 * abs(peak))[0]
        half = int(hit[0]) if len(hit) else None
    day1 = eff[:, min(start + TICKS_PER_DAY, n - 1)]
    sl = slice(None, None, every)
    return {
        "path": {
            "mean": mean[sl].tolist(),
            "lo": np.quantile(eff, 0.05, axis=0)[sl].tolist(),
            "hi": np.quantile(eff, 0.95, axis=0)[sl].tolist(),
            "se": se[sl].tolist(),
        },
        "final": {
            "mean": f_mean,
            "se": f_se,
            "ci95": [f_mean - 1.96 * f_se, f_mean + 1.96 * f_se],
            "t": f_mean / f_se if f_se > 0 else 0.0,
            "p_positive": float((final > 0).mean()),
        },
        "one_day": {"mean": float(day1.mean()), "se": float(day1.std(ddof=1) / np.sqrt(r)) if r > 1 else 0.0},
        "peak": {"value": peak, "tick": k},
        "ticks_to_half_peak": half,
    }


def isolate(
    cfg: Config,
    scenario: Scenario,
    seeds: Sequence[int],
    n_ticks: int,
    world: World | None = None,
    targets: Sequence[int] | None = None,
    every: int = 4,
    progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    world = world or World.build(cfg)
    events = list(scenario.events)
    targets = [e.id for e in events] if targets is None else list(targets)
    variants = _variants(events, targets)
    logp: dict[str, list[np.ndarray]] = {k: [] for k in variants}
    vol: dict[str, list[np.ndarray]] = {k: [] for k in variants}
    total, done = len(seeds) * len(variants), 0
    stopped = False
    for s in seeds:
        if should_stop is not None and should_stop():
            stopped = True
            break
        for k, evs in variants.items():
            sc = Scenario([replace(e) for e in evs], dict(scenario.labels))
            ser = Simulation(cfg, sc, int(s), world=world).run(n_ticks)["series"]
            logp[k].append(np.log(np.asarray(ser["price"], np.float64)))
            vol[k].append(np.asarray(ser["volume"], np.float64))
            done += 1
            if progress is not None:
                progress(done, total)
    r = len(logp["all"])
    if r == 0:
        return {"seeds": 0, "cancelled": True}
    P = {k: np.stack(v) for k, v in logp.items()}
    V = {k: np.stack(v) for k, v in vol.items()}
    by_id = {e.id: e for e in events}
    rows = []
    tot = _stats(P["all"] - P["none"], every, None)
    for t in targets:
        e = by_id[t]
        st = _stats(P["all"] - P[f"without_{t}"], every, e.tick)
        base_vol = V[f"without_{t}"][:, e.tick :].sum(axis=1)
        extra = (V["all"][:, e.tick :].sum(axis=1) - base_vol) / np.maximum(base_vol, 1e-9)
        st.update(
            {
                "id": t,
                "label": scenario.labels.get(t, f"{e.kind} at tick {e.tick}"),
                "kind": e.kind,
                "tick": e.tick,
                "day": e.tick // TICKS_PER_DAY,
                "true_impact": e.true_impact,
                "sentiment": e.sentiment,
                "credibility": e.credibility,
                "salience": e.salience,
                "seeding": e.seeding,
                "pass_through": st["final"]["mean"] / e.true_impact if abs(e.true_impact) > 1e-9 else None,
                "extra_volume": float(extra.mean()),
                "share_of_total": st["final"]["mean"] / tot["final"]["mean"]
                if abs(tot["final"]["mean"]) > 1e-9
                else None,
            }
        )
        rows.append(st)
    isolated_sum = float(sum(x["final"]["mean"] for x in rows))
    return json_safe(
        {
            "seeds": r,
            "cancelled": stopped,
            "n_ticks": n_ticks,
            "every": every,
            "tick": list(range(0, n_ticks, every)),
            "baseline": {
                "mean": P["none"].mean(axis=0)[::every].tolist(),
                "with_events": P["all"].mean(axis=0)[::every].tolist(),
            },
            "total": tot,
            "events": rows,
            "isolated_sum": isolated_sum,
            "interaction": tot["final"]["mean"] - isolated_sum,
        }
    )


# --------------------------------------------------------------------------- real moves


def decompose_real_move(
    exp: Any, o: int, h: int, runs: int = 12, params: dict[str, float] | None = None
) -> dict:
    """Split the real move from close `o` to close `o + h` into the isolated contributions of the
    filings in the window, replayed with their measured reactions (an `Experiment` supplies the
    data, the fitted agents and the event rows)."""
    from .calibration import with_params
    from .experiment import _WORLD, CLOSE_TICK, _init_worker, _scenario

    if "world" not in _WORLD:
        _init_worker(exp.cfg.n_agents, exp.cfg.seed)
    task = exp.task(o, h, params or {}, oracle=True)
    rows = task.events[0]
    hist = exp.ds.history
    window = [e for e in exp.ds.events if task.start <= e.reaction_idx <= o + h]
    # rows are (tick, kind, impact, sentiment, salience, complexity) in the order of `window`
    # (minus events before the replay start); label them with their filing
    from .experiment import KIND

    sc = _scenario(rows)
    labels = {}
    used: set[int] = set()
    for ev in sc.events:
        match = next(
            (
                w
                for w in window
                if w.id not in used and KIND[w.group] == ev.kind and ev.tick == _tick(exp, w, task.start)
            ),
            None,
        )
        if match is not None:
            used.add(match.id)
        labels[ev.id] = (
            f"{match.form} {', '.join(match.items)} ({match.group}, {hist.dates[match.reaction_idx]})"
            if match
            else ev.kind
        )
    sc = Scenario(sc.events, labels)
    cfg = with_params(_WORLD["cfg"], task.params)
    cfg = replace(cfg, market=replace(cfg.market, implied_vol=float(np.clip(task.iv, 0.05, 3.0))))
    o_tick = (o - task.start) * TICKS_PER_DAY + CLOSE_TICK
    end_tick = o_tick + h * TICKS_PER_DAY
    res = isolate(cfg, sc, task.seeds[:runs], end_tick + 1, world=_WORLD["world"], every=8)
    real = float(np.log(hist.close[o + h] / hist.close[o]))
    try:  # the market-adjusted (abnormal) move: what the company's own news has to explain
        from .event_parser import event_study

        real_abn = float(
            event_study(hist.close, hist.market, o + 1, est_window=120, event_window=(0, h - 1)).car
        )
    except ValueError:
        real_abn = real
    mkt = float(np.log(hist.market[o + h] / hist.market[o]))
    res.update(
        {
            "origin": hist.dates[o],
            "target": hist.dates[o + h],
            "start": hist.dates[task.start],
            "origin_tick": o_tick,
            "real_move": real,
            "real_abnormal_move": real_abn,
            "market_move": mkt,
            "measured_reactions": [
                {
                    "date": hist.dates[w.reaction_idx],
                    "form": w.form,
                    "items": w.items,
                    "group": w.group,
                    "label": w.label,
                }
                for w in window
            ],
        }
    )
    # effects over the forecast window only: subtract each path's value at the origin
    k0 = o_tick // res["every"]
    for x in [res["total"], *res["events"]]:
        m = x["path"]["mean"]
        x["window_effect"] = m[-1] - m[min(k0, len(m) - 1)]
    return res


def _tick(exp: Any, e: Any, start: int) -> int | None:
    idx, t = exp.slots[e.id]
    return None if idx < start else (idx - start) * TICKS_PER_DAY + t


# --------------------------------------------------------------------------- CLI: real earnings moves

_EXP: dict[str, Any] = {}


def _init_decompose(ticker: str) -> None:
    from .experiment import Experiment, ExperimentConfig

    exp = Experiment(ExperimentConfig(ticker=ticker, n_agents=1000))
    _EXP["exp"] = exp
    res = json.loads((ROOT / "docs" / "experiments" / ticker / "results.json").read_text(encoding="utf-8"))
    _EXP["params"] = dict(res["simulation"]["params"])


def _decompose_one(args: tuple[int, int, int]) -> dict[str, Any]:
    o, h, runs = args
    return decompose_real_move(_EXP["exp"], o, h, runs=runs, params=_EXP["params"])


def decompose_earnings(ticker: str = "AAPL", h: int = 2, runs: int = 12, workers: int = 10) -> dict[str, Any]:
    """Every test-period earnings release: from the close before it to `h` closes later."""
    from concurrent.futures import ProcessPoolExecutor

    from .experiment import Experiment, ExperimentConfig

    exp = Experiment(ExperimentConfig(ticker=ticker, n_agents=1000))
    hist = exp.ds.history
    jobs = [
        (e.reaction_idx - 1, h, runs)
        for e in exp.ds.events
        if e.group == "earnings"
        and e.reaction_idx >= exp.split_idx
        and e.reaction_idx - 1 + h < len(hist.dates)
    ]
    with ProcessPoolExecutor(workers, initializer=_init_decompose, initargs=(ticker,)) as ex:
        windows = list(ex.map(_decompose_one, jobs))
    return json_safe({"ticker": ticker, "name": hist.name, "horizon": h, "runs": runs, "windows": windows})


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Split real earnings-window moves into per-event effects.")
    ap.add_argument("ticker", nargs="?", default="AAPL")
    ap.add_argument("--horizon", type=int, default=2)
    ap.add_argument("--runs", type=int, default=12)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args(argv)
    res = decompose_earnings(args.ticker.upper(), args.horizon, args.runs, args.workers)
    out = ROOT / "docs" / "experiments" / args.ticker.upper() / "isolation.json"
    out.write_text(json.dumps(res), encoding="utf-8")
    for w in res["windows"]:
        parts = ", ".join(f"{e['label'][:28]} {e['window_effect'] * 100:+.2f}%" for e in w["events"])
        print(
            f"{w['origin']} -> {w['target']}: real {w['real_move'] * 100:+.2f}% (market {w['market_move'] * 100:+.2f}%), "
            f"simulated {w['total']['window_effect'] * 100:+.2f}% = {parts}"
        )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
