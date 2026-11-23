"""News events (HANDOFF §4 M1 `events.py`).

Only the `Event` record is implemented so far; it was pulled forward for the event parser
(issue #14). `EventQueue`, `load_events`, `hawkes_events`, `seed_agents` and broadcast
belong to issue #4.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Kinds from the user's design notes, plus `statement` (a company statement, such as a
# confirmation or denial, which the notes' kinds do not cover) and `price_move`, which the
# simulation creates itself when the price moves past `price_news_threshold` (HANDOFF §4 M4).
NEWS_KINDS = ("earnings", "macro", "regulatory", "product", "rumour", "leak", "statement")
KINDS = (*NEWS_KINDS, "price_move")
SEEDINGS = ("official", "outlet", "influencer", "insider", "anonymous")


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
