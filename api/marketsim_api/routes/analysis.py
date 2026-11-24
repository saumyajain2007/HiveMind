"""Calibrations, backtests and datasets (issue #18).

Calibrations and backtests are jobs like runs: they share the run index (mode `calibration` /
`backtest`), `POST /runs/{id}/cancel` and the live stream, which sends one `trial` or `origin`
message per finished step.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

import marketsim

from ..config_schema import default_parameters
from ..datasets import DatasetStore
from ..deps import JobsDep, StoreDep
from ..schemas import (
    BacktestCreate,
    BacktestSpec,
    CalibrationCreate,
    CalibrationSpec,
    DatasetDetail,
    DatasetRecord,
    DatasetUpload,
    RunDetail,
    RunMode,
    RunSpec,
    ScenarioSpec,
)
from ..storage import NotFound, Store

router = APIRouter(tags=["analysis"])


def _datasets(request: Request) -> DatasetStore:
    ds: DatasetStore = request.app.state.datasets
    return ds


# --------------------------------------------------------------------------- datasets


@router.post("/data/upload", response_model=DatasetRecord, status_code=status.HTTP_201_CREATED)
def upload(body: DatasetUpload, request: Request) -> DatasetRecord:
    """Store a `date,close` CSV and its dated events after validating both."""
    try:
        return _datasets(request).create(body)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


@router.get("/data", response_model=list[DatasetRecord])
def list_datasets(request: Request) -> list[DatasetRecord]:
    return _datasets(request).list()


@router.get("/data/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: str, request: Request) -> DatasetDetail:
    try:
        return _datasets(request).detail(dataset_id)
    except NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dataset {dataset_id} not found") from None


@router.delete("/data/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: str, request: Request) -> Response:
    try:
        _datasets(request).delete(dataset_id)
    except NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dataset {dataset_id} not found") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- jobs


def _start(
    body: CalibrationCreate | BacktestCreate,
    mode: RunMode,
    request: Request,
    store: Store,
    jobs: Any,
) -> RunDetail:
    ds = _datasets(request)
    try:
        rec = ds.get(body.dataset_id)
    except NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dataset {body.dataset_id} not found") from None
    scenario = ScenarioSpec(
        name=f"{mode.value}: {rec.name}", n_agents=body.n_agents, days=min(rec.n_days, 250), seed=body.seed
    )
    calibration = backtest = None
    if isinstance(body, CalibrationCreate):
        calibration = CalibrationSpec(
            dataset_id=rec.id,
            dataset_sha256=rec.sha256,
            space=body.space,
            n_trials=body.n_trials,
            runs_per_trial=body.runs_per_trial,
        )
    else:
        bad = [o for o in body.origins or [] if not 0 <= o < rec.n_days - body.horizon]
        if bad:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"origins {bad} leave no room for a {body.horizon}-day horizon in {rec.n_days} days",
            )
        backtest = BacktestSpec(
            dataset_id=rec.id,
            dataset_sha256=rec.sha256,
            origins=body.origins,
            horizon=body.horizon,
            runs=body.runs,
            lookback_days=body.lookback_days,
        )
    spec = RunSpec(
        engine_version=marketsim.__version__,
        mode=mode,
        runs=1,
        workers=1,
        seed=body.seed,
        scenario=scenario,
        parameters=body.parameters if body.parameters is not None else default_parameters(),
        calibration=calibration,
        backtest=backtest,
    )
    run = store.create_run(spec, name=body.name or scenario.name)
    ds.copy_into(rec.id, store.run_dir(run.id))
    if jobs is not None:
        jobs.submit(run)
    return run


def _get(store: Store, run_id: str, mode: RunMode, filename: str, step: str, jobs: Any) -> dict[str, Any]:
    try:
        run = store.get_run(run_id)
    except NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{mode.value} {run_id} not found") from None
    if run.mode != mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{run_id} is not a {mode.value}")
    path = store.run_dir(run_id) / filename
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    steps: list[dict[str, Any]] = []
    ch = jobs.channels.get(run_id) if jobs is not None else None
    if result is None and ch is not None:  # still running: what has finished so far
        steps = [m for m in ch.messages if m["type"] == step]
    return {"run": run.model_dump(mode="json"), "result": result, "progress": steps}


@router.get("/runs/{run_id}/isolation")
def get_isolation(run_id: str, store: StoreDep, jobs: JobsDep) -> dict[str, Any]:
    """Isolated effect of every event (start one with `POST /runs`, `mode: "isolation"`): per
    event the paired with/without price-effect path, final effect with a 95% CI, peak, timing,
    pass-through and extra volume, plus the total move and the interaction between events."""
    return _get(store, run_id, RunMode.isolation, "isolation.json", "progress", jobs)


@router.post("/calibrations", response_model=RunDetail, status_code=status.HTTP_201_CREATED)
def create_calibration(
    body: CalibrationCreate, request: Request, store: StoreDep, jobs: JobsDep
) -> RunDetail:
    """Start a calibration; watch it on `WS /runs/{id}/stream` (one `trial` message per trial)."""
    return _start(body, RunMode.calibration, request, store, jobs)


@router.get("/calibrations/{run_id}")
def get_calibration(run_id: str, store: StoreDep, jobs: JobsDep) -> dict[str, Any]:
    """The run, its result (trial log, best parameters, best path vs observed, sensitivity)
    once finished, and the trials finished so far while running."""
    return _get(store, run_id, RunMode.calibration, "calibration.json", "trial", jobs)


@router.post("/backtests", response_model=RunDetail, status_code=status.HTTP_201_CREATED)
def create_backtest(body: BacktestCreate, request: Request, store: StoreDep, jobs: JobsDep) -> RunDetail:
    """Start a backtest; watch it on `WS /runs/{id}/stream` (one `origin` message per origin)."""
    return _start(body, RunMode.backtest, request, store, jobs)


@router.get("/backtests/{run_id}")
def get_backtest(run_id: str, store: StoreDep, jobs: JobsDep) -> dict[str, Any]:
    """The run, its result (CRPS per origin for the model and the random walk, skill score)
    once finished, and the origins finished so far while running."""
    return _get(store, run_id, RunMode.backtest, "backtest.json", "origin", jobs)
