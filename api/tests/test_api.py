"""API foundation tests (issue #16): schemas, config round trip, scenarios, runs, storage."""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from marketsim.config import Config, TradingConfig
from marketsim_api.config_schema import (
    FIELD_RANGES,
    SECTIONS,
    default_parameters,
    engine_to_parameters,
    parameters_to_engine,
)
from marketsim_api.export_openapi import render_all
from marketsim_api.log import JsonFormatter
from marketsim_api.main import create_app
from marketsim_api.schemas import RunStatus
from marketsim_api.settings import Settings

V1 = "/api/v1"

RUMOUR = {
    "tick": 50,
    "kind": "rumour",
    "sentiment": 0.8,
    "credibility": 0.2,
    "salience": 0.7,
    "complexity": 0.2,
    "seeding": "anonymous",
    "label": "Takeover talk on a forum",
}
DENIAL = {
    "tick": 250,
    "kind": "statement",
    "sentiment": -0.3,
    "credibility": 0.9,
    "salience": 0.5,
    "complexity": 0.2,
    "seeding": "official",
    "parent": 0,
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        Settings(data_dir=tmp_path / "data", cors_origins=["http://localhost:5173"], log_json=False)
    )
    with TestClient(app) as c:
        yield c


def scenario(**kw: Any) -> dict[str, Any]:
    return {"name": "Demo", "n_agents": 1000, "days": 5, "seed": 3, "events": [RUMOUR, DENIAL], **kw}


# --------------------------------------------------------------------------- meta


def test_health(client: TestClient) -> None:
    for path in ("/api/health", f"{V1}/health"):
        r = client.get(path)
        assert r.status_code == 200 and r.json()["status"] == "ok"
        assert r.headers["x-request-id"]


def test_cors(client: TestClient) -> None:
    r = client.options(
        f"{V1}/runs", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    )
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_openapi_file_is_current() -> None:
    for path, text in render_all().items():
        stale = f"stale {path.name}; run: uv run python -m marketsim_api.export_openapi"
        assert path.read_text(encoding="utf-8") == text, stale


def test_json_log_formatter() -> None:
    rec = logging.makeLogRecord({"msg": "request", "levelname": "INFO", "name": "x", "status": 200})
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "request" and out["status"] == 200 and out["level"] == "info"


# --------------------------------------------------------------------------- config schema


def test_defaults_round_trip_through_engine_config() -> None:
    params = default_parameters()
    assert parameters_to_engine(params, 10_000, 0) == Config()
    assert engine_to_parameters(Config()).model_dump() == params.model_dump()


def test_custom_parameters_reach_engine() -> None:
    data = default_parameters().model_dump()
    data["market"]["impact_Y"] = 1.1
    data["graph"]["platforms"] = ["twitter", "tiktok"]
    data["trading"]["strategy_prior"]["swing"] = [0.2, 0.5, 0.3]
    data["population"]["correlations"] = [{"a": "age", "b": "knowledge", "rho": -0.5}]
    cfg = parameters_to_engine(type(default_parameters()).model_validate(data), 2_000, 9)
    assert cfg.market.impact_Y == 1.1 and cfg.graph.platforms == ("twitter", "tiktok")
    assert cfg.trading.strategy_prior[2] == (0.2, 0.5, 0.3)
    assert cfg.population.correlations == {("age", "knowledge"): -0.5}
    assert (cfg.n_agents, cfg.seed) == (2_000, 9)


def test_schema_covers_every_config_field(client: TestClient) -> None:
    body = client.get(f"{V1}/config/schema").json()
    by_section = {s["name"]: {f["name"]: f for f in s["fields"]} for s in body["sections"]}
    for section, cls in SECTIONS.items():
        names = [f.name for f in dataclasses.fields(cls)]
        assert list(by_section[section]) == names, section
        for name in names:
            meta = by_section[section][name]
            assert meta["description"], f"{section}.{name} has no description"
            if meta["kind"] in ("int", "float", "map", "list"):
                assert f"{section}.{name}" in FIELD_RANGES, f"{section}.{name} has no range"
    assert by_section["population"]["investor_share"]["placeholder"] is True
    assert by_section["graph"]["twitter_mean_out"]["placeholder"] is False
    assert by_section["market"]["impact_Y"]["default"] == 0.7
    assert body["clock"]["ticks_per_day"] == 96 and "statement" in body["enums"]["kinds"]


def test_defaults_endpoint(client: TestClient) -> None:
    body = client.get(f"{V1}/config/defaults").json()
    assert body["parameters"]["trading"]["strategy_prior"]["long_term"] == [0.7, 0.1, 0.2]
    assert body["scenario"]["n_agents"] == 10_000 and body["scenario"]["events"] == []


@pytest.mark.parametrize(
    "patch",
    [
        ("market", "impact_Y", -1.0),
        ("diffusion", "attention_slots", 0),
        ("graph", "platforms", ["twitter", "myspace"]),
        ("graph", "platforms", []),
        ("graph", "youtube_lag_ticks", [50, 10]),
        ("graph", "reach", {"twitter": 0.1}),
        (
            "trading",
            "strategy_prior",
            {"long_term": [0.5, 0.5, 0.5], "swing": [0.3, 0.4, 0.3], "day_trader": [0.1, 0.5, 0.4]},
        ),
        ("population", "correlations", [{"a": "age", "b": "shoe_size", "rho": 0.1}]),
        ("population", "correlations", [{"a": "age", "b": "age", "rho": 0.1}]),
        ("market", "not_a_field", 1),
    ],
)
def test_invalid_parameters_rejected(client: TestClient, patch: tuple[str, str, Any]) -> None:
    params = default_parameters().model_dump()
    section, name, value = patch
    params[section][name] = value
    r = client.post(f"{V1}/runs", json={"scenario": scenario(), "parameters": params})
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- scenarios


def test_scenario_crud(client: TestClient) -> None:
    r = client.post(f"{V1}/scenarios", json=scenario())
    assert r.status_code == 201
    rec = r.json()
    sid = rec["id"]
    events = rec["spec"]["events"]
    assert [e["id"] for e in events] == [0, 1]  # auto-assigned
    assert events[1]["parent"] == 0

    assert client.get(f"{V1}/scenarios/{sid}").json()["spec"]["name"] == "Demo"
    assert len(client.get(f"{V1}/scenarios").json()) == 1

    r = client.put(f"{V1}/scenarios/{sid}", json=scenario(name="Renamed", days=6))
    assert r.status_code == 200 and r.json()["spec"]["days"] == 6

    assert client.delete(f"{V1}/scenarios/{sid}").status_code == 204
    assert client.get(f"{V1}/scenarios/{sid}").status_code == 404
    assert client.delete(f"{V1}/scenarios/{sid}").status_code == 404
    assert client.put(f"{V1}/scenarios/{sid}", json=scenario()).status_code == 404


@pytest.mark.parametrize(
    "events",
    [
        [{**RUMOUR, "tick": 5 * 96}],  # past the end
        [RUMOUR, {**DENIAL, "parent": 7}],  # unknown parent
        [{**RUMOUR, "id": 1, "tick": 300}, {**DENIAL, "id": 2, "parent": 1, "tick": 100}],  # parent later
        [{**RUMOUR, "id": 4}, {**DENIAL, "id": 4, "parent": -1}],  # duplicate ids
        [{**RUMOUR, "kind": "price_move"}],  # internal kind
        [{**RUMOUR, "seeding": "pigeon"}],
        [{**RUMOUR, "sentiment": 1.5}],
        [{**RUMOUR, "unexpected": True}],
    ],
)
def test_invalid_scenarios_rejected(client: TestClient, events: list[dict[str, Any]]) -> None:
    assert client.post(f"{V1}/scenarios", json=scenario(events=events)).status_code == 422


def test_events_are_sorted_by_tick(client: TestClient) -> None:
    spec = scenario(events=[{**DENIAL, "id": 9, "parent": -1}, {**RUMOUR, "id": 2}])
    events = client.post(f"{V1}/scenarios", json=spec).json()["spec"]["events"]
    assert [e["tick"] for e in events] == [50, 250]


# --------------------------------------------------------------------------- runs


def test_create_run_inline(client: TestClient, tmp_path: Path) -> None:
    r = client.post(f"{V1}/runs", json={"scenario": scenario(), "name": "first"})
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "queued" and run["name"] == "first"
    assert (run["mode"], run["runs"], run["n_agents"], run["days"], run["seed"]) == ("single", 1, 1000, 5, 3)
    assert run["spec"]["parameters"]["market"]["impact_Y"] == 0.7
    spec_file = tmp_path / "data" / "runs" / run["id"] / "spec.json"
    assert json.loads(spec_file.read_text(encoding="utf-8"))["scenario"]["events"][0]["kind"] == "rumour"


def test_spec_hash_is_deterministic(client: TestClient) -> None:
    def h(**kw: Any) -> str:
        body = {"scenario": scenario(), **kw}
        return str(client.post(f"{V1}/runs", json=body).json()["spec_hash"])

    base = h()
    assert h() == base
    assert h(name="other name", workers=4) == base  # labels and workers do not change results
    assert h(seed=4) != base
    assert h(mode="montecarlo", runs=20) != base
    labelled = scenario(events=[{**RUMOUR, "label": "x"}, DENIAL], name="Other", description="d")
    assert str(client.post(f"{V1}/runs", json={"scenario": labelled}).json()["spec_hash"]) == base


def test_run_from_saved_scenario_is_a_snapshot(client: TestClient) -> None:
    sid = client.post(f"{V1}/scenarios", json=scenario()).json()["id"]
    run = client.post(f"{V1}/runs", json={"scenario_id": sid, "mode": "montecarlo", "runs": 20}).json()
    assert run["scenario_id"] == sid and run["runs"] == 20
    client.put(f"{V1}/scenarios/{sid}", json=scenario(days=9))
    assert client.get(f"{V1}/runs/{run['id']}").json()["spec"]["scenario"]["days"] == 5


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"scenario_id": "abc", "scenario": scenario()},
        {"scenario": scenario(), "mode": "single", "runs": 5},
        {"scenario": scenario(), "runs": 0},
    ],
)
def test_invalid_run_requests(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post(f"{V1}/runs", json=body).status_code == 422


def test_unknown_scenario_and_run(client: TestClient) -> None:
    assert client.post(f"{V1}/runs", json={"scenario_id": "nope"}).status_code == 404
    assert client.get(f"{V1}/runs/nope").status_code == 404
    assert client.delete(f"{V1}/runs/nope").status_code == 404


def test_list_runs_paging_and_filter(client: TestClient) -> None:
    ids = [client.post(f"{V1}/runs", json={"scenario": scenario(seed=i)}).json()["id"] for i in range(5)]
    store = client.app.state.store  # type: ignore[attr-defined]
    store.set_status(ids[0], RunStatus.done, summary={"final_price": 101.2})
    page = client.get(f"{V1}/runs", params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    done = client.get(f"{V1}/runs", params={"status": "done"}).json()
    assert done["total"] == 1 and done["items"][0]["summary"] == {"final_price": 101.2}
    assert client.get(f"{V1}/runs", params={"status": "exploded"}).status_code == 422


def test_delete_run(client: TestClient, tmp_path: Path) -> None:
    run_id = client.post(f"{V1}/runs", json={"scenario": scenario()}).json()["id"]
    assert client.delete(f"{V1}/runs/{run_id}").status_code == 409  # still queued
    client.app.state.store.set_status(run_id, RunStatus.failed, error="boom")  # type: ignore[attr-defined]
    assert client.get(f"{V1}/runs/{run_id}").json()["error"] == "boom"
    assert client.delete(f"{V1}/runs/{run_id}").status_code == 204
    assert not (tmp_path / "data" / "runs" / run_id).exists()
    assert client.get(f"{V1}/runs/{run_id}").status_code == 404


def test_parameters_in_run_override_defaults(client: TestClient) -> None:
    params = default_parameters().model_dump()
    params["trading"]["risk_aversion"] = 5.0
    run = client.post(f"{V1}/runs", json={"scenario": scenario(), "parameters": params}).json()
    assert run["spec"]["parameters"]["trading"]["risk_aversion"] == 5.0
    assert TradingConfig().risk_aversion == 2.0  # the engine default is untouched


def test_nested_population_fields_round_trip_and_build() -> None:
    """Population settings from #2 (nested tuples / dicts) survive JSON and build a population."""
    from marketsim.config import LONG_TERM
    from marketsim.population import Population

    data = default_parameters().model_dump()
    data["population"]["marginals"]["age"] = ["beta", 2.5, 3.0, 18.0, 67.0]
    data["population"]["category_logits"]["long_term"] = [0.2, {"age": 1.0}]
    data["population"]["peak_hour_mix"] = [[0.8, 21.0, 2.0], [0.2, 12.0, 2.0]]
    data["population"]["intensity_beta"] = [1.5, 3.0]
    cfg = parameters_to_engine(type(default_parameters()).model_validate(data), 2_000, 4)
    pc = cfg.population
    assert pc.marginals["age"] == ("beta", 2.5, 3.0, 18.0, 67.0)
    assert pc.category_logits[LONG_TERM] == (0.2, {"age": 1.0})
    assert pc.peak_hour_mix == ((0.8, 21.0, 2.0), (0.2, 12.0, 2.0))
    assert pc.intensity_beta == (1.5, 3.0)
    pop = Population.build(cfg)
    assert pop.n >= 2_000


@pytest.mark.parametrize(
    "patch",
    [
        ("marginals", {"age": ["beta", 2.0, 3.0, 18.0, 67.0]}),  # missing traits
        ("platform_params", {"twitter": {"target": 0.2}}),  # missing platforms
        ("intensity_beta", [0.0, 3.0]),  # below range
        ("intensity_beta", [2.0, 3.0, 4.0]),  # wrong length
    ],
)
def test_invalid_population_fields_rejected(patch: tuple[str, Any]) -> None:
    from pydantic import ValidationError

    data = default_parameters().model_dump()
    data["population"][patch[0]] = patch[1]
    with pytest.raises(ValidationError):
        type(default_parameters()).model_validate(data)
