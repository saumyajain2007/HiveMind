"""Saved scenarios: CRUD."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from ..deps import StoreDep
from ..schemas import ScenarioRecord, ScenarioSpec
from ..storage import NotFound

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"scenario {scenario_id} not found")


@router.post("", response_model=ScenarioRecord, status_code=status.HTTP_201_CREATED)
def create_scenario(spec: ScenarioSpec, store: StoreDep) -> ScenarioRecord:
    return store.create_scenario(spec)


@router.get("", response_model=list[ScenarioRecord])
def list_scenarios(store: StoreDep) -> list[ScenarioRecord]:
    return store.list_scenarios()


@router.get("/{scenario_id}", response_model=ScenarioRecord)
def get_scenario(scenario_id: str, store: StoreDep) -> ScenarioRecord:
    try:
        return store.get_scenario(scenario_id)
    except NotFound:
        raise _not_found(scenario_id) from None


@router.put("/{scenario_id}", response_model=ScenarioRecord)
def update_scenario(scenario_id: str, spec: ScenarioSpec, store: StoreDep) -> ScenarioRecord:
    try:
        return store.update_scenario(scenario_id, spec)
    except NotFound:
        raise _not_found(scenario_id) from None


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(scenario_id: str, store: StoreDep) -> Response:
    try:
        store.delete_scenario(scenario_id)
    except NotFound:
        raise _not_found(scenario_id) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
