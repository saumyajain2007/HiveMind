"""Runs: create (queued), list, inspect, delete.

Runs are only recorded here; executing them (job runner, live stream) is issue #17.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

import marketsim

from ..config_schema import default_parameters
from ..deps import StoreDep
from ..schemas import RunCreate, RunDetail, RunList, RunSpec, RunStatus
from ..storage import Conflict, NotFound

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunDetail, status_code=status.HTTP_201_CREATED)
def create_run(body: RunCreate, store: StoreDep) -> RunDetail:
    """Record a run with status `queued`.

    The scenario is copied into the run, so later edits to a saved scenario never change a
    past run.
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
    return store.create_run(spec, name=body.name or scenario.name)


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


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: str, store: StoreDep) -> Response:
    try:
        store.delete_run(run_id)
    except NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found") from None
    except Conflict as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
