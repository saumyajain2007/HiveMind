"""News events: the record, a queue, a JSON loader, synthetic shocks, seeding (issue #4).

HANDOFF §4 M1 `events.py`.

* `Event`: exactly the user's fields (docs/design_notes.txt) plus `id` and `topic`.
* `EventQueue`: events ordered by tick; `pop_due(tick)` returns everything due.
* `load_events(path)`: strict JSON loader (raises on bad input rather than clamping).
* `hawkes_events(...)`: discrete-time self-exciting arrivals with randomised attributes.
* `seed_agents(event, pop, rng)`: who hears an event first, by seeding type.
* `broadcast_hits(...)`: TV / push-alert reach on an item's first tick.
* `apply_to_market(event, market)`: a real event moves the hidden value V_true.
"""

from __future__ import annotations

import heapq
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from .config import MEDIA, NON_INVESTOR, TOPICS

if TYPE_CHECKING:
    from .market import MarketState

# Kinds from the user's design notes, plus `statement` (a company statement, such as a
# confirmation or denial, which the notes' kinds do not cover) and `price_move`, which the
# simulation creates itself when the price moves past `price_news_threshold` (HANDOFF §4 M4).
NEWS_KINDS = ("earnings", "macro", "regulatory", "product", "rumour", "leak", "statement")
KINDS = (*NEWS_KINDS, "price_move")
SEEDINGS = ("official", "outlet", "influencer", "insider", "anonymous")
# Kinds whose items can be adopted as narratives and mutated (HANDOFF §4 M2).
NARRATIVE_KINDS = ("rumour", "leak")


@dataclass
class Event:
    """Exactly the user's fields (docs/design_notes.txt), plus `id` and `topic`."""

    tick: int
    kind: str  # earnings, macro, regulatory, product, rumour, leak, statement (+ price_move, internal)
    ticker: int  # sector / ticker index; v1 simulates one ticker (0)
    true_impact: float  # log change in fundamental value; hidden from agents (0 for a false rumour)
    sentiment: float  # how it's presented, -1..1
    credibility: float  # trustworthiness, 0..1
    salience: float  # how attention-grabbing it is, 0..1
    complexity: float  # knowledge needed to interpret it correctly, 0..1
    seeding: str  # official, outlet, influencer, insider, anonymous
    parent: int = -1  # for follow-ups: confirmations, denials, corrections
    id: int = -1
    topic: str = "finance"

    @property
    def is_real(self) -> bool:
        """A real event moves the hidden fundamental value."""
        return self.true_impact != 0.0

    @property
    def is_narrative(self) -> bool:
        return self.kind in NARRATIVE_KINDS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- validation + loading

_RANGES = {
    "sentiment": (-1.0, 1.0),
    "credibility": (0.0, 1.0),
    "salience": (0.0, 1.0),
    "complexity": (0.0, 1.0),
    "true_impact": (-1.0, 1.0),
}
_REQUIRED = ("tick", "kind", "sentiment", "credibility", "salience", "complexity", "seeding")
_ALLOWED = set(Event.__dataclass_fields__)


def event_from_dict(d: Mapping[str, Any], *, allow_internal: bool = False) -> Event:
    """Strictly validate one event mapping. Raises ValueError on any problem (no clamping)."""
    if not isinstance(d, Mapping):
        raise ValueError(f"event must be an object, got {type(d).__name__}")
    unknown = set(d) - _ALLOWED - {"label"}
    if unknown:
        raise ValueError(f"unknown event fields {sorted(unknown)}")
    missing = [k for k in _REQUIRED if k not in d]
    if missing:
        raise ValueError(f"missing event fields {missing}")
    kinds = KINDS if allow_internal else NEWS_KINDS
    if d["kind"] not in kinds:
        raise ValueError(f"unknown kind {d['kind']!r}; expected one of {kinds}")
    if d["seeding"] not in SEEDINGS:
        raise ValueError(f"unknown seeding {d['seeding']!r}; expected one of {SEEDINGS}")
    topic = d.get("topic", "finance")
    if topic not in TOPICS:
        raise ValueError(f"unknown topic {topic!r}")
    for key in ("tick", "ticker", "parent", "id"):
        if key in d and (isinstance(d[key], bool) or not isinstance(d[key], int)):
            raise ValueError(f"{key} must be an integer")
    if d["tick"] < 0:
        raise ValueError("tick must be >= 0")
    values: dict[str, float] = {}
    for key, (lo, hi) in _RANGES.items():
        v = d.get(key, 0.0)
        if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
            raise ValueError(f"{key} must be a finite number")
        if not lo <= v <= hi:
            raise ValueError(f"{key}={v} outside [{lo}, {hi}]")
        values[key] = float(v)
    return Event(
        tick=d["tick"],
        kind=d["kind"],
        ticker=d.get("ticker", 0),
        seeding=d["seeding"],
        parent=d.get("parent", -1),
        id=d.get("id", -1),
        topic=topic,
        **values,
    )


def load_events(path: str | Path) -> list[Event]:
    """Load events from JSON: a list of event objects, or {"events": [...]}.

    Ids are assigned in file order where missing; parents must refer to an earlier-or-equal tick.
    """
    with Path(path).open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, Mapping):
        data = data.get("events")
    if not isinstance(data, list):
        raise ValueError("expected a JSON list of events or an object with an 'events' list")
    events = [event_from_dict(d) for d in data]
    assign_ids(events)
    by_id = {e.id: e for e in events}
    for e in events:
        if e.parent >= 0:
            p = by_id.get(e.parent)
            if p is None or p.tick > e.tick or p.id == e.id:
                raise ValueError(f"event {e.id}: parent {e.parent} must exist and come earlier")
    return events


def assign_ids(events: Iterable[Event], start: int = 0) -> None:
    """Give every event with id -1 a fresh id, above the largest existing one; checks uniqueness."""
    events = list(events)
    nxt = max([start - 1, *(e.id for e in events)]) + 1
    for e in events:
        if e.id < 0:
            e.id = nxt
            nxt += 1
    ids = [e.id for e in events]
    if len(set(ids)) != len(ids):
        raise ValueError("event ids must be unique")


# --------------------------------------------------------------------------- queue


class EventQueue:
    """Min-heap of events by (tick, id). Deterministic order for equal ticks."""

    def __init__(self, events: Iterable[Event] = ()) -> None:
        self._heap: list[tuple[int, int, int, Event]] = []
        self._seq = 0
        self._next_id = 0
        for e in events:
            self.push(e)

    def push(self, event: Event) -> Event:
        if event.id < 0:
            event.id = self._next_id
        self._next_id = max(self._next_id, event.id + 1)
        heapq.heappush(self._heap, (event.tick, event.id, self._seq, event))
        self._seq += 1
        return event

    def pop_due(self, tick: int) -> list[Event]:
        """All events with `event.tick <= tick`, in (tick, id) order."""
        out = []
        while self._heap and self._heap[0][0] <= tick:
            out.append(heapq.heappop(self._heap)[3])
        return out

    def peek_tick(self) -> int | None:
        return self._heap[0][0] if self._heap else None

    def next_id(self) -> int:
        return self._next_id

    def __len__(self) -> int:
        return len(self._heap)


# --------------------------------------------------------------------------- synthetic shocks


def hawkes_intensity(counts: np.ndarray, mu: float, alpha: float, beta: float) -> np.ndarray:
    """λ_t = mu + alpha · Σ_{s<t} e^{-beta (t-s)} · N_s  (per-tick expected arrivals)."""
    lam = np.empty(len(counts))
    excite = 0.0
    decay = math.exp(-beta)
    for t, n in enumerate(counts):
        lam[t] = mu + alpha * excite
        excite = (excite + n) * decay
    return lam


# (kind, weight, seeding choices, credibility range, real?) for synthetic events
_SYNTH_KINDS: tuple[tuple[str, float, tuple[str, ...], tuple[float, float], bool], ...] = (
    ("rumour", 0.35, ("anonymous", "influencer"), (0.1, 0.4), False),
    ("leak", 0.10, ("insider",), (0.4, 0.7), True),
    ("macro", 0.15, ("outlet",), (0.7, 0.95), True),
    ("product", 0.15, ("official", "outlet"), (0.7, 0.95), True),
    ("regulatory", 0.10, ("official", "outlet"), (0.75, 0.95), True),
    ("earnings", 0.10, ("official",), (0.85, 1.0), True),
    ("statement", 0.05, ("official",), (0.8, 1.0), False),
)


def hawkes_events(
    mu: float,
    alpha: float,
    beta: float,
    n_ticks: int,
    rng: np.random.Generator,
    *,
    start_id: int = 0,
    impact_sd: float = 0.02,
) -> list[Event]:
    """Self-exciting synthetic shocks: N_t ~ Poisson(λ_t), λ from `hawkes_intensity`.

    Each arrival raises the intensity of later ticks by alpha·e^{-beta·k} (k >= 1), so the
    branching ratio is alpha·e^{-beta} / (1 - e^{-beta}); the process is stationary when it is
    below 1, with mean rate mu / (1 - ratio). Attributes are drawn per
    kind: rumours are anonymous or influencer-seeded with low credibility and no true impact;
    real kinds get true_impact ~ N(0, impact_sd) with sentiment leaning the same way.
    """
    if mu < 0 or alpha < 0 or beta <= 0:
        raise ValueError("need mu >= 0, alpha >= 0, beta > 0")
    weights = np.array([k[1] for k in _SYNTH_KINDS])
    weights = weights / weights.sum()
    events: list[Event] = []
    excite = 0.0
    decay = math.exp(-beta)
    next_id = start_id
    for t in range(n_ticks):
        lam = mu + alpha * excite
        n = int(rng.poisson(lam))
        for _ in range(n):
            kind, _, seedings, (c_lo, c_hi), real = _SYNTH_KINDS[
                int(rng.choice(len(_SYNTH_KINDS), p=weights))
            ]
            impact = float(np.clip(rng.normal(0.0, impact_sd), -0.3, 0.3)) if real else 0.0
            lean = math.tanh(impact / max(impact_sd, 1e-9)) if real else float(rng.uniform(-1, 1))
            sentiment = float(np.clip(0.7 * lean + rng.normal(0.0, 0.25), -1.0, 1.0))
            events.append(
                Event(
                    tick=t,
                    kind=kind,
                    ticker=0,
                    true_impact=impact,
                    sentiment=sentiment,
                    credibility=float(rng.uniform(c_lo, c_hi)),
                    salience=float(rng.beta(2.0, 3.0)),
                    complexity=float(rng.beta(2.0, 2.0)),
                    seeding=str(rng.choice(seedings)),
                    id=next_id,
                    topic="finance",
                )
            )
            next_id += 1
        excite = (excite + n) * decay
    return events


# --------------------------------------------------------------------------- seeding + broadcast


class SeedPopulation(Protocol):
    """Population fields used for seeding and broadcast."""

    @property
    def n(self) -> int: ...

    category: np.ndarray
    knowledge: np.ndarray
    influence: np.ndarray
    media_attention: np.ndarray


OFFICIAL_INVESTOR_SHARE = 0.005  # top-knowledge investors who read official releases directly
INFLUENCER_TOP_SHARE = 0.001
INSIDER_COUNT = 5
INSIDER_TOP_SHARE = 0.10  # insiders are drawn from the best-connected 10% of investors


def seed_agents(
    event: Event,
    pop: SeedPopulation,
    rng: np.random.Generator,
    connectedness: np.ndarray | None = None,
) -> np.ndarray:
    """Agents who know an event first (HANDOFF §4 M1). Returns sorted unique int64 ids.

    * official: all media outlets + the top 0.5% of investors by knowledge (at least one)
    * outlet: 3-10 random media outlets (all of them if fewer exist)
    * influencer: one random person from the top 0.1% by influence (media excluded)
    * insider: ~5 investors from the best-connected 10% (`connectedness`, e.g. total graph
      degree; falls back to influence)
    * anonymous: one random person with below-median influence

    Funds and prop firms also learn official events at once; firms (#9) read the event itself.
    """
    category = np.asarray(pop.category)
    media = np.flatnonzero(category == MEDIA)
    people = np.flatnonzero(category != MEDIA)
    investors = np.flatnonzero((category != NON_INVESTOR) & (category != MEDIA))
    influence = np.asarray(pop.influence, np.float64)

    def top(ids: np.ndarray, score: np.ndarray, share: float) -> np.ndarray:
        k = max(1, math.ceil(share * len(ids)))
        return ids[np.argsort(-score[ids], kind="stable")[:k]]

    s = event.seeding
    if s == "official":
        pool = investors if len(investors) else people
        out = np.concatenate([media, top(pool, np.asarray(pop.knowledge), OFFICIAL_INVESTOR_SHARE)])
    elif s == "outlet":
        if len(media) == 0:
            out = top(people, influence, INFLUENCER_TOP_SHARE)
        else:
            k = min(len(media), int(rng.integers(3, 11)))
            out = rng.choice(media, size=k, replace=False)
    elif s == "influencer":
        out = rng.choice(top(people, influence, INFLUENCER_TOP_SHARE), size=1)
    elif s == "insider":
        pool = investors if len(investors) else people
        score = np.asarray(connectedness if connectedness is not None else influence, np.float64)
        candidates = top(pool, score, INSIDER_TOP_SHARE)
        out = rng.choice(candidates, size=min(INSIDER_COUNT, len(candidates)), replace=False)
    elif s == "anonymous":
        low = people[influence[people] <= np.median(influence[people])]
        out = rng.choice(low if len(low) else people, size=1)
    else:
        raise ValueError(f"unknown seeding {s!r}")
    return np.unique(np.asarray(out, np.int64))


def broadcast_hits(
    salience: float, media_attention: np.ndarray, rate: float, rng: np.random.Generator
) -> np.ndarray:
    """Agents reached by TV / push alerts on an item's first tick.

    Each agent is hit with probability salience · media_attention · rate. Returns int64 ids.
    """
    p = np.clip(salience * np.asarray(media_attention, np.float64) * rate, 0.0, 1.0)
    return np.flatnonzero(rng.random(len(p)) < p).astype(np.int64)


def apply_to_market(event: Event, market: MarketState) -> None:
    """A real event moves the hidden fundamental value at injection: V_true *= exp(true_impact)."""
    if event.true_impact != 0.0:
        market.apply_fundamental_shock(event.true_impact)
