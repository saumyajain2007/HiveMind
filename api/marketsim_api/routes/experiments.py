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
