"""Isolation runs: paired with/without counterfactuals for every event, as a job."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from marketsim_api.main import create_app
from marketsim_api.settings import Settings

V1 = "/api/v1"
EVENTS = [
    {
        "tick": 41,
        "kind": "rumour",
        "sentiment": 0.8,
        "credibility": 0.3,
        "salience": 0.9,
        "complexity": 0.2,
        "seeding": "influencer",
        "label": "Takeover talk",
    },
    {
        "tick": 45,
        "kind": "earnings",
        "true_impact": -0.04,
        "sentiment": -0.7,
        "credibility": 0.95,
        "salience": 0.9,
        "complexity": 0.4,
        "seeding": "official",
        "label": "Earnings miss",
    },
]


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=Path(tmp_path_factory.mktemp("iso")),
        log_json=False,
        run_jobs=True,
        max_jobs=2,
        executor="thread",
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_isolation_job(client: TestClient) -> None:
    scenario = {"name": "iso", "n_agents": 600, "days": 1, "seed": 2, "events": EVENTS}
    run = client.post(f"{V1}/runs", json={"scenario": scenario, "mode": "isolation", "runs": 3}).json()
    assert run["mode"] == "isolation"
    end = time.monotonic() + 120
    while time.monotonic() < end:
        body = client.get(f"{V1}/runs/{run['id']}/isolation").json()
        if body["run"]["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert body["run"]["status"] == "done", body["run"].get("error")
    res = body["result"]
    assert res["seeds"] == 3 and len(res["events"]) == 2
    miss = next(e for e in res["events"] if e["label"] == "Earnings miss")
    assert miss["final"]["mean"] < 0  # a public -4% earnings miss lowers the price
    assert miss["pass_through"] is not None
    # before an event fires, the paired runs are identical: its effect is exactly 0
    assert all(abs(x) < 1e-12 for x in miss["path"]["mean"][: 45 // res["every"]])
    assert res["interaction"] == pytest.approx(res["total"]["final"]["mean"] - res["isolated_sum"])


def test_isolation_needs_two_seeds(client: TestClient) -> None:
    scenario = {"name": "iso", "n_agents": 600, "days": 1, "seed": 2, "events": EVENTS}
    r = client.post(f"{V1}/runs", json={"scenario": scenario, "mode": "isolation", "runs": 1})
    assert r.status_code == 422
