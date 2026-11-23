"""Tests for marketsim.event_parser (issue #14). The LLM is always a fake callable."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from marketsim.event_parser import (
    EVENT_JSON_SCHEMA,
    PROMPT_TEMPLATE,
    TRUE_IMPACT_LIMIT,
    EventParseError,
    Headline,
    abnormal_return_impact,
    build_prompt,
    event_study,
    extract_json,
    parse_headlines,
    validate_event,
)
from marketsim.events import KINDS, NEWS_KINDS, SEEDINGS, Event

GOOD = {
    "kind": "earnings",
    "sentiment": -0.7,
    "credibility": 0.95,
    "salience": 0.6,
    "complexity": 0.5,
    "seeding": "official",
    "true_impact": -0.05,
    "topic": "finance",
    "parent": -1,
}


class FakeLLM:
    """Returns canned responses keyed by a substring of the headline line; counts calls."""

    def __init__(self, responses: dict[str, object], default: object = GOOD) -> None:
        self.responses, self.default = responses, default
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        last = prompt.strip().splitlines()[-1]  # 'Headline: "..."'
        for key, resp in self.responses.items():
            if key in last:
                return resp if isinstance(resp, str) else json.dumps(resp)
        return json.dumps(self.default)


# --------------------------------------------------------------------------- Event record


def test_event_has_exactly_the_user_fields_plus_id_and_topic() -> None:
    user = ["tick", "kind", "ticker", "true_impact", "sentiment", "credibility", "salience"]
    user += ["complexity", "seeding", "parent"]
    assert list(Event.__dataclass_fields__) == [*user, "id", "topic"]
    ev = Event(0, "rumour", 0, 0.0, 0.5, 0.2, 0.7, 0.2, "anonymous")
    assert ev.parent == -1 and ev.topic == "finance" and not ev.is_real
    assert set(NEWS_KINDS) < set(KINDS) and "price_move" in KINDS


# --------------------------------------------------------------------------- validation


def test_validate_good_event() -> None:
    ev = validate_event(GOOD, tick=40, event_id=3)
    assert ev == Event(40, "earnings", 0, -0.05, -0.7, 0.95, 0.6, 0.5, "official", -1, 3, "finance")
    assert ev.is_real


def test_validate_clamps_ranges() -> None:
    d = {**GOOD, "sentiment": 3.0, "credibility": -0.2, "salience": 1.7, "complexity": -5, "true_impact": 2.0}
    ev = validate_event(d)
    assert (ev.sentiment, ev.credibility, ev.salience, ev.complexity) == (1.0, 0.0, 1.0, 0.0)
    assert ev.true_impact == TRUE_IMPACT_LIMIT
    assert validate_event({**GOOD, "true_impact": -9}).true_impact == -TRUE_IMPACT_LIMIT
    assert validate_event({**GOOD, "parent": -7}).parent == -1


@pytest.mark.parametrize(
    "bad",
    [
        {**GOOD, "kind": "merger"},
        {**GOOD, "kind": "price_move"},  # internal kind, never parsed from news
        {**GOOD, "seeding": "telepathy"},
        {**GOOD, "topic": "gardening"},
        {**GOOD, "sentiment": "very bad"},
        {**GOOD, "sentiment": float("nan")},
        {**GOOD, "credibility": True},
        {**GOOD, "parent": 1.5},
        {k: v for k, v in GOOD.items() if k != "salience"},
        [GOOD],
    ],
)
def test_validate_rejects(bad: object) -> None:
    with pytest.raises(EventParseError):
        validate_event(bad)  # type: ignore[arg-type]


def test_extract_json_tolerates_fences_and_prose() -> None:
    assert extract_json("```json\n" + json.dumps(GOOD) + "\n```") == GOOD
    assert extract_json("Sure! Here it is: " + json.dumps(GOOD) + " Hope that helps.") == GOOD
    for bad in ["no json here", "{not: valid}", "[1, 2, 3]", '{"a": 1']:
        with pytest.raises(EventParseError):
            extract_json(bad)


# --------------------------------------------------------------------------- prompt


def test_prompt_contents() -> None:
    p = build_prompt('Acme "beats" estimates', ["earlier one"])
    assert p.count("Headline:") == 4  # 3 few-shot examples + the target
    assert '"kind"' in p and "statement" in p and "anonymous" in p
    assert "0: earlier one" in p
    assert p.rstrip().endswith("Headline: \"Acme 'beats' estimates\"")
    assert build_prompt("x") == build_prompt("x")  # deterministic, so caching works
    assert "(none)" in build_prompt("x")
    assert "$" not in PROMPT_TEMPLATE.substitute(
        schema="", limit=0.5, topics="", examples="", context="", headline=""
    )


def test_schema_matches_validator() -> None:
    assert set(EVENT_JSON_SCHEMA["properties"]["kind"]["enum"]) == set(NEWS_KINDS)
    assert set(EVENT_JSON_SCHEMA["properties"]["seeding"]["enum"]) == set(SEEDINGS)
    for example in [line for line in build_prompt("x").splitlines() if line.startswith('{"kind"')]:
        validate_event(json.loads(example))  # every few-shot answer is itself valid


# --------------------------------------------------------------------------- parse_headlines


def test_parse_headlines_ids_ticks_and_parents(tmp_path: Path) -> None:
    rumour = {**GOOD, "kind": "rumour", "seeding": "anonymous", "true_impact": 0.0, "sentiment": 0.8}
    denial = {**GOOD, "kind": "statement", "true_impact": 0.0, "parent": 0}
    llm = FakeLLM({"takeover talks": rumour, "denies": denial})
    events = parse_headlines(
        [
            Headline("Forum post: Acme in takeover talks", tick=100),
            {"text": "Acme denies takeover", "tick": 300},
            "Acme misses estimates",
        ],
        llm,
        tmp_path / "cache.json",
        first_id=10,
    )
    assert [e.id for e in events] == [10, 11, 12]
    assert [e.tick for e in events] == [100, 300, 0]
    assert [e.kind for e in events] == ["rumour", "statement", "earnings"]
    assert events[1].parent == 10  # batch index 0 mapped to event id 10
    assert "0: Forum post: Acme in takeover talks" in llm.calls[1]  # earlier headlines given as context


def test_cache_skips_llm_on_rerun(tmp_path: Path) -> None:
    cache = tmp_path / "sub" / "cache.json"
    heads = ["Acme misses estimates", "Acme raises dividend"]
    llm = FakeLLM({})
    first = parse_headlines(heads, llm, cache)
    assert len(llm.calls) == 2 and cache.exists()
    assert len(json.loads(cache.read_text(encoding="utf-8"))) == 2

    llm2 = FakeLLM({}, default={"kind": "garbage"})  # would fail if it were called
    again = parse_headlines(heads, llm2, cache)
    assert llm2.calls == [] and again == first

    llm3 = FakeLLM({})
    parse_headlines([*heads, "Acme CEO resigns"], llm3, cache)
    assert len(llm3.calls) == 1  # only the new headline


def test_parse_without_cache_calls_every_time() -> None:
    llm = FakeLLM({})
    parse_headlines(["a"], llm)
    parse_headlines(["a"], llm)
    assert len(llm.calls) == 2


def test_bad_response_raises_or_skips(tmp_path: Path) -> None:
    llm = FakeLLM({"broken": "I cannot answer that", "weird": {**GOOD, "seeding": "pigeon"}})
    with pytest.raises(EventParseError, match="headline 1"):
        parse_headlines(["fine", "broken"], llm, tmp_path / "c.json")
    # the good response was cached even though the batch failed
    assert len(json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))) == 2

    events = parse_headlines(["fine", "broken", "weird", "also fine"], llm, on_error="skip")
    assert [e.id for e in events] == [0, 1]


def test_parent_must_point_backwards() -> None:
    llm = FakeLLM({"self": {**GOOD, "parent": 0}})
    with pytest.raises(EventParseError, match="earlier headline"):
        parse_headlines(["self ref"], llm)


def test_parent_of_skipped_headline_is_dropped() -> None:
    llm = FakeLLM({"broken": "nope", "child": {**GOOD, "parent": 0}})
    events = parse_headlines(["broken", "child"], llm, on_error="skip")
    assert len(events) == 1 and events[0].parent == -1


def test_bad_arguments() -> None:
    with pytest.raises(ValueError):
        parse_headlines(["a"], FakeLLM({}), on_error="ignore")
    with pytest.raises(TypeError):
        parse_headlines([42], FakeLLM({}))  # type: ignore[list-item]


# --------------------------------------------------------------------------- event study


def _synthetic_prices(
    n: int = 300, alpha: float = 0.0002, beta: float = 1.3, jump_at: int = 200, jump: float = -0.05
):
    rng = np.random.default_rng(0)
    rm = rng.normal(0.0003, 0.01, n - 1)
    rs = alpha + beta * rm
    rs[jump_at - 1] += jump  # return into price index `jump_at`
    market = 100 * np.exp(np.concatenate([[0], np.cumsum(rm)]))
    stock = 50 * np.exp(np.concatenate([[0], np.cumsum(rs)]))
    return stock, market


def test_event_study_recovers_exact_jump() -> None:
    stock, market = _synthetic_prices()
    es = event_study(stock, market, event_idx=200)
    assert es.car == pytest.approx(-0.05, abs=1e-10)
    assert es.alpha == pytest.approx(0.0002, abs=1e-10) and es.beta == pytest.approx(1.3, abs=1e-10)
    assert abnormal_return_impact(stock, market, 200) == pytest.approx(-0.05, abs=1e-10)
    # a window that misses the jump sees no abnormal return (estimation excludes the event day)
    assert abnormal_return_impact(stock, market, 200, event_window=(1, 3)) == pytest.approx(0.0, abs=1e-10)
    # a window that starts before the event day still catches it
    assert abnormal_return_impact(stock, market, 200, event_window=(-1, 1)) == pytest.approx(-0.05, abs=1e-10)


def test_event_study_with_noise() -> None:
    rng = np.random.default_rng(1)
    stock, market = _synthetic_prices()
    stock = stock * np.exp(rng.normal(0, 0.002, len(stock)))  # idiosyncratic noise
    es = event_study(stock, market, event_idx=200)
    assert es.car == pytest.approx(-0.05, abs=0.02)
    assert es.t_stat < -3 and math.isfinite(es.resid_sd)


def test_event_study_window_errors() -> None:
    stock, market = _synthetic_prices()
    with pytest.raises(ValueError):
        event_study(stock, market, event_idx=50, est_window=120)  # not enough history
    with pytest.raises(ValueError):
        event_study(stock, market, event_idx=298, event_window=(0, 5))  # runs past the data
    with pytest.raises(ValueError):
        event_study(stock, market, event_idx=200, event_window=(2, 0))
    with pytest.raises(ValueError):
        event_study(stock, market[:-1], event_idx=200)


def test_leakage_warning_documented() -> None:
    doc = abnormal_return_impact.__doc__ or ""
    assert "leakage" in doc.lower() and "calibration" in doc.lower()
