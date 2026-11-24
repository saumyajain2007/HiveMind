"""Real-data experiments (`python -m marketsim.experiment <TICKER>`), served read-only.

Results live in `docs/experiments/<TICKER>/results.json` (override the folder with
MARKETSIM_EXPERIMENTS_DIR).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/experiments", tags=["experiments"])
library_router = APIRouter(prefix="/event-library", tags=["experiments"])


def experiments_dir() -> Path:
    default = Path(__file__).resolve().parents[3] / "docs" / "experiments"
    return Path(os.environ.get("MARKETSIM_EXPERIMENTS_DIR", str(default)))


@lru_cache(maxsize=8)
def _load(path: str, mtime: float) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def _results(ticker: str) -> dict[str, Any]:
    p = experiments_dir() / ticker.upper() / "results.json"
    if not ticker.isalnum() or not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no experiment for {ticker}")
    return _load(str(p), p.stat().st_mtime)


@router.get("")
def list_experiments() -> list[dict[str, Any]]:
    """Every experiment with its periods and headline skill (one-day horizon)."""
    out = []
    root = experiments_dir()
    if root.exists():
        for d in sorted(root.iterdir()):
            if (d / "results.json").exists():
                r = _results(d.name)
                one = r["backtest"].get("1") or next(iter(r["backtest"].values()))
                out.append(
                    {
                        "ticker": r["ticker"],
                        "name": r["name"],
                        "period": r["period"],
                        "events": r["events"],
                        "horizons": [int(h) for h in r["backtest"]],
                        "skill": {
                            m: v["skill_vs_random_walk"] for m, v in one["summary"]["all"].items() if m != "n"
                        },
                    }
                )
    return out


@router.get("/{ticker}")
def get_experiment(ticker: str) -> dict[str, Any]:
    """Full results: impact-model metrics, simulation training log, and every out-of-sample
    forecast (date, actual close, each model's median / 90% interval / P(up) / CRPS)."""
    return _results(ticker)


@router.get("/{ticker}/strategy")
def get_strategy(ticker: str) -> dict[str, Any]:
    """Forecast statistics (mean, sd, quantiles, P(up) per day, with bias / RMSE / information
    coefficient / coverage), the latest forecast, and trading strategies built on the model."""
    p = experiments_dir() / ticker.upper() / "strategy.json"
    if not ticker.isalnum() or not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no strategy results for {ticker}")
    return _load(str(p), p.stat().st_mtime)


@router.get("/{ticker}/isolation")
def get_real_isolation(ticker: str) -> dict[str, Any]:
    """Real earnings windows split into each filing's isolated contribution
    (`python -m marketsim.isolation <TICKER>`)."""
    p = experiments_dir() / ticker.upper() / "isolation.json"
    if not ticker.isalnum() or not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no isolation results for {ticker}")
    return _load(str(p), p.stat().st_mtime)


@library_router.get("")
def get_event_library(events: bool = False) -> dict[str, Any]:
    """Every filing of every downloaded stock (`python -m marketsim.event_library`): the isolated
    real effect of each event type, earnings reactions by stock, and the pooled impact model.
    `events=true` adds the per-event rows (large)."""
    p = experiments_dir() / "events" / "library.json"
    if not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no event library yet")
    lib = _load(str(p), p.stat().st_mtime)
    return lib if events else {k: v for k, v in lib.items() if k != "events"}
