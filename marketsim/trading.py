"""Retail trading decisions (issue #9, HANDOFF §4 M3 `trading.py`).

Following the user's lines:

* Only investors trade, only when online, and only while the market is open.
* expected return E = w_f·fundamental + w_c·chartist + w_s·sentiment, with
  fundamental = clip((perceived_value − P) / P, ±0.5), chartist = log momentum over the
  category's `momentum_ticks`, sentiment = confidence · sentiment_scale.
* The weights start at the category's prior and shift toward whatever has been profitable:
  w = (1 − switching)·prior + switching·softmax(switching_intensity · fitness), where each
  strategy's fitness is an EMA of sign(mean signal at t−1) · return at t.
* target = risk_tolerance · equity · E / risk, risk = risk_aversion · iv_daily² · horizon_days,
  clipped to [0, equity] (no short selling for retail in v1).
* order = target − holding, only if |order value| > (0.05·(1 − impulsiveness) + 0.005)·equity.
* Panic: with an unrealised loss beyond `panic_loss`, with probability
  panic_rate · (loss_aversion − 1) · impulsiveness the target becomes 0.
* Limit = P · exp(±(0.002 + 0.02·impulsiveness + 0.5·|E|)), capped at ±10%.

`equity` is the agent's current cash plus shares at the current price.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import CATEGORIES, DAY_TRADER, LONG_TERM, SWING, Config
from .market import MarketState
from .population import Population

LIMIT_CAP = 0.10  # limit prices at most ±10% from the last price
STRATEGIES = ("fundamental", "chartist", "sentiment")


@dataclass
class OrderBatch:
    """Limit orders from one kind of trader. `qty` > 0 buys, < 0 sells (shares)."""

    owner: np.ndarray  # agent ids (retail) or firm indices
    qty: np.ndarray
    limit: np.ndarray

    @staticmethod
    def empty() -> OrderBatch:
        return OrderBatch(np.zeros(0, np.int64), np.zeros(0), np.zeros(0))

    def __len__(self) -> int:
        return len(self.qty)

    @property
    def buy_volume(self) -> float:
        return float(self.qty[self.qty > 0].sum())

    @property
    def sell_volume(self) -> float:
        return float(-self.qty[self.qty < 0].sum())


def filled_mask(batch: OrderBatch, price: float) -> np.ndarray:
    """Orders that cross the clearing price (the auction fills every crossing order in full)."""
    return ((batch.qty > 0) & (batch.limit >= price)) | ((batch.qty < 0) & (batch.limit <= price))


def softmax(x: np.ndarray) -> np.ndarray:
    z = np.exp(x - x.max())
    return z / z.sum()


class Trading:
    def __init__(self, pop: Population, cfg: Config, rng: np.random.Generator) -> None:
        self.pop, self.cfg, self.rng = pop, cfg, rng
        tc = cfg.trading
        k = len(CATEGORIES)
        self.prior = np.full((k, 3), 1.0 / 3.0)
        self.horizon = np.ones(k)
        self.momentum_ticks = np.ones(k, np.int64)
        for cat in (LONG_TERM, SWING, DAY_TRADER):
            self.prior[cat] = tc.strategy_prior[cat]
            self.horizon[cat] = tc.horizon_days[cat]
            self.momentum_ticks[cat] = tc.momentum_ticks[cat]
        self.fitness = np.zeros(3)
        self._last_signal: np.ndarray | None = None  # mean signal per strategy, previous tick

    # ---------------------------------------------------------------- strategy mix
    def weights(self) -> np.ndarray:
        """(len(CATEGORIES), 3) strategy weights from the priors and current fitness."""
        tc = self.cfg.trading
        return (1.0 - tc.switching) * self.prior + tc.switching * softmax(
            tc.switching_intensity * self.fitness
        )

    def update_fitness(self, log_return: float) -> None:
        """EMA of sign(mean signal at t−1) · return at t, then refresh agents' weights."""
        if self._last_signal is not None:
            d = self.cfg.trading.fitness_decay
            self.fitness = d * self.fitness + (1.0 - d) * np.sign(self._last_signal) * log_return
        inv = self.pop.investor_ids
        self.pop.strategy_weights[inv] = self.weights()[self.pop.category[inv]]

    # ---------------------------------------------------------------- signals
    def signals(self, ids: np.ndarray, market: MarketState) -> np.ndarray:
        """(len(ids), 3): fundamental, chartist, sentiment."""
        pop, P = self.pop, market.price
        out = np.empty((len(ids), 3))
        out[:, 0] = np.clip((pop.perceived_value[ids] - P) / P, -0.5, 0.5)
        lookback = self.momentum_ticks[pop.category[ids]]
        out[:, 1] = market.momentum(lookback)
        out[:, 2] = pop.confidence[ids] * self.cfg.trading.sentiment_scale
        return out

    def expected_return(self, ids: np.ndarray, market: MarketState) -> np.ndarray:
        sig = self.signals(ids, market)
        return (self.pop.strategy_weights[ids] * sig).sum(axis=1)

    def remember_signals(self, market: MarketState) -> None:
        """Store the mean signal of all investors (for next tick's fitness update)."""
        inv = self.pop.investor_ids
        self._last_signal = self.signals(inv, market).mean(axis=0) if len(inv) else np.zeros(3)

    # ---------------------------------------------------------------- sizing
    def equity(self, ids: np.ndarray, price: float) -> np.ndarray:
        return np.maximum(self.pop.cash[ids] + self.pop.shares[ids] * price, 0.0)

    def target_value(self, ids: np.ndarray, E: np.ndarray, market: MarketState) -> np.ndarray:
        pop, tc = self.pop, self.cfg.trading
        eq = self.equity(ids, market.price)
        risk = tc.risk_aversion * market.iv_daily() ** 2 * self.horizon[pop.category[ids]]
        target = pop.risk_tolerance[ids] * eq * E / np.maximum(risk, 1e-12)
        return np.clip(target, 0.0, eq)

    def threshold(self, ids: np.ndarray, price: float) -> np.ndarray:
        return (0.05 * (1.0 - self.pop.impulsiveness[ids]) + 0.005) * self.equity(ids, price)

    def panics(self, ids: np.ndarray, price: float) -> np.ndarray:
        pop, tc = self.pop, self.cfg.trading
        entry = pop.entry_price[ids]
        holding = (pop.shares[ids] > 0) & (entry > 0)
        loss = np.where(holding, 1.0 - price / np.where(entry > 0, entry, 1.0), 0.0)
        p = tc.panic_rate * (pop.loss_aversion[ids] - 1.0) * pop.impulsiveness[ids]
        return (loss > tc.panic_loss) & (self.rng.random(len(ids)) < p)

    def equilibrate(self, market: MarketState) -> None:
        """Start every investor at the position the trading rule wants at the opening price
        (entry price = that price), so the first auction does not replay the whole set-up."""
        pop, P = self.pop, market.price
        ids = pop.investor_ids
        if len(ids) == 0:
            return
        eq = self.equity(ids, P)
        target = self.target_value(ids, self.expected_return(ids, market), market)
        pop.shares[ids] = target / P
        pop.cash[ids] = eq - target
        pop.entry_price[ids] = np.where(target > 0, P, 0.0)

    # ---------------------------------------------------------------- orders
    def orders(self, market: MarketState, online: np.ndarray) -> OrderBatch:
        """Limit orders of online investors at the current price."""
        pop, P = self.pop, market.price
        ids = pop.investor_ids
        ids = ids[online[ids]]
        if len(ids) == 0:
            return OrderBatch.empty()
        E = self.expected_return(ids, market)
        target = self.target_value(ids, E, market)
        panic = self.panics(ids, P)
        target[panic] = 0.0
        order_value = target - pop.shares[ids] * P
        act = np.abs(order_value) > self.threshold(ids, P)
        act |= panic & (pop.shares[ids] > 0)  # a panicking holder sells regardless of size
        ids, E, order_value = ids[act], E[act], order_value[act]
        if len(ids) == 0:
            return OrderBatch.empty()
        side = np.sign(order_value)
        offset = np.minimum(0.002 + 0.02 * pop.impulsiveness[ids] + 0.5 * np.abs(E), LIMIT_CAP)
        limit = P * np.exp(side * offset)
        qty = order_value / P
        # no leverage, no shorting: buys limited by cash at the limit price, sells by holdings
        qty = np.where(side > 0, np.minimum(qty, pop.cash[ids] / limit), np.maximum(qty, -pop.shares[ids]))
        keep = qty != 0
        return OrderBatch(ids[keep], qty[keep], limit[keep])

    def settle(self, batch: OrderBatch, price: float) -> None:
        """Apply fills at the clearing price: cash, shares and average entry price."""
        pop = self.pop
        filled = filled_mask(batch, price)
        ids, q = batch.owner[filled], batch.qty[filled]
        if len(ids) == 0:
            return
        old = pop.shares[ids]
        new = np.maximum(old + q, 0.0)
        buys = q > 0
        avg_cost = (old * pop.entry_price[ids] + q * price) / np.maximum(new, 1e-12)
        cost = np.where(buys, avg_cost, pop.entry_price[ids])
        pop.entry_price[ids] = np.where(new > 1e-9, cost, 0.0)
        pop.shares[ids] = np.where(new > 1e-9, new, 0.0)
        pop.cash[ids] -= q * price
