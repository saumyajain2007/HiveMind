"""Runs: create (and start), list, inspect, cancel, delete (issues #16, #17).

`POST /runs` records the run and hands it to the job runner; the live stream is in
`routes/stream.py`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

import marketsim

from ..config_schema import default_parameters
from ..deps import JobsDep, StoreDep
from ..schemas import RunCreate, RunDetail, RunList, RunSpec, RunStatus
from ..storage import Conflict, NotFound

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunDetail, status_code=status.HTTP_201_CREATED)
def create_run(body: RunCreate, store: StoreDep, jobs: JobsDep) -> RunDetail:
    """Record a run with status `queued` and start it.

    The scenario is copied into the run, so later edits to a saved scenario never change a
    past run. Watch it on `WS /runs/{id}/stream`.
    """
    if body.scenario_id is not None:
        try:
            scenario = store.get_scenario(body.scenario_id).spec
        except NotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"scenario {body.scenario_id} not found") from None
    else:
        assert body.scenario is not None  # guaranteed by RunCreate validation
        scenario = body.scenario
    spec = RunSpec(
        engine_version=marketsim.__version__,
        mode=body.mode,
        runs=body.runs,
        workers=body.workers,
        seed=body.seed if body.seed is not None else scenario.seed,
        scenario=scenario,
        scenario_id=body.scenario_id,
        parameters=body.parameters if body.parameters is not None else default_parameters(),
    )
    run = store.create_run(spec, name=body.name or scenario.name)
    if jobs is not None:
        jobs.submit(run, pace=body.pace)
    return run


@router.get("", response_model=RunList)
def list_runs(
    store: StoreDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_: Annotated[RunStatus | None, Query(alias="status")] = None,
) -> RunList:
    items, total = store.list_runs(limit=limit, offset=offset, status=status_)
    return RunList(items=items, total=total)


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: str, store: StoreDep) -> RunDetail:
    try:
        return store.get_run(run_id)
    except NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found") from None


@router.post("/{run_id}/cancel", response_model=RunDetail, status_code=status.HTTP_202_ACCEPTED)
def cancel_run(run_id: str, store: StoreDep, jobs: JobsDep) -> RunDetail:
    """Ask a queued or running run to stop. It ends as `cancelled` and keeps what it computed."""
    try:
        run = store.get_run(run_id)
    except NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found") from None
    if run.status not in (RunStatus.queued, RunStatus.running):
        raise HTTPException(status.HTTP_409_CONFLICT, f"run {run_id} is already {run.status.value}")
    if jobs is None or not jobs.cancel(run_id):
        store.set_status(run_id, RunStatus.cancelled)
    return store.get_run(run_id)


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: str, store: StoreDep) -> Response:
    try:
        store.delete_run(run_id)
    except NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found") from None
    except Conflict as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
