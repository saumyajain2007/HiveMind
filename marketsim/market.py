"""Market: state, batch auction with a square-root market maker, Black–Scholes (issue #8).

HANDOFF §2.8–2.10 and §4 M3 `market.py`.

Each open tick is one **call auction**. Agents and firms submit limit orders. The clearing
log move r solves

    D(P·e^r) = sign(r) · ADV · (r / (Y·σ_daily))²

where D(p) is the agents' net demand at price p and the right-hand side is the market maker's
supply under the square-root impact law (|r| = Y·σ·sqrt(Q/ADV)). Every crossing order is
filled in full at the single clearing price, and the market maker absorbs the imbalance into
its inventory. A small noise term stands in for order flow the model does not represent.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from scipy.special import ndtr

from .config import MARKET_CLOSE_TICK, MARKET_OPEN_TICK, TICKS_PER_DAY, MarketConfig

OPEN_TICKS_PER_DAY = MARKET_CLOSE_TICK - MARKET_OPEN_TICK  # 26 fifteen-minute ticks


def is_market_open(tick: int) -> bool:
    return MARKET_OPEN_TICK <= tick % TICKS_PER_DAY < MARKET_CLOSE_TICK


# --------------------------------------------------------------------------- Black–Scholes


def bs_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black–Scholes price of a European call. T in years; r and sigma annualised.

    At expiry (T <= 0) or with zero volatility, returns the discounted intrinsic value.
    """
    if T <= 0.0:
        return max(S - K, 0.0)
    if sigma <= 0.0:
        return max(S - K * math.exp(-r * T), 0.0)
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / sq
    d2 = d1 - sq
    return float(S * ndtr(d1) - K * math.exp(-r * T) * ndtr(d2))


# --------------------------------------------------------------------------- auction


def demand_curve(
    buy_q: np.ndarray, buy_lim: np.ndarray, sell_q: np.ndarray, sell_lim: np.ndarray
) -> Callable[[np.ndarray | float], np.ndarray]:
    """Return D(p) = Σ buy_q[buy_lim ≥ p] − Σ sell_q[sell_lim ≤ p], vectorised over p.

    One sort per side; each evaluation is a `searchsorted` plus a lookup in a cumulative sum.
    D is non-increasing in p.
    """
    bo = np.argsort(buy_lim, kind="stable")
    b_lim = np.asarray(buy_lim, np.float64)[bo]
    b_cum = np.concatenate([[0.0], np.cumsum(np.asarray(buy_q, np.float64)[bo])])
    so = np.argsort(sell_lim, kind="stable")
    s_lim = np.asarray(sell_lim, np.float64)[so]
    s_cum = np.concatenate([[0.0], np.cumsum(np.asarray(sell_q, np.float64)[so])])

    def D(p: np.ndarray | float) -> np.ndarray:
        p = np.asarray(p, np.float64)
        buys = b_cum[-1] - b_cum[np.searchsorted(b_lim, p, side="left")]  # limits >= p
        sells = s_cum[np.searchsorted(s_lim, p, side="right")]  # limits <= p
        return buys - sells

    return D


def mm_supply(r: np.ndarray | float, adv: float, Y: float, sigma_daily: float) -> np.ndarray:
    """Shares the market maker sells (negative: buys) to let the price move by log return r."""
    r = np.asarray(r, np.float64)
    scale = max(Y * sigma_daily, 1e-12)
    return np.sign(r) * adv * (r / scale) ** 2


@dataclass
class AuctionResult:
    price: float  # clearing price
    log_return: float  # log(price / previous price), noise included
    buy_fill: np.ndarray  # bool mask over buy orders
    sell_fill: np.ndarray  # bool mask over sell orders
    bought: float  # shares bought by agents
    sold: float  # shares sold by agents
    volume: float  # shares that changed hands = max(bought, sold)
    mm_delta: float  # change in market-maker inventory = sold - bought
    capped: bool  # circuit breaker hit
    impact_return: float  # log move from the auction alone, before noise


def batch_auction(
    buy_q: np.ndarray,
    buy_lim: np.ndarray,
    sell_q: np.ndarray,
    sell_lim: np.ndarray,
    P: float,
    sigma_daily: float,
    adv: float,
    Y: float,
    cap: float,
    noise_sd: float = 0.0,
    rng: np.random.Generator | None = None,
    iters: int = 60,
) -> AuctionResult:
    """Clear one tick. Quantities are positive share counts; limits are prices.

    The excess demand f(r) = D(P·e^r) − mm_supply(r) is non-increasing in r, so the clearing
    move is found by bisection on [−cap, cap]; if f does not change sign the move sits at the
    cap. Noise (`noise_sd`, a log-return standard deviation) is then added and the result is
    clipped to ±cap again. Orders are filled against the final price, so no order is ever
    filled outside its limit.
    """
    buy_q, buy_lim = np.asarray(buy_q, np.float64), np.asarray(buy_lim, np.float64)
    sell_q, sell_lim = np.asarray(sell_q, np.float64), np.asarray(sell_lim, np.float64)
    if np.any(buy_q < 0) or np.any(sell_q < 0):
        raise ValueError("order quantities must be non-negative")
    if P <= 0 or cap <= 0:
        raise ValueError("price and cap must be positive")

    D = demand_curve(buy_q, buy_lim, sell_q, sell_lim)
    adv = max(adv, 1e-9)  # keeps mm_supply strictly increasing, so the crossing is unique

    def f(r: float) -> float:
        return float(D(P * math.exp(r)) - mm_supply(r, adv, Y, sigma_daily))

    lo, hi = -cap, cap
    if f(hi) > 0:
        r = hi
    elif f(lo) < 0:
        r = lo
    else:
        for _ in range(iters):
            mid = 0.5 * (lo + hi)
            if f(mid) > 0:
                lo = mid
            else:
                hi = mid
        r = 0.5 * (lo + hi)
    impact_r = r
    if noise_sd > 0:
        if rng is None:
            raise ValueError("noise_sd > 0 needs an rng")
        r += float(rng.normal(0.0, noise_sd))
    capped = abs(r) >= cap
    r = float(np.clip(r, -cap, cap))
    price = P * math.exp(r)

    buy_fill = (buy_lim >= price) & (buy_q > 0)
    sell_fill = (sell_lim <= price) & (sell_q > 0)
    bought = float(buy_q[buy_fill].sum())
    sold = float(sell_q[sell_fill].sum())
    return AuctionResult(
        price=price,
        log_return=r,
        buy_fill=buy_fill,
        sell_fill=sell_fill,
        bought=bought,
        sold=sold,
        volume=max(bought, sold),
        mm_delta=sold - bought,
        capped=capped,
        impact_return=impact_r,
    )


def average_daily_volume(total_shares_held: float, adv_turnover: float) -> float:
    """ADV = adv_turnover · total shares held (HANDOFF §4 M3)."""
    return adv_turnover * total_shares_held


# --------------------------------------------------------------------------- market state


@dataclass
class MarketState:
    """Price, hidden fundamental value, history, volatility and the option signal.

    Call `record_tick` once per tick (open or closed). Daily OHLC and the EWMA realised
    volatility are updated when a day's last open tick is recorded.
    """

    cfg: MarketConfig = field(default_factory=MarketConfig)
    implied_vol: float | np.ndarray | None = None  # constant, or a per-tick series; default cfg.implied_vol
    price: float = 0.0
    v_true: float = 0.0
    tick: int = -1
    mm_inventory: float = 0.0
    prices: list[float] = field(default_factory=list)
    volumes: list[float] = field(default_factory=list)
    v_true_hist: list[float] = field(default_factory=list)
    atm_call: list[float] = field(default_factory=list)
    ohlc: list[tuple[float, float, float, float]] = field(default_factory=list)  # one row per day
    daily_vol: float = 0.0  # EWMA realised daily volatility (log returns)
    _day: list[float] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.price <= 0:
            self.price = self.cfg.initial_price
        if self.v_true <= 0:
            self.v_true = self.price
        if self.implied_vol is None:
            self.implied_vol = self.cfg.implied_vol
        if self.daily_vol <= 0:
            self.daily_vol = self.iv_annual(0) / math.sqrt(self.cfg.trading_days_per_year)

    # ---------------------------------------------------------- volatility
    def iv_annual(self, tick: int | None = None) -> float:
        """Annualised implied vol at `tick` (default: current tick)."""
        iv = self.implied_vol
        if isinstance(iv, np.ndarray):
            t = max(self.tick if tick is None else tick, 0)
            return float(iv[min(t, len(iv) - 1)])
        return float(iv if iv is not None else self.cfg.implied_vol)

    def iv_daily(self, tick: int | None = None) -> float:
        return self.iv_annual(tick) / math.sqrt(self.cfg.trading_days_per_year)

    def tick_noise_sd(self) -> float:
        """Std of the unmodelled-flow log return on one open tick."""
        return self.cfg.noise_frac * self.daily_vol / math.sqrt(OPEN_TICKS_PER_DAY)

    # ---------------------------------------------------------- signals
    def momentum(self, lookback: int | np.ndarray) -> float | np.ndarray:
        """log(P_now / P_{now − lookback}), using the oldest price if history is shorter."""
        if not self.prices:
            return np.zeros_like(lookback, dtype=np.float64) if isinstance(lookback, np.ndarray) else 0.0
        hist = np.asarray(self.prices)
        idx = np.maximum(len(hist) - 1 - np.asarray(lookback), 0)
        out = np.log(hist[-1] / hist[idx])
        return out if isinstance(lookback, np.ndarray) else float(out)

    def return_since(self, ticks_ago: int) -> float:
        return float(self.momentum(ticks_ago))

    def atm_call_price(self) -> float:
        T = self.cfg.option_maturity_days / 365.0
        return bs_call(self.price, self.price, T, self.cfg.risk_free_rate, self.iv_annual())

    # ---------------------------------------------------------- updates
    def apply_fundamental_shock(self, true_impact: float) -> None:
        """A real event moves the hidden value: V_true *= exp(true_impact)."""
        self.v_true *= math.exp(true_impact)

    def record_tick(self, tick: int, auction: AuctionResult | None = None) -> None:
        """Log one tick. Pass the auction result on open ticks; closed ticks keep the price."""
        self.tick = tick
        volume = 0.0
        if auction is not None:
            self.price = auction.price
            self.mm_inventory += auction.mm_delta
            volume = auction.volume
        self.prices.append(self.price)
        self.volumes.append(volume)
        self.v_true_hist.append(self.v_true)
        self.atm_call.append(self.atm_call_price())

        if is_market_open(tick):
            self._day.append(self.price)
            if tick % TICKS_PER_DAY == MARKET_CLOSE_TICK - 1:
                self._close_day()

    def _close_day(self) -> None:
        day = self._day
        prev_close = self.ohlc[-1][3] if self.ohlc else self.cfg.initial_price
        self.ohlc.append((day[0], max(day), min(day), day[-1]))
        r = math.log(day[-1] / prev_close)
        lam = self.cfg.vol_ewma_lambda
        self.daily_vol = math.sqrt(lam * self.daily_vol**2 + (1 - lam) * r * r)
        self._day = []

    def adv(self, total_shares_held: float) -> float:
        return average_daily_volume(total_shares_held, self.cfg.adv_turnover)

    def clear(
        self,
        buy_q: np.ndarray,
        buy_lim: np.ndarray,
        sell_q: np.ndarray,
        sell_lim: np.ndarray,
        total_shares_held: float,
        rng: np.random.Generator,
    ) -> AuctionResult:
        """Run one auction at the current price with the configured impact law and noise.

        Does not record the tick; call `record_tick(tick, result)` afterwards.
        """
        return batch_auction(
            buy_q,
            buy_lim,
            sell_q,
            sell_lim,
            P=self.price,
            sigma_daily=self.daily_vol,
            adv=self.adv(total_shares_held),
            Y=self.cfg.impact_Y,
            cap=self.cfg.circuit_breaker,
            noise_sd=self.tick_noise_sd(),
            rng=rng,
        )
