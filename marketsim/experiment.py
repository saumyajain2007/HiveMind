"""Train on a real stock's past events, then forecast its later prices out of sample.

    uv run python -m marketsim.experiment AAPL --split 2024-01-01

1. **Events:** every SEC filing of the company becomes an event (`realdata`), labelled with its
   actual abnormal return on the reaction day (event study against SPY).
2. **Impact model (classification + size):** trained on events before `--split` only
   (`impact_model`), with its regularisation chosen on the last 30% of the training events.
3. **Simulation training:** a small grid over the simulator's market parameters, scored by the
   mean CRPS of one-day-ahead forecasts on training-period origins.
4. **Out-of-sample backtest:** for every trading day after the split, forecast the close
   `horizon` days ahead with four models and score them with CRPS against what happened:

   * ``random_walk``: lognormal, trailing 20-day volatility (the benchmark);
   * ``event_random_walk``: the same plus a jump for every *scheduled* earnings release in the
     horizon, drawn from the impact model (earnings dates are announced weeks ahead);
   * ``abm_raw``: the agent-based simulation, seeded with the events known at the forecast
     origin (as the impact model reads them) plus scheduled earnings in the horizon (a fresh
     draw from the impact model in each run). Its R runs become a predictive distribution
     with the small-sample Student-t rule (`raw_predictive`);
   * ``abm``: the same runs, post-processed by a recalibration fitted on training origins only
     (`Recalibration`: shrink the ensemble's centre, rescale its spread, blend in trailing
     volatility; the "model output statistics" step of weather forecasting);
   * ``abm_oracle``: the simulation told every event in the window *and its true reaction*
     (raw ensemble). It uses the future and is not a forecast; it shows how much better
     perfect event knowledge would make the simulation.

   Every forecaster is scored on the same number of samples (`rw_samples`). Scoring a
   16-member ensemble directly would add a penalty of about spread / (2 x 16) to its CRPS
   and cap its 5-95% interval's coverage near 80%, which says nothing about the model.

5. **Report:** `docs/experiments/<TICKER>/` gets results.json, report.md and plots, and
   `data/<TICKER>/events.json` gets the labelled events in the format the web app uploads.

No step reads anything after a forecast origin except the oracle and the scoring.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm

from .backtest import crps_sample
from .calibration import with_params
from .config import TICKS_PER_DAY, Config
from .events import Event
from .impact_model import ImpactModel
from .realdata import FEATURES, Dataset, RealEvent, feature_matrix, features_at, load_dataset
from .sim import Scenario, Simulation, World, json_safe

ROOT = Path(__file__).resolve().parents[1]
CLOSE_TICK = 63
MODELS = ("random_walk", "event_random_walk", "abm_raw", "abm", "abm_oracle")
KIND = {
    "earnings": "earnings",
    "periodic_report": "regulatory",
    "executive": "statement",
    "vote": "statement",
    "governance": "statement",
    "other_event": "statement",
    "disclosure": "statement",
    "agreement": "product",
}


@dataclass
class ExperimentConfig:
    ticker: str = "AAPL"
    split: str = "2024-01-01"  # train on events / origins before, test after
    train_from: str = "2016-01-01"
    horizons: tuple[int, ...] = (1, 5)
    n_agents: int = 1500
    runs: int = 16  # simulation runs per origin
    rw_samples: int = 4000
    lookback_days: int = 5  # the market maker's depth settles over the first day
    vol_window: int = 20
    train_origins: int = 200
    test_every: int = 1  # forecast from every n-th trading day of the test period
    long_every: int = 2  # and, for horizons > 1 day (overlapping windows), every n-th of those
    grid: dict[str, list[float]] = field(
        default_factory=lambda: {
            # the agents' own order flow is too smooth (thousands of independent choices average
            # out), so the unmodelled-flow noise is the main lever on the forecast spread
            "market.noise_frac": [0.4, 0.6, 0.8, 1.1, 1.5],
            "market.mm_news_pass_through": [0.6, 1.0],
        }
    )
    workers: int = min(8, max(1, (os.cpu_count() or 2) - 2))  # each worker holds a population
    seed: int = 0
    data_root: str | None = None
    out_dir: str | None = None
    # fitted agent behaviour (`marketsim.agent_fit`); None = read docs/experiments/<T>/agent_fit.json
    # if it exists, {} = the config defaults
    agent_params: dict[str, float] | None = None
    # the population's real-data inputs (marketsim.survey); "" = the PLACEHOLDER population
    survey: str = "us"


def load_agent_params(ticker: str) -> dict[str, float]:
    p = ROOT / "docs" / "experiments" / ticker.upper() / "agent_fit.json"
    if not p.exists():
        return {}
    best = json.loads(p.read_text(encoding="utf-8"))["best"]["params"]
    return {k: float(v) for k, v in best.items()}


# --------------------------------------------------------------------------- events -> simulation


def release_slot(ds: Dataset, e: RealEvent) -> tuple[int, int]:
    """(trading-day index, tick within that day) at which the release enters the simulation."""
    t = datetime.fromisoformat(e.released)
    day = t.date().isoformat()
    idx = ds.history.index_on_or_after(day)
    if idx < len(ds.history.dates) and ds.history.dates[idx] == day:
        return idx, (t.hour * 60 + t.minute) // 15
    return idx, 32  # weekend / holiday release: 08:00 on the next trading day


def to_event(e: RealEvent, tick: int, impact: float, sentiment: float, size: float, eid: int) -> Event:
    return Event(
        tick=tick,
        kind=KIND[e.group],
        ticker=0,
        true_impact=float(np.clip(impact, -0.5, 0.5)),
        sentiment=float(np.clip(sentiment, -1.0, 1.0)),
        credibility=0.95,
        salience=float(np.clip(0.3 + 8.0 * size, 0.2, 1.0)),
        complexity=0.4 if e.group in ("earnings", "periodic_report") else 0.2,
        seeding="official",
        id=eid,
    )


@dataclass
class OriginTask:
    origin: int
    horizon: int
    start: int
    iv: float
    params: dict[str, float]
    seeds: list[int]
    # per-run event lists: [(tick, kind, impact, sentiment, salience, complexity)]
    events: list[list[tuple[int, str, float, float, float, float]]]


def _scenario(rows: list[tuple[int, str, float, float, float, float]]) -> Scenario:
    evs = [
        Event(t, k, 0, imp, sent, 0.95, sal, cx, "official", id=i)
        for i, (t, k, imp, sent, sal, cx) in enumerate(sorted(rows))
    ]
    return Scenario(evs)


_WORLD: dict[str, Any] = {}


def _init_worker(n_agents: int, seed: int, survey: str = "us") -> None:
    cfg = replace(Config(), n_agents=n_agents, seed=seed)
    cfg = replace(cfg, population=replace(cfg.population, survey=survey))
    _WORLD["cfg"], _WORLD["world"] = cfg, World.build(cfg)


def _simulate(task: OriginTask) -> np.ndarray:
    """Simulated ratio close[origin + horizon] / close[origin], one per run."""
    base: Config = _WORLD["cfg"]
    cfg = with_params(base, task.params)
    cfg = replace(cfg, market=replace(cfg.market, implied_vol=float(np.clip(task.iv, 0.05, 3.0))))
    o_tick = (task.origin - task.start) * TICKS_PER_DAY + CLOSE_TICK
    end_tick = o_tick + task.horizon * TICKS_PER_DAY
    out = []
    for seed, rows in zip(task.seeds, task.events, strict=True):
        p = Simulation(cfg, _scenario(rows), seed, world=_WORLD["world"]).run(end_tick + 1)["series"]["price"]
        out.append(p[end_tick] / p[o_tick])
    return np.asarray(out)


# --------------------------------------------------------------------------- ensembles -> forecasts


def _log_stats(ratios: np.ndarray) -> tuple[float, float]:
    lr = np.log(np.asarray(ratios, np.float64))
    return float(lr.mean()), float(lr.std(ddof=1)) if len(lr) > 1 else 0.0


def raw_predictive(ratios: np.ndarray, rng: np.random.Generator, n: int) -> np.ndarray:
    """Predictive distribution of a new run given R runs (normal log returns, unknown mean and
    variance): Student-t with R - 1 degrees of freedom, scale sd * sqrt(1 + 1/R)."""
    m = len(ratios)
    mu, sd = _log_stats(ratios)
    scale = max(sd, 1e-6) * math.sqrt(1.0 + 1.0 / m)
    return np.exp(mu + scale * rng.standard_t(max(m - 1, 1), n))


def gaussian_crps(mu: np.ndarray, sigma: np.ndarray, y: np.ndarray) -> np.ndarray:
    z = (y - mu) / sigma
    return np.asarray(sigma * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / math.sqrt(math.pi)))


@dataclass
class Recalibration:
    """Ensemble -> forecast: log return ~ Normal(shrink * ensemble mean,
    sqrt((spread * ensemble sd)^2 + (vol_weight * trailing vol * sqrt(h))^2)).
    Fitted by minimum CRPS on training origins (Gneiting et al. 2005, EMOS)."""

    shrink: float = 1.0
    spread: float = 1.0
    vol_weight: float = 0.0
    train_crps: float = float("nan")
    raw_train_crps: float = float("nan")

    def params(self, ratios: np.ndarray, rv: float) -> tuple[float, float]:
        mu, sd = _log_stats(ratios)
        return self.shrink * mu, math.sqrt((self.spread * sd) ** 2 + (self.vol_weight * rv) ** 2) + 1e-9

    def sample(self, ratios: np.ndarray, rv: float, rng: np.random.Generator, n: int) -> np.ndarray:
        mu, s = self.params(ratios, rv)
        return np.exp(rng.normal(mu, s, n))

    @staticmethod
    def fit(ensembles: Sequence[np.ndarray], rv: np.ndarray, y: np.ndarray) -> Recalibration:
        stats = np.array([_log_stats(e) for e in ensembles])
        mus, sds = stats[:, 0], stats[:, 1]
        m = len(ensembles[0])

        def loss(th: np.ndarray) -> float:
            b, a, c = th[0], math.exp(th[1]), math.exp(th[2])
            s = np.sqrt((a * sds) ** 2 + (c * rv) ** 2) + 1e-9
            return float(np.mean(gaussian_crps(b * mus, s, y)))

        fits = [
            minimize(loss, np.array(x0), method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-9})
            for x0 in ([1.0, 0.0, math.log(0.3)], [0.3, math.log(0.5), 0.0])
        ]
        best = min(fits, key=lambda r: float(r.fun))
        raw = np.mean(gaussian_crps(mus, np.maximum(sds, 1e-6) * math.sqrt(1 + 1 / m), y))
        return Recalibration(
            shrink=float(best.x[0]),
            spread=float(math.exp(best.x[1])),
            vol_weight=float(math.exp(best.x[2])),
            train_crps=float(best.fun),
            raw_train_crps=float(raw),
        )


# --------------------------------------------------------------------------- the experiment


class Experiment:
    def __init__(self, cfg: ExperimentConfig) -> None:
        self.cfg = cfg
        root = Path(cfg.data_root) if cfg.data_root else None
        self.ds = load_dataset(cfg.ticker, root)
        h = self.ds.history
        self.split_idx = h.index_on_or_after(cfg.split)
        self.from_idx = max(h.index_on_or_after(cfg.train_from), 130)
        self.earn_days = earn_days = {e.reaction_idx for e in self.ds.events if e.group == "earnings"}
        # an earnings release owns its reaction day: other filings on that day (e.g. the 10-Q
        # filed the next morning) are kept as events but not used as training labels
        self.labelled = [
            e
            for e in self.ds.events
            if e.label is not None and not (e.group != "earnings" and e.reaction_idx in earn_days)
        ]
        self.train_events = [e for e in self.labelled if e.reaction_idx < self.split_idx]
        self.test_events = [e for e in self.labelled if e.reaction_idx >= self.split_idx]
        self.slots = {e.id: release_slot(self.ds, e) for e in self.ds.events}
        self.rng = np.random.default_rng([cfg.seed, 42])
        self.model = self._fit_impact_model()
        self.jump_scale = 1.0
        self.jump_scale, self.jump_fit = self._fit_jump_scale()
        if cfg.agent_params is None:
            cfg.agent_params = {} if cfg.data_root else load_agent_params(cfg.ticker)
        self.agent_params: dict[str, float] = dict(cfg.agent_params)
        self.recal: dict[int, Recalibration] = {}
        self.ensembles: dict[str, np.ndarray] = {}  # raw simulation runs, saved for re-scoring

    # ---------------------------------------------------------------- impact model
    def _fit_impact_model(self) -> ImpactModel:
        tr = self.train_events
        X, y = feature_matrix(tr), np.array([e.label for e in tr])
        cut = int(len(tr) * 0.7)  # time-ordered validation split inside the training years
        best = None
        for l2 in (0.3, 1.0, 3.0, 10.0, 30.0, 100.0):
            m = ImpactModel(l2=l2).fit(X[:cut], y[:cut])
            ll = m.evaluate(X[cut:], y[cut:], y[:cut])["log_loss"]
            if best is None or ll < best[0]:
                best = (ll, l2)
        assert best is not None
        self.l2 = best[1]
        return ImpactModel(l2=self.l2).fit(X, y)

    def _fit_jump_scale(self) -> tuple[float, list[dict[str, float]]]:
        """Scale on the impact model's sampled earnings jumps, chosen by the one-day CRPS of the
        event-aware random walk over every training-period earnings release. The classifier's
        size distribution is fitted on all filings, so its tails are not tuned to earnings."""
        hist = self.ds.history
        origins = [
            e.reaction_idx - 1
            for e in self.train_events
            if e.group == "earnings" and e.reaction_idx - 1 >= self.from_idx
        ]
        if not origins:
            return 1.0, []
        fit = []
        for k in (0.4, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0):
            rng = np.random.default_rng([self.cfg.seed, 11])  # common random numbers across k
            crps = []
            for o in origins:
                s = self.trailing_vol(o)
                z = rng.normal(-0.5 * s * s, s, self.cfg.rw_samples)
                j = sum(
                    (
                        self.model.sample(self._masked_features(e, o), rng, self.cfg.rw_samples)[:, 0]
                        for e in self.scheduled_in_horizon(o, 1)
                    ),
                    start=np.zeros(self.cfg.rw_samples),
                )
                crps.append(crps_sample(hist.close[o] * np.exp(z + k * j), hist.close[o + 1]) / hist.close[o])
            fit.append({"scale": k, "mean_crps": float(np.mean(crps)), "n": len(origins)})
        best = min(fit, key=lambda r: r["mean_crps"])
        print(f"earnings jump scale: {best['scale']} (training earnings days: {len(origins)})")
        return float(best["scale"]), fit

    def impact_report(self) -> dict[str, Any]:
        tr, te = self.train_events, self.test_events
        ytr = np.array([e.label for e in tr])
        res: dict[str, Any] = {
            "l2": self.l2,
            "n_train": len(tr),
            "n_test": len(te),
            "test": self.model.evaluate(feature_matrix(te), np.array([e.label for e in te]), ytr),
        }
        earn = [e for e in te if e.group == "earnings"]
        if earn:
            res["test_earnings"] = self.model.evaluate(
                feature_matrix(earn), np.array([e.label for e in earn]), ytr
            )
        # standardised coefficients: which features push towards "up" and towards bigger moves
        res["direction_weights"] = {
            k: float(self.model.W[i, 2] - self.model.W[i, 0]) for i, k in enumerate(FEATURES)
        }
        res["size_weights"] = {k: float(self.model.size_w[i]) for i, k in enumerate(FEATURES)}
        # every out-of-sample event: the model's prediction next to what actually happened
        if te:
            X = feature_matrix(te)
            p, size, exp = self.model.proba(X), self.model.size(X), self.model.expected(X)
            res["events"] = [
                {
                    "date": self.ds.history.dates[e.reaction_idx],
                    "released": e.released,
                    "form": e.form,
                    "items": e.items,
                    "group": e.group,
                    "actual": e.label,
                    "p_down": float(p[i, 0]),
                    "p_flat": float(p[i, 1]),
                    "p_up": float(p[i, 2]),
                    "size": float(size[i]),
                    "expected": float(exp[i]),
                }
                for i, e in enumerate(te)
            ]
        return res

    # ---------------------------------------------------------------- per-origin inputs
    def trailing_vol(self, o: int) -> float:
        c = self.ds.history.close
        r = np.diff(np.log(c[max(0, o - self.cfg.vol_window) : o + 1]))
        return float(r.std(ddof=1)) if len(r) > 2 else 0.015

    def scheduled_in_horizon(self, o: int, h: int) -> list[RealEvent]:
        return [e for e in self.ds.events if e.group == "earnings" and o < e.reaction_idx <= o + h]

    def _masked_features(self, e: RealEvent, o: int) -> np.ndarray:
        """What is known at origin `o` about a scheduled release: its group and the market
        features up to o, not its numbers."""
        f = dict(e.features)
        f.update(features_at(self.ds.history, o + 1))
        f["eps_yoy"] = f["rev_yoy"] = 0.0
        return np.array([[f[k] for k in FEATURES]])

    def task(self, o: int, h: int, params: dict[str, float], oracle: bool) -> OriginTask:
        params = {**self.agent_params, **params}
        start = max(0, o - self.cfg.lookback_days)
        runs = self.cfg.runs
        rows: list[list[tuple[int, str, float, float, float, float]]] = [[] for _ in range(runs)]

        def tick_of(e: RealEvent) -> int | None:
            idx, t = self.slots[e.id]
            if idx < start:
                return None
            return (idx - start) * TICKS_PER_DAY + t

        window = [e for e in self.ds.events if start <= e.reaction_idx <= o + h]
        for e in window:
            tk = tick_of(e)
            if tk is None:
                continue
            cx = 0.4 if e.group in ("earnings", "periodic_report") else 0.2
            if oracle:
                # an earnings release owns its reaction day: a 10-Q reacting the same day carries
                # the earnings move as its label, and must not be injected a second time
                shared = e.group != "earnings" and e.reaction_idx in self.earn_days
                lab = 0.0 if shared or e.label is None else e.label
                sal = float(np.clip(0.3 + 8.0 * abs(lab), 0.2, 1.0))
                for r in rows:
                    r.append((tk, KIND[e.group], lab, float(np.clip(20 * lab, -1, 1)), sal, cx))
            elif e.reaction_idx <= o:  # already released: the model's reading of it
                X = feature_matrix([e])
                imp = float(self.model.expected(X)[0])
                p = self.model.proba(X)[0]
                sal = float(np.clip(0.3 + 8.0 * self.model.size(X)[0], 0.2, 1.0))
                for r in rows:
                    r.append((tk, KIND[e.group], imp, float(p[2] - p[0]), sal, cx))
            elif e.group == "earnings":  # scheduled: a fresh draw of its reaction in every run
                X = self._masked_features(e, o)
                draws = self.jump_scale * self.model.sample(X, self.rng, runs)[:, 0]
                sal = float(np.clip(0.3 + 8.0 * self.model.size(X)[0], 0.2, 1.0))
                for r, d in zip(rows, draws, strict=True):
                    r.append((tk, KIND[e.group], float(d), float(np.clip(20 * d, -1, 1)), sal, cx))
        return OriginTask(
            origin=o,
            horizon=h,
            start=start,
            iv=self.trailing_vol(o) * math.sqrt(252),
            params=params,
            seeds=[self.cfg.seed * 100_003 + o * 101 + i for i in range(runs)],
            events=rows,
        )

    def random_walks(self, o: int, h: int) -> tuple[np.ndarray, np.ndarray]:
        s = self.trailing_vol(o) * math.sqrt(h)
        z = self.rng.normal(-0.5 * s * s, s, self.cfg.rw_samples)
        jumps = np.zeros(self.cfg.rw_samples)
        for e in self.scheduled_in_horizon(o, h):
            jumps += (
                self.jump_scale
                * self.model.sample(self._masked_features(e, o), self.rng, self.cfg.rw_samples)[:, 0]
            )
        return np.exp(z), np.exp(z + jumps)

    # ---------------------------------------------------------------- running
    def _run_tasks(self, ex: ProcessPoolExecutor | None, tasks: list[OriginTask]) -> list[np.ndarray]:
        if ex is None:
            if "world" not in _WORLD:
                _init_worker(self.cfg.n_agents, self.cfg.seed, self.cfg.survey)
            return [_simulate(t) for t in tasks]
        return list(ex.map(_simulate, tasks, chunksize=4))

    def training_origins(self) -> list[int]:
        # a representative sample of training days (earnings days at their natural rate), so the
        # chosen spread fits ordinary days as well as event days
        cand = np.arange(self.from_idx, self.split_idx - max(self.cfg.horizons))
        rng = np.random.default_rng([self.cfg.seed, 7])
        return sorted(
            int(o) for o in rng.choice(cand, size=min(self.cfg.train_origins, len(cand)), replace=False)
        )

    def train_simulation(
        self, ex: ProcessPoolExecutor | None
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        """Grid search over market parameters on training origins, scored by the one-day CRPS of
        the raw ensemble's predictive distribution; then, per horizon, the recalibration."""
        h = 1
        origins = self.training_origins()
        keys = list(self.cfg.grid)
        combos = [dict(zip(keys, vals, strict=True)) for vals in _product([self.cfg.grid[k] for k in keys])]
        close = self.ds.history.close
        log: list[dict[str, Any]] = []
        for params in combos:
            t0 = time.perf_counter()
            sims = self._run_tasks(ex, [self.task(o, h, params, oracle=False) for o in origins])
            crps = [
                crps_sample(close[o] * raw_predictive(s, self.rng, self.cfg.rw_samples), close[o + h])
                / close[o]
                for o, s in zip(origins, sims, strict=True)
            ]
            log.append(
                {
                    "params": params,
                    "mean_crps": float(np.mean(crps)),
                    "mean_ensemble_sd": float(np.mean([_log_stats(s)[1] for s in sims])),
                    "seconds": time.perf_counter() - t0,
                    "_sims": sims,
                }
            )
            print(f"  train {params}: CRPS {np.mean(crps) * 100:.4f}% of price")
        best = min(log, key=lambda r: r["mean_crps"])
        params = dict(best["params"])
        for hh in self.cfg.horizons:
            sims = (
                best["_sims"]
                if hh == h
                else self._run_tasks(ex, [self.task(o, hh, params, oracle=False) for o in origins])
            )
            rv = np.array([self.trailing_vol(o) * math.sqrt(hh) for o in origins])
            y = np.array([math.log(close[o + hh] / close[o]) for o in origins])
            self.recal[hh] = Recalibration.fit(sims, rv, y)
            self.ensembles[f"train_h{hh}"] = np.array(sims)
            self.ensembles[f"train_h{hh}_origins"] = np.array(origins)
            print(f"  recalibration h={hh}: {self.recal[hh]}")
        for r in log:
            r.pop("_sims")
        return params, log

    def backtest(
        self, ex: ProcessPoolExecutor | None, params: dict[str, float], h: int
    ) -> list[dict[str, Any]]:
        hist = self.ds.history
        every = self.cfg.test_every * (1 if h == 1 else self.cfg.long_every)
        origins = list(range(self.split_idx, len(hist.dates) - h, every))
        tasks = [self.task(o, h, params, oracle=False) for o in origins]
        oracle_tasks = [self.task(o, h, params, oracle=True) for o in origins]
        sims = self._run_tasks(ex, tasks + oracle_tasks)
        abm, orc = sims[: len(origins)], sims[len(origins) :]
        self.ensembles[f"test_h{h}"] = np.array(abm)
        self.ensembles[f"test_h{h}_oracle"] = np.array(orc)
        self.ensembles[f"test_h{h}_origins"] = np.array(origins)
        recal = self.recal.get(h, Recalibration())
        n = self.cfg.rw_samples
        rows = []
        for i, o in enumerate(origins):
            p0, actual = float(hist.close[o]), float(hist.close[o + h])
            rw, erw = self.random_walks(o, h)
            row: dict[str, Any] = {
                "origin": hist.dates[o],
                "target": hist.dates[o + h],
                "close": p0,
                "actual": actual,
                "actual_return": actual / p0 - 1.0,
                "earnings_in_horizon": bool(self.scheduled_in_horizon(o, h)),
                "events_known": sum(
                    1 for e in self.ds.events if o - self.cfg.lookback_days <= e.reaction_idx <= o
                ),
            }
            forecasts = (
                rw,
                erw,
                raw_predictive(abm[i], self.rng, n),
                recal.sample(abm[i], self.trailing_vol(o) * math.sqrt(h), self.rng, n),
                raw_predictive(orc[i], self.rng, n),
            )
            for name, ratios in zip(MODELS, forecasts, strict=True):
                s = p0 * ratios
                row[name] = {
                    "crps": crps_sample(s, actual) / p0,
                    "median": float(np.median(s)),
                    "q05": float(np.quantile(s, 0.05)),
                    "q95": float(np.quantile(s, 0.95)),
                    "p_up": float((s > p0).mean()),
                }
            rows.append(row)
        return rows

    def run(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        impact = self.impact_report()
        print(f"impact model: l2={self.l2}, test accuracy {impact['test']['accuracy']:.2f}")
        ex = (
            ProcessPoolExecutor(
                self.cfg.workers,
                initializer=_init_worker,
                initargs=(self.cfg.n_agents, self.cfg.seed, self.cfg.survey),
            )
            if self.cfg.workers > 1
            else None
        )
        try:
            params, train_log = self.train_simulation(ex)
            print(f"trained simulation parameters: {params}")
            results = {h: self.backtest(ex, params, h) for h in self.cfg.horizons}
        finally:
            if ex is not None:
                ex.shutdown()
        hist = self.ds.history
        return json_safe(
            {
                "ticker": hist.ticker,
                "name": hist.name,
                "config": {**asdict(self.cfg), "horizons": list(self.cfg.horizons)},
                "period": {
                    "train": [hist.dates[self.from_idx], hist.dates[self.split_idx - 1]],
                    "test": [hist.dates[self.split_idx], hist.dates[-1]],
                },
                "events": {
                    "total": len(self.ds.events),
                    "labelled": len(self.labelled),
                    "train": len(self.train_events),
                    "test": len(self.test_events),
                },
                "impact_model": {**impact, "jump_scale": self.jump_scale, "jump_fit": self.jump_fit},
                "simulation": {
                    "params": params,
                    "grid": train_log,
                    "recalibration": {str(h): asdict(r) for h, r in self.recal.items()},
                },
                "backtest": {
                    str(h): {"summary": summarize(rows), "origins": rows} for h, rows in results.items()
                },
                "seconds": time.perf_counter() - t0,
            }
        )


def _product(lists: Sequence[Sequence[float]]) -> list[tuple[float, ...]]:
    out: list[tuple[float, ...]] = [()]
    for xs in lists:
        out = [(*p, x) for p in out for x in xs]
    return out


# --------------------------------------------------------------------------- scoring


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def stats(sub: list[dict[str, Any]]) -> dict[str, Any]:
        if not sub:
            return {"n": 0}
        rw = np.mean([r["random_walk"]["crps"] for r in sub])
        out: dict[str, Any] = {"n": len(sub)}
        up = np.array([r["actual_return"] > 0 for r in sub])
        for m in MODELS:
            crps = float(np.mean([r[m]["crps"] for r in sub]))
            inside = np.mean([r[m]["q05"] <= r["actual"] <= r[m]["q95"] for r in sub])
            pu = np.array([r[m]["p_up"] for r in sub])
            out[m] = {
                "mean_crps_pct": 100 * crps,
                "skill_vs_random_walk": float(1 - crps / rw) if rw > 0 else 0.0,
                "coverage_90": float(inside),
                "direction_accuracy": float(((pu > 0.5) == up).mean()),
                "brier_up": float(np.mean((pu - up) ** 2)),
            }
        return out

    return {
        "all": stats(rows),
        "earnings_in_horizon": stats([r for r in rows if r["earnings_in_horizon"]]),
        "no_earnings": stats([r for r in rows if not r["earnings_in_horizon"]]),
    }


# --------------------------------------------------------------------------- outputs


def write_events_json(exp: Experiment, path: Path) -> None:
    """Labelled events in the dated format the web app's Analysis page uploads."""
    out = []
    for e in exp.ds.events:
        t = datetime.fromisoformat(e.released)
        lab = e.label or 0.0
        out.append(
            {
                "date": exp.ds.history.dates[min(exp.slots[e.id][0], len(exp.ds.history.dates) - 1)],
                "time": f"{t.hour:02d}:{t.minute:02d}" if exp.slots[e.id][1] != 32 else "08:00",
                "kind": KIND[e.group],
                "true_impact": float(np.clip(lab, -0.5, 0.5)),
                "sentiment": float(np.clip(20 * lab, -1, 1)),
                "credibility": 0.95,
                "salience": float(np.clip(0.3 + 8 * abs(lab), 0.2, 1.0)),
                "complexity": 0.4 if e.group in ("earnings", "periodic_report") else 0.2,
                "seeding": "official",
                "label": f"{e.form} {', '.join(e.items)}".strip(),
            }
        )
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(description="Train on a stock's past events and forecast its later prices.")
    ap.add_argument("ticker", nargs="?", default="AAPL")
    ap.add_argument("--split", default="2024-01-01")
    ap.add_argument("--horizons", default="1,5")
    ap.add_argument("--agents", type=int, default=1500)
    ap.add_argument("--runs", type=int, default=16)
    ap.add_argument("--train-origins", type=int, default=200)
    ap.add_argument("--workers", type=int, default=min(8, max(1, (os.cpu_count() or 2) - 2)))
    ap.add_argument("--quick", action="store_true", help="tiny grid and few origins (smoke test)")
    ap.add_argument("--data-root")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    cfg = ExperimentConfig(
        ticker=args.ticker,
        split=args.split,
        horizons=tuple(int(x) for x in args.horizons.split(",")),
        n_agents=args.agents,
        runs=args.runs,
        train_origins=args.train_origins,
        workers=args.workers,
        data_root=args.data_root,
        out_dir=args.out,
    )
    agents = load_agent_params(cfg.ticker) if not cfg.data_root else {}
    if not cfg.data_root:  # re-tune the unmodelled flow around the fitted value (agent fit or intraday fit)
        n = agents.get("market.noise_frac", Config().market.noise_frac)
        cfg.grid = {"market.noise_frac": [round(n * f, 3) for f in (0.6, 1.0, 1.5)]}
    if args.quick:
        cfg.grid = {"market.noise_frac": [0.6, 1.5]}
        cfg.runs = min(cfg.runs, 4)
        cfg.train_origins = min(cfg.train_origins, 20)
    exp = Experiment(cfg)
    res = exp.run()
    out = Path(cfg.out_dir) if cfg.out_dir else ROOT / "docs" / "experiments" / cfg.ticker.upper()
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(res), encoding="utf-8")
    np.savez_compressed(out / "ensembles.npz", **exp.ensembles)  # type: ignore[arg-type]
    if not cfg.data_root:
        write_events_json(exp, ROOT / "data" / cfg.ticker.upper() / "events.json")
    from .experiment_report import write_report

    write_report(res, out)
    from .strategy import write_strategy

    write_strategy(cfg.ticker, out)
    print(f"wrote {out} in {res['seconds']:.0f}s")
    return res


if __name__ == "__main__":
    main()
