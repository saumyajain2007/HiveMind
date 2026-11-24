"""Built-in scenarios (HANDOFF §4 M4 demo, and the web Builder's presets, #20).

Ticks are absolute: day d (0-based) starts at d · 96; the market opens at tick 38 (09:30).
"""

from __future__ import annotations

from typing import Any

from .config import MARKET_OPEN_TICK, TICKS_PER_DAY
from .sim import Scenario

D = TICKS_PER_DAY

# HANDOFF: "day 1 an anonymous acquisition rumour (true_impact 0), day 3 a company denial
# (official, parent = rumour), plus one real earnings miss (true_impact −0.05)". Day 1 is the
# first simulated day; the earnings miss lands on day 4, before the open.
DEMO_EVENTS: list[dict[str, Any]] = [
    {
        "id": 0,
        "tick": MARKET_OPEN_TICK + 6,
        "kind": "rumour",
        "true_impact": 0.0,
        "sentiment": 0.8,
        "credibility": 0.2,
        "salience": 0.8,
        "complexity": 0.2,
        "seeding": "anonymous",
        "label": "Forum post: Acme in takeover talks",
    },
    {
        "id": 1,
        "tick": 2 * D + MARKET_OPEN_TICK + 2,
        "kind": "statement",
        "true_impact": 0.0,
        "sentiment": -0.6,
        "credibility": 0.95,
        "salience": 0.7,
        "complexity": 0.1,
        "seeding": "official",
        "parent": 0,
        "label": "Acme: 'no talks with any party'",
    },
    {
        "id": 2,
        "tick": 3 * D + MARKET_OPEN_TICK - 8,
        "kind": "earnings",
        "true_impact": -0.05,
        "sentiment": -0.7,
        "credibility": 0.95,
        "salience": 0.8,
        "complexity": 0.4,
        "seeding": "official",
        "label": "Q3 earnings miss",
    },
]

QUIET_EVENTS: list[dict[str, Any]] = []

MEME_EVENTS: list[dict[str, Any]] = [
    {
        "id": 0,
        "tick": MARKET_OPEN_TICK - 20,
        "kind": "rumour",
        "true_impact": 0.0,
        "sentiment": 1.0,
        "credibility": 0.3,
        "salience": 1.0,
        "complexity": 0.1,
        "seeding": "influencer",
        "label": "Influencer: 'shorts are trapped, to the moon'",
    },
    {
        "id": 1,
        "tick": D + MARKET_OPEN_TICK - 10,
        "kind": "rumour",
        "true_impact": 0.0,
        "sentiment": 0.9,
        "credibility": 0.25,
        "salience": 0.9,
        "complexity": 0.1,
        "seeding": "anonymous",
        "parent": 0,
        "label": "Forum: 'squeeze not squoze'",
    },
]

PRESETS: dict[str, list[dict[str, Any]]] = {
    "demo": DEMO_EVENTS,
    "quiet": QUIET_EVENTS,
    "meme": MEME_EVENTS,
}


def demo() -> Scenario:
    return Scenario.from_dicts(DEMO_EVENTS)


def preset(name: str) -> Scenario:
    return Scenario.from_dicts(PRESETS[name])
