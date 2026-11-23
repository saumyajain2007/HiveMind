"""Parameter defaults and field metadata for the Scenario Builder."""

from __future__ import annotations

from fastapi import APIRouter

from ..config_schema import default_parameters, ui_schema
from ..schemas import ConfigDefaults, ConfigSchema, ScenarioSpec, SectionMeta

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/defaults", response_model=ConfigDefaults)
def get_defaults() -> ConfigDefaults:
    """Default parameters (from `config.py`) and a default empty scenario."""
    return ConfigDefaults(parameters=default_parameters(), scenario=ScenarioSpec())


@router.get("/schema", response_model=ConfigSchema)
def get_schema() -> ConfigSchema:
    """Every parameter with its default, range, description and PLACEHOLDER flag, plus enums."""
    return ConfigSchema(sections=[SectionMeta.model_validate(s) for s in ui_schema()])
