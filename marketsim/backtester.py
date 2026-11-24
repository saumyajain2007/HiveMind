"""A small, dependency-free backtesting framework for signals built on the model's forecasts.

    from marketsim.backtester import Backtest, Costs, Signal

    bt = Backtest(dates, returns, benchmark=returns, costs=Costs(commission_bps=1, slippage_bps=4))
    res = bt.run(Signal("long_flat", "Long/flat", "Long when P(up) > 50%", positions))
    print(res.stats["sharpe"], res.stats["deflated_sharpe"], len(res.trades))

Conventions (daily bars, close to close):

* ``returns[t]`` is the asset's simple return from close t to close t+1;
* ``positions[t]`` is the target weight decided at close t from information up to close t and
  held to close t+1 (negative = short, |w| > 1 = leverage). A signal therefore never sees the
  return it is paid on;
* costs are charged on every change of position: commission + slippage in bp of the traded
  notional, and a borrow fee (annual bp) on short exposure.

Statistics: total return, CAGR, volatility, Sharpe (with a stationary-bootstrap 95% CI),
Sortino, Calmar, max drawdown and its duration, per-trade win rate, profit factor, expectancy,
exposure and turnover, alpha / beta / information ratio against the benchmark, skew and
kurtosis, and the two overfitting-aware ratios of Bailey and Lopez de Prado:

* **Probabilistic Sharpe ratio (PSR):** P(true Sharpe > 0) given the track record's length,
  skew and fat tails;
* **Deflated Sharpe ratio (DSR):** the PSR against the Sharpe one would expect from the *best of
  N* strategies that have no skill, where N is how many variants were tried. Trying many
  variants and keeping the best is exactly how a backtest overfits; the DSR charges for it.

`forecast_fitness` scores the forecasts themselves (information coefficient, rank IC, hit
rate, Brier score, log loss, calibration bins).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.stats import norm, spearmanr

EULER_GAMMA = 0.5772156649015329


@dataclass
class Costs:
    commission_bps: float = 1.0
    slippage_bps: float = 4.0  # half-spread + impact for a liquid large cap
    borrow_bps_annual: float = 30.0  # general-collateral borrow fee on shorts

    @property
    def per_trade(self) -> float:
        return (self.commission_bps + self.slippage_bps) / 1e4


@dataclass
class Signal:
    name: str
    label: str
    description: str
    positions: np.ndarray
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trade:
    side: str
    entry: str
    exit: str
    bars: int
    weight: float
    ret: float  # compounded net return of the position over the trade

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "entry": self.entry,
            "exit": self.exit,
            "bars": self.bars,
            "weight": self.weight,
            "ret": self.ret,
        }


@dataclass
class BacktestResult:
    name: str
    label: str
    description: str
    dates: list[str]
    positions: np.ndarray
    net: np.ndarray
    equity: np.ndarray
    drawdown: np.ndarray
    trades: list[Trade]
    stats: dict[str, Any]

    def to_dict(self, max_trades: int = 60) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            **self.stats,
            "equity": self.equity.tolist(),
            "drawdown": self.drawdown.tolist(),
            "positions": self.positions.tolist(),
            "trades": [t.to_dict() for t in self.trades[-max_trades:]],
        }


# --------------------------------------------------------------------------- statistics


def _skew_kurt(x: np.ndarray) -> tuple[float, float]:
    s = x.std()
    if s <= 0 or len(x) < 4:
        return 0.0, 3.0
    z = (x - x.mean()) / s
    return float(np.mean(z**3)), float(np.mean(z**4))


def probabilistic_sharpe(sr: float, n: int, skew: float, kurt: float, sr_star: float = 0.0) -> float:
    """P(true per-period Sharpe > sr_star) for an observed per-period Sharpe `sr` over n periods
    (Bailey & Lopez de Prado 2012; kurt is the raw kurtosis, 3 for a normal)."""
    if n < 3:
        return float("nan")
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    return float(norm.cdf((sr - sr_star) * math.sqrt(n - 1) / denom))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """Expected maximum per-period Sharpe among `n_trials` skill-less strategies whose Sharpe
    estimates vary with variance `var_sr` (Bailey & Lopez de Prado 2014)."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    a = norm.ppf(1 - 1 / n_trials)
    b = norm.ppf(1 - 1 / (n_trials * math.e))
    return float(math.sqrt(var_sr) * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b))


def _max_dd(equity: np.ndarray) -> tuple[float, int, np.ndarray]:
    eq = np.concatenate([[1.0], equity])
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    longest, cur = 0, 0
    for v in dd:
        cur = cur + 1 if v < 0 else 0
        longest = max(longest, cur)
    return float(np.min(dd)), longest, dd[1:]


def _bootstrap_sharpe_ci(r: np.ndarray, rng: np.random.Generator, ppy: int, n: int = 2000, block: int = 10):
    T = len(r)
    out = np.empty(n)
    for k in range(n):
        idx = np.empty(T, dtype=int)
        i = 0
        while i < T:
            start = rng.integers(T)
            L = min(int(rng.geometric(1 / block)), T - i)
            idx[i : i + L] = (start + np.arange(L)) % T
            i += L
        x = r[idx]
        out[k] = x.mean() / x.std() * math.sqrt(ppy) if x.std() > 0 else 0.0
    return [float(np.quantile(out, 0.025)), float(np.quantile(out, 0.975))]


def trades_from_positions(dates: Sequence[str], positions: np.ndarray, net: np.ndarray) -> list[Trade]:
    """Contiguous runs of same-sign, non-zero positions; return compounded from the net series."""
    trades: list[Trade] = []
    i, n = 0, len(positions)
    while i < n:
        if positions[i] == 0:
            i += 1
            continue
        sgn = np.sign(positions[i])
        j = i
        while j + 1 < n and np.sign(positions[j + 1]) == sgn:
            j += 1
        r = float(np.prod(1 + net[i : j + 1]) - 1)
        trades.append(
            Trade(
                side="long" if sgn > 0 else "short",
                entry=dates[i],
                exit=dates[min(j + 1, n - 1)] if j + 1 < n else dates[j],
                bars=j - i + 1,
                weight=float(np.mean(np.abs(positions[i : j + 1]))),
                ret=r,
            )
        )
        i = j + 1
    return trades


def performance_stats(
    net: np.ndarray,
    positions: np.ndarray,
    trades: list[Trade],
    bench: np.ndarray | None,
    ppy: int,
    costs_paid: float,
    turnover: float,
    rng: np.random.Generator,
) -> dict[str, Any]:
    n = len(net)
    years = n / ppy
    equity = np.cumprod(1 + net)
    sd = float(net.std(ddof=1)) if n > 1 else 0.0
    sr_p = float(net.mean() / sd) if sd > 0 else 0.0
    skew, kurt = _skew_kurt(net)
    down = net[net < 0]
    mdd, mdd_days, dd = _max_dd(equity)
    cagr = float(equity[-1] ** (1 / years) - 1) if years > 0 and equity[-1] > 0 else -1.0
    wins = [t.ret for t in trades if t.ret > 0]
    losses = [t.ret for t in trades if t.ret <= 0]
    out: dict[str, Any] = {
        "periods": n,
        "years": years,
        "total_return": float(equity[-1] - 1),
        "cagr": cagr,
        "ann_vol": sd * math.sqrt(ppy),
        "sharpe": sr_p * math.sqrt(ppy),
        "sharpe_ci95": _bootstrap_sharpe_ci(net, rng, ppy) if n > 20 else [float("nan")] * 2,
        "sortino": float(net.mean() * ppy / (down.std(ddof=1) * math.sqrt(ppy))) if len(down) > 2 else 0.0,
        "max_drawdown": mdd,
        "max_drawdown_days": mdd_days,
        "calmar": cagr / abs(mdd) if mdd < 0 else 0.0,
        "skew": skew,
        "kurtosis": kurt - 3.0,
        "probabilistic_sharpe": probabilistic_sharpe(sr_p, n, skew, kurt),
        "n_trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "profit_factor": float(sum(wins) / abs(sum(losses)))
        if losses and sum(losses) != 0
        else float("inf")
        if wins
        else 0.0,
        "expectancy": float(np.mean([t.ret for t in trades])) if trades else 0.0,
        "avg_win": float(np.mean(wins)) if wins else 0.0,
        "avg_loss": float(np.mean(losses)) if losses else 0.0,
        "avg_bars": float(np.mean([t.bars for t in trades])) if trades else 0.0,
        "hit_rate": float((net[positions != 0] > 0).mean()) if (positions != 0).any() else 0.0,
        "exposure": float(np.abs(positions).mean()),
        "turnover_per_year": turnover / years if years > 0 else 0.0,
        "costs": costs_paid,
        "mean_daily": float(net.mean()),
        "t_mean": float(net.mean() / (sd / math.sqrt(n))) if sd > 0 else 0.0,
        "_sr_period": sr_p,
        "_skew": skew,
        "_kurt": kurt,
    }
    if bench is not None:
        X = np.c_[np.ones(n), bench]
        coef, *_ = np.linalg.lstsq(X, net, rcond=None)
        resid = net - X @ coef
        se = math.sqrt(resid.var(ddof=2) * np.linalg.inv(X.T @ X)[0, 0]) if n > 3 else 0.0
        active = net - bench
        te = float(active.std(ddof=1))
        out.update(
            {
                "alpha_ann": float(coef[0] * ppy),
                "alpha_t": float(coef[0] / se) if se > 0 else 0.0,
                "beta": float(coef[1]),
                # identical to the benchmark (tracking error ~0): the ratio is meaningless
                "information_ratio": float(active.mean() / te * math.sqrt(ppy)) if te > 1e-4 else None,
                "correlation_to_benchmark": float(np.corrcoef(net, bench)[0, 1]) if net.std() > 0 else 0.0,
            }
        )
    return out | {"_drawdown": dd}


# --------------------------------------------------------------------------- the engine


class Backtest:
    def __init__(
        self,
        dates: Sequence[str],
        returns: np.ndarray,
        benchmark: np.ndarray | None = None,
        costs: Costs | None = None,
        periods_per_year: int = 252,
        max_leverage: float | None = None,
        seed: int = 3,
    ) -> None:
        self.dates = list(dates)
        self.returns = np.asarray(returns, np.float64)
        self.benchmark = None if benchmark is None else np.asarray(benchmark, np.float64)
        self.costs = costs or Costs()
        self.ppy = periods_per_year
        self.max_leverage = max_leverage
        self.seed = seed
        if len(self.dates) != len(self.returns):
            raise ValueError("dates and returns must have the same length")

    def run(self, signal: Signal) -> BacktestResult:
        w = np.asarray(signal.positions, np.float64)
        if w.shape != self.returns.shape:
            raise ValueError(f"{signal.name}: positions {w.shape} vs returns {self.returns.shape}")
        if self.max_leverage is not None:
            w = np.clip(w, -self.max_leverage, self.max_leverage)
        dw = np.abs(np.diff(np.concatenate([[0.0], w])))
        trade_cost = dw * self.costs.per_trade
        borrow = np.maximum(-w, 0.0) * self.costs.borrow_bps_annual / 1e4 / self.ppy
        net = w * self.returns - trade_cost - borrow
        trades = trades_from_positions(self.dates, w, net)
        st = performance_stats(
            net,
            w,
            trades,
            self.benchmark,
            self.ppy,
            float(trade_cost.sum() + borrow.sum()),
            float(dw.sum()),
            np.random.default_rng(self.seed),
        )
        dd = st.pop("_drawdown")
        return BacktestResult(
            signal.name,
            signal.label,
            signal.description,
            self.dates,
            w,
            net,
            np.cumprod(1 + net),
            dd,
            trades,
            st,
        )

    def run_all(self, signals: Sequence[Signal], n_trials: int | None = None) -> list[BacktestResult]:
        """Run every signal; the deflated Sharpe uses `n_trials` (default: the number of signals
        here) and the spread of their Sharpe ratios. Pass the true number of variants you tried,
        including ones you threw away, or the deflation is too kind."""
        res = [self.run(s) for s in signals]
        srs = np.array([r.stats["_sr_period"] for r in res])
        N = max(n_trials or len(res), 1)
        var_sr = float(srs.var(ddof=1)) if len(srs) > 1 else 0.0
        sr0 = expected_max_sharpe(N, var_sr)
        for r in res:
            s = r.stats
            s["deflated_sharpe"] = probabilistic_sharpe(
                s["_sr_period"], s["periods"], s["_skew"], s["_kurt"], sr0
            )
            s["trials"] = N
            s["expected_max_sharpe_ann"] = sr0 * math.sqrt(self.ppy)
            for k in ("_sr_period", "_skew", "_kurt"):
                s.pop(k, None)
        return res


# --------------------------------------------------------------------------- model fitness


def forecast_fitness(
    expected_return: np.ndarray, p_up: np.ndarray, actual_return: np.ndarray, bins: int = 10
) -> dict[str, Any]:
    """How good are the forecasts themselves, before any trading rule."""
    er, p, ar = (np.asarray(x, np.float64) for x in (expected_return, p_up, actual_return))
    n = len(ar)
    up = (ar > 0).astype(float)
    ic = float(np.corrcoef(er, ar)[0, 1]) if er.std() > 0 and ar.std() > 0 else 0.0
    ric = float(spearmanr(er, ar).statistic) if er.std() > 0 else 0.0
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    base = up.mean()
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    calib = []
    for k in range(bins):
        m = (p >= edges[k]) & (p <= edges[k + 1]) if k == bins - 1 else (p >= edges[k]) & (p < edges[k + 1])
        if m.sum():
            calib.append({"p_mean": float(p[m].mean()), "freq_up": float(up[m].mean()), "n": int(m.sum())})
    return {
        "n": n,
        "information_coefficient": ic,
        "ic_t": ic * math.sqrt((n - 2) / max(1e-12, 1 - ic * ic)) if n > 2 else 0.0,
        "rank_ic": ric,
        "hit_rate": float((np.sign(er) == np.sign(ar)).mean()),
        "brier": float(np.mean((p - up) ** 2)),
        "brier_climatology": float(np.mean((base - up) ** 2)),
        "log_loss": float(-np.mean(up * np.log(pc) + (1 - up) * np.log(1 - pc))),
        "log_loss_climatology": float(-np.mean(up * np.log(base) + (1 - up) * np.log(1 - base)))
        if 0 < base < 1
        else 0.0,
        "calibration": calib,
    }
