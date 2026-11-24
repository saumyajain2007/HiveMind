"""Write real engine results as mock fixtures for the web app (issues #20–#25).

    uv run python -m marketsim_api.export_fixtures

Runs a small demo single run, a Monte Carlo run, a calibration and a backtest through the real
API (threads, temporary data dir), then saves each results endpoint's JSON under
`web/src/mocks/fixtures/results/`. The mock server (MSW) serves these for any run id, so pages
show genuine model output without a backend. Not checked in CI (it takes ~1 minute); rerun it
after changing the engine or the result endpoints.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from marketsim.backtest import synthetic_series
from marketsim.scenarios import DEMO_EVENTS

from .main import create_app
from .settings import Settings

OUT = Path(__file__).resolve().parents[2] / "web" / "src" / "mocks" / "fixtures" / "results"
V1 = "/api/v1"


def _wait(c: TestClient, run_id: str) -> dict[str, Any]:
    while True:
        run = c.get(f"{V1}/runs/{run_id}").json()
        if run["status"] in ("done", "failed", "cancelled"):
            if run["status"] != "done":
                raise RuntimeError(f"run {run_id} {run['status']}: {run.get('error')}")
            return run  # type: ignore[no-any-return]
        time.sleep(0.2)


def _write(name: str, data: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"  {name}.json  {(OUT / f'{name}.json').stat().st_size / 1024:.0f} kB")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(data_dir=Path(tmp), log_json=False, run_jobs=True, max_jobs=4, executor="thread")
        with TestClient(create_app(settings)) as c:
            scenario = {
                "name": "Demo: rumour → denial → earnings miss",
                "n_agents": 3_000,
                "days": 5,
                "seed": 0,
                "events": DEMO_EVENTS,
            }
            # Dynamics seed 15 of this world is one where the rumour mutates (2 mutations, 2 inventions),
            # so the Narratives page has a family tree to show; with default rates most seeds have none.
            single = c.post(f"{V1}/runs", json={"scenario": scenario, "seed": 15}).json()
            mc = c.post(
                f"{V1}/runs",
                json={"scenario": {**scenario, "n_agents": 2_000}, "mode": "montecarlo", "runs": 20},
            ).json()
            closes, events = synthetic_series(days=40, seed=1)
            csv = "date,close\n" + "\n".join(
                f"2025-{1 + d // 28:02d}-{1 + d % 28:02d},{x:.4f}" for d, x in enumerate(closes)
            )
            dated = [
                {
                    **{k: v for k, v in e.event.to_dict().items() if k not in ("tick", "id", "parent")},
                    "day": e.day,
                }
                for e in events
            ]
            ds = c.post(
                f"{V1}/data/upload", json={"name": "Synthetic stock (40 days)", "csv": csv, "events": dated}
            ).json()
            cal = c.post(
                f"{V1}/calibrations",
                json={"dataset_id": ds["id"], "n_agents": 800, "n_trials": 16, "runs_per_trial": 2},
            ).json()
            bt = c.post(
                f"{V1}/backtests",
                json={"dataset_id": ds["id"], "n_agents": 800, "origins": list(range(22, 39)), "runs": 6},
            ).json()
            runs = {
                k: _wait(c, r["id"]) for k, r in {"single": single, "mc": mc, "cal": cal, "bt": bt}.items()
            }
            s, m = single["id"], mc["id"]
            _write("run-single", runs["single"])
            _write("run-montecarlo", runs["mc"])
            _write("series", c.get(f"{V1}/runs/{s}/series").json())
            _write("series-mc", c.get(f"{V1}/runs/{m}/series").json())
            _write("quantiles", c.get(f"{V1}/runs/{m}/quantiles").json())
            _write("paths", c.get(f"{V1}/runs/{m}/paths?sample=20&every=2").json())
            _write("awareness", c.get(f"{V1}/runs/{s}/awareness?every=2").json())
            _write("lineage", c.get(f"{V1}/runs/{s}/lineage").json())
            _write("stylized", c.get(f"{V1}/runs/{s}/stylized-facts").json())
            _write("stylized-mc", c.get(f"{V1}/runs/{m}/stylized-facts").json())
            _write("graph", c.get(f"{V1}/runs/{s}/graph?sample=1200").json())
            _write("node-seen", c.get(f"{V1}/runs/{s}/node-seen").json())
            _write("dataset", c.get(f"{V1}/data/{ds['id']}").json())
            _write("calibration", c.get(f"{V1}/calibrations/{cal['id']}").json())
            _write("backtest", c.get(f"{V1}/backtests/{bt['id']}").json())


if __name__ == "__main__":
    main()
