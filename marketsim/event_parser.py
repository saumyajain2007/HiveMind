"""Offline LLM event parser and event-study labelling (issue #14, HANDOFF §2.7 and §4 M5).

Turns real-world headlines into `Event`s with a caller-supplied LLM:

    events = parse_headlines(headlines, llm=my_llm, cache_path="cache/events.json")

`llm` is any `Callable[[str], str]` that takes a prompt and returns the model's text. This
module never makes network calls. Use temperature 0 in the callable so that parsing is
repeatable; that setting is the caller's job, since only the caller knows the client.
Responses are cached on disk by a hash of the prompt, so a re-run never calls the LLM for a
headline it has already seen.

`abnormal_return_impact` labels the `true_impact` of historical events from prices
(market-model event study), for calibration only. See its docstring for the leakage warning.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

import numpy as np

from .config import TOPICS
from .events import NEWS_KINDS, SEEDINGS, Event

PROMPT_VERSION = "1"  # bump when PROMPT_TEMPLATE changes, so old cache entries are not reused
TRUE_IMPACT_LIMIT = 0.5  # |log change in fundamental value| accepted from a parse

EVENT_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "MarketEvent",
    "type": "object",
    "required": ["kind", "sentiment", "credibility", "salience", "complexity", "seeding", "true_impact"],
    "properties": {
        "kind": {"type": "string", "enum": list(NEWS_KINDS)},
        "sentiment": {
            "type": "number",
            "minimum": -1,
            "maximum": 1,
            "description": "How the news is presented",
        },
        "credibility": {"type": "number", "minimum": 0, "maximum": 1},
        "salience": {"type": "number", "minimum": 0, "maximum": 1, "description": "How attention-grabbing"},
        "complexity": {"type": "number", "minimum": 0, "maximum": 1, "description": "Expertise needed"},
        "seeding": {"type": "string", "enum": list(SEEDINGS)},
        "true_impact": {
            "type": "number",
            "minimum": -TRUE_IMPACT_LIMIT,
            "maximum": TRUE_IMPACT_LIMIT,
            "description": "Best estimate of the log change in fundamental value; 0 if unverified",
        },
        "topic": {"type": "string", "enum": list(TOPICS)},
        "parent": {
            "type": "integer",
            "minimum": -1,
            "description": "Index of an earlier headline in this batch that this one follows up, or -1",
        },
    },
    "additionalProperties": False,
}

FEW_SHOT: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        '"Acme Corp Q3 revenue misses estimates by 8%, cuts full-year guidance"',
        {"kind": "earnings", "sentiment": -0.7, "credibility": 0.95, "salience": 0.6, "complexity": 0.5,
         "seeding": "official", "true_impact": -0.06, "topic": "finance", "parent": -1},
    ),
    (
        '"Anonymous forum post claims Acme is in takeover talks with a rival"',
        {"kind": "rumour", "sentiment": 0.8, "credibility": 0.2, "salience": 0.7, "complexity": 0.2,
         "seeding": "anonymous", "true_impact": 0.0, "topic": "finance", "parent": -1},
    ),
    (
        "\"Acme denies takeover reports: 'no talks are taking place'\""
        "  (earlier headline 0 was the takeover rumour)",
        {"kind": "statement", "sentiment": -0.3, "credibility": 0.9, "salience": 0.5, "complexity": 0.2,
         "seeding": "official", "true_impact": 0.0, "topic": "finance", "parent": 0},
    ),
)  # fmt: skip

PROMPT_TEMPLATE = Template(
    """You convert one financial news headline into a structured market event for a simulator.

Return ONLY a JSON object that matches this JSON schema. No prose, no code fences.
$schema

Field guide:
- kind: earnings, macro, regulatory, product, rumour (unverified claim), leak (unofficial but specific),
  statement (a company statement that is none of the above, such as a confirmation or denial).
- sentiment: how the headline presents the news for the stock, -1 (very negative) to 1 (very positive).
- credibility: how trustworthy the source and claim are, 0 to 1.
- salience: how attention-grabbing it is for ordinary people, 0 to 1.
- complexity: how much financial knowledge is needed to interpret it correctly, 0 to 1.
- seeding: who releases it first: official (company or regulator), outlet (news media),
  influencer, insider, anonymous.
- true_impact: your best estimate of the log change in the company's fundamental value,
  between -$limit and $limit. Use 0 for rumours and anything unverified.
- topic: one of $topics.
- parent: if the headline confirms, denies or corrects an earlier headline listed below,
  that headline's index; otherwise -1.

Examples:
$examples

Earlier headlines in this batch:
$context

Headline: "$headline"
"""
)


class EventParseError(ValueError):
    """The LLM response could not be turned into a valid Event."""


# --------------------------------------------------------------------------- validation


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(max(x, lo), hi)


def _number(d: Mapping[str, Any], key: str) -> float:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise EventParseError(f"field {key!r} must be a finite number, got {v!r}")
    return float(v)


def validate_event(d: Mapping[str, Any], *, tick: int = 0, event_id: int = -1, ticker: int = 0) -> Event:
    """Build an `Event` from a parsed dict.

    Rejects missing fields, non-numeric values, and unknown kinds, seedings or topics.
    Clamps numeric fields into range (sentiment [-1, 1]; credibility, salience, complexity
    [0, 1]; true_impact ±TRUE_IMPACT_LIMIT). Unknown extra keys are ignored. `tick`,
    `event_id` and `ticker` come from the caller, not the LLM.
    """
    if not isinstance(d, Mapping):
        raise EventParseError(f"expected a JSON object, got {type(d).__name__}")
    for key in EVENT_JSON_SCHEMA["required"]:
        if key not in d:
            raise EventParseError(f"missing field {key!r}")
    kind, seeding = d["kind"], d["seeding"]
    if kind not in NEWS_KINDS:
        raise EventParseError(f"unknown kind {kind!r}; expected one of {NEWS_KINDS}")
    if seeding not in SEEDINGS:
        raise EventParseError(f"unknown seeding {seeding!r}; expected one of {SEEDINGS}")
    topic = d.get("topic", "finance")
    if topic not in TOPICS:
        raise EventParseError(f"unknown topic {topic!r}")
    parent = d.get("parent", -1)
    if isinstance(parent, bool) or not isinstance(parent, int):
        raise EventParseError(f"parent must be an integer, got {parent!r}")
    return Event(
        tick=int(tick),
        kind=str(kind),
        ticker=int(ticker),
        true_impact=_clamp(_number(d, "true_impact"), -TRUE_IMPACT_LIMIT, TRUE_IMPACT_LIMIT),
        sentiment=_clamp(_number(d, "sentiment"), -1.0, 1.0),
        credibility=_clamp(_number(d, "credibility"), 0.0, 1.0),
        salience=_clamp(_number(d, "salience"), 0.0, 1.0),
        complexity=_clamp(_number(d, "complexity"), 0.0, 1.0),
        seeding=str(seeding),
        parent=max(int(parent), -1),
        id=event_id,
        topic=str(topic),
    )


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> dict[str, Any]:
    """Parse the JSON object in an LLM response, tolerating code fences and surrounding text."""
    s = _FENCE.sub("", text.strip())
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise EventParseError(f"no JSON object in response: {text[:200]!r}")
    try:
        obj = json.loads(s[start : end + 1])
    except json.JSONDecodeError as e:
        raise EventParseError(f"invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise EventParseError("response JSON is not an object")
    return obj


# --------------------------------------------------------------------------- prompting + cache


def build_prompt(headline: str, context: Iterable[str] = ()) -> str:
    ctx = "\n".join(f"{i}: {h}" for i, h in enumerate(context)) or "(none)"
    return PROMPT_TEMPLATE.substitute(
        schema=json.dumps(EVENT_JSON_SCHEMA, indent=1),
        limit=TRUE_IMPACT_LIMIT,
        topics=", ".join(TOPICS),
        examples="\n\n".join(f"Headline: {h}\n{json.dumps(ans)}" for h, ans in FEW_SHOT),
        context=ctx,
        headline=headline.replace('"', "'"),
    )


def _cache_key(prompt: str) -> str:
    return hashlib.sha256(f"v{PROMPT_VERSION}\n{prompt}".encode()).hexdigest()


def _load_cache(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {str(k): str(v) for k, v in data.items()}


def _save_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1, sort_keys=True)
    os.replace(tmp, path)  # atomic, so an interrupted run never leaves a half-written cache


@dataclass
class Headline:
    text: str
    tick: int = 0


def parse_headlines(
    headlines: Iterable[str | Headline | Mapping[str, Any]],
    llm: Callable[[str], str],
    cache_path: str | Path | None = None,
    *,
    first_id: int = 0,
    ticker: int = 0,
    on_error: str = "raise",
) -> list[Event]:
    """Parse headlines in order into Events with ids `first_id, first_id + 1, ...`.

    Each headline is a string, a `Headline`, or a mapping with `text` and optional `tick`.
    Earlier headlines in the batch are shown to the LLM so a follow-up can name its
    `parent` by batch index; that index is mapped to the parent's event id. Raw responses are
    cached in `cache_path` (JSON, keyed by a hash of the prompt) and validated on every run.
    With `on_error="skip"`, headlines whose response fails validation are dropped; their
    children then get `parent = -1`.
    """
    if on_error not in ("raise", "skip"):
        raise ValueError("on_error must be 'raise' or 'skip'")
    path = Path(cache_path) if cache_path is not None else None
    cache = _load_cache(path)
    dirty = False
    items = [_as_headline(h) for h in headlines]
    events: list[Event] = []
    batch_to_id: dict[int, int] = {}
    next_id = first_id
    try:
        for i, h in enumerate(items):
            prompt = build_prompt(h.text, [x.text for x in items[:i]])
            key = _cache_key(prompt)
            if key not in cache:
                cache[key] = llm(prompt)
                dirty = True
            try:
                raw = extract_json(cache[key])
                parent_idx = raw.get("parent", -1)
                if isinstance(parent_idx, int) and not isinstance(parent_idx, bool) and parent_idx >= i:
                    raise EventParseError(f"parent {parent_idx} is not an earlier headline (index {i})")
                ev = validate_event(raw, tick=h.tick, event_id=next_id, ticker=ticker)
            except EventParseError as e:
                if on_error == "raise":
                    raise EventParseError(f"headline {i} ({h.text[:60]!r}): {e}") from e
                continue
            ev.parent = batch_to_id.get(ev.parent, -1) if ev.parent >= 0 else -1
            batch_to_id[i] = next_id
            next_id += 1
            events.append(ev)
    finally:
        if dirty and path is not None:
            _save_cache(path, cache)
    return events


def _as_headline(h: str | Headline | Mapping[str, Any]) -> Headline:
    if isinstance(h, Headline):
        return h
    if isinstance(h, str):
        return Headline(h)
    if isinstance(h, Mapping) and isinstance(h.get("text"), str):
        return Headline(h["text"], int(h.get("tick", 0)))
    raise TypeError(f"headline must be a str, Headline or mapping with 'text', got {h!r}")


# --------------------------------------------------------------------------- event study


@dataclass
class EventStudy:
    car: float  # cumulative abnormal log return over the event window
    alpha: float
    beta: float
    resid_sd: float  # residual sd in the estimation window (per period)
    t_stat: float  # car / (resid_sd * sqrt(window length))


def event_study(
    stock_px: np.ndarray,
    market_px: np.ndarray,
    event_idx: int,
    est_window: int = 120,
    event_window: tuple[int, int] = (0, 2),
) -> EventStudy:
    """Market-model event study on log returns. See `abnormal_return_impact`."""
    s = np.log(np.asarray(stock_px, np.float64))
    m = np.log(np.asarray(market_px, np.float64))
    if s.shape != m.shape or s.ndim != 1:
        raise ValueError("stock_px and market_px must be 1-D arrays of the same length")
    a, b = event_window
    if a > b:
        raise ValueError("event_window must be (start, end) with start <= end")
    rs, rm = np.diff(s), np.diff(m)  # rs[k] is the return from price k to price k + 1
    ev0, ev1 = event_idx + a - 1, event_idx + b - 1  # return indices covering the event window
    # The estimation window ends before both the event day and the event window, so the
    # event's own return never contaminates alpha and beta.
    est1 = min(ev0, event_idx - 1)
    est0 = est1 - est_window
    if est0 < 0 or ev0 < 0 or ev1 >= len(rs):
        raise ValueError("not enough data around the event for these windows")
    x, y = rm[est0:est1], rs[est0:est1]
    xm, ym = x.mean(), y.mean()
    vx = ((x - xm) ** 2).sum()
    beta = float(((x - xm) * (y - ym)).sum() / vx) if vx > 0 else 0.0
    alpha = float(ym - beta * xm)
    resid = y - (alpha + beta * x)
    dof = max(len(y) - 2, 1)
    resid_sd = float(np.sqrt((resid**2).sum() / dof))
    ar = rs[ev0 : ev1 + 1] - (alpha + beta * rm[ev0 : ev1 + 1])
    car = float(ar.sum())
    denom = resid_sd * math.sqrt(len(ar))
    return EventStudy(car, alpha, beta, resid_sd, car / denom if denom > 0 else math.inf)


def abnormal_return_impact(
    stock_px: np.ndarray,
    market_px: np.ndarray,
    event_idx: int,
    est_window: int = 120,
    event_window: tuple[int, int] = (0, 2),
) -> float:
    """Cumulative abnormal log return (market model) around a historical event.

    Prices are daily closes, aligned; `event_idx` is the index of the event day's close. The
    market model r_stock = α + β·r_market is fitted by OLS on the `est_window` returns before
    the event day (and before the event window, if it starts earlier), and the abnormal
    returns are summed over days `event_idx + event_window[0] .. event_idx + event_window[1]` (inclusive).

    .. warning:: **Calibration only: lookahead leakage.**
       The result uses prices *after* the event. Use it only to label `true_impact` on
       historical events for calibration (issue #12) and for scoring. Never feed it into a
       forecast made at or before the event (backtests, live runs, or as an LLM hint): that
       leaks the outcome into the prediction and makes the backtest look better than it is.
    """
    return event_study(stock_px, market_px, event_idx, est_window, event_window).car
