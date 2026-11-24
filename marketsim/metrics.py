"""Summary statistics of price paths: returns, stylised facts, drawdowns (#10, #11).

HANDOFF §4 M6: kurtosis of open-tick returns and the autocorrelation of |r| at lags 1–10 are
*reported*, not asserted.
"""

from __future__ import annotations

import numpy as np

from .config import MARKET_CLOSE_TICK, MARKET_OPEN_TICK, TICKS_PER_DAY


def open_mask(n_ticks: int, start: int = 0) -> np.ndarray:
    t = (np.arange(start, start + n_ticks)) % TICKS_PER_DAY
    return (t >= MARKET_OPEN_TICK) & (t < MARKET_CLOSE_TICK)


def open_tick_returns(prices: np.ndarray) -> np.ndarray:
    """Log returns of the open ticks (the price only changes in auctions)."""
    prices = np.asarray(prices, np.float64)
    r = np.diff(np.log(prices), prepend=np.log(prices[0]))
    return r[open_mask(len(prices))]


def excess_kurtosis(x: np.ndarray) -> float:
    x = np.asarray(x, np.float64)
    if len(x) < 4:
        return float("nan")
    d = x - x.mean()
    v = (d * d).mean()
    return float((d**4).mean() / (v * v) - 3.0) if v > 0 else float("nan")


def acf(x: np.ndarray, lags: int = 10) -> np.ndarray:
    """Sample autocorrelation at lags 1..`lags`."""
    x = np.asarray(x, np.float64)
    d = x - x.mean()
    denom = float((d * d).sum())
    out = np.full(lags, np.nan)
    if denom <= 0:
        return out
    for k in range(1, lags + 1):
        if k < len(x):
            out[k - 1] = float((d[:-k] * d[k:]).sum() / denom)
    return out


def max_drawdown(prices: np.ndarray) -> float:
    """Largest peak-to-trough fall as a fraction (0.1 = −10%)."""
    p = np.asarray(prices, np.float64)
    peak = np.maximum.accumulate(p)
    return float(np.max(1.0 - p / peak)) if len(p) else 0.0


def stylized_facts(prices: np.ndarray, lags: int = 10) -> dict:
    r = open_tick_returns(prices)
    return {
        "n_returns": len(r),
        "return_sd": float(r.std()) if len(r) else 0.0,
        "excess_kurtosis": excess_kurtosis(r),
        "acf_r": acf(r, lags).tolist(),
        "acf_abs_r": acf(np.abs(r), lags).tolist(),
    }
