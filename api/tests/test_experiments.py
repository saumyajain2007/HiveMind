"""Real-data experiment endpoints: read-only views of `docs/experiments/<TICKER>/results.json`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from marketsim_api.main import create_app
from marketsim_api.settings import Settings

V1 = "/api/v1"
MODELS = ("random_walk", "event_random_walk", "abm", "abm_oracle")


def _fake_results() -> dict:
    per_model = {m: {"skill_vs_random_walk": 0.1 * i, "mean_crps_pct": 1.0} for i, m in enumerate(MODELS)}
    stats = {"n": 2, **per_model}
    return {
        "ticker": "FAKE",
        "name": "Fake Inc",
        "period": {"train": ["2016-01-04", "2023-12-29"], "test": ["2024-01-02", "2024-12-31"]},
        "events": {"total": 10, "labelled": 9, "train": 6, "test": 3},
        "backtest": {"1": {"summary": {"all": stats}, "origins": []}},
    }


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    (tmp_path / "FAKE").mkdir()
    (tmp_path / "FAKE" / "results.json").write_text(json.dumps(_fake_results()), "utf-8")
    (tmp_path / "FAKE" / "strategy.json").write_text(json.dumps({"ticker": "FAKE", "strategy": {}}), "utf-8")
    monkeypatch.setenv("MARKETSIM_EXPERIMENTS_DIR", str(tmp_path))
    settings = Settings(data_dir=tmp_path / "data", log_json=False, run_jobs=False)
    return TestClient(create_app(settings))


def test_list_and_get(client: TestClient) -> None:
    rows = client.get(f"{V1}/experiments").json()
    assert [r["ticker"] for r in rows] == ["FAKE"]
    assert rows[0]["horizons"] == [1]
    assert rows[0]["skill"]["abm"] == pytest.approx(0.2)
    full = client.get(f"{V1}/experiments/fake").json()
    assert full["name"] == "Fake Inc"


def test_unknown_or_bad_ticker_is_404(client: TestClient) -> None:
    assert client.get(f"{V1}/experiments/NOPE").status_code == 404
    assert client.get(f"{V1}/experiments/..%2Fsecret").status_code == 404


def test_strategy(client: TestClient) -> None:
    assert client.get(f"{V1}/experiments/FAKE/strategy").json()["ticker"] == "FAKE"
    assert client.get(f"{V1}/experiments/NOPE/strategy").status_code == 404
