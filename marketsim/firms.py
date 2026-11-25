"""Large rule-based traders: prop firms and funds (issue #9, HANDOFF §4 M3 `firms.py`).

* `PropFirms`: short-horizon momentum plus last tick's order imbalance,
  target value = capital · tanh(k · momentum + k2 · imbalance), with tight limits.
* `Funds`: know V_true with a 1-day lag (`fund_lag_ticks`), corrected at once for official
  real events they read directly (HANDOFF §4 M1, seeding "official"),
  target value = capital · clip(k · (V_known − P) / P, −1, 1).
* `DiscretionaryPolicy`: a hook that may set a fund's target once per official event. The
  default `RuleBasedPolicy` returns None (keep the rule above).

Firms can be short: they are institutions with borrowing, unlike v1 retail. Each firm type gets
half of `firm_capital_share` × total investor wealth, split evenly between its firms.
"""

from __future__ import annotations

import math
from typing import Protocol

import numpy as np

from .config import MarketConfig
from .events import Event
from .market import MarketState
from .trading import OrderBatch, filled_mask

PROP_LIMIT = 0.003  # limit offset from the last price
FUND_LIMIT = 0.01
REBALANCE = 0.01  # firms only trade if the order is worth more than 1% of capital


class DiscretionaryPolicy(Protocol):
    """Decides a fund's position once per official event.

    Return a target fraction of capital in [-1, 1] that replaces the fund's rule for the rest of
    the trading day, or None to keep the rule.

    LLM hook (not implemented in v1, no network calls at runtime): an implementation could put
    the event's fields and a market summary (price, V_known, IV, recent returns) into a prompt
    and parse a fraction from the reply, caching the answer by event id so runs stay
    reproducible.
    """

    def on_event(self, event: Event, market: MarketState) -> float | None: ...


class RuleBasedPolicy:
    def on_event(self, event: Event, market: MarketState) -> float | None:
        return None


class _Firms:
    limit_offset = PROP_LIMIT

    def __init__(self, n: int, total_capital: float) -> None:
        self.n = n
        self.capital = np.full(n, total_capital / n if n else 0.0)
        self.cash = self.capital.copy()
        self.shares = np.zeros(n)

    def target_fraction(self, market: MarketState) -> np.ndarray:
        raise NotImplementedError

    def orders(self, market: MarketState) -> OrderBatch:
        if self.n == 0:
            return OrderBatch.empty()
        P = market.price
        target = np.clip(self.target_fraction(market), -1.0, 1.0) * self.capital
        value = target - self.shares * P
        act = np.abs(value) > REBALANCE * self.capital
        ids = np.flatnonzero(act)
        side = np.sign(value[act])
        return OrderBatch(ids, value[act] / P, P * np.exp(side * self.limit_offset))

    def settle(self, batch: OrderBatch, price: float) -> None:
        f = filled_mask(batch, price)
        np.add.at(self.shares, batch.owner[f], batch.qty[f])
        np.add.at(self.cash, batch.owner[f], -batch.qty[f] * price)

    def equity(self, price: float) -> np.ndarray:
        return self.cash + self.shares * price


class PropFirms(_Firms):
    limit_offset = PROP_LIMIT

    def __init__(self, n: int, total_capital: float, momentum_ticks: int, k: float, k2: float) -> None:
        super().__init__(n, total_capital)
        self.momentum_ticks, self.k, self.k2 = momentum_ticks, k, k2
        self.imbalance = 0.0  # last tick's (buy − sell) / (buy + sell) of retail orders

    def observe(self, retail: OrderBatch) -> None:
        b, s = retail.buy_volume, retail.sell_volume
        self.imbalance = (b - s) / (b + s) if b + s > 0 else 0.0

    def target_fraction(self, market: MarketState) -> np.ndarray:
        mom = float(market.momentum(self.momentum_ticks))
        return np.full(self.n, math.tanh(self.k * mom + self.k2 * self.imbalance))


class Funds(_Firms):
    limit_offset = FUND_LIMIT

    def __init__(
        self,
        n: int,
        total_capital: float,
        k: float,
        lag_ticks: int,
        policy: DiscretionaryPolicy | None = None,
    ) -> None:
        super().__init__(n, total_capital)
        self.k, self.lag = k, lag_ticks
        self.policy: DiscretionaryPolicy = policy or RuleBasedPolicy()
        self._official: list[tuple[int, float]] = []  # (tick, public reading) of official releases
        self._override: dict[int, tuple[int, float]] = {}  # firm -> (until tick, fraction)

    def on_event(self, event: Event, market: MarketState, tick: int) -> None:
        if event.seeding != "official":
            return
        if event.true_impact != 0.0:  # they read the release, not the hidden value
            self._official.append((tick, event.true_impact if event.signal is None else event.signal))
        frac = self.policy.on_event(event, market)
        if frac is not None:
            until = tick + (96 - tick % 96)  # rest of the trading day
            for i in range(self.n):
                self._override[i] = (until, float(np.clip(frac, -1.0, 1.0)))

    def known_value(self, market: MarketState) -> float:
        """V_true as of `lag` ticks ago (the oldest record if the run is younger), plus the
        official real events read since then."""
        hist = market.v_true_hist
        if not hist:
            return market.v_true * math.exp(sum(imp for _, imp in self._official))
        back = min(self.lag, len(hist) - 1)
        seen_until = market.tick - back  # V_true recorded at this tick includes its events
        bump = sum(imp for t, imp in self._official if t > seen_until)
        return hist[-1 - back] * math.exp(bump)

    def target_fraction(self, market: MarketState) -> np.ndarray:
        P = market.price
        frac = np.full(self.n, self.k * (self.known_value(market) - P) / P)
        for i, (until, f) in list(self._override.items()):
            if market.tick < until:
                frac[i] = f
            else:
                del self._override[i]
        return frac


class Company:
    """The listed company as a trader: a share buyback programme.

    The company knows its own value (V_true) at once. On open ticks, when the price is more than
    `threshold` below V_true, it buys back shares, at most `daily_budget` of its programme per day
    and with limits at most 0.5% above the last price. Bought-back shares are retired (they leave
    the float). It never sells.
    """

    LIMIT = 0.005

    def __init__(self, programme: float, threshold: float, daily_budget: float) -> None:
        self.programme = programme  # total cash set aside for buybacks
        self.cash = programme
        self.shares = 0.0  # retired shares bought back so far
        self.threshold = threshold
        self.daily_budget = daily_budget
        self._day = -1
        self._spent_today = 0.0

    def orders(self, market: MarketState) -> OrderBatch:
        day = market.tick // 96 if market.tick >= 0 else 0
        if day != self._day:
            self._day, self._spent_today = day, 0.0
        P, V = market.price, market.v_true
        if self.cash <= 0 or V * (1.0 - self.threshold) <= P:
            return OrderBatch.empty()
        room = min(self.cash, self.daily_budget * self.programme - self._spent_today)
        if room <= 0:
            return OrderBatch.empty()
        # buy more the deeper the discount: a sixth of today's room per tick at the threshold
        depth = min(1.0, (1.0 - P / V) / max(self.threshold, 1e-9) / 6.0)
        limit = P * math.exp(self.LIMIT)
        return OrderBatch(np.zeros(1, np.int64), np.array([room * depth / limit]), np.array([limit]))

    def settle(self, batch: OrderBatch, price: float) -> None:
        f = filled_mask(batch, price)
        bought = float(batch.qty[f].sum())
        self.shares += bought
        self.cash -= bought * price
        self._spent_today += bought * price


def build_company(cfg: MarketConfig, total_investor_wealth: float) -> Company:
    return Company(
        cfg.company_buyback_programme * total_investor_wealth,
        cfg.company_buyback_threshold,
        cfg.company_buyback_daily,
    )


def build_firms(cfg: MarketConfig, total_investor_wealth: float) -> tuple[PropFirms, Funds]:
    """Each firm type gets half of `firm_capital_share` × total investor wealth."""
    cap = cfg.firm_capital_share * total_investor_wealth / 2.0
    props = PropFirms(
        cfg.n_prop_firms, cap, cfg.prop_momentum_ticks, cfg.prop_momentum_k, cfg.prop_imbalance_k
    )
    funds = Funds(cfg.n_funds, cap, cfg.fund_value_k, cfg.fund_lag_ticks)
    return props, funds
