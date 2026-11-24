"""Job execution and live streaming (issue #17)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from marketsim.config import TICKS_PER_DAY
from marketsim_api import worker
from marketsim_api.jobs import coalesce
from marketsim_api.main import create_app
from marketsim_api.schemas import RunSpec
from marketsim_api.settings import Settings
from marketsim_api.storage import Store

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

ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(tmp_path: Path) -> Iterator[ClientFactory]:
    opened: list[Any] = []

    def make(executor: str = "thread", **kw: Any) -> TestClient:
        settings = Settings(
            data_dir=tmp_path / "data", log_json=False, run_jobs=True, max_jobs=2, executor=executor, **kw
        )
        ctx = TestClient(create_app(settings))
        opened.append(ctx)
        return ctx.__enter__()

    yield make
    for c in opened:
        c.__exit__(None, None, None)


def body(days: int = 1, n_agents: int = 2_000, **kw: Any) -> dict[str, Any]:
    scenario = {"name": "t", "n_agents": n_agents, "days": days, "seed": 3, "events": [RUMOUR]}
    return {"scenario": scenario, **kw}


def stream(client: TestClient, run_id: str, after: int | None = None) -> list[dict[str, Any]]:
    url = f"{V1}/runs/{run_id}/stream" + (f"?after={after}" if after is not None else "")
    out = []
    with client.websocket_connect(url) as ws:
        while True:
            m = ws.receive_json()
            out.append(m)
            if m["type"] in ("done", "error"):
                return out


def wait_status(client: TestClient, run_id: str, statuses: set[str], timeout: float = 60) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        run = client.get(f"{V1}/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} never reached {statuses}")


# --------------------------------------------------------------------------- the acceptance test


def test_live_run_in_a_process_streams_every_hour_and_finishes(make_client: ClientFactory) -> None:
    client = make_client("process")
    run = client.post(f"{V1}/runs", json=body()).json()
    msgs = stream(client, run["id"])
    hello, *rest, done = msgs
    assert hello["type"] == "hello" and hello["run_id"] == run["id"] and hello["n_agents"] == 2_000
    assert hello["ticks_per_day"] == TICKS_PER_DAY and len(hello["node_sample"]) > 0
    assert done["type"] == "done" and done["status"] == "done" and "families" in done["summary"]
    ticks = [m for m in rest if m["type"] == "tick"]
    assert {m["tick"] // 4 for m in ticks} == set(range(24))  # at least one frame per simulated hour
    assert [m["tick"] for m in ticks] == sorted(m["tick"] for m in ticks)
    assert ticks[-1]["tick"] == TICKS_PER_DAY - 1
    ev = next(m for m in rest if m["type"] == "event")
    assert (ev["tick"], ev["kind"], ev["label"]) == (41, "rumour", "Takeover talk")
    assert {"price", "v_true", "volume", "confidence", "iv", "atm_call", "awareness"} <= set(ticks[-1])
    final = wait_status(client, run["id"], {"done"})
    assert final["summary"]["n_ticks"] == TICKS_PER_DAY


def test_cancel_stops_within_a_second(make_client: ClientFactory) -> None:
    client = make_client("process")
    run = client.post(f"{V1}/runs", json=body(days=30, pace=200)).json()
    wait_status(client, run["id"], {"running"})
    time.sleep(0.3)
    t0 = time.monotonic()
    r = client.post(f"{V1}/runs/{run['id']}/cancel")
    assert r.status_code == 202
    final = wait_status(client, run["id"], {"cancelled", "done", "failed"}, timeout=5)
    assert final["status"] == "cancelled"
    assert time.monotonic() - t0 < 1.0
    assert final["summary"]["cancelled"] and final["summary"]["n_ticks"] < 30 * TICKS_PER_DAY
    assert client.post(f"{V1}/runs/{run['id']}/cancel").status_code == 409


# --------------------------------------------------------------------------- behaviour (threads: fast)


def test_worker_never_waits_for_clients_and_reconnect_gets_the_tail(make_client: ClientFactory) -> None:
    client = make_client()
    run = client.post(f"{V1}/runs", json=body()).json()
    wait_status(client, run["id"], {"done"})  # nobody was listening
    msgs = stream(client, run["id"], after=50)
    ticks = [m["tick"] for m in msgs if m["type"] == "tick"]
    assert ticks and min(ticks) > 50 and msgs[-1]["type"] == "done"
    assert not [m for m in msgs if m["type"] == "event"]  # the rumour (tick 41) was before `after`


def test_finished_run_replays_from_disk(make_client: ClientFactory) -> None:
    client = make_client()
    run = client.post(f"{V1}/runs", json=body()).json()
    wait_status(client, run["id"], {"done"})
    client.app.state.jobs.channels.clear()  # type: ignore[attr-defined]  # as after an API restart
    msgs = stream(client, run["id"])
    assert msgs[0]["type"] == "hello" and msgs[0]["replay"]
    ticks = [m for m in msgs if m["type"] == "tick"]
    assert [m["tick"] for m in ticks] == list(range(TICKS_PER_DAY))  # every tick, for scrubbing
    assert any(m["type"] == "event" and m["label"] == "Takeover talk" for m in msgs)


def test_montecarlo_job_streams_progress(make_client: ClientFactory) -> None:
    client = make_client()
    run = client.post(f"{V1}/runs", json=body(n_agents=800, mode="montecarlo", runs=3)).json()
    msgs = stream(client, run["id"])
    progress = [m for m in msgs if m["type"] == "progress"]
    assert progress and progress[-1]["done"] == 3 and progress[-1]["total"] == 3
    assert len(progress[-1]["quantiles"]["0.5"]) == TICKS_PER_DAY
    assert msgs[-1]["type"] == "done" and msgs[-1]["summary"]["n_runs"] == 3
    store: Store = client.app.state.store  # type: ignore[attr-defined]
    assert (store.run_dir(run["id"]) / "mc" / "paths.npy").exists()


def test_failure_is_reported(make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(worker, "parameters_to_engine", boom)
    client = make_client()
    run = client.post(f"{V1}/runs", json=body()).json()
    msgs = stream(client, run["id"])
    assert msgs[-1] == {"type": "error", "message": "RuntimeError: engine exploded"}
    assert wait_status(client, run["id"], {"failed"})["error"] == "RuntimeError: engine exploded"


def test_runs_left_running_are_marked_failed_on_startup(tmp_path: Path) -> None:
    store = Store(tmp_path / "data")
    spec = RunSpec.model_validate(
        {
            "engine_version": "x",
            "mode": "single",
            "runs": 1,
            "workers": 1,
            "seed": 0,
            "scenario": body()["scenario"],
            "parameters": TestClient(create_app(Settings(data_dir=tmp_path / "d2", run_jobs=False)))
            .get(f"{V1}/config/defaults")
            .json()["parameters"],
        }
    )
    run = store.create_run(spec, "left over")
    app = create_app(Settings(data_dir=tmp_path / "data", log_json=False, run_jobs=False))
    with TestClient(app) as c:
        r = c.get(f"{V1}/runs/{run.id}").json()
    assert r["status"] == "failed" and "interrupted" in r["error"]


def test_unknown_run_stream_says_so(make_client: ClientFactory) -> None:
    client = make_client()
    assert stream(client, "nope") == [{"type": "error", "message": "run nope not found"}]


def test_coalesce_keeps_hourly_frames_and_all_news() -> None:
    msgs: list[dict[str, Any]] = [{"type": "tick", "tick": t} for t in range(10)]
    msgs.insert(3, {"type": "event", "tick": 2})
    msgs += [{"type": "progress", "done": 1}, {"type": "progress", "done": 2}]
    out = coalesce(msgs)
    assert [m.get("tick") for m in out if m["type"] == "tick"] == [3, 7, 9]
    assert {"type": "event", "tick": 2} in out
    assert [m["done"] for m in out if m["type"] == "progress"] == [2]
    assert [m["tick"] for m in coalesce(msgs, after=5) if m["type"] == "tick"] == [7, 9]
