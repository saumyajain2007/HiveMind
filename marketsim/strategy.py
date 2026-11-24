"""Forecast statistics, the latest forecast, and trading strategies built on the experiment.

    uv run python -m marketsim.strategy AAPL

Reads `docs/experiments/<T>/results.json` and `ensembles.npz` (written by
`marketsim.experiment`) and writes `strategy.json` next to them.

* **Forecast statistics.** For every out-of-sample origin, the recalibrated agent model's
  forecast distribution (lognormal): mean, sd, median, 5/25/75/95% quantiles, P(up), expected
  return, then how it compares with what happened: bias, RMSE, information coefficient
  (correlation of expected with actual return), z-scores, interval coverage, and whether the
  forecast *spread* tracks the size of the realised move (volatility skill), each next to the
  random walk.
* **Latest forecast.** The model run from the last close in the data, 1 and 5 days ahead.
* **Strategies** (daily, AAPL only, positions set at the close from that close's forecast, held
  to the next close; costs charged on every change of position). Every rule is fixed in advance
  or set from the training years; none is tuned on the test period, because tuning on the
  period you report is how backtests lie.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import norm

from .experiment import (
    ROOT,
    Experiment,
    ExperimentConfig,
    Recalibration,
    _init_worker,
    _simulate,
)
from .sim import json_safe

COST_BPS = 5.0  # per unit of position change (AAPL's spread is ~1 bp; this leaves room for impact)
MAX_LEVERAGE = 1.5
Q = (0.05, 0.25, 0.5, 0.75, 0.95)


# --------------------------------------------------------------------------- forecast distributions


def lognormal_stats(p0: float, mu: float, s: float) -> dict[str, float]:
    m = p0 * math.exp(mu + 0.5 * s * s)
    out = {
        "mean": m,
        "sd": m * math.sqrt(math.expm1(s * s)),
        "expected_return": m / p0 - 1.0,
        "p_up": float(norm.cdf(mu / s)) if s > 0 else float(mu > 0),
        "log_mu": mu,
        "log_sd": s,
    }
    for q in Q:
        out[f"q{int(q * 100):02d}"] = p0 * math.exp(mu + s * float(norm.ppf(q)))
    return out


def _t(x: np.ndarray) -> float:
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std() > 0 else 0.0


def forecast_table(exp: Experiment, res: dict[str, Any], ens: Any, h: int) -> dict[str, Any]:
    close = exp.ds.history.close
    dates = exp.ds.history.dates
    rc = Recalibration(**res["simulation"]["recalibration"][str(h)])
    origins = ens[f"test_h{h}_origins"]
    runs = ens[f"test_h{h}"]
    rows = []
    for o, r in zip(origins, runs, strict=True):
        o = int(o)
        p0, actual = float(close[o]), float(close[o + h])
        rv = exp.trailing_vol(o) * math.sqrt(h)
        mu, s = rc.params(r, rv)
        st = lognormal_stats(p0, mu, s)
        y = math.log(actual / p0)
        rows.append(
            {
                "origin": dates[o],
                "target": dates[o + h],
                "close": p0,
                "actual": actual,
                "actual_return": actual / p0 - 1.0,
                **st,
                "z": (y - mu) / s,
                "rw_sd_log": rv,
                "rw_z": (y + 0.5 * rv * rv) / rv,
                "raw_mean": p0 * float(np.mean(r)),
                "raw_sd": p0 * float(np.std(r, ddof=1)),
                "raw_min": p0 * float(np.min(r)),
                "raw_max": p0 * float(np.max(r)),
            }
        )
    ar = np.array([r["actual_return"] for r in rows])
    er = np.array([r["expected_return"] for r in rows])
    z = np.array([r["z"] for r in rows])
    rwz = np.array([r["rw_z"] for r in rows])
    s_model = np.array([r["log_sd"] for r in rows])
    s_rw = np.array([r["rw_sd_log"] for r in rows])
    absy = np.abs(np.log1p(ar))
    ic = float(np.corrcoef(er, ar)[0, 1]) if er.std() > 0 else 0.0
    n = len(rows)

    def cover(zz: np.ndarray, q: float) -> float:
        return float((np.abs(zz) <= norm.ppf(0.5 + q / 2)).mean())

    summary = {
        "n": n,
        "mean_actual_return": float(ar.mean()),
        "mean_expected_return": float(er.mean()),
        "bias": float((ar - er).mean()),
        "rmse_model": float(np.sqrt(np.mean((ar - er) ** 2))),
        "rmse_random_walk": float(np.sqrt(np.mean(ar**2))),  # the random walk expects no change
        "mae_model": float(np.mean(np.abs(ar - er))),
        "mae_random_walk": float(np.mean(np.abs(ar))),
        "information_coefficient": ic,
        "ic_t": ic * math.sqrt((n - 2) / max(1e-12, 1 - ic * ic)) if n > 2 else 0.0,
        "sign_hit_rate": float((np.sign(er - 0) == np.sign(ar)).mean()),
        "z_mean": float(z.mean()),
        "z_sd": float(z.std(ddof=1)),
        "rw_z_mean": float(rwz.mean()),
        "rw_z_sd": float(rwz.std(ddof=1)),
        "coverage_50": cover(z, 0.5),
        "coverage_90": cover(z, 0.9),
        "rw_coverage_50": cover(rwz, 0.5),
        "rw_coverage_90": cover(rwz, 0.9),
        "mean_forecast_sd": float(s_model.mean()),
        "mean_rw_sd": float(s_rw.mean()),
        "realised_rms": float(np.sqrt(np.mean(np.log1p(ar) ** 2))),
        "vol_skill_model": float(np.corrcoef(s_model, absy)[0, 1]),
        "vol_skill_random_walk": float(np.corrcoef(s_rw, absy)[0, 1]),
    }
    return {"summary": summary, "rows": rows}


# --------------------------------------------------------------------------- strategies


def _max_drawdown(eq: np.ndarray) -> float:
    peak = np.maximum.accumulate(eq)
    return float(np.min(eq / peak - 1.0))


def _bootstrap_sharpe(r: np.ndarray, b: np.ndarray, rng: np.random.Generator, n: int = 2000, block: int = 10):
    """Stationary block bootstrap: 95% CI of the annualised Sharpe and P(Sharpe <= buy & hold)."""
    T = len(r)
    shs, diffs = [], []
    for _ in range(n):
        idx = np.empty(T, dtype=int)
        i = 0
        while i < T:
            start = rng.integers(T)
            L = min(int(rng.geometric(1 / block)), T - i)
            idx[i : i + L] = (start + np.arange(L)) % T
            i += L
        rr, bb = r[idx], b[idx]
        sr = rr.mean() / rr.std() * math.sqrt(252) if rr.std() > 0 else 0.0
        sb = bb.mean() / bb.std() * math.sqrt(252) if bb.std() > 0 else 0.0
        shs.append(sr)
        diffs.append(sr - sb)
    return (float(np.quantile(shs, 0.025)), float(np.quantile(shs, 0.975))), float(
        np.mean(np.array(diffs) <= 0)
    )


def strategy_stats(
    w: np.ndarray, ret: np.ndarray, bench: np.ndarray, rng: np.random.Generator
) -> dict[str, Any]:
    dw = np.abs(np.diff(np.concatenate([[0.0], w])))
    net = w * ret - dw * COST_BPS / 1e4
    eq = np.cumprod(1.0 + net)
    years = len(net) / 252
    vol = float(net.std(ddof=1) * math.sqrt(252))
    down = net[net < 0]
    sharpe = float(net.mean() / net.std(ddof=1) * math.sqrt(252)) if net.std() > 0 else 0.0
    X = np.c_[np.ones_like(bench), bench]
    coef, *_ = np.linalg.lstsq(X, net, rcond=None)
    resid = net - X @ coef
    se = math.sqrt(resid.var(ddof=2) * np.linalg.inv(X.T @ X)[0, 0])
    ci, p_worse = _bootstrap_sharpe(net, bench, rng)
    active = w != 0
    mdd = _max_drawdown(np.concatenate([[1.0], eq]))
    cagr = float(eq[-1] ** (1 / years) - 1) if years > 0 else 0.0
    return {
        "total_return": float(eq[-1] - 1.0),
        "cagr": cagr,
        "ann_vol": vol,
        "sharpe": sharpe,
        "sharpe_ci95": ci,
        "p_sharpe_not_above_buy_hold": p_worse,
        "sortino": float(net.mean() * 252 / (down.std(ddof=1) * math.sqrt(252))) if len(down) > 2 else 0.0,
        "max_drawdown": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else 0.0,
        "hit_rate": float((net[active] > 0).mean()) if active.any() else 0.0,
        "exposure": float(np.abs(w).mean()),
        "turnover_per_year": float(dw.sum() / years) if years > 0 else 0.0,
        "costs": float((dw * COST_BPS / 1e4).sum()),
        "alpha_ann": float(coef[0] * 252),
        "alpha_t": float(coef[0] / se) if se > 0 else 0.0,
        "beta": float(coef[1]),
        "mean_daily": float(net.mean()),
        "t_mean": _t(net),
        "equity": eq.tolist(),
    }


def strategies(exp: Experiment, table: dict[str, Any]) -> dict[str, Any]:
    rows = table["rows"]
    close = exp.ds.history.close
    idx = {d: i for i, d in enumerate(exp.ds.history.dates)}
    ret = np.array([r["actual_return"] for r in rows])
    mu = np.array([r["log_mu"] for r in rows])
    s = np.array([r["log_sd"] for r in rows])
    rw_s = np.array([r["rw_sd_log"] for r in rows])
    # the volatility target: AAPL's own daily sd over the training years (fixed in advance)
    tr = np.diff(np.log(close[exp.from_idx : exp.split_idx]))
    target = float(tr.std(ddof=1))
    earn_days = {
        e.reaction_idx: e for e in exp.ds.events if e.group == "earnings" and e.reaction_idx >= exp.split_idx
    }
    w_earn = np.zeros(len(rows))
    for i, r in enumerate(rows):
        o = idx[r["origin"]]
        e = earn_days.get(o + 1)
        if e is not None:
            w_earn[i] = float(np.sign(exp.model.expected(exp._masked_features(e, o))[0]))
    rules = {
        "buy_hold": (
            "Buy and hold",
            "Always 100% long. The benchmark.",
            np.ones(len(rows)),
        ),
        "model_long_short": (
            "Direction, long/short",
            "100% long when the model's P(up) > 50%, 100% short otherwise.",
            np.where(mu > 0, 1.0, -1.0),
        ),
        "model_long_flat": (
            "Direction, long/flat",
            "100% long when P(up) > 50%, in cash otherwise.",
            np.where(mu > 0, 1.0, 0.0),
        ),
        "vol_target_model": (
            "Volatility target (model)",
            f"Long, sized to a {target * 100:.2f}% daily risk target (AAPL's 2016-2023 sd) using the "
            f"model's forecast sd; capped at {MAX_LEVERAGE}x.",
            np.clip(target / s, 0.0, MAX_LEVERAGE),
        ),
        "vol_target_trailing": (
            "Volatility target (trailing vol)",
            "The same sizing with plain 20-day trailing volatility instead of the model: shows "
            "whether the model adds anything to a naive risk forecast.",
            np.clip(target / rw_s, 0.0, MAX_LEVERAGE),
        ),
        "earnings_classifier": (
            "Earnings classifier",
            "Only on earnings reaction days: long or short by the sign of the classifier's expected "
            "reaction (date known in advance, numbers masked); in cash otherwise.",
            w_earn,
        ),
    }
    rng = np.random.default_rng(3)
    out = {}
    for k, (label, desc, w) in rules.items():
        out[k] = {"label": label, "description": desc, **strategy_stats(w, ret, ret, rng)}
    return {
        "cost_bps": COST_BPS,
        "max_leverage": MAX_LEVERAGE,
        "vol_target_daily": target,
        "dates": [r["target"] for r in rows],
        "start": rows[0]["origin"],
        "results": out,
    }


# --------------------------------------------------------------------------- latest forecast


def _next_business_days(d: str, n: int) -> list[str]:
    out: list[str] = []
    x = date.fromisoformat(d)
    while len(out) < n:
        x += timedelta(days=1)
        if x.weekday() < 5:
            out.append(x.isoformat())
    return out


def latest_forecast(exp: Experiment, res: dict[str, Any]) -> dict[str, Any]:
    h_all = [int(h) for h in res["simulation"]["recalibration"]]
    o = len(exp.ds.history.dates) - 1
    p0 = float(exp.ds.history.close[o])
    _init_worker(exp.cfg.n_agents, exp.cfg.seed)
    params = dict(res["simulation"]["params"])
    days = _next_business_days(exp.ds.history.dates[o], max(h_all))
    out: dict[str, Any] = {"date": exp.ds.history.dates[o], "close": p0, "horizons": {}}
    for h in h_all:
        task = exp.task(o, h, params, oracle=False)
        ratios = _simulate(task)
        rc = Recalibration(**res["simulation"]["recalibration"][str(h)])
        mu, s = rc.params(ratios, exp.trailing_vol(o) * math.sqrt(h))
        out["horizons"][str(h)] = {
            "target": days[h - 1],
            **lognormal_stats(p0, mu, s),
            "runs": (p0 * ratios).tolist(),
            "random_walk_sd": p0 * exp.trailing_vol(o) * math.sqrt(h),
            "scheduled_earnings": len(exp.scheduled_in_horizon(o, h)),
        }
    return out


# --------------------------------------------------------------------------- main


def write_strategy(ticker: str, out_dir: Path | None = None, n_agents: int | None = None) -> Path:
    out = out_dir or ROOT / "docs" / "experiments" / ticker.upper()
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    ens = np.load(out / "ensembles.npz")
    c = res["config"]
    exp = Experiment(
        ExperimentConfig(
            ticker=ticker,
            split=c["split"],
            train_from=c["train_from"],
            n_agents=n_agents or c["n_agents"],
            runs=c["runs"],
            seed=c["seed"],
            lookback_days=c["lookback_days"],
            vol_window=c["vol_window"],
            agent_params=c.get("agent_params") or {},
            data_root=c.get("data_root"),
        )
    )
    tables = {h: forecast_table(exp, res, ens, int(h)) for h in res["simulation"]["recalibration"]}
    doc = {
        "ticker": res["ticker"],
        "name": res["name"],
        "period": res["period"],
        "agent_params": c.get("agent_params") or {},
        "latest": latest_forecast(exp, res),
        "forecasts": tables,
        "strategy": strategies(exp, tables["1"]),
    }
    p = out / "strategy.json"
    p.write_text(json.dumps(json_safe(doc)), encoding="utf-8")
    return p


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Forecast statistics and trading strategies.")
    ap.add_argument("ticker", nargs="?", default="AAPL")
    args = ap.parse_args(argv)
    p = write_strategy(args.ticker)
    doc = json.loads(p.read_text(encoding="utf-8"))
    for v in doc["strategy"]["results"].values():
        print(
            f"{v['label']:34s} total {v['total_return'] * 100:+7.1f}%  Sharpe {v['sharpe']:+.2f} "
            f"[{v['sharpe_ci95'][0]:+.2f}, {v['sharpe_ci95'][1]:+.2f}]  maxDD {v['max_drawdown'] * 100:6.1f}%  "
            f"alpha {v['alpha_ann'] * 100:+.1f}%/yr (t {v['alpha_t']:+.2f})"
        )
    for h, t in doc["forecasts"].items():
        s = t["summary"]
        print(
            f"h={h}: IC {s['information_coefficient']:+.3f} (t {s['ic_t']:+.2f}), cov90 {s['coverage_90']:.2f}, "
            f"vol skill model {s['vol_skill_model']:.2f} vs RW {s['vol_skill_random_walk']:.2f}"
        )
    lt = doc["latest"]
    for f in lt["horizons"].values():
        print(
            f"latest {lt['date']} close {lt['close']:.2f} -> {f['target']}: mean {f['mean']:.2f} sd {f['sd']:.2f} "
            f"90% [{f['q05']:.2f}, {f['q95']:.2f}] P(up) {f['p_up']:.2f}"
        )
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
