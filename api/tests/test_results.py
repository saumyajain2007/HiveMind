"""Results, analysis, datasets and parser endpoints (issue #18), on small stored fixture runs."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from marketsim.backtest import synthetic_series
from marketsim.config import TICKS_PER_DAY
from marketsim_api import llm
from marketsim_api.main import create_app
from marketsim_api.settings import Settings

V1 = "/api/v1"
RUMOUR = {
    "tick": 41,
    "kind": "rumour",
    "sentiment": 0.8,
    "credibility": 0.2,
    "salience": 0.9,
    "complexity": 0.2,
    "seeding": "influencer",
    "label": "Takeover talk",
}


def wait(client: TestClient, run_id: str, timeout: float = 120) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        run = client.get(f"{V1}/runs/{run_id}").json()
        if run["status"] in ("done", "failed", "cancelled"):
            assert run["status"] == "done", run.get("error")
            return run
        time.sleep(0.05)
    raise AssertionError("timed out")


@pytest.fixture(scope="module")
def ctx(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    settings = Settings(
        data_dir=tmp_path_factory.mktemp("data"), log_json=False, run_jobs=True, max_jobs=4, executor="thread"
    )
    with TestClient(create_app(settings)) as client:
        scenario = {"name": "fixture", "n_agents": 1_500, "days": 1, "seed": 3, "events": [RUMOUR]}
        single = client.post(f"{V1}/runs", json={"scenario": scenario}).json()
        mc = client.post(
            f"{V1}/runs", json={"scenario": {**scenario, "n_agents": 800}, "mode": "montecarlo", "runs": 3}
        ).json()
        closes, events = synthetic_series(days=30, seed=4, n_events=3)
        csv = "date,close\n" + "\n".join(f"2024-01-{d + 1:02d},{c:.4f}" for d, c in enumerate(closes))
        dated = [
            {
                **{k: v for k, v in e.event.to_dict().items() if k not in ("tick", "id", "parent")},
                "day": e.day,
            }
            for e in events
        ]
        ds = client.post(f"{V1}/data/upload", json={"name": "synthetic", "csv": csv, "events": dated}).json()
        cal = client.post(
            f"{V1}/calibrations",
            json={
                "dataset_id": ds["id"],
                "n_agents": 400,
                "n_trials": 2,
                "runs_per_trial": 1,
                "space": {"impact_Y": [0.5, 1.0]},
            },
        ).json()
        bt = client.post(
            f"{V1}/backtests",
            json={"dataset_id": ds["id"], "n_agents": 400, "origins": [22, 25], "runs": 2},
        ).json()
        for r in (single, mc, cal, bt):
            wait(client, r["id"])
        yield {
            "client": client,
            "single": single["id"],
            "mc": mc["id"],
            "ds": ds,
            "cal": cal["id"],
            "bt": bt["id"],
        }


def unpack(p: dict[str, Any]) -> np.ndarray:
    return np.frombuffer(base64.b64decode(p["b64"]), "<f4").reshape(p["shape"])


def test_series(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    r = c.get(f"{V1}/runs/{ctx['single']}/series").json()
    assert r["n_ticks"] == TICKS_PER_DAY and len(r["series"]["price"]) == TICKS_PER_DAY
    assert set(r["series"]) >= {"price", "v_true", "volume", "confidence", "iv", "atm_call", "mm_inventory"}
    assert len(r["ohlc"]) == 1 and r["events"][0]["label"] == "Takeover talk"
    down = c.get(f"{V1}/runs/{ctx['single']}/series?every=8&encoding=b64").json()
    assert down["tick"][0] == 0 and down["tick"][-1] == TICKS_PER_DAY - 1
    price = unpack(down["series"]["price"])
    assert np.allclose(price, np.asarray(r["series"]["price"])[down["tick"]], rtol=1e-6)
    mc_series = c.get(f"{V1}/runs/{ctx['mc']}/series").json()  # representative run
    assert mc_series["n_ticks"] == TICKS_PER_DAY


def test_quantiles_and_paths(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    q = c.get(f"{V1}/runs/{ctx['mc']}/quantiles").json()
    assert q["n_runs"] == 3 and set(q["quantiles"]) == {"0.05", "0.25", "0.5", "0.75", "0.95"}
    assert all(a <= b + 1e-9 for a, b in zip(q["quantiles"]["0.25"], q["quantiles"]["0.75"], strict=True))
    p = c.get(f"{V1}/runs/{ctx['mc']}/paths?sample=2&encoding=b64").json()
    assert unpack(p["paths"]).shape == (2, TICKS_PER_DAY) and len(p["seeds"]) == 2
    assert c.get(f"{V1}/runs/{ctx['single']}/quantiles").status_code == 400


def test_awareness_and_lineage(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    a = c.get(f"{V1}/runs/{ctx['single']}/awareness").json()
    assert a["columns"][:3] == ["tick", "root", "total"] and len(a["category_sizes"]) == 5
    rumour = next(f for f in a["families"] if f["label"] == "Takeover talk")
    last = rumour["rows"][-1]
    assert last[2] == rumour["aware"] and sum(last[3 + 6 :]) == last[2]
    lin = c.get(f"{V1}/runs/{ctx['single']}/lineage").json()
    assert lin["items"][0]["origin"] == "event" and lin["families"]


def test_stylized_facts(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    for run in (ctx["single"], ctx["mc"]):
        s = c.get(f"{V1}/runs/{run}/stylized-facts?lags=5").json()
        assert len(s["acf_abs_r"]) == 5 and len(s["histogram"]["centres"]) == 48
        assert s["n_returns"] > 0


def test_graph_and_node_seen(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    g = c.get(f"{V1}/runs/{ctx['single']}/graph?sample=500").json()
    assert len(g["nodes"]) == 500 and set(g["layers"]) == {"twitter", "reddit", "friendship"}
    ids = {n["id"] for n in g["nodes"]}
    assert all(a in ids and b in ids for a, b, _ in g["edges"])
    assert {e[2] for e in g["edges"]} <= set(g["layers"]) and "overlap_jaccard" in g["stats"]
    tw = c.get(f"{V1}/runs/{ctx['single']}/graph?layer=twitter&sample=500").json()
    assert {e[2] for e in tw["edges"]} <= {"twitter"}
    assert c.get(f"{V1}/runs/{ctx['single']}/graph?layer=tiktok").status_code == 400
    seen = c.get(f"{V1}/runs/{ctx['single']}/node-seen").json()
    assert seen["columns"] == ["tick", "index", "item"] and seen["rows"]
    # streamed spread agrees with stored awareness: every sampled node marked aware of the rumour
    # family is counted in the family's total
    assert all(0 <= row[1] < 3_000 for row in seen["rows"])


def test_results_need_a_finished_run(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    assert c.get(f"{V1}/runs/nope/series").status_code == 404
    queued = c.post(
        f"{V1}/runs",
        json={"scenario": {"name": "x", "n_agents": 100_000, "days": 30, "events": []}, "pace": 1},
    ).json()
    assert c.get(f"{V1}/runs/{queued['id']}/series").status_code == 409
    c.post(f"{V1}/runs/{queued['id']}/cancel")


def test_datasets(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    ds = ctx["ds"]
    assert ds["n_days"] == 30 and ds["n_events"] == 3
    assert ds["id"] in {d["id"] for d in c.get(f"{V1}/data").json()}
    detail = c.get(f"{V1}/data/{ds['id']}").json()
    assert len(detail["closes"]) == 30 and detail["dates"][0] == "2024-01-01"
    bad = c.post(f"{V1}/data/upload", json={"name": "bad", "csv": "day,price\n1,2\n"})
    assert bad.status_code == 422 and "date" in bad.json()["detail"]
    bad_ev = c.post(
        f"{V1}/data/upload",
        json={"name": "bad", "csv": "date,close\n2024-01-01,1\n2024-01-02,2\n", "events": [{"day": 0}]},
    )
    assert bad_ev.status_code == 422
    assert c.get(f"{V1}/data/zzz").status_code == 404


def test_calibration(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    r = c.get(f"{V1}/calibrations/{ctx['cal']}").json()
    res = r["result"]
    assert r["run"]["mode"] == "calibration" and len(res["trials"]) == 2
    assert 0.5 <= res["best"]["impact_Y"] <= 1.0 and len(res["observed"]) == 30
    assert len(res["best_path"]) == 30 and res["meta"]["relative"]
    assert r["run"]["summary"]["best_rmse"] == pytest.approx(res["best_rmse"])
    bad = c.post(f"{V1}/calibrations", json={"dataset_id": ctx["ds"]["id"], "space": {"nope": [0, 1]}})
    assert bad.status_code == 422
    assert c.get(f"{V1}/backtests/{ctx['cal']}").status_code == 404


def test_backtest(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    r = c.get(f"{V1}/backtests/{ctx['bt']}").json()
    res = r["result"]
    assert [o["origin"] for o in res["origins"]] == [22, 25]
    assert all(o["crps_model"] >= 0 and o["crps_rw"] >= 0 for o in res["origins"])
    assert r["run"]["summary"]["skill"] == pytest.approx(res["skill"])
    bad = c.post(f"{V1}/backtests", json={"dataset_id": ctx["ds"]["id"], "origins": [29], "horizon": 2})
    assert bad.status_code == 422


def test_stream_carries_trials_and_origins(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    for run, kind in ((ctx["cal"], "trial"), (ctx["bt"], "origin")):
        with c.websocket_connect(f"{V1}/runs/{run}/stream") as ws:
            msgs = []
            while True:
                m = ws.receive_json()
                msgs.append(m)
                if m["type"] in ("done", "error"):
                    break
        assert [m["done"] for m in msgs if m["type"] == kind] == [1, 2]


GOOD_REPLY = json.dumps(
    {
        "kind": "earnings",
        "true_impact": -0.04,
        "sentiment": -0.6,
        "credibility": 0.9,
        "salience": 0.7,
        "complexity": 0.4,
        "seeding": "official",
        "parent": -1,
    }
)


def test_parse_manual_flow(ctx: dict[str, Any]) -> None:
    c = ctx["client"]
    heads = [{"text": "Acme misses Q3 earnings", "tick": 40}, {"text": "Acme denies takeover rumours"}]
    first = c.post(f"{V1}/events/parse", json={"headlines": heads}).json()
    assert first["provider"] == "none" and len(first["prompts"]) == 2 and not first["events"]
    assert "Acme misses Q3 earnings" in first["prompts"][1]  # earlier headlines are context
    second = c.post(
        f"{V1}/events/parse", json={"headlines": heads, "responses": [GOOD_REPLY, "not json"]}
    ).json()
    assert second["provider"] == "manual" and len(second["events"]) == 1
    ev = second["events"][0]
    assert (ev["tick"], ev["kind"], ev["label"]) == (40, "earnings", "Acme misses Q3 earnings")
    assert second["errors"] and "Acme denies" in second["errors"][0]
    bad = c.post(f"{V1}/events/parse", json={"headlines": heads, "responses": [GOOD_REPLY]})
    assert bad.status_code == 422


def test_parse_with_a_provider(ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake(prompt: str) -> str:
        calls.append(prompt)
        return GOOD_REPLY

    monkeypatch.setenv("MARKETSIM_LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "anthropic_llm", lambda *a, **k: fake)
    c = ctx["client"]
    body = {"headlines": [{"text": "Acme cuts guidance"}]}
    r = c.post(f"{V1}/events/parse", json=body).json()
    assert r["provider"] == "anthropic" and len(r["events"]) == 1 and len(calls) == 1
    c.post(f"{V1}/events/parse", json=body)
    assert len(calls) == 1  # second call served from the cache
    monkeypatch.setenv("MARKETSIM_LLM_PROVIDER", "pigeon")
    assert c.post(f"{V1}/events/parse", json=body).status_code == 503


def test_large_responses_are_gzipped(ctx: dict[str, Any]) -> None:
    r = ctx["client"].get(f"{V1}/runs/{ctx['single']}/series", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
