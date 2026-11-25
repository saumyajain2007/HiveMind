"""Request and response models for the API (issue #16)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from marketsim.config import (
    ALL_PLATFORMS,
    CATEGORIES,
    MARKET_CLOSE_TICK,
    MARKET_OPEN_TICK,
    TICKS_PER_DAY,
    TOPICS,
)
from marketsim.events import NEWS_KINDS, SEEDINGS, Event

from .config_schema import Parameters

MAX_AGENTS = 2_000_000
MAX_DAYS = 250
MAX_RUNS = 1_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- events + scenarios


class EventSpec(_Strict):
    """A scheduled news event. Mirrors `marketsim.events.Event`."""

    id: int = Field(-1, ge=-1, description="Unique within the scenario; -1 to assign automatically")
    tick: int = Field(ge=0, description=f"Tick of injection ({TICKS_PER_DAY} ticks per day, 15 minutes each)")
    kind: str = Field(json_schema_extra={"enum": list(NEWS_KINDS)})
    ticker: int = Field(0, ge=0, description="Ticker / sector index; v1 simulates one ticker (0)")
    true_impact: Annotated[float, Field(ge=-0.5, le=0.5)] | None = Field(
        0.0, description="Log change in fundamental value; hidden. null = the engine draws it at injection"
    )
    sentiment: float = Field(ge=-1.0, le=1.0)
    credibility: float = Field(ge=0.0, le=1.0)
    salience: float = Field(ge=0.0, le=1.0)
    complexity: float = Field(ge=0.0, le=1.0)
    seeding: str = Field(json_schema_extra={"enum": list(SEEDINGS)})
    parent: int = Field(-1, ge=-1, description="Id of the event this follows up, or -1")
    topic: str = Field("finance", json_schema_extra={"enum": list(TOPICS)})
    label: str | None = Field(
        None, max_length=200, description="Headline shown in the UI (not used by the engine)"
    )

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in NEWS_KINDS:
            raise ValueError(f"unknown kind {v!r}; expected one of {NEWS_KINDS}")
        return v

    @field_validator("seeding")
    @classmethod
    def _seeding(cls, v: str) -> str:
        if v not in SEEDINGS:
            raise ValueError(f"unknown seeding {v!r}; expected one of {SEEDINGS}")
        return v

    @field_validator("topic")
    @classmethod
    def _topic(cls, v: str) -> str:
        if v not in TOPICS:
            raise ValueError(f"unknown topic {v!r}")
        return v

    def to_engine(self) -> Event:
        return Event(
            tick=self.tick,
            kind=self.kind,
            ticker=self.ticker,
            true_impact=0.0 if self.true_impact is None else self.true_impact,
            draw_impact=self.true_impact is None,
            sentiment=self.sentiment,
            credibility=self.credibility,
            salience=self.salience,
            complexity=self.complexity,
            seeding=self.seeding,
            parent=self.parent,
            id=self.id,
            topic=self.topic,
        )


class ScenarioSpec(_Strict):
    """What to simulate: population size, length, seed and the scheduled events."""

    name: str = Field("Untitled scenario", min_length=1, max_length=120)
    description: str = Field("", max_length=2000)
    n_agents: int = Field(10_000, ge=100, le=MAX_AGENTS)
    days: int = Field(5, ge=1, le=MAX_DAYS)
    seed: int = Field(0, ge=0, le=2**32 - 1)
    events: list[EventSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_events(self) -> ScenarioSpec:
        n_ticks = self.days * TICKS_PER_DAY
        next_id = max((e.id for e in self.events), default=-1) + 1
        for e in self.events:
            if e.id < 0:
                e.id = next_id
                next_id += 1
        ids = [e.id for e in self.events]
        if len(set(ids)) != len(ids):
            raise ValueError("event ids must be unique")
        by_id = {e.id: e for e in self.events}
        for e in self.events:
            if e.tick >= n_ticks:
                raise ValueError(f"event {e.id}: tick {e.tick} is past the end of the run ({n_ticks} ticks)")
            if e.parent >= 0:
                parent = by_id.get(e.parent)
                if parent is None:
                    raise ValueError(f"event {e.id}: parent {e.parent} does not exist")
                if parent.id == e.id or parent.tick > e.tick:
                    raise ValueError(f"event {e.id}: parent {e.parent} must come earlier")
        self.events.sort(key=lambda e: (e.tick, e.id))
        return self

    @property
    def n_ticks(self) -> int:
        return self.days * TICKS_PER_DAY


class ScenarioRecord(_Strict):
    id: str
    created_at: datetime
    updated_at: datetime
    spec: ScenarioSpec


# --------------------------------------------------------------------------- runs


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class RunMode(StrEnum):
    single = "single"
    montecarlo = "montecarlo"
    calibration = "calibration"
    backtest = "backtest"
    isolation = "isolation"


class RunCreate(_Strict):
    """Start a run from a saved scenario (`scenario_id`) or an inline `scenario`."""

    name: str | None = Field(None, max_length=120)
    mode: RunMode = RunMode.single
    runs: int = Field(
        1,
        ge=1,
        le=MAX_RUNS,
        description="Monte Carlo repetitions (1 for a single run); isolation: the number of paired seeds",
    )
    workers: int = Field(1, ge=1, le=64)
    scenario_id: str | None = None
    scenario: ScenarioSpec | None = None
    parameters: Parameters | None = Field(None, description="Model parameters; defaults if omitted")
    seed: int | None = Field(None, ge=0, le=2**32 - 1, description="Overrides the scenario's seed")
    pace: float = Field(
        0.0,
        ge=0.0,
        le=10_000.0,
        description="Live viewing: at most this many ticks per second (0 = as fast as possible). "
        "Does not change results.",
    )

    @model_validator(mode="after")
    def _one_scenario(self) -> RunCreate:
        if (self.scenario_id is None) == (self.scenario is None):
            raise ValueError("give exactly one of scenario_id or scenario")
        if self.mode == RunMode.single and self.runs != 1:
            raise ValueError("a single run has runs = 1; use mode 'montecarlo' for more")
        if self.mode not in (RunMode.single, RunMode.montecarlo, RunMode.isolation):
            raise ValueError("use POST /calibrations or POST /backtests for those modes")
        if self.mode == RunMode.isolation and self.runs < 2:
            raise ValueError("an isolation needs runs >= 2 (paired seeds) for a confidence interval")
        return self


# --------------------------------------------------------------------------- analysis jobs (#18)

CALIBRATION_SPACE = {
    "impact_Y": (0.3, 1.5),
    "base_share": (0.1, 0.5),
    "mu0": (0.1, 0.7),
    "sentiment_scale": (0.01, 0.10),
}


class CalibrationSpec(_Strict):
    dataset_id: str
    dataset_sha256: str
    space: dict[str, tuple[float, float]]
    n_trials: int
    runs_per_trial: int


class BacktestSpec(_Strict):
    dataset_id: str
    dataset_sha256: str
    origins: list[int] | None
    horizon: int
    runs: int
    lookback_days: int


class _AnalysisCreate(_Strict):
    name: str | None = Field(None, max_length=120)
    dataset_id: str
    n_agents: int = Field(3_000, ge=100, le=200_000)
    seed: int = Field(0, ge=0, le=2**32 - 1)
    parameters: Parameters | None = Field(None, description="Base model parameters; defaults if omitted")


class CalibrationCreate(_AnalysisCreate):
    """Random-search calibration against an uploaded dataset's daily closes."""

    space: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: dict(CALIBRATION_SPACE),
        description="Parameter -> (low, high). Names: impact_Y, base_share, mu0, sentiment_scale or "
        "'section.field'",
    )
    n_trials: int = Field(40, ge=1, le=1_000)
    runs_per_trial: int = Field(4, ge=1, le=50)

    @model_validator(mode="after")
    def _check_space(self) -> CalibrationCreate:
        from marketsim.calibration import with_params
        from marketsim.config import Config

        if not self.space:
            raise ValueError("space needs at least one parameter")
        for name, (lo, hi) in self.space.items():
            if not lo <= hi:
                raise ValueError(f"{name}: low must not exceed high")
            try:
                with_params(Config(), {name: lo})
            except (KeyError, ValueError, TypeError):
                raise ValueError(f"unknown or non-numeric parameter {name!r}") from None
        return self


class BacktestCreate(_AnalysisCreate):
    """CRPS backtest of the model against a random walk on an uploaded dataset."""

    origins: list[int] | None = Field(
        None, description="Day indices to forecast from; default every day from day 20 on"
    )
    horizon: int = Field(1, ge=1, le=60, description="Days ahead")
    runs: int = Field(10, ge=1, le=200, description="Monte Carlo runs per origin")
    lookback_days: int = Field(3, ge=0, le=30)


# --------------------------------------------------------------------------- datasets (#18)


class DatasetUpload(_Strict):
    """A daily close series (CSV text with a `date,close` header) plus optional dated events."""

    name: str = Field(min_length=1, max_length=120)
    csv: str = Field(min_length=1, max_length=5_000_000)
    events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Event objects with `date` (or `day`) and optional `time` instead of `tick`",
    )


class DatasetRecord(_Strict):
    id: str
    name: str
    created_at: datetime
    n_days: int
    first_date: str
    last_date: str
    n_events: int
    sha256: str


class DatasetDetail(DatasetRecord):
    dates: list[str]
    closes: list[float]
    events: list[dict[str, Any]]


# --------------------------------------------------------------------------- headline parsing (#18)


class HeadlineIn(_Strict):
    text: str = Field(min_length=1, max_length=1_000)
    tick: int = Field(0, ge=0)


class ParseRequest(_Strict):
    headlines: list[HeadlineIn] = Field(min_length=1, max_length=200)
    responses: list[str] | None = Field(
        None,
        description="LLM replies pasted by hand, one per headline (the manual flow when no provider "
        "is configured)",
    )
    ticker: int = Field(0, ge=0)
    first_id: int = Field(0, ge=0)


class ParseResponse(_Strict):
    provider: str
    prompts: list[str] = Field(default_factory=list, description="Prompts to paste into an LLM")
    events: list[EventSpec] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RunSpec(_Strict):
    """Everything needed to reproduce a run exactly. Stored as runs/<id>/spec.json."""

    engine_version: str
    mode: RunMode
    runs: int
    workers: int
    seed: int
    scenario: ScenarioSpec
    scenario_id: str | None = None
    parameters: Parameters
    calibration: CalibrationSpec | None = None
    backtest: BacktestSpec | None = None


class RunRecord(_Strict):
    id: str
    name: str
    status: RunStatus
    mode: RunMode
    runs: int
    n_agents: int
    days: int
    seed: int
    scenario_id: str | None
    spec_hash: str = Field(description="sha256 of the canonical spec; equal hashes give identical results")
    created_at: datetime
    updated_at: datetime
    summary: dict[str, Any] | None = None
    error: str | None = None


class RunDetail(RunRecord):
    spec: RunSpec


class RunList(_Strict):
    items: list[RunRecord]
    total: int


# --------------------------------------------------------------------------- config endpoints


class FieldMeta(_Strict):
    name: str
    key: str
    kind: Literal["int", "float", "bool", "map", "list", "json", "other"]
    default: Any
    min: float | None
    max: float | None
    description: str
    placeholder: bool


class SectionMeta(_Strict):
    name: str
    fields: list[FieldMeta]


class Enumerations(_Strict):
    kinds: list[str] = list(NEWS_KINDS)
    seedings: list[str] = list(SEEDINGS)
    topics: list[str] = list(TOPICS)
    platforms: list[str] = list(ALL_PLATFORMS)
    categories: list[str] = list(CATEGORIES)


class Clock(_Strict):
    ticks_per_day: int = TICKS_PER_DAY
    minutes_per_tick: int = 24 * 60 // TICKS_PER_DAY
    market_open_tick: int = MARKET_OPEN_TICK
    market_close_tick: int = MARKET_CLOSE_TICK


class ConfigSchema(_Strict):
    sections: list[SectionMeta]
    enums: Enumerations = Field(default_factory=Enumerations)
    clock: Clock = Field(default_factory=Clock)


class ConfigDefaults(_Strict):
    parameters: Parameters
    scenario: ScenarioSpec


class Health(_Strict):
    status: Literal["ok"] = "ok"
    api_version: str
    engine_version: str
