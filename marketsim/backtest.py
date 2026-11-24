"""Backtest against a random walk with CRPS (issue #13, HANDOFF §4 M5).

For each forecast origin (a day index into a daily close series):

1. Only events at or before the origin's close are used (no lookahead). The simulation starts
   `lookback_days` before the origin, so recent events have time to spread, and its implied
   vol is the trailing realised vol at the origin.
2. Monte Carlo runs give a sample of the simulated return from the origin close to the close
   `horizon` days later; applied to the actual origin close, that is the model's forecast.
3. The benchmark is a driftless lognormal random walk with the same trailing realised vol.
4. Both are scored with the sample CRPS (energy form) against the actual close.

The skill score is 1 − mean CRPS(model) / mean CRPS(random walk): above 0 the model beats the
random walk.

Data formats (see the README): prices are a CSV with a `date,close` header; events are a JSON
list of event objects (as in `events.load_events`) where `tick` is replaced by `date`
(YYYY-MM-DD) or `day` (index into the price series) plus an optional `time` ("HH:MM", default
09:00).
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
from scipy.special import ndtr

from .config import MARKET_CLOSE_TICK, TICKS_PER_DAY, Config
from .events import Event, event_from_dict
from .sim import Scenario, Simulation, World

CLOSE_TICK = MARKET_CLOSE_TICK - 1  # the last open tick of a day
MINUTES_PER_TICK = 24 * 60 // TICKS_PER_DAY


# --------------------------------------------------------------------------- CRPS


def crps_sample(samples: np.ndarray, y: float) -> float:
    """CRPS of an ensemble, energy form: E|X − y| − ½·E|X − X'| (O(m log m))."""
    x = np.sort(np.asarray(samples, np.float64))
    m = len(x)
    if m == 0:
        raise ValueError("need at least one sample")
    term1 = np.abs(x - y).mean()
    i = np.arange(1, m + 1)
    term2 = 2.0 * np.sum((2 * i - m - 1) * x) / (m * m)  # E|X − X'| from the sorted sample
    return float(term1 - 0.5 * term2)


def crps_gaussian(mu: float, sigma: float, y: float) -> float:
    """Closed-form CRPS of N(mu, sigma²) (Gneiting & Raftery 2007)."""
    z = (y - mu) / sigma
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    return float(sigma * (z * (2 * ndtr(z) - 1) + 2 * pdf - 1 / math.sqrt(math.pi)))


# --------------------------------------------------------------------------- data


def load_price_csv(path: str | Path) -> tuple[list[str], np.ndarray]:
    """`date,close` CSV (header required, dates ascending). Returns (dates, closes)."""
    dates, closes = [], []
    with Path(path).open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = [c.strip().lower() for c in (reader.fieldnames or [])]
        if "date" not in fields or "close" not in fields:
            raise ValueError("expected a CSV with 'date' and 'close' columns")
        for row in reader:
            row = {k.strip().lower(): v for k, v in row.items()}
            close = float(row["close"])
            if not math.isfinite(close) or close <= 0:
                raise ValueError(f"bad close {row['close']!r} on {row['date']}")
            dates.append(row["date"].strip())
            closes.append(close)
    if dates != sorted(dates):
        raise ValueError("dates must be ascending")
    if len(set(dates)) != len(dates):
        raise ValueError("duplicate dates")
    return dates, np.asarray(closes)


@dataclass
class DatedEvent:
    day: int  # index into the price series
    event: Event  # `tick` is the tick within that day (0..95)

    @property
    def time(self) -> int:
        """Absolute tick counted from day 0 of the series."""
        return self.day * TICKS_PER_DAY + self.event.tick


def parse_dated_events(
    raw: Sequence[Mapping[str, Any]], dates: Sequence[str] | None = None
) -> list[DatedEvent]:
    out = []
    index = {d: i for i, d in enumerate(dates or [])}
    for i, d in enumerate(raw):
        d = dict(d)
        if "date" in d:
            if d["date"] not in index:
                raise ValueError(f"event {i}: date {d['date']} not in the price series")
            day = index[d.pop("date")]
        elif "day" in d:
            day = d.pop("day")
            if not isinstance(day, int) or day < 0:
                raise ValueError(f"event {i}: day must be a non-negative integer")
        else:
            raise ValueError(f"event {i}: needs 'date' or 'day'")
        hh, mm = (int(x) for x in str(d.pop("time", "09:00")).split(":"))
        d["tick"] = (hh * 60 + mm) // MINUTES_PER_TICK
        d.setdefault("id", i)
        out.append(DatedEvent(day, event_from_dict(d)))
    return out


def load_dated_events(path: str | Path, dates: Sequence[str] | None = None) -> list[DatedEvent]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, Mapping):
        data = data.get("events")
    if not isinstance(data, list):
        raise ValueError("expected a JSON list of events or an object with an 'events' list")
    return parse_dated_events(data, dates)


def synthetic_series(
    days: int = 60, seed: int = 0, daily_vol: float = 0.02, n_events: int = 6
) -> tuple[np.ndarray, list[DatedEvent]]:
    """A synthetic daily close series with real news jumps, for the demo (HANDOFF: the demo
    runs on synthetic data only). Returns (closes, dated events)."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0, daily_vol, days)
    events = []
    for k, day in enumerate(sorted(rng.choice(np.arange(5, days), n_events, replace=False))):
        impact = float(rng.normal(0.0, 0.04))
        r[day] += impact
        ev = Event(
            tick=8 * 4,  # 08:00, before the open
            kind=str(rng.choice(["earnings", "product", "regulatory", "macro"])),
            ticker=0,
            true_impact=impact,
            sentiment=float(np.clip(10 * impact, -1, 1)),
            credibility=0.9,
            salience=float(np.clip(0.4 + 8 * abs(impact), 0, 1)),
            complexity=0.3,
            seeding="official",
            id=k,
        )
        events.append(DatedEvent(int(day), ev))
    closes = 100.0 * np.exp(np.cumsum(r))
    return closes, events


# --------------------------------------------------------------------------- forecasts


def trailing_vol(closes: np.ndarray, origin: int, window: int = 20) -> float:
    """Daily log-return sd over the `window` days up to and including `origin`."""
    lo = max(0, origin - window)
    r = np.diff(np.log(closes[lo : origin + 1]))
    return float(r.std(ddof=1)) if len(r) >= 2 else 0.02


def random_walk_samples(
    p0: float, daily_vol: float, horizon: int, n: int, rng: np.random.Generator
) -> np.ndarray:
    """Driftless lognormal random walk: p0 · exp(N(−½σ²h, σ²h)) (mean-preserving)."""
    s = daily_vol * math.sqrt(horizon)
    return p0 * np.exp(rng.normal(-0.5 * s * s, s, n))


def events_known_at(events: Sequence[DatedEvent], origin: int) -> list[DatedEvent]:
    """Events at or before the origin's close (anything later would be lookahead)."""
    cutoff = origin * TICKS_PER_DAY + CLOSE_TICK
    return [e for e in events if e.time <= cutoff]


def model_samples(
    cfg: Config,
    world: World,
    closes: np.ndarray,
    events: Sequence[DatedEvent],
    origin: int,
    horizon: int,
    seeds: Sequence[int],
    lookback_days: int = 3,
    vol_window: int = 20,
) -> tuple[np.ndarray, list[int]]:
    """Simulated closes `horizon` days after `origin`, rebased to the actual origin close.
    Returns (samples, ids of the events used)."""
    start = max(0, origin - lookback_days)
    known = [e for e in events_known_at(events, origin) if e.day >= start]
    sim_events = [replace(e.event, tick=e.time - start * TICKS_PER_DAY, parent=-1) for e in known]
    iv = trailing_vol(closes, origin, vol_window) * math.sqrt(cfg.market.trading_days_per_year)
    run_cfg = replace(cfg, market=replace(cfg.market, implied_vol=float(np.clip(iv, 0.05, 3.0))))
    origin_tick = (origin - start) * TICKS_PER_DAY + CLOSE_TICK
    end_tick = origin_tick + horizon * TICKS_PER_DAY
    out = []
    for s in seeds:
        res = Simulation(run_cfg, Scenario(sim_events), s, world=world).run(end_tick + 1)
        p = res["series"]["price"]
        out.append(p[end_tick] / p[origin_tick])
    return closes[origin] * np.asarray(out), [e.event.id for e in known]


# --------------------------------------------------------------------------- backtest


@dataclass
class BacktestResult:
    origins: list[dict[str, Any]]  # per origin: date/day, actual, crps_model, crps_rw, ...
    horizon: int
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def mean_crps_model(self) -> float:
        return float(np.mean([o["crps_model"] for o in self.origins]))

    @property
    def mean_crps_rw(self) -> float:
        return float(np.mean([o["crps_rw"] for o in self.origins]))

    @property
    def skill(self) -> float:
        """1 − mean CRPS(model) / mean CRPS(random walk)."""
        return 1.0 - self.mean_crps_model / self.mean_crps_rw if self.mean_crps_rw > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "origins": self.origins,
            "mean_crps_model": self.mean_crps_model,
            "mean_crps_rw": self.mean_crps_rw,
            "skill": self.skill,
            "meta": self.meta,
        }


def backtest(
    price_series: np.ndarray,
    events: Sequence[DatedEvent],
    origins: Sequence[int],
    horizon: int = 1,
    *,
    config: Config | None = None,
    runs: int = 10,
    rw_samples: int = 2_000,
    lookback_days: int = 3,
    vol_window: int = 20,
    dates: Sequence[str] | None = None,
    seed: int = 0,
    world: World | None = None,
    on_origin: Callable[[int, int, dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> BacktestResult:
    closes = np.asarray(price_series, np.float64)
    cfg = config or Config()
    world = world or World.build(cfg)
    rng = np.random.default_rng([seed, 13])
    seeds = list(range(1, runs + 1))
    rows: list[dict[str, Any]] = []
    for k, o in enumerate(origins):
        if should_stop is not None and should_stop():
            break
        if not 0 <= o < len(closes) - horizon:
            raise ValueError(f"origin {o} leaves no room for a {horizon}-day horizon")
        actual = float(closes[o + horizon])
        model, used = model_samples(cfg, world, closes, events, o, horizon, seeds, lookback_days, vol_window)
        rw = random_walk_samples(
            float(closes[o]), trailing_vol(closes, o, vol_window), horizon, rw_samples, rng
        )
        row = {
            "origin": o,
            "date": dates[o] if dates else None,
            "close": float(closes[o]),
            "actual": actual,
            "crps_model": crps_sample(model, actual),
            "crps_rw": crps_sample(rw, actual),
            "model_median": float(np.median(model)),
            "model_q05": float(np.quantile(model, 0.05)),
            "model_q95": float(np.quantile(model, 0.95)),
            "rw_q05": float(np.quantile(rw, 0.05)),
            "rw_q95": float(np.quantile(rw, 0.95)),
            "events_used": used,
        }
        rows.append(row)
        if on_origin is not None:
            on_origin(k, len(origins), row)
    return BacktestResult(
        rows,
        horizon,
        meta={
            "runs": runs,
            "lookback_days": lookback_days,
            "vol_window": vol_window,
            "n_agents": cfg.n_agents,
        },
    )


def main() -> None:  # python -m marketsim.backtest: synthetic demo
    closes, events = synthetic_series(days=40, seed=1)
    cfg = replace(Config(), n_agents=3_000)
    res = backtest(closes, events, origins=list(range(22, 38, 2)), horizon=1, config=cfg, runs=8)
    for o in res.origins:
        print(
            f"day {o['origin']:3d}  actual {o['actual']:7.2f}  "
            f"CRPS model {o['crps_model']:.3f}  rw {o['crps_rw']:.3f}"
        )
    print(
        f"mean CRPS model {res.mean_crps_model:.3f}, "
        f"random walk {res.mean_crps_rw:.3f}, skill {res.skill:+.3f}"
    )


if __name__ == "__main__":
    main()
