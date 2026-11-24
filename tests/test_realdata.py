"""Real-data pipeline: loading, event timing, the impact model, and the experiment (synthetic files)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from marketsim.experiment import Experiment, ExperimentConfig
from marketsim.impact_model import ImpactModel
from marketsim.realdata import FEATURES, feature_matrix, load_dataset, utc_to_new_york


def test_utc_to_new_york_follows_daylight_saving() -> None:
    assert utc_to_new_york(datetime(2024, 1, 30, 21, 30)) == datetime(2024, 1, 30, 16, 30)  # EST
    assert utc_to_new_york(datetime(2024, 8, 1, 20, 30)) == datetime(2024, 8, 1, 16, 30)  # EDT
    assert utc_to_new_york(datetime(2024, 3, 10, 6, 59)).hour == 1  # just before the switch
    assert utc_to_new_york(datetime(2024, 3, 10, 7, 0)).hour == 3  # 2:00 EST -> 3:00 EDT


def _write_fake(root: Path, days: int = 500, seed: int = 0) -> list[str]:
    rng = np.random.default_rng(seed)
    d0 = date(2020, 1, 1)
    dates = [d for d in (d0 + timedelta(days=i) for i in range(int(days * 1.5))) if d.weekday() < 5][:days]
    m = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, days)))
    s = 50 * np.exp(np.cumsum(1.1 * np.diff(np.log(m), prepend=np.log(m[0])) + rng.normal(0, 0.01, days)))
    filings = []
    for k, i in enumerate(range(150, days - 5, 30)):
        move = 0.06 if k % 2 == 0 else -0.06
        s[i + 1 :] *= np.exp(move)  # an earnings reaction on the next close
        filings.append(
            {
                "form": "8-K",
                "items": ["2.02", "9.01"],
                "accepted": f"{dates[i].isoformat()}T21:30:00",
                "accession": f"a{k}",
            }
        )
        filings.append(
            {
                "form": "8-K",
                "items": ["5.07"],
                "accepted": f"{dates[i + 7].isoformat()}T14:00:00",
                "accession": f"v{k}",
            }
        )
    d = root / "FAKE"
    d.mkdir(parents=True)
    for name, px in (("prices.csv", s), ("market.csv", m)):
        (d / name).write_text(
            "date,close,volume\n" + "".join(f"{x},{p:.4f},1000\n" for x, p in zip(dates, px, strict=True)),
            "utf-8",
        )
    (d / "filings.json").write_text(json.dumps({"name": "Fake Inc", "filings": filings}), "utf-8")
    (d / "fundamentals.json").write_text(json.dumps({"eps_diluted": [], "revenue": []}), "utf-8")
    return [x.isoformat() for x in dates]


@pytest.fixture(scope="module")
def fake(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    root = tmp_path_factory.mktemp("data")
    return root, _write_fake(root)


def test_reaction_day_and_labels(fake: tuple[Path, list[str]]) -> None:
    root, dates = fake
    ds = load_dataset("FAKE", root)
    earn = [e for e in ds.events if e.group == "earnings"]
    votes = [e for e in ds.events if e.group == "vote"]
    assert earn and votes
    e = earn[0]
    # accepted 21:30 UTC = 16:30 New York, after the close: the next close reacts
    assert dates[e.reaction_idx - 1] == e.released[:10] and e.after_close
    assert e.label is not None and abs(e.label - 0.06) < 0.03  # the planted +6% jump
    v = votes[0]
    assert dates[v.reaction_idx] == v.released[:10] and not v.after_close  # 09:00 NY: same day
    X = feature_matrix(ds.events)
    assert X.shape == (len(ds.events), len(FEATURES)) and np.isfinite(X).all()
    assert (feature_matrix(earn, mask_announcement=True)[:, FEATURES.index("eps_yoy")] == 0).all()


def test_impact_model_learns_a_planted_signal() -> None:
    rng = np.random.default_rng(0)
    n = 600
    X = rng.normal(size=(n, 4))
    y = np.where(X[:, 0] > 0, 1, -1) * np.exp(-3.5 + 0.8 * X[:, 1] + 0.2 * rng.normal(size=n))
    m = ImpactModel(tau=0.005, l2=1.0).fit(X[:400], y[:400])
    r = m.evaluate(X[400:], y[400:], y[:400])
    assert r["direction_hit_rate"] > 0.85 and r["size_corr"] > 0.8
    assert r["log_loss"] < r["base_rate_log_loss"]
    draws = m.sample(X[400:410], np.random.default_rng(1), 500)
    assert draws.shape == (500, 10)
    assert np.sign(np.median(draws, axis=0)).tolist() == np.where(X[400:410, 0] > 0, 1.0, -1.0).tolist()


def test_forecasts_never_see_unscheduled_future_events(fake: tuple[Path, list[str]]) -> None:
    root, _ = fake
    exp = Experiment(
        ExperimentConfig(ticker="FAKE", split="2021-03-01", data_root=str(root), workers=1, runs=3)
    )
    vote = next(e for e in exp.ds.events if e.group == "vote" and e.reaction_idx > exp.split_idx)
    o = vote.reaction_idx - 1  # the vote happens the day after the forecast origin
    t = exp.task(o, 2, {}, oracle=False)
    o_tick = (o - t.start) * 96 + 63
    for rows in t.events:
        for tick, kind, *_ in rows:
            assert tick <= o_tick or kind == "earnings"  # only scheduled earnings may lie ahead
    oracle = exp.task(o, 2, {}, oracle=True)
    assert any(
        tick > o_tick and kind == "statement" for tick, kind, *_ in oracle.events[0]
    )  # the oracle sees it


def test_experiment_end_to_end(fake: tuple[Path, list[str]], tmp_path: Path) -> None:
    root, _ = fake
    cfg = ExperimentConfig(
        ticker="FAKE",
        split="2021-03-01",
        data_root=str(root),
        workers=1,
        runs=2,
        n_agents=300,
        horizons=(1,),
        train_origins=4,
        grid={"market.noise_frac": [0.6]},
        rw_samples=200,
        test_every=12,
    )
    res = Experiment(cfg).run()
    b = res["backtest"]["1"]
    assert b["summary"]["all"]["n"] == len(b["origins"]) > 10
    for m in ("random_walk", "event_random_walk", "abm", "abm_oracle"):
        assert b["summary"]["all"][m]["mean_crps_pct"] > 0
    from marketsim.experiment_report import write_report

    assert write_report(res, tmp_path).exists()
    assert (tmp_path / "skill_h1.png").exists()
