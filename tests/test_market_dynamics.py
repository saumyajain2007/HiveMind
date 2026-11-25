"""Fitted tick dynamics: news is priced once, and order flow is not trend-following."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from marketsim.config import Config
from marketsim.events import Event, apply_to_market
from marketsim.market import MarketState


def _auction(m: MarketState, rng: np.random.Generator, buy: float = 0.0):
    q = np.array([buy]) if buy > 0 else np.zeros(0)
    lim = np.array([1e9]) if buy > 0 else np.zeros(0)
    return m.clear(q, lim, np.zeros(0), np.zeros(0), 1e6, rng)


def test_news_requote_is_not_amplified() -> None:
    cfg = replace(Config().market, noise_frac=0.0, mm_flow_anticipation=1.0, mm_news_pass_through=1.0)
    m = MarketState(cfg)
    rng = np.random.default_rng(0)
    m.rho_num, m.rho_den = 0.8, 1.0  # a market maker that expects strongly persistent flow
    m.apply_public_news(-0.05)
    res = _auction(m, rng)
    assert abs(res.log_return - (-0.05 * cfg.mm_news_pass_through)) < 1e-6


def test_hidden_value_does_not_set_the_price() -> None:
    """By default the market maker does not re-quote on news: V_true moves, the price does not."""
    m = MarketState(replace(Config().market, noise_frac=0.0))
    p0 = m.price
    apply_to_market(
        Event(
            tick=0,
            kind="earnings",
            ticker=0,
            true_impact=-0.10,
            sentiment=-0.5,
            credibility=0.9,
            salience=0.8,
            complexity=0.3,
            seeding="official",
            signal=-0.07,
        ),
        m,
    )
    assert m.v_true == pytest.approx(p0 * np.exp(-0.10))
    res = _auction(m, np.random.default_rng(0))
    assert abs(res.log_return) < 1e-9


def test_anticipation_off_leaves_auction_unchanged() -> None:
    rng = np.random.default_rng(1)
    on = MarketState(replace(Config().market, noise_frac=0.0, mm_flow_anticipation=0.0))
    r = _auction(on, rng, buy=500.0)
    assert r.log_return == r.impact_return


def test_noise_cannot_run_away() -> None:
    """Realised volatility does not feed the noise level: it is bounded by implied volatility."""
    cfg = Config().market
    m = MarketState(cfg)
    m.daily_vol = 10.0  # absurd realised volatility
    m.abs_ewma = 10.0  # and absurd recent moves
    ceiling = 4.0 * cfg.noise_frac * m.iv_daily() / (26**0.5) * max(cfg.noise_intraday_profile or (1.0,))
    assert m.tick_noise_sd() <= ceiling + 1e-12
