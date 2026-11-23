"""Skeleton smoke tests (issue #1). Module tests arrive with each engine issue."""

import marketsim
from marketsim import config


def test_package_imports() -> None:
    assert marketsim.__version__


def test_config_defaults_construct() -> None:
    cfg = config.Config()
    assert cfg.n_agents == 10_000
    assert set(cfg.graph.platforms) <= set(config.ALL_PLATFORMS)
    assert config.MARKET_OPEN_TICK < config.MARKET_CLOSE_TICK <= config.TICKS_PER_DAY
    assert len(config.CATEGORIES) == 5


def test_strategy_priors_sum_to_one() -> None:
    for mix in config.TradingConfig().strategy_prior.values():
        assert abs(sum(mix) - 1.0) < 1e-9
